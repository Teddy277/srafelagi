"""
Download Telegram channel profile photos for the sources ticker.
Run once (or when you add a new channel) so frontend/images/channels/ has avatars.
Uses the same .env and session as main.py (job_listener.session).
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
CHANNELS = [ch.strip() for ch in os.getenv("CHANNELS", "").split(",") if ch.strip()]

# Same session as main.py so no re-login if already connected
SESSION_NAME = "job_listener"
OUTPUT_DIR = Path(__file__).resolve().parent / "frontend" / "images" / "channels"


async def main():
    if not CHANNELS:
        print("No CHANNELS in .env. Nothing to sync.")
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()
    print(f"Syncing profile photos for {len(CHANNELS)} channels -> {OUTPUT_DIR}")
    for channel in CHANNELS:
        try:
            entity = await client.get_entity(channel)
            username = getattr(entity, "username", None) or str(entity.id)
            path = OUTPUT_DIR / f"{username}.jpg"
            await client.download_profile_photo(entity, file=str(path))
            print(f"  OK: {channel} -> {path.name}")
        except Exception as e:
            print(f"  Skip: {channel} -> {e}")
    await client.disconnect()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
