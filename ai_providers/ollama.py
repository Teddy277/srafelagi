"""
Ollama AI Provider - Local LLM integration

Requires Ollama to be running locally (http://localhost:11434)

To install Ollama:
  1. Visit https://ollama.com and download for your OS
  2. Run: ollama pull llama3.2  (or your preferred model)
  3. Ollama will run on http://localhost:11434 by default

Completely free - runs locally on your machine.
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

DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

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


class OllamaProvider(BaseAIProvider):
    """Ollama local LLM provider."""

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        super().__init__("ollama")
        self.base_url = (base_url or DEFAULT_OLLAMA_URL).rstrip('/')
        self.model = model or DEFAULT_MODEL
        self._available = None  # Cache availability check

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is available."""
        if self._available is not None:
            return self._available

        if requests is None:
            logger.warning("requests is not installed; skipping Ollama normalization")
            self._available = False
            return False

        try:
            # Check if Ollama is running
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code != 200:
                logger.debug(f"Ollama not available at {self.base_url}")
                self._available = False
                return False

            # Check if model exists
            data = response.json()
            models = [m.get('name', '') for m in data.get('models', [])]

            # Model might be referenced with or without tag
            model_exists = any(
                self.model in m or m.startswith(self.model.split(':')[0])
                for m in models
            )

            if not model_exists:
                logger.warning(f"Ollama model '{self.model}' not found. Available: {models}")
                self._available = False
                return False

            logger.debug(f"Ollama is available with model: {self.model}")
            self._available = True
            return True
        except Exception as e:
            if requests is not None and isinstance(e, requests.exceptions.ConnectionError):
                logger.debug(f"Cannot connect to Ollama at {self.base_url}")
                self._available = False
                return False
            logger.debug(f"Ollama availability check failed: {e}")
            self._available = False
            return False

    def normalize_job_text(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Normalize job text using Ollama."""
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
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 2000,
                    }
                },
                timeout=60,  # Local models can be slow
            )

            response.raise_for_status()
            data = response.json()

            text = data.get('response', '').strip()
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
                logger.warning(f"Ollama returned invalid JSON: {text[:200]}")
                return out

            return out

        except Exception as e:
            if requests is not None and isinstance(e, requests.exceptions.Timeout):
                logger.warning("Ollama request timed out")
                return out
            logger.warning(f"Ollama normalization failed: {e}")
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
