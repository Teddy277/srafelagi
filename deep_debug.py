# test_afriwork_full.py
import asyncio
from scrapers.afriwork import AfriworkScraper

async def test():
    scraper = AfriworkScraper()
    
    uuid = "fdd6a20f-4906-43ee-af18-86728d85d208"
    
    print(f"🔍 Scraping UUID: {uuid}\n")
    
    result = await scraper.scrape(f"https://afriworket.com/jobs/{uuid}")
    
    print(f"Success: {result.success}")
    print(f"Title: {result.title}")
    print(f"Company: {result.company}")
    print(f"Location: {result.location}")
    print(f"Email: {result.apply_email}")
    print(f"\nDescription ({len(result.description or '')} chars):")
    print("=" * 50)
    print(result.description[:2000] if result.description else "None")

if __name__ == "__main__":
    asyncio.run(test())