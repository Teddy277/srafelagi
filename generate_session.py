"""
Run this ONCE on your local machine to generate Telegram session strings for Render.

Usage:
    python generate_session.py

It will ask you to log in with your phone number (for the listener)
and your bot token (for the bot), then print two strings to paste into
Render's environment variables:
  - TELEGRAM_SESSION_STRING
  - TELEGRAM_BOT_SESSION_STRING
"""

import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID   = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "") or os.getenv("BOT_TOKEN", "")


async def generate_user_session():
    print("\n=== Step 1: User session (for main.py Telegram listener) ===")
    print("You will be asked for your phone number and a code sent to Telegram.")
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        await client.start(phone=lambda: input("Phone number (with country code, e.g. +251...): "))
        session_str = client.session.save()
    print("\n✅ TELEGRAM_SESSION_STRING (paste this into Render env vars):")
    print(session_str)
    return session_str


async def generate_bot_session():
    print("\n=== Step 2: Bot session (for telegram_bot.py) ===")
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        await client.start(bot_token=BOT_TOKEN)
        session_str = client.session.save()
    print("\n✅ TELEGRAM_BOT_SESSION_STRING (paste this into Render env vars):")
    print(session_str)
    return session_str


async def main():
    if not API_ID or not API_HASH:
        print("ERROR: API_ID and API_HASH must be set in .env")
        return

    user_str = await generate_user_session()
    bot_str  = await generate_bot_session()

    print("\n" + "=" * 60)
    print("Copy these into Render → Environment Variables:")
    print("=" * 60)
    print(f"TELEGRAM_SESSION_STRING={user_str}")
    print(f"TELEGRAM_BOT_SESSION_STRING={bot_str}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
