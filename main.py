"""
main.py -- The Master Listener
================================
Entry point. Connects to Telegram via Telethon, monitors channels,
detects job posts, scrapes full details, saves to PostgreSQL.

Features:
  - Cleans Telegram markdown formatting
  - Extracts apply links (Google Forms, career portals)
  - Makes URLs clickable in descriptions
  - Auto-reconnects to Neon serverless DB
  - Closes aiohttp sessions properly
  - Handles company LISTING pages (fans out to individual jobs)
  - SMART MERGE: Scraped data + Telegram text fallback

Processing Order:
  1. Afriwork UUID buttons (Playwright scraping)
  2. Standard URLs in message text (site-specific scrapers)
  3. URLs in inline buttons
  4. Raw text parsing (fallback)
"""

import os
import re
import logging
import asyncio
import shutil
from datetime import datetime, date
from typing import Optional, List
from urllib.parse import urlparse, parse_qs

from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from dotenv import load_dotenv

from database import Database, parse_deadline_date
from telegram_parser import parse_telegram_message
from scrapers import get_scraper
from ai_normalize import normalize_job_text
from utils import normalize_url, normalize_text

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
CHANNELS = [
    ch.strip() for ch in os.getenv('CHANNELS', '').split(',') if ch.strip()
]

if not API_ID or not API_HASH:
    raise ValueError(
        "API_ID and API_HASH must be set in .env file. "
        "Get them from https://my.telegram.org"
    )

if not CHANNELS:
    raise ValueError(
        "CHANNELS must be set in .env file. "
        "Example: CHANNELS=freelance_ethio,harmeejobs,effoyjobs"
    )

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('main')

# ============================================================
# DATABASE
# ============================================================

db = Database()

# ============================================================
# TELETHON CLIENT
# ============================================================

TELEGRAM_SESSION_NAME = os.getenv('TELEGRAM_SESSION_NAME', 'job_listener').strip() or 'job_listener'
TELEGRAM_SESSION_DIR = os.getenv('TELEGRAM_SESSION_DIR', '').strip()


def get_telegram_session_name() -> str:
    """
    Store the Telethon SQLite session outside the OneDrive workspace by default.
    This avoids intermittent "database is locked" errors on the session file.
    """
    if TELEGRAM_SESSION_DIR:
        base_dir = TELEGRAM_SESSION_DIR
    else:
        local_app_data = os.getenv('LOCALAPPDATA')
        if local_app_data:
            base_dir = os.path.join(local_app_data, 'ethiopian-jobs', 'telethon')
        else:
            base_dir = os.path.join(os.getcwd(), '.telethon')

    os.makedirs(base_dir, exist_ok=True)
    session_name = os.path.join(base_dir, TELEGRAM_SESSION_NAME)
    legacy_session_file = os.path.join(os.getcwd(), f'{TELEGRAM_SESSION_NAME}.session')
    target_session_file = f'{session_name}.session'

    if (
        os.path.abspath(target_session_file) != os.path.abspath(legacy_session_file)
        and not os.path.exists(target_session_file)
        and os.path.exists(legacy_session_file)
    ):
        try:
            shutil.copy2(legacy_session_file, target_session_file)
            logger.info("Copied Telegram session to %s", target_session_file)
        except Exception as e:
            logger.warning("Could not copy Telegram session to %s: %s", target_session_file, e)

    return session_name


asyncio.set_event_loop(asyncio.new_event_loop())

# On Render (or any server with no persistent disk), set TELEGRAM_SESSION_STRING in env.
# Generate it locally once by running: python generate_session.py
_SESSION_STRING = os.getenv('TELEGRAM_SESSION_STRING', '').strip()
if _SESSION_STRING:
    client = TelegramClient(StringSession(_SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient(get_telegram_session_name(), API_ID, API_HASH)

# Populated in main() with peer IDs of monitored channels; handler ignores other chats
ALLOWED_CHAT_IDS = set()

# Polling: interval in seconds (channels that don't push updates are still fetched)
POLL_INTERVAL_SECONDS = 90
POLL_MESSAGES_PER_CHANNEL = 25

# ============================================================
# PATTERNS
# ============================================================

URL_PATTERN = re.compile(
    r'https?://[^\s<>"\')\]]+',
    re.IGNORECASE
)
# Protocol-less URLs (e.g. docs.google.com/forms/..., www.example.com/apply)
URL_PATTERN_PROTOCOLLESS = re.compile(
    r'(?:www\.|[a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)/[^\s<>"\')\]]*',
    re.IGNORECASE
)

AFRIWORK_UUID_PATTERN = re.compile(
    r'startapp=([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
    re.IGNORECASE
)

KNOWN_JOB_DOMAINS = {
    'afriworket.com', 'www.afriworket.com',
    'harmeejobs.com', 'www.harmeejobs.com',
    'effoyjobs.com', 'www.effoyjobs.com',
    'effoysira.com', 'www.effoysira.com',
    'kebenajobs.com', 'www.kebenajobs.com',
    'abayjobs.com', 'www.abayjobs.com',
    'ethiojobs.net', 'www.ethiojobs.net',
    'hagerejobs.com', 'www.hagerejobs.com',
    'geezjobs.com', 'www.geezjobs.com',
    'hahu.jobs', 'www.hahu.jobs',
    'reportervacancy.com', 'www.reportervacancy.com',
}

EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE
)

PLATFORM_EMAIL_DOMAINS = {
    'afriworket.com', 'harmeejobs.com', 'effoyjobs.com',
    'effoysira.com', 'kebenajobs.com', 'telegram.org',
    'abayjobs.com', 'hagerejobs.com', 'geezjobs.com',
    'hahu.jobs',
    'reportervacancy.com',
}

# ── Listing page patterns ────────────────────────────────────────────
LISTING_PAGE_PATTERNS = [
    re.compile(r'ethiojobs\.net/companies/[^/]+/jobs/?', re.IGNORECASE),
    re.compile(r'hagerejobs\.com/companies/[^/]+/jobs/?', re.IGNORECASE),
    re.compile(r'/employers?/[^/]+/jobs/?', re.IGNORECASE),
]


# ============================================================
# TEXT CLEANING & FORMATTING
# ============================================================

def clean_telegram_text(text: str) -> str:
    """Clean Telegram markdown and formatting artifacts from text."""
    if not text:
        return text

    # Decode HTML entities (e.g. &amp; → &, &lt; → <) from scraped web content
    import html as _html
    text = _html.unescape(text)

    text = re.sub(r'```[\s\S]*?```', lambda m: m.group(0).strip('`').strip(), text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{2,}', '', text)
    text = text.replace('\u00a0', ' ')
    text = text.replace('\u200b', '')
    text = text.replace('\u200c', '')
    text = text.replace('\u200d', '')
    text = text.replace('\ufeff', '')
    lines = [line.strip() for line in text.split('\n')]
    # Remove lines that are purely Telegram hashtags (e.g. #company_name, #location)
    lines = [l for l in lines if not re.match(r'^(#\w+\s*)+$', l)]
    # Remove Telegram channel footer lines (e.g. "@hahujobs | @hahujobs_bot")
    lines = [l for l in lines if not re.match(r'^@\w+(\s*\|\s*@\w+)*\s*$', l)]
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_apply_links(text: str) -> List[str]:
    """Extract application links from job descriptions. Includes protocol-less URLs (e.g. docs.google.com/forms/...)."""
    if not text:
        return []

    all_urls = list(URL_PATTERN.findall(text))
    for m in URL_PATTERN_PROTOCOLLESS.finditer(text):
        raw = m.group(0)
        if not re.match(r'^https?://', raw, re.IGNORECASE):
            all_urls.append(normalize_url_with_protocol(raw))
    apply_urls = []
    seen = set()

    for url in all_urls:
        url = clean_url(url)
        if not url:
            continue
        if not re.match(r'^https?://', url, re.IGNORECASE):
            url = normalize_url_with_protocol(url)
        if url in seen:
            continue
        seen.add(url)
        if not is_acceptable_apply_url(url):
            continue
        apply_urls.append(url)

    # Prefer URLs that look like apply forms / career pages
    apply_urls.sort(key=lambda u: (0 if _looks_like_apply_url(u) else 1, u))
    return apply_urls


def normalize_description_line_breaks(text: str) -> str:
    """Unify line endings and collapse excessive newlines for consistent display."""
    if not text:
        return text
    text = re.sub(r'\r\n|\r', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def format_description_with_links(text: str) -> str:
    """Make URLs in description text clickable as HTML links."""
    if not text:
        return text
    text = normalize_description_line_breaks(text)

    def url_to_link(match):
        url = match.group(0)
        url = clean_url(url)
        if not url:
            return match.group(0)

        url_lower = url.lower()

        if 'forms.gle' in url_lower or 'google.com/forms' in url_lower:
            link_text = 'Apply Here (Google Form)'
        elif 'erecruit' in url_lower or 'oracle' in url_lower:
            link_text = 'Apply Here (Career Portal)'
        elif 'workday' in url_lower:
            link_text = 'Apply Here (Workday)'
        elif 't.me/' in url_lower:
            link_text = 'Telegram Channel'
        elif len(url) > 60:
            link_text = url[:57] + '...'
        else:
            link_text = url

        return f'<a href="{url}" target="_blank" rel="noopener">{link_text}</a>'

    text = URL_PATTERN.sub(url_to_link, text)
    return text


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def generate_telegram_id(channel_id: int, message_id: int) -> int:
    return abs(channel_id) * 10_000_000_000 + message_id


def clean_url(url: str) -> str:
    url = url.rstrip('*.,;:!?)')
    url = re.sub(r'[\*\.\,\;\:\!\?\)\]]+$', '', url)
    if url.endswith('#'):
        url = url[:-1]
    return url


def normalize_url_with_protocol(url: str) -> str:
    """Ensure URL has https:// so it can be used as apply_link."""
    if not url or not url.strip():
        return url
    u = url.strip()
    if re.match(r'^https?://', u, re.IGNORECASE):
        return u
    if u.startswith('//'):
        return 'https:' + u
    return 'https://' + u


def is_acceptable_apply_url(url: str) -> bool:
    """True if URL is suitable as an apply link (not telegram, not social, not skip domains)."""
    if not url or len(url) < 10:
        return False
    url_lower = url.lower()
    if 't.me/' in url_lower or 'telegram' in url_lower:
        return False
    skip_domains = [
        'effoysira.com', 'effoyjobs.com', 'harmeejobs.com',
        'kebenajobs.com', 'afriworket.com', 'abayjobs.com',
    ]
    if any(d in url_lower for d in skip_domains):
        return False
    social = [
        'facebook.com', 'twitter.com', 'linkedin.com',
        'instagram.com', 'youtube.com', 'tiktok.com',
    ]
    if any(s in url_lower for s in social):
        return False
    return True


def _looks_like_apply_url(url: str) -> bool:
    """Prefer URLs that look like apply forms or career pages."""
    u = url.lower()
    return any(x in u for x in ('/form', 'forms.', 'apply', 'careers', 'job/apply', 'vacancy'))


def extract_urls_from_text(text: str) -> List[str]:
    if not text:
        return []
    raw_urls = URL_PATTERN.findall(text)
    cleaned = []
    seen = set()
    for url in raw_urls:
        url = clean_url(url)
        if url and len(url) > 10 and url not in seen:
            seen.add(url)
            cleaned.append(url)
    return cleaned


def is_scrapable_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().split(':')[0]
        if (parsed.path or '').strip() in ('', '/'):
            return False
        return domain in KNOWN_JOB_DOMAINS
    except Exception:
        return False


def is_telegram_url(url: str) -> bool:
    try:
        return 't.me' in urlparse(url).netloc.lower()
    except Exception:
        return False


# Ethiopian mobile: 09 + 8 digits
_ETHIOPIAN_MOBILE = re.compile(r'09\d{8}')
# Amharic "job type" repeated in bulk ads
_AMHARIC_JOB_TYPE = re.compile(r'የስራ\s*አይነት|ደመወዝ===|ፆታ===')


def looks_like_bulk_phone_ad(text: str) -> bool:
    """Skip bulk classified ads (many phone numbers + repeated job-type lines)."""
    if not text or len(text) < 400:
        return False
    phones = _ETHIOPIAN_MOBILE.findall(text)
    if len(phones) < 2:
        return False
    amharic_markers = len(_AMHARIC_JOB_TYPE.findall(text))
    if amharic_markers >= 3:
        return True
    if len(phones) >= 3 and amharic_markers >= 1:
        return True
    return False


def is_listing_page(url: str) -> bool:
    for pattern in LISTING_PAGE_PATTERNS:
        if pattern.search(url):
            return True
    return False


def extract_email_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    emails = EMAIL_PATTERN.findall(text)
    for email in emails:
        email = email.rstrip('.,;:!?)')
        domain = email.split('@')[-1].lower()
        if domain not in PLATFORM_EMAIL_DOMAINS:
            return email.lower()
    return None


def extract_salary_from_text(text: str) -> Optional[str]:
    salary_match = re.search(
        r'(?:salary|payment|pay|compensation|benefits)\s*[:\-&]?\s*(.+?)(?:\n|$)',
        text, re.IGNORECASE
    )
    if salary_match:
        salary = salary_match.group(1).strip()
        if len(salary) > 3:
            return salary

    etb_match = re.search(r'[\d,]+\s*(?:ETB|Birr)', text, re.IGNORECASE)
    if etb_match:
        return etb_match.group(0).strip()

    return None


def extract_afriwork_uuid(message) -> Optional[str]:
    if not message.reply_markup:
        return None
    markup = message.reply_markup
    if not hasattr(markup, 'rows'):
        return None
    for row in markup.rows:
        if not hasattr(row, 'buttons'):
            continue
        for button in row.buttons:
            if not hasattr(button, 'url') or not button.url:
                continue
            url = button.url
            url_lower = url.lower()
            if 'afriwork' not in url_lower and 'afriaborkers' not in url_lower:
                continue
            match = AFRIWORK_UUID_PATTERN.search(url)
            if match:
                uuid = match.group(1)
                logger.info(f"  Extracted Afriwork UUID: {uuid}")
                return uuid
            try:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                if 'startapp' in params:
                    uuid = params['startapp'][0]
                    if re.match(
                        r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$',
                        uuid, re.IGNORECASE
                    ):
                        return uuid
            except Exception:
                continue
    return None


def extract_button_urls(message) -> List[str]:
    urls = []
    if not message.reply_markup:
        return urls
    markup = message.reply_markup
    if not hasattr(markup, 'rows'):
        return urls
    for row in markup.rows:
        if not hasattr(row, 'buttons'):
            continue
        for button in row.buttons:
            if hasattr(button, 'url') and button.url:
                urls.append(button.url)
    return urls


def get_channel_name(event) -> str:
    try:
        if event.chat and hasattr(event.chat, 'username') and event.chat.username:
            return f"@{event.chat.username}"
    except Exception:
        pass
    try:
        return f"@{event.chat_id}"
    except Exception:
        return "@unknown"


# ============================================================
# SCRAPER SESSION CLEANUP
# ============================================================

async def cleanup_scraper(scraper):
    try:
        if hasattr(scraper, 'session') and scraper.session:
            if not scraper.session.closed:
                await scraper.session.close()
                await asyncio.sleep(0.1)
    except Exception:
        pass
    try:
        if hasattr(scraper, 'close'):
            await scraper.close()
            await asyncio.sleep(0.1)
    except Exception:
        pass


# ============================================================
# TELEGRAM TEXT FALLBACK PARSER
# ============================================================

def parse_telegram_fallback(raw_text: str) -> dict:
    """
    Extract job fields from the Telegram message text.
    Used as FALLBACK when the scraper returns empty/poor data.
    """
    if not raw_text:
        return {}

    result = {}

    # ── Company ──────────────────────────────────────────────────────
    company_match = re.search(
        r'(?:company|organization|employer|ድርጅት|ኩባንያ)\s*[:\-]\s*(.+?)(?:\n|$)',
        raw_text, re.IGNORECASE
    )
    if company_match:
        company = company_match.group(1).strip()
        # Clean trailing labels
        company = re.sub(r'\s*(?:employment|location|deadline|requirement).*$',
                         '', company, flags=re.IGNORECASE)
        if company:
            result['company'] = company

    # ── Deadline ─────────────────────────────────────────────────────
    deadline_match = re.search(
        r'(?:deadline|closing\s*date|expires?|due\s*date|end\s*date|'
        r'የመጨረሻ\s*ቀን|የማመልከቻ\s*ቀን)\s*[:\-]\s*(.+?)(?:\n|$)',
        raw_text, re.IGNORECASE
    )
    if deadline_match:
        result['deadline'] = deadline_match.group(1).strip()

    # ── Location ─────────────────────────────────────────────────────
    location_match = re.search(
        r'(?:location|place\s*of\s*work|work\s*place|city|ቦታ)\s*[:\-]\s*(.+?)(?:\n|$)',
        raw_text, re.IGNORECASE
    )
    if location_match:
        result['location'] = location_match.group(1).strip()

    # ── Salary ───────────────────────────────────────────────────────
    salary = extract_salary_from_text(raw_text)
    if salary:
        result['salary'] = salary

    # ── Email ────────────────────────────────────────────────────────
    email = extract_email_from_text(raw_text)
    if email:
        result['email'] = email

    # ── Title (first non-label line) ─────────────────────────────────
    lines = [l.strip() for l in raw_text.strip().split('\n') if l.strip()]
    skip_prefixes = [
        'company:', 'location:', 'deadline:', 'employment type:',
        'employment:', 'requirement', 'qualification', 'click here',
        'category:', 'salary:', '#', 'http', 'link (', 'type:',
    ]
    for line in lines:
        line_lower = line.lower().strip()
        if any(line_lower.startswith(p) for p in skip_prefixes):
            continue
        if len(line) > 5 and len(line) < 200:
            result['title'] = line.rstrip('!').strip()
            break

    return result


def is_description_empty(description: Optional[str]) -> bool:
    """Check if a scraped description is empty or useless."""
    if not description:
        return True

    clean = description.strip().lower()

    empty_phrases = [
        'no description available',
        'no description available.',
        'no description',
        'n/a',
        'not available',
        'no info',
        'description not found',
        'coming soon',
        '',
    ]

    if clean in empty_phrases:
        return True

    # Text that is just "no description available" plus boilerplate (e.g. "View original post on source website")
    if 'no description available' in clean:
        stripped = re.sub(
            r'\b(view original post|on source website|click here to learn more|link)\b',
            '', clean, flags=re.IGNORECASE
        )
        stripped = re.sub(r'https?://\S+', '', stripped)
        stripped = ''.join(stripped.split())
        if len(stripped) < 50 or 'nodescriptionavailable' in stripped.replace(' ', ''):
            return True

    # Too short to be useful (less than 30 chars after stripping)
    if len(clean) < 30:
        return True

    return False


# ============================================================
# BUILD JOB DATA (SMART MERGE)
# ============================================================

def build_job_data(
    job_result,
    url: str,
    telegram_id: int,
    source_channel: str,
    message_date: Optional[datetime],
    raw_text: str,
) -> Optional[dict]:
    """
    Convert a scraper result into a job_data dict ready for db.save_job().
    SMART MERGE: Scraped data wins, Telegram text fills the gaps.
    """
    job_result_exists = job_result is not None

    # Check for explicit failure
    if job_result_exists and hasattr(job_result, 'success') and not job_result.success:
        error_msg = getattr(job_result, 'error', 'Unknown error')
        logger.warning(f"  Scraping not fully successful: {error_msg}")
        scraped_title = getattr(job_result, 'title', None)
        scraped_desc = getattr(job_result, 'description', None)
        if not scraped_title and not scraped_desc and not raw_text:
            return None

    # ── Parse Telegram text for fallback values ──────────────────────
    tg = parse_telegram_fallback(raw_text) if raw_text else {}

    # Also try the full parser
    tg_parsed = None
    if raw_text:
        try:
            tg_parsed = parse_telegram_message(raw_text)
        except Exception:
            pass

    # ── Extract scraped values ───────────────────────────────────────
    if job_result_exists:
        scraped_title = getattr(job_result, 'title', None)
        scraped_company = getattr(job_result, 'company', None)
        scraped_description = getattr(job_result, 'description', None)
        scraped_location = getattr(job_result, 'location', None)
        scraped_deadline = getattr(job_result, 'deadline', None)
        scraped_apply_url = getattr(job_result, 'apply_url', None)
        scraped_apply_email = getattr(job_result, 'apply_email', None)
        scraped_apply_type = getattr(job_result, 'apply_type', None)
        scraped_data = getattr(job_result, 'scraped_data', None) or {}
    else:
        scraped_title = None
        scraped_company = None
        scraped_description = None
        scraped_location = None
        scraped_deadline = None
        scraped_apply_url = None
        scraped_apply_email = None
        scraped_apply_type = None
        scraped_data = {}

    # ── Salary from scraped_data ─────────────────────────────────────
    salary = None
    if isinstance(scraped_data, dict):
        salary = scraped_data.get('salary')
        period = scraped_data.get('salary_period')
        if salary and period:
            salary = f"{salary} ({period})"

    # ════════════════════════════════════════════════════════════════
    # SMART MERGE: Scraped wins → Telegram fallback fills gaps
    # ════════════════════════════════════════════════════════════════

    # Title
    final_title = scraped_title
    if not final_title:
        final_title = tg.get('title')
    if not final_title and tg_parsed:
        final_title = getattr(tg_parsed, 'title', None)

    # Company
    final_company = scraped_company
    if not final_company:
        final_company = tg.get('company')
    if not final_company and tg_parsed:
        final_company = getattr(tg_parsed, 'company', None)

    # Description — CRITICAL: use Telegram text if scraper got nothing useful
    final_description = scraped_description
    if is_description_empty(final_description):
        if raw_text and len(raw_text.strip()) > 30:
            candidate = raw_text.strip()
            # Don't use Telegram text if it's just the "no description available" teaser
            if not is_description_empty(candidate):
                final_description = candidate
                logger.info("  📝 Using Telegram text as description (scraper returned empty)")

    # Location
    final_location = scraped_location
    if not final_location:
        final_location = tg.get('location')
    if not final_location and tg_parsed:
        final_location = getattr(tg_parsed, 'location', None)

    # Deadline
    final_deadline = scraped_deadline
    if not final_deadline:
        final_deadline = tg.get('deadline')
    if not final_deadline and tg_parsed:
        final_deadline = getattr(tg_parsed, 'deadline', None)
    # Last resort: regex scan of raw Telegram text
    if not final_deadline and raw_text:
        for _pat in [
            r'(?:deadline|closing\s*date|apply\s*before|ends?)[:\s]+([^\n]{3,80})',
            r'(?:last\s+date|due\s+date)[:\s]+([^\n]{3,80})',
        ]:
            _m = re.search(_pat, raw_text, re.IGNORECASE)
            if _m:
                final_deadline = _m.group(1).strip()
                break

    # Salary
    if not salary:
        salary = tg.get('salary')

    # Must have at least title or description
    if not final_title and not final_description:
        return None

    # ── Clean text fields ────────────────────────────────────────────
    cleaned_title = clean_telegram_text(final_title) if final_title else None
    cleaned_company = clean_telegram_text(final_company) if final_company else None
    cleaned_description = clean_telegram_text(final_description) if final_description else None

    # ── AI rewrite (Gemini) for clean, recruiter-quality job text ─────
    try:
        before_desc_len = len(cleaned_description or "")
        normalized = normalize_job_text(
            title=cleaned_title,
            company=cleaned_company,
            description=cleaned_description,
        )
        new_title = normalized.get("title")
        new_company = normalized.get("company")
        new_desc = normalized.get("description")

        # Only accept AI output if it actually changed something meaningful
        changed = []
        if new_title and new_title.strip() and new_title != cleaned_title:
            cleaned_title = new_title
            changed.append("title")
        if new_company and new_company.strip() and new_company != cleaned_company:
            cleaned_company = new_company
            changed.append("company")
        if new_desc and len(new_desc.strip()) >= 30 and new_desc != cleaned_description:
            cleaned_description = new_desc
            changed.append(f"description ({before_desc_len}→{len(new_desc)} chars)")

        if changed:
            logger.info("  AI rewrote: %s", ", ".join(changed))
        else:
            logger.info("  AI normalization ran but made no changes (or unavailable)")
    except Exception as e:
        logger.warning("  AI normalization failed: %s: %s", type(e).__name__, e)

    # ── Apply URL ────────────────────────────────────────────────────
    apply_url = scraped_apply_url
    if not apply_url and cleaned_description:
        apply_links = extract_apply_links(cleaned_description)
        if apply_links:
            apply_url = apply_links[0]
            logger.info(f"  Found apply link in description: {apply_url}")
    source_url_val = getattr(job_result, 'source_url', url) if job_result_exists else url
    if not apply_url and source_url_val:
        apply_url = source_url_val
        logger.info(f"  Using job page as apply link (e.g. HaHu/Afriwork): {apply_url[:60]}...")

    # ── Email ────────────────────────────────────────────────────────
    apply_email = scraped_apply_email
    if not apply_email:
        apply_email = tg.get('email')
    if not apply_email and cleaned_description:
        apply_email = extract_email_from_text(cleaned_description)

    # ── Format description ───────────────────────────────────────────
    formatted_description = format_description_with_links(
        cleaned_description
    ) if cleaned_description else None

    # ── Normalize fields for duplicate detection ──────────────────────
    source_url_normalized = normalize_url(source_url_val) if source_url_val else None
    title_normalized = normalize_text(cleaned_title) if cleaned_title else None
    company_normalized = normalize_text(cleaned_company) if cleaned_company else None

    # ── Build dict ───────────────────────────────────────────────────
    job_data = {
        'telegram_id': telegram_id,
        'telegram_channel': source_channel,
        'telegram_date': message_date,
        'title': cleaned_title,
        'company': cleaned_company,
        'location': final_location,
        'description': formatted_description,
        'source_url': source_url_val,
        'source_url_normalized': source_url_normalized,
        'title_normalized': title_normalized,
        'company_normalized': company_normalized,
        'apply_url': apply_url,
        'apply_email': apply_email,
        'apply_type': scraped_apply_type,
        'deadline': final_deadline,
        'salary': salary,
        'scraped_data': scraped_data if isinstance(scraped_data, dict) else {},
        'raw_text': raw_text,
    }

    # Infer apply_type
    if job_data['apply_email'] and not job_data['apply_type']:
        job_data['apply_type'] = 'email'
    elif job_data['apply_url'] and not job_data['apply_type']:
        job_data['apply_type'] = 'url'

    return job_data


# ============================================================
# PROCESSING FUNCTIONS
# ============================================================

async def process_listing_page(
    url: str,
    scraper,
    telegram_id: int,
    source_channel: str,
    message_date: Optional[datetime],
    raw_text: str,
):
    """
    Handle a company listing page: fan out to individual jobs.
    IMPORTANT: Does NOT pass Telegram raw_text to individual jobs
    because the Telegram text describes the LISTING, not each job.
    """
    logger.info(f"  📋 Detected LISTING page: {url}")

    if hasattr(scraper, 'extract_job_urls'):
        job_urls = await scraper.extract_job_urls(url)
    else:
        logger.warning(f"  Scraper has no extract_job_urls method: {url}")
        return

    if not job_urls:
        logger.warning(f"  Listing page returned 0 job URLs: {url}")
        return

    logger.info(f"  Found {len(job_urls)} jobs on listing page — scraping each...")

    # ── Extract company from listing URL as fallback ─────────────────
    listing_company = None
    company_match = re.search(r'/companies/([^/]+)', url)
    if company_match:
        slug = company_match.group(1)
        listing_company = slug.replace('-', ' ').title()
        listing_company = re.sub(r'\bPlc\b', 'PLC', listing_company)
        listing_company = re.sub(r'\bLlc\b', 'LLC', listing_company)
        listing_company = re.sub(r'\bNgo\b', 'NGO', listing_company)
        listing_company = re.sub(r'\bSc\b', 'SC', listing_company)
        logger.info(f"  Company from listing URL: {listing_company}")

    success = 0
    skipped = 0

    for i, job_url in enumerate(job_urls, 1):
        try:
            logger.info(f"  [{i}/{len(job_urls)}] Scraping: {job_url}")

            if db.job_exists(job_url):
                logger.info(f"  [{i}/{len(job_urls)}] Job URL already exists in jobs table, skipping scrape.")
                skipped += 1
                continue

            job_result = await scraper.scrape(job_url)

            # ── Unique telegram_id per job ───────────────────────────
            unique_telegram_id = telegram_id + i

            # ════════════════════════════════════════════════════════
            # CRITICAL: Pass EMPTY raw_text for individual jobs!
            # The Telegram text says "Company X is hiring for various
            # positions" — that's about the LISTING, not each job.
            # We must NOT use it as description for individual jobs.
            # ════════════════════════════════════════════════════════
            job_data = build_job_data(
                job_result, job_url,
                unique_telegram_id, source_channel, message_date,
                raw_text=""  # ← EMPTY! Don't pollute with listing text
            )

            if job_data and job_data.get('title'):
                # Fill in company from listing URL if scraper missed it
                if not job_data.get('company') and listing_company:
                    job_data['company'] = listing_company

                # Store the original listing URL for reference
                if not job_data.get('raw_text'):
                    job_data['raw_text'] = f"From listing: {url}"

                # Skip jobs that are already expired
                dl_date = parse_deadline_date(job_data.get("deadline"))
                if dl_date is not None and dl_date < date.today():
                    logger.info(
                        f"  [{i}/{len(job_urls)}] Skipped expired (deadline {job_data.get('deadline')}): {job_data.get('title', '')}"
                    )
                    await asyncio.sleep(2)
                    continue

                job_id = db.save_job(job_data)
                if job_id:
                    logger.info(
                        f"  [{i}/{len(job_urls)}] ✅ Saved #{job_id}: "
                        f"{job_data['title']} "
                        f"| Company: {job_data.get('company') or 'N/A'} "
                        f"| Email: {job_data.get('apply_email') or 'N/A'}"
                    )
                    success += 1
                else:
                    logger.warning(f"  [{i}/{len(job_urls)}] DB save returned None.")
            else:
                logger.warning(f"  [{i}/{len(job_urls)}] Empty result, skipped.")

            await asyncio.sleep(2)

        except Exception as e:
            logger.error(
                f"  [{i}/{len(job_urls)}] Error scraping {job_url}: {e}",
                exc_info=True
            )

    logger.info(
        f"  ✅ Listing complete: {success} saved, {skipped} skipped "
        f"out of {len(job_urls)} from {url}"
    )

async def process_url(
    url: str,
    telegram_id: int,
    source_channel: str,
    message_date: Optional[datetime],
    raw_text: str
):
    """Process a single URL: detect listing vs single job -> scrape -> save."""
    scraper = get_scraper(url)
    if not scraper:
        logger.info(f"  No scraper available for: {url}")
        return

    try:
        # Check listing page
        scraper_knows_listing = (
            hasattr(scraper, 'is_listing_page')
            and scraper.is_listing_page(url)
        )
        global_listing_match = is_listing_page(url)

        if scraper_knows_listing or global_listing_match:
            await process_listing_page(
                url, scraper,
                telegram_id, source_channel, message_date, raw_text
            )
            return

        # Single job page
        logger.info(f"  Scraping: {url}")

        if db.job_exists(url):
            logger.info(f"  Job URL already exists in jobs table, skipping scrape: {url}")
            return

        job_result = await scraper.scrape(url)

        job_data = build_job_data(
            job_result, url,
            telegram_id, source_channel, message_date, raw_text
        )

        if not job_data:
            logger.warning(f"  Scraper returned empty result for: {url}")
            return

        # Skip jobs that are already expired
        dl_date = parse_deadline_date(job_data.get("deadline"))
        if dl_date is not None and dl_date < date.today():
            logger.info(f"  Skipped expired (deadline {job_data.get('deadline')}): {job_data.get('title', '')}")
            return

        job_id = db.save_job(job_data)

        if job_id:
            logger.info(
                f"  ✅ Saved job #{job_id}: {job_data['title']}"
                f" | Company: {job_data['company'] or 'N/A'}"
                f" | Email: {job_data['apply_email'] or 'N/A'}"
                f" | Apply: {job_data['apply_url'][:50] if job_data['apply_url'] else 'N/A'}"
            )

    except Exception as e:
        logger.error(f"  Error processing URL {url}: {e}", exc_info=True)
    finally:
        await cleanup_scraper(scraper)


async def process_afriwork_uuid(
    uuid: str,
    telegram_id: int,
    source_channel: str,
    message_date: Optional[datetime],
    raw_text: str
):
    afriwork_url = f"https://afriworket.com/jobs/{uuid}"
    logger.info(f"  Afriwork UUID -> {afriwork_url}")
    await process_url(
        afriwork_url, telegram_id, source_channel, message_date, raw_text
    )


async def process_raw_text(
    text: str,
    telegram_id: int,
    source_channel: str,
    message_date: Optional[datetime],
    button_urls: Optional[List[str]] = None,
):
    """Process a raw text message. Uses button_urls as apply/source fallback when link not in text (e.g. freelance_ethio)."""
    if looks_like_bulk_phone_ad(text):
        logger.info("  Skip: bulk phone ad (multiple 09x numbers, no job link)")
        return
    parsed = parse_telegram_message(text)
    if not parsed:
        return

    title = getattr(parsed, 'title', None)
    if not title:
        return

    company = getattr(parsed, 'company', None)
    location = getattr(parsed, 'location', None)
    deadline = getattr(parsed, 'deadline', None)
    urls = getattr(parsed, 'urls', []) or []

    for url in urls:
        clean = clean_url(url)
        if is_scrapable_url(clean) and not is_telegram_url(clean):
            logger.info(f"  Found scrapable URL in text, scraping: {clean}")
            await process_url(
                clean, telegram_id, source_channel, message_date, text
            )
            return

    description = clean_telegram_text(text)
    if len(description) < 30:
        return

    # Fallback deadline: parse_telegram_message can miss some formats — re-extract from raw text
    if not deadline:
        for _pat in [
            r'(?:deadline|closing\s*date|apply\s*before|ends?)[:\s]+([^\n]{3,80})',
            r'(?:last\s+date|due\s+date)[:\s]+([^\n]{3,80})',
        ]:
            _m = re.search(_pat, text, re.IGNORECASE)
            if _m:
                deadline = _m.group(1).strip()
                break

    apply_email = extract_email_from_text(text)
    salary = extract_salary_from_text(text)

    apply_url = None
    source_url = None
    apply_links = extract_apply_links(text)
    if apply_links:
        apply_url = apply_links[0]
    elif urls:
        for u in urls:
            u = clean_url(str(u))
            if u and not is_telegram_url(u):
                apply_url = normalize_url_with_protocol(u)
                break
    if not apply_url and button_urls:
        for u in button_urls:
            u = clean_url(u)
            if not u:
                continue
            u = normalize_url_with_protocol(u)
            if is_acceptable_apply_url(u):
                apply_url = u
                source_url = u
                logger.info(f"  Using button URL as apply link: {u[:60]}...")
                break

    # Normalize fields for duplicate detection
    cleaned_title = clean_telegram_text(title)
    cleaned_company = clean_telegram_text(company) if company else None

    # AI normalization — removes #hashtags, @mentions, and structures the description
    try:
        normalized = normalize_job_text(
            title=cleaned_title,
            company=cleaned_company,
            description=description,
        )
        if normalized.get("title") and normalized["title"].strip():
            cleaned_title = normalized["title"]
        if normalized.get("company") and normalized["company"].strip():
            cleaned_company = normalized["company"]
        if normalized.get("description") and len(normalized["description"].strip()) >= 30:
            description = normalized["description"]
            logger.info("  AI normalized direct Telegram message")
    except Exception as e:
        logger.warning("  AI normalization failed for direct message: %s", e)

    formatted_description = format_description_with_links(description)
    title_normalized = normalize_text(cleaned_title) if cleaned_title else None
    company_normalized = normalize_text(cleaned_company) if cleaned_company else None
    source_url_normalized = normalize_url(source_url) if source_url else None

    job_data = {
        'telegram_id': telegram_id,
        'telegram_channel': source_channel,
        'telegram_date': message_date,
        'title': cleaned_title,
        'company': cleaned_company,
        'location': location,
        'description': formatted_description,
        'source_url': source_url,
        'source_url_normalized': source_url_normalized,
        'title_normalized': title_normalized,
        'company_normalized': company_normalized,
        'apply_url': apply_url,
        'apply_email': apply_email,
        'apply_type': 'email' if apply_email else ('url' if apply_url else None),
        'deadline': deadline,
        'salary': salary,
        'scraped_data': {},
        'raw_text': text,
    }

    # Skip jobs that are already expired
    dl_date = parse_deadline_date(job_data.get("deadline"))
    if dl_date is not None and dl_date < date.today():
        logger.info(f"  Skipped expired (deadline {deadline}): {job_data.get('title', '')}")
        return

    job_id = db.save_job(job_data)
    if job_id:
        logger.info(
            f"  Saved from text #{job_id}: {job_data['title']}"
            f" | Company: {company or 'N/A'}"
            f" | Email: {apply_email or 'N/A'}"
            f" | Apply: {apply_url[:50] if apply_url else 'N/A'}"
        )


# ============================================================
# PROCESS ONE MESSAGE (shared by handler and polling)
# ============================================================

async def process_message(message, chat_id: int, source_channel: str, message_date):
    """Run the same pipeline (Afriwork UUID → URLs → buttons → raw text) on a single message."""
    text = message.text or getattr(message, "raw_text", None) or ""
    telegram_id = generate_telegram_id(chat_id, message.id)
    processed = False

    try:
        afriwork_uuid = extract_afriwork_uuid(message)
        if afriwork_uuid:
            logger.info(f"  [Step 1] Afriwork UUID: {afriwork_uuid}")
            await process_afriwork_uuid(
                afriwork_uuid, telegram_id, source_channel,
                message_date, text
            )
            processed = True
    except Exception as e:
        logger.error(f"  Step 1 error: {e}")

    if not processed:
        try:
            text_urls = extract_urls_from_text(text)
            scrapable_urls = [
                url for url in text_urls
                if is_scrapable_url(url) and not is_telegram_url(url)
            ]
            if scrapable_urls:
                logger.info(f"  [Step 2] Found {len(scrapable_urls)} scrapable URL(s)")
                for url in scrapable_urls:
                    await process_url(
                        url, telegram_id, source_channel,
                        message_date, text
                    )
                processed = True
        except Exception as e:
            logger.error(f"  Step 2 error: {e}")

    if not processed:
        try:
            button_urls = extract_button_urls(message)
            job_urls = [
                clean_url(url) for url in button_urls
                if "afriwork" not in url.lower()
                and "afriaborkers" not in url.lower()
                and is_scrapable_url(clean_url(url))
            ]
            if job_urls:
                logger.info(f"  [Step 3] Found {len(job_urls)} button URL(s)")
                for url in job_urls:
                    await process_url(
                        url, telegram_id, source_channel,
                        message_date, text
                    )
                processed = True
        except Exception as e:
            logger.error(f"  Step 3 error: {e}")

    if not processed and len(text) > 50:
        try:
            logger.info(f"  [Step 4] Parsing text ({len(text)} chars)")
            button_urls = extract_button_urls(message)
            await process_raw_text(
                text, telegram_id, source_channel, message_date,
                button_urls=button_urls,
            )
        except Exception as e:
            logger.error(f"  Step 4 error: {e}", exc_info=True)


# ============================================================
# MAIN EVENT HANDLER
# ============================================================

async def handler(event):
    logger.info(
        "RECV chat_id=%s msg_id=%s channel=%s",
        event.chat_id,
        getattr(event.message, "id", None),
        get_channel_name(event),
    )
    if event.chat_id not in ALLOWED_CHAT_IDS:
        return
    message = event.message
    source_channel = get_channel_name(event)
    message_date = message.date
    telegram_id = generate_telegram_id(event.chat_id, message.id)
    if db.is_telegram_message_processed(telegram_id):
        return
    logger.info(f"New message in {source_channel} (msg_id={message.id})")
    await process_message(message, event.chat_id, source_channel, message_date)
    db.mark_telegram_message_processed(telegram_id, source_channel)


# ============================================================
# POLLING (for channels that don't push updates)
# ============================================================

async def poll_channels_once(resolved_entities):
    """Fetch recent messages from each channel and process any not already in DB."""
    for entity in resolved_entities:
        try:
            chat_id = utils.get_peer_id(entity)
            source_channel = f"@{entity.username}" if getattr(entity, "username", None) else f"@{chat_id}"
            messages = await client.get_messages(entity, limit=POLL_MESSAGES_PER_CHANNEL)
        except Exception as e:
            logger.warning("Poll get_messages failed for %s: %s", source_channel, e)
            continue
        for message in messages:
            if not message or getattr(message, "id", None) is None:
                continue
            telegram_id = generate_telegram_id(chat_id, message.id)
            if db.is_telegram_message_processed(telegram_id):
                continue
            logger.info("Poll: new message in %s (msg_id=%s)", source_channel, message.id)
            try:
                await process_message(message, chat_id, source_channel, message.date)
                db.mark_telegram_message_processed(telegram_id, source_channel)
            except Exception as e:
                logger.error("Poll process_message error: %s", e, exc_info=True)


async def poll_channels_loop(resolved_entities):
    """Run polling every POLL_INTERVAL_SECONDS."""
    await asyncio.sleep(10)  # let push handler settle first
    while True:
        try:
            await poll_channels_once(resolved_entities)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Poll loop error: %s", e, exc_info=True)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


# ============================================================
# STARTUP
# ============================================================

async def main():
    logger.info("=" * 60)
    logger.info("Ethiopian Job Aggregator -- Starting Up")
    logger.info("=" * 60)

    try:
        db.initialize()
        logger.info("Database initialized successfully.")
        n = db.delete_expired_jobs()
        if n:
            logger.info("Removed %d expired job(s) from database.", n)
    except Exception as e:
        logger.warning(f"Database init warning: {e}")
        try:
            db.connect()
        except Exception as e2:
            logger.error(f"Database connection failed: {e2}")
            return

    logger.info(f"Monitoring {len(CHANNELS)} channel(s):")
    for ch in CHANNELS:
        logger.info(f"  - {ch}")

    logger.info("")
    logger.info("Connecting to Telegram...")

    try:
        await client.start()
        me = await client.get_me()
        logger.info(f"Connected as: {me.first_name} (@{me.username or 'no username'})")
    except Exception as e:
        logger.error(f"Failed to connect to Telegram: {e}")
        return

    logger.info("Verifying channel access...")
    accessible = 0
    resolved_entities = []
    for channel in CHANNELS:
        try:
            entity = await client.get_entity(channel)
            resolved_entities.append(entity)
            channel_title = getattr(entity, 'title', channel)
            logger.info(f"  OK: {channel} ({channel_title})")
            accessible += 1
        except Exception as e:
            logger.warning(f"  WARN: Cannot access {channel}: {e}")

    if accessible == 0:
        logger.error("Cannot access ANY channels!")
        return

    # Use peer IDs and accept all NewMessage events, then filter in handler.
    # This avoids Telethon/Telegram quirks where some channels don't trigger when using chats=.
    ALLOWED_CHAT_IDS.clear()
    ALLOWED_CHAT_IDS.update(utils.get_peer_id(e) for e in resolved_entities)
    client.add_event_handler(handler, events.NewMessage())
    logger.info(f"Handler registered (allowed chat IDs: {sorted(ALLOWED_CHAT_IDS)})")

    asyncio.create_task(poll_channels_loop(resolved_entities))
    logger.info("Channel polling started (every %s s)", POLL_INTERVAL_SECONDS)

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Listening on {accessible}/{len(CHANNELS)} channels...")
    logger.info("Press Ctrl+C to stop.")
    logger.info("=" * 60)

    await client.run_until_disconnected()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("")
        logger.info("Shutting down...")
        db.close()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        db.close()
