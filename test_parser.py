"""
Test the Telegram URL parser - Run this FIRST
No database or internet needed!
"""

from telegram_parser import TelegramParser

def test_url_cleaning():
    """Test that dirty URLs get cleaned properly"""
    
    parser = TelegramParser()
    
    print("=" * 60)
    print("🧪 TEST 1: URL CLEANING")
    print("=" * 60)
    
    # Test cases: (dirty_url, expected_clean_url)
    test_cases = [
        # Trailing asterisks
        ("https://effoysira.com/job-title/****", "https://effoysira.com/job-title/"),
        ("https://effoysira.com/developer***", "https://effoysira.com/developer"),
        
        # Trailing dots
        ("https://kebenajobs.com/accountant....", "https://kebenajobs.com/accountant"),
        ("www.harmeejobs.com/manager...", "https://www.harmeejobs.com/manager"),
        
        # Mixed junk
        ("https://ethioworks.com/job***###", "https://ethioworks.com/job"),
        ("https://abayjobs.com/vacancy!!!", "https://abayjobs.com/vacancy"),
        
        # Special characters
        ("https://effoysira.com/job~~~", "https://effoysira.com/job"),
        ("https://effoysira.com/position•••", "https://effoysira.com/position"),
        
        # No protocol
        ("www.effoysira.com/job", "https://www.effoysira.com/job"),
        ("effoysira.com/test****", "https://effoysira.com/test"),
    ]
    
    passed = 0
    failed = 0
    
    for dirty, expected in test_cases:
        cleaned = parser.clean_url(dirty)
        
        # Remove trailing slash for comparison
        cleaned_normalized = cleaned.rstrip('/') if cleaned else None
        expected_normalized = expected.rstrip('/') if expected else None
        
        if cleaned_normalized == expected_normalized:
            print(f"  ✅ PASS: {dirty[:40]}...")
            passed += 1
        else:
            print(f"  ❌ FAIL: {dirty}")
            print(f"       Expected: {expected}")
            print(f"       Got:      {cleaned}")
            failed += 1
    
    print(f"\n  Results: {passed} passed, {failed} failed")
    return failed == 0


def test_url_extraction():
    """Test extracting URLs from message text"""
    
    parser = TelegramParser()
    
    print("\n" + "=" * 60)
    print("🧪 TEST 2: URL EXTRACTION FROM MESSAGES")
    print("=" * 60)
    
    test_messages = [
        {
            "text": """📢 Software Developer Needed!
            Company: Tech Ethiopia
            Apply: https://effoysira.com/software-dev/****
            Deadline: Dec 30""",
            "expected_domain": "effoysira.com"
        },
        {
            "text": """🔔 Accountant Position
            More info: www.kebenajobs.com/accountant....
            Send CV before January""",
            "expected_domain": "kebenajobs.com"
        },
        {
            "text": """Hiring: Marketing Manager
            Link: harmeejobs.com/marketing***###
            Location: Addis Ababa""",
            "expected_domain": "harmeejobs.com"
        },
        {
            "text": """New job alert!
            Check: https://ethioworks.com/driver-needed~~~
            Apply now!""",
            "expected_domain": "ethioworks.com"
        },
    ]
    
    passed = 0
    
    for i, test in enumerate(test_messages, 1):
        parsed = parser.parse_message(test["text"])
        
        print(f"\n  Message {i}:")
        print(f"    Title: {parsed.title}")
        print(f"    URLs found: {len(parsed.urls)}")
        
        if parsed.urls:
            first_url = parsed.urls[0]
            print(f"    First URL: {first_url}")
            
            if test["expected_domain"] in first_url:
                print(f"    ✅ Correct domain found!")
                passed += 1
            else:
                print(f"    ❌ Expected domain: {test['expected_domain']}")
        else:
            print(f"    ❌ No URLs extracted!")
    
    print(f"\n  Results: {passed}/{len(test_messages)} passed")
    return passed == len(test_messages)


def test_info_extraction():
    """Test extracting job info from messages"""
    
    parser = TelegramParser()
    
    print("\n" + "=" * 60)
    print("🧪 TEST 3: JOB INFO EXTRACTION")
    print("=" * 60)
    
    message = """📢 Senior Software Developer Needed!

Company: Ethio Telecom
Location: Addis Ababa
Salary: 50,000 - 80,000 ETB

Requirements:
- 5+ years experience
- Python, JavaScript

Apply before: January 15, 2025

Link: https://effoysira.com/ethio-telecom-developer/****"""
    
    parsed = parser.parse_message(message)
    
    print(f"\n  Extracted Data:")
    print(f"    Title: {parsed.title}")
    print(f"    Company: {parsed.company}")
    print(f"    Location: {parsed.location}")
    print(f"    Deadline: {parsed.deadline}")
    print(f"    URLs: {parsed.urls}")
    
    # Check results
    checks = [
        ("Title found", parsed.title is not None),
        ("URL cleaned", parsed.urls and "****" not in parsed.urls[0]),
    ]
    
    for name, result in checks:
        status = "✅" if result else "❌"
        print(f"    {status} {name}")
    
    return all(result for _, result in checks)


def run_all_tests():
    """Run all parser tests"""
    
    print("\n" + "=" * 60)
    print("🚀 TELEGRAM PARSER TESTS")
    print("=" * 60)
    
    results = []
    
    results.append(("URL Cleaning", test_url_cleaning()))
    results.append(("URL Extraction", test_url_extraction()))
    results.append(("Info Extraction", test_info_extraction()))
    
    print("\n" + "=" * 60)
    print("📊 FINAL RESULTS")
    print("=" * 60)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n  🎉 All tests passed!")
    else:
        print("\n  ⚠️ Some tests failed. Check the output above.")
    
    return all_passed


if __name__ == "__main__":
    run_all_tests()