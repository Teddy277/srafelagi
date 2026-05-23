"""
Base Scraper - IMPROVED VERSION
Better description extraction and apply link handling
"""

import re
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field
import aiohttp
from bs4 import BeautifulSoup

# Try to import trafilatura
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ScrapedJob:
    """Complete scraped job data"""
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    salary: Optional[str] = None
    deadline: Optional[str] = None
    source_url: str = ""
    apply_url: Optional[str] = None  # Regular URL (not mailto)
    apply_email: Optional[str] = None  # Email address only
    apply_type: Optional[str] = None
    raw_html: str = ""
    scraped_data: Dict[str, Any] = field(default_factory=dict)
    success: bool = False
    error: Optional[str] = None


class BaseScraper(ABC):
    """Base class for all job scrapers"""
    
    # Form patterns
    FORM_PATTERNS = [
        re.compile(r'forms\.google\.com', re.I),
        re.compile(r'docs\.google\.com/forms', re.I),
        re.compile(r'forms\.office\.com', re.I),
        re.compile(r'typeform\.com', re.I),
        re.compile(r'jotform\.com', re.I),
    ]
    
    # Email pattern
    EMAIL_PATTERN = re.compile(
        r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'
    )
    
    # Domains to skip
    SKIP_DOMAINS = {
        'effoysira.com', 'kebenajobs.com', 'harmeejobs.com',
        'ethioworks.com', 'abayjobs.com', 'ethiopianjobs.net',
        'themeisle.com', 'developer.wordpress.org', 'wordpress.org',
        'facebook.com', 'm.facebook.com', 'twitter.com', 'x.com',
        'instagram.com', 'linkedin.com', 'youtube.com',
        'whatsapp.com', 'wa.me', 't.me', 'telegram.me',
        'play.google.com', 'apps.apple.com',
        'bit.ly', 'tinyurl.com', 'goo.gl',
        'fonts.googleapis.com', 'ajax.googleapis.com',
    }
    
    # Site-generic emails to skip
    SKIP_EMAILS = {
        'info@harmeejobs.com', 'info@effoysira.com', 'info@kebenajobs.com',
        'contact@harmeejobs.com', 'admin@harmeejobs.com',
    }
    
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]
    
    def __init__(self, timeout: int = 30):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def fetch_page(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Fetch page HTML"""
        if not self.session:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        
        headers = {
            'User-Agent': self.USER_AGENTS[0],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        for attempt in range(3):
            try:
                async with self.session.get(url, headers=headers, allow_redirects=True, ssl=False) as response:
                    if response.status == 200:
                        html = await response.text()
                        return html, str(response.url)
                    elif response.status == 404:
                        logger.warning(f"404 Not Found: {url}")
                        return None, None
            except asyncio.TimeoutError:
                logger.warning(f"Timeout (attempt {attempt + 1}): {url}")
            except Exception as e:
                logger.error(f"Fetch error: {e}")
                break
            await asyncio.sleep(1)
        
        return None, None

    def clean_title(self, title: str) -> str:
        """Clean up job title"""
        if not title:
            return title
        
        # Remove common suffixes
        patterns = [
            r'Full\s*Time.*$', r'Part\s*Time.*$', r'NEW$', r'HOT$',
            r'\s*[-–|]\s*$', r'\s*[-–|]\s*Effoysira.*$', r'\s*[-–|]\s*Kebena.*$',
        ]
        for pattern in patterns:
            title = re.sub(pattern, '', title, flags=re.I)
        
        return ' '.join(title.split()).strip()

    def decode_cloudflare_email(self, encoded: str) -> Optional[str]:
        """Decode Cloudflare protected email"""
        try:
            r = int(encoded[:2], 16)
            email = ''.join(chr(int(encoded[i:i+2], 16) ^ r) for i in range(2, len(encoded), 2))
            if self.EMAIL_PATTERN.match(email):
                return email.lower()
        except:
            pass
        return None

    def extract_description(self, html: str, soup: BeautifulSoup) -> Optional[str]:
        """Extract FULL job description - IMPROVED"""
        description = None
        
        # Method 1: Try trafilatura first (usually best quality)
        if TRAFILATURA_AVAILABLE:
            try:
                description = trafilatura.extract(
                    html,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False,
                    include_formatting=True,
                )
                if description and len(description) > 200:
                    return description.strip()
            except Exception as e:
                logger.debug(f"Trafilatura failed: {e}")
        
        # Method 2: Look for specific content containers (priority order)
        content_selectors = [
            '.entry-content',          # WordPress
            '.job-content',            # Job sites
            '.job-description',        # Job sites
            'article .content',        # Generic
            '.post-content',           # Blog-style
            '.single-content',         # Single post
            '.job-details',            # Job details
            'article',                 # Article tag
            '.content',                # Generic content
            'main',                    # Main content
        ]
        
        for selector in content_selectors:
            elem = soup.select_one(selector)
            if elem:
                # Remove unwanted elements
                for unwanted in elem.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe', '.sharedaddy', '.social-share', '.post-navigation', '.comments']):
                    unwanted.decompose()
                
                text = elem.get_text(separator='\n', strip=True)
                
                # Clean up the text
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                text = '\n'.join(lines)
                
                if len(text) > 200:
                    return text
        
        # Method 3: Get all paragraph text from body
        body = soup.find('body')
        if body:
            # Remove unwanted sections
            for unwanted in body.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
                unwanted.decompose()
            
            paragraphs = body.find_all('p')
            text = '\n'.join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20])
            
            if len(text) > 200:
                return text
        
        return description

    def extract_emails(self, soup: BeautifulSoup, html: str) -> List[str]:
        """Extract all valid email addresses"""
        emails = set()
        
        # 1. Decode Cloudflare emails
        for match in re.findall(r'data-cfemail="([a-f0-9]+)"', html):
            decoded = self.decode_cloudflare_email(match)
            if decoded:
                emails.add(decoded)
        
        # 2. Find mailto links
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('mailto:'):
                email = href[7:].split('?')[0].strip().lower()
                if self.EMAIL_PATTERN.match(email):
                    emails.add(email)
        
        # 3. Find emails in "How to Apply" sections
        for heading in soup.find_all(['h2', 'h3', 'h4', 'strong', 'b']):
            text = heading.get_text(strip=True).lower()
            if any(phrase in text for phrase in ['how to apply', 'application', 'apply', 'send cv', 'send resume']):
                parent = heading.parent
                if parent:
                    found = self.EMAIL_PATTERN.findall(parent.get_text())
                    for email in found:
                        emails.add(email.lower())
        
        # 4. Find emails in content with context
        text = soup.get_text()
        context_patterns = [
            r'(?:email|e-mail|mail)[:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'(?:send|submit|forward)[^.]*?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})[^.]*?(?:apply|application|cv|resume)',
        ]
        
        for pattern in context_patterns:
            matches = re.findall(pattern, text, re.I)
            for email in matches:
                emails.add(email.lower())
        
        # Filter invalid emails
        valid = []
        for email in emails:
            if email in self.SKIP_EMAILS:
                continue
            if len(email) > 50:
                continue
            if any(x in email for x in ['example', 'test', 'sample', 'domain.com']):
                continue
            valid.append(email)
        
        return valid

    def extract_apply_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """Extract apply links (NOT mailto - those go to emails)"""
        candidates = []
        
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            text = a.get_text(strip=True).lower()
            
            # Skip empty, javascript, or mailto links
            if not href or href.startswith(('javascript:', '#', 'tel:', 'mailto:')):
                continue
            
            # Make absolute URL
            try:
                full_url = urljoin(base_url, href)
            except:
                continue
            
            # Skip aggregator domains
            try:
                domain = urlparse(full_url).netloc.lower().replace('www.', '')
                if any(skip in domain for skip in self.SKIP_DOMAINS):
                    continue
            except:
                continue
            
            # Score the link
            priority = 100
            link_type = 'external'
            
            # Form links (highest priority)
            if any(p.search(full_url) for p in self.FORM_PATTERNS):
                priority = 1
                link_type = 'google_form' if 'google' in full_url else 'form'
            
            # Apply button text
            elif any(word in text for word in ['apply now', 'apply here', 'submit application', 'click to apply']):
                priority = 5
                link_type = 'apply_button'
            
            # Apply in URL
            elif '/apply' in full_url.lower():
                priority = 10
                link_type = 'apply_url'
            
            # Career/jobs portal
            elif any(x in full_url.lower() for x in ['/careers', '/jobs', '/vacancy', '/recruitment']):
                priority = 15
                link_type = 'portal'
            
            else:
                continue  # Skip unrelated links
            
            candidates.append({
                'url': full_url,
                'type': link_type,
                'priority': priority,
                'text': text[:50]
            })
        
        candidates.sort(key=lambda x: x['priority'])
        return candidates

    def extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract and clean job title"""
        selectors = [
            'h1.entry-title', 'h1.job-title', '.job-title h1',
            'h1[itemprop="title"]', '.title h1', 'article h1', 'h1'
        ]
        
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                title = self.clean_title(elem.get_text(strip=True))
                if 5 < len(title) < 200:
                    return title
        
        # Fallback to og:title
        meta = soup.find('meta', property='og:title')
        if meta and meta.get('content'):
            title = meta['content']
            title = re.split(r'\s*[\|\-–]\s*', title)[0]
            title = self.clean_title(title)
            if 5 < len(title) < 200:
                return title
        
        return None

    def extract_company(self, soup: BeautifulSoup, text: str) -> Optional[str]:
        """Extract company name"""
        # From specific elements
        selectors = ['.company-name', '.company', '.employer', '[itemprop="hiringOrganization"]']
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                company = elem.get_text(strip=True)
                if 2 < len(company) < 100:
                    return company
        
        # From text patterns
        patterns = [
            r'(?:company|organization|employer)[:\s]+([A-Za-z0-9\s\-&\.]+?)(?:\n|,|$)',
            r'^([A-Z][A-Za-z0-9\s\-&\.]+?)\s+(?:is hiring|vacancy|job)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.M)
            if match:
                company = match.group(1).strip()
                if 3 < len(company) < 80:
                    return company
        
        return None

    def extract_location(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract job location"""
        selectors = ['.job-location', '.location', '[itemprop="jobLocation"]']
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                return elem.get_text(strip=True)[:100]
        
        # Ethiopian cities
        text = soup.get_text().lower()
        cities = ['addis ababa', 'bahir dar', 'hawassa', 'dire dawa', 'mekelle', 'gondar', 'jimma', 'adama']
        for city in cities:
            if city in text:
                return city.title()
        
        if 'ethiopia' in text:
            return 'Ethiopia'
        
        return None

    def extract_deadline(self, text: str) -> Optional[str]:
        """Extract application deadline"""
        patterns = [
            r'deadline[:\s]+([A-Za-z]+\s+\d{1,2},?\s*\d{4})',
            r'closing\s*date[:\s]+([A-Za-z]+\s+\d{1,2},?\s*\d{4})',
            r'apply\s*(?:before|by)[:\s]+([A-Za-z]+\s+\d{1,2},?\s*\d{4})',
            r'deadline[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(1).strip()[:50]
        return None

    async def scrape(self, url: str) -> ScrapedJob:
        """Main scraping method"""
        result = ScrapedJob(source_url=url)
        
        try:
            # Fetch page
            html, final_url = await self.fetch_page(url)
            
            if not html:
                result.error = "Failed to fetch page"
                return result
            
            result.raw_html = html
            result.source_url = final_url or url
            
            # Parse HTML
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove scripts/styles
            for tag in soup.find_all(['script', 'style', 'noscript']):
                tag.decompose()
            
            text = soup.get_text()
            
            # Extract data
            result.title = self.extract_title(soup)
            result.company = self.extract_company(soup, text)
            result.location = self.extract_location(soup)
            result.description = self.extract_description(html, soup)
            result.deadline = self.extract_deadline(text)
            
            # Extract apply methods
            # 1. Get emails
            emails = self.extract_emails(soup, html)
            if emails:
                result.apply_email = emails[0]
                result.apply_type = 'email'
            
            # 2. Get apply links
            links = self.extract_apply_links(soup, result.source_url)
            if links:
                best_link = links[0]
                result.apply_url = best_link['url']
                result.apply_type = best_link['type']
            
            # Log what we found
            if result.description:
                logger.info(f"   📝 Description: {len(result.description)} chars")
            if result.apply_url:
                logger.info(f"   🔗 Apply URL: {result.apply_url[:50]}")
            if result.apply_email:
                logger.info(f"   📧 Apply Email: {result.apply_email}")
            
            result.success = True
            
        except Exception as e:
            result.error = str(e)
            logger.error(f"Scraping error for {url}: {e}")
        
        return result

    @abstractmethod
    def get_domain(self) -> str:
        pass


class GenericScraper(BaseScraper):
    """Generic scraper for unknown domains"""
    def get_domain(self) -> str:
        return "*"