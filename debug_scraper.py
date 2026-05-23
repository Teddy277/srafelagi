# debug_scraper.py
import asyncio
from scrapers import ScraperFactory

# A sample URL from your logs (KebenaJobs)
TEST_URL = "https://kebenajobs.com/ethiopost-19/"
DOMAIN = "kebenajobs.com"

async def test():
    print(f"🔬 DEBUGGING SCRAPER for: {TEST_URL}")
    
    scraper = ScraperFactory.get_scraper(DOMAIN)
    result = await scraper.scrape(TEST_URL)
    
    if not result:
        print("❌ Scraper returned None")
        return

    print("\n" + "="*50)
    print("RESULTS:")
    print("="*50)
    
    desc_len = len(result.get('description', ''))
    print(f"📝 Description Length: {desc_len} characters")
    print(f"🔗 Apply URL found:    {result.get('apply_url')}")
    print(f"📧 Email found:        {result.get('apply_email')}")
    
    print("\n📄 Start of Description:")
    print("-" * 20)
    print(result.get('description', '')[:300] + "...")
    print("-" * 20)

    if desc_len < 500:
        print("\n⚠️ WARNING: Description is suspiciously short!")
    else:
        print("\n✅ SUCCESS: Long description extracted!")

if __name__ == "__main__":
    asyncio.run(test())