# search_raw_html.py
"""
Search the debug_rendered.html for job content
"""

import re

def search():
    try:
        with open("debug_rendered.html", "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        print("❌ File not found! Run the playwright test first.")
        return
    
    print(f"📄 Loaded {len(html)} characters\n")
    
    # Convert to lowercase for searching
    html_lower = html.lower()
    
    # Search for job titles mentioned in the Telegram post
    search_terms = [
        'driver',
        'monitoring evaluation',
        'mel specialist',
        'consortium program manager',
        'merl advisor',
        'monitoring, evaluation',
        'food information',
        'logistics',
        'regional finance',
    ]
    
    print("=" * 70)
    print("🔍 SEARCHING FOR JOB TITLES")
    print("=" * 70)
    
    for term in search_terms:
        if term.lower() in html_lower:
            print(f"\n✅ FOUND: '{term}'")
            
            # Find and show context
            idx = html_lower.find(term.lower())
            start = max(0, idx - 100)
            end = min(len(html), idx + 200)
            context = html[start:end]
            
            # Clean up
            context = ' '.join(context.split())
            print(f"   Context: ...{context}...")
        else:
            print(f"❌ NOT FOUND: '{term}'")
    
    # Search for common job-related patterns
    print("\n" + "=" * 70)
    print("🔍 SEARCHING FOR JOB-RELATED HTML PATTERNS")
    print("=" * 70)
    
    patterns = [
        (r'job_listing[^"]*"', "WP Job Manager listings"),
        (r'class="[^"]*position[^"]*"', "Position classes"),
        (r'class="[^"]*vacancy[^"]*"', "Vacancy classes"),
        (r'href="[^"]*job[^"]*"', "Job links"),
        (r'<li[^>]*class="[^"]*job[^"]*"', "Job list items"),
        (r'data-job', "Job data attributes"),
    ]
    
    for pattern, desc in patterns:
        matches = re.findall(pattern, html, re.I)
        if matches:
            print(f"\n✅ {desc}: Found {len(matches)} matches")
            for m in matches[:5]:
                print(f"   - {m[:60]}")
        else:
            print(f"❌ {desc}: No matches")
    
    # Look for URLs that might be job detail pages
    print("\n" + "=" * 70)
    print("🔍 SEARCHING FOR HARMEEJOBS LINKS")
    print("=" * 70)
    
    links = re.findall(r'href="(https?://[^"]*harmeejobs[^"]*)"', html, re.I)
    unique_links = list(set(links))
    
    print(f"\nFound {len(unique_links)} unique HarmeeJobs links:")
    for link in sorted(unique_links):
        print(f"   {link}")
    
    # Check if there's content in main area
    print("\n" + "=" * 70)
    print("🔍 COMPANY DATA SECTION")
    print("=" * 70)
    
    # Find company-data section
    match = re.search(r'class="company-data[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.S | re.I)
    if match:
        content = match.group(1)
        # Clean HTML
        clean = re.sub(r'<[^>]+>', ' ', content)
        clean = ' '.join(clean.split())
        print(f"Company data content:\n{clean[:500]}...")
    else:
        print("Company data section not found in expected format")
    
    # Look for JSON data
    print("\n" + "=" * 70)
    print("🔍 SEARCHING FOR JSON DATA")
    print("=" * 70)
    
    # Look for embedded JSON
    json_matches = re.findall(r'<script[^>]*type="application/(?:ld\+)?json"[^>]*>(.*?)</script>', html, re.S | re.I)
    for i, json_str in enumerate(json_matches):
        if 'job' in json_str.lower() or 'position' in json_str.lower():
            print(f"\n📋 JSON block {i+1} (contains job-related content):")
            print(json_str[:300])
    
    if not json_matches:
        print("No JSON-LD blocks found")

if __name__ == "__main__":
    search()