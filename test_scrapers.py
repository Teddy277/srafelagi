"""
Test web scrapers - Requires internet connection
"""

import asyncio
from scrapers import scrape_job_url, ScraperFactory


async def test_single_url(url: str):
    """Test scraping a single URL"""
    
    print(f"\n{'='*60}")
    print(f"📌 Testing: {url}")
    print("-" * 60)
    
    try:
        result = await scrape_job_url(url)
        
        print(f"  ✓ Success: {result.success}")
        print(f"  ✓ Title: {result.title or 'Not found'}")
        print(f"  ✓ Company: {result.company or 'Not found'}")
        print(f"  ✓ Location: {result.location or 'Not found'}")
        print(f"  ✓ Description: {len(result.description or '')} chars")
        print(f"  ✓ Apply URL: {result.apply_url or 'Not found'}")
        print(f"  ✓ Apply Email: {result.apply_email or 'Not found'}")
        print(f"  ✓ Apply Type: {result.apply_type or 'Not found'}")
        
        if result.error:
            print(f"  ⚠️ Error: {result.error}")
        
        return result.success
        
    except Exception as e:
        print(f"  ❌ Exception: {e}")
        return False


async def test_with_real_urls():
    """Test with real job URLs (may fail if pages don't exist)"""
    
    print("\n" + "=" * 60)
    print("🌐 LIVE SCRAPER TESTS")
    print("Note: These may fail if the specific job pages no longer exist")
    print("=" * 60)
    
    # These are example URLs - replace with real ones
    test_urls = [
        "https://www.effoysira.com",  # Test homepage
        "https://www.kebenajobs.com",
        "https://harmeejobs.com",
    ]
    
    results = []
    
    for url in test_urls:
        success = await test_single_url(url)
        results.append((url, success))
    
    print("\n" + "=" * 60)
    print("📊 RESULTS SUMMARY")
    print("=" * 60)
    
    for url, success in results:
        status = "✅" if success else "❌"
        domain = url.split('/')[2]
        print(f"  {status} {domain}")


async def test_scraper_factory():
    """Test that correct scraper is selected for each domain"""
    
    print("\n" + "=" * 60)
    print("🏭 SCRAPER FACTORY TESTS")
    print("=" * 60)
    
    test_cases = [
        ("https://effoysira.com/job", "EffoysiraScraper"),
        ("https://www.effoysira.com/job", "EffoysiraScraper"),
        ("https://harmeejobs.com/position", "HarmeeJobsScraper"),
        ("https://ethioworks.com/vacancy", "EthioworksScraper"),
        ("https://kebenajobs.com/job", "KebenaJobsScraper"),
        ("https://unknown-site.com/job", "GenericScraper"),
    ]
    
    for url, expected_scraper in test_cases:
        scraper = ScraperFactory.get_scraper(url)
        actual = scraper.__class__.__name__
        
        if actual == expected_scraper:
            print(f"  ✅ {url[:35]}... → {actual}")
        else:
            print(f"  ❌ {url[:35]}...")
            print(f"       Expected: {expected_scraper}")
            print(f"       Got: {actual}")


async def test_apply_link_detection():
    """Test apply link detection with mock HTML"""
    
    print("\n" + "=" * 60)
    print("🔗 APPLY LINK DETECTION TESTS")
    print("=" * 60)
    
    from scrapers.base import GenericScraper
    from bs4 import BeautifulSoup
    
    scraper = GenericScraper()
    
    # Test HTML with various apply links
    test_html = """
    <html>
    <body>
        <h1>Software Developer</h1>
        <p>Great job opportunity!</p>
        
        <h2>How to Apply</h2>
        <p>Submit your application via Google Form:</p>
        <a href="https://forms.google.com/d/1234567">Apply Now</a>
        
        <p>Or email us at: <a href="mailto:jobs@company.com">jobs@company.com</a></p>
        
        <a href="https://effoysira.com/other-job">Other Jobs</a>
    </body>
    </html>
    """
    
    soup = BeautifulSoup(test_html, 'html.parser')
    
    apply_url, apply_type, apply_email = scraper.find_best_apply_link(
        soup, test_html, "https://example.com"
    )
    
    print(f"  Apply URL: {apply_url}")
    print(f"  Apply Type: {apply_type}")
    print(f"  Apply Email: {apply_email}")
    
    # Verify Google Form was found (highest priority)
    if apply_url and "forms.google.com" in apply_url:
        print("  ✅ Correctly prioritized Google Form!")
    elif apply_email == "jobs@company.com":
        print("  ✅ Found email as fallback!")
    else:
        print("  ❌ Apply link detection failed")


async def run_all_tests():
    """Run all scraper tests"""
    
    print("\n" + "=" * 60)
    print("🚀 SCRAPER TESTS")
    print("=" * 60)
    
    # Test 1: Factory
    await test_scraper_factory()
    
    # Test 2: Apply link detection (no internet needed)
    await test_apply_link_detection()
    
    # Test 3: Live tests (needs internet)
    print("\n" + "-" * 60)
    response = input("Run live scraper tests? (requires internet) [y/N]: ")
    
    if response.lower() == 'y':
        await test_with_real_urls()
    else:
        print("  Skipping live tests.")
    
    print("\n" + "=" * 60)
    print("✅ Scraper tests complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())