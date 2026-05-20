"""
utils.py - Shared utility functions for Ethiopian Job Aggregator

Provides URL normalization, text normalization, and similarity calculation
for enhanced duplicate detection.
"""

import re
import logging
from typing import Optional, Set
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

logger = logging.getLogger(__name__)

# Common tracking parameters to strip from URLs
TRACKING_PARAMS: Set[str] = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'utm_source_platform', 'utm_creative_format', 'utm_marketing_tactic',
    'fbclid', 'gclid', 'wbraid', 'gbraid', 'dclid', 'msclkid',
    'twclid', 'li_fat_id', 'mc_cid', 'mc_eid', 'igshid',
    'ref', 'referrer', 'referral', 'source', 'medium',
    'campaign', 'term', 'content', 'cid', 'sid', 'sessionid',
    'ajs_aid', 'ajs_anonymous_id', 'amp', 'sourcetype', 'sourcedetail',
}


def normalize_url(url: Optional[str]) -> Optional[str]:
    """
    Normalize a URL for duplicate detection.

    Transformations:
    - Converts to lowercase
    - Removes www. prefix
    - Removes trailing slashes
    - Strips common tracking parameters (utm_source, fbclid, etc.)
    - Converts HTTP to HTTPS
    - Removes fragments (unless they contain meaningful content)
    - Sorts query parameters

    Args:
        url: The URL to normalize

    Returns:
        Normalized URL or None if input is invalid
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()
    if not url:
        return None

    try:
        # Parse URL
        parsed = urlparse(url)

        # Scheme: force HTTPS
        scheme = 'https'

        # Netloc: lowercase and remove www.
        netloc = parsed.netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]

        # Path: lowercase and remove trailing slashes
        path = parsed.path.lower()
        if path.endswith('/') and len(path) > 1:
            path = path.rstrip('/')

        # Query: remove tracking parameters and sort remaining
        query_dict = parse_qs(parsed.query, keep_blank_values=False)
        filtered_params = {
            k: v for k, v in query_dict.items()
            if k.lower() not in TRACKING_PARAMS
        }
        # Sort parameters for consistency
        query = urlencode(sorted(filtered_params.items()), doseq=True) if filtered_params else ''

        # Fragment: usually discard, but keep if it looks like meaningful content
        fragment = parsed.fragment.lower() if parsed.fragment else ''
        # Keep fragment only if it's not a common tracking/auto-generated one
        if fragment and not re.match(r'^[a-f0-9]{8,}$', fragment):
            # Check if it contains meaningful words
            if re.search(r'[a-z]{3,}', fragment):
                pass  # Keep meaningful fragments
            else:
                fragment = ''
        else:
            fragment = ''

        # Reconstruct URL
        normalized = urlunparse((scheme, netloc, path, '', query, fragment))

        return normalized if normalized else None

    except Exception as e:
        logger.debug(f"Failed to normalize URL {url}: {e}")
        return url.lower().strip() if url else None


def normalize_text(text: Optional[str]) -> Optional[str]:
    """
    Normalize text for duplicate comparison.

    Transformations:
    - Converts to lowercase
    - Removes extra whitespace
    - Removes special characters that don't affect meaning
    - Standardizes common variations (e.g., "&" to "and")

    Args:
        text: The text to normalize

    Returns:
        Normalized text or None if input is invalid
    """
    if not text or not isinstance(text, str):
        return None

    text = text.strip()
    if not text:
        return None

    # Convert to lowercase
    text = text.lower()

    # Replace common variations
    text = text.replace('&', ' and ')
    text = text.replace('@', ' at ')
    text = text.replace('+', ' plus ')
    text = text.replace('/', ' ')
    text = text.replace('\\', ' ')

    # Remove special characters but keep alphanumeric and spaces
    text = re.sub(r'[^\w\s]', ' ', text)

    # Normalize whitespace (multiple spaces to single, strip ends)
    text = re.sub(r'\s+', ' ', text).strip()

    return text if text else None


def calculate_similarity(text1: Optional[str], text2: Optional[str]) -> float:
    """
    Calculate similarity between two texts using word overlap.

    Returns a score between 0.0 (completely different) and 1.0 (identical).

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score as a float between 0.0 and 1.0
    """
    if not text1 or not text2:
        return 0.0

    if text1 == text2:
        return 1.0

    # Normalize both texts
    norm1 = normalize_text(text1)
    norm2 = normalize_text(text2)

    if not norm1 or not norm2:
        return 0.0

    if norm1 == norm2:
        return 1.0

    # Split into word sets
    words1 = set(norm1.split())
    words2 = set(norm2.split())

    # Remove very common words (optional, could be expanded)
    common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should'}
    words1 = words1 - common_words
    words2 = words2 - common_words

    if not words1 or not words2:
        return 0.0

    # Calculate Jaccard similarity (intersection / union)
    intersection = len(words1 & words2)
    union = len(words1 | words2)

    if union == 0:
        return 0.0

    return intersection / union


def calculate_job_similarity(
    title1: Optional[str],
    company1: Optional[str],
    title2: Optional[str],
    company2: Optional[str],
    description1: Optional[str] = None,
    description2: Optional[str] = None
) -> float:
    """
    Calculate overall similarity between two jobs.

    Combines title, company, and optionally description similarity with weighted scoring.

    Args:
        title1: First job title
        company1: First job company
        title2: Second job title
        company2: Second job company
        description1: First job description (optional)
        description2: Second job description (optional)

    Returns:
        Similarity score as a float between 0.0 and 1.0
    """
    # Title similarity (most important)
    title_sim = calculate_similarity(title1, title2)

    # Company similarity (high importance)
    company_sim = calculate_similarity(company1, company2)

    # Description similarity (if provided)
    desc_sim = 0.0
    if description1 and description2:
        desc_sim = calculate_similarity(description1, description2)

    # Weighted combination
    # Title is most important, then company, then description
    if description1 and description2:
        # With description: 50% title, 30% company, 20% description
        total_sim = (title_sim * 0.5) + (company_sim * 0.3) + (desc_sim * 0.2)
    else:
        # Without description: 60% title, 40% company
        total_sim = (title_sim * 0.6) + (company_sim * 0.4)

    return total_sim


def is_likely_duplicate(
    title1: Optional[str],
    company1: Optional[str],
    title2: Optional[str],
    company2: Optional[str],
    description1: Optional[str] = None,
    description2: Optional[str] = None,
    threshold: float = 0.85
) -> bool:
    """
    Determine if two jobs are likely duplicates based on similarity threshold.

    Args:
        title1: First job title
        company1: First job company
        title2: Second job title
        company2: Second job company
        description1: First job description (optional)
        description2: Second job description (optional)
        threshold: Similarity threshold (default 0.85 = 85%)

    Returns:
        True if jobs are likely duplicates
    """
    similarity = calculate_job_similarity(
        title1, company1, title2, company2, description1, description2
    )
    return similarity >= threshold


def extract_domain(url: Optional[str]) -> Optional[str]:
    """
    Extract the domain from a URL.

    Args:
        url: The URL

    Returns:
        Domain name or None
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return None


def get_url_variants(url: Optional[str]) -> list:
    """
    Generate common URL variants for fuzzy matching.

    Useful for finding URLs that might differ only in protocol or www prefix.

    Args:
        url: The URL

    Returns:
        List of possible URL variants
    """
    if not url:
        return []

    variants = {url}

    try:
        parsed = urlparse(url)

        # Scheme variants
        schemes = ['http', 'https']

        # Netloc variants (with/without www)
        netloc = parsed.netloc.lower()
        netlocs = {netloc}
        if netloc.startswith('www.'):
            netlocs.add(netloc[4:])
        else:
            netlocs.add('www.' + netloc)

        # Generate variants
        for scheme in schemes:
            for nl in netlocs:
                variant = urlunparse((scheme, nl, parsed.path, parsed.params, parsed.query, parsed.fragment))
                variants.add(variant)
                # With/without trailing slash
                if parsed.path.endswith('/'):
                    variant_no_slash = urlunparse((scheme, nl, parsed.path.rstrip('/'), parsed.params, parsed.query, parsed.fragment))
                    variants.add(variant_no_slash)
                else:
                    variant_with_slash = urlunparse((scheme, nl, parsed.path + '/', parsed.params, parsed.query, parsed.fragment))
                    variants.add(variant_with_slash)

    except Exception:
        pass

    return list(variants)
