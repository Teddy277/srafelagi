"""
ReporterVacancy scraper for reportervacancy.com job/vacancy pages.
Handles URLs like https://reportervacancy.com/comercial-bank-of-ethiopia-job-vacancy-2025/
Used when Telegram channels (e.g. @addis_zemen_vacancy) post links to these pages.
"""
import re
import logging
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

CUTOFF_PHRASES = [
    "related posts",
    "related articles",
    "share this",
    "follow our",
    "join our telegram",
    "© ",
    "all rights reserved",
]


class ReporterVacancyScraper(BaseScraper):
    """Scraper for reportervacancy.com vacancy pages."""

    def get_domain(self) -> str:
        return "reportervacancy.com"

    async def scrape(self, url: str) -> ScrapedJob:
        html, final_url = None, url
        try:
            html, final_url = await self.fetch_page(url)
        except Exception as e:
            logger.error("ReporterVacancy fetch error for %s: %s", url, e)
            return self._empty_result(url)

        if not html:
            return self._empty_result(url)

        soup = BeautifulSoup(html, "html.parser")
        for sel in ["script", "style", "nav", "header", "footer", "aside", "noscript"]:
            for tag in soup.select(sel):
                tag.decompose()

        title = self._extract_title(soup)
        company = self._extract_company(soup, title)
        description = self._extract_description(soup)
        apply_url = self._extract_apply_url(soup, url)
        email = self._extract_email(soup, description) if description else None

        job = ScrapedJob()
        job.source_url = final_url or url
        job.title = title
        job.company = company
        job.description = description
        job.apply_url = apply_url
        job.apply_email = email
        job.apply_type = "email" if email else ("url" if apply_url else None)
        job.success = True
        job.scraped_data = {}
        if email:
            job.scraped_data["email"] = email

        logger.info("ReporterVacancy OK  title=%s  company=%s", title, company)
        return job

    def _empty_result(self, url: str) -> ScrapedJob:
        job = ScrapedJob()
        job.source_url = url
        job.success = False
        job.error = "Failed to fetch page"
        return job

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        for sel in ["h1", ".entry-title", ".post-title", "[class*='title']"]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) < 300:
                    return self._clean_title(txt)
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return self._clean_title(og["content"].strip()[:300])
        return None

    @staticmethod
    def _clean_title(title: str) -> str:
        """Strip ' – The Reporter' or similar suffix."""
        for suffix in [" – The Reporter", " - The Reporter", " | The Reporter"]:
            if title.endswith(suffix):
                return title[: -len(suffix)].strip()
        return title.strip()

    def _extract_company(self, soup: BeautifulSoup, title: Optional[str]) -> Optional[str]:
        # From title like "Commercial Bank of Ethiopia Job Vacancy 2025"
        if title:
            for pattern in [
                r"^(.+?)\s+Job\s+Vacancy",
                r"^(.+?)\s+Jobs\s+\d{4}",
                r"^(.+?)\s+Career",
            ]:
                m = re.search(pattern, title, re.IGNORECASE)
                if m:
                    name = m.group(1).strip()
                    if 3 < len(name) < 120:
                        return name
        for tag in soup.find_all(["strong", "b", "h2", "h3"]):
            text = tag.get_text(strip=True)
            if "bank of ethiopia" in text.lower() or "commercial bank" in text.lower():
                if len(text) < 100:
                    return text
        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        for sel in [
            ".entry-content",
            ".post-content",
            ".content",
            "article",
            "main",
            "[class*='entry-content']",
            "[class*='post-content']",
        ]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text("\n", strip=True)
                if len(txt) > 100:
                    return self._final_trim(txt)
        body = soup.find("body")
        if body:
            txt = body.get_text("\n", strip=True)
            if len(txt) > 100:
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

    def _extract_apply_url(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        def norm(h: str) -> str:
            return urljoin(base_url, h) if h and not h.startswith("http") else (h or "")

        candidates = []
        for tag in soup.find_all(["p", "div", "li", "strong", "h2", "h3"]):
            text = tag.get_text(strip=True).lower()
            if "application link" in text or "how to apply" in text or "apply online" in text:
                for a in tag.find_all("a", href=True):
                    href = norm(a.get("href", "").strip())
                    if href and "t.me" not in href and "telegram" not in href:
                        candidates.append(href)
                if tag.parent:
                    for a in tag.parent.find_all("a", href=True):
                        href = norm(a.get("href", "").strip())
                        if href and "t.me" not in href:
                            candidates.append(href)
        if candidates:
            for h in candidates:
                if "vacancy." in h or "showvacancy" in h or "/apply" in h:
                    return h
            return candidates[0]
        for a in soup.find_all("a", href=True):
            href = norm(a.get("href", "").strip())
            if href and ("vacancy." in href or "showvacancy" in href) and "t.me" not in href:
                return href
        return None

    def _extract_email(self, soup: BeautifulSoup, description: Optional[str]) -> Optional[str]:
        email_re = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if href.startswith("mailto:"):
                raw = href.replace("mailto:", "").split("?")[0].strip()
                m = email_re.search(raw)
                if m and "reportervacancy.com" not in m.group(0).lower():
                    return m.group(0)
        if description:
            m = email_re.search(description)
            if m and "reportervacancy.com" not in m.group(0).lower():
                return m.group(0)
        return None
