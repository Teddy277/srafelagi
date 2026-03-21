# test_afriwork_parser.py
"""
Test the Afriwork parser against KNOWN Playwright output.
Verifies all field extractions including:
  - Company from bottom section (backward search)
  - How to Apply inline content (no company name leak)
  - All metadata fields
  - Description content quality

Run: python test_afriwork_parser.py
No Playwright or internet needed -- tests parsing logic only.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrapers.afriwork import AfriworkScraper

# EXACT text from Playwright test output
SAMPLE_TEXT = """Explore Jobs
Pricing
Resources
Learn
Register
Login
Back

You need to login to apply for this job

Login to Apply
Sales Engineer
Environmental and Energy engineering

Posted February 8, 2026

Addis Ababa, Ethiopia

Job Type: Onsite - Full Time

Deadline: February 11, 2026

Vacancies: 1

Education Qualification: Bachelors Degree

Applicants Needed: Both

15,000 ETB

Monthly

JUNIOR

Experience Level

Skills And Expertise
Sales Engineering
Work Address
Welo Sefer
Job Description

Company Description

Dorina Engineering | \u12f6\u122a\u1293 \u12a2\u1295\u1302\u1290\u122a\u1295\u130d is a growing supplier of a wide range of water pumps, renewable energy, and related electromechanical products. The company is based in Addis Ababa and is committed to delivering innovative products and excellent service to its clients.

\u00a0

Role Description

Our Company is looking for a qualified and competent Sales Engineer with a background in water pumping and renewable energy.

\u00a0

Key Responsibilities

\u2713 Preparation of technical proposals for renewable energy solutions and water pumping solutions.

\u2713 Sale of solar power systems and energy storage system products.

\u2713 Selling submersible pumps, solar pumps, inverters, control systems and other related products.

\u2713 As a staff of the company, accepts client\u2019s specified requirements and proposes appropriate product and Services which meets the clients need in accordance with the described specification.

\u00a0

Salary: Monthly 15000ETB NET and sales commission

\u00a0

Qualification

\u2713 BSc degree in Renewable Energy, Electrical, Mechanical or Electromechanical Engineering

\u2713 One-year direct sales experience on water pump and solar systems

\u2713 Must have good communication skills in written and spoken English.

\u2713 Clean and neatly prepared CV is preferred.

\u00a0

How to Apply: Interested and qualified applicants can submit their application letter, CV and supporting documents via email within 5 consecutive days via email. hrdorinaengineering@gmail.com

DORINA ENGINEERING

company

Jobs Posted: 4

View Company Profile

Attract Top Talent. Build Dream Teams, Faster

Company

Learn
Pricing
Case Studies
FAQ
OurStory
Find work
Blog
New offers
Help

Contact Us

+251 961 666 667
|
+251 908 549 999
support@afriworket.com

Haile Gebrselassie St. Addis Ababa, Ethiopia

Terms of Service

Made with \ud83e\udd0d in Ethiopia

\u00a9 2025 Afriwork Inc. All right reserved."""


def test_parser():
    scraper = AfriworkScraper()
    result = scraper.parse_job_text(SAMPLE_TEXT)

    print("=" * 60)
    print("PARSED RESULTS")
    print("=" * 60)

    checks = {
        'title': 'Sales Engineer',
        'company': 'DORINA ENGINEERING',
        'category': 'Environmental and Energy engineering',
        'location': 'Addis Ababa, Ethiopia',
        'job_type': 'Onsite - Full Time',
        'deadline': 'February 11, 2026',
        'salary': '15,000 ETB',
        'salary_period': 'Monthly',
        'experience': 'JUNIOR',
        'education': 'Bachelors Degree',
        'vacancies': '1',
        'skills': 'Sales Engineering',
        'work_address': 'Welo Sefer',
        'apply_email': 'hrdorinaengineering@gmail.com',
    }

    all_passed = True

    for field, expected in checks.items():
        actual = result.get(field)
        if actual:
            match = expected.lower() in actual.lower()
        else:
            match = False
        status = "PASS" if match else "FAIL"
        if not match:
            all_passed = False
        print(f"  [{status}] {field:20s} = {actual}")
        if not match:
            print(f"         {'':20s}   expected: {expected}")

    # ── Description check ───────────────────────────────────
    print()
    print("=" * 60)
    print("DESCRIPTION PREVIEW")
    print("=" * 60)

    desc = result.get('description', '')
    if desc:
        print(f"  Length: {len(desc)} chars")
        print()
        print(desc[:600])
        if len(desc) > 600:
            print(f"\n  ... ({len(desc) - 600} more chars)")

        # Verify description contains key content
        desc_checks = [
            ('Has company intro', 'growing supplier' in desc.lower()),
            ('Has role description', 'sales engineer' in desc.lower()),
            ('Has responsibilities', 'key responsibilities' in desc.lower()),
            ('Has qualifications', 'qualification' in desc.lower()),
            ('Has salary info', '15000etb' in desc.lower().replace(' ', '')),
        ]
        print()
        for label, passed in desc_checks:
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {label}")
            if not passed:
                all_passed = False
    else:
        print("  [FAIL] NO DESCRIPTION EXTRACTED")
        all_passed = False

    # ── How to Apply check ──────────────────────────────────
    print()
    print("=" * 60)
    print("HOW TO APPLY")
    print("=" * 60)

    hta = result.get('how_to_apply', '')
    if hta:
        print(f"  {hta}")

        hta_checks = [
            ('Has instructions',
             'submit' in hta.lower() or 'apply' in hta.lower() or 'send' in hta.lower()),
            ('Has email',
             'hrdorinaengineering@gmail.com' in hta.lower()),
            ('NOT company name',
             hta.strip() != 'DORINA ENGINEERING'),
            ('No "company" label leak',
             '\ncompany' not in hta.lower()),
        ]
        print()
        for label, passed in hta_checks:
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {label}")
            if not passed:
                all_passed = False
    else:
        print("  [FAIL] NO 'HOW TO APPLY' SECTION FOUND")
        all_passed = False

    # ── Final verdict ───────────────────────────────────────
    print()
    print("=" * 60)
    if all_passed:
        print("ALL CHECKS PASSED!")
    else:
        print("SOME CHECKS FAILED -- review above")
    print("=" * 60)


if __name__ == '__main__':
    test_parser()