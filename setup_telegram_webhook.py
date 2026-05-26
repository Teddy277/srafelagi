"""
Run once after deploying to Render to point Telegram at your webhook.

Usage:
  python setup_telegram_webhook.py             # set the webhook
  python setup_telegram_webhook.py --delete    # remove it
  python setup_telegram_webhook.py --info      # show current webhook status

Required env vars:
  TELEGRAM_BOT_TOKEN  — from @BotFather
  SITE_URL or SITE_BASE_URL — public HTTPS URL of your API (e.g. https://srafelagi.onrender.com)
  TELEGRAM_WEBHOOK_SECRET (optional) — random string. Sent by Telegram in a header so api.py can verify.
"""
import os
import sys
import secrets

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
SITE_URL = (os.getenv("SITE_URL") or os.getenv("SITE_BASE_URL") or "").rstrip("/")
WEBHOOK_SECRET = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()

if not BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN not set.")
    sys.exit(1)

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def info():
    r = requests.get(f"{API_BASE}/getWebhookInfo", timeout=15)
    print(r.json())


def delete():
    r = requests.post(f"{API_BASE}/deleteWebhook", json={"drop_pending_updates": True}, timeout=15)
    print(r.json())


def setup():
    global WEBHOOK_SECRET
    if not SITE_URL or not SITE_URL.startswith("https://"):
        print("ERROR: SITE_URL must be an https:// URL (Telegram requires HTTPS).")
        print("       Got:", repr(SITE_URL))
        sys.exit(1)

    if not WEBHOOK_SECRET:
        WEBHOOK_SECRET = secrets.token_urlsafe(32)
        print("Generated a new TELEGRAM_WEBHOOK_SECRET — add this to your env vars:")
        print(f"  TELEGRAM_WEBHOOK_SECRET={WEBHOOK_SECRET}")
        print()

    url = f"{SITE_URL}/telegram/webhook"
    payload = {
        "url": url,
        "secret_token": WEBHOOK_SECRET,
        "drop_pending_updates": True,
        "allowed_updates": ["message", "edited_message"],
    }
    r = requests.post(f"{API_BASE}/setWebhook", json=payload, timeout=15)
    print(f"Webhook URL: {url}")
    print("Response:", r.json())


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--delete":
        delete()
    elif arg == "--info":
        info()
    else:
        setup()
