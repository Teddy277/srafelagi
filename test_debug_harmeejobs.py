# test_debug_harmeejobs.py
"""
Debug script to see exactly what's being fetched from HarmeeJobs
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup

async def debug_fetch():
    url = "https://harmeejobs.com/company/mercy-corps/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    print(f"🔍 Fetching: {url}\n")
    
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url, headers=headers, ssl=False) as response:
                print(f"📊 Status: {response.status}")
                print(f"📊 Final URL: {response.url}")
                print(f"📊 Content-Type: {response.headers.get('Content-Type', 'Unknown')}")
                
                html = await response.text()
                print(f"📊 HTML Length: {len(html)} characters\n")
                
                # Save raw HTML for inspection
                with open("debug_harmeejobs.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 Saved raw HTML to: debug_harmeejobs.html\n")
                
                # Parse and analyze
                soup = BeautifulSoup(html, 'html.parser')
                
                # Check for Cloudflare challenge
                if "challenge" in html.lower() or "cf-browser-verification" in html.lower():
                    print("⚠️ CLOUDFLARE CHALLENGE DETECTED!")
                    print("   The site is blocking automated requests.\n")
                    return
                
                # Check for JavaScript requirement
                noscript = soup.find('noscript')
                if noscript and "javascript" in noscript.get_text().lower():
                    print("⚠️ JAVASCRIPT REQUIRED!")
                    print(f"   Message: {noscript.get_text()[:200]}\n")
                
                # Print page title
                title = soup.find('title')
                print(f"📄 Page Title: {title.get_text() if title else 'No title'}\n")
                
                # Look for job listings
                print("🔍 Looking for job listings...\n")
                
                # Method 1: Job cards
                job_cards = soup.select('.job_listing, .job-listing, .job-card, .job-item, article.job')
                print(f"   Job cards found: {len(job_cards)}")
                
                # Method 2: Tables
                tables = soup.find_all('table')
                print(f"   Tables found: {len(tables)}")
                for i, table in enumerate(tables):
                    rows = table.find_all('tr')
                    print(f"      Table {i+1}: {len(rows)} rows")
                
                # Method 3: Links to /job/
                job_links = [a for a in soup.find_all('a', href=True) if '/job/' in a['href']]
                print(f"   Links to /job/ pages: {len(job_links)}")
                
                # Method 4: Any lists
                all_lists = soup.find_all(['ul', 'ol'])
                print(f"   Lists (ul/ol) found: {len(all_lists)}")
                
                # Print found job links
                if job_links:
                    print("\n📋 Found job links:")
                    for link in job_links[:10]:
                        print(f"   - {link.get_text(strip=True)[:50]}")
                        print(f"     URL: {link['href']}")
                
                # Print all h1, h2, h3 tags to understand structure
                print("\n📑 Page structure (headings):")
                for h in soup.find_all(['h1', 'h2', 'h3'])[:15]:
                    print(f"   <{h.name}>: {h.get_text(strip=True)[:60]}")
                
                # Look for main content area
                print("\n📦 Content containers:")
                containers = [
                    '.entry-content', '.job-content', '.content', 
                    'article', 'main', '.company-jobs', '.job-listings'
                ]
                for selector in containers:
                    elem = soup.select_one(selector)
                    if elem:
                        text_preview = elem.get_text(strip=True)[:100]
                        print(f"   {selector}: Found ({len(elem.get_text())} chars)")
                        print(f"      Preview: {text_preview}...")
                
                # Check for specific HarmeeJobs structure
                print("\n🔎 HarmeeJobs specific elements:")
                specific = [
                    '.company-name', '.company-header', '.job_listings',
                    '.wpjm-jobs-wrapper', '.job-manager-jobs', '#job-manager-job-dashboard'
                ]
                for selector in specific:
                    elem = soup.select_one(selector)
                    print(f"   {selector}: {'✅ Found' if elem else '❌ Not found'}")
                
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_fetch())