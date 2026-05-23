import re
import logging
from typing import Optional
from bs4 import BeautifulSoup, Tag, NavigableString
from .base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

# ── Phrases that mark where "real" job content ENDS ──────────────────────
CUTOFF_PHRASES = [
    "related jobs",
    "recent jobs",
    "similar jobs",
    "more jobs",
    "other jobs",
    "recommended jobs",
    "you may also like",
    "ተዛማጅ ስራዎች",           # Amharic: Related Jobs
    "ይህ ስራ የ hagere jobs ነው",  # Amharic footer
    "ይህ ስራ የ hagerejobs ነው",
    "share this job",
    "apply for this job",
]

# CSS selectors that commonly wrap the "Related Jobs" sidebar / footer
POISON_SELECTORS = [
    "section.related-jobs",
    "div.related-jobs",
    "div.recent-jobs",
    "div.similar-jobs",
    ".related_jobs",
    ".recent_jobs",
    ".similar_jobs",
    "#related-jobs",
    "#recent-jobs",
    "aside",
    "footer",
    ".job-sidebar-related",
    ".widget-related-jobs",
    ".sidebar",
]


class HagereJobsScraper(BaseScraper):
    """Scraper for hagerejobs.com — strips 'Related Jobs' before extraction."""

    def get_domain(self) -> str:
        return "hagerejobs.com"

    # ── public entry point ───────────────────────────────────────────────
    async def scrape(self, url: str) -> ScrapedJob:
        html = await self._fetch_html(url)
        if not html:
            logger.warning("HagereJobs: empty response for %s", url)
            return ScrapedJob(url=url)

        soup = BeautifulSoup(html, "html.parser")

        # ❶  Nuke every element that smells like "Related Jobs"
        self._remove_poison_sections(soup)

        # ❷  Now safely extract fields
        title       = self._extract_title(soup)
        company     = self._extract_company(soup)
        description = self._extract_description(soup)
        deadline    = self._extract_deadline(soup, description)
        location    = self._extract_location(soup, description)
        salary      = self._extract_salary(description)
        email       = self._extract_email(description)

        job = ScrapedJob(
            url=url,
            title=title,
            company=company,
            description=description,
            deadline=deadline,
            location=location,
            salary=salary,
            email=email,
        )
        logger.info(
            "HagereJobs OK  title=%s  company=%s  loc=%s",
            title, company, location,
        )
        return job

    # ── STEP 1 : remove all "Related Jobs" containers ────────────────────
    def _remove_poison_sections(self, soup: BeautifulSoup) -> None:
        """Destroy every DOM subtree that belongs to Related/Recent Jobs."""

        # A) Remove by CSS selector
        for sel in POISON_SELECTORS:
            for tag in soup.select(sel):
                logger.debug("Removed poison selector: %s", sel)
                tag.decompose()

        # B) Remove any heading (h1-h6, strong, b, div, span, p)
        #    whose text matches a cutoff phrase — AND its next siblings
        heading_tags = soup.find_all(
            ["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "div", "span", "p"]
        )
        for tag in heading_tags:
            tag_text = tag.get_text(strip=True).lower()
            if any(phrase in tag_text for phrase in CUTOFF_PHRASES):
                logger.debug("Cutoff heading found: '%s'", tag_text[:60])
                self._destroy_from_here_down(tag)
                break  # everything below is gone

        # C) Walk raw text nodes — if a cutoff phrase appears in a text
        #    node, nuke the parent container and everything after it
        for text_node in list(soup.strings):
            if any(phrase in text_node.lower() for phrase in CUTOFF_PHRASES):
                parent = text_node.parent
                if parent:
                    logger.debug(
                        "Cutoff text node in <%s>: '%s'",
                        parent.name, text_node.strip()[:60],
                    )
                    self._destroy_from_here_down(parent)
                    break

    @staticmethod
    def _destroy_from_here_down(tag: Tag) -> None:
        """Remove *tag* and every sibling that comes after it."""
        # collect next siblings first (can't mutate while iterating)
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

    # ── STEP 2 : safe field extractors ───────────────────────────────────

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Job title from the page heading."""
        # Try the most common selectors first
        for sel in [
            "h1.job-title", "h1.entry-title", "h1.job_title",
            ".job-header h1", ".job-detail h1",
            "h1",
        ]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) < 300:
                    return txt

        # og:title fallback
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()

        return None

    def _extract_company(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Company name — pull ONLY from the structured job-detail area,
        never from related-job cards (those are already decomposed).
        """
        # ── pattern A: labelled row  "Company: Foo"  ────────────────────
        for label_tag in soup.find_all(
            ["strong", "b", "span", "th", "dt", "label", "h5", "h6"]
        ):
            label = label_tag.get_text(strip=True).lower()
            if label in (
                "company", "company:", "company name", "company name:",
                "organization", "organization:", "employer", "employer:",
                "ድርጅት", "ድርጅት:", "ኩባንያ", "ኩባንያ:",
            ):
                # value is the next sibling / next tag / parent's next child
                value = self._text_after_label(label_tag)
                if value:
                    return value

        # ── pattern B: CSS class on the company element ─────────────────
        for sel in [
            ".company-name", ".job-company", ".company",
            ".employer-name", ".job-detail-company",
            '[class*="company"]', '[class*="employer"]',
        ]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) < 200:
                    return txt

        # ── pattern C: meta tag ─────────────────────────────────────────
        for prop in ["og:site_name", "author"]:
            meta = soup.find("meta", attrs={"property": prop}) or \
                   soup.find("meta", attrs={"name": prop})
            if meta and meta.get("content"):
                c = meta["content"].strip()
                if c.lower() not in ("hagerejobs", "hagere jobs", "hagerejobs.com"):
                    return c

        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Full job description text (Related-Jobs already removed)."""
        # Prefer the main content container
        for sel in [
            ".job-description", ".job-detail", ".job-content",
            ".entry-content", ".job_description", "article",
            "#job-description", "#job-detail",
            "main",
        ]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text("\n", strip=True)
                if len(text) > 80:
                    return self._final_trim(text)

        # Fallback: <body> text (poison already removed)
        body = soup.find("body")
        if body:
            text = body.get_text("\n", strip=True)
            if text:
                return self._final_trim(text)

        return None

    def _extract_deadline(
        self, soup: BeautifulSoup, desc: Optional[str]
    ) -> Optional[str]:
        """Deadline / closing date."""
        # labelled value
        for label_tag in soup.find_all(
            ["strong", "b", "span", "th", "dt", "label"]
        ):
            lt = label_tag.get_text(strip=True).lower()
            if any(k in lt for k in ("deadline", "closing date", "expires",
                                      "end date", "የመጨረሻ ቀን")):
                val = self._text_after_label(label_tag)
                if val:
                    return val

        # regex inside description
        if desc:
            m = re.search(
                r"(?:deadline|closing\s*date|expires?)[:\s]*"
                r"([A-Za-z0-9,\s/\-\.]+)",
                desc, re.IGNORECASE,
            )
            if m:
                return m.group(1).strip()[:80]

        return None

    def _extract_location(
        self, soup: BeautifulSoup, desc: Optional[str]
    ) -> Optional[str]:
        for label_tag in soup.find_all(
            ["strong", "b", "span", "th", "dt", "label"]
        ):
            lt = label_tag.get_text(strip=True).lower()
            if any(k in lt for k in ("location", "location:", "city",
                                      "work place", "workplace", "ቦታ")):
                val = self._text_after_label(label_tag)
                if val:
                    return val

        for sel in [".job-location", ".location", '[class*="location"]']:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) < 150:
                    return txt

        # Regex inside description
        if desc:
            m = re.search(
                r"(?:location|work\s*place|city)[:\s]*([^\n,]{2,60})",
                desc, re.IGNORECASE,
            )
            if m:
                return m.group(1).strip()

        return None

    def _extract_salary(self, desc: Optional[str]) -> Optional[str]:
        if not desc:
            return None
        patterns = [
            r"(?:salary|pay|compensation|wage)[:\s]*([^\n]{5,80})",
            r"([\d,]+(?:\.\d+)?\s*(?:ETB|Birr|USD))",
            r"(ETB\s*[\d,]+(?:\.\d+)?)",
        ]
        for pat in patterns:
            m = re.search(pat, desc, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def _extract_email(self, desc: Optional[str]) -> Optional[str]:
        if not desc:
            return None
        m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}", desc)
        return m.group(0) if m else None

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _text_after_label(label_tag: Tag) -> Optional[str]:
        """Return the first meaningful text immediately after a label tag."""
        # 1) Next sibling text
        sib = label_tag.next_sibling
        while sib:
            if isinstance(sib, NavigableString):
                txt = sib.strip().strip(":").strip()
                if txt:
                    return txt
            elif isinstance(sib, Tag):
                txt = sib.get_text(strip=True).strip(":").strip()
                if txt:
                    return txt
            sib = sib.next_sibling

        # 2) Parent's text minus the label itself
        parent = label_tag.parent
        if parent:
            full = parent.get_text(strip=True)
            label = label_tag.get_text(strip=True)
            remainder = full.replace(label, "", 1).strip().strip(":").strip()
            if remainder:
                return remainder

        return None

    @staticmethod
    def _final_trim(text: str) -> str:
        """Last-resort trim: cut at any surviving cutoff phrase."""
        lower = text.lower()
        earliest = len(text)
        for phrase in CUTOFF_PHRASES:
            idx = lower.find(phrase)
            if idx != -1 and idx < earliest:
                earliest = idx
        trimmed = text[:earliest].strip()
        # collapse excessive blank lines
        trimmed = re.sub(r"\n{3,}", "\n\n", trimmed)
        return trimmed