# scrapers/generic.py
from typing import Dict, Optional
from bs4 import BeautifulSoup
import re
import trafilatura
from .base import BaseScraper

class GenericScraper(BaseScraper):
    """Generic scraper for unknown job sites"""
    
    def __init__(self):
        super().__init__()
        self.name = "generic"
    
    def parse(self, soup: BeautifulSoup, url: str) -> Dict:
        """Generic parsing for any job site"""
        
        result = {
            'url': url,
            'source': 'generic',
            'title': None,
            'company': None,
            'description': None,
            'requirements': [],
            'responsibilities': [],
            'education': None,
            'experience': None,
            'salary': None,
            'location': None,
            'deadline': None,
            'how_to_apply': None,
            'apply_email': None,
            'apply_phone': None,
            'raw_text': None,
        }
        
        # Get title
        title = soup.find('h1')
        if title:
            result['title'] = self.clean_text(title.get_text())
        
        # Use trafilatura for clean text extraction
        try:
            html_str = str(soup)
            clean_text = trafilatura.extract(html_str)
            if clean_text:
                result['raw_text'] = clean_text
                result['description'] = clean_text[:2000]
                
                # Extract fields from clean text
                result['deadline'] = self.extract_deadline(clean_text)
                result['apply_email'] = self.extract_email(clean_text)
                result['apply_phone'] = self.extract_phone(clean_text)
                result['location'] = self._extract_location(clean_text)
                result['salary'] = self._extract_salary(clean_text)
        except Exception as e:
            print(f"⚠️ [generic] trafilatura error: {e}")
        
        # Fallback to body text
        if not result['raw_text']:
            body = soup.find('body')
            if body:
                result['raw_text'] = body.get_text(separator='\n')[:5000]
                result['description'] = result['raw_text'][:2000]
        
        return result
    
    def _extract_location(self, text: str) -> Optional[str]:
        """Extract location"""
        match = re.search(r'[Ll]ocation[:\s]+([^\n]+)', text)
        if match:
            return self.clean_text(match.group(1))[:200]
        return None
    
    def _extract_salary(self, text: str) -> Optional[str]:
        """Extract salary"""
        match = re.search(r'[Ss]alary[:\s]+([^\n]+)', text)
        if match:
            return self.clean_text(match.group(1))[:200]
        return None