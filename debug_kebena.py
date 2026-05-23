import asyncio
from scrapers import ScraperFactory

# The URL that failed for you
URL = "https://kebenajobs.com/almighty-media-and-promotion-plc-2/"

async def test():
    print(f"🔬 Debugging: {URL}")
    scraper = ScraperFactory.get_scraper("kebenajobs.com")
    result = await scraper.scrape(URL)
    
    print("\n" + "="*40)
    print(f"📝 Description Length: {len(result.get('description', ''))}")
    print(f"🔗 Apply URL: {result.get('apply_url')}")
    print(f"📧 Email: {result.get('apply_email')}")
    print("="*40)
    
    if not result.get('apply_url'):
        print("\n❌ FAILED TO FIND APPLY LINK")
        # Print all links found to see why
        from bs4 import BeautifulSoup
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.get(URL) as resp:
                text = await resp.text()
                soup = BeautifulSoup(text, 'lxml')
                print("\nFound these links on page:")
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if 'http' in href and 'kebenajobs' not in href:
                        print(f" - {href}")

asyncio.run(test())