"""
One-off script to backfill apply_url for existing jobs where it's missing
but a source_url exists (e.g. HaHuJobs, Afriwork, EffoySira).

Usage (from project root):
  python backfill_apply_links.py

Requires DATABASE_URL in .env (same as the main app).
"""
import os

from dotenv import load_dotenv

from database import Database


def main() -> int:
    load_dotenv()
    db = Database()
    db.initialize()

    conn = db.conn
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET apply_url = source_url,
                    apply_type = COALESCE(apply_type, 'url')
                WHERE apply_url IS NULL
                  AND source_url IS NOT NULL
                """
            )
            updated = cur.rowcount
        conn.commit()
        print(f"Backfill complete. Updated {updated} job(s).")
        return 0
    except Exception as e:
        print(f"Backfill failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

