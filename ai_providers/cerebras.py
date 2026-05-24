"""
Cerebras AI Provider - Ultra-fast free inference
Sign up at https://cerebras.ai to get a free API key.
Free tier: 1M tokens/day per key, sub-second responses.
"""

import json
import logging
import os
from typing import Dict, Optional

try:
    import requests
except ImportError:
    requests = None

from .base import BaseAIProvider

logger = logging.getLogger(__name__)

_raw_keys = os.getenv("CEREBRAS_API_KEYS", os.getenv("CEREBRAS_API_KEY", "")).strip()
_CEREBRAS_KEYS = [k.strip() for k in _raw_keys.split(",") if k.strip()]
DEFAULT_MODEL = os.getenv("CEREBRAS_MODEL", "llama-3.3-70b")
CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"

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


class CerebrasProvider(BaseAIProvider):
    """Cerebras API provider — ultra-fast free inference with key rotation."""

    def __init__(self):
        super().__init__("cerebras")
        self.keys = _CEREBRAS_KEYS
        self.model = DEFAULT_MODEL
        self._key_index = 0

    def is_available(self) -> bool:
        return bool(self.keys) and requests is not None

    def _next_key(self) -> Optional[str]:
        if not self.keys:
            return None
        key = self.keys[self._key_index % len(self.keys)]
        self._key_index += 1
        return key

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
        if not self.is_available() or not (title or company or description):
            return out

        prompt = NORMALIZE_PROMPT.format(
            title=title or "Not provided",
            company=company or "Not provided",
            description=(description or "Not provided")[:12000],
        )

        for _ in range(len(self.keys)):
            key = self._next_key()
            if not key:
                break
            try:
                resp = requests.post(
                    CEREBRAS_API_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": self.model, "messages": [{"role": "user", "content": prompt}],
                          "temperature": 0.3, "max_tokens": 2000},
                    timeout=20,
                )
                if resp.status_code == 429:
                    logger.warning("Cerebras key rate-limited, trying next key...")
                    continue
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"].strip()
                import re
                match = re.search(r'\{[\s\S]*\}', text)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        if parsed.get("title"):
                            out["title"] = str(parsed["title"]).strip() or out["title"]
                        if parsed.get("company"):
                            out["company"] = str(parsed["company"]).strip() or out["company"]
                        if parsed.get("description"):
                            out["description"] = str(parsed["description"]).strip() or out["description"]
                return out
            except Exception as e:
                logger.warning("Cerebras key error: %s", e)
                continue

        return out
