"""
ai_providers package - Modular AI provider implementations

Supports multiple AI providers for text normalization with fallback chain.
"""

from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)

# Provider imports (lazy to avoid import errors if not used)
_ollama = None
_groq = None
_gemini = None

def get_provider(name: str):
    """
    Get an AI provider by name.

    Args:
        name: Provider name ('ollama', 'groq', 'gemini')

    Returns:
        Provider class or None if not available
    """
    global _ollama, _groq, _gemini

    name = name.lower().strip()

    if name == 'ollama':
        if _ollama is None:
            try:
                from . import ollama as _ollama_module
            except ImportError as e:
                logger.warning("Ollama provider unavailable: %s", e)
                return None
            _ollama = _ollama_module
        return _ollama.OllamaProvider()

    elif name == 'groq':
        if _groq is None:
            try:
                from . import groq as _groq_module
            except ImportError as e:
                logger.warning("Groq provider unavailable: %s", e)
                return None
            _groq = _groq_module
        return _groq.GroqProvider()

    elif name == 'gemini':
        if _gemini is None:
            try:
                from . import gemini as _gemini_module
            except ImportError as e:
                logger.warning("Gemini provider unavailable: %s", e)
                return None
            _gemini = _gemini_module
        return _gemini.GeminiProvider()

    else:
        logger.warning(f"Unknown AI provider: {name}")
        return None


def get_available_providers(preferred: Optional[list] = None) -> list:
    """
    Get list of available AI providers.

    Args:
        preferred: Optional list of provider names in order of preference

    Returns:
        List of available provider instances
    """
    providers = []

    # Default order if not specified
    names = preferred or ['ollama', 'groq', 'gemini']

    for name in names:
        provider = get_provider(name)
        if provider and provider.is_available():
            providers.append(provider)

    return providers


__all__ = ['get_provider', 'get_available_providers']
