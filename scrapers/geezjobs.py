"""
GeezJobs scraper for geezjobs.com job detail pages.
Handles URLs like https://geezjobs.com/job-detail/nurses-biruh-vision-ophthalmic
Used when Telegram posts (e.g. @geezjobs_ethiopia) include a "Detail and Apply" button.
"""
import re
import logging
from typing import Optional
from bs4 import BeautifulSoup
from .base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

# Cut off description at these phrases (GeezJobs sidebar/footer)
CUTOFF_PHRASES = [
    "view all vacancies at",
    "view all vacancies",
    "your dream job starts",
    "receive job alerts",
    "get job alerts",
    "featured jobs",
    "join telegram alerts",
    "countries we serve",
    "country office",
]


class GeezJobsScraper(BaseScraper):
    """Scraper for geezjobs.com job detail pages."""

    def get_domain(self) -> str:
        return "geezjobs.com"

    async def scrape(self, url: str) -> ScrapedJob:
        html, final_url = None, url
        try:
            html, final_url = await self.fetch_page(url)
        except Exception as e:
            logger.error("GeezJobs fetch error for %s: %s", url, e)
            return self._empty_result(url)

        if not html:
            return self._empty_result(url)

        soup = BeautifulSoup(html, "html.parser")

        # Remove nav, footer, script, style
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

        logger.info("GeezJobs OK  title=%s  company=%s", title, company)
        return job

    def _empty_result(self, url: str) -> ScrapedJob:
        job = ScrapedJob()
        job.source_url = url
        job.success = False
        job.error = "Failed to fetch page"
        return job

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        # h1 often: "Nurse at Biruh Vision Eye Speciality Center"
        for sel in ["h1", ".job-title", ".job-detail h1", "h1.entry-title"]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) < 300:
                    return txt
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()[:300]
        return None

    def _extract_company(self, soup: BeautifulSoup) -> Optional[str]:
        # Same-element pattern: "Employer: Biruh Vision Eye Speciality Center"
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6", "p", "div"]):
            full = tag.get_text(strip=True)
            if full.lower().startswith("employer:"):
                val = full.split(":", 1)[-1].strip()
                if val and len(val) < 200:
                    return val
        # Label + next sibling
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6"]):
            label = tag.get_text(strip=True).lower().rstrip(":")
            if label == "employer":
                val = self._text_after_label(tag)
                if val and len(val) < 200:
                    return val
        # From h1 "Nurse at Biruh Vision..." -> "Biruh Vision..."
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
            if low.startswith("place of work:") or low.startswith("location:"):
                val = full.split(":", 1)[-1].strip()
                if val and len(val) < 150 and "date" not in val.lower() and "hour" not in val.lower():
                    return val
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6"]):
            label = tag.get_text(strip=True).lower().rstrip(":")
            if label == "place of work" or label == "location":
                val = self._text_after_label(tag)
                if val and len(val) < 150 and "date" not in val.lower() and "hour" not in val.lower():
                    return val
        return None

    def _extract_deadline(self, soup: BeautifulSoup) -> Optional[str]:
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6", "p", "div"]):
            full = tag.get_text(strip=True)
            if full.lower().startswith("deadline:"):
                val = full.split(":", 1)[-1].strip()
                if val and len(val) < 80 and "share" not in val.lower() and "copy" not in val.lower():
                    return val
        for tag in soup.find_all(["strong", "b", "span", "h5", "h6"]):
            label = tag.get_text(strip=True).lower().rstrip(":")
            if label == "deadline":
                val = self._text_after_label(tag)
                if val and len(val) < 80 and "share" not in val.lower() and "copy" not in val.lower():
                    return val
        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        for sel in [
            ".job-description",
            ".job-detail",
            ".job-content",
            ".entry-content",
            "article",
            "main",
            "[class*='job-detail']",
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
        # mailto links first (prefer link in "How to apply" area)
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if href.startswith("mailto:"):
                raw = href.replace("mailto:", "").split("?")[0].strip()
                m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}", raw)
                if m:
                    email = self._clean_email(m.group(0)) or m.group(0)
                    domain = email.split("@")[-1].lower()
                    if domain not in ("geezjobs.com", "geezweb.com"):
                        return email
        # From "How to apply" area
        for tag in soup.find_all(["h2", "h3", "h4", "strong", "b"]):
            if "how to apply" in tag.get_text(strip=True).lower():
                parent = tag.parent
                if parent:
                    text = parent.get_text()
                    m = re.search(
                        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                        text,
                    )
                    if m:
                        email = self._clean_email(m.group(0)) or m.group(0)
                        domain = email.split("@")[-1].lower()
                        if domain not in ("geezjobs.com", "geezweb.com"):
                            return email
        if description:
            m = re.search(
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                description,
            )
            if m:
                email = self._clean_email(m.group(0)) or m.group(0)
                if email:
                    domain = email.split("@")[-1].lower()
                    if domain not in ("geezjobs.com", "geezweb.com"):
                        return email
        return None

    @staticmethod
    def _clean_email(raw: str) -> Optional[str]:
        """Strip leading 'to' / trailing 'Email' that sometimes get merged in HTML."""
        s = raw.strip()
        if not s or "@" not in s:
            return None
        if s.lower().startswith("to") and not s.lower().startswith("to@"):
            s = s[2:].lstrip()
        if s.lower().endswith("email"):
            s = s[:-5].rstrip()
        return s if "@" in s and "." in s else raw

    def _extract_apply_url(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        # "Apply Now" link to job application page
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(strip=True).lower()
            if "apply now" in text and "geezjobs.com" in href and "/job-application/" in href:
                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(base_url, href)
                return href
        return None
