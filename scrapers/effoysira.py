"""
Scraper for effoysira.com - IMPROVED
Better description and apply link extraction
"""

from bs4 import BeautifulSoup
from typing import Optional, Tuple, List
from urllib.parse import urljoin
from .base import BaseScraper, ScrapedJob
import re
import logging

logger = logging.getLogger(__name__)


class EffoysiraScraper(BaseScraper):
    """Specialized scraper for effoysira.com"""
    
    def get_domain(self) -> str:
        return "effoysira.com"
    
    def extract_description(self, html: str, soup: BeautifulSoup) -> Optional[str]:
        """Effoysira-specific description extraction"""
        
        # Try entry-content first (WordPress standard)
        content = soup.select_one('.entry-content')
        
        if content:
            # Remove share buttons, navigation, ads
            for unwanted in content.find_all(['script', 'style', '.sharedaddy', '.social-share', 
                                               '.post-navigation', '.comments', '.related-posts',
                                               '.jeg_share', '.jeg_post_tags', 'ins', 'iframe']):
                unwanted.decompose()
            
            # Get all text content
            paragraphs = []
            
            for elem in content.find_all(['p', 'li', 'h2', 'h3', 'h4', 'strong']):
                text = elem.get_text(strip=True)
                if text and len(text) > 5:
                    # Add heading markers
                    if elem.name in ['h2', 'h3', 'h4']:
                        text = f"\n\n{text}\n"
                    paragraphs.append(text)
            
            description = '\n'.join(paragraphs)
            
            # Clean up
            description = re.sub(r'\n{3,}', '\n\n', description)
            description = description.strip()
            
            if len(description) > 200:
                return description
        
        # Fallback to base method
        return super().extract_description(html, soup)
    
    def extract_company(self, soup: BeautifulSoup, text: str) -> Optional[str]:
        """Extract company from effoysira"""
        
        # Try title pattern: "Company Name Job Vacancy"
        title = soup.select_one('h1.entry-title, h1')
        if title:
            title_text = title.get_text(strip=True)
            
            patterns = [
                r'^([A-Z][A-Za-z0-9\s\-&\.]+?)\s+(?:Job Vacancy|Vacancy|Career|Hiring|Jobs)',
                r'^([A-Z][A-Za-z0-9\s\-&\.]+?)\s+(?:is hiring|is looking)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, title_text, re.I)
                if match:
                    company = match.group(1).strip()
                    # Clean common suffixes
                    company = re.sub(r'\s+(PLC|Plc|plc|SC|S\.C\.|Ltd|LLC)\.?$', r' \1', company)
                    if 3 < len(company) < 60:
                        return company
        
        # Look in content
        content = soup.select_one('.entry-content')
        if content:
            content_text = content.get_text()
            
            patterns = [
                r'(?:Company|Organization|Employer|About)[:\s]+([A-Z][A-Za-z0-9\s\-&\.]+?)(?:\n|,|is)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, content_text)
                if match:
                    company = match.group(1).strip()
                    if 3 < len(company) < 60:
                        return company
        
        return super().extract_company(soup, text)
    
    def extract_emails(self, soup: BeautifulSoup, html: str) -> List[str]:
        """Enhanced email extraction for effoysira"""
        emails = super().extract_emails(soup, html)
        
        # Also look specifically in entry-content
        content = soup.select_one('.entry-content')
        if content:
            content_text = content.get_text()
            
            # Find emails near application context
            patterns = [
                r'(?:send|submit|email|apply)[^.]*?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+-]+@(?!effoysira\.com)[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, content_text, re.I)
                for email in matches:
                    email_lower = email.lower()
                    if email_lower not in self.SKIP_EMAILS and email_lower not in emails:
                        if len(email_lower) < 50:
                            emails.append(email_lower)
        
        return emails
    
    async def scrape(self, url: str) -> ScrapedJob:
        """Scrape effoysira with enhanced extraction"""
        result = await super().scrape(url)
        
        if result.success and result.raw_html:
            soup = BeautifulSoup(result.raw_html, 'html.parser')
            text = soup.get_text()
            
            # Try to improve company if not found
            if not result.company:
                result.company = self.extract_company(soup, text)
            
            # Try to find email if no apply method found
            if not result.apply_url and not result.apply_email:
                emails = self.extract_emails(soup, result.raw_html)
                if emails:
                    result.apply_email = emails[0]
                    result.apply_type = 'email'
        
        return result