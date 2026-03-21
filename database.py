"""
database.py - Database operations for Ethiopian Job Aggregator
FINAL VERSION with:
  - Fast startup (no unnecessary index drops)
  - Auto-reconnect for Neon serverless
  - created_at = NOW() on updates (jobs appear at top)
  - Clean error handling
  - job_exists() for duplicate detection on listing pages
  - Drops bad telegram_id unique constraint (breaks listing pages)
"""

import os
import re
import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    logger.warning("psycopg2 not installed. Run: pip install psycopg2-binary")

# Deadline text parsing: try many formats for exact date matching
MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]
MONTH_ABBREV = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DEADLINE_DATE_FORMATS = [
    "%B %d, %Y",   # February 18, 2026
    "%b %d, %Y",   # Feb 18, 2026
    "%d %B %Y",    # 18 February 2026
    "%d %b %Y",    # 18 Feb 2026
    "%Y-%m-%d",    # 2026-02-18
    "%d/%m/%Y",    # 18/02/2026
    "%m/%d/%Y",    # 02/18/2026
    "%d-%m-%Y",    # 18-02-2026
    "%d.%m.%Y",    # 18.02.2026
    "%B %d %Y",    # February 18 2026
    "%b %d %Y",    # Feb 18 2026
    "%d %b %y",    # 18 Feb 26
    "%d/%m/%y",    # 18/02/26
]


def parse_deadline_date(text: Optional[str]) -> Optional[date]:
    """Parse deadline_text into a date. Tries multiple formats and regex. Returns None if unparseable."""
    if not text or not str(text).strip():
        return None
    text = str(text).strip()
    # Try full string first
    for fmt in DEADLINE_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    # Try to find a date-like substring (e.g. "Deadline: March 11, 2026" or "before Feb 18")
    months = "|".join(MONTH_NAMES + MONTH_ABBREV)
    patterns = [
        re.compile(rf"(?:{months})\s+\d{{1,2}}\s*,?\s*\d{{4}}", re.IGNORECASE),
        re.compile(r"\d{4}-\d{2}-\d{2}"),
        re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}"),
        re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}"),
        re.compile(r"\d{1,2}-\d{1,2}-\d{2,4}"),
    ]
    for pat in patterns:
        for m in pat.finditer(text):
            chunk = m.group(0).strip()
            for f in DEADLINE_DATE_FORMATS:
                try:
                    return datetime.strptime(chunk, f).date()
                except ValueError:
                    pass
                try:
                    return datetime.strptime(chunk.replace(",", " "), f.replace(",", " ").replace("  ", " ")).date()
                except ValueError:
                    pass
    return None


# Category slug -> keywords for accurate filtering (avoids "it" matching "credit", "deposit", etc.)
CATEGORY_KEYWORDS = {
    "it": [
        "software", "developer", "programming", "information technology",
        " IT ", "IT ", " tech ", "computer science", "data science", "web developer",
        "software engineer", "programmer", "full stack", "frontend", "backend",
        "system administrator", "network", "database", "ICT", "IT officer",
        "IT manager", "IT specialist", "IT department",
    ],
    "fresh_graduate": [
        "fresh graduate", "graduate", "entry level", "no experience",
        "0 year", "zero experience", "recent graduate", "first job",
    ],
    "finance": [
        "finance", "accountant", "accounting", "CFA", "financial analyst",
        "audit", "financial ", "treasury", "controller", "finance officer",
    ],
    "banking": [
        "bank", "banking", "teller", "loan officer", "branch manager",
        "commercial bank", "bank officer", "credit officer",
    ],
    "ngo": [
        "NGO", "non-profit", "nonprofit", "non profit", "development sector",
        "humanitarian", "civil society", "INGO", "charity",
    ],
}


def _category_condition(category: str) -> tuple:
    """Returns (SQL fragment, params list) for category filter, or (None, []) if unknown."""
    keywords = CATEGORY_KEYWORDS.get((category or "").strip().lower())
    if not keywords:
        return None, []
    # (title ILIKE %s OR description ILIKE %s) OR (title ILIKE %s OR description ILIKE %s) OR ...
    frags = []
    params = []
    for kw in keywords:
        frags.append("(title ILIKE %s OR description ILIKE %s)")
        term = f"%{kw}%"
        params.extend([term, term])
    return "(" + " OR ".join(frags) + ")", params


def _is_job_expired(job: Dict[str, Any]) -> bool:
    """True if job has a parseable deadline that is in the past."""
    dl = job.get("deadline") or job.get("deadline_text")
    d = parse_deadline_date(dl)
    return d is not None and d < date.today()


def _jobs_base_where(
    search: Optional[str] = None,
    category: Optional[str] = None,
    location: Optional[str] = None,
) -> tuple:
    """Shared WHERE conditions and params for get_jobs and get_job_count (no expiring). Returns (conditions_list, params_list)."""
    conditions = ["1=1"]
    params = []
    if search:
        conditions.append(
            "(title ILIKE %s OR company ILIKE %s OR description ILIKE %s)"
        )
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term])
    cat_slug = (category or "").strip().lower() if isinstance(category, str) else ""
    if cat_slug:
        cat_sql, cat_params = _category_condition(cat_slug)
        if cat_sql:
            conditions.append(cat_sql)
            params.extend(cat_params)
    if location:
        conditions.append("location ILIKE %s")
        params.append(f"%{location}%")
    return conditions, params


class Database:
    """PostgreSQL database handler with auto-reconnect for Neon serverless"""

    def __init__(self):
        self.connection_string = os.getenv('DATABASE_URL')
        self.conn = None

        if not self.connection_string:
            logger.warning("DATABASE_URL not set in .env file")

    def initialize(self):
        """Connect and ensure tables exist"""
        self.connect()
        self._ensure_tables()
        self._ensure_schema()

    def connect(self):
        """Establish database connection"""
        if not PSYCOPG2_AVAILABLE:
            raise ImportError("psycopg2 is required")

        if not self.connection_string:
            raise ValueError("DATABASE_URL not set")

        try:
            if self.conn:
                try:
                    self.conn.close()
                except Exception:
                    pass

            self.conn = psycopg2.connect(self.connection_string)
            self.conn.autocommit = False
            logger.info("Database connected")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def _ensure_connection(self):
        """
        Check if connection is alive, reconnect if needed.
        Neon serverless PostgreSQL closes idle connections aggressively.
        """
        try:
            if self.conn is None or self.conn.closed:
                logger.info("Connection closed, reconnecting...")
                self.connect()
                return

            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
        except Exception:
            logger.info("Connection stale, reconnecting...")
            try:
                self.connect()
            except Exception as e:
                logger.error(f"Reconnection failed: {e}")
                raise

    def _ensure_tables(self):
        """Create the jobs table if it doesn't exist"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS jobs (
                        id              SERIAL PRIMARY KEY,
                        telegram_id     VARCHAR(100),
                        telegram_channel VARCHAR(100),
                        telegram_date   TIMESTAMP,
                        title           VARCHAR(500),
                        company         VARCHAR(500),
                        location        VARCHAR(255),
                        description     TEXT,
                        source_url      TEXT,
                        apply_url       TEXT,
                        apply_email     VARCHAR(500),
                        apply_type      VARCHAR(50),
                        deadline_text   VARCHAR(255),
                        salary          VARCHAR(255),
                        scraped_data    JSONB DEFAULT '{}',
                        raw_text        TEXT,
                        channel_username VARCHAR(100),
                        telegram_text   TEXT,
                        created_at      TIMESTAMP DEFAULT NOW(),
                        updated_at      TIMESTAMP DEFAULT NOW()
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS apply_clicks (
                        id          SERIAL PRIMARY KEY,
                        job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                        click_type  VARCHAR(20) DEFAULT 'link',
                        clicked_at   TIMESTAMP DEFAULT NOW()
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS job_views (
                        id          SERIAL PRIMARY KEY,
                        job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                        viewed_at   TIMESTAMP DEFAULT NOW()
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS job_alerts (
                        id           SERIAL PRIMARY KEY,
                        email        VARCHAR(255) NOT NULL,
                        keywords     VARCHAR(500),
                        location     VARCHAR(255),
                        frequency    VARCHAR(20) DEFAULT 'daily',
                        confirmed    BOOLEAN DEFAULT FALSE,
                        confirm_token VARCHAR(64) UNIQUE,
                        created_at   TIMESTAMP DEFAULT NOW(),
                        last_sent_at TIMESTAMP
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS telegram_posted_jobs (
                        job_id    INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                        channel   VARCHAR(100) NOT NULL,
                        posted_at TIMESTAMP DEFAULT NOW(),
                        PRIMARY KEY (job_id, channel)
                    );
                """)
            self.conn.commit()
            logger.info("Tables verified")
        except Exception as e:
            logger.error(f"Table creation error: {e}")
            self.conn.rollback()

    def _ensure_schema(self):
        """Ensure required columns and indexes exist - FAST version.
        Only creates missing columns and indexes, never drops existing ones.
        ALSO: drops the bad telegram_id unique constraint that breaks listing pages."""
        try:
            with self.conn.cursor() as cur:
                # ════════════════════════════════════════════════════════
                # FIX: Drop the telegram_id unique constraint if it exists
                # This constraint breaks listing pages where 20 different
                # jobs all come from the same Telegram message (same telegram_id)
                # ════════════════════════════════════════════════════════
                cur.execute("""
                    SELECT constraint_name
                    FROM information_schema.table_constraints
                    WHERE table_name = 'jobs'
                      AND constraint_type = 'UNIQUE'
                      AND constraint_name LIKE '%telegram_id%'
                """)
                bad_constraints = cur.fetchall()
                for row in bad_constraints:
                    constraint_name = row[0]
                    # Don't drop our composite index (telegram_id + channel)
                    if constraint_name == 'idx_jobs_telegram_unique':
                        continue
                    try:
                        cur.execute(
                            f"ALTER TABLE jobs DROP CONSTRAINT {constraint_name};"
                        )
                        logger.info(
                            f"Dropped bad unique constraint: {constraint_name} "
                            f"(was blocking listing page saves)"
                        )
                    except Exception as e:
                        logger.warning(f"Could not drop constraint {constraint_name}: {e}")
                        self.conn.rollback()

                # Also check for unique INDEX on just telegram_id
                cur.execute("""
                    SELECT indexname FROM pg_indexes
                    WHERE tablename = 'jobs'
                      AND indexdef LIKE '%UNIQUE%'
                      AND indexname LIKE '%telegram_id%'
                      AND indexname != 'idx_jobs_telegram_unique'
                """)
                bad_indexes = cur.fetchall()
                for row in bad_indexes:
                    idx_name = row[0]
                    try:
                        cur.execute(f"DROP INDEX IF EXISTS {idx_name};")
                        logger.info(
                            f"Dropped bad unique index: {idx_name}"
                        )
                    except Exception as e:
                        logger.warning(f"Could not drop index {idx_name}: {e}")
                        self.conn.rollback()

                # Check existing columns
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'jobs';
                """)
                existing = {row[0] for row in cur.fetchall()}

                # Only add missing columns
                required_columns = [
                    ('telegram_channel', 'VARCHAR(100)'),
                    ('telegram_date', 'TIMESTAMP'),
                    ('apply_type', 'VARCHAR(50)'),
                    ('raw_text', 'TEXT'),
                    ('channel_username', 'VARCHAR(100)'),
                    ('telegram_text', 'TEXT'),
                    ('updated_at', 'TIMESTAMP DEFAULT NOW()'),
                ]

                for col_name, col_type in required_columns:
                    base_name = col_name.split()[0]
                    if base_name not in existing:
                        try:
                            cur.execute(
                                f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type};"
                            )
                            logger.info(f"Added column: {col_name}")
                        except Exception:
                            self.conn.rollback()

                # Check existing indexes — only create if missing
                cur.execute("""
                    SELECT indexname FROM pg_indexes
                    WHERE tablename = 'jobs';
                """)
                existing_indexes = {row[0] for row in cur.fetchall()}

                if 'idx_jobs_source_url_unique' not in existing_indexes:
                    try:
                        cur.execute("""
                            CREATE UNIQUE INDEX idx_jobs_source_url_unique
                            ON jobs (source_url)
                            WHERE source_url IS NOT NULL AND source_url != '';
                        """)
                        logger.info("Created index: idx_jobs_source_url_unique")
                    except Exception:
                        self.conn.rollback()

                if 'idx_jobs_telegram_unique' not in existing_indexes:
                    try:
                        cur.execute("""
                            CREATE UNIQUE INDEX idx_jobs_telegram_unique
                            ON jobs (telegram_id, telegram_channel)
                            WHERE telegram_id IS NOT NULL
                              AND telegram_channel IS NOT NULL
                              AND (source_url IS NULL OR source_url = '');
                        """)
                        logger.info("Created index: idx_jobs_telegram_unique")
                    except Exception:
                        self.conn.rollback()

                if 'idx_jobs_created_at' not in existing_indexes:
                    try:
                        cur.execute("""
                            CREATE INDEX idx_jobs_created_at
                            ON jobs (created_at DESC);
                        """)
                        logger.info("Created index: idx_jobs_created_at")
                    except Exception:
                        self.conn.rollback()

            self.conn.commit()
            logger.info("Database schema ready")

        except Exception as e:
            logger.error(f"Schema error: {e}")
            try:
                self.conn.rollback()
            except Exception:
                self.connect()

    # ================================================================
    # JOB EXISTS CHECK
    # ================================================================

    def job_exists(self, url: str) -> bool:
        """
        Check if a job with this source_url already exists in the database.
        Used by process_listing_page() to skip already-scraped jobs.
        """
        if not url or not url.strip():
            return False

        self._ensure_connection()

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM jobs WHERE source_url = %s LIMIT 1",
                    (url,)
                )
                exists = cur.fetchone() is not None
            return exists
        except Exception as e:
            logger.error(f"job_exists check failed for {url}: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return False

    def get_job_by_source_url(self, source_url: str) -> Optional[Dict[str, Any]]:
        """Get one job row by source_url (for refresh/update). Returns dict with id, telegram_id, telegram_channel, etc."""
        if not source_url or not source_url.strip():
            return None
        self._ensure_connection()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, source_url, telegram_id, telegram_channel, telegram_date, raw_text,
                              title, company, location, description, deadline_text, salary,
                              apply_url, apply_email, apply_type, scraped_data
                       FROM jobs WHERE source_url = %s LIMIT 1""",
                    (source_url.strip(),)
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_job_by_source_url failed: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return None

    def exists_job_with_telegram_id(self, telegram_id) -> bool:
        """Return True if any job exists with this telegram_id (used to skip already-processed messages when polling)."""
        if telegram_id is None:
            return False
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM jobs WHERE telegram_id = %s LIMIT 1",
                    (str(telegram_id),)
                )
                return cur.fetchone() is not None
        except Exception as e:
            logger.debug("exists_job_with_telegram_id failed: %s", e)
            try:
                self.conn.rollback()
            except Exception:
                pass
            return False

    def get_source_urls_like(self, pattern: str) -> List[str]:
        """Return list of source_urls where source_url LIKE pattern (e.g. %%ethiojobs.net%%)."""
        if not pattern or "%" not in pattern:
            return []
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT source_url FROM jobs WHERE source_url IS NOT NULL AND source_url LIKE %s",
                    (pattern,)
                )
                return [row[0] for row in cur.fetchall() if row[0]]
        except Exception as e:
            logger.error(f"get_source_urls_like failed: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return []

    # ================================================================
    # SAVE / UPSERT
    # ================================================================

    def save_job(self, job_data: Dict[str, Any]) -> Optional[int]:
        """
        Save or update a job.
        Uses source_url for dedupe when set, else (telegram_id, telegram_channel).
        Auto-reconnects if connection is lost.
        """
        self._ensure_connection()

        source_url = job_data.get('source_url') or None
        if isinstance(source_url, str) and source_url.strip() == '':
            source_url = None

        params = {
            'telegram_id': str(job_data.get('telegram_id', '')),
            'telegram_channel': job_data.get('telegram_channel'),
            'telegram_date': job_data.get('telegram_date'),
            'title': job_data.get('title'),
            'company': job_data.get('company'),
            'location': job_data.get('location'),
            'description': job_data.get('description'),
            'source_url': source_url,
            'apply_url': job_data.get('apply_url'),
            'apply_email': job_data.get('apply_email'),
            'apply_type': job_data.get('apply_type'),
            'deadline': job_data.get('deadline'),
            'salary': job_data.get('salary'),
            'scraped_data': Json(job_data.get('scraped_data', {})),
            'raw_text': job_data.get('raw_text'),
        }

        try:
            if source_url:
                result = self._upsert_by_url(params)
            else:
                result = self._upsert_by_telegram(params)

            if result:
                logger.info(f"Job saved: #{result}")
            return result

        except Exception as e:
            logger.error(f"Failed to save job: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return self._simple_insert(job_data)

    def _upsert_by_url(self, params: Dict) -> Optional[int]:
        """
        Insert or update job, deduplicating by source_url.
        CRITICAL: When updating, bumps BOTH created_at AND updated_at
        so re-posted jobs appear at the top of the website.
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM jobs WHERE source_url = %s",
                    (params['source_url'],)
                )
                existing = cur.fetchone()

                if existing:
                    cur.execute("""
                        UPDATE jobs SET
                            title = COALESCE(%s, title),
                            company = COALESCE(%s, company),
                            location = COALESCE(%s, location),
                            description = COALESCE(%s, description),
                            apply_url = COALESCE(%s, apply_url),
                            apply_email = COALESCE(%s, apply_email),
                            apply_type = COALESCE(%s, apply_type),
                            deadline_text = COALESCE(%s, deadline_text),
                            salary = COALESCE(%s, salary),
                            scraped_data = %s,
                            telegram_id = %s,
                            telegram_channel = %s,
                            telegram_date = COALESCE(%s, telegram_date),
                            raw_text = COALESCE(%s, raw_text),
                            channel_username = %s,
                            telegram_text = %s,
                            created_at = NOW(),
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                    """, (
                        params['title'], params['company'],
                        params['location'], params['description'],
                        params['apply_url'], params['apply_email'],
                        params['apply_type'], params['deadline'],
                        params['salary'], params['scraped_data'],
                        params['telegram_id'], params['telegram_channel'],
                        params['telegram_date'], params['raw_text'],
                        params['telegram_channel'], params['raw_text'],
                        existing[0],
                    ))
                    result = cur.fetchone()
                    self.conn.commit()
                    logger.info(f"Updated job #{existing[0]} (bumped to top)")
                    return result[0] if result else existing[0]
                else:
                    cur.execute("""
                        INSERT INTO jobs (
                            telegram_id, telegram_channel, telegram_date,
                            title, company, location, description,
                            source_url, apply_url, apply_email, apply_type,
                            deadline_text, salary, scraped_data, raw_text,
                            channel_username, telegram_text,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, NOW(), NOW()
                        )
                        RETURNING id
                    """, (
                        params['telegram_id'], params['telegram_channel'],
                        params['telegram_date'], params['title'],
                        params['company'], params['location'],
                        params['description'], params['source_url'],
                        params['apply_url'], params['apply_email'],
                        params['apply_type'], params['deadline'],
                        params['salary'], params['scraped_data'],
                        params['raw_text'], params['telegram_channel'],
                        params['raw_text'],
                    ))
                    result = cur.fetchone()
                    self.conn.commit()
                    return result[0] if result else None

        except Exception as e:
            logger.error(f"Upsert by URL failed: {e}")
            self.conn.rollback()
            raise

    def _upsert_by_telegram(self, params: Dict) -> Optional[int]:
        """Insert or update job, deduplicating by telegram_id + channel"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT id FROM jobs
                    WHERE telegram_id = %s
                      AND telegram_channel = %s
                      AND (source_url IS NULL OR source_url = '')
                """, (params['telegram_id'], params['telegram_channel']))
                existing = cur.fetchone()

                if existing:
                    cur.execute("""
                        UPDATE jobs SET
                            title = COALESCE(%s, title),
                            company = COALESCE(%s, company),
                            location = COALESCE(%s, location),
                            description = COALESCE(%s, description),
                            apply_url = COALESCE(%s, apply_url),
                            apply_email = COALESCE(%s, apply_email),
                            apply_type = COALESCE(%s, apply_type),
                            deadline_text = COALESCE(%s, deadline_text),
                            salary = COALESCE(%s, salary),
                            created_at = NOW(),
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                    """, (
                        params['title'], params['company'],
                        params['location'], params['description'],
                        params['apply_url'], params['apply_email'],
                        params['apply_type'], params['deadline'],
                        params['salary'], existing[0],
                    ))
                    result = cur.fetchone()
                    self.conn.commit()
                    return result[0] if result else existing[0]
                else:
                    cur.execute("""
                        INSERT INTO jobs (
                            telegram_id, telegram_channel, telegram_date,
                            title, company, location, description,
                            apply_url, apply_email, apply_type,
                            deadline_text, salary, scraped_data, raw_text,
                            channel_username, telegram_text,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, NOW(), NOW()
                        )
                        RETURNING id
                    """, (
                        params['telegram_id'], params['telegram_channel'],
                        params['telegram_date'], params['title'],
                        params['company'], params['location'],
                        params['description'], params['apply_url'],
                        params['apply_email'], params['apply_type'],
                        params['deadline'], params['salary'],
                        params['scraped_data'], params['raw_text'],
                        params['telegram_channel'], params['raw_text'],
                    ))
                    result = cur.fetchone()
                    self.conn.commit()
                    return result[0] if result else None

        except Exception as e:
            logger.error(f"Upsert by telegram failed: {e}")
            self.conn.rollback()
            raise

    def _simple_insert(self, job_data: Dict[str, Any]) -> Optional[int]:
        """Fallback: Simple insert with manual duplicate check"""
        try:
            self._ensure_connection()

            source_url = (job_data.get('source_url') or '').strip() or None

            with self.conn.cursor() as cur:
                if source_url:
                    cur.execute(
                        "SELECT id FROM jobs WHERE source_url = %s",
                        (source_url,)
                    )
                else:
                    cur.execute("""
                        SELECT id FROM jobs
                        WHERE telegram_id = %s
                          AND telegram_channel = %s
                          AND (source_url IS NULL OR source_url = '')
                    """, (
                        str(job_data.get('telegram_id', '')),
                        job_data.get('telegram_channel')
                    ))

                existing = cur.fetchone()
                if existing:
                    cur.execute("""
                        UPDATE jobs SET
                            title = COALESCE(%s, title),
                            description = COALESCE(%s, description),
                            created_at = NOW(),
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                    """, (
                        job_data.get('title'),
                        job_data.get('description'),
                        existing[0],
                    ))
                    result = cur.fetchone()
                    self.conn.commit()
                    logger.info(f"Job updated (fallback): #{existing[0]}")
                    return result[0] if result else existing[0]

                cur.execute("""
                    INSERT INTO jobs (
                        telegram_id, telegram_channel, telegram_date,
                        title, company, location, description,
                        source_url, apply_url, apply_email, apply_type,
                        deadline_text, salary, scraped_data, raw_text,
                        channel_username, telegram_text,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, NOW(), NOW()
                    )
                    RETURNING id
                """, (
                    str(job_data.get('telegram_id', '')),
                    job_data.get('telegram_channel'),
                    job_data.get('telegram_date'),
                    job_data.get('title'),
                    job_data.get('company'),
                    job_data.get('location'),
                    job_data.get('description'),
                    source_url,
                    job_data.get('apply_url'),
                    job_data.get('apply_email'),
                    job_data.get('apply_type'),
                    job_data.get('deadline'),
                    job_data.get('salary'),
                    Json(job_data.get('scraped_data', {})),
                    job_data.get('raw_text'),
                    job_data.get('telegram_channel'),
                    job_data.get('raw_text'),
                ))
                result = cur.fetchone()

            self.conn.commit()
            return result[0] if result else None

        except Exception as e:
            logger.error(f"Simple insert failed: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return None

    # ================================================================
    # READ OPERATIONS
    # ================================================================

    def get_jobs(
        self,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
        category: Optional[str] = None,
        location: Optional[str] = None,
        expiring: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get jobs with optional filtering. expiring: 'today' or 'week'."""
        self._ensure_connection()

        try:
            conditions, params = _jobs_base_where(search=search, category=category, location=location)

            # Expiring filter: do NOT add SQL here; we filter by parsed date in Python
            order = "created_at DESC NULLS LAST"
            if sort == "deadline":
                order = "deadline_text ASC NULLS LAST, created_at DESC NULLS LAST"

            fetch_limit = limit + offset
            if expiring:
                fetch_limit = min(2000, fetch_limit + 1000)  # fetch more to filter by date

            query = f"""
                SELECT
                    id, telegram_id, telegram_channel, channel_username, telegram_date,
                    title, company, location, description,
                    source_url, apply_url, apply_email, apply_type,
                    deadline_text as deadline, salary,
                    created_at, updated_at
                FROM jobs
                WHERE {' AND '.join(conditions)}
                ORDER BY {order}
                LIMIT %s OFFSET %s
            """
            if expiring:
                params.extend([fetch_limit, 0])
            else:
                params.extend([limit, offset])

            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                results = cur.fetchall()

            rows = []
            for row in results:
                job = dict(row)
                for key in ['telegram_date', 'created_at', 'updated_at']:
                    if job.get(key) and hasattr(job[key], 'isoformat'):
                        job[key] = job[key].isoformat()
                rows.append(job)

            # Exclude expired jobs (deadline in the past)
            rows = [r for r in rows if not _is_job_expired(r)]

            if expiring in ("today", "tomorrow", "week"):
                today = date.today()
                tomorrow = today + timedelta(days=1)
                end_date = today + timedelta(days=7)
                filtered = []
                for job in rows:
                    dl = job.get("deadline") or job.get("deadline_text")
                    d = parse_deadline_date(dl)
                    if d is None:
                        continue
                    if expiring == "today":
                        if d != today:
                            continue
                    elif expiring == "tomorrow":
                        if d != tomorrow:
                            continue
                    else:
                        if d < today or d > end_date:
                            continue
                    filtered.append(job)
                if sort == "deadline":
                    filtered.sort(key=lambda j: (parse_deadline_date(j.get("deadline") or j.get("deadline_text")) or date.max, j.get("created_at") or ""))
                else:
                    filtered.sort(key=lambda j: (j.get("created_at") or ""), reverse=True)
                jobs = filtered[offset:offset + limit]
            else:
                jobs = rows

            return jobs

        except Exception as e:
            logger.error(f"Failed to get jobs: {e}")
            return []

    def get_job_by_id(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Get single job by ID"""
        self._ensure_connection()

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
                result = cur.fetchone()

            if result:
                job = dict(result)
                for key in ['telegram_date', 'created_at', 'updated_at',
                            'scraped_at', 'deadline_date']:
                    if job.get(key) and hasattr(job[key], 'isoformat'):
                        job[key] = job[key].isoformat()
                return job

            return None

        except Exception as e:
            logger.error(f"Failed to get job: {e}")
            return None

    def get_posted_job_ids(self, channel: str) -> set:
        """Return set of job IDs already posted to the given Telegram channel."""
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT job_id FROM telegram_posted_jobs WHERE channel = %s",
                    (channel.strip(),),
                )
                return {row[0] for row in cur.fetchall()}
        except Exception as e:
            logger.warning(f"get_posted_job_ids failed: {e}")
            return set()

    def mark_job_posted(self, job_id: int, channel: str) -> None:
        """Record that a job was posted to a Telegram channel (avoids reposting)."""
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO telegram_posted_jobs (job_id, channel)
                    VALUES (%s, %s)
                    ON CONFLICT (job_id, channel) DO NOTHING
                    """,
                    (job_id, channel.strip()),
                )
            self.conn.commit()
        except Exception as e:
            logger.warning(f"mark_job_posted failed: {e}")
            self.conn.rollback()

    def get_job_count(
        self,
        search: Optional[str] = None,
        category: Optional[str] = None,
        location: Optional[str] = None,
        expiring: Optional[str] = None,
    ) -> int:
        """Get total job count with same filters as get_jobs."""
        self._ensure_connection()

        try:
            conditions, params = _jobs_base_where(search=search, category=category, location=location)

            if expiring in ("today", "tomorrow", "week"):
                # Fetch jobs and filter by parsed deadline date for exact count
                query = f"""
                    SELECT deadline_text as deadline
                    FROM jobs
                    WHERE {' AND '.join(conditions)}
                    LIMIT %s
                """
                params.append(2000)
                with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()
                today = date.today()
                tomorrow = today + timedelta(days=1)
                end_date = today + timedelta(days=7)
                count = 0
                for row in rows:
                    d = parse_deadline_date(row.get("deadline"))
                    if d is None:
                        continue
                    if expiring == "today":
                        if d == today:
                            count += 1
                    elif expiring == "tomorrow":
                        if d == tomorrow:
                            count += 1
                    else:
                        if today <= d <= end_date:
                            count += 1
                return count

            # Count only non-expired jobs (same as get_jobs)
            query = f"""
                SELECT id, deadline_text as deadline
                FROM jobs
                WHERE {' AND '.join(conditions)}
                LIMIT 50000
            """
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
            count = sum(1 for r in rows if not _is_job_expired(r))
            return count

        except Exception as e:
            logger.error(f"Failed to get count: {e}")
            return 0

    def delete_expired_jobs(self) -> int:
        """Delete jobs whose parsed deadline is in the past. Returns number deleted."""
        self._ensure_connection()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, deadline_text as deadline FROM jobs")
                rows = cur.fetchall()
            expired_ids = [r["id"] for r in rows if _is_job_expired(r)]
            if not expired_ids:
                return 0
            for i in range(0, len(expired_ids), 500):
                batch = expired_ids[i : i + 500]
                with self.conn.cursor() as cur:
                    cur.execute("DELETE FROM jobs WHERE id = ANY(%s)", (batch,))
                self.conn.commit()
            logger.info(f"Deleted {len(expired_ids)} expired job(s)")
            return len(expired_ids)
        except Exception as e:
            logger.error(f"Failed to delete expired jobs: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics. total_jobs excludes expired (matches list/categories)."""
        self._ensure_connection()

        try:
            total = self.get_job_count()
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM jobs
                    WHERE (apply_url IS NOT NULL OR apply_email IS NOT NULL)
                """)
                with_apply = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*) FROM jobs
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """)
                last_24h = cur.fetchone()[0]

            return {
                'total_jobs': total,
                'with_apply_link': with_apply,
                'last_24h': last_24h,
                'by_channel': {}
            }

        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {'total_jobs': 0, 'with_apply_link': 0}

    def get_categories(self) -> List[Dict[str, Any]]:
        """Get job categories with counts (non-expired only, matches list when you filter by category)."""
        category_list = [
            {"slug": "it", "name": "Software & IT"},
            {"slug": "finance", "name": "Finance"},
            {"slug": "banking", "name": "Banking"},
            {"slug": "ngo", "name": "NGO"},
            {"slug": "fresh_graduate", "name": "Fresh Graduate"},
        ]

        try:
            result = []
            for cat in category_list:
                slug = cat["slug"]
                count = self.get_job_count(category=slug)
                result.append({"name": cat["name"], "slug": slug, "count": count})
            result.sort(key=lambda x: x["count"], reverse=True)
            return result

        except Exception as e:
            logger.error(f"Failed to get categories: {e}")
            return []

    def record_apply_click(self, job_id: int, click_type: str = "link") -> None:
        """Record an apply-link or apply-email click for analytics."""
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO apply_clicks (job_id, click_type) VALUES (%s, %s)",
                    (job_id, click_type[:20] if click_type else "link"),
                )
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Failed to record apply click: {e}")
            self.conn.rollback()

    def get_apply_counts_for_jobs(self, job_ids: List[int]) -> Dict[int, int]:
        """Return dict mapping job_id -> total apply clicks (link + email) for admin analytics."""
        if not job_ids:
            return {}
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                placeholders = ",".join("%s" for _ in job_ids)
                cur.execute(
                    f"SELECT job_id, COUNT(*) FROM apply_clicks WHERE job_id IN ({placeholders}) GROUP BY job_id",
                    tuple(job_ids),
                )
                return {row[0]: row[1] for row in cur.fetchall()}
        except Exception as e:
            logger.warning(f"get_apply_counts_for_jobs failed: {e}")
            return {}

    def get_apply_stats(self) -> Dict[str, int]:
        """Return total apply clicks, last 24h, and last 7 days for dashboard."""
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM apply_clicks")
                total = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(*) FROM apply_clicks WHERE clicked_at > NOW() - INTERVAL '24 hours'"
                )
                clicks_24h = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(*) FROM apply_clicks WHERE clicked_at > NOW() - INTERVAL '7 days'"
                )
                clicks_7d = cur.fetchone()[0]
            return {"total_clicks": total, "clicks_24h": clicks_24h, "clicks_7d": clicks_7d}
        except Exception as e:
            logger.warning(f"get_apply_stats failed: {e}")
            return {"total_clicks": 0, "clicks_24h": 0, "clicks_7d": 0}

    def get_top_jobs_by_applies(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return top jobs by apply click count for dashboard."""
        self._ensure_connection()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT j.id, j.title, j.company, COUNT(c.id) AS apply_count
                    FROM jobs j
                    LEFT JOIN apply_clicks c ON c.job_id = j.id
                    GROUP BY j.id, j.title, j.company
                    HAVING COUNT(c.id) > 0
                    ORDER BY apply_count DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"get_top_jobs_by_applies failed: {e}")
            return []

    def record_job_view(self, job_id: int) -> None:
        """Record a single job view for analytics."""
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO job_views (job_id) VALUES (%s)",
                    (job_id,),
                )
            self.conn.commit()
        except Exception as e:
            logger.warning(f"record_job_view failed: {e}")
            self.conn.rollback()

    def get_view_stats(self, period: str = "month") -> Dict[str, Any]:
        """Return view count for the given period: 'day' (last 24h), 'week' (last 7d), 'month' (last 30d)."""
        self._ensure_connection()
        interval = "24 hours"
        if period == "week":
            interval = "7 days"
        elif period == "month":
            interval = "30 days"
        else:
            period = "day"
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM job_views WHERE viewed_at > NOW() - INTERVAL %s",
                    (interval,),
                )
                count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM job_views")
                total = cur.fetchone()[0]
            return {"period": period, "count": count, "total": total}
        except Exception as e:
            logger.warning(f"get_view_stats failed: {e}")
            return {"period": period, "count": 0, "total": 0}

    def add_job_alert(self, email: str, keywords: str = None, location: str = None, frequency: str = "daily") -> Optional[str]:
        """Add a job alert subscription. Returns confirm_token or None on error."""
        self._ensure_connection()
        import secrets
        token = secrets.token_urlsafe(32)
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO job_alerts (email, keywords, location, frequency, confirm_token)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (email.strip().lower(), (keywords or "").strip() or None, (location or "").strip() or None, (frequency or "daily")[:20], token),
                )
            self.conn.commit()
            return token
        except Exception as e:
            logger.warning(f"Failed to add job alert: {e}")
            self.conn.rollback()
            return None

    def confirm_job_alert(self, token: str) -> bool:
        """Mark subscription as confirmed. Returns True if found and updated."""
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute("UPDATE job_alerts SET confirmed = TRUE, confirm_token = NULL WHERE confirm_token = %s", (token,))
                self.conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            logger.warning(f"Failed to confirm job alert: {e}")
            self.conn.rollback()
            return False

    def unsubscribe_job_alert(self, email: str) -> bool:
        """Remove subscription by email. Returns True if any row was deleted."""
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM job_alerts WHERE email = %s", (email.strip().lower(),))
                self.conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            logger.warning(f"Failed to unsubscribe job alert: {e}")
            self.conn.rollback()
            return False

    def get_confirmed_job_alerts(self):
        """Return list of confirmed subscriptions: dict with id, email, keywords, location, frequency, last_sent_at."""
        self._ensure_connection()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, email, keywords, location, frequency, last_sent_at FROM job_alerts WHERE confirmed = TRUE"
                )
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Failed to get job alerts: {e}")
            return []

    def mark_alert_sent(self, alert_id: int) -> None:
        """Set last_sent_at for a subscription."""
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute("UPDATE job_alerts SET last_sent_at = NOW() WHERE id = %s", (alert_id,))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()

    def close(self):
        """Close database connection"""
        if self.conn:
            try:
                self.conn.close()
                logger.info("Database connection closed")
            except Exception:
                pass