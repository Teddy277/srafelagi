"""
scrapers/abayjobs.py - AbayJobs Scraper
Handles abayjobs.com - WordPress job site.
"""

import logging
from .base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)


class AbayJobsScraper(BaseScraper):
    """Scraper for abayjobs.com"""

    def get_domain(self) -> str:
        return "abayjobs.com"

    async def scrape(self, url: str) -> ScrapedJob:
        """Scrape AbayJobs page"""
        # Let base scrape handle most things
        result = await super().scrape(url)
        
        if not result or not result.success:
            return result

        # Fix company name if it grabbed a category
        # AbayJobs often puts company name in title: "Company Name Vacancy"
        if result.title and "Vacancy" in result.title:
            company_candidate = result.title.split("Vacancy")[0].strip()
            if len(company_candidate) > 3:
                result.company = company_candidate
        
        # Or try to find it in the first line of description
        if result.description:
            lines = result.description.split('\n')
            for line in lines[:3]:
                line = line.strip('*# ')
                if (line and len(line) < 100 
                        and "Vacancy" not in line 
                        and "Education" not in line):
                    # Check if it looks like a company name
                    if any(x in line.lower() for x in ['bank', 'insurance', 'authority', 'agency', 'college', 'university', 'board']):
                        result.company = line
                        break

        return result