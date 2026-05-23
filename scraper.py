# scraper.py
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import trafilatura
import re
from urllib.parse import urlparse

class JobScraper:
    """Scrapes full job details from various Ethiopian job sites"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        # Site-specific parsers
        self.site_parsers = {
            'effoysira.com': self.parse_effoysira,
            'ethiojobs.net': self.parse_ethiojobs,
            'jobsinethiopia.net': self.parse_jobsinethiopia,
            'ethiopianreporter.com': self.parse_reporter,
            'zayride.com': self.parse_zayride,
        }
    
    async def fetch_page(self, url, timeout=15):
        """Fetch HTML content from URL"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, 
                    headers=self.headers, 
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    ssl=False
                ) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        print(f"❌ Failed to fetch {url}: Status {response.status}")
                        return None
        except asyncio.TimeoutError:
            print(f"⏰ Timeout fetching {url}")
            return None
        except Exception as e:
            print(f"❌ Error fetching {url}: {e}")
            return None
    
    async def scrape_job(self, url):
        """Main method to scrape any job URL"""
        
        if not url:
            return None
        
        html = await self.fetch_page(url)
        if not html:
            return None
        
        # Find matching parser
        domain = urlparse(url).netloc.replace('www.', '')
        
        for site, parser in self.site_parsers.items():
            if site in domain:
                return parser(html, url)
        
        # Default generic parser
        return self.parse_generic(html, url)
    
    def parse_effoysira(self, html, url):
        """Parser for effoysira.com"""
        soup = BeautifulSoup(html, 'lxml')
        
        job = {
            'source': 'effoysira.com',
            'url': url,
            'title': None,
            'organization': None,
            'description': None,
            'requirements': [],
            'responsibilities': [],
            'salary': None,
            'location': None,
            'deadline': None,
            'experience': None,
            'education': None,
            'job_type': None,
            'how_to_apply': None,
            'positions': [],
            'raw_text': None
        }
        
        # Title
        title_tag = soup.find('h1', class_='entry-title') or soup.find('h1')
        if title_tag:
            job['title'] = title_tag.get_text(strip=True)
        
        # Main content
        content = soup.find('div', class_='entry-content') or soup.find('article')
        if content:
            job['raw_text'] = content.get_text(separator='\n', strip=True)
            
            # Extract structured data
            text = job['raw_text']
            
            # Organization
            org_match = re.search(r'(?:Company|Organization|ድርጅት)[:\s]+(.+)', text, re.I)
            if org_match:
                job['organization'] = org_match.group(1).strip()[:200]
            
            # Deadline
            deadline_patterns = [
                r'[Dd]eadline[:\s]+([^\n]+)',
                r'ማብቂያ[:\s]+([^\n]+)',
                r'Closing [Dd]ate[:\s]+([^\n]+)',
            ]
            for pattern in deadline_patterns:
                match = re.search(pattern, text)
                if match:
                    job['deadline'] = match.group(1).strip()[:100]
                    break
            
            # Location
            location_match = re.search(r'(?:Location|Place|ቦታ)[:\s]+([^\n]+)', text, re.I)
            if location_match:
                job['location'] = location_match.group(1).strip()
            
            # Salary
            salary_match = re.search(r'(?:Salary|ደመወዝ)[:\s]+([^\n]+)', text, re.I)
            if salary_match:
                job['salary'] = salary_match.group(1).strip()
            
            # Experience
            exp_match = re.search(r'(?:Experience|ልምድ)[:\s]+([^\n]+)', text, re.I)
            if exp_match:
                job['experience'] = exp_match.group(1).strip()
            
            # Education
            edu_match = re.search(r'(?:Education|Qualification|ትምህርት)[:\s]+([^\n]+)', text, re.I)
            if edu_match:
                job['education'] = edu_match.group(1).strip()
            
            # How to apply
            apply_section = re.search(
                r'(?:How to [Aa]pply|Application|ማመልከቻ)[:\s]*(.+?)(?=\n\n|\Z)', 
                text, 
                re.S
            )
            if apply_section:
                job['how_to_apply'] = apply_section.group(1).strip()[:500]
            
            # Extract requirements section
            req_section = re.search(
                r'(?:Requirements?|Qualifications?|መስፈርቶች)[:\s]*(.+?)(?=Responsibilities|Duties|How to|Application|\Z)',
                text,
                re.S | re.I
            )
            if req_section:
                requirements = re.findall(r'[•\-\*]\s*(.+)', req_section.group(1))
                job['requirements'] = requirements[:20]
            
            # Extract responsibilities
            resp_section = re.search(
                r'(?:Responsibilities|Duties|ኃላፊነት)[:\s]*(.+?)(?=Requirements|Qualifications|How to|Application|\Z)',
                text,
                re.S | re.I
            )
            if resp_section:
                responsibilities = re.findall(r'[•\-\*]\s*(.+)', resp_section.group(1))
                job['responsibilities'] = responsibilities[:20]
            
            # Get full description using trafilatura (cleaner text)
            clean_text = trafilatura.extract(html)
            if clean_text:
                job['description'] = clean_text[:5000]
        
        return job
    
    def parse_ethiojobs(self, html, url):
        """Parser for ethiojobs.net"""
        soup = BeautifulSoup(html, 'lxml')
        
        job = {
            'source': 'ethiojobs.net',
            'url': url,
            'title': None,
            'organization': None,
            'description': None,
            'requirements': [],
            'salary': None,
            'location': None,
            'deadline': None,
            'experience': None,
            'education': None,
            'job_type': None,
            'raw_text': None
        }
        
        # Title
        title = soup.find('h1') or soup.find('h2', class_='job-title')
        if title:
            job['title'] = title.get_text(strip=True)
        
        # Company
        company = soup.find('a', class_='company-name') or soup.find('div', class_='company')
        if company:
            job['organization'] = company.get_text(strip=True)
        
        # Job details section
        details = soup.find('div', class_='job-details') or soup.find('div', class_='job-description')
        if details:
            job['raw_text'] = details.get_text(separator='\n', strip=True)
            job['description'] = job['raw_text'][:5000]
        
        # Extract from meta/structured elements
        for item in soup.find_all('li', class_='job-meta-item'):
            text = item.get_text(strip=True).lower()
            value = item.get_text(strip=True).split(':')[-1].strip()
            
            if 'location' in text:
                job['location'] = value
            elif 'deadline' in text or 'closing' in text:
                job['deadline'] = value
            elif 'salary' in text:
                job['salary'] = value
            elif 'experience' in text:
                job['experience'] = value
        
        return job
    
    def parse_jobsinethiopia(self, html, url):
        """Parser for jobsinethiopia.net"""
        # Similar structure to ethiojobs
        return self.parse_ethiojobs(html, url)
    
    def parse_reporter(self, html, url):
        """Parser for Ethiopian Reporter jobs"""
        soup = BeautifulSoup(html, 'lxml')
        
        job = {
            'source': 'ethiopianreporter.com',
            'url': url,
            'title': None,
            'description': None,
            'raw_text': None
        }
        
        article = soup.find('article') or soup.find('div', class_='content')
        if article:
            title = article.find('h1')
            job['title'] = title.get_text(strip=True) if title else None
            job['raw_text'] = article.get_text(separator='\n', strip=True)
            job['description'] = job['raw_text'][:5000]
        
        return job
    
    def parse_zayride(self, html, url):
        """Parser for zayride.com"""
        soup = BeautifulSoup(html, 'lxml')
        
        job = {
            'source': 'zayride.com',
            'url': url,
            'title': None,
            'description': None,
            'raw_text': None
        }
        
        content = soup.find('div', class_='entry-content') or soup.find('article')
        if content:
            title = soup.find('h1', class_='entry-title')
            job['title'] = title.get_text(strip=True) if title else None
            job['raw_text'] = content.get_text(separator='\n', strip=True)
            
            # Use trafilatura for clean extraction
            clean = trafilatura.extract(html)
            job['description'] = clean[:5000] if clean else job['raw_text'][:5000]
        
        return job
    
    def parse_generic(self, html, url):
        """Generic parser for unknown sites"""
        soup = BeautifulSoup(html, 'lxml')
        
        job = {
            'source': urlparse(url).netloc,
            'url': url,
            'title': None,
            'description': None,
            'raw_text': None
        }
        
        # Try to get title
        title = soup.find('h1')
        if title:
            job['title'] = title.get_text(strip=True)
        
        # Use trafilatura for content extraction (works on most sites)
        clean_text = trafilatura.extract(html)
        if clean_text:
            job['description'] = clean_text[:5000]
            job['raw_text'] = clean_text
        else:
            # Fallback to body text
            body = soup.find('body')
            if body:
                job['raw_text'] = body.get_text(separator='\n', strip=True)[:5000]
        
        return job


# Quick test
async def test_scraper():
    scraper = JobScraper()
    url = "https://effoysira.com/national-election-board-of-ethiopia-vacancy"
    result = await scraper.scrape_job(url)
    print(result)

if __name__ == '__main__':
    asyncio.run(test_scraper())