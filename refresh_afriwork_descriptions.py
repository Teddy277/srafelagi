"""
Refresh descriptions for existing Afriwork jobs in the database.

Before the scraper read Afriwork's embedded job data, jobs from Afriwork
(posted via @freelance_ethio) were saved with only a header block
("Company: ... Category: ...") and no actual description. This re-scrapes
each Afriwork job and saves the full text.

Usage:
  python refresh_afriwork_descriptions.py            # update the database
  python refresh_afriwork_descriptions.py --dry-run  # only show what would change
"""
import asyncio
import logging
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

from database import Database, parse_deadline_date
from scrapers.afriwork import AfriworkScraper


async def main(dry_run: bool):
    db = Database()
    try:
        db.initialize()
    except Exception as e:
        logger.error("Database init failed: %s", e)
        sys.exit(1)

    urls = db.get_source_urls_like("%afriworket.com/jobs/%")
    if not urls:
        logger.info("No Afriwork jobs found in database.")
        return

    logger.info("Found %d Afriwork job(s)%s.", len(urls), " (dry run)" if dry_run else "")
    scraper = AfriworkScraper()

    # Import build_job_data from main (needs main's env/config)
    from main import build_job_data

    updated = skipped = failed = 0
    for i, url in enumerate(urls, 1):
        try:
            existing = db.get_job_by_source_url(url)
            if not existing:
                continue
            job_result = await scraper.scrape(url)
            if not job_result or not getattr(job_result, "success", False):
                logger.warning("[%d/%d] Scrape failed, skipping: %s", i, len(urls), url)
                failed += 1
                continue

            old_len = len(existing.get("description") or "")
            new_len = len(job_result.description or "")
            if new_len <= old_len:
                skipped += 1
                continue
            logger.info("[%d/%d] %s: %d -> %d chars", i, len(urls), job_result.title, old_len, new_len)
            if dry_run:
                updated += 1
                continue

            job_data = build_job_data(
                job_result, url,
                existing.get("telegram_id") or "",
                existing.get("telegram_channel") or "",
                existing.get("telegram_date"),
                existing.get("raw_text") or "",
            )
            if not job_data:
                failed += 1
                continue
            dl_date = parse_deadline_date(job_data.get("deadline"))
            if dl_date is not None and dl_date < date.today():
                skipped += 1
                continue
            db.save_job(job_data)
            updated += 1
        except Exception as e:
            logger.exception("  Error on %s: %s", url, e)
            failed += 1

    verb = "Would update" if dry_run else "Updated"
    logger.info("Done. %s %d, unchanged/expired %d, failed %d.", verb, updated, skipped, failed)


if __name__ == "__main__":
    asyncio.run(main(dry_run="--dry-run" in sys.argv))
