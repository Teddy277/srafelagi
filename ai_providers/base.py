"""
Base class for AI providers
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class BaseAIProvider(ABC):
    """Abstract base class for AI providers."""

    def __init__(self, name: str):
        self.name = name
        self._cache = {}
        self._cache_enabled = True
        self._cache_max_size = 100

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is available (configured and reachable)."""
        pass

    @abstractmethod
    def normalize_job_text(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """
        Normalize job text using AI.

        Args:
            title: Job title
            company: Company name
            description: Job description

        Returns:
            Dict with keys 'title', 'company', 'description'
        """
        pass

    def _get_cache_key(self, title: Optional[str], company: Optional[str], description: Optional[str]) -> str:
        """Generate a cache key from input."""
        # Simple hash-based key
        import hashlib
        content = f"{title or ''}|{company or ''}|{description or ''}"[:500]
        return hashlib.md5(content.encode()).hexdigest()

    def _get_cached(self, title: Optional[str], company: Optional[str], description: Optional[str]) -> Optional[Dict[str, Optional[str]]]:
        """Get cached result if available."""
        if not self._cache_enabled:
            return None

        key = self._get_cache_key(title, company, description)
        return self._cache.get(key)

    def _set_cached(self, title: Optional[str], company: Optional[str], description: Optional[str], result: Dict[str, Optional[str]]):
        """Cache a result."""
        if not self._cache_enabled:
            return

        # Limit cache size
        if len(self._cache) >= self._cache_max_size:
            # Remove oldest entry (simple approach)
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        key = self._get_cache_key(title, company, description)
        self._cache[key] = result

    def clear_cache(self):
        """Clear the cache."""
        self._cache.clear()

    def disable_cache(self):
        """Disable caching."""
        self._cache_enabled = False
        self.clear_cache()

    def enable_cache(self):
        """Enable caching."""
        self._cache_enabled = True


class FallbackAIProvider(BaseAIProvider):
    """Provider that chains multiple providers with fallback."""

    def __init__(self, providers: list):
        super().__init__("fallback")
        self.providers = providers

    def is_available(self) -> bool:
        """Available if any provider is available."""
        return any(p.is_available() for p in self.providers)

    def normalize_job_text(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Try each provider in order until one succeeds."""
        out = {
            "title": title or "",
            "company": company or "",
            "description": description or "",
        }

        # Check cache first
        cached = self._get_cached(title, company, description)
        if cached:
            logger.debug(f"FallbackProvider: Cache hit")
            return cached

        for provider in self.providers:
            if not provider.is_available():
                continue

            try:
                logger.debug(f"Trying {provider.name}...")
                result = provider.normalize_job_text(title, company, description)

                # Validate result
                if result.get("title") or result.get("company") or result.get("description"):
                    logger.info(f"Successfully normalized using {provider.name}")
                    self._set_cached(title, company, description, result)
                    return result

            except Exception as e:
                logger.warning(f"{provider.name} failed: {e}")
                continue

        logger.warning("All AI providers failed, returning original text")
        self._set_cached(title, company, description, out)
        return out
