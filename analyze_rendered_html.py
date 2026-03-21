# analyze_rendered_html.py
"""
Analyze the debug_rendered.html to find job listings structure
"""

from bs4 import BeautifulSoup
import re

def analyze():
    # Load the rendered HTML
    try:
        with open("debug_rendered.html", "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        print("❌ debug_rendered.html not found! Run test_playwright_scraper.py first.")
        return
    
    print(f"📄 Loaded {len(html)} characters\n")
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Remove scripts/styles for cleaner analysis
    for tag in soup.find_all(['script', 'style', 'noscript']):
        tag.decompose()
    
    # ══════════════════════════════════════════════════════════════
    # SEARCH 1: Find elements containing job-related keywords
    # ══════════════════════════════════════════════════════════════
    
    print("=" * 70)
    print("🔍 SEARCH 1: Elements containing job keywords")
    print("=" * 70)
    
    job_keywords = ['driver', 'monitoring', 'evaluation', 'specialist', 'coordinator', 
                   'advisor', 'manager', 'mel', 'merl', 'consortium', 'program']
    
    found_elements = []
    
    for elem in soup.find_all(['div', 'li', 'a', 'span', 'p', 'h1', 'h2', 'h3', 'h4', 'article', 'section', 'tr', 'td']):
        text = elem.get_text(strip=True).lower()
        
        # Check if contains any job keyword
        if any(kw in text for kw in job_keywords) and 10 < len(text) < 300:
            # Get parent classes for context
            parent_classes = []
            for parent in elem.parents:
                if parent.get('class'):
                    parent_classes.extend(parent.get('class'))
                if len(parent_classes) > 5:
                    break
            
            found_elements.append({
                'tag': elem.name,
                'text': elem.get_text(strip=True)[:100],
                'class': elem.get('class', []),
                'id': elem.get('id', ''),
                'parent_classes': parent_classes[:5],
                'href': elem.get('href', '') if elem.name == 'a' else '',
            })
    
    # Show unique patterns
    seen = set()
    for item in found_elements:
        key = (item['tag'], str(item['class']), item['text'][:50])
        if key not in seen:
            seen.add(key)
            print(f"\n📌 <{item['tag']}> class={item['class']}")
            print(f"   Text: {item['text']}")
            if item['href']:
                print(f"   Href: {item['href']}")
            if item['parent_classes']:
                print(f"   Parent classes: {item['parent_classes']}")
    
    if not found_elements:
        print("\n⚠️ No elements found with job keywords!")
    
    # ══════════════════════════════════════════════════════════════
    # SEARCH 2: Find all unique class names that might be job-related
    # ══════════════════════════════════════════════════════════════
    
    print("\n" + "=" * 70)
    print("🔍 SEARCH 2: Job-related CSS classes")
    print("=" * 70)
    
    all_classes = set()
    for elem in soup.find_all(class_=True):
        for cls in elem.get('class', []):
            all_classes.add(cls.lower())
    
    job_class_keywords = ['job', 'listing', 'vacancy', 'position', 'career', 
                          'post', 'opening', 'company', 'employer', 'work']
    
    matching_classes = [cls for cls in all_classes if any(kw in cls for kw in job_class_keywords)]
    
    print("\nClasses containing job-related keywords:")
    for cls in sorted(matching_classes):
        print(f"   .{cls}")
    
    # ══════════════════════════════════════════════════════════════
    # SEARCH 3: Look for list structures
    # ══════════════════════════════════════════════════════════════
    
    print("\n" + "=" * 70)
    print("🔍 SEARCH 3: List structures (ul/ol) with multiple items")
    print("=" * 70)
    
    for ul in soup.find_all(['ul', 'ol']):
        items = ul.find_all('li', recursive=False)
        if len(items) >= 2:
            ul_classes = ul.get('class', [])
            sample_text = items[0].get_text(strip=True)[:80] if items else ""
            
            # Check if looks job-related
            if any(kw in sample_text.lower() for kw in job_keywords) or any('job' in str(c).lower() for c in ul_classes):
                print(f"\n📋 <ul class='{ul_classes}'> with {len(items)} items")
                for i, li in enumerate(items[:5]):
                    print(f"   {i+1}. {li.get_text(strip=True)[:70]}")
                    link = li.find('a', href=True)
                    if link:
                        print(f"      Link: {link.get('href', '')[:70]}")
    
    # ══════════════════════════════════════════════════════════════
    # SEARCH 4: Find all internal links
    # ══════════════════════════════════════════════════════════════
    
    print("\n" + "=" * 70)
    print("🔍 SEARCH 4: Links that might be job listings")
    print("=" * 70)
    
    potential_job_links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        
        # Check if looks like a job link
        if any(kw in text.lower() for kw in job_keywords) and 5 < len(text) < 200:
            potential_job_links.append({
                'text': text,
                'href': href,
                'class': a.get('class', [])
            })
    
    seen_texts = set()
    for link in potential_job_links:
        text_key = link['text'].lower()[:50]
        if text_key not in seen_texts:
            seen_texts.add(text_key)
            print(f"\n🔗 {link['text'][:60]}")
            print(f"   Href: {link['href'][:70]}")
            print(f"   Class: {link['class']}")
    
    # ══════════════════════════════════════════════════════════════
    # SEARCH 5: Look for specific WP Job Manager structure
    # ══════════════════════════════════════════════════════════════
    
    print("\n" + "=" * 70)
    print("🔍 SEARCH 5: WordPress/WP Job Manager elements")
    print("=" * 70)
    
    wp_selectors = [
        'ul.job_listings', '.job_listings', '.job-listings',
        'li.job_listing', '.job_listing', '.job-listing',
        '.type-job_listing', '.jobs-wrapper', '.job-manager',
        '.wpjm', '.cariera', '.developer-listing', '.developer_listing',
        '.resume_listing', '.company_listing', '.company-listing',
    ]
    
    for selector in wp_selectors:
        elems = soup.select(selector)
        if elems:
            print(f"\n✅ Found: {selector} ({len(elems)} elements)")
            for elem in elems[:2]:
                text = elem.get_text(strip=True)[:100]
                print(f"   Content: {text}...")
    
    # ══════════════════════════════════════════════════════════════
    # SEARCH 6: Check data attributes
    # ══════════════════════════════════════════════════════════════
    
    print("\n" + "=" * 70)
    print("🔍 SEARCH 6: Elements with data-* attributes")
    print("=" * 70)
    
    for elem in soup.find_all(attrs=lambda x: x and any(k.startswith('data-') for k in x.keys())):
        data_attrs = {k: v for k, v in elem.attrs.items() if k.startswith('data-')}
        if any('job' in str(v).lower() or 'listing' in str(v).lower() for v in data_attrs.values()):
            print(f"\n📌 <{elem.name}> with data attrs:")
            for k, v in data_attrs.items():
                print(f"   {k}: {str(v)[:50]}")
    
    # ══════════════════════════════════════════════════════════════
    # SEARCH 7: Dump main content area
    # ══════════════════════════════════════════════════════════════
    
    print("\n" + "=" * 70)
    print("🔍 SEARCH 7: Main content structure")
    print("=" * 70)
    
    main_selectors = ['.entry-content', '.page-content', 'main', '#content', 
                      '.content-area', 'article', '.company-content', '.single-company']
    
    for selector in main_selectors:
        main = soup.select_one(selector)
        if main:
            print(f"\n📦 Found: {selector}")
            
            # Get direct children structure
            children = main.find_all(recursive=False)
            print(f"   Direct children: {len(children)}")
            
            for i, child in enumerate(children[:10]):
                child_classes = child.get('class', [])
                child_text = child.get_text(strip=True)[:60]
                print(f"   {i+1}. <{child.name} class='{child_classes}'> {child_text}...")
            
            break

    # ══════════════════════════════════════════════════════════════
    # FINAL: Text dump of potential job area
    # ══════════════════════════════════════════════════════════════
    
    print("\n" + "=" * 70)
    print("📄 FULL TEXT containing 'Driver' or 'Monitoring'")
    print("=" * 70)
    
    # Find paragraphs/divs containing key job titles
    for elem in soup.find_all(['p', 'div', 'span', 'li', 'h2', 'h3', 'h4']):
        text = elem.get_text(strip=True)
        if ('driver' in text.lower() or 'monitoring' in text.lower()) and 20 < len(text) < 500:
            print(f"\n<{elem.name} class='{elem.get('class', [])}'> id='{elem.get('id', '')}'>")
            print(f"   {text}")
            
            # Show parent structure
            parent = elem.parent
            if parent:
                print(f"   Parent: <{parent.name} class='{parent.get('class', [])}'>")

if __name__ == "__main__":
    analyze()