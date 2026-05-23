"""
Gemini AI Provider - Google Gemini API

Supports multiple API keys with automatic rotation when a key hits its quota.

Single key:  GEMINI_API_KEY=key1
Multi key:   GEMINI_API_KEYS=key1,key2,key3,...   (takes priority)

Get keys from https://aistudio.google.com/app/apikey (one per Google account)
"""

import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

from .base import BaseAIProvider

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Support comma-separated list of keys; fall back to single key
_raw_keys = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
_ALL_KEYS: List[str] = [k.strip() for k in _raw_keys.split(",") if k.strip()]

NORMALIZE_PROMPT = """You are an expert job board editor for an Ethiopian jobs site.
Your job: rewrite the post below into a clean, recruiter-quality job listing.

LANGUAGE: Detect the source language. If the input is mostly Amharic, keep the body in Amharic. If it is mostly English, write in English. Never translate — keep the original language.

OUTPUT FORMAT for "description" — plain text only, NO markdown, NO asterisks, NO hashes.
Use these EXACT section headings (translate the heading if the body language is Amharic):

About the Role
<1-3 sentences. What the role is and who the employer is.>

Responsibilities
- <short bullet>
- <short bullet>

Requirements
- <education / experience>
- <skills>

Benefits
- <only if mentioned in the source>

How to Apply
<exact instructions from the source. Keep ALL emails, URLs, and phone numbers verbatim.>

RULES:
- Preserve every URL, email address, and phone number exactly as in the source.
- Drop spam, emojis used as decoration, repeated punctuation, "JOIN OUR CHANNEL" promos.
- Title: short, professional, Title Case (e.g., "Senior Accountant", not "SENIOR ACCOUNTANT!!!").
- Company: just the organization name, nothing else.
- If a section has no information in the source, omit that section entirely.
- Never invent facts. If salary or benefits are not stated, do not write them.

Return ONLY valid JSON, no code fence:
{{"title": "...", "company": "...", "description": "..."}}

SOURCE POST:
Title: {title}
Company: {company}
Description:
{description}
"""


class GeminiProvider(BaseAIProvider):
    """Google Gemini API provider with automatic key rotation on quota exhaustion."""

    def __init__(self, api_keys: Optional[List[str]] = None, model: Optional[str] = None):
        super().__init__("gemini")
        self.model = model or DEFAULT_MODEL
        self._client_dependency_available = None

        # Accept a list, a single string, or fall back to env
        if api_keys is None:
            self._keys = list(_ALL_KEYS)
        elif isinstance(api_keys, str):
            self._keys = [api_keys] if api_keys.strip() else []
        else:
            self._keys = [k for k in api_keys if k and k.strip()]

        # Per-key state: client instance and whether the key is quota-exhausted
        self._clients: Dict[str, object] = {}
        self._exhausted: Dict[str, float] = {}  # key -> epoch when marked exhausted

        self._available = None

    # ── public API ───────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        if not self._has_client_dependency():
            if self._available is None:
                logger.warning(
                    "Gemini disabled: google-genai not installed. Run: pip install google-genai"
                )
            self._available = False
            return False

        if not self._keys:
            if self._available is None:
                logger.warning("Gemini disabled: no API key set (GEMINI_API_KEYS or GEMINI_API_KEY)")
            self._available = False
            return False

        if self._available is None:
            logger.info(
                "Gemini provider ready (%d key(s), model=%s)", len(self._keys), self.model
            )
        self._available = True
        return True

    def normalize_job_text(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        out = {
            "title": title or "",
            "company": company or "",
            "description": description or "",
        }

        if not self.is_available():
            return out
        if not (title or company or description):
            return out
        if description and len(description.strip()) < 30 and not title:
            return out

        prompt = NORMALIZE_PROMPT.format(
            title=(title or "Not provided").strip(),
            company=(company or "Not provided").strip(),
            description=(description or "Not provided").strip()[:12000],
        )

        # Try each non-exhausted key in order
        for key in self._active_keys():
            client = self._get_client(key)
            if not client:
                continue

            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower():
                    logger.warning("Gemini key #%d quota exhausted, rotating to next key", self._key_index(key) + 1)
                    self._mark_exhausted(key)
                    continue  # try next key
                logger.error("Gemini call failed: %s: %s", type(e).__name__, e)
                return out

            text = self._extract_text(response)
            if not text:
                logger.warning("Gemini returned empty response")
                return out

            parsed = self._parse_json(text)
            if not parsed:
                logger.warning("Gemini returned unparseable response: %s", text[:300])
                return out

            new_title = self._clean_str(parsed.get("title"))
            new_company = self._clean_str(parsed.get("company"))
            new_description = self._clean_str(parsed.get("description"))

            if description and not self._preserves_contacts(description, new_description):
                logger.warning("Gemini dropped URLs/emails — falling back to original description")
                new_description = None

            if new_title:
                out["title"] = new_title
            if new_company:
                out["company"] = new_company
            if new_description and len(new_description) >= 30:
                out["description"] = new_description
                logger.info(
                    "Gemini rewrote job (key #%d): '%s' -> '%s' (desc %d -> %d chars)",
                    self._key_index(key) + 1,
                    (title or "")[:40],
                    new_title[:40] if new_title else (title or "")[:40],
                    len(description or ""),
                    len(new_description),
                )
            else:
                logger.warning("Gemini returned no usable description")

            return out

        # All keys exhausted
        logger.error(
            "All %d Gemini key(s) are quota-exhausted. AI normalization skipped.", len(self._keys)
        )
        return out

    # ── internal helpers ─────────────────────────────────────────────────────

    def _active_keys(self) -> List[str]:
        """Return keys that are not currently quota-exhausted."""
        now = time.time()
        # Reset exhaustion after 24 hours (daily quota resets)
        active = [k for k in self._keys if now - self._exhausted.get(k, 0) > 86400]
        if not active and self._keys:
            # All exhausted but some may have aged out — reset all and retry
            logger.info("All Gemini keys were exhausted; resetting exhaustion state.")
            self._exhausted.clear()
            active = list(self._keys)
        return active

    def _mark_exhausted(self, key: str):
        self._exhausted[key] = time.time()
        remaining = len(self._active_keys())
        if remaining:
            logger.info("%d Gemini key(s) still available.", remaining)
        else:
            logger.warning("All Gemini keys are now quota-exhausted for today.")

    def _key_index(self, key: str) -> int:
        try:
            return self._keys.index(key)
        except ValueError:
            return -1

    def _has_client_dependency(self) -> bool:
        if self._client_dependency_available is None:
            try:
                from google import genai  # noqa: F401
                self._client_dependency_available = True
            except ImportError:
                self._client_dependency_available = False
        return self._client_dependency_available

    def _get_client(self, key: str):
        if key not in self._clients:
            try:
                from google import genai
                self._clients[key] = genai.Client(api_key=key)
            except Exception as e:
                logger.error("Failed to create Gemini client: %s", e)
                return None
        return self._clients[key]

    # ── static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_text(response) -> str:
        if hasattr(response, "text") and response.text:
            return response.text.strip()
        try:
            candidates = getattr(response, "candidates", None) or []
            for cand in candidates:
                content = getattr(cand, "content", None)
                if not content:
                    continue
                parts = getattr(content, "parts", None) or []
                for part in parts:
                    text = getattr(part, "text", None)
                    if text:
                        return text.strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        if not text:
            return None
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            obj = json.loads(match.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _clean_str(value) -> Optional[str]:
        if value is None:
            return None
        s = str(value).strip()
        if not s or s.lower() in {"not provided", "n/a", "none", "null"}:
            return None
        return s

    @staticmethod
    def _preserves_contacts(source: str, output: Optional[str]) -> bool:
        if not output:
            return True
        url_re = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
        email_re = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

        src_urls = {u.rstrip(".,;:") for u in url_re.findall(source)}
        out_urls = {u.rstrip(".,;:") for u in url_re.findall(output)}
        src_emails = set(e.lower() for e in email_re.findall(source))
        out_emails = set(e.lower() for e in email_re.findall(output))

        if src_urls and not src_urls.issubset(out_urls):
            return False
        if src_emails and not src_emails.issubset(out_emails):
            return False
        return True
