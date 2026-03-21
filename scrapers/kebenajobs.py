"""
scrapers/kebenajobs.py - KebenaJobs Scraper
Handles kebenajobs.com - WordPress site.

Uses BaseScraper.scrape() directly since it already handles:
  - fetch_page()
  - extract_title()
  - extract_description() (finds .entry-content)
  - extract_company()
  - extract_location()
  - extract_emails()
  - extract_apply_links()
  - extract_deadline()

No overrides needed - the base class works perfectly for this site.
The old version had a custom scrape() that called self.parse_html()
which doesn't exist in BaseScraper, causing the error:
  'KebenaJobsScraper' object has no attribute 'parse_html'

By NOT defining scrape(), it inherits BaseScraper.scrape() which
already extracts 2750 chars of content from .entry-content.
"""

import logging
from .base import BaseScraper

logger = logging.getLogger(__name__)


class KebenaJobsScraper(BaseScraper):
    """Scraper for kebenajobs.com - inherits everything from BaseScraper."""

    def get_domain(self) -> str:
        return "kebenajobs.com"