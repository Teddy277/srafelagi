"""
Test with REAL job pages from Ethiopian job sites
Uses correct category/listing pages for each site
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
from scrapers import scrape_job_url
from urllib.parse import urljoin, urlparse
import re


class JobURLFinder:
    """Smart job URL finder for Ethiopian job sites"""
    
    # Site-specific JOB LISTING pages (not homepages!)
    SITE_CONFIGS = {
        'effoysira.com': {
            'listing_pages': [
                'https://effoysira.com/category/job/',
                'https://www.effoysira.com/category/job/',
            ],
            'job_link_selectors': [
                'h2.entry-title a',
                'h3.entry-title a', 
                '.entry-title a',
                'article a',
                '.post-title a',
                '.jeg_post_title a',
                'h2 a',
                'h3 a',
            ],
            'skip_patterns': [
                '/category/', '/tag/', '/page/', '/author/',
                'wp-login', 'wp-admin', '#', 'javascript:',
                'facebook.com', 'twitter.com', 't.me', 'telegram',
            ]
        },
        'kebenajobs.com': {
            'listing_pages': [
                'https://kebenajobs.com/category/jobs/',
                'https://www.kebenajobs.com/category/jobs/',
                'https://kebenajobs.com/',
            ],
            'job_link_selectors': [
                'h2.entry-title a',
                '.entry-title a',
                'article h2 a',
                'h2 a',
                'h3 a',
            ],
            'skip_patterns': [
                '/category/', '/tag/', '/page/',
                'wp-login', '#', 'javascript:',
            ]
        },
        'harmeejobs.com': {
            'listing_pages': [
                'https://harmeejobs.com/jobs/',
                'https://harmeejobs.com/job-listings/',
                'https://harmeejobs.com/',
            ],
            'job_link_selectors': [
                '.job_listing a',
                '.job-title a',
                'h2 a',
                'h3 a',
                'article a',
            ],
            'skip_patterns': [
                'wp-login', 'lostpassword', '/page/',
                '#', 'javascript:', 'my-account',
            ]
        },
        'ethioworks.com': {
            'listing_pages': [
                'https://ethioworks.com/jobs/',
                'https://ethioworks.com/',
            ],
            'job_link_selectors': [
                '.job-title a',
                'h2 a',
                'h3 a',
                'article a',
            ],
            'skip_patterns': [
                'wp-login', '/page/', '#', 'javascript:',
            ]
        },
    }
    
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        )
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    def _get_site_config(self, site_key: str) -> dict:
        """Get configuration for a site"""
        for key, config in self.SITE_CONFIGS.items():
            if key in site_key:
                return config
        return None
    
    def _should_skip_url(self, url: str, skip_patterns: list) -> bool:
        """Check if URL should be skipped"""
        url_lower = url.lower()
        for pattern in skip_patterns:
            if pattern in url_lower:
                return True
        return False
    
    def _looks_like_job_url(self, url: str, base_domain: str) -> bool:
        """Check if URL looks like a job posting"""
        try:
            parsed = urlparse(url)
            path = parsed.path.lower()
            
            # Must be on same domain
            if base_domain not in parsed.netloc:
                return False
            
            # Must have a path with content
            if len(path) < 10:
                return False
            
            # Must have hyphens (slug-style URL)
            if '-' not in path:
                return False
            
            # Must not be a category/tag page
            if '/category/' in path or '/tag/' in path or '/page/' in path:
                return False
            
            return True
            
        except Exception:
            return False
    
    async def find_job_urls_from_listing(self, listing_url: str, config: dict, max_jobs: int = 3) -> list:
        """Find job URLs from a listing/category page"""
        
        print(f"\n  📂 Checking: {listing_url}")
        
        try:
            async with self.session.get(listing_url, ssl=False) as response:
                if response.status != 200:
                    print(f"     ❌ HTTP {response.status}")
                    return []
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                job_urls = []
                seen = set()
                base_domain = urlparse(listing_url).netloc.replace('www.', '')
                
                # Try each selector
                for selector in config['job_link_selectors']:
                    if len(job_urls) >= max_jobs:
                        break
                    
                    elements = soup.select(selector)
                    
                    for elem in elements:
                        if len(job_urls) >= max_jobs:
                            break
                        
                        href = elem.get('href', '')
                        if not href:
                            continue
                        
                        # Make absolute
                        full_url = urljoin(listing_url, href)
                        
                        # Skip if seen
                        if full_url in seen:
                            continue
                        seen.add(full_url)
                        
                        # Skip unwanted URLs
                        if self._should_skip_url(full_url, config['skip_patterns']):
                            continue
                        
                        # Check if it looks like a job URL
                        if self._looks_like_job_url(full_url, base_domain):
                            job_urls.append(full_url)
                            title = elem.get_text(strip=True)[:50]
                            print(f"     ✅ Found: {title}...")
                
                return job_urls
                
        except Exception as e:
            print(f"     ❌ Error: {e}")
            return []
    
    async def find_jobs_for_site(self, site_name: str, max_jobs: int = 2) -> list:
        """Find job URLs for a specific site"""
        
        print(f"\n🌐 SITE: {site_name.upper()}")
        print("=" * 50)
        
        config = self._get_site_config(site_name)
        if not config:
            print(f"  ⚠️ No configuration for {site_name}")
            return []
        
        all_job_urls = []
        
        for listing_url in config['listing_pages']:
            if len(all_job_urls) >= max_jobs:
                break
            
            urls = await self.find_job_urls_from_listing(
                listing_url, 
                config, 
                max_jobs - len(all_job_urls)
            )
            all_job_urls.extend(urls)
        
        print(f"\n  📊 Total job URLs found: {len(all_job_urls)}")
        return all_job_urls


async def test_job_page(url: str) -> dict:
    """Test scraping a single job page"""
    
    print(f"\n{'─'*60}")
    print(f"📄 Scraping: {url[:65]}...")
    print("─" * 60)
    
    try:
        result = await scrape_job_url(url)
        
        if result.success:
            print(f"  ✅ SUCCESS")
            print(f"  📌 Title: {result.title or 'Not found'}")
            print(f"  🏢 Company: {result.company or 'Not found'}")
            print(f"  📍 Location: {result.location or 'Not found'}")
            print(f"  📝 Description: {len(result.description or '')} characters")
            print(f"  ⏰ Deadline: {result.deadline or 'Not found'}")
            
            print()
            if result.apply_url:
                print(f"  🔗 APPLY URL: {result.apply_url}")
                print(f"     Type: {result.apply_type}")
            if result.apply_email:
                print(f"  📧 APPLY EMAIL: {result.apply_email}")
            
            if not result.apply_url and not result.apply_email:
                print(f"  ⚠️ No apply link or email found")
            
            return {
                'url': url,
                'success': True,
                'has_apply': bool(result.apply_url or result.apply_email),
                'title': result.title,
                'apply_url': result.apply_url,
                'apply_email': result.apply_email,
            }
        else:
            print(f"  ❌ FAILED: {result.error}")
            return {'url': url, 'success': False, 'has_apply': False}
            
    except Exception as e:
        print(f"  ❌ Exception: {e}")
        return {'url': url, 'success': False, 'has_apply': False}


async def run_tests():
    """Main test runner"""
    
    print("=" * 60)
    print("🚀 ETHIOPIAN JOB SCRAPER - REAL PAGE TESTS")
    print("=" * 60)
    print("\nThis test finds ACTUAL job postings and tests scraping them.\n")
    
    sites_to_test = [
        'effoysira.com',
        'kebenajobs.com',
        'harmeejobs.com',
    ]
    
    all_results = []
    
    async with JobURLFinder() as finder:
        for site in sites_to_test:
            # Find job URLs
            job_urls = await finder.find_jobs_for_site(site, max_jobs=2)
            
            if not job_urls:
                print(f"\n  ⚠️ No jobs found on {site}")
                continue
            
            # Test each job
            for url in job_urls:
                result = await test_job_page(url)
                all_results.append(result)
                await asyncio.sleep(1)  # Be nice to servers
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 FINAL SUMMARY")
    print("=" * 60)
    
    if not all_results:
        print("\n  ⚠️ No job pages were tested successfully")
        print("\n  💡 Try the manual test instead:")
        print("     python quick_test.py")
        return
    
    successful = [r for r in all_results if r.get('success')]
    with_apply = [r for r in successful if r.get('has_apply')]
    
    print(f"\n  📈 Results:")
    print(f"     Total tested: {len(all_results)}")
    print(f"     Successfully scraped: {len(successful)}")
    print(f"     Found apply link/email: {len(with_apply)}")
    
    if successful:
        print(f"\n  📋 Jobs scraped:")
        for r in successful:
            icon = "✅" if r.get('has_apply') else "⚠️"
            title = (r.get('title') or 'Unknown title')[:40]
            print(f"     {icon} {title}")
            if r.get('apply_url'):
                print(f"        → {r['apply_url'][:50]}...")
            elif r.get('apply_email'):
                print(f"        → {r['apply_email']}")
    
    # Success rate
    if all_results:
        success_rate = len(successful) / len(all_results) * 100
        apply_rate = len(with_apply) / max(len(successful), 1) * 100
        print(f"\n  📊 Scrape success rate: {success_rate:.0f}%")
        print(f"  📊 Apply link found rate: {apply_rate:.0f}%")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())