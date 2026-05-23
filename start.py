"""
start.py — Single entry point for Render free tier.
Runs api.py, main.py (Telegram listener), and telegram_bot.py
all in one process so they fit in a single free web service.

Render start command: python start.py
"""

import os
import sys
import subprocess
import signal
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PYTHON = sys.executable

services = [
    {"name": "api",      "cmd": [PYTHON, "api.py"]},
    {"name": "listener", "cmd": [PYTHON, "main.py"]},
    {"name": "bot",      "cmd": [PYTHON, "telegram_bot.py"]},
]

processes = []


def start_all():
    for svc in services:
        logger.info("Starting %s: %s", svc["name"], " ".join(svc["cmd"]))
        p = subprocess.Popen(svc["cmd"])
        processes.append((svc["name"], p))


def stop_all(signum=None, frame=None):
    logger.info("Shutting down all services...")
    for name, p in processes:
        try:
            p.terminate()
            logger.info("Stopped %s", name)
        except Exception:
            pass
    sys.exit(0)


def monitor():
    """Restart any crashed service automatically."""
    import time
    while True:
        time.sleep(10)
        for i, (name, p) in enumerate(processes):
            if p.poll() is not None:  # process died
                logger.warning("%s crashed (exit %s), restarting...", name, p.returncode)
                svc = next(s for s in services if s["name"] == name)
                new_p = subprocess.Popen(svc["cmd"])
                processes[i] = (name, new_p)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_all)
    signal.signal(signal.SIGINT, stop_all)

    start_all()
    logger.info("All services started. Monitoring...")

    try:
        monitor()
    except Exception as e:
        logger.error("Monitor error: %s", e)
        stop_all()
