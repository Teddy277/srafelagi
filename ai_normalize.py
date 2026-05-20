"""
Normalize job title, company, and description using AI providers with fallback chain.

Supports multiple providers in order of preference:
1. Ollama (local - completely free)
2. Groq (free tier: 1.5M tokens/day)
3. Gemini (Google - requires API key)

Setup:
  # For Ollama (local):
  - Install from https://ollama.com
  - Run: ollama pull llama3.2

  # For Groq:
  - Get API key from https://console.groq.com
  - Add to .env: GROQ_API_KEY=your_key

  # For Gemini:
  - Get API key from https://aistudio.google.com/app/apikey
  - Add to .env: GEMINI_API_KEY=your_key

Environment Variables:
  AI_PROVIDERS=ollama,groq,gemini  # Order of preference (comma-separated)
  OLLAMA_URL=http://localhost:11434
  OLLAMA_MODEL=llama3.2
  GROQ_API_KEY=your_key
  GROQ_MODEL=llama-3.1-8b-instant
  GEMINI_API_KEY=your_key
  GEMINI_MODEL=gemini-2.0-flash

If all providers fail, original text is returned unchanged.
"""

import logging
import os
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Optional: load .env so env vars are available when this module is used standalone
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ai_providers.base import FallbackAIProvider
from ai_providers import get_provider

# Provider priority from environment (comma-separated list)
AI_PROVIDERS = os.getenv("AI_PROVIDERS", "ollama,groq,gemini").strip()

# Initialize fallback provider with available providers
def _get_fallback_provider() -> FallbackAIProvider:
    """Initialize the fallback provider chain."""
    provider_names = [p.strip().lower() for p in AI_PROVIDERS.split(",") if p.strip()]

    providers = []
    for name in provider_names:
        try:
            provider = get_provider(name)
            if provider is None:
                logger.warning(f"Unknown AI provider: {name}")
                continue

            providers.append(provider)
            logger.debug(f"Added {name} to provider chain")
        except ImportError as e:
            logger.warning(
                "Skipping %s provider because an optional dependency is missing: %s",
                name,
                e,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize {name} provider: {e}")

    if not providers:
        logger.warning("No AI providers configured or available")

    return FallbackAIProvider(providers)


# Global fallback provider instance
_fallback_provider: Optional[FallbackAIProvider] = None


def _get_provider() -> FallbackAIProvider:
    """Get or initialize the fallback provider."""
    global _fallback_provider
    if _fallback_provider is None:
        _fallback_provider = _get_fallback_provider()
    return _fallback_provider


def normalize_job_text(
    title: Optional[str] = None,
    company: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """
    Normalize job title, company, and description using AI providers.

    Tries providers in order of preference (Ollama -> Groq -> Gemini).
    Returns dict with keys title, company, description (normalized or original).
    If no providers are available or all fail, returns original values.

    Args:
        title: Job title to normalize
        company: Company name to normalize
        description: Job description to normalize

    Returns:
        Dict with keys 'title', 'company', 'description' containing normalized text
    """
    out = {
        "title": title or "",
        "company": company or "",
        "description": description or "",
    }

    if not (title or company or description):
        return out

    try:
        provider = _get_provider()

        if not provider.is_available():
            logger.debug("No AI providers available, skipping normalization")
            return out

        result = provider.normalize_job_text(title, company, description)

        # Validate result
        if result and (result.get("title") or result.get("company") or result.get("description")):
            return result

        return out

    except Exception as e:
        logger.warning(f"AI normalization failed: {e}. Using original text.")
        return out


def get_available_providers() -> list:
    """
    Get list of currently available AI providers.

    Returns:
        List of provider names that are available
    """
    provider = _get_provider()
    return [p.name for p in provider.providers if p.is_available()]


def clear_cache():
    """Clear the normalization cache."""
    provider = _get_provider()
    provider.clear_cache()
    logger.debug("AI normalization cache cleared")


# Backwards compatibility - keep the old function name if anyone uses it
normalize_job = normalize_job_text
