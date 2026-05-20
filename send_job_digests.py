"""
Send job alert digests to confirmed subscribers.
Run daily via cron, e.g.: 0 9 * * * cd /path/to/project && python send_job_digests.py

Requires .env with DATABASE_URL and optionally SMTP_* for sending email.
"""
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

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
        subject = f"EthioJobs: {len(new_jobs)} new job(s) for you"
        lines = [f"New jobs matching your alert ({len(new_jobs)}):", ""]
        for j in new_jobs[:20]:
            title = (j.get("title") or "Job")[:80]
            job_id = j.get("id")
            url = f"{SITE_BASE_URL}#job={job_id}"
            lines.append(f"- {title}")
            lines.append(f"  {url}")
            lines.append("")
        body_text = "\n".join(lines)
        body_html = "<p>New jobs matching your alert:</p><ul>"
        for j in new_jobs[:20]:
            title = (j.get("title") or "Job").replace("<", "&lt;").replace(">", "&gt;")[:80]
            job_id = j.get("id")
            url = f"{SITE_BASE_URL}#job={job_id}"
            body_html += f'<li><a href="{url}">{title}</a></li>'
        body_html += "</ul><p>— Srafelagi</p>"
        if send_email(email, subject, body_text, body_html):
            db.mark_alert_sent(sub["id"])
            sent += 1
            print(f"Sent digest to {email} ({len(new_jobs)} jobs)")
    print(f"Done. Sent {sent} digest(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
