"""
Normalize job title, company, and description using Google Gemini so all jobs
have a consistent, professional format.

Setup:
  pip install google-genai
  Add to .env: GEMINI_API_KEY=your_key   (get one at https://aistudio.google.com/app/apikey)
If the key is missing or the API fails, original text is returned unchanged.
"""
import json
import logging
import re
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Optional: load .env so GEMINI_API_KEY is available when this module is used standalone
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
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


def normalize_job_text(
    title: Optional[str] = None,
    company: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """
    Call Gemini to normalize job title, company, and description.
    Returns dict with keys title, company, description (normalized or original).
    If GEMINI_API_KEY is not set or the API fails, returns original values.
    """
    out = {
        "title": title or "",
        "company": company or "",
        "description": description or "",
    }
    if not GEMINI_API_KEY:
        logger.debug("GEMINI_API_KEY not set, skipping AI normalization")
        return out
    if not (title or company or description):
        return out

    prompt = NORMALIZE_PROMPT.format(
        title=title or "Not provided",
        company=company or "Not provided",
        description=(description or "Not provided")[:12000],
    )
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = (getattr(response, "text", None) or getattr(response, "candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "") or "").strip()
        if not text:
            return out
        # Remove optional markdown code block
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        if isinstance(data, dict):
            if "title" in data and data["title"] is not None:
                out["title"] = str(data["title"]).strip() or out["title"]
            if "company" in data and data["company"] is not None:
                out["company"] = str(data["company"]).strip() or out["company"]
            if "description" in data and data["description"] is not None:
                out["description"] = str(data["description"]).strip() or out["description"]
        return out
    except ImportError:
        logger.warning("google-genai not installed. pip install google-genai for AI normalization.")
        return out
    except Exception as e:
        logger.warning("Gemini normalization failed: %s. Using original text.", e)
        return out
