"""
scrapers/afriwork.py - Afriwork Scraper
Uses Playwright to render JavaScript-heavy Nuxt.js pages.

KEY INSIGHT: The rendered page text has a predictable structure.
We split by known section headers rather than guessing line positions.

FIXES APPLIED:
  - Company extraction from bottom section (backward search)
  - How to Apply inline content capture (colon-separated on same line)
  - Footer line detection stops "DORINA ENGINEERING" + "company" leak
  - Company block pattern detection in marker extraction
"""

import re
import asyncio
import logging
from typing import Optional, Dict, List
import aiohttp
from bs4 import BeautifulSoup

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from .base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)


class AfriworkScraper(BaseScraper):
    """
    Scraper for afriworket.com (Nuxt.js SPA).
    Playwright renders the JS, then we parse the visible text.
    """

    BASE_URL = "https://afriworket.com"

    # Emails belonging to the platform itself — must be filtered out
    SITE_EMAILS = {
        'info@afriworket.com',
        'support@afriworket.com',
        'hello@afriworket.com',
        'contact@afriworket.com',
    }

    # Lines that appear in the page chrome (header/footer/nav)
    # and must be skipped when looking for job content
    NOISE_LINES = {
        'explore jobs', 'pricing', 'resources', 'learn', 'register',
        'login', 'back', 'login to apply', 'apply',
        'find work', 'blog', 'new offers', 'help', 'contact us',
        'terms of service', 'case studies', 'faq', 'ourstory',
        'you need to login to apply for this job',
        'attract top talent. build dream teams, faster',
    }

    def get_domain(self) -> str:
        return "afriworket.com"

    def is_valid_email(self, email: str) -> bool:
        """Return True only for real employer emails, not platform emails."""
        if not email:
            return False
        email_lower = email.lower().strip()
        if email_lower in self.SITE_EMAILS:
            return False
        if 'afriwork' in email_lower:
            return False
        if not self.EMAIL_PATTERN.match(email_lower):
            return False
        return True

    def extract_uuid(self, text: str) -> Optional[str]:
        """
        Extract UUID from various URL formats:
          - startapp=UUID (Telegram mini-app button)
          - /jobs/UUID (direct web URL)
          - bare UUID in text
        """
        patterns = [
            r'startapp=([a-f0-9\-]{36})',
            r'jobs?/([a-f0-9\-]{36})',
            r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    # ─── Fetching ───────────────────────────────────────────

    async def fetch_with_playwright(self, url: str) -> Optional[str]:
        """
        Launch headless Chromium, navigate to URL, wait for Nuxt.js
        hydration, return the fully-rendered body text.
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not installed, falling back to aiohttp")
            return await self.fetch_with_aiohttp(url)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                    ]
                )
                page = await browser.new_page(
                    viewport={'width': 1280, 'height': 720},
                    user_agent=(
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/125.0.0.0 Safari/537.36'
                    ),
                )

                logger.info(f"   Playwright loading: {url}")

                # Try networkidle first (waits for all XHR to finish)
                # Fall back to domcontentloaded if it times out
                try:
                    await page.goto(url, wait_until='networkidle', timeout=30000)
                except Exception:
                    logger.warning("   networkidle timeout, trying domcontentloaded")
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)

                # Extra wait for Vue/Nuxt reactivity to settle
                await asyncio.sleep(2)

                text = await page.inner_text('body')
                await browser.close()

                if text:
                    logger.info(f"   Playwright got {len(text)} chars")
                return text

        except Exception as e:
            logger.error(f"   Playwright failed: {e}")
            return None

    async def fetch_with_aiohttp(self, url: str) -> Optional[str]:
        """Fallback fetcher — won't render JS but better than nothing."""
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml',
        }
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, ssl=False) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        return soup.get_text(separator='\n', strip=True)
        except Exception as e:
            logger.error(f"   aiohttp fallback failed: {e}")
        return None

    # ─── Parsing Helpers ────────────────────────────────────

    def _clean_lines(self, text: str) -> List[str]:
        """
        Split raw text into lines, strip whitespace,
        remove empty lines and known noise (nav/footer).
        """
        lines = []
        for line in text.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower() in self.NOISE_LINES:
                continue
            lines.append(stripped)
        return lines

    def _find_line_index(self, lines: List[str], marker: str) -> int:
        """
        Find the index of the FIRST line that STARTS WITH or EQUALS
        the marker (case-insensitive). Returns -1 if not found.
        """
        marker_lower = marker.lower()
        for i, line in enumerate(lines):
            line_lower = line.lower()
            # Exact match
            if line_lower == marker_lower:
                return i
            # Starts with marker (e.g., "Job Description" matches "job description")
            if line_lower.startswith(marker_lower):
                return i
            # Marker followed by colon (e.g., "How to Apply: ...")
            if line_lower.startswith(marker_lower + ':'):
                return i
            if line_lower.startswith(marker_lower + ' :'):
                return i
        return -1

    def _is_footer_line(self, line: str) -> bool:
        """
        Check if a line belongs to footer/noise content.
        
        This is called during text extraction to stop collecting
        lines when we hit the page footer or company info block.
        
        IMPORTANT: "company" as a standalone line is the label
        that appears under the company name in Afriwork's layout.
        It must be treated as footer to prevent leaking into
        "How to Apply" or other sections.
        """
        line_lower = line.lower().strip()

        # Check against known noise lines
        if line_lower in self.NOISE_LINES:
            return True

        # "company" as a standalone line is the label under company name
        if line_lower == 'company':
            return True

        # Footer signal phrases
        footer_signals = [
            'verified company', 'jobs posted:', 'view company profile',
            'attract top talent', 'made with', '\u00a9 20', 'terms of service',
            '+251 ', 'contact us', 'all right reserved', 'haile gebrselassie',
        ]
        return any(signal in line_lower for signal in footer_signals)

    def _extract_between_markers(
        self,
        lines: List[str],
        start_marker: str,
        end_markers: List[str],
        max_lines: int = 100
    ) -> Optional[str]:
        """
        Extract all text between start_marker and the first end_marker found.

        CRITICAL BEHAVIORS:
        
        1. INLINE CONTENT: If the start_marker line contains content after
           a colon, that content is captured as the first line.
           Example: "How to Apply: Submit your CV via email..."
           Captures: "Submit your CV via email..."

        2. FOOTER DETECTION: Stops when _is_footer_line() returns True.

        3. COMPANY BLOCK DETECTION: Stops when a line is followed by
           "company" (standalone) on the next line. This prevents
           the company name from leaking into extracted content.
           Pattern:
             DORINA ENGINEERING    <-- would leak without this check
             company               <-- standalone label
             Jobs Posted: 4
        """
        start_idx = self._find_line_index(lines, start_marker)
        if start_idx == -1:
            return None

        collected = []

        # ── Handle inline content on the marker line itself ──
        # Example: "How to Apply: Interested and qualified applicants..."
        marker_line = lines[start_idx]
        inline_match = re.match(
            rf'(?i){re.escape(start_marker)}\s*[:\-\u2013]\s*(.+)',
            marker_line
        )
        if inline_match:
            inline_content = inline_match.group(1).strip()
            if inline_content and len(inline_content) > 3:
                collected.append(inline_content)

        # Start collecting from the line AFTER the marker
        search_start = start_idx + 1

        # Find the earliest end marker
        end_idx = len(lines)
        for end_marker in end_markers:
            for i in range(search_start, len(lines)):
                if end_marker.lower() in lines[i].lower():
                    if i < end_idx:
                        end_idx = i
                    break

        # Cap at max_lines to avoid runaway extraction
        if end_idx - search_start > max_lines:
            end_idx = search_start + max_lines

        # Collect lines, stopping at footer or company block
        for i in range(search_start, end_idx):
            line = lines[i]

            # Stop at footer noise
            if self._is_footer_line(line):
                break

            # Stop at the company block pattern:
            # [COMPANY NAME] followed by "company" on next line
            # This prevents "DORINA ENGINEERING" from leaking into
            # "How to Apply" or other sections
            if (i + 1 < len(lines)
                    and lines[i + 1].lower().strip() == 'company'):
                break

            collected.append(line)

        if collected:
            return '\n'.join(collected)
        return None

    # ─── Company Extraction ─────────────────────────────────

    def _extract_company_from_bottom(self, lines: List[str]) -> Optional[str]:
        """
        Extract company name from the bottom section of the page.

        The Afriwork page structure near the bottom is:

            DORINA ENGINEERING       <-- company name (often ALL CAPS)
            company                  <-- literal word "company"
            Jobs Posted: 4           <-- job count

        OR sometimes:

            DORINA ENGINEERING
            Jobs Posted: 4

        Strategy: Search BACKWARDS from the end to find this pattern.
        This is more reliable than forward search because the company
        section is always near the bottom of the page.
        """
        for i in range(len(lines) - 1, 0, -1):
            line_lower = lines[i].lower().strip()

            # Pattern 1: Find "company" label, company name is line before it
            if line_lower == 'company':
                # Verify: "jobs posted" should appear 1-2 lines after
                has_jobs_posted = False
                for j in range(i + 1, min(i + 3, len(lines))):
                    if 'jobs posted' in lines[j].lower():
                        has_jobs_posted = True
                        break

                if has_jobs_posted and i > 0:
                    candidate = lines[i - 1].strip()
                    # Sanity check: company name should be reasonable text
                    if (len(candidate) > 2
                            and not self._is_footer_line(candidate)
                            and 'how to apply' not in candidate.lower()):
                        return candidate

            # Pattern 2: Find "Jobs Posted:" directly, company is 1-2 lines before
            if 'jobs posted' in line_lower:
                if i > 0:
                    prev = lines[i - 1].strip()
                    prev_lower = prev.lower()
                    # Skip if previous line is "company" label — go one more up
                    if prev_lower == 'company' and i > 1:
                        candidate = lines[i - 2].strip()
                    elif prev_lower != 'company':
                        candidate = prev
                    else:
                        continue

                    if (len(candidate) > 2
                            and not self._is_footer_line(candidate)
                            and 'how to apply' not in candidate.lower()):
                        return candidate

        return None

    def _extract_company_from_description(self, description: str) -> Optional[str]:
        """
        Fallback: extract company name from the job description text.
        Many Ethiopian job posts start with a company introduction.
        """
        if not description:
            return None

        patterns = [
            # "Company Name: XYZ Engineering"
            r'(?:company\s*(?:name)?)\s*[:\-\u2013]\s*(.+?)(?:\n|$)',
            # "About XYZ PLC" or "XYZ Engineering is..."
            r'^(?:about\s+)?(.+?\s+(?:plc|ltd|inc|llc|engineering|construction|trading|manufacturing))\b',
        ]

        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE | re.MULTILINE)
            if match:
                company = match.group(1).strip()
                company = re.sub(
                    r'^(?:about|company[:\s]*)', '', company, flags=re.IGNORECASE
                ).strip()
                if len(company) > 2:
                    return company

        return None

    # ─── Main Parser ────────────────────────────────────────

    def parse_job_text(self, text: str) -> Dict:
        """
        Parse structured job data from the rendered page text.

        The Afriwork rendered output has this structure:
        ---------------------------------------------------
        [nav noise: Explore Jobs, Pricing, etc.]
        Back
        You need to login...
        Login to Apply
        Sales Engineer                    <-- TITLE
        Environmental and Energy...       <-- CATEGORY
        Posted February 8, 2026           <-- POST DATE
        Addis Ababa, Ethiopia             <-- LOCATION
        Job Type: Onsite - Full Time      <-- METADATA FIELDS
        Deadline: February 11, 2026
        Vacancies: 1
        Education Qualification: ...
        15,000 ETB                        <-- SALARY
        Monthly                           <-- SALARY PERIOD
        JUNIOR                            <-- EXPERIENCE LEVEL
        Experience Level                  <-- (label after the value)
        Skills And Expertise
        [skills]
        Work Address
        [address]
        Job Description                   <-- SECTION HEADER
        [full description text]
        How to Apply: [instructions]      <-- MAY BE INLINE
        DORINA ENGINEERING                <-- COMPANY NAME
        company                           <-- literal label
        Jobs Posted: 4
        View Company Profile
        [footer noise]
        ---------------------------------------------------
        """
        result = {
            'title': None,
            'company': None,
            'category': None,
            'posted_date': None,
            'location': None,
            'deadline': None,
            'salary': None,
            'salary_period': None,
            'job_type': None,
            'experience': None,
            'education': None,
            'vacancies': None,
            'skills': None,
            'work_address': None,
            'description': None,
            'how_to_apply': None,
            'apply_email': None,
        }

        lines = self._clean_lines(text)

        if not lines:
            return result

        # ── Find the content start ──────────────────────────
        # Skip everything until after "Login to Apply" or "Back"
        # The job title is the first meaningful line after that
        content_start = 0
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if 'login to apply' in line_lower:
                content_start = i + 1
                break
            if line_lower == 'back':
                content_start = i + 1
                # Don't break — "Login to Apply" is more reliable

        # ── Title ───────────────────────────────────────────
        # First line after content_start that isn't noise
        for i in range(content_start, min(content_start + 5, len(lines))):
            candidate = lines[i]
            candidate_lower = candidate.lower()
            if candidate_lower in self.NOISE_LINES:
                continue
            if 'login' in candidate_lower or 'apply' in candidate_lower:
                continue
            if len(candidate) > 3:
                result['title'] = candidate
                content_start = i + 1
                break

        # ── Category (line right after title) ───────────────
        if content_start < len(lines):
            next_line = lines[content_start]
            # Category is a short phrase, not a metadata field
            if (not re.match(r'^(posted|addis|job type|deadline)', next_line, re.I)
                    and len(next_line) > 3
                    and ':' not in next_line
                    and not next_line.replace(',', '').replace(' ', '').isdigit()):
                result['category'] = next_line
                content_start += 1

        # ── Metadata fields ────────────────────────────────
        desc_idx = self._find_line_index(lines, 'job description')
        metadata_end = desc_idx if desc_idx != -1 else len(lines)

        i = content_start
        while i < metadata_end:
            line = lines[i]
            line_lower = line.lower()

            # Posted date
            posted_match = re.match(r'posted\s+(.+)', line, re.IGNORECASE)
            if posted_match:
                result['posted_date'] = posted_match.group(1).strip()
                i += 1
                continue

            # Location — "City, Ethiopia" format
            if ('ethiopia' in line_lower
                    and not result['location']
                    and 'haile' not in line_lower
                    and 'made' not in line_lower):
                result['location'] = line
                i += 1
                continue

            # Job Type
            job_type_match = re.match(
                r'job\s*type\s*[:\-]?\s*(.+)', line, re.IGNORECASE
            )
            if job_type_match:
                result['job_type'] = job_type_match.group(1).strip()
                i += 1
                continue

            # Deadline
            deadline_match = re.match(
                r'deadline\s*[:\-]?\s*(.+)', line, re.IGNORECASE
            )
            if deadline_match:
                result['deadline'] = deadline_match.group(1).strip()
                i += 1
                continue

            # Vacancies
            vac_match = re.match(
                r'vacancies\s*[:\-]?\s*(\d+)', line, re.IGNORECASE
            )
            if vac_match:
                result['vacancies'] = vac_match.group(1)
                i += 1
                continue

            # Education
            edu_match = re.match(
                r'education\s*qualification\s*[:\-]?\s*(.+)', line, re.IGNORECASE
            )
            if edu_match:
                result['education'] = edu_match.group(1).strip()
                i += 1
                continue

            # Salary — look for ETB/Birr amounts
            salary_match = re.search(
                r'([\d,]+)\s*(?:ETB|Birr)', line, re.IGNORECASE
            )
            if salary_match and not result['salary']:
                result['salary'] = line.strip()
                # Check next line for period (Monthly/Annual)
                if i + 1 < metadata_end:
                    next_lower = lines[i + 1].lower().strip()
                    if next_lower in ('monthly', 'annual', 'yearly',
                                      'daily', 'weekly', 'hourly'):
                        result['salary_period'] = lines[i + 1].strip()
                        i += 2
                        continue
                i += 1
                continue

            # Experience level — value appears BEFORE the label
            if line_lower in ('junior', 'senior', 'mid-level', 'mid level',
                              'entry level', 'entry-level', 'expert'):
                result['experience'] = line
                # Skip the "Experience Level" label that follows
                if (i + 1 < metadata_end
                        and 'experience level' in lines[i + 1].lower()):
                    i += 2
                else:
                    i += 1
                continue

            # "Experience Level" label without preceding value
            if 'experience level' in line_lower:
                i += 1
                continue

            # "Applicants Needed" — skip this metadata line
            if 'applicants needed' in line_lower:
                i += 1
                continue

            # Skills section — value is on the NEXT line
            if 'skills and expertise' in line_lower:
                if i + 1 < metadata_end:
                    skill_line = lines[i + 1]
                    if ('work address' not in skill_line.lower()
                            and 'job description' not in skill_line.lower()):
                        result['skills'] = skill_line
                        i += 2
                        continue
                i += 1
                continue

            # Work address — value is on the NEXT line
            if 'work address' in line_lower:
                if i + 1 < metadata_end:
                    addr_line = lines[i + 1]
                    if 'job description' not in addr_line.lower():
                        result['work_address'] = addr_line
                        i += 2
                        continue
                i += 1
                continue

            i += 1

        # ── Job Description section ─────────────────────────
        result['description'] = self._extract_between_markers(
            lines,
            start_marker='job description',
            end_markers=[
                'how to apply',
                'view company profile',
                'jobs posted',
                'contact us',
                'terms of service',
                'attract top talent',
            ],
            max_lines=100,
        )

        # ── How to Apply section ────────────────────────────
        # Can be either:
        #   A) Standalone header with content on following lines
        #   B) Inline: "How to Apply: Interested applicants should..."
        # _extract_between_markers handles both via inline_match
        result['how_to_apply'] = self._extract_between_markers(
            lines,
            start_marker='how to apply',
            end_markers=[
                'view company profile',
                'jobs posted',
                'contact us',
                'terms of service',
                'attract top talent',
            ],
            max_lines=20,
        )

        # ── Company name ────────────────────────────────────
        # PRIMARY: Extract from the bottom section pattern
        result['company'] = self._extract_company_from_bottom(lines)

        # FALLBACK: Extract from description text
        if not result['company']:
            result['company'] = self._extract_company_from_description(
                result.get('description', '')
            )

        # ── Email extraction ────────────────────────────────
        # Search the FULL text for emails, then filter out platform emails
        all_emails = self.EMAIL_PATTERN.findall(text)
        for email in all_emails:
            if self.is_valid_email(email):
                result['apply_email'] = email.lower().strip()
                break

        return result

    # ─── Main Entry Point ───────────────────────────────────

    async def scrape(self, url: str) -> ScrapedJob:
        """
        Full scraping pipeline:
          1. Extract UUID from URL
          2. Fetch rendered page with Playwright
          3. Parse structured data from text
          4. Build formatted output
        """
        result = ScrapedJob(source_url=url)

        logger.info(f"[Afriwork] Scraping: {url}")

        try:
            # ── Step 1: Extract UUID ────────────────────────
            uuid = self.extract_uuid(url)
            if not uuid:
                result.error = "Could not extract UUID from URL"
                logger.error(f"   No UUID in: {url}")
                return result

            logger.info(f"   UUID: {uuid}")

            job_url = f"{self.BASE_URL}/jobs/{uuid}"
            result.source_url = job_url

            # ── Step 2: Fetch rendered page ─────────────────
            text = await self.fetch_with_playwright(job_url)

            if not text or len(text) < 100:
                result.error = "Page returned insufficient content"
                logger.error(
                    f"   Only got {len(text) if text else 0} chars"
                )
                return result

            # ── Step 3: Parse ───────────────────────────────
            job_data = self.parse_job_text(text)

            result.title = job_data.get('title')
            result.company = job_data.get('company')
            result.location = job_data.get('location')
            result.deadline = job_data.get('deadline')
            result.apply_email = job_data.get('apply_email')

            if result.apply_email:
                result.apply_type = 'email'

            # ── Step 4: Build formatted description ─────────
            desc_parts = []

            # Header metadata block
            metadata_fields = [
                ('Company', job_data.get('company')),
                ('Category', job_data.get('category')),
                ('Location', job_data.get('location')),
                ('Job Type', job_data.get('job_type')),
                ('Salary', self._format_salary(
                    job_data.get('salary'), job_data.get('salary_period')
                )),
                ('Education', job_data.get('education')),
                ('Experience', job_data.get('experience')),
                ('Vacancies', job_data.get('vacancies')),
                ('Skills', job_data.get('skills')),
                ('Work Address', job_data.get('work_address')),
                ('Posted', job_data.get('posted_date')),
                ('Deadline', job_data.get('deadline')),
            ]

            for label, value in metadata_fields:
                if value:
                    desc_parts.append(f"{label}: {value}")

            if desc_parts:
                desc_parts.append('')
                desc_parts.append('=' * 50)
                desc_parts.append('')

            # Main description
            if job_data.get('description'):
                desc_parts.append('JOB DESCRIPTION:')
                desc_parts.append('')
                desc_parts.append(job_data['description'])

            # How to apply
            if job_data.get('how_to_apply'):
                desc_parts.append('')
                desc_parts.append('=' * 50)
                desc_parts.append('')
                desc_parts.append('HOW TO APPLY:')
                desc_parts.append('')
                desc_parts.append(job_data['how_to_apply'])

            # Email highlight
            if job_data.get('apply_email'):
                desc_parts.append('')
                desc_parts.append(f"Apply to: {job_data['apply_email']}")

            result.description = '\n'.join(desc_parts)

            # Store extra scraped metadata
            result.scraped_data = {
                'source': 'afriwork_playwright',
                'uuid': uuid,
                'category': job_data.get('category'),
                'posted_date': job_data.get('posted_date'),
                'salary': job_data.get('salary'),
                'salary_period': job_data.get('salary_period'),
                'education': job_data.get('education'),
                'experience': job_data.get('experience'),
                'vacancies': job_data.get('vacancies'),
                'skills': job_data.get('skills'),
                'work_address': job_data.get('work_address'),
            }

            # ── Success check ──────────────────────────────
            has_title = bool(result.title)
            has_desc = bool(
                result.description and len(result.description) > 100
            )
            result.success = has_title and has_desc

            if result.success:
                logger.info(
                    f"   Done: {result.title}"
                    f" | {len(result.description)} chars"
                    f" | Company: {result.company}"
                    f" | Email: {result.apply_email}"
                )
            else:
                logger.warning(
                    f"   Partial -- title={has_title}, desc={has_desc}"
                )

        except Exception as e:
            logger.error(f"   Scraping error: {e}")
            import traceback
            traceback.print_exc()
            result.error = str(e)

        return result

    def _format_salary(
        self, salary: Optional[str], period: Optional[str]
    ) -> Optional[str]:
        """Combine salary amount and period into one string."""
        if not salary:
            return None
        if period:
            return f"{salary} ({period})"
        return salary