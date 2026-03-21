# test_scraper_direct.py
"""
Direct test of the HarmeeJobs scraper
"""

import asyncio
import sys

# Add project root to path
sys.path.insert(0, '.')

from scrapers import get_scraper, HarmeeJobsScraper

async def test():
    url = "https://harmeejobs.com/company/mercy-corps/"
    
    print(f"\n{'='*60}")
    print(f"Testing URL: {url}")
    print(f"{'='*60}\n")
    
    # Get scraper
    scraper = get_scraper(url)
    print(f"Scraper class: {scraper.__class__.__name__}")
    
    # Verify it's the right one
    if not isinstance(scraper, HarmeeJobsScraper):
        print("⚠️ WARNING: Not using HarmeeJobsScraper!")
    
    # Run scrape
    async with scraper:
        result = await scraper.scrape(url)
    
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"Success: {result.success}")
    print(f"Error: {result.error}")
    print(f"Title: {result.title}")
    print(f"Company: {result.company}")
    print(f"Apply Email: {result.apply_email}")
    print(f"Apply URL: {result.apply_url}")
    
    if result.description:
        print(f"\n--- DESCRIPTION ({len(result.description)} chars) ---")
        print(result.description[:2000])
        if len(result.description) > 2000:
            print("\n... [truncated]")
    else:
        print("\n⚠️ NO DESCRIPTION!")

if __name__ == "__main__":
    asyncio.run(test())