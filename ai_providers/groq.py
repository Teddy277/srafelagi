"""
Groq AI Provider - Fast inference with free tier

Groq offers 1,500,000 tokens/day free tier with fast inference.
Sign up at https://console.groq.com to get an API key.

Free tier models:
- llama-3.1-8b-instant
- llama-3.3-70b-versatile
- mixtral-8x7b-32768
"""

import json
import logging
import os
from typing import Dict, Optional, Any

try:
    import requests
except ImportError:
    requests = None

from .base import BaseAIProvider

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

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


class GroqProvider(BaseAIProvider):
    """Groq API provider with free tier."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        super().__init__("groq")
        self.api_key = api_key or GROQ_API_KEY
        self.model = model or DEFAULT_MODEL
        self._available = None

    def is_available(self) -> bool:
        """Check if Groq API key is configured."""
        if self._available is not None:
            return self._available

        self._available = bool(self.api_key) and requests is not None
        if self.api_key and requests is None:
            logger.warning("requests is not installed; skipping Groq normalization")
        return self._available

    def normalize_job_text(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Normalize job text using Groq API."""
        out = {
            "title": title or "",
            "company": company or "",
            "description": description or "",
        }

        if requests is None:
            return out

        if not self.is_available():
            return out

        if not (title or company or description):
            return out

        prompt = NORMALIZE_PROMPT.format(
            title=title or "Not provided",
            company=company or "Not provided",
            description=(description or "Not provided")[:12000],
        )

        try:
            response = requests.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2000,
                },
                timeout=30,
            )

            response.raise_for_status()
            data = response.json()

            # Extract text from response
            message = data.get('choices', [{}])[0].get('message', {})
            text = message.get('content', '').strip()

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
                logger.warning(f"Groq returned invalid JSON: {text[:200]}")
                return out

            return out

        except Exception as e:
            if requests is not None and isinstance(e, requests.exceptions.HTTPError):
                if e.response.status_code == 429:
                    logger.warning("Groq rate limit exceeded (free tier: 1.5M tokens/day)")
                elif e.response.status_code == 401:
                    logger.warning("Groq API key invalid")
                else:
                    logger.warning(f"Groq HTTP error: {e}")
                return out
            if requests is not None and isinstance(e, requests.exceptions.Timeout):
                logger.warning("Groq request timed out")
                return out
            logger.warning(f"Groq normalization failed: {e}")
            return out

    def _clean_json_response(self, text: str) -> str:
        """Extract JSON from response that might contain markdown."""
        import re

        # Remove markdown code blocks
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        # Find JSON object
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            return match.group(0)

        return text
