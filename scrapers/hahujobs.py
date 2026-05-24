"""
HaHuJobs scraper for hahu.jobs job detail pages.
Handles URLs like https://www.hahu.jobs/jobs/8QhVpgGMnaIZKR
Used when Telegram posts (@hahujobs) include a "Details" button.
"""
import re
import logging
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

CUTOFF_PHRASES = [
    "share this job",
    "apply through hahujobs",
    "telegram bot",
    "hahujobs_bot",
    "© ",
    "all rights reserved",
]


class HahuJobsScraper(BaseScraper):
    """Scraper for hahu.jobs job detail pages."""

    def get_domain(self) -> str:
        return "hahu.jobs"

    async def scrape(self, url: str) -> ScrapedJob:
        html, final_url = None, url
        try:
            html, final_url = await self.fetch_page(url)
        except Exception as e:
            logger.error("HaHuJobs fetch error for %s: %s", url, e)
            return self._empty_result(url)

        if not html:
            return self._empty_result(url)

        soup = BeautifulSoup(html, "html.parser")
        for sel in ["script", "style", "nav", "header", "footer", "aside", "noscript"]:
            for tag in soup.select(sel):
                tag.decompose()

        title = self._extract_title(soup)
        company = self._extract_company(soup)
        location = self._extract_location(soup)
        deadline = self._extract_deadline(soup)
        description = self._extract_description(soup)
        email = self._extract_email(soup, description)
        apply_url = self._extract_apply_url(soup, url)

        job = ScrapedJob()
        job.source_url = final_url or url
        job.title = title
        job.company = company
        job.location = location
        job.deadline = deadline
        job.description = description
        job.apply_email = email
        job.apply_url = apply_url
        job.apply_type = "email" if email else ("url" if apply_url else None)
        job.success = True
        job.scraped_data = {}
        if email:
            job.scraped_data["email"] = email

        logger.info("HaHuJobs OK  title=%s  company=%s", title, company)
        return job

    def _empty_result(self, url: str) -> ScrapedJob:
        job = ScrapedJob()
        job.source_url = url
        job.success = False
        job.error = "Failed to fetch page"
        return job

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        for sel in ["h1", ".job-title", "[data-testid='job-title']", ".title", "h1.entry-title"]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) < 300 and "quantity" not in txt.lower() and "full description" not in txt.lower():
                    return txt
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            t = og["content"].strip()[:300]
            if "quantity" not in t.lower() and "full description" not in t.lower():
                return t
        return None

    def _extract_company(self, soup: BeautifulSoup) -> Optional[str]:
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6", "p", "div"]):
            full = tag.get_text(strip=True)
            low = full.lower()
            if low.startswith("company:") or low.startswith("employer:"):
                val = full.split(":", 1)[-1].strip()
                if val and len(val) < 200:
                    return val
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6"]):
            label = tag.get_text(strip=True).lower().rstrip(":")
            if label in ("company", "employer"):
                val = self._text_after_label(tag)
                if val and len(val) < 200:
                    return val
        h1 = soup.select_one("h1")
        if h1:
            txt = h1.get_text(strip=True)
            if " at " in txt:
                return txt.split(" at ", 1)[-1].strip()
        return None

    def _text_after_label(self, label_tag) -> Optional[str]:
        sib = label_tag.next_sibling
        while sib:
            if hasattr(sib, "get_text"):
                txt = sib.get_text(strip=True).strip(":").strip()
            else:
                txt = str(sib).strip().strip(":").strip()
            if txt and len(txt) < 200:
                return txt
            sib = getattr(sib, "next_sibling", None)
        parent = label_tag.parent
        if parent:
            full = parent.get_text(strip=True)
            label = label_tag.get_text(strip=True)
            remainder = full.replace(label, "", 1).strip().strip(":").strip()
            if remainder and len(remainder) < 200:
                return remainder
        return None

    def _extract_location(self, soup: BeautifulSoup) -> Optional[str]:
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6", "p", "div"]):
            full = tag.get_text(strip=True)
            low = full.lower()
            if low.startswith("location:") or low.startswith("place of work:") or low.startswith("city:"):
                val = full.split(":", 1)[-1].strip()
                if val and len(val) < 150 and "date" not in val.lower():
                    return val
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6"]):
            label = tag.get_text(strip=True).lower().rstrip(":")
            if label in ("location", "place of work", "city"):
                val = self._text_after_label(tag)
                if val and len(val) < 150 and "date" not in val.lower():
                    return val
        return None

    def _extract_deadline(self, soup: BeautifulSoup) -> Optional[str]:
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6", "p", "div"]):
            full = tag.get_text(strip=True)
            if full.lower().startswith("deadline:"):
                val = full.split(":", 1)[-1].strip()
                if val and len(val) > 3 and "share" not in val.lower() and re.search(r'\d', val):
                    return val
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6"]):
            label = tag.get_text(strip=True).lower().rstrip(":")
            if label == "deadline":
                val = self._text_after_label(tag)
                if val and len(val) > 3 and "share" not in val.lower() and re.search(r'\d', val):
                    return val
        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        for sel in [
            ".job-description",
            ".job-detail",
            ".job-content",
            ".description",
            "[class*='job-detail']",
            "[class*='description']",
            ".entry-content",
            "article",
            "main",
        ]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text("\n", strip=True)
                if len(txt) > 80:
                    return self._final_trim(txt)
        body = soup.find("body")
        if body:
            txt = body.get_text("\n", strip=True)
            if len(txt) > 80:
                return self._final_trim(txt)
        return None

    def _final_trim(self, text: str) -> str:
        lower = text.lower()
        earliest = len(text)
        for phrase in CUTOFF_PHRASES:
            idx = lower.find(phrase)
            if idx != -1 and idx < earliest:
                earliest = idx
        trimmed = text[:earliest].strip()
        return re.sub(r"\n{3,}", "\n\n", trimmed)

    def _extract_email(self, soup: BeautifulSoup, description: Optional[str]) -> Optional[str]:
        email_re = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if href.startswith("mailto:"):
                raw = href.replace("mailto:", "").split("?")[0].strip()
                m = email_re.search(raw)
                if m and "hahu.jobs" not in m.group(0).lower():
                    return m.group(0)
        if description:
            m = email_re.search(description)
            if m and "hahu.jobs" not in m.group(0).lower():
                return m.group(0)
        return None

    def _extract_apply_url(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            text = a.get_text(strip=True).lower()
            if not href.startswith("http"):
                href = urljoin(base_url, href)
            if "t.me" in href or "telegram" in href:
                continue
            if "apply" in text or "application" in text or "apply now" in text:
                if "hahu.jobs" in href or "job" in href:
                    return href
        return None
