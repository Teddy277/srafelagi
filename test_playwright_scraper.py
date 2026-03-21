# test_playwright_scraper.py
import asyncio
import sys
sys.path.insert(0, '.')

from scrapers import get_scraper

async def test():
    url = "https://harmeejobs.com/company/mercy-corps/"
    
    print(f"\n{'='*60}")
    print(f"Testing: {url}")
    print(f"{'='*60}\n")
    
    scraper = get_scraper(url)
    
    async with scraper:
        result = await scraper.scrape(url)
    
    print(f"\n{'='*60}")
    print("FINAL RESULTS")
    print(f"{'='*60}")
    print(f"Success: {result.success}")
    print(f"Error: {result.error}")
    print(f"Title: {result.title}")
    print(f"Company: {result.company}")
    print(f"Apply Email: {result.apply_email}")
    
    if result.description:
        print(f"\n--- DESCRIPTION ({len(result.description)} chars) ---")
        print(result.description[:3000])
    else:
        print("\n⚠️ NO DESCRIPTION!")

if __name__ == "__main__":
    asyncio.run(test())