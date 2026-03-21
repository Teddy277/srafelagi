import re
import asyncio
from typing import List, Dict
from urllib.parse import urljoin, quote_plus
from bs4 import BeautifulSoup
from .base import BaseScraper, ScrapedJob

class HarmeeJobsScraper(BaseScraper):
    JOBS_PAGE = "https://harmeejobs.com/jobs/"

    def get_domain(self) -> str:
        return "harmeejobs.com"

    async def scrape(self, url: str) -> ScrapedJob:
        result = ScrapedJob(source_url=url)
        is_company = '/company/' in url.lower()
        
        if is_company:
            # Construct Search Query
            company_slug = url.split('/company/')[-1].strip('/')
            company_name = company_slug.replace('-', ' ').title()
            search_url = f"{self.JOBS_PAGE}?search_keywords={quote_plus(company_name)}"
            
            html, _ = await self.fetch_page(search_url)
            if html:
                soup = BeautifulSoup(html, 'html.parser')
                links = []
                for a in soup.find_all('a', href=True):
                    if '/job/' in a['href'] and len(a.get_text()) > 5:
                        links.append(urljoin(self.JOBS_PAGE, a['href']))
                
                # Fetch first 3 jobs to build a combined description
                full_desc = f"🏢 {company_name} - Multiple Vacancies\n\n"
                for link in list(set(links))[:3]:
                    j_html, _ = await self.fetch_page(link)
                    if j_html:
                        j_soup = BeautifulSoup(j_html, 'html.parser')
                        desc_div = j_soup.select_one('.job_description')
                        if desc_div:
                            full_desc += f"📌 Position: {link.split('/')[-2].replace('-', ' ').title()}\n"
                            full_desc += desc_div.get_text(separator='\n')[:500] + "...\n\n"
                
                result.title = f"{company_name} - Jobs"
                result.description = full_desc
                result.success = True
        else:
            # Single Job Page
            html, _ = await self.fetch_page(url)
            if html:
                soup = BeautifulSoup(html, 'html.parser')
                result.title = self.extract_title(soup)
                result.description = self.extract_description(html, soup)
                result.apply_email = self.extract_emails(soup, html)[0] if self.extract_emails(soup, html) else None
                result.success = True
        
        return result