"""
Srafelagi Telegram Bot
======================
Lets users search jobs and subscribe to daily alerts directly from Telegram.

Setup:
  1. Create a bot via @BotFather on Telegram, copy the token.
  2. Add BOT_TOKEN=<token> to your .env file.
  3. Run:  python telegram_bot.py

The bot runs independently from main.py (separate process).
"""

import os
import re
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from dotenv import load_dotenv
from database import Database

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

API_ID    = int(os.getenv("API_ID", "0"))
API_HASH  = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "") or os.getenv("BOT_TOKEN", "")
SITE_URL  = os.getenv("SITE_URL", "https://srafelagi.et")

db = Database()

_BOT_SESSION_STRING = os.getenv('TELEGRAM_BOT_SESSION_STRING', '').strip()
if _BOT_SESSION_STRING:
    bot = TelegramClient(StringSession(_BOT_SESSION_STRING), API_ID, API_HASH)
else:
    bot = TelegramClient("srafelagi_bot", API_ID, API_HASH)

# ── Helpers ────────────────────────────────────────────────────────────────

def _pseudo_email(user_id: int) -> str:
    """Stable pseudo-email for Telegram users so we reuse the job_alerts table."""
    return f"tg_{user_id}@telegram.bot"

def _fmt_job(j: dict) -> str:
    title    = (j.get("title")    or "Job").strip()[:70]
    company  = (j.get("company")  or "").strip()[:50]
    location = (j.get("location") or "").strip()[:40]
    deadline = (j.get("deadline_text") or j.get("deadline") or "").strip()[:25]
    salary   = (j.get("salary")   or "").strip()[:40]
    jid      = j.get("id")

    lines = [f"**{title}**"]
    meta = []
    if company:  meta.append(f"🏢 {company}")
    if location: meta.append(f"📍 {location}")
    if meta:
        lines.append("  " + "  ".join(meta))
    detail = []
    if deadline: detail.append(f"⏰ Deadline: {deadline}")
    if salary:   detail.append(f"💰 {salary}")
    if detail:
        lines.append("  " + "  ".join(detail))
    if jid:
        lines.append(f"  🔗 {SITE_URL}/job/{jid}")
    return "\n".join(lines)

HELP_TEXT = f"""\
🇪🇹 **Srafelagi — Ethiopian Jobs Bot**

Find jobs and get daily alerts, straight in Telegram.

**Commands:**
• `/search accountant` — Search jobs by keyword
• `/jobs accountant` — Same as /search
• `/category it` — Browse by category (it, finance, banking, ngo, engineering, health, teaching, marketing, government, fresh\_graduate)
• `/subscribe accountant` — Daily alert for a keyword
• `/subscribe` — Daily alert for all new jobs
• `/unsubscribe` — Stop alerts
• `/help` — Show this message

Browse all jobs: {SITE_URL}
"""

# ── Command handlers ───────────────────────────────────────────────────────

@bot.on(events.NewMessage(pattern=r"^/start"))
async def cmd_start(event):
    await event.respond(HELP_TEXT, parse_mode="markdown", link_preview=False)

@bot.on(events.NewMessage(pattern=r"^/help"))
async def cmd_help(event):
    await event.respond(HELP_TEXT, parse_mode="markdown", link_preview=False)

@bot.on(events.NewMessage(pattern=r"^/search\s*(.*)"))
async def cmd_search(event):
    await _do_search(event)

@bot.on(events.NewMessage(pattern=r"^/jobs\s*(.*)"))
async def cmd_jobs(event):
    await _do_search(event)

@bot.on(events.NewMessage(pattern=r"^/category\s*(.*)"))
async def cmd_category(event):
    cat = (event.pattern_match.group(1) or "").strip().lower() or None
    try:
        jobs = db.get_jobs(limit=5, category=cat)
        label = f" in **{cat}**" if cat else ""
        if not jobs:
            await event.respond(f"No jobs found{label}.\n\nBrowse: {SITE_URL}", parse_mode="markdown", link_preview=False)
            return
        header = f"📂 Top {len(jobs)} jobs{label}:\n\n"
        body = "\n\n".join(_fmt_job(j) for j in jobs)
        footer = f"\n\n[See all →]({SITE_URL})"
        await event.respond(header + body + footer, parse_mode="markdown", link_preview=False)
    except Exception as e:
        logger.error("cmd_category error: %s", e)
        await event.respond("Error fetching jobs. Try again.")

async def _do_search(event):
    keywords = (event.pattern_match.group(1) or "").strip() or None
    try:
        jobs = db.get_jobs(limit=5, search=keywords)
        if not jobs:
            tip = f" for **{keywords}**" if keywords else ""
            await event.respond(
                f"No jobs found{tip}.\n\nTry different keywords or browse: {SITE_URL}",
                parse_mode="markdown", link_preview=False,
            )
            return
        header = f"🔍 Top {len(jobs)} jobs"
        if keywords:
            header += f" for **{keywords}**"
        header += ":\n\n"
        body   = "\n\n".join(_fmt_job(j) for j in jobs)
        footer = f"\n\n[See all →]({SITE_URL})"
        await event.respond(header + body + footer, parse_mode="markdown", link_preview=False)
    except Exception as e:
        logger.error("_do_search error: %s", e)
        await event.respond("Error fetching jobs. Try again.")

@bot.on(events.NewMessage(pattern=r"^/subscribe\s*(.*)"))
async def cmd_subscribe(event):
    keywords = (event.pattern_match.group(1) or "").strip() or None
    sender = await event.get_sender()
    email  = _pseudo_email(sender.id)
    try:
        token = db.add_job_alert(email=email, keywords=keywords, frequency="daily")
        if token:
            # Auto-confirm Telegram subscribers — no email verification needed
            db.confirm_job_alert(token)
            kw_text = f" for **{keywords}**" if keywords else ""
            await event.respond(
                f"✅ Subscribed! You'll get a daily digest{kw_text} right here.\n\n"
                "Use /unsubscribe to stop.",
                parse_mode="markdown",
            )
        else:
            await event.respond(
                "You're already subscribed!\n"
                "Use /unsubscribe first if you want to change keywords.",
            )
    except Exception as e:
        logger.error("cmd_subscribe error: %s", e)
        await event.respond("Error subscribing. Try again.")

@bot.on(events.NewMessage(pattern=r"^/unsubscribe"))
async def cmd_unsubscribe(event):
    sender = await event.get_sender()
    email  = _pseudo_email(sender.id)
    try:
        deleted = db.unsubscribe_job_alert(email)
        if deleted:
            await event.respond(
                "🔕 Unsubscribed. You won't receive more job alerts.\n\n"
                "Use /subscribe to re-enable.",
            )
        else:
            await event.respond(
                "You're not subscribed yet. Use /subscribe to start.",
            )
    except Exception as e:
        logger.error("cmd_unsubscribe error: %s", e)
        await event.respond("Error. Try again.")

@bot.on(events.NewMessage)
async def catch_all(event):
    """Catch any non-command message and nudge the user toward commands."""
    text = event.text or ""
    if text.startswith("/"):
        return  # Already handled or unknown command
    await event.respond(
        "I only understand commands. Type /help to see what I can do.",
    )


# ── Entry point ────────────────────────────────────────────────────────────

async def main():
    if not API_ID or not API_HASH:
        raise ValueError("API_ID and API_HASH must be set in .env")
    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN not set in .env.\n"
            "Create a bot at @BotFather on Telegram and paste the token."
        )
    db.initialize()
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info("Bot running as @%s — press Ctrl+C to stop.", me.username)
    await bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
