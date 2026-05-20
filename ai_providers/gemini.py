"""
Gemini AI Provider - Google Gemini API

Requires GEMINI_API_KEY from https://aistudio.google.com/app/apikey

Note: Gemini has rate limits and may incur costs.
Consider using free alternatives (Ollama, Groq) first.
"""

import json
import logging
import os
import re
from typing import Dict, Optional, Any

from .base import BaseAIProvider

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

NORMALIZE_PROMPT = """You are a job board editor. Normalize the following job post so it has a consistent, professional format.

Rules:
- Title: One clear job title (e.g. "Software Engineer", "Accountant"). No ALL CAPS, no extra punctuation.
- Company: Company or organization name only. Clean and concise.
- Description: Use exactly these sections in order, with these headings. Keep the original meaning and details. Use plain text, no markdown.
  1) "About the role" - 1-2 sentences summarizing the position.
  2) "Responsibilities" - bullet points or short paragraphs.
  3) "Requirements" - bullet points or short list.
  4) "How to apply" - instructions or "Apply via the link below." Do not remove URLs or emails from the description.

If a section has no content, omit that section. Preserve any URLs and email addresses in the description exactly as given.
Output ONLY a valid JSON object with exactly these keys: "title", "company", "description". No other text, no code fence.

Job title: {title}
Company: {company}
Description:
{description}
"""


class GeminiProvider(BaseAIProvider):
    """Google Gemini API provider."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        super().__init__("gemini")
        self.api_key = api_key or GEMINI_API_KEY
        self.model = model or DEFAULT_MODEL
        self._client = None
        self._available = None
        self._client_dependency_available = None

    def is_available(self) -> bool:
        """Check if Gemini API key is configured."""
        if self._available is not None:
            return self._available

        self._available = bool(self.api_key) and self._has_client_dependency()
        if self.api_key and not self._available:
            logger.warning("google-genai is not installed; skipping Gemini normalization")
        return self._available

    def _has_client_dependency(self) -> bool:
        """Check if the google-genai package is installed."""
        if self._client_dependency_available is None:
            try:
                from google import genai  # noqa: F401
                self._client_dependency_available = True
            except ImportError:
                self._client_dependency_available = False
        return self._client_dependency_available

    def _get_client(self):
        """Lazy load Gemini client."""
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                logger.warning("google-genai not installed. Run: pip install google-genai")
                return None
        return self._client

    def normalize_job_text(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Normalize job text using Gemini API."""
        out = {
            "title": title or "",
            "company": company or "",
            "description": description or "",
        }

        if not self.is_available():
            return out

        if not (title or company or description):
            return out

        client = self._get_client()
        if not client:
            return out

        prompt = NORMALIZE_PROMPT.format(
            title=title or "Not provided",
            company=company or "Not provided",
            description=(description or "Not provided")[:12000],
        )

        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
            )

            # Extract text from response
            text = ""
            if hasattr(response, "text"):
                text = response.text or ""
            elif hasattr(response, "candidates"):
                candidates = response.candidates or [{}]
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [{}])
                    text = parts[0].get("text", "") if parts else ""

            text = text.strip()
            if not text:
                return out

            # Parse JSON response
            text = self._clean_json_response(text)

            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    if parsed.get("title"):
                        out["title"] = str(parsed["title"]).strip() or out["title"]
                    if parsed.get("company"):
                        out["company"] = str(parsed["company"]).strip() or out["company"]
                    if parsed.get("description"):
                        out["description"] = str(parsed["description"]).strip() or out["description"]
            except json.JSONDecodeError:
                logger.warning(f"Gemini returned invalid JSON: {text[:200]}")
                return out

            return out

        except Exception as e:
            logger.warning(f"Gemini normalization failed: {e}")
            return out

    def _clean_json_response(self, text: str) -> str:
        """Extract JSON from response that might contain markdown."""
        # Remove markdown code blocks
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        # Find JSON object
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            return match.group(0)

        return text
