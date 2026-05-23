"""
Post new IT jobs to a Telegram channel (Srafelagi IT Jobs).
Run on a schedule (e.g. cron every 6–12 hours):
  0 */6 * * * cd /path/to/project && python post_it_jobs_to_telegram.py

Requires .env:
  DATABASE_URL          - PostgreSQL connection
  TELEGRAM_BOT_TOKEN    - From @BotFather (add bot as channel admin)
  TELEGRAM_IT_CHANNEL   - Channel handle, e.g. @srafelagi_it_jobs
  SITE_BASE_URL         - e.g. https://srafelagi.et (for job links)
"""
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from dotenv import load_dotenv

TELEGRAM_MAX_LENGTH = 4096
DESCRIPTION_MAX_LENGTH = 2600  # leaves room for title, company, meta, apply

load_dotenv()

# Optional: use database from project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import Database

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_IT_CHANNEL = os.getenv("TELEGRAM_IT_CHANNEL", "").strip()
SITE_BASE_URL = (os.getenv("SITE_BASE_URL") or "https://srafelagi.et").strip().rstrip("/")
DELAY_BETWEEN_POSTS = 1.5  # seconds, to avoid Telegram rate limits
MAX_JOBS_PER_RUN = 30


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """Send a text message to a Telegram chat/channel. Returns True on success."""
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                return True
            return False
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"Telegram API error: {e.code} {e.reason} — {body[:300]}")
        return False
    except Exception as e:
        print(f"Telegram API error: {e}")
        return False


def strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    if not text or not isinstance(text, str):
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&amp;", "&", text, flags=re.IGNORECASE)
    text = re.sub(r"&lt;", "<", text, flags=re.IGNORECASE)
    text = re.sub(r"&gt;", ">", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Exclude jobs that are clearly accounting/finance (not IT) from the IT channel
NON_IT_ROLE_KEYWORDS = re.compile(
    r"\b(accountant|accounting\s+officer|audit\s+officer|auditor|bookkeeper|"
    r"payroll\s+officer|tax\s+officer|treasury\s+officer|finance\s+officer|"
    r"CFA|ACCA|financial\s+controller|chief\s+accountant|cost\s+accountant)\b",
    re.IGNORECASE,
)


def is_likely_non_it(job: dict) -> bool:
    """True if job is clearly accounting/finance (exclude from IT channel)."""
    title = (job.get("title") or "").strip()
    company = (job.get("company") or "").strip()
    desc = (job.get("description") or "")[:600]
    text = " ".join([title, company, strip_html(desc)]).lower()
    return bool(NON_IT_ROLE_KEYWORDS.search(text))


def format_job_message(job: dict, base_url: str) -> str:
    """Format a single job for Telegram with full info, under 4096 chars.
    Many sources store job title in 'company' and company name in 'title';
    we show job (position) first by using company field for Position when both exist."""
    db_title = (job.get("title") or "").strip()
    db_company = (job.get("company") or "").strip()
    position = db_company if db_company else (db_title or "Job")
    company_name = db_title if db_company else ""
    location = (job.get("location") or "").strip()
    deadline = (job.get("deadline") or job.get("deadline_text") or "").strip()
    salary = (job.get("salary") or "").strip()
    description = strip_html(job.get("description") or "")
    if len(description) > DESCRIPTION_MAX_LENGTH:
        description = description[: DESCRIPTION_MAX_LENGTH - 1].rstrip() + "…"

    apply_url = (job.get("apply_url") or "").strip()
    apply_email = (job.get("apply_email") or "").strip()
    source_url = (job.get("source_url") or "").strip()
    if apply_url:
        apply_link = apply_url
    elif apply_email:
        apply_link = f"mailto:{apply_email}"
    elif source_url:
        apply_link = source_url
    else:
        job_id = job.get("id")
        apply_link = f"{base_url}/#job={job_id}" if job_id else base_url

    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        f"🖥  Position: {position}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if company_name:
        lines.append(f"🏢  Company: {company_name}")
    if location:
        lines.append(f"📍  {location}")
    if deadline:
        lines.append(f"📅  Deadline: {deadline}")
    if salary:
        lines.append(f"💰  {salary}")
    lines.append("")
    if description:
        lines.append("📋  Description")
        lines.append(description)
        lines.append("")
    lines.append(f"🔗  Apply: {apply_link}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    text = "\n".join(lines)
    if len(text) > TELEGRAM_MAX_LENGTH:
        suffix = f"\n…\n🔗  Apply: {apply_link}\n━━━━━━━━━━━━━━━━━━━━"
        text = text[: TELEGRAM_MAX_LENGTH - len(suffix) - 5].rstrip() + suffix
    return text


def main():
    if not DATABASE_URL:
        print("DATABASE_URL not set in .env")
        return 1
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_IT_CHANNEL:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_IT_CHANNEL in .env (bot must be channel admin)")
        return 1

    db = Database()
    db.initialize()

    posted_ids = db.get_posted_job_ids(TELEGRAM_IT_CHANNEL)
    jobs = db.get_jobs(limit=MAX_JOBS_PER_RUN, offset=0, category="it", sort="newest")
    candidates = [j for j in jobs if j.get("id") not in posted_ids]
    new_jobs = [j for j in candidates if not is_likely_non_it(j)]
    skipped = len(candidates) - len(new_jobs)
    if skipped:
        print(f"Filtered out {skipped} non-IT (e.g. accounting/finance) job(s).")

    if not new_jobs:
        print("No new IT jobs to post.")
        return 0

    print(f"Posting {len(new_jobs)} new IT job(s) to {TELEGRAM_IT_CHANNEL}")

    ok = 0
    for job in new_jobs:
        text = format_job_message(job, SITE_BASE_URL)
        if send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_IT_CHANNEL, text):
            db.mark_job_posted(job["id"], TELEGRAM_IT_CHANNEL)
            ok += 1
            print(f"  Posted job id={job['id']}: {(job.get('title') or '')[:50]}...")
        else:
            print(f"  Failed to post job id={job['id']}")
        time.sleep(DELAY_BETWEEN_POSTS)

    print(f"Done. Posted {ok}/{len(new_jobs)}.")
    return 0 if ok == len(new_jobs) else 1


if __name__ == "__main__":
    sys.exit(main())
