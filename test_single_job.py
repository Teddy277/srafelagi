# test_simple_fetch.py
"""
Simple fetch test without Playwright
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re

async def test_fetch():
    urls = [
        "https://harmeejobs.com/job/food-information-reporting-assistant/",
        "https://harmeejobs.com/jobs/",
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    timeout = aiohttp.ClientTimeout(total=60)  # 60 second timeout
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for url in urls:
            print(f"\n{'='*60}")
            print(f"🌐 Fetching: {url}")
            print(f"{'='*60}")
            
            try:
                async with session.get(url, headers=headers, ssl=False) as response:
                    print(f"   Status: {response.status}")
                    
                    if response.status == 200:
                        html = await response.text()
                        print(f"   HTML Length: {len(html)} chars")
                        
                        # Save for inspection
                        filename = url.split('/')[-2] + ".html"
                        with open(filename, "w", encoding="utf-8") as f:
                            f.write(html)
                        print(f"   💾 Saved to: {filename}")
                        
                        # Quick parse
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Title
                        title = soup.select_one('h1')
                        if title:
                            print(f"   📌 Title: {title.get_text(strip=True)[:60]}")
                        
                        # Look for job listings
                        jobs = soup.select('.job_listing, .job-listing, li.job, article.job')
                        print(f"   📋 Job elements found: {len(jobs)}")
                        
                        # Look for job links
                        job_links = [a for a in soup.find_all('a', href=True) if '/job/' in a['href']]
                        print(f"   🔗 Job links found: {len(job_links)}")
                        
                        for link in job_links[:5]:
                            print(f"      - {link.get_text(strip=True)[:40]}: {link['href'][:50]}")
                    else:
                        print(f"   ❌ Failed with status {response.status}")
                        
            except asyncio.TimeoutError:
                print(f"   ❌ Timeout!")
            except Exception as e:
                print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_fetch())