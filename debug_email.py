import asyncio
from scrapers import ScraperFactory

URL = "https://kebenajobs.com/almighty-media-and-promotion-plc-2/"

async def test():
    print(f"🔬 Testing Cloudflare Decoding...")
    scraper = ScraperFactory.get_scraper("kebenajobs.com")
    result = await scraper.scrape(URL)
    
    print(f"\n📧 Email Found: {result.get('apply_email')}")
    print(f"🔗 Apply URL:  {result.get('apply_url')}")
    
    if result.get('apply_email'):
        print("\n✅ SUCCESS! Email decoded!")
    else:
        print("\n❌ FAILED. Still hidden.")

asyncio.run(test())