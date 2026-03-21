# test_abayjobs.py
import asyncio
from scrapers.abayjobs import AbayJobsScraper

async def test():
    scraper = AbayJobsScraper()
    result = await scraper.scrape(
        "https://abayjobs.com/national-election-board-of-ethiopia-vacancy-5861"
    )

    print(f"Title: {result.title}")
    print(f"Company: {result.company}")
    print(f"Email: {result.apply_email}")
    print(f"Apply URL: {result.apply_url}")
    print(f"Success: {result.success}")
    desc_len = len(result.description) if result.description else 0
    print(f"Description: {desc_len} chars")

    if result.description:
        print()
        print("=" * 60)
        print(result.description[:800])
        print("=" * 60)
    else:
        print("EMPTY!")

    if hasattr(scraper, 'session') and scraper.session:
        await scraper.session.close()

asyncio.run(test())