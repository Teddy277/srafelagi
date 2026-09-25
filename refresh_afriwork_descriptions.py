"""
Refresh descriptions for existing Afriwork jobs in the database.

Before the scraper read Afriwork's embedded job data, jobs from Afriwork
(posted via @freelance_ethio) were saved with only a header block
("Company: ... Category: ...", then a "=====" line) and no actual
description. This re-scrapes those jobs and stores the full text.

Only the description (and a missing apply email) is updated. created_at is
left alone, so refreshed jobs keep their place in the listing instead of
jumping to the top as if newly posted.

The API server runs this in the background on startup (see api.py), so a
deploy fixes the production database by itself. It's idempotent: refreshed
rows no longer match the query.

Manual usage (uses DATABASE_URL from the environment / .env):
  python refresh_afriwork_descriptions.py            # update the database
  python refresh_afriwork_descriptions.py --dry-run  # only show what would change
"""
import asyncio
import logging
import sys
from datetime import date

logger = logging.getLogger(__name__)

# Rows still in the old format: the header block + "=====" separator, or too short
# to hold a real description.
_NEEDS_REFRESH_SQL = """
    SELECT id, source_url, description, deadline_text
    FROM jobs
    WHERE source_url LIKE '%%afriworket.com/jobs/%%'
      AND (description IS NULL OR description LIKE '%%====================%%' OR length(description) < 400)
    ORDER BY id DESC
"""


def _rows_needing_refresh(db):
    from database import parse_deadline_date
    db._ensure_connection()
    with db.conn.cursor() as cur:
        cur.execute(_NEEDS_REFRESH_SQL)
        rows = cur.fetchall()
    db.conn.commit()
    today = date.today()
    out = []
    for job_id, url, desc, deadline_text in rows:
        dl = parse_deadline_date(deadline_text)
        if dl is not None and dl < today:
            continue  # expired: not shown, will be cleaned up anyway
        out.append((job_id, url, desc or ""))
    return out


def _save_description(db, job_id: int, description: str, apply_email) -> None:
    db._ensure_connection()
    try:
        with db.conn.cursor() as cur:
            cur.execute(
                """UPDATE jobs
                   SET description = %s,
                       apply_email = COALESCE(apply_email, %s),
                       updated_at = NOW()
                   WHERE id = %s""",
                (description, apply_email, job_id),
            )
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        raise


async def refresh_afriwork_descriptions(db, pause: float = 1.0, dry_run: bool = False) -> dict:
    """Re-scrape old-format Afriwork jobs and store their full description."""
    from scrapers.afriwork import AfriworkScraper

    rows = await asyncio.to_thread(_rows_needing_refresh, db)
    stats = {"todo": len(rows), "updated": 0, "unchanged": 0, "failed": 0}
    if not rows:
        logger.info("Afriwork refresh: nothing to do.")
        return stats
    logger.info("Afriwork refresh: %d job(s) need a full description%s.",
                len(rows), " (dry run)" if dry_run else "")

    scraper = AfriworkScraper()
    for i, (job_id, url, old_desc) in enumerate(rows, 1):
        try:
            result = await scraper.scrape(url)
            new_desc = (result.description or "").strip() if result and result.success else ""
            if not new_desc:
                stats["failed"] += 1
            elif len(new_desc) <= len(old_desc):
                stats["unchanged"] += 1
            else:
                if not dry_run:
                    await asyncio.to_thread(_save_description, db, job_id, new_desc, result.apply_email)
                stats["updated"] += 1
                logger.info("[%d/%d] #%s %s: %d -> %d chars", i, len(rows), job_id,
                            (result.title or "")[:50], len(old_desc), len(new_desc))
        except Exception as e:
            stats["failed"] += 1
            logger.warning("[%d/%d] #%s refresh failed: %s", i, len(rows), job_id, e)
        await asyncio.sleep(pause)  # be gentle with Afriwork and our own server

    logger.info("Afriwork refresh done: %s", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("scrapers.afriwork").setLevel(logging.WARNING)
    from database import Database

    _db = Database()
    try:
        _db.initialize()
    except Exception as e:
        logger.error("Database init failed: %s", e)
        sys.exit(1)
    asyncio.run(refresh_afriwork_descriptions(_db, pause=0.2, dry_run="--dry-run" in sys.argv))
