"""
Send job alert digests to confirmed subscribers.
Run daily via cron, e.g.: 0 9 * * * cd /path/to/project && python send_job_digests.py

Subscribers via email get an SMTP digest.
Subscribers via Telegram bot (email shape: tg_<id>@telegram.bot) get a Telegram message.

Requires .env with DATABASE_URL, SMTP_* for email, TELEGRAM_BOT_TOKEN for Telegram.
"""
import os
import re
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

try:
    import requests
except ImportError:
    requests = None

from database import Database

# SMTP config (same as api.py)
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER or "noreply@srafelagi.et").strip()
PUBLIC_HOST = (os.getenv("PUBLIC_HOST") or os.getenv("HOST") or "localhost").strip() or "localhost"
if PUBLIC_HOST in {"0.0.0.0", "127.0.0.1", "::", "::1"}:
    PUBLIC_HOST = "localhost"
DEFAULT_SITE_BASE_URL = f"http://{PUBLIC_HOST}:{int(os.getenv('PORT', '8000'))}"
SITE_BASE_URL = os.getenv("SITE_BASE_URL", DEFAULT_SITE_BASE_URL).strip().rstrip("/")

# Telegram bot config — for sending digests to bot subscribers
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
TELEGRAM_PSEUDO_EMAIL_RE = re.compile(r"^tg_(\d+)@telegram\.bot$")


def is_telegram_subscriber(email: str) -> bool:
    return bool(email and TELEGRAM_PSEUDO_EMAIL_RE.match(email))


def telegram_user_id(email: str):
    m = TELEGRAM_PSEUDO_EMAIL_RE.match(email or "")
    return int(m.group(1)) if m else None


def send_telegram(user_id: int, text: str) -> bool:
    """Send a Telegram message to a user via the bot HTTP API."""
    if not TELEGRAM_BOT_TOKEN or requests is None:
        print("Telegram bot token not set or requests missing — skipping telegram digest")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        # Telegram message limit is 4096 chars
        payload = {
            "chat_id": user_id,
            "text": text[:4000],
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            return True
        # Retry without markdown if parse_mode failed
        if r.status_code == 400:
            payload.pop("parse_mode", None)
            r = requests.post(url, json=payload, timeout=15)
            return r.status_code == 200
        print(f"Telegram send failed ({r.status_code}): {r.text[:200]}")
        return False
    except Exception as e:
        print(f"Telegram send error: {e}")
        return False


def build_telegram_digest(jobs: list) -> str:
    """Build a Markdown-formatted Telegram digest message."""
    lines = [f"🇪🇹 *{len(jobs)} new job(s) for you:*\n"]
    for j in jobs[:15]:
        title = (j.get("title") or "Job").strip()[:80]
        company = (j.get("company") or "").strip()[:60]
        location = (j.get("location") or "").strip()[:40]
        deadline = (j.get("deadline_text") or j.get("deadline") or "").strip()[:25]
        job_id = j.get("id")
        url = f"{SITE_BASE_URL}/job/{job_id}"
        lines.append(f"*{title}*")
        meta = []
        if company:
            meta.append(f"🏢 {company}")
        if location:
            meta.append(f"📍 {location}")
        if meta:
            lines.append("  ".join(meta))
        if deadline:
            lines.append(f"⏰ {deadline}")
        lines.append(f"🔗 {url}\n")
    if len(jobs) > 15:
        lines.append(f"…and {len(jobs) - 15} more at {SITE_BASE_URL}")
    lines.append("\n/unsubscribe to stop alerts")
    return "\n".join(lines)


def send_email(to: str, subject: str, body_text: str, body_html: str = None) -> bool:
    if not SMTP_HOST or not SMTP_USER:
        print("SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env")
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = to
        msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, [to], msg.as_string())
        return True
    except Exception as e:
        print(f"Send failed: {e}")
        return False


def parse_created_at(created_at):
    """Return datetime or None."""
    if created_at is None:
        return None
    if hasattr(created_at, "timestamp"):
        return created_at
    s = str(created_at)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26].replace("Z", "").replace("+00:00", ""), fmt.replace("T", " ")[:19])
        except ValueError:
            continue
    return None


def main():
    db = Database()
    db.initialize()
    alerts = db.get_confirmed_job_alerts()
    if not alerts:
        print("No confirmed subscriptions.")
        return 0
    now = datetime.utcnow()
    sent = 0
    for sub in alerts:
        freq = (sub.get("frequency") or "daily").strip().lower()
        last_sent = sub.get("last_sent_at")
        if last_sent and hasattr(last_sent, "timestamp"):
            since = last_sent
        else:
            since = now - timedelta(days=7 if freq == "weekly" else 1)
        keywords = (sub.get("keywords") or "").strip() or None
        location = (sub.get("location") or "").strip() or None
        jobs = db.get_jobs(limit=50, offset=0, search=keywords, location=location, sort="newest")
        # Filter by created_at >= since
        try:
            since_ts = since.timestamp() if hasattr(since, "timestamp") else since
        except Exception:
            since_ts = since
        new_jobs = []
        for j in jobs:
            ct = parse_created_at(j.get("created_at"))
            if not ct:
                continue
            try:
                j_ts = ct.timestamp() if hasattr(ct, "timestamp") else ct
            except Exception:
                continue
            if j_ts >= since_ts:
                new_jobs.append(j)
        if not new_jobs:
            continue
        email = sub.get("email")

        # Telegram bot subscribers — send via bot API, skip SMTP
        if is_telegram_subscriber(email):
            user_id = telegram_user_id(email)
            digest_text = build_telegram_digest(new_jobs)
            if send_telegram(user_id, digest_text):
                db.mark_alert_sent(sub["id"])
                sent += 1
                print(f"Sent Telegram digest to user {user_id} ({len(new_jobs)} jobs)")
            continue

        subject = f"EthioJobs: {len(new_jobs)} new job(s) for you"
        lines = [f"New jobs matching your alert ({len(new_jobs)}):", ""]
        for j in new_jobs[:20]:
            title = (j.get("title") or "Job")[:80]
            company = (j.get("company") or "")[:60]
            job_id = j.get("id")
            url = f"{SITE_BASE_URL}/job/{job_id}"
            label = f"{title}" + (f" — {company}" if company else "")
            lines.append(f"- {label}")
            lines.append(f"  {url}")
            lines.append("")
        lines.append(f"Browse all jobs: {SITE_BASE_URL}")
        lines.append(f"Unsubscribe: {SITE_BASE_URL}?unsubscribe=1")
        body_text = "\n".join(lines)
        body_html = (
            "<div style='font-family:sans-serif;max-width:600px'>"
            f"<h2 style='color:#065f46'>New jobs for you</h2>"
            f"<p>{len(new_jobs)} new job(s) matching your alert:</p><ul>"
        )
        for j in new_jobs[:20]:
            title = (j.get("title") or "Job").replace("<", "&lt;").replace(">", "&gt;")[:80]
            company = (j.get("company") or "").replace("<", "&lt;").replace(">", "&gt;")[:60]
            deadline = (j.get("deadline") or "")[:40]
            job_id = j.get("id")
            url = f"{SITE_BASE_URL}/job/{job_id}"
            body_html += (
                f'<li style="margin-bottom:12px">'
                f'<a href="{url}" style="color:#065f46;font-weight:600">{title}</a>'
                + (f'<br><span style="color:#555">{company}</span>' if company else "")
                + (f'<br><small style="color:#888">Deadline: {deadline}</small>' if deadline else "")
                + "</li>"
            )
        body_html += (
            f'</ul><p><a href="{SITE_BASE_URL}" style="color:#065f46">Browse all jobs</a></p>'
            f'<p style="font-size:12px;color:#888">You are receiving this because you subscribed to job alerts on Srafelagi. '
            f'<a href="{SITE_BASE_URL}?unsubscribe=1">Unsubscribe</a></p>'
            "</div>"
        )
        if send_email(email, subject, body_text, body_html):
            db.mark_alert_sent(sub["id"])
            sent += 1
            print(f"Sent digest to {email} ({len(new_jobs)} jobs)")
    print(f"Done. Sent {sent} digest(s).")
    return sent


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result >= 0 else 1)
