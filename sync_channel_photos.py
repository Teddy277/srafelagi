"""
Download Telegram channel profile photos for the sources ticker.
Run once (or when you add a new channel) so frontend/images/channels/ has avatars.
Uses the same .env and Telethon session strategy as main.py.
"""
import asyncio
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
CHANNELS = [ch.strip() for ch in os.getenv("CHANNELS", "").split(",") if ch.strip()]

SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "job_listener").strip() or "job_listener"
SESSION_DIR = os.getenv("TELEGRAM_SESSION_DIR", "").strip()
OUTPUT_DIR = Path(__file__).resolve().parent / "frontend" / "images" / "channels"


def get_telegram_session_name() -> str:
    if SESSION_DIR:
        base_dir = Path(SESSION_DIR)
    else:
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            base_dir = Path(local_app_data) / "ethiopian-jobs" / "telethon"
        else:
            base_dir = Path.cwd() / ".telethon"

    base_dir.mkdir(parents=True, exist_ok=True)
    session_name = base_dir / SESSION_NAME
    legacy_session = Path.cwd() / f"{SESSION_NAME}.session"
    target_session = Path(f"{session_name}.session")

    if legacy_session.exists() and not target_session.exists() and legacy_session.resolve() != target_session.resolve():
        try:
            shutil.copy2(legacy_session, target_session)
        except Exception:
            pass

    return str(session_name)


async def main():
    if not CHANNELS:
        print("No CHANNELS in .env. Nothing to sync.")
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(get_telegram_session_name(), API_ID, API_HASH)
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
