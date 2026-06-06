"""
Telegram bot via webhook — replaces telegram_bot.py polling.

Telegram POSTs every user message to /telegram/webhook on this API.
We respond using the HTTP Bot API (no Telethon, no separate process).

Setup:
  1. Deploy the API publicly (Render gives you an HTTPS URL).
  2. Set env vars: TELEGRAM_BOT_TOKEN, SITE_URL, TELEGRAM_WEBHOOK_SECRET (any random string).
  3. Run once locally: python setup_telegram_webhook.py
     This registers the webhook URL with Telegram.
"""
import os
import logging

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
SITE_URL = (os.getenv("SITE_URL") or os.getenv("SITE_BASE_URL") or "https://srafelagi.onrender.com").rstrip("/")
WEBHOOK_SECRET = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""


HELP_TEXT = f"""\
🇪🇹 *Srafelagi — Ethiopian Jobs Bot*

Find jobs and get daily alerts, straight in Telegram.

*Commands:*
• `/search accountant` — Search jobs by keyword
• `/jobs accountant` — Same as /search
• `/category it` — Browse by category (it, finance, banking, ngo, engineering, health, teaching, marketing, government, fresh_graduate)
• `/subscribe accountant` — Daily alert for a keyword
• `/subscribe` — Daily alert for all new jobs
• `/unsubscribe` — Stop alerts
• `/help` — Show this message

Browse all jobs: {SITE_URL}
"""


def send_message(chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
    """Send a message via the Telegram HTTP Bot API."""
    if not BOT_TOKEN or requests is None:
        logger.warning("TELEGRAM_BOT_TOKEN not set or requests missing")
        return False
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=10)
        if r.status_code == 200:
            return True
        # Retry without parse_mode if Markdown failed
        if r.status_code == 400 and parse_mode:
            payload.pop("parse_mode", None)
            r = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=10)
            return r.status_code == 200
        logger.warning("Telegram send failed (%s): %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        logger.warning("Telegram send error: %s", e)
        return False


def _fmt_job(j: dict) -> str:
    title = (j.get("title") or "Job").strip()[:70]
    company = (j.get("company") or "").strip()[:50]
    location = (j.get("location") or "").strip()[:40]
    deadline = (j.get("deadline_text") or j.get("deadline") or "").strip()[:25]
    salary = (j.get("salary") or "").strip()[:40]
    jid = j.get("id")

    lines = [f"*{title}*"]
    meta = []
    if company:
        meta.append(f"🏢 {company}")
    if location:
        meta.append(f"📍 {location}")
    if meta:
        lines.append("  " + "  ".join(meta))
    detail = []
    if deadline:
        detail.append(f"⏰ Deadline: {deadline}")
    if salary:
        detail.append(f"💰 {salary}")
    if detail:
        lines.append("  " + "  ".join(detail))
    if jid:
        lines.append(f"  🔗 {SITE_URL}/job/{jid}")
    return "\n".join(lines)


def _split(text: str):
    """Split '/cmd arg arg' → ('cmd', 'arg arg')."""
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lstrip("/").split("@")[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    return cmd, arg


def _pseudo_email(user_id: int) -> str:
    return f"tg_{user_id}@telegram.bot"


def _do_search(chat_id: int, keywords: str, db) -> None:
    try:
        jobs = db.get_jobs(limit=5, search=keywords or None)
    except Exception as e:
        logger.error("search error: %s", e)
        send_message(chat_id, "Error fetching jobs. Try again.")
        return
    if not jobs:
        tip = f" for *{keywords}*" if keywords else ""
        send_message(chat_id, f"No jobs found{tip}.\n\nTry different keywords or browse: {SITE_URL}")
        return
    header = f"🔍 Top {len(jobs)} jobs"
    if keywords:
        header += f" for *{keywords}*"
    header += ":\n\n"
    body = "\n\n".join(_fmt_job(j) for j in jobs)
    footer = f"\n\n[See all →]({SITE_URL})"
    send_message(chat_id, header + body + footer)


def _do_category(chat_id: int, cat: str, db) -> None:
    cat = (cat or "").strip().lower() or None
    try:
        jobs = db.get_jobs(limit=5, category=cat)
    except Exception as e:
        logger.error("category error: %s", e)
        send_message(chat_id, "Error fetching jobs. Try again.")
        return
    label = f" in *{cat}*" if cat else ""
    if not jobs:
        send_message(chat_id, f"No jobs found{label}.\n\nBrowse: {SITE_URL}")
        return
    header = f"📂 Top {len(jobs)} jobs{label}:\n\n"
    body = "\n\n".join(_fmt_job(j) for j in jobs)
    footer = f"\n\n[See all →]({SITE_URL})"
    send_message(chat_id, header + body + footer)


def _do_subscribe(chat_id: int, user_id: int, keywords: str, db) -> None:
    email = _pseudo_email(user_id)
    try:
        token = db.add_job_alert(email=email, keywords=keywords or None, frequency="daily")
        if token:
            db.confirm_job_alert(token)
            kw_text = f" for *{keywords}*" if keywords else ""
            send_message(
                chat_id,
                f"✅ Subscribed! You'll get a daily digest{kw_text} right here.\n\nUse /unsubscribe to stop.",
            )
        else:
            send_message(
                chat_id,
                "You're already subscribed!\nUse /unsubscribe first if you want to change keywords.",
            )
    except Exception as e:
        logger.error("subscribe error: %s", e)
        send_message(chat_id, "Error subscribing. Try again.")


def _do_unsubscribe(chat_id: int, user_id: int, db) -> None:
    email = _pseudo_email(user_id)
    try:
        deleted = db.unsubscribe_job_alert(email)
        if deleted:
            send_message(
                chat_id,
                "🔕 Unsubscribed. You won't receive more job alerts.\n\nUse /subscribe to re-enable.",
            )
        else:
            send_message(chat_id, "You're not subscribed yet. Use /subscribe to start.")
    except Exception as e:
        logger.error("unsubscribe error: %s", e)
        send_message(chat_id, "Error. Try again.")


def handle_update(update: dict, db) -> None:
    """Dispatch one Telegram update to the appropriate handler."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    chat_id = chat.get("id")
    user_id = sender.get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return

    if not text.startswith("/"):
        send_message(chat_id, "I only understand commands. Type /help to see what I can do.")
        return

    cmd, arg = _split(text)
    if cmd in ("start", "help"):
        send_message(chat_id, HELP_TEXT)
    elif cmd in ("id", "myid", "chatid"):
        send_message(chat_id, f"Your Telegram chat ID is: `{chat_id}`\n\nPaste it into the admin dashboard to receive new job-post alerts here.")
    elif cmd in ("search", "jobs"):
        _do_search(chat_id, arg, db)
    elif cmd == "category":
        _do_category(chat_id, arg, db)
    elif cmd == "subscribe":
        _do_subscribe(chat_id, user_id, arg, db)
    elif cmd == "unsubscribe":
        _do_unsubscribe(chat_id, user_id, db)
    else:
        send_message(chat_id, "Unknown command. Type /help to see what I can do.")
