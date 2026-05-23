"""
Telegram Message Parser - Robust URL extraction and cleaning
Handles junk characters, partial URLs, and various message formats
"""

import re
from urllib.parse import urlparse, urlunparse, urljoin
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ParsedJob:
    """Structured job data from Telegram message"""
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    urls: List[str] = None
    deadline: Optional[str] = None
    raw_text: str = ""
    
    def __post_init__(self):
        if self.urls is None:
            self.urls = []


class TelegramParser:
    """
    Parses Telegram messages to extract job information.
    Aggressively cleans URLs to prevent 404 errors.
    """
    
    # Characters that are commonly appended as junk
    JUNK_CHARS = set('*#@!~`^+=[]{}|\\<>()…•·●○◦▪▫■□▲△▼▽◆◇★☆✓✔✕✖✗✘')
    
    # Pattern for trailing junk (multiple special chars or dots at end)
    TRAILING_JUNK_PATTERN = re.compile(
        r'[\*\#\@\!\~\`\^\+\=\[\]\{\}\|\\\<\>\(\)…•·●○◦▪▫■□▲△▼▽◆◇★☆✓✔✕✖✗✘\.\-\_]+$'
    )
    
    # Pattern for repeated characters at end (like ****, ...., ----)
    REPEATED_CHARS_PATTERN = re.compile(r'(.)\1{2,}$')
    
    # Known job aggregator domains
    AGGREGATOR_DOMAINS = [
        'effoysira.com', 'kebenajobs.com', 'harmeejobs.com',
        'ethioworks.com', 'abayjobs.com', 'ethiopianjobs.net',
        'ethiojobs.net', 'jobsearchethiopia.com', 'ezega.com',
        'afriwork.com', 'jobwebethiopia.com', 'ethiopianreporter.com'
    ]
    
    # URL extraction patterns (ordered by priority)
    URL_PATTERNS = [
        # Full URLs with protocol
        re.compile(
            r'https?://[^\s<>\"\'\)\]\}，。！？；：""'']+',
            re.IGNORECASE
        ),
        # URLs without protocol (www.)
        re.compile(
            r'www\.[a-zA-Z0-9][a-zA-Z0-9\-]*\.[a-zA-Z]{2,}[^\s<>\"\'\)\]\}，。！？；：""'']*',
            re.IGNORECASE
        ),
        # Domain patterns commonly seen
        re.compile(
            r'(?:[a-zA-Z0-9\-]+\.)?(?:effoysira|kebenajobs|harmeejobs|ethioworks|abayjobs)\.com[^\s<>\"\'\)\]\}]*',
            re.IGNORECASE
        ),
    ]
    
    # Title extraction patterns
    TITLE_PATTERNS = [
        re.compile(r'^[📢📣🔔💼🏢👔]\s*(.+?)(?:\n|$)', re.MULTILINE),
        re.compile(r'(?:position|job\s*title|vacancy|hiring)[:\s]+(.+?)(?:\n|$)', re.IGNORECASE),
        re.compile(r'^(.+?)\s*(?:wanted|needed|required|vacancy)', re.IGNORECASE | re.MULTILINE),
        re.compile(r'^([A-Z][A-Za-z\s\-\/]+)(?:\n|$)', re.MULTILINE),  # Title case first line
    ]
    
    # Company extraction patterns  
    COMPANY_PATTERNS = [
        re.compile(r'(?:company|organization|employer|org)[:\s]+(.+?)(?:\n|$)', re.IGNORECASE),
        re.compile(r'(?:at|@)\s+([A-Z][A-Za-z\s\-&\.]+?)(?:\n|,|$)', re.IGNORECASE),
        re.compile(r'([A-Z][A-Za-z\s\-&\.]+?)\s+(?:is\s+)?(?:hiring|looking|seeking)', re.IGNORECASE),
    ]
    
    # Location patterns
    LOCATION_PATTERNS = [
        re.compile(r'(?:location|place|city|area)[:\s]+(.+?)(?:\n|$)', re.IGNORECASE),
        re.compile(r'(?:in|at)\s+(Addis\s*Ababa|Bahir\s*Dar|Hawassa|Dire\s*Dawa|Mekelle|Gondar|Jimma|Adama)', re.IGNORECASE),
    ]
    
    # Deadline patterns
    DEADLINE_PATTERNS = [
        re.compile(r'(?:deadline|closing\s*date|apply\s*before|ends?)[:\s]+(.+?)(?:\n|$)', re.IGNORECASE),
        re.compile(r'(?:until|by|before)\s+(\w+\s+\d{1,2},?\s*\d{4})', re.IGNORECASE),
    ]

    def __init__(self):
        self.stats = {
            'urls_cleaned': 0,
            'urls_rejected': 0,
            'messages_parsed': 0
        }

    def clean_url(self, url: str) -> Optional[str]:
        """
        Aggressively clean a URL by removing trailing junk.
        Returns None if URL is invalid after cleaning.
        """
        if not url:
            return None
            
        original_url = url
        
        # Step 1: Basic strip
        url = url.strip()
        
        # Step 2: Remove common trailing junk characters
        while url and url[-1] in self.JUNK_CHARS:
            url = url[:-1]
        
        # Step 3: Remove trailing dots, dashes, underscores (repeated)
        url = self.TRAILING_JUNK_PATTERN.sub('', url)
        
        # Step 4: Handle repeated characters like **** or ....
        url = self.REPEATED_CHARS_PATTERN.sub('', url)
        
        # Step 5: Remove trailing slash if it's the only path
        if url.endswith('/') and url.count('/') == 3:
            url = url[:-1]
            
        # Step 6: Remove trailing punctuation that got captured
        while url and url[-1] in '.,;:!?\'"':
            url = url[:-1]
        
        # Step 7: Ensure protocol exists
        if not url.startswith(('http://', 'https://')):
            if url.startswith('www.'):
                url = 'https://' + url
            else:
                # Try to add https:// for known domains
                for domain in self.AGGREGATOR_DOMAINS:
                    if domain in url:
                        if not url.startswith('http'):
                            url = 'https://' + url
                        break
        
        # Step 8: Validate the cleaned URL
        if not self._is_valid_url(url):
            logger.debug(f"URL rejected after cleaning: {original_url} -> {url}")
            self.stats['urls_rejected'] += 1
            return None
        
        if url != original_url:
            logger.info(f"URL cleaned: {original_url} -> {url}")
            self.stats['urls_cleaned'] += 1
            
        return url

    def _is_valid_url(self, url: str) -> bool:
        """Validate URL structure"""
        try:
            parsed = urlparse(url)
            
            # Must have scheme and netloc
            if not parsed.scheme or not parsed.netloc:
                return False
            
            # Scheme must be http or https
            if parsed.scheme not in ('http', 'https'):
                return False
            
            # Domain must have at least one dot
            if '.' not in parsed.netloc:
                return False
            
            # Domain parts must be valid
            domain_parts = parsed.netloc.split('.')
            if any(len(part) == 0 for part in domain_parts):
                return False
            
            # TLD must be at least 2 characters
            if len(domain_parts[-1]) < 2:
                return False
                
            return True
            
        except Exception:
            return False

    def extract_urls(self, text: str) -> List[str]:
        """Extract all URLs from text and clean them"""
        if not text:
            return []
        
        urls = set()
        
        # Try each pattern
        for pattern in self.URL_PATTERNS:
            matches = pattern.findall(text)
            for match in matches:
                cleaned = self.clean_url(match)
                if cleaned:
                    urls.add(cleaned)
        
        # Sort by priority: /job/ or /company/ pages first, then aggregator domain, then longer (more specific) URLs
        def url_priority(u: str):
            has_job_path = '/job/' in u or '/company/' in u
            is_aggregator = any(d in u for d in self.AGGREGATOR_DOMAINS)
            return (
                not has_job_path,   # job/company pages first
                not is_aggregator,  # then aggregator domains
                -len(u)             # then longer URLs (more specific) before homepage
            )
        sorted_urls = sorted(urls, key=url_priority)
        
        return sorted_urls

    # Lines that are metadata/labels, not job titles (e.g. HaHuJobs format)
    NON_TITLE_LINES = re.compile(
        r'^(quantity|quanitity|full\s+description|description|deadline|how\s+to\s+apply|'
        r'location|company|employer|duties|requirements|salary|experience|'
        r'\*\s*\d|^\d{1,2}[\s/\-]\d|'
        r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2})',
        re.IGNORECASE
    )

    def extract_title(self, text: str) -> Optional[str]:
        """Extract job title from message. Skips metadata lines like Quantity, Full description, dates."""
        for pattern in self.TITLE_PATTERNS:
            match = pattern.search(text)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                title = title.strip(':-–—')
                if 5 < len(title) < 150 and not self.NON_TITLE_LINES.match(title.strip()):
                    return title

        # Fallback: first line that looks like a title (skip Quantity, Full description, date-only)
        lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
        for line in lines:
            if line.startswith('http') or line.startswith('#') or line.startswith('**'):
                continue
            if self.NON_TITLE_LINES.match(line):
                continue
            if re.match(r'^[\d\*\s\-/]+$', line) or re.match(r'^[A-Za-z]+\s+\d{1,2},?\s*\d{4}$', line):
                continue
            if 5 < len(line) < 100:
                return line
        if lines and 5 < len(lines[0]) < 100 and not lines[0].startswith('http'):
            return lines[0]
        return None

    def extract_company(self, text: str) -> Optional[str]:
        """Extract company name from message"""
        for pattern in self.COMPANY_PATTERNS:
            match = pattern.search(text)
            if match:
                company = match.group(1).strip()
                company = re.sub(r'\s+', ' ', company)
                if 2 < len(company) < 100:
                    return company
        return None

    def extract_location(self, text: str) -> Optional[str]:
        """Extract job location from message"""
        for pattern in self.LOCATION_PATTERNS:
            match = pattern.search(text)
            if match:
                location = match.group(1).strip()
                if len(location) < 50:
                    return location
        return None

    def extract_deadline(self, text: str) -> Optional[str]:
        """Extract application deadline from message"""
        for pattern in self.DEADLINE_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1).strip()
        return None

    def parse_message(self, text: str, entities: List[Any] = None) -> ParsedJob:
        """
        Parse a Telegram message and extract job information.
        
        Args:
            text: The message text
            entities: Telegram message entities (for extracting URLs from buttons/links)
        """
        self.stats['messages_parsed'] += 1
        
        # Extract URLs from text
        urls = self.extract_urls(text)
        
        # Also extract URLs from entities if available
        if entities:
            for entity in entities:
                if hasattr(entity, 'url') and entity.url:
                    cleaned = self.clean_url(entity.url)
                    if cleaned and cleaned not in urls:
                        urls.insert(0, cleaned)  # Priority to entity URLs
        
        return ParsedJob(
            title=self.extract_title(text),
            company=self.extract_company(text),
            location=self.extract_location(text),
            urls=urls,
            deadline=self.extract_deadline(text),
            raw_text=text
        )

    def get_best_url(self, parsed: ParsedJob) -> Optional[str]:
        """Get the best URL to scrape from parsed job"""
        if not parsed.urls:
            return None
        return parsed.urls[0]  # Already sorted by priority

    def get_stats(self) -> Dict[str, int]:
        """Get parsing statistics"""
        return self.stats.copy()


# Convenience function for quick parsing
def parse_telegram_message(text: str, entities: List[Any] = None) -> ParsedJob:
    """Quick parse function"""
    parser = TelegramParser()
    return parser.parse_message(text, entities)


# Test function
if __name__ == "__main__":
    test_messages = [
        """📢 Software Developer Needed!
        Company: Tech Ethiopia PLC
        Location: Addis Ababa
        
        Apply here: https://effoysira.com/software-developer-job/****
        Deadline: December 30, 2024""",
        
        """🔔 Accountant Position at XYZ Bank
        
        More info: www.kebenajobs.com/accountant-xyz....
        
        Send CV before January 15""",
        
        """Hiring: Marketing Manager
        at ABC Corporation (Addis Ababa)
        
        Link: harmeejobs.com/marketing-manager-abc***###""",
    ]
    
    parser = TelegramParser()
    
    for i, msg in enumerate(test_messages, 1):
        print(f"\n{'='*50}")
        print(f"Test Message {i}:")
        parsed = parser.parse_message(msg)
        print(f"  Title: {parsed.title}")
        print(f"  Company: {parsed.company}")
        print(f"  Location: {parsed.location}")
        print(f"  Deadline: {parsed.deadline}")
        print(f"  URLs: {parsed.urls}")
    
    print(f"\n{'='*50}")
    print(f"Stats: {parser.get_stats()}")