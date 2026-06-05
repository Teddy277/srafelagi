"""
One-time cleanup: strip corrupted/invisible characters (lone surrogates,
U+FFFD "box" glyphs, control chars, soft hyphens) from job text already stored
in the database. New jobs are cleaned automatically in database.save_job(); this
fixes rows that were saved before that gate existed.

Usage:
  python fix_encoding.py --dry-run   # show how many rows would change (no writes)
  python fix_encoding.py             # apply the cleanup
"""
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from database import clean_text

load_dotenv()

DRY_RUN = "--dry-run" in sys.argv
DB_URL = os.getenv("DATABASE_URL")
FIELDS = ["title", "company", "location", "description", "raw_text"]

if not DB_URL:
    print("ERROR: DATABASE_URL not set (check your .env).")
    sys.exit(1)


def main():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, " + ", ".join(FIELDS) + " FROM jobs")
        rows = cur.fetchall()

    scanned = len(rows)
    changed = 0
    samples = []

    with conn.cursor() as cur:
        for row in rows:
            updates = {}
            for field in FIELDS:
                original = row.get(field)
                if isinstance(original, str):
                    cleaned = clean_text(original)
                    if cleaned != original:
                        updates[field] = cleaned
            if not updates:
                continue
            changed += 1
            if "title" in updates and len(samples) < 10:
                samples.append((row["id"], updates["title"]))
            if not DRY_RUN:
                assignments = ", ".join(f"{f} = %s" for f in updates)
                cur.execute(
                    f"UPDATE jobs SET {assignments} WHERE id = %s",
                    list(updates.values()) + [row["id"]],
                )

    if DRY_RUN:
        conn.rollback()
        print(f"[dry-run] {changed} of {scanned} job(s) contain characters to clean. No changes written.")
    else:
        conn.commit()
        print(f"Cleaned {changed} of {scanned} job(s).")

    if samples:
        print("Sample cleaned titles:")
        for jid, title in samples:
            try:
                print(f"  #{jid}: {title}")
            except Exception:
                print(f"  #{jid}: <title with characters this console can't print>")

    conn.close()


if __name__ == "__main__":
    main()
