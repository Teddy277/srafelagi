"""
Srafelagi API - Complete Version
"""
import os
import socket
import hashlib
import logging
from contextlib import closing
from datetime import datetime, timedelta

from typing import Optional
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, Response, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import uvicorn
from database import Database

try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logger.warning("PyJWT not installed. Admin login will not work. Install with: pip install PyJWT")

app = FastAPI(title="EthioJobs API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db = Database()

# ── Simple in-memory TTL cache + rate limiter ────────────────────────────────
import time as _time

class _TTLCache:
    def __init__(self):
        self._store = {}

    def get(self, key):
        entry = self._store.get(key)
        if entry and _time.monotonic() < entry["exp"]:
            return entry["val"]
        return None

    def set(self, key, val, ttl: int):
        self._store[key] = {"val": val, "exp": _time.monotonic() + ttl}

    def delete(self, key):
        self._store.pop(key, None)

_cache = _TTLCache()

class _RateLimiter:
    """Sliding-window per-IP rate limiter (no extra dependencies)."""
    def __init__(self, max_requests: int, window_seconds: int):
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict = {}  # ip -> [timestamps]

    def is_allowed(self, ip: str) -> bool:
        now = _time.monotonic()
        cutoff = now - self._window
        hits = [t for t in self._hits.get(ip, []) if t > cutoff]
        if len(hits) >= self._max:
            self._hits[ip] = hits
            return False
        hits.append(now)
        self._hits[ip] = hits
        return True

# 60 requests per minute per IP on public job endpoints
_rate_limiter = _RateLimiter(max_requests=60, window_seconds=60)

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# Admin authentication
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
_ADMIN_PASSWORD_RAW = os.getenv("ADMIN_PASSWORD", "").strip()
_ADMIN_BCRYPT_HASH = os.getenv("ADMIN_PASSWORD_HASH", "").strip()  # bcrypt hash takes priority
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production").strip()

try:
    import bcrypt as _bcrypt
    _BCRYPT_AVAILABLE = True
except ImportError:
    _bcrypt = None
    _BCRYPT_AVAILABLE = False

if not _ADMIN_BCRYPT_HASH and not _ADMIN_PASSWORD_RAW:
    logger.warning("No admin password set. Set ADMIN_PASSWORD_HASH in .env (recommended) or ADMIN_PASSWORD.")

def _check_admin_password(password: str) -> bool:
    """Verify admin password. Tries bcrypt hash first, falls back to plaintext compare."""
    if _ADMIN_BCRYPT_HASH:
        if _BCRYPT_AVAILABLE:
            try:
                return _bcrypt.checkpw(password.encode(), _ADMIN_BCRYPT_HASH.encode())
            except Exception:
                return False
        else:
            logger.warning("ADMIN_PASSWORD_HASH is set but bcrypt is not installed. Run: pip install bcrypt")
            return False
    # Fallback: plain password comparison (only for dev/testing)
    return bool(_ADMIN_PASSWORD_RAW and password == _ADMIN_PASSWORD_RAW)
JWT_ALGORITHM = "HS256"
security = HTTPBearer()


def _display_host(host: str) -> str:
    if host in {"0.0.0.0", "127.0.0.1", "::", "::1"}:
        return "localhost"
    return host


def _can_bind(host: str, port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
        return True


def _pick_server_port(host: str, preferred_port: int) -> tuple[int, bool]:
    candidates = []
    for candidate in [preferred_port, 8000, 8001, 8002, 3000, 5000, 8888, 9000]:
        if candidate > 0 and candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        if _can_bind(host, candidate):
            return candidate, candidate != preferred_port

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1], True


SERVER_HOST = (os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0")
PREFERRED_PORT = int(os.getenv("PORT", "8000"))
SERVER_PORT, SERVER_PORT_WAS_FALLBACK = _pick_server_port(SERVER_HOST, PREFERRED_PORT)
PUBLIC_HOST = (os.getenv("PUBLIC_HOST", "").strip() or _display_host(SERVER_HOST))
DEFAULT_SITE_BASE_URL = f"http://{PUBLIC_HOST}:{SERVER_PORT}"


def create_access_token(username: str) -> str:
    if not JWT_AVAILABLE:
        raise HTTPException(status_code=500, detail="JWT not available. Install PyJWT.")
    expire = datetime.utcnow() + timedelta(hours=24)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not JWT_AVAILABLE:
        raise HTTPException(status_code=500, detail="JWT not available. Install PyJWT.")
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        if username != ADMIN_USERNAME:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.on_event("startup")
async def startup():
    db.initialize()
    logger.info("Database ready")
    import asyncio
    asyncio.create_task(_schedule_daily_digest())
    asyncio.create_task(_schedule_expired_cleanup())


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Telegram POSTs every user message here. Replaces the long-polling bot."""
    import telegram_webhook as tg
    if tg.WEBHOOK_SECRET:
        sent_secret = request.headers.get("x-telegram-bot-api-secret-token", "")
        if sent_secret != tg.WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="invalid secret")
    try:
        update = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}
    try:
        import asyncio
        await asyncio.to_thread(tg.handle_update, update, db)
    except Exception as e:
        logger.error("telegram webhook error: %s", e)
    return {"ok": True}


async def _schedule_daily_digest():
    """Run job alert digests every day at 09:00 UTC automatically."""
    import asyncio
    from datetime import datetime, timedelta

    while True:
        now = datetime.utcnow()
        next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        wait = (next_run - now).total_seconds()
        logger.info("Next digest scheduled at %s UTC (in %.0f seconds)", next_run.strftime("%Y-%m-%d %H:%M"), wait)
        await asyncio.sleep(wait)
        try:
            logger.info("Running daily job alert digest...")
            import send_job_digests
            sent = send_job_digests.main()
            logger.info("Daily digest done. Sent: %s", sent)
        except Exception as e:
            logger.error("Daily digest failed: %s", e)


async def _schedule_expired_cleanup():
    """Delete expired jobs every night at 02:00 UTC.
    Only removes jobs whose deadline has passed. Jobs with no deadline
    are removed after 60 days so the DB stays lean.
    """
    import asyncio
    from datetime import datetime, timedelta

    while True:
        now = datetime.utcnow()
        next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        wait = (next_run - now).total_seconds()
        logger.info("Next expired-job cleanup at %s UTC (in %.0f s)", next_run.strftime("%Y-%m-%d %H:%M"), wait)
        await asyncio.sleep(wait)
        try:
            # Delete jobs whose deadline has passed
            expired = db.delete_expired_jobs()
            # Also delete jobs with no deadline that are older than 60 days
            no_deadline_old = _delete_old_no_deadline_jobs(days=60)
            logger.info("Cleanup done — expired: %d, no-deadline older than 60d: %d", expired, no_deadline_old)
        except Exception as e:
            logger.error("Expired job cleanup failed: %s", e)


def _delete_old_no_deadline_jobs(days: int = 60) -> int:
    """Delete jobs that have no deadline and were scraped more than `days` days ago."""
    try:
        db._ensure_connection()
        with db.conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM jobs
                WHERE (deadline_text IS NULL OR deadline_text = '')
                  AND created_at < NOW() - INTERVAL '%s days'
                """,
                (days,),
            )
            count = cur.rowcount
        db.conn.commit()
        return count
    except Exception as e:
        logger.error("Failed to delete old no-deadline jobs: %s", e)
        try:
            db.conn.rollback()
        except Exception:
            pass
        return 0


# ============ API ROUTES ============

@app.get("/api/jobs")
async def get_jobs(
    request: Request,
    page: int = 1,
    per_page: int = 12,
    search: str = None,
    category: str = None,
    location: str = None,
    expiring: str = None,
    sort: str = None,
    min_salary: int = None,
):
    if not _rate_limiter.is_allowed(_get_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")
    offset = (page - 1) * per_page
    cat_param = category.strip().lower() if category and isinstance(category, str) and category.strip() else None
    exp = expiring if expiring in ("today", "tomorrow", "week") else None
    sal = min_salary if min_salary and min_salary > 0 else None
    jobs = db.get_jobs(
        limit=per_page,
        offset=offset,
        search=search,
        category=cat_param,
        location=location,
        expiring=exp,
        sort=sort if sort in ("newest", "deadline") else None,
        min_salary=sal,
    )
    total = db.get_job_count(
        search=search,
        category=cat_param,
        location=location,
        expiring=exp,
        min_salary=sal,
    )
    
    # Fix mailto in apply_url and ensure apply_email when apply type is email
    for job in jobs:
        if job.get('apply_url') and str(job['apply_url']).startswith('mailto:'):
            job['apply_email'] = (job['apply_url'][7:].split('?')[0] or '').strip()
            job['apply_url'] = None
        if (job.get('apply_type') or '').lower() in ('email', 'mailto') and not (job.get('apply_email') or '').strip() and job.get('apply_url'):
            u = str(job['apply_url']).strip()
            if u.startswith('mailto:'):
                job['apply_email'] = (u[7:].split('?')[0] or '').strip()
                job['apply_url'] = None
    
    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page)
    }

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int):
    job = db.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Fix mailto in apply_url and ensure apply_email when apply type is email
    if job.get('apply_url') and str(job['apply_url']).startswith('mailto:'):
        job['apply_email'] = (job['apply_url'][7:].split('?')[0] or '').strip()
        job['apply_url'] = None
    if (job.get('apply_type') or '').lower() in ('email', 'mailto') and not (job.get('apply_email') or '').strip() and job.get('apply_url'):
        u = str(job['apply_url']).strip()
        if u.startswith('mailto:'):
            job['apply_email'] = (u[7:].split('?')[0] or '').strip()
            job['apply_url'] = None
    
    return job

@app.get("/api/jobs/{job_id}/stats")
async def get_job_stats(job_id: int):
    """Trust signals for the modal: views, applies, age."""
    job = db.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return db.get_job_stats(job_id)


@app.get("/api/stats")
async def get_stats():
    cached = _cache.get("stats")
    if cached is not None:
        return cached
    result = db.get_stats()
    _cache.set("stats", result, ttl=300)  # 5 minutes
    return result

@app.get("/api/categories")
async def get_categories():
    cached = _cache.get("categories")
    if cached is not None:
        return cached
    result = db.get_categories()
    _cache.set("categories", result, ttl=600)  # 10 minutes
    return result

@app.get("/health")
async def health():
    try:
        db._ensure_connection()
        return {"status": "ok"}
    except Exception:
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "db_error"}, status_code=503)


# ============ JOB VIEW TRACKING ============
@app.get("/api/view")
@app.post("/api/view")
async def record_view(id: int = None):
    """Record a job view (modal or job page). No auth. GET or POST. Returns 204."""
    if id is None:
        raise HTTPException(status_code=400, detail="Missing id")
    job = db.get_job_by_id(id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db.record_job_view(id)
    return Response(status_code=204)

# ============ APPLY CLICK TRACKING (redirect) ============
@app.get("/api/out")
@app.post("/api/out")
async def apply_out(id: int = None, type: str = None):
    """Track apply click and redirect to apply_url, or record email click and return 204. GET or POST (for sendBeacon)."""
    if id is None:
        raise HTTPException(status_code=400, detail="Missing id")
    job = db.get_job_by_id(id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if (type or "").strip().lower() == "email":
        db.record_apply_click(id, "email")
        return Response(status_code=204)
    db.record_apply_click(id, "link")
    target = (job.get("apply_url") or "").strip()
    if not target:
        target = (job.get("source_url") or "").strip()
    if not target:
        return RedirectResponse(url="/", status_code=302)
    return RedirectResponse(url=target, status_code=302)


# ============ RSS FEED ============
@app.get("/feed")
async def rss_feed(request: Request, category: str = None, limit: int = 50):
    """RSS 2.0 feed of latest jobs. Optional: category=it|finance|banking|ngo|fresh_graduate, limit=50."""
    base = str(request.base_url).rstrip("/")
    cat = category.strip().lower() if category and isinstance(category, str) and category.strip() else None
    jobs = db.get_jobs(limit=min(limit, 100), offset=0, category=cat, sort="newest")
    import xml.etree.ElementTree as ET
    from html import escape as html_escape
    rss = ET.Element("rss", version="2.0", attrib={"xmlns:atom": "http://www.w3.org/2005/Atom"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Srafelagi — Jobs in Ethiopia"
    ET.SubElement(channel, "link").text = base
    ET.SubElement(channel, "description").text = "Latest job listings from Srafelagi, GeezJobs, Afriwork and Telegram channels."
    ET.SubElement(channel, "language").text = "en"
    for j in jobs:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = (j.get("title") or "Job")[:200]
        ET.SubElement(item, "link").text = f"{base}#job={j.get('id')}"
        desc = (j.get("description") or "")[:500].replace("<", "&lt;").replace(">", "&gt;")
        ET.SubElement(item, "description").text = desc
        if j.get("company"):
            ET.SubElement(item, "author").text = html_escape(j["company"][:100])
        if j.get("created_at"):
            raw = j["created_at"]
            try:
                if hasattr(raw, "strftime"):
                    dt = raw
                elif "T" in str(raw):
                    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(str(raw)[:19], "%Y-%m-%d %H:%M:%S")
                ET.SubElement(item, "pubDate").text = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
            except Exception:
                ET.SubElement(item, "pubDate").text = str(raw)[:50]
    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode").encode("utf-8")
    return Response(content=xml_bytes, media_type="application/rss+xml")


# ============ JOB ALERTS (EMAIL SUBSCRIPTIONS) ============
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SITE_BASE_URL = os.getenv("SITE_BASE_URL", DEFAULT_SITE_BASE_URL).strip().rstrip("/")
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER or "noreply@srafelagi.et").strip()


def send_email(to: str, subject: str, body_text: str, body_html: str = None) -> bool:
    """Send email via SMTP. Returns True if sent, False if not configured or error."""
    if not SMTP_HOST or not SMTP_USER:
        logger.warning("Job alerts: SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env to send emails.")
        return False
    try:
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
        logger.error("Failed to send email: %s", e)
        return False


class SubscribeRequest(BaseModel):
    email: str
    keywords: str = None
    location: str = None
    frequency: str = "daily"


@app.post("/api/alerts/subscribe")
async def alerts_subscribe(req: SubscribeRequest, request: Request):
    """Subscribe to job alerts. Sends confirmation email."""
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    frequency = (req.frequency or "daily").strip().lower()
    if frequency not in ("daily", "weekly"):
        frequency = "daily"
    token = db.add_job_alert(email, keywords=req.keywords, location=req.location, frequency=frequency)
    if not token:
        raise HTTPException(status_code=500, detail="Failed to subscribe")
    confirm_url = f"{SITE_BASE_URL}/api/alerts/confirm?token={token}"
    text = f"Confirm your job alert subscription at Srafelagi.\n\nClick here to confirm: {confirm_url}\n\nIf you didn't request this, ignore this email."
    html = f"<p>Confirm your job alert subscription at Srafelagi.</p><p><a href=\"{confirm_url}\">Click here to confirm</a></p><p>If you didn't request this, ignore this email.</p>"
    send_email(email, "Confirm your Srafelagi alert", text, html)
    return {"ok": True, "message": "Check your email to confirm your subscription."}


@app.get("/api/alerts/confirm")
async def alerts_confirm(token: str = None):
    """Confirm subscription via token (from email link). Redirects to home with query param."""
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")
    ok = db.confirm_job_alert(token)
    if not ok:
        raise HTTPException(status_code=404, detail="Invalid or expired link")
    return RedirectResponse(url=f"/?confirmed=1", status_code=302)


class UnsubscribeRequest(BaseModel):
    email: str


@app.post("/api/alerts/unsubscribe")
async def alerts_unsubscribe(req: UnsubscribeRequest):
    """Unsubscribe from job alerts by email."""
    email = (req.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email required")
    removed = db.unsubscribe_job_alert(email)
    return {"ok": True, "message": "Unsubscribed." if removed else "No subscription found for this email."}


# ============ AI ASSISTANT ============

from fastapi import UploadFile, File
from typing import List as _List

ASSISTANT_SYSTEM_PROMPT = """You are Srafelagi AI, the official AI assistant of Srafelagi — Ethiopia's smart job board.
You help job seekers in Ethiopia find the right jobs, improve their CVs, and prepare for interviews.

IMPORTANT IDENTITY RULES — follow these strictly:
- Your name is "Srafelagi AI". Never say you are Gemini, ChatGPT, Claude, Llama, Groq, or any other AI.
- If anyone asks what AI you are or who made you, say: "I'm Srafelagi AI, built to help Ethiopians find jobs."
- Never reveal the underlying technology or model powering you.

FORMATTING RULES — follow these strictly:
- Never use markdown. No **, *, #, ##, -, --, ***, ```, or any other markdown symbols.
- Write in plain conversational sentences only.
- If listing items, write them as normal sentences or use plain numbers like: 1. 2. 3.
- Keep responses short and natural, like a helpful person texting you.

Your personality:
- Warm, encouraging, and professional
- You know the Ethiopian job market well (NGOs, banks, government, tech, healthcare)
- You understand both English and Amharic job titles and contexts
- You give practical, actionable advice

When the user shares their CV or asks about jobs:
- Identify their key skills, experience level, and field
- Match them to the most relevant jobs from the list provided
- Explain WHY each job is a good match for them
- Give honest advice about their chances and how to improve

When suggesting jobs, always reference the actual jobs given to you in context.
Keep responses concise and helpful. Never make up job listings."""


def _extract_pdf_text(file_bytes: bytes) -> str:
    try:
        import io
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


# Admin-selected AI provider (persists until server restart)
_selected_ai: dict = {"provider": "auto", "model": None}

# Verified free OpenRouter models
_OPENROUTER_FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "openai/gpt-oss-120b:free",
    "google/gemma-4-31b-it:free",
    "deepseek/deepseek-v4-flash:free",
    "google/gemma-4-26b-a4b-it:free",
    "meta-llama/llama-3.2-3b-instruct:free",
]


def _try_groq(messages: list, system: str) -> Optional[str]:
    import requests as _req
    _raw_groq = os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", ""))
    groq_keys = [k.strip() for k in _raw_groq.split(",") if k.strip()]
    groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    groq_messages = [{"role": "system", "content": system}]
    groq_messages += [{"role": m["role"], "content": m["content"]} for m in messages[-8:]]
    for groq_key in groq_keys:
        try:
            resp = _req.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={"model": groq_model, "messages": groq_messages, "max_tokens": 1024, "temperature": 0.7},
                timeout=20,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
            if resp.status_code in (429, 413):
                continue
            logger.warning("Groq error: %s %s", resp.status_code, resp.text[:200])
            break
        except Exception as e:
            logger.warning("Groq key error: %s", e)
    return None


def _try_openrouter(messages: list, system: str, model: Optional[str] = None) -> Optional[str]:
    import requests as _req
    _raw_or = os.getenv("OPENROUTER_API_KEYS", os.getenv("OPENROUTER_API_KEY", ""))
    or_keys = [k.strip() for k in _raw_or.split(",") if k.strip()]
    models_to_try = [model] if model else [m.strip() for m in os.getenv("OPENROUTER_MODELS", ",".join(_OPENROUTER_FREE_MODELS)).split(",") if m.strip()]
    or_messages = [{"role": "system", "content": system}]
    or_messages += [{"role": m["role"], "content": m["content"]} for m in messages[-8:]]
    for or_key in or_keys:
        for or_model in models_to_try:
            try:
                resp = _req.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {or_key}", "Content-Type": "application/json",
                             "HTTP-Referer": "https://srafelagi.et", "X-Title": "Srafelagi AI"},
                    json={"model": or_model, "messages": or_messages, "max_tokens": 1024, "temperature": 0.7},
                    timeout=25,
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    if content and content.strip():
                        logger.info("OpenRouter responded via %s", or_model)
                        return content.strip()
                if resp.status_code in (429, 402, 503, 404):
                    logger.warning("OpenRouter model %s unavailable (%s), trying next...", or_model, resp.status_code)
                    continue
                logger.warning("OpenRouter error: %s %s", resp.status_code, resp.text[:200])
                continue
            except Exception as e:
                logger.warning("OpenRouter model %s error: %s", or_model, e)
    return None


def _gemini_chat(messages: list, system: str = ASSISTANT_SYSTEM_PROMPT) -> str:
    """Route chat to the admin-selected AI provider, or auto-fallback chain."""
    global _selected_ai
    provider = _selected_ai.get("provider", "auto")
    sel_model = _selected_ai.get("model")

    # ── Direct routing when admin has selected a specific provider ──
    if provider == "groq":
        result = _try_groq(messages, system)
        return result or "I'm temporarily unavailable. Please try again in a moment."

    if provider == "openrouter":
        result = _try_openrouter(messages, system, model=sel_model)
        return result or "I'm temporarily unavailable. Please try again in a moment."

    if provider == "gemini":
        pass  # falls through to Gemini block below

    # ── Try Gemini (8s timeout per key) ─────────────────────
    import concurrent.futures as _cf
    try:
        from ai_providers.gemini import GeminiProvider
        provider = GeminiProvider()
        if provider.is_available():
            history_text = ""
            for msg in messages[:-1]:
                role = "User" if msg["role"] == "user" else "Assistant"
                history_text += f"{role}: {msg['content']}\n\n"
            last = messages[-1]["content"] if messages else ""
            full_prompt = f"{system}\n\n{history_text}User: {last}\n\nAssistant:"

            for key in provider._active_keys():
                client = provider._get_client(key)
                if not client:
                    continue
                try:
                    def _call(c=client, p=full_prompt, m=provider.model):
                        return c.models.generate_content(model=m, contents=p)
                    with _cf.ThreadPoolExecutor(max_workers=1) as ex:
                        fut = ex.submit(_call)
                        response = fut.result(timeout=8)
                    text = GeminiProvider._extract_text(response)
                    if text:
                        return text
                except _cf.TimeoutError:
                    logger.warning("Gemini key timed out, skipping to Groq")
                    break
                except Exception as e:
                    err = str(e)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower():
                        provider._mark_exhausted(key)
                        continue
                    logger.warning("Gemini chat error: %s", e)
                    break
    except Exception as e:
        logger.warning("Gemini chat setup failed: %s", e)

    # ── Fallback 1: Groq ────────────────────────────────────
    result = _try_groq(messages, system)
    if result:
        return result

    # ── Fallback 2: OpenRouter ──────────────────────────────
    result = _try_openrouter(messages, system)
    if result:
        return result

    return "I'm temporarily unavailable. Please try again in a moment."


def _jobs_to_context(jobs: list) -> str:
    if not jobs:
        return "No matching jobs found in the database right now."
    lines = ["Here are relevant jobs currently available on Srafelagi:\n"]
    for j in jobs:
        title = j.get("title") or "Job"
        company = j.get("company") or ""
        location = j.get("location") or ""
        deadline = j.get("deadline") or ""
        desc = (j.get("description") or "")[:300]
        jid = j.get("id")
        line = f"- [{title}]" + (f" at {company}" if company else "") + (f" | {location}" if location else "")
        if deadline:
            line += f" | Deadline: {deadline}"
        line += f" | ID: {jid}"
        if desc:
            line += f"\n  {desc}"
        lines.append(line)
    return "\n".join(lines)


class ChatMessage(BaseModel):
    role: str   # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    message: str
    history: _List[ChatMessage] = []
    cv_text: str = ""


def _search_jobs_smart(message: str = "", cv_text: str = "", limit: int = 6) -> list:
    """Search jobs using multiple strategies, always returning results if any exist."""
    # 1. Search by user message (skip short/generic messages)
    if len(message.split()) >= 2:
        jobs = db.get_jobs(limit=limit, search=message[:150], sort="newest")
        if jobs:
            return jobs

    # 2. Extract meaningful CV keywords (skip common words)
    if cv_text:
        _stop = {"and","or","the","is","in","at","to","of","a","an","for","with","i","my","me","we","on","as","it","be"}
        cv_words = [w for w in cv_text.split() if len(w) > 3 and w.lower() not in _stop]
        # Try progressively shorter keyword lists
        for keyword_count in [8, 4, 2]:
            kw = " ".join(cv_words[:keyword_count])
            if kw.strip():
                jobs = db.get_jobs(limit=limit, search=kw, sort="newest")
                if jobs:
                    return jobs

    # 3. Common tech/IT keywords if CV mentions them
    _tech_terms = ["software","developer","engineer","IT","programmer","analyst","data","system","network","database"]
    combined = (message + " " + cv_text).lower()
    for term in _tech_terms:
        if term.lower() in combined:
            jobs = db.get_jobs(limit=limit, search=term, sort="newest")
            if jobs:
                return jobs

    # 4. Final fallback — return latest jobs regardless
    return db.get_jobs(limit=limit, sort="newest")


@app.post("/api/assistant/chat")
async def assistant_chat(req: ChatRequest):
    """AI job assistant chat. Searches real jobs and responds with Gemini."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")

    jobs = _search_jobs_smart(message=req.message, cv_text=req.cv_text)
    jobs_context = _jobs_to_context(jobs)

    # Build system prompt with jobs + CV context
    system = ASSISTANT_SYSTEM_PROMPT
    if req.cv_text:
        system += f"\n\nThe user's CV/profile:\n{req.cv_text[:3000]}"
    system += f"\n\n{jobs_context}"

    # Build message history
    messages = [{"role": m.role, "content": m.content} for m in req.history[-8:]]
    messages.append({"role": "user", "content": req.message})

    reply = _gemini_chat(messages, system=system)

    # Return reply + job cards for the frontend to display
    return {
        "reply": reply,
        "jobs": jobs[:5],
    }


@app.post("/api/assistant/cv")
async def assistant_cv(file: UploadFile = File(...)):
    """Upload a CV (PDF or TXT), extract text, find matching jobs, return AI summary."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:  # 5MB limit
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")

    # Extract text
    filename = (file.filename or "").lower()
    if filename.endswith(".pdf"):
        cv_text = _extract_pdf_text(content)
    else:
        try:
            cv_text = content.decode("utf-8", errors="ignore")
        except Exception:
            cv_text = ""

    if not cv_text.strip():
        raise HTTPException(status_code=400, detail="Could not read text from file. Try a text-based PDF or .txt file.")

    # Ask Gemini to extract profile
    profile_prompt = f"""Extract a brief professional profile from this CV. Return:
- Name (if found)
- Field / Job type they are targeting
- Years of experience
- Top 5 skills
- Education level
- Suggested job search keywords (3-5 words for searching Ethiopian job boards)

CV text:
{cv_text[:4000]}

Reply in plain text, structured clearly."""

    profile_summary = _gemini_chat(
        [{"role": "user", "content": profile_prompt}],
        system="You are a professional CV analyst. Be concise and accurate."
    )

    # Search jobs based on CV using smart multi-strategy search
    jobs = _search_jobs_smart(cv_text=cv_text, limit=6)

    # Ask Gemini for personalized match explanation
    match_prompt = f"""Based on this candidate's CV, explain which of these jobs are the best matches and why.
Be specific about the match between their skills and each job's requirements.

Candidate profile:
{profile_summary}

{_jobs_to_context(jobs)}

Give a warm, encouraging response with clear job recommendations."""

    match_reply = _gemini_chat(
        [{"role": "user", "content": match_prompt}],
        system=ASSISTANT_SYSTEM_PROMPT
    )

    return {
        "cv_text": cv_text[:5000],
        "profile": profile_summary,
        "reply": match_reply,
        "jobs": jobs[:5],
    }


# ============ ADMIN API ============

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/admin/login")
async def admin_login(req: LoginRequest):
    username = req.username.strip()
    password = req.password.strip()
    if username == ADMIN_USERNAME and _check_admin_password(password):
        token = create_access_token(username)
        return {"access_token": token, "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/admin/stats")
async def admin_stats(username: str = Depends(verify_token)):
    stats = db.get_stats()
    db._ensure_connection()
    try:
        with db.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM jobs")
            total_all = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM jobs WHERE created_at > NOW() - INTERVAL '24 hours'")
            last_24h = cur.fetchone()[0]
            # Count expired jobs (without deleting)
            cur.execute("SELECT id, deadline_text as deadline FROM jobs")
            rows = cur.fetchall()
            expired_count = sum(1 for r in rows if _is_job_expired(dict(r)))
    except Exception as e:
        total_all = stats.get('total_jobs', 0)
        last_24h = stats.get('last_24h', 0)
        expired_count = 0
    apply_stats = db.get_apply_stats()
    top_jobs = db.get_top_jobs_by_applies(10)
    return {
        "total_jobs": stats.get('total_jobs', 0),
        "total_all": total_all,
        "last_24h": last_24h,
        "with_apply_link": stats.get('with_apply_link', 0),
        "expired_count": expired_count,
        "total_apply_clicks": apply_stats.get("total_clicks", 0),
        "apply_clicks_24h": apply_stats.get("clicks_24h", 0),
        "apply_clicks_7d": apply_stats.get("clicks_7d", 0),
        "top_jobs_by_applies": top_jobs,
    }

@app.get("/api/admin/jobs")
async def admin_list_jobs(
    page: int = 1,
    per_page: int = 50,
    search: str = None,
    username: str = Depends(verify_token)
):
    offset = (page - 1) * per_page
    jobs = db.get_jobs(limit=per_page, offset=offset, search=search)
    total = db.get_job_count(search=search)
    job_ids = [j["id"] for j in jobs if j.get("id")]
    apply_counts = db.get_apply_counts_for_jobs(job_ids) if job_ids else {}
    for j in jobs:
        j["apply_count"] = apply_counts.get(j["id"], 0)
    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page)
    }

@app.get("/api/admin/jobs/{job_id}")
async def admin_get_job(job_id: int, username: str = Depends(verify_token)):
    job = db.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    counts = db.get_apply_counts_for_jobs([job_id])
    job["apply_count"] = counts.get(job_id, 0)
    return job

@app.put("/api/admin/jobs/{job_id}")
async def admin_update_job(job_id: int, job_data: dict, username: str = Depends(verify_token)):
    existing = db.get_job_by_id(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Update job fields
    updated = db.save_job({**existing, **job_data})
    if updated:
        return {"success": True, "job_id": updated}
    raise HTTPException(status_code=400, detail="Failed to update job")

@app.delete("/api/admin/jobs/{job_id}")
async def admin_delete_job(job_id: int, username: str = Depends(verify_token)):
    db._ensure_connection()
    try:
        with db.conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
            db.conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Job not found")
            return {"success": True, "deleted": job_id}
    except Exception as e:
        db.conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/jobs/expired")
async def admin_delete_expired(username: str = Depends(verify_token)):
    count = db.delete_expired_jobs()
    return {"success": True, "deleted_count": count}

@app.get("/api/admin/stats/views")
async def admin_view_stats(period: str = "month", username: str = Depends(verify_token)):
    """View counts for dashboard. period: day | week | month."""
    period = (period or "month").strip().lower()
    if period not in ("day", "week", "month"):
        period = "month"
    return db.get_view_stats(period)


# ── AI Provider Management ──────────────────────────────────────────────────

class AISelectRequest(BaseModel):
    provider: str   # "auto" | "gemini" | "groq" | "openrouter"
    model: Optional[str] = None

class AITestRequest(BaseModel):
    provider: str
    model: Optional[str] = None

@app.get("/api/admin/ai-providers")
async def admin_ai_providers(username: str = Depends(verify_token)):
    gemini_keys = len([k for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()])
    groq_keys   = len([k for k in os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", "")).split(",") if k.strip()])
    or_keys     = len([k for k in os.getenv("OPENROUTER_API_KEYS", os.getenv("OPENROUTER_API_KEY", "")).split(",") if k.strip()])
    providers = [
        {"id": "gemini",     "name": "Gemini",  "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"), "keys": gemini_keys},
        {"id": "groq",       "name": "Groq",    "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), "keys": groq_keys},
    ] + [
        {"id": "openrouter", "name": "OpenRouter", "model": m, "keys": or_keys}
        for m in _OPENROUTER_FREE_MODELS
    ]
    return {"providers": providers, "selected": _selected_ai}

@app.post("/api/admin/ai-providers/test")
async def admin_test_ai_provider(req: AITestRequest, username: str = Depends(verify_token)):
    import time, concurrent.futures as _cf
    import requests as _req
    test_system = "You are a test assistant. Reply with exactly the word: OK"
    test_msgs   = [{"role": "user", "content": "Reply with exactly the word: OK"}]
    start = time.time()

    try:
        if req.provider == "gemini":
            from ai_providers.gemini import GeminiProvider
            prov = GeminiProvider()
            keys = prov._active_keys() if prov.is_available() else []
            if not keys:
                return {"status": "error", "message": "All Gemini keys are quota-exhausted"}
            client = prov._get_client(keys[0])
            prompt = f"{test_system}\n\nUser: Reply with exactly the word: OK\n\nAssistant:"
            def _call():
                return client.models.generate_content(model=prov.model, contents=prompt)
            with _cf.ThreadPoolExecutor(max_workers=1) as ex:
                response = ex.submit(_call).result(timeout=10)
            text = GeminiProvider._extract_text(response) or ""
            return {"status": "ok", "response": text[:60], "elapsed": round(time.time()-start, 2)}

        if req.provider == "groq":
            _raw = os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", ""))
            keys = [k.strip() for k in _raw.split(",") if k.strip()]
            if not keys:
                return {"status": "error", "message": "No Groq keys configured"}
            resp = _req.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {keys[0]}", "Content-Type": "application/json"},
                json={"model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                      "messages": [{"role": "system", "content": test_system}, {"role": "user", "content": "Reply with exactly the word: OK"}],
                      "max_tokens": 10},
                timeout=12,
            )
            elapsed = round(time.time()-start, 2)
            if resp.status_code == 200:
                return {"status": "ok", "response": resp.json()["choices"][0]["message"]["content"][:60], "elapsed": elapsed}
            return {"status": "error", "message": f"HTTP {resp.status_code}: {resp.text[:120]}"}

        if req.provider == "openrouter":
            _raw = os.getenv("OPENROUTER_API_KEYS", os.getenv("OPENROUTER_API_KEY", ""))
            keys = [k.strip() for k in _raw.split(",") if k.strip()]
            if not keys:
                return {"status": "error", "message": "No OpenRouter keys configured"}
            model = req.model or _OPENROUTER_FREE_MODELS[0]
            resp = _req.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {keys[0]}", "Content-Type": "application/json",
                         "HTTP-Referer": "https://srafelagi.et", "X-Title": "Srafelagi AI"},
                json={"model": model,
                      "messages": [{"role": "system", "content": test_system}, {"role": "user", "content": "Reply with exactly the word: OK"}],
                      "max_tokens": 10},
                timeout=18,
            )
            elapsed = round(time.time()-start, 2)
            if resp.status_code == 200:
                return {"status": "ok", "response": resp.json()["choices"][0]["message"]["content"][:60], "elapsed": elapsed}
            return {"status": "error", "message": f"HTTP {resp.status_code}: {resp.text[:150]}"}

    except _cf.TimeoutError:
        return {"status": "timeout", "message": "Request timed out"}
    except Exception as e:
        return {"status": "error", "message": str(e)[:120]}

    return {"status": "error", "message": "Unknown provider"}

@app.post("/api/admin/ai-providers/select")
async def admin_select_ai_provider(req: AISelectRequest, username: str = Depends(verify_token)):
    global _selected_ai
    _selected_ai = {"provider": req.provider, "model": req.model}
    logger.info("Admin selected AI provider: %s model=%s", req.provider, req.model)
    return {"ok": True, "selected": _selected_ai}


# ============ SERVE FRONTEND ============

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

# Check if frontend folder exists
if os.path.exists(FRONTEND_DIR):
    # Mount CSS folder
    css_dir = os.path.join(FRONTEND_DIR, "css")
    if os.path.exists(css_dir):
        app.mount("/css", StaticFiles(directory=css_dir), name="css")

    # Mount JS folder
    js_dir = os.path.join(FRONTEND_DIR, "js")
    if os.path.exists(js_dir):
        app.mount("/js", StaticFiles(directory=js_dir), name="js")
    
    # Mount images folder (if exists)
    img_dir = os.path.join(FRONTEND_DIR, "images")
    if os.path.exists(img_dir):
        app.mount("/images", StaticFiles(directory=img_dir), name="images")

    # ============ JOB PAGE (SEO, shareable URL) ============
    def _job_page_html(job: dict, base: str) -> str:
        from html import escape
        jid = job.get("id")
        title = (job.get("title") or "Job")[:120]
        company = (job.get("company") or "")[:80]
        location = (job.get("location") or "")[:80]
        deadline = (job.get("deadline_text") or job.get("deadline") or "")[:80]
        salary = (job.get("salary") or "")[:80]
        job_url = f"{base}/job/{jid}"
        og_image = f"{base}/api/og/job/{jid}"
        plain_desc = " ".join((job.get("description") or "").split())[:200]
        meta_desc = plain_desc or (f"{title}" + (f" at {company}" if company else "") + " — Apply now on Srafelagi.")

        # Build apply CTA (sidebar + inline)
        if job.get("apply_email"):
            email = escape(job["apply_email"])
            apply_cta = (
                f'<a href="mailto:{email}" class="btn btn-primary btn-lg apply-cta">'
                f'<i class="fas fa-paper-plane"></i> Apply by email</a>'
                f'<button type="button" class="btn btn-outline btn-block" onclick="navigator.clipboard.writeText(\'{email}\').then(()=>this.textContent=\'Email copied!\')">'
                f'<i class="fas fa-copy"></i> Copy email address</button>'
            )
            inline_apply = f'<div class="email-box"><span class="email-display">{email}</span></div>'
        elif job.get("apply_url"):
            apply_cta = (
                f'<a href="{base}/api/out?id={jid}" class="btn btn-primary btn-lg apply-cta" target="_blank" rel="noopener">'
                f'<i class="fas fa-external-link-alt"></i> Apply online</a>'
            )
            inline_apply = ""
        else:
            apply_cta = '<p class="apply-note">Apply via the source link in the description.</p>'
            inline_apply = ""

        # Format description into paragraphs / bullets
        raw_desc = (job.get("description") or "")[:8000]
        paragraphs = []
        for block in [p.strip() for p in raw_desc.split("\n\n") if p.strip()]:
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            is_bullets = lines and all(
                l.startswith(("-", "*", "•", "·")) or l[:2].isdigit() and l[2:3] in (".", ")")
                for l in lines
            )
            if is_bullets and len(lines) >= 1:
                items = "".join(f"<li>{escape(l.lstrip('-*•·0123456789.) '))}</li>" for l in lines)
                paragraphs.append(f"<ul>{items}</ul>")
            else:
                paragraphs.append(f"<p>{escape(block).replace(chr(10), '<br>')}</p>")
        desc_html = "".join(paragraphs) if paragraphs else "<p>No description available.</p>"

        logo_letter = ((company or title or "?").strip() or "?")[:1].upper()
        full_title = f"{title}" + (f" — {company}" if company else "") + " | Srafelagi"

        meta_pills = ""
        if location:
            meta_pills += f'<span><i class="fas fa-map-marker-alt"></i> {escape(location)}</span>'
        if deadline:
            meta_pills += f'<span><i class="fas fa-calendar"></i> {escape(deadline)}</span>'
        if salary:
            meta_pills += f'<span><i class="fas fa-coins"></i> {escape(salary)}</span>'

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(full_title)}</title>
<meta name="description" content="{escape(meta_desc[:160])}">
<link rel="canonical" href="{escape(job_url)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{escape(full_title)}">
<meta property="og:description" content="{escape(meta_desc[:200])}">
<meta property="og:url" content="{escape(job_url)}">
<meta property="og:image" content="{escape(og_image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:site_name" content="Srafelagi">
<meta property="og:locale" content="en_US">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{escape(full_title)}">
<meta name="twitter:description" content="{escape(meta_desc[:200])}">
<meta name="twitter:image" content="{escape(og_image)}">
<script type="application/ld+json">{{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "{escape(title)}",
  "description": "{escape(plain_desc[:500])}",
  "hiringOrganization": {{ "@type": "Organization", "name": "{escape(company or 'Srafelagi')}" }},
  "jobLocation": {{ "@type": "Place", "address": {{ "@type": "PostalAddress", "addressLocality": "{escape(location or 'Addis Ababa')}", "addressCountry": "ET" }} }},
  "url": "{escape(job_url)}"
}}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🇪🇹</text></svg>">
<link rel="stylesheet" href="/css/style.css">
<style>
.job-page-shell {{ padding: 110px 0 80px; background: var(--bg-canvas); min-height: 100vh; }}
.job-page-wrap {{ max-width: 1100px; margin: 0 auto; padding: 0 24px; }}
.job-page-card {{
    background: var(--bg-primary);
    border-radius: var(--radius-2xl);
    box-shadow: var(--shadow-lg);
    overflow: hidden;
    border: 1px solid var(--divider);
}}
.job-page-card .modal-hero {{ border-radius: 0; }}
.job-page-card .modal-grid {{ padding: 32px 36px 40px; }}
@media (max-width: 900px) {{
    .job-page-shell {{ padding: 88px 0 60px; }}
    .job-page-wrap {{ padding: 0 12px; }}
    .job-page-card {{ border-radius: var(--radius-xl); }}
}}
</style>
</head>
<body>
<nav class="navbar scrolled" id="navbar">
  <div class="container">
    <a href="/" class="logo">
      <img src="/images/srafelagi.jpg" alt="" class="logo-img">
      <span class="logo-text">Srafelagi</span>
    </a>
    <div class="nav-actions">
      <a href="/#jobs" class="btn btn-primary"><i class="fas fa-search"></i><span>Browse jobs</span></a>
    </div>
  </div>
</nav>

<main class="job-page-shell">
  <div class="job-page-wrap">
    <p style="margin-bottom: 16px;">
      <a href="/" class="link-muted" style="font-size: 14px; font-weight: 500;">
        <i class="fas fa-arrow-left"></i> Back to all jobs
      </a>
    </p>

    <article class="job-page-card">
      <header class="modal-hero">
        <div class="modal-hero-bg"></div>
        <div class="modal-hero-inner">
          <div class="modal-hero-logo">{escape(logo_letter)}</div>
          <div class="modal-hero-text">
            <h1 class="modal-hero-title">{escape(title)}</h1>
            {f'<p class="modal-hero-company">{escape(company)}</p>' if company else ''}
            <div class="modal-hero-meta">{meta_pills}</div>
          </div>
        </div>
      </header>

      <div class="modal-grid">
        <main class="modal-main">
          {f'<div class="apply-section"><h4><i class="fas fa-paper-plane"></i> How to Apply</h4>{inline_apply}</div>' if inline_apply else ''}
          <div class="description-section">
            <div class="description-text">{desc_html}</div>
          </div>
          {f'<div class="source-section"><a href="{escape(job.get("source_url") or "")}" target="_blank" rel="noopener"><i class="fas fa-external-link-alt"></i> View original on source</a></div>' if job.get("source_url") else ''}
        </main>

        <aside class="modal-side">
          <div class="modal-side-card">
            <div class="modal-side-apply">
              {apply_cta}
            </div>
            <div class="modal-side-actions">
              <a class="btn-side-action" href="https://t.me/share/url?url={escape(job_url)}&text={escape(title)}" target="_blank" rel="noopener" aria-label="Share on Telegram">
                <i class="fab fa-telegram"></i><span>Telegram</span>
              </a>
              <a class="btn-side-action" href="https://wa.me/?text={escape(title + ' — ' + job_url)}" target="_blank" rel="noopener" aria-label="Share on WhatsApp">
                <i class="fab fa-whatsapp"></i><span>WhatsApp</span>
              </a>
              <a class="btn-side-action" href="/#jobs" aria-label="Browse all jobs">
                <i class="fas fa-th-large"></i><span>Browse</span>
              </a>
              <a class="btn-side-action" href="mailto:info@srafelagi.et?subject=Report+job&body=Job+URL%3A+{escape(job_url)}" aria-label="Report this job">
                <i class="fas fa-flag"></i><span>Report</span>
              </a>
            </div>
            {f'<div class="modal-side-deadline"><i class="fas fa-clock"></i><div><div class="modal-side-deadline-label">{escape(deadline)}</div><div class="modal-side-deadline-date">Application deadline</div></div></div>' if deadline else ''}
            <div class="modal-side-meta">
              {f'<div class="modal-side-meta-row"><span class="modal-side-meta-label">Company</span><span class="modal-side-meta-value">{escape(company)}</span></div>' if company else ''}
              {f'<div class="modal-side-meta-row"><span class="modal-side-meta-label">Location</span><span class="modal-side-meta-value">{escape(location)}</span></div>' if location else ''}
              {f'<div class="modal-side-meta-row"><span class="modal-side-meta-label">Salary</span><span class="modal-side-meta-value">{escape(salary)}</span></div>' if salary else ''}
            </div>
          </div>
        </aside>
      </div>
    </article>
  </div>
</main>

<footer class="footer" style="margin-top: 0;">
  <div class="container">
    <div class="footer-bottom" style="border: none; padding: 0;">
      <p>&copy; {datetime.utcnow().year} Srafelagi. Made in Ethiopia. <a href="/" style="color: var(--primary);">Home</a></p>
    </div>
  </div>
</footer>

<script>
  // Record view + small interactions
  if (navigator.sendBeacon) {{ navigator.sendBeacon("{base}/api/view?id={jid}"); }}
  else {{ fetch("{base}/api/view?id={jid}").catch(function(){{}}); }}
  window.SRAFELAGI_API_BASE = "{base}";
  window.addEventListener('scroll', function() {{
    var n = document.getElementById('navbar');
    if (n) n.classList.toggle('scrolled', window.scrollY > 10);
  }}, {{ passive: true }});
</script>
<script src="/js/assistant.js"></script>
</body>
</html>"""

    @app.get("/job/{path:path}", response_class=HTMLResponse)
    async def serve_job_page(path: str, request: Request):
        """Serve a single job as a full HTML page for SEO and sharing. Path: 123 or 123-slug."""
        base = str(request.base_url).rstrip("/")
        job_id_str = path.split("-")[0] if path else ""
        try:
            job_id = int(job_id_str)
        except ValueError:
            raise HTTPException(status_code=404, detail="Not found")
        job = db.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.get("apply_url") and str(job.get("apply_url", "")).startswith("mailto:"):
            job["apply_email"] = job["apply_url"][7:].split("?")[0]
            job["apply_url"] = None
        html = _job_page_html(job, base)
        return HTMLResponse(html)

    @app.get("/api/og/job/{job_id}", response_class=Response)
    async def og_image_job(job_id: int, request: Request):
        """Premium SVG Open Graph card for a job — used on Telegram, Facebook, Twitter previews."""
        from html import escape as _e
        job = db.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Not found")

        title_raw = (job.get("title") or "Job").strip()
        company = _e((job.get("company") or "Srafelagi").strip()[:48])
        location = _e((job.get("location") or "").strip()[:36])
        deadline = _e((job.get("deadline_text") or job.get("deadline") or "").strip()[:32])
        logo_letter = _e((company or title_raw or "?")[:1].upper())

        # Wrap title to 2 lines (~26 chars per line)
        words = title_raw.split()
        line1, line2 = [], []
        for w in words:
            if sum(len(x) + 1 for x in line1) + len(w) <= 28:
                line1.append(w)
            elif sum(len(x) + 1 for x in line2) + len(w) <= 30:
                line2.append(w)
        title_l1 = _e(" ".join(line1) or title_raw[:28])
        title_l2 = _e(" ".join(line2))

        meta_parts = []
        if location: meta_parts.append(location)
        if deadline: meta_parts.append("Deadline: " + deadline)
        meta_line = _e(" · ".join(meta_parts))

        w, h = 1200, 630
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#065f46"/>
      <stop offset="55%" stop-color="#047857"/>
      <stop offset="100%" stop-color="#0d9488"/>
    </linearGradient>
    <radialGradient id="glow1" cx="0.85" cy="0.05" r="0.7">
      <stop offset="0%" stop-color="rgba(255,255,255,0.22)"/>
      <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
    </radialGradient>
    <radialGradient id="glow2" cx="0.05" cy="0.95" r="0.7">
      <stop offset="0%" stop-color="rgba(251,191,36,0.18)"/>
      <stop offset="100%" stop-color="rgba(251,191,36,0)"/>
    </radialGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#bg)"/>
  <rect width="{w}" height="{h}" fill="url(#glow1)"/>
  <rect width="{w}" height="{h}" fill="url(#glow2)"/>

  <!-- Top brand row -->
  <g transform="translate(72, 76)">
    <rect width="48" height="48" rx="14" fill="rgba(255,255,255,0.16)" stroke="rgba(255,255,255,0.28)" stroke-width="1.5"/>
    <text x="24" y="33" font-family="Georgia, serif" font-size="26" fill="#ffffff" text-anchor="middle">S</text>
    <text x="64" y="32" font-family="Georgia, serif" font-size="26" fill="#ffffff">Srafelagi</text>
  </g>
  <text x="{w-72}" y="108" font-family="Inter, Arial, sans-serif" font-size="16" fill="rgba(255,255,255,0.75)" text-anchor="end" letter-spacing="3">JOBS · ETHIOPIA</text>

  <!-- Logo tile + content -->
  <g transform="translate(72, 220)">
    <rect width="120" height="120" rx="28" fill="rgba(255,255,255,0.18)" stroke="rgba(255,255,255,0.3)" stroke-width="2"/>
    <text x="60" y="92" font-family="Georgia, serif" font-size="72" fill="#ffffff" text-anchor="middle">{logo_letter}</text>
  </g>

  <text x="220" y="266" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="600" fill="rgba(255,255,255,0.92)">{company}</text>
  <text x="220" y="332" font-family="Georgia, serif" font-size="56" font-weight="400" fill="#ffffff">{title_l1}</text>
  {'<text x="220" y="394" font-family="Georgia, serif" font-size="56" font-weight="400" fill="#ffffff">' + title_l2 + '</text>' if title_l2 else ''}
  {'<text x="220" y="' + ('456' if title_l2 else '394') + '" font-family="Inter, Arial, sans-serif" font-size="22" fill="rgba(255,255,255,0.85)">' + meta_line + '</text>' if meta_line else ''}

  <!-- Footer CTA bar -->
  <rect x="72" y="528" width="1056" height="64" rx="32" fill="rgba(255,255,255,0.12)" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"/>
  <text x="600" y="568" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="600" fill="#ffffff" text-anchor="middle">Apply now · srafelagi.et</text>
</svg>'''
        return Response(content=svg, media_type="image/svg+xml")
    
    # Serve index.html for root
    @app.get("/")
    async def serve_index():
        index_path = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "index.html not found"}
    
    # Serve favicon
    @app.get("/favicon.ico")
    async def serve_favicon():
        favicon_path = os.path.join(FRONTEND_DIR, "favicon.ico")
        if os.path.exists(favicon_path):
            return FileResponse(favicon_path)
        raise HTTPException(status_code=404)

    # Serve privacy page
    @app.get("/privacy")
    async def serve_privacy():
        privacy_path = os.path.join(FRONTEND_DIR, "privacy.html")
        if os.path.exists(privacy_path):
            return FileResponse(privacy_path)
        raise HTTPException(status_code=404)

    # PWA manifest
    @app.get("/manifest.json")
    async def serve_manifest():
        p = os.path.join(FRONTEND_DIR, "manifest.json")
        if os.path.exists(p):
            return FileResponse(p, media_type="application/manifest+json")
        raise HTTPException(status_code=404)

    # Serve admin pages (/admin and /admin/ -> login.html)
    @app.get("/admin/{path:path}")
    async def serve_admin(path: str):
        path = (path or "").strip().lstrip("/")
        admin_dir = os.path.join(FRONTEND_DIR, "admin")
        admin_path = os.path.normpath(os.path.join(admin_dir, path)) if path else admin_dir
        if not admin_path.startswith(admin_dir):
            raise HTTPException(status_code=404)
        if not path or os.path.isdir(admin_path):
            login_path = os.path.join(admin_dir, "login.html")
            if os.path.isfile(login_path):
                return FileResponse(login_path)
            raise HTTPException(status_code=404)
        if os.path.isfile(admin_path):
            return FileResponse(admin_path)
        raise HTTPException(status_code=404)

    # robots.txt
    @app.get("/robots.txt")
    async def serve_robots():
        from fastapi.responses import PlainTextResponse
        content = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /api/\n"
            "Sitemap: https://srafelagi.et/sitemap.xml\n"
        )
        return PlainTextResponse(content)

    # sitemap.xml — includes dynamic job pages
    @app.get("/sitemap.xml")
    async def serve_sitemap():
        BASE = "https://srafelagi.et"
        today = datetime.utcnow().strftime("%Y-%m-%d")
        urls = [
            f'  <url><loc>{BASE}/</loc><changefreq>daily</changefreq><priority>1.0</priority><lastmod>{today}</lastmod></url>',
            f'  <url><loc>{BASE}/privacy</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>',
        ]
        for row in db.get_job_ids_for_sitemap():
            jid = row.get("id")
            created = row.get("created_at")
            lastmod = f"<lastmod>{str(created)[:10]}</lastmod>" if created else ""
            urls.append(
                f'  <url><loc>{BASE}/job/{jid}</loc>'
                f'<changefreq>weekly</changefreq><priority>0.7</priority>{lastmod}</url>'
            )
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        xml += "\n".join(urls)
        xml += "\n</urlset>"
        return Response(content=xml, media_type="application/xml")

else:
    logger.warning("Frontend directory not found: %s", FRONTEND_DIR)
    
    @app.get("/")
    async def no_frontend():
        return {
            "message": "Srafelagi API is running!",
            "jobs_endpoint": "/api/jobs",
            "stats_endpoint": "/api/stats",
            "docs": "/docs",
            "note": "Frontend not found. Create 'frontend' folder."
        }

# ============ MAIN ============

if __name__ == "__main__":
    open_url = f"http://{_display_host(SERVER_HOST)}:{SERVER_PORT}"
    print("=" * 50)
    print("🚀 Srafelagi Portal")
    print("=" * 50)
    print(f"📍 Open: {open_url}")
    print(f"📖 API Docs: {open_url}/docs")
    print(f"💡 Hard refresh: Ctrl+Shift+R")
    print("=" * 50)
    if SERVER_PORT_WAS_FALLBACK:
        print(
            f"Requested port {PREFERRED_PORT} is unavailable. "
            f"Using {SERVER_PORT} instead. Set PORT in .env to override."
        )
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
