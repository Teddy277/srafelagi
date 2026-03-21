import json
import re
import logging
from typing import Optional, List
from urllib.parse import urljoin
from .base import BaseScraper, ScrapedJob

try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

logger = logging.getLogger(__name__)

# ── URL patterns ─────────────────────────────────────────────────────────
COMPANY_LISTING_RE = re.compile(r'/companies/[^/]+/jobs/?', re.IGNORECASE)
SINGLE_JOB_RE      = re.compile(r'/jobs?/[^/]+', re.IGNORECASE)

# ── Cutoff phrases: everything after these is garbage ────────────────────
ETHIOJOBS_CUTOFF_PHRASES = [
    "more jobs by",
    "search similar jobs",
    "similar jobs in",
    "jobs in engineering",
    "jobs in accounting",
    "jobs in health",
    "jobs in sales",
    "jobs in it",
    "jobs in fmcg",
    "jobs for mid level",
    "jobs for senior",
    "jobs for junior",
    "jobs for entry",
    "jobs in addis ababa",
    "jobs in amhara",
    "jobs in oromia",
    "related jobs",
    "recent jobs",
    "you may also like",
    "verifying...",
    "verifying",
]


class EthioJobsScraper(BaseScraper):
    """Scraper for ethiojobs.net — handles both single jobs AND company listing pages."""

    def get_domain(self) -> str:
        return "ethiojobs.net"

    # ── public: is this a listing page? ──────────────────────────────────
    def is_listing_page(self, url: str) -> bool:
        return bool(COMPANY_LISTING_RE.search(url))

    # ── public: extract job URLs from a listing page ─────────────────────
    async def extract_job_urls(self, url: str) -> List[str]:
        from playwright.async_api import async_playwright

        job_urls: List[str] = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=45_000)

                # Try to load all jobs
                for _ in range(20):
                    try:
                        load_more = page.locator(
                            'button:has-text("Load More"), '
                            'button:has-text("Show More"), '
                            'a:has-text("Load More"), '
                            'a:has-text("Next")'
                        ).first
                        if await load_more.is_visible(timeout=2000):
                            await load_more.click()
                            await page.wait_for_timeout(2000)
                        else:
                            break
                    except Exception:
                        break

                # Collect all job links
                all_links = await page.eval_on_selector_all(
                    'a[href]',
                    '(els) => els.map(e => e.href)'
                )

                seen = set()
                for href in all_links:
                    full = urljoin(url, href)
                    if (
                        SINGLE_JOB_RE.search(full)
                        and '/companies/' not in full
                        and 'ethiojobs.net' in full
                        and full not in seen
                    ):
                        seen.add(full)
                        job_urls.append(full)

                # ── DEDUPLICATE: keep only unique job slugs ──────────
                # EthioJobs has both /job/XXX-title and /jobs/BASE64
                # that point to the same job. Keep only clean slug URLs.
                final_urls = []
                seen_slugs = set()
                for u in job_urls:
                    # Extract the slug part after /job/ or /jobs/
                    slug_match = re.search(r'/jobs?/([A-Za-z0-9_\-]+)', u)
                    if slug_match:
                        slug = slug_match.group(1)
                        # Skip base64-encoded duplicates (very long strings)
                        if len(slug) > 100:
                            continue
                        if slug not in seen_slugs:
                            seen_slugs.add(slug)
                            final_urls.append(u)
                    else:
                        final_urls.append(u)

                job_urls = final_urls
                await browser.close()

            logger.info(
                "EthioJobs listing %s → found %d individual job URLs",
                url, len(job_urls),
            )

        except Exception as e:
            logger.error("Failed to extract job URLs from %s: %s", url, e)

        return job_urls

    # ── public: scrape a SINGLE job detail page ──────────────────────────
    async def scrape(self, url: str) -> Optional[ScrapedJob]:
        from playwright.async_api import async_playwright
        from bs4 import BeautifulSoup

        html = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=45_000)

                # Wait for content to load (EthioJobs uses .job-detail-body-container)
                try:
                    await page.wait_for_selector(
                        'h1, .job-title, .job-detail-body-container, .job-detail-description',
                        timeout=10_000
                    )
                except Exception:
                    pass
                await page.wait_for_timeout(2000)

                html = await page.content()
                await browser.close()
        except Exception as e:
            logger.error("EthioJobs Playwright error for %s: %s", url, e)
            return self._empty_result(url)

        if not html:
            return self._empty_result(url)

        soup = BeautifulSoup(html, "html.parser")

        # ── Remove noisy sections BEFORE extraction ──────────────────────
        for sel in ["footer", "nav", "header", ".sidebar", "aside",
                     ".related-jobs", ".similar-jobs", ".recent-jobs",
                     "script", "style", "noscript"]:
            for tag in soup.select(sel):
                tag.decompose()

        # ── Remove "More Jobs by..." section and everything after ────────
        self._remove_related_jobs(soup)

        title       = self._extract_title(soup)
        company     = self._extract_company(soup, url)
        description = self._extract_description(html, soup)
        deadline    = (
            self._deadline_from_next_data(html)
            or self._deadline_from_json_ld(html)
            or self._extract_deadline(soup, description)
        )
        location    = self._extract_location(soup, description)
        salary      = self._extract_salary(soup, description)
        email       = self._extract_email(soup, description)

        # Build ScrapedJob safely using attribute assignment
        job = ScrapedJob()
        job.source_url = url
        job.title = title
        job.company = company
        job.description = description
        job.deadline = deadline
        job.location = location
        job.apply_email = email
        job.success = True

        job.scraped_data = {}
        if salary:
            job.scraped_data['salary'] = salary
        if email:
            job.scraped_data['email'] = email

        logger.info("EthioJobs OK  title=%s  company=%s", title, company)
        return job

    # ── Remove related jobs section ──────────────────────────────────────
    def _remove_related_jobs(self, soup) -> None:
        """Remove 'More Jobs by...' and 'Search Similar Jobs' sections."""
        from bs4 import Tag, NavigableString

        # Find any element whose text starts a cutoff phrase
        all_tags = soup.find_all(
            ["h1", "h2", "h3", "h4", "h5", "h6",
             "strong", "b", "div", "span", "p", "section"]
        )
        for tag in all_tags:
            tag_text = tag.get_text(strip=True).lower()
            if any(tag_text.startswith(phrase) or phrase in tag_text
                   for phrase in ETHIOJOBS_CUTOFF_PHRASES):
                logger.debug("EthioJobs cutoff at: '%s'", tag_text[:60])
                # Remove this tag and everything after it
                siblings_after = []
                sibling = tag.next_sibling
                while sibling:
                    siblings_after.append(sibling)
                    sibling = sibling.next_sibling
                for sib in siblings_after:
                    if isinstance(sib, Tag):
                        sib.decompose()
                    elif isinstance(sib, NavigableString):
                        sib.extract()
                tag.decompose()
                break

    # ── empty result helper ──────────────────────────────────────────────
    def _empty_result(self, url: str) -> ScrapedJob:
        job = ScrapedJob()
        job.source_url = url
        job.success = False
        job.error = "Failed to fetch page"
        return job

    # ── TITLE ────────────────────────────────────────────────────────────
    def _extract_title(self, soup) -> Optional[str]:
        # Try specific selectors first
        for sel in ["h1.job-title", "h1.entry-title", ".job-header h1",
                     ".job-detail h1"]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) < 300:
                    return txt

        # Generic h1 — but skip navigation/site headings
        h1s = soup.find_all("h1")
        for h1 in h1s:
            txt = h1.get_text(strip=True)
            if txt and len(txt) < 300:
                skip_words = ['ethiojobs', 'login', 'register', 'home',
                              'search', 'menu']
                if not any(w in txt.lower() for w in skip_words):
                    return txt

        # og:title fallback
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
            # Remove "- EthioJobs" suffix
            title = re.sub(r'\s*[-|]\s*EthioJobs.*$', '', title, flags=re.IGNORECASE)
            if title:
                return title

        return None

    # ── COMPANY ──────────────────────────────────────────────────────────
    def _extract_company(self, soup, url: str = "") -> Optional[str]:
        """Extract company name from multiple sources."""

        # Method 1: "View all open positions" link text patterns
        # EthioJobs shows company name near "View all open positions"
        for a_tag in soup.find_all('a'):
            href = a_tag.get('href', '')
            if '/companies/' in href and '/jobs' in href:
                # The parent container likely has the company name
                parent = a_tag.parent
                if parent:
                    for child in parent.children:
                        if hasattr(child, 'get_text'):
                            txt = child.get_text(strip=True)
                            if (txt
                                and txt != 'View all open positions'
                                and len(txt) < 200
                                and 'view all' not in txt.lower()):
                                return txt

        # Method 2: Extract from the listing URL itself
        # /companies/msa-trading-plc/jobs → "MSA Trading PLC"
        if url:
            company_match = re.search(r'/companies/([^/]+)', url)
            if company_match:
                slug = company_match.group(1)
                name = slug.replace('-', ' ').title()
                # Fix common abbreviations
                name = re.sub(r'\bPlc\b', 'PLC', name)
                name = re.sub(r'\bLlc\b', 'LLC', name)
                name = re.sub(r'\bNgo\b', 'NGO', name)
                name = re.sub(r'\bSc\b', 'SC', name)
                return name

        # Method 3: Labelled value "Company:" or "Posted by:"
        for tag in soup.find_all(["strong", "b", "span", "th", "dt", "label",
                                   "h5", "h6"]):
            lt = tag.get_text(strip=True).lower().rstrip(":")
            if lt in ("company", "company name", "organization", "employer",
                       "posted by", "hiring company"):
                sib = tag.next_sibling
                while sib:
                    txt = (sib.get_text(strip=True) if hasattr(sib, 'get_text')
                           else str(sib).strip())
                    txt = txt.strip(":").strip()
                    if txt and len(txt) < 200:
                        return txt
                    sib = sib.next_sibling

        # Method 4: CSS class selectors
        for sel in [".company-name", ".job-company", ".employer-name",
                    '[class*="company"]', '[class*="employer"]']:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) < 200:
                    skip = ['ethiojobs', 'view all', 'apply']
                    if not any(s in txt.lower() for s in skip):
                        return txt

        # Method 5: og:site_name (skip if it's just "ethiojobs")
        meta = soup.find("meta", property="og:site_name")
        if meta and meta.get("content"):
            c = meta["content"].strip()
            if c.lower() not in ("ethiojobs", "ethiojobs.net"):
                return c

        return None

    # ── DESCRIPTION ──────────────────────────────────────────────────────
    def _extract_description(self, html: Optional[str], soup) -> Optional[str]:
        # 1) Try __NEXT_DATA__ first (full description + requirement + how_to_apply)
        if html:
            desc = self._description_from_next_data(html)
            if desc and len(desc) > 80:
                return self._final_trim(desc)
            # 2) Fall back to JSON-LD JobPosting (main description only)
            desc = self._description_from_json_ld(html)
            if desc and len(desc) > 80:
                return self._final_trim(desc)

        # 3) EthioJobs-specific: .job-detail-body-container and .job-detail-description
        for sel in [
            ".job-detail-body-container",
            ".job-detail-description-details",
            ".job-detail-body-left",
            ".job-description",
            ".job-detail",
            ".job-content",
            ".entry-content",
            ".job_description",
            "article",
            "#job-description",
            "#job-detail",
            "[class*='job-detail-description']",
            "main",
        ]:
            if sel == ".job-detail-description-details":
                # Collect all description detail blocks and join
                els = soup.select(sel)
                if els:
                    parts = [el.get_text("\n", strip=True) for el in els]
                    txt = "\n\n".join(p for p in parts if len(p) > 10)
                    if len(txt) > 80:
                        return self._final_trim(txt)
                continue
            el = soup.select_one(sel)
            if el:
                txt = el.get_text("\n", strip=True)
                if len(txt) > 80:
                    return self._final_trim(txt)

        body = soup.find("body")
        if body:
            txt = body.get_text("\n", strip=True)
            if txt and len(txt) > 80:
                return self._final_trim(txt)

        # 4) Trafilatura fallback on raw HTML
        if html and TRAFILATURA_AVAILABLE:
            try:
                extracted = trafilatura.extract(
                    html,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False,
                    include_formatting=True,
                )
                if extracted and len(extracted) > 80:
                    return self._final_trim(extracted)
            except Exception as e:
                logger.debug("EthioJobs trafilatura fallback failed: %s", e)
        return None

    def _description_from_json_ld(self, html: str) -> Optional[str]:
        """Extract job description from application/ld+json JobPosting."""
        match = re.search(
            r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        )
        if not match:
            return None
        try:
            data = json.loads(match.group(1).strip())
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                desc = data.get("description")
                if isinstance(desc, str):
                    return self._strip_html(desc)
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def _description_from_next_data(self, html: str) -> Optional[str]:
        """Extract full job description from Next.js __NEXT_DATA__ (description + requirement + skills + how_to_apply)."""
        match = re.search(
            r'<script[^>]*id\s*=\s*["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        )
        if not match:
            return None
        try:
            data = json.loads(match.group(1).strip())
            props = data.get("props", {}).get("pageProps", {}).get("data") or data.get("props", {}).get("pageProps", {}).get("job")
            if not props:
                return None
            if not isinstance(props, dict):
                return None
            parts = []
            for key in ("description", "requirement", "how_to_apply"):
                val = props.get(key)
                if isinstance(val, str) and val.strip():
                    parts.append(self._strip_html(val))
            # Requirement Skill section (EthioJobs uses skills_mandatory_names / skills_desired_names)
            skills_mandatory = props.get("skills_mandatory_names")
            if isinstance(skills_mandatory, list) and skills_mandatory:
                names = [str(s).strip() for s in skills_mandatory if s]
                if names:
                    parts.append("Requirement Skill\n" + "\n".join(names))
            skills_desired = props.get("skills_desired_names")
            if isinstance(skills_desired, list) and skills_desired:
                names = [str(s).strip() for s in skills_desired if s]
                if names:
                    parts.append("Desired skills\n" + "\n".join(names))
            if parts:
                return "\n\n".join(parts)
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        return None

    def _deadline_from_next_data(self, html: str) -> Optional[str]:
        """Extract deadline from Next.js __NEXT_DATA__ (deadline, application_deadline, etc.)."""
        match = re.search(
            r'<script[^>]*id\s*=\s*["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        )
        if not match:
            return None
        try:
            data = json.loads(match.group(1).strip())
            props = data.get("props", {}).get("pageProps", {}).get("data") or data.get("props", {}).get("pageProps", {}).get("job")
            if not props or not isinstance(props, dict):
                return None
            for key in ("deadline", "application_deadline", "closing_date", "application_deadline_date", "valid_through", "validThrough", "expiry_date"):
                val = props.get(key)
                if val is None:
                    continue
                if isinstance(val, (int, float)):
                    # Unix timestamp
                    from datetime import datetime
                    try:
                        dt = datetime.utcfromtimestamp(val)
                        return dt.strftime("%B %d, %Y")
                    except (OSError, ValueError):
                        continue
                s = str(val).strip()
                if s and len(s) < 80:
                    return s
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        return None

    def _deadline_from_json_ld(self, html: str) -> Optional[str]:
        """Extract deadline from application/ld+json JobPosting validThrough (ISO date)."""
        match = re.search(
            r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        )
        if not match:
            return None
        try:
            data = json.loads(match.group(1).strip())
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                val = data.get("validThrough")
                if not val:
                    return None
                s = str(val).strip()
                if not s or len(s) > 50:
                    return None
                # If ISO (YYYY-MM-DD or full datetime), format to readable
                if re.match(r"^\d{4}-\d{2}-\d{2}", s):
                    from datetime import datetime
                    try:
                        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                        return dt.strftime("%B %d, %Y")
                    except (ValueError, TypeError):
                        return s[:10] if len(s) >= 10 else s
                return s
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    @staticmethod
    def _strip_html(html_fragment: str) -> str:
        """Remove HTML tags and decode entities for plain text."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_fragment, "html.parser")
        return soup.get_text("\n", strip=True)

    # ── DEADLINE ─────────────────────────────────────────────────────────
    def _extract_deadline(self, soup, desc: Optional[str]) -> Optional[str]:
        # 1) Look for labelled deadline in page structure (sibling)
        for tag in soup.find_all(["strong", "b", "span", "th", "dt", "label", "div", "p"]):
            lt = tag.get_text(strip=True).lower()
            if any(k in lt for k in ("deadline", "closing date", "expires")):
                sib = tag.next_sibling
                while sib:
                    txt = (sib.get_text(strip=True) if hasattr(sib, 'get_text')
                           else str(sib).strip())
                    txt = txt.strip(":").strip()
                    if txt and len(txt) < 100:
                        return txt
                    sib = getattr(sib, "next_sibling", None)
                # 1b) Same element or parent block may contain "Deadline: Feb 15, 2026"
                block = tag.find_parent(["div", "li", "td", "section"]) or tag
                block_text = block.get_text(" ", strip=True)
                m = re.search(
                    r"(?:deadline|closing\s*date|expires?)[:\s]*([A-Za-z0-9,\s/\-\.]{2,80})",
                    block_text, re.IGNORECASE,
                )
                if m:
                    return m.group(1).strip()[:80]

        # 2) Regex from description
        if desc:
            m = re.search(
                r"(?:deadline|closing\s*date|expires?)[:\s]*"
                r"([A-Za-z0-9,\s/\-\.]+)",
                desc, re.IGNORECASE,
            )
            if m:
                return m.group(1).strip()[:80]

        # 3) Regex on main content / body as fallback
        for sel in [".job-detail-body-container", ".job-detail-description-details", "main", "body"]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(" ", strip=True)
                if len(txt) > 50:
                    m = re.search(
                        r"(?:deadline|closing\s*date|expires?)[:\s]*([A-Za-z0-9,\s/\-\.]{2,80})",
                        txt, re.IGNORECASE,
                    )
                    if m:
                        return m.group(1).strip()[:80]
        return None

    # ── LOCATION ─────────────────────────────────────────────────────────
    def _extract_location(self, soup, desc: Optional[str]) -> Optional[str]:
        # Look for "Location Type" or "Location" labels
        for tag in soup.find_all(["strong", "b", "span", "th", "dt", "label"]):
            lt = tag.get_text(strip=True).lower()
            # Skip "Location Type" (that's "Office"/"Remote", not the city)
            if 'location type' in lt:
                continue
            if any(k in lt for k in ("location", "place of work",
                                      "work place", "city")):
                sib = tag.next_sibling
                while sib:
                    txt = (sib.get_text(strip=True) if hasattr(sib, 'get_text')
                           else str(sib).strip())
                    txt = txt.strip(":").strip()
                    if txt and len(txt) < 150:
                        return txt
                    sib = sib.next_sibling

        # Regex in description for "Place of Work: Kombolcha"
        if desc:
            m = re.search(
                r"(?:place of work|location|work\s*place)[:\s]*([^\n]{2,60})",
                desc, re.IGNORECASE
            )
            if m:
                loc = m.group(1).strip()
                # Don't return "Office" as location
                if loc.lower() not in ('office', 'remote', 'hybrid'):
                    return loc
        return None

    # ── SALARY ───────────────────────────────────────────────────────────
    def _extract_salary(self, soup, desc: Optional[str]) -> Optional[str]:
        # Check structured data first
        for tag in soup.find_all(["strong", "b", "span", "th", "dt", "label"]):
            lt = tag.get_text(strip=True).lower()
            if any(k in lt for k in ("salary", "pay", "compensation")):
                sib = tag.next_sibling
                while sib:
                    txt = (sib.get_text(strip=True) if hasattr(sib, 'get_text')
                           else str(sib).strip())
                    txt = txt.strip(":").strip()
                    if txt and len(txt) < 100:
                        return txt
                    sib = sib.next_sibling

        if not desc:
            return None
        for pat in [r"(?:salary|pay|compensation)[:\s]*([^\n]{5,80})",
                    r"([\d,]+(?:\.\d+)?\s*(?:ETB|Birr|USD))",
                    r"(ETB\s*[\d,]+)"]:
            m = re.search(pat, desc, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    # ── EMAIL ────────────────────────────────────────────────────────────
    def _extract_email(self, soup, desc: Optional[str]) -> Optional[str]:
        # Check for email in structured "How to Apply" section
        for tag in soup.find_all('a', href=True):
            href = tag.get('href', '')
            if href.startswith('mailto:'):
                email = href.replace('mailto:', '').strip()
                if email and '@' in email:
                    # Skip platform emails
                    domain = email.split('@')[-1].lower()
                    if domain not in ('ethiojobs.net', 'ethiojobs.com'):
                        return email

        if not desc:
            return None
        m = re.search(
            r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}",
            desc
        )
        if m:
            email = m.group(0)
            domain = email.split('@')[-1].lower()
            if domain not in ('ethiojobs.net', 'ethiojobs.com'):
                return email
        return None

    # ── Final text trim ──────────────────────────────────────────────────
    @staticmethod
    def _final_trim(text: str) -> str:
        """Cut off text at any surviving cutoff phrase."""
        lower = text.lower()
        earliest = len(text)
        for phrase in ETHIOJOBS_CUTOFF_PHRASES:
            idx = lower.find(phrase)
            if idx != -1 and idx < earliest:
                earliest = idx
        trimmed = text[:earliest].strip()
        trimmed = re.sub(r"\n{3,}", "\n\n", trimmed)
        return trimmed