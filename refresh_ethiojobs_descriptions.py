"""
Refresh descriptions for existing EthioJobs jobs in the database.
Re-scrapes each job URL and updates the stored description (full text including
About You, Requirement Skill, How To Apply). Run occasionally to fix truncated descriptions.

Usage:
  python refresh_ethiojobs_descriptions.py
"""
import asyncio
import logging
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Import after path is set
from database import Database, parse_deadline_date
from scrapers.ethiojobs import EthioJobsScraper

async def main():
    db = Database()
    try:
        db.initialize()
    except Exception as e:
        logger.error("Database init failed: %s", e)
        sys.exit(1)

    urls = db.get_source_urls_like("%ethiojobs.net%")
    if not urls:
        logger.info("No EthioJobs jobs found in database.")
        return

    logger.info("Found %d EthioJobs job(s). Re-scraping to refresh descriptions...", len(urls))
    scraper = EthioJobsScraper()

    # Import build_job_data from main (needs main's env/config)
    from main import build_job_data

    updated = 0
    failed = 0
    for i, url in enumerate(urls, 1):
        try:
            existing = db.get_job_by_source_url(url)
            if not existing:
                continue
            logger.info("[%d/%d] %s", i, len(urls), url[:70] + "..." if len(url) > 70 else url)
            job_result = await scraper.scrape(url)
            if not job_result or not getattr(job_result, "success", False):
                logger.warning("  Scrape failed, skipping.")
                failed += 1
                continue
            telegram_id = existing.get("telegram_id") or ""
            channel = existing.get("telegram_channel") or ""
            raw_text = existing.get("raw_text") or ""
            message_date = existing.get("telegram_date")
            job_data = build_job_data(
                job_result, url, telegram_id, channel, message_date, raw_text
            )
            if job_data:
                dl_date = parse_deadline_date(job_data.get("deadline"))
                if dl_date is not None and dl_date < date.today():
                    logger.info("  Skipped expired job (deadline %s).", job_data.get("deadline"))
                    failed += 1
                else:
                    db.save_job(job_data)
                    updated += 1
            else:
                failed += 1
        except Exception as e:
            logger.exception("  Error: %s", e)
            failed += 1

    logger.info("Done. Updated %d, failed %d.", updated, failed)


if __name__ == "__main__":
    asyncio.run(main())
