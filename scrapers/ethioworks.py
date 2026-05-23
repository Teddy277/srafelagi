"""
Scraper for ethioworks.com
"""

from bs4 import BeautifulSoup
from typing import Optional, Tuple
from urllib.parse import urljoin
from .base import BaseScraper, ScrapedJob
import re


class EthioworksScraper(BaseScraper):
    """Specialized scraper for ethioworks.com"""
    
    def get_domain(self) -> str:
        return "ethioworks.com"
    
    def extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Ethioworks title extraction"""
        selectors = [
            'h1.job-title',
            '.job-header h1',
            'h1.entry-title',
            '.job-single-title',
            'h1'
        ]
        
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                title = elem.get_text(strip=True)
                # Clean up common suffixes
                title = re.sub(r'\s*[-–|].*$', '', title)
                if 5 < len(title) < 200:
                    return title
        
        return None
    
    def extract_company(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract company from ethioworks"""
        selectors = [
            '.company-name',
            '.job-company-name',
            '.employer',
            '[class*="company"]'
        ]
        
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                company = elem.get_text(strip=True)
                if company and len(company) < 100:
                    return company
        
        # Try to find in structured data
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if 'hiringOrganization' in data:
                        org = data['hiringOrganization']
                        if isinstance(org, dict):
                            return org.get('name')
                        return str(org)
            except Exception:
                pass
        
        return None
    
    def extract_job_details_table(self, soup: BeautifulSoup) -> dict:
        """Extract data from job details table (common in ethioworks)"""
        details = {}
        
        # They often have a table with job details
        tables = soup.find_all('table')
        for table in tables:
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True).lower()
                    value = cells[1].get_text(strip=True)
                    
                    if 'company' in key or 'organization' in key:
                        details['company'] = value
                    elif 'location' in key or 'place' in key:
                        details['location'] = value
                    elif 'salary' in key:
                        details['salary'] = value
                    elif 'deadline' in key or 'closing' in key:
                        details['deadline'] = value
                    elif 'experience' in key:
                        details['experience'] = value
        
        # Also check definition lists
        for dl in soup.find_all('dl'):
            dts = dl.find_all('dt')
            dds = dl.find_all('dd')
            for dt, dd in zip(dts, dds):
                key = dt.get_text(strip=True).lower()
                value = dd.get_text(strip=True)
                if 'company' in key:
                    details['company'] = value
                elif 'location' in key:
                    details['location'] = value
        
        return details
    
    def find_best_apply_link(
        self, 
        soup: BeautifulSoup, 
        html: str, 
        base_url: str
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Ethioworks apply link extraction.
        They sometimes use modals or special buttons.
        """
        # Check for apply button
        apply_selectors = [
            'a.apply-button',
            'a.btn-apply',
            'a[href*="apply"]',
            '.apply-section a',
            'a[class*="apply"]',
            'button[onclick*="apply"]'
        ]
        
        for selector in apply_selectors:
            elems = soup.select(selector)
            for elem in elems:
                if elem.name == 'a':
                    href = elem.get('href', '')
                elif elem.name == 'button':
                    onclick = elem.get('onclick', '')
                    match = re.search(r"['\"]([^'\"]+)['\"]", onclick)
                    href = match.group(1) if match else ''
                else:
                    continue
                
                if href and not href.startswith(('#', 'javascript:')):
                    full_url = urljoin(base_url, href)
                    if not self._is_aggregator_link(full_url):
                        if self._is_form_link(full_url):
                            return full_url, 'google_form', None
                        return full_url, 'apply_button', None
        
        # Look for form links anywhere in content
        content = soup.select_one('.job-content, .entry-content, article, main')
        if content:
            for a in content.find_all('a', href=True):
                href = a['href']
                if self._is_form_link(href):
                    return href, 'google_form', None
        
        # Look for email
        text = soup.get_text()
        
        # Common patterns in Ethiopian job posts
        email_section_patterns = [
            re.compile(r'(?:send|submit|email)[^.]*?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', re.I),
            re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})[^.]*(?:apply|application|cv|resume)', re.I),
        ]
        
        for pattern in email_section_patterns:
            match = pattern.search(text)
            if match:
                email = match.group(1)
                if '@' in email and not any(x in email.lower() for x in ['example', 'test', 'domain']):
                    return None, 'email', email.lower()
        
        # Fall back to base
        return super().find_best_apply_link(soup, html, base_url)
    
    async def scrape(self, url: str) -> ScrapedJob:
        """Scrape ethioworks with additional data extraction"""
        result = await super().scrape(url)
        
        if result.success and result.raw_html:
            soup = BeautifulSoup(result.raw_html, 'html.parser')
            
            # Extract structured details
            details = self.extract_job_details_table(soup)
            
            if details:
                result.scraped_data['table_data'] = details
                
                if not result.company and details.get('company'):
                    result.company = details['company']
                if not result.location and details.get('location'):
                    result.location = details['location']
                if not result.deadline and details.get('deadline'):
                    result.deadline = details['deadline']
                if not result.salary and details.get('salary'):
                    result.salary = details['salary']
        
        return result