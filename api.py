"""
Srafelagi API - Complete Version
"""
import os
import hashlib
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

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
    print("⚠️ PyJWT not installed. Admin login will not work. Install with: pip install PyJWT")

app = FastAPI(title="EthioJobs API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db = Database()

# Admin authentication
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123").strip()
ADMIN_PASSWORD_HASH = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production").strip()
JWT_ALGORITHM = "HS256"
security = HTTPBearer()

# Debug: Print admin config (remove in production)
print(f"🔐 Admin username: {ADMIN_USERNAME}")
print(f"🔐 Admin password hash: {ADMIN_PASSWORD_HASH[:16]}...")

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
    print("✅ Database ready!")

# ============ API ROUTES ============

@app.get("/api/jobs")
async def get_jobs(
    page: int = 1,
    per_page: int = 12,
    search: str = None,
    category: str = None,
    location: str = None,
    expiring: str = None,
    sort: str = None,
):
    offset = (page - 1) * per_page
    # Normalize category to slug so count and list use the same filter
    cat_param = category.strip().lower() if category and isinstance(category, str) and category.strip() else None
    exp = expiring if expiring in ("today", "tomorrow", "week") else None
    jobs = db.get_jobs(
        limit=per_page,
        offset=offset,
        search=search,
        category=cat_param,
        location=location,
        expiring=exp,
        sort=sort if sort in ("newest", "deadline") else None,
    )
    total = db.get_job_count(
        search=search,
        category=cat_param,
        location=location,
        expiring=exp,
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

@app.get("/api/stats")
async def get_stats():
    return db.get_stats()

@app.get("/api/categories")
async def get_categories():
    return db.get_categories()


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

SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://localhost:8080").strip().rstrip("/")
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER or "noreply@srafelagi.et").strip()


def send_email(to: str, subject: str, body_text: str, body_html: str = None) -> bool:
    """Send email via SMTP. Returns True if sent, False if not configured or error."""
    if not SMTP_HOST or not SMTP_USER:
        print("⚠️ Job alerts: SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env to send emails.")
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
        print(f"⚠️ Failed to send email: {e}")
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


# ============ ADMIN API ============

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/admin/login")
async def admin_login(req: LoginRequest):
    username = req.username.strip()
    password = req.password.strip()
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    # Debug logging (remove in production)
    print(f"🔍 Login attempt - Username: '{username}' (expected: '{ADMIN_USERNAME}')")
    print(f"🔍 Password hash: {password_hash[:16]}... (expected: {ADMIN_PASSWORD_HASH[:16]}...)")
    print(f"🔍 Match: username={username == ADMIN_USERNAME}, password={password_hash == ADMIN_PASSWORD_HASH}")
    
    if username == ADMIN_USERNAME and password_hash == ADMIN_PASSWORD_HASH:
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

# ============ SERVE FRONTEND ============

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

# Check if frontend folder exists
if os.path.exists(FRONTEND_DIR):
    print(f"📂 Frontend directory: {FRONTEND_DIR}")
    
    # Mount CSS folder
    css_dir = os.path.join(FRONTEND_DIR, "css")
    if os.path.exists(css_dir):
        app.mount("/css", StaticFiles(directory=css_dir), name="css")
        print(f"   ✅ CSS folder mounted: {css_dir}")
    
    # Mount JS folder
    js_dir = os.path.join(FRONTEND_DIR, "js")
    if os.path.exists(js_dir):
        app.mount("/js", StaticFiles(directory=js_dir), name="js")
        print(f"   ✅ JS folder mounted: {js_dir}")
    
    # Mount images folder (if exists)
    img_dir = os.path.join(FRONTEND_DIR, "images")
    if os.path.exists(img_dir):
        app.mount("/images", StaticFiles(directory=img_dir), name="images")

    # ============ JOB PAGE (SEO, shareable URL) ============
    def _job_page_html(job: dict, base: str) -> str:
        from html import escape
        title = (job.get("title") or "Job").replace("<", "&lt;").replace(">", "&gt;")[:100]
        company = (job.get("company") or "").replace("<", "&lt;").replace(">", "&gt;")[:80]
        job_url = f"{base}/job/{job.get('id')}"
        og_image = f"{base}/api/og/job/{job.get('id')}"
        meta_desc = f"{title}" + (f" at {company}" if company else "") + " — Srafelagi. Apply now."
        jid = job.get("id")
        if job.get("apply_email"):
            apply_btn = f'<a href="mailto:{escape(job.get("apply_email"))}" class="btn btn-primary btn-lg"><i class="fas fa-paper-plane"></i> Send CV by email</a>'
        else:
            apply_btn = f'<a href="{base}/api/out?id={jid}" class="btn btn-primary btn-lg" target="_blank" rel="noopener"><i class="fas fa-external-link-alt"></i> Apply online</a>'
        raw_desc = (job.get("description") or "")[:5000]
        desc_paras = [p.strip() for p in raw_desc.split("\n\n") if p.strip()]
        desc_html = "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in desc_paras) if desc_paras else f"<p>{escape('No description available.')}</p>"
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)} at {escape(company)} | EthioJobs</title>
<meta name="description" content="{escape(meta_desc[:160])}">
<link rel="canonical" href="{escape(job_url)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{escape(title)} at {escape(company)} | Srafelagi">
<meta property="og:description" content="{escape(meta_desc[:200])}">
<meta property="og:url" content="{escape(job_url)}">
<meta property="og:image" content="{escape(og_image)}">
<meta property="og:locale" content="en_US">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{escape(title)} | EthioJobs">
<meta name="twitter:description" content="{escape(meta_desc[:200])}">
<meta name="twitter:image" content="{escape(og_image)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🇪🇹</text></svg>">
<link rel="stylesheet" href="/css/style.css">
</head>
<body>
<nav class="navbar scrolled">
<div class="container">
<a href="/" class="logo" style="display:flex;align-items:center;gap:0.6rem;"><img src="{base}/images/srafelagi.jpg" alt="" class="logo-img" style="height:48px;width:48px;object-fit:cover;border-radius:50%;"><span class="logo-text" style="font-size:1.25rem;font-weight:600;">Srafelagi</span></a>
<div class="nav-actions"><a href="/" class="btn btn-primary"><i class="fas fa-search"></i> Search Jobs</a></div>
</div>
</nav>
<main class="container" style="padding: 6rem 1.5rem 4rem; max-width: 720px;">
<article class="job-page-article">
<h1 style="font-family: var(--font-heading); font-size: 1.5rem; margin-bottom: 0.5rem;">{escape(title)}</h1>
<p style="color: var(--text-muted); font-size: 0.9375rem; margin-bottom: 1rem;">{escape(company)}</p>
<div style="display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; font-size: 0.875rem;">
{f'<span><i class="fas fa-map-marker-alt"></i> {escape(job.get("location") or "")}</span>' if job.get("location") else ""}
{f'<span><i class="fas fa-clock"></i> {escape(job.get("deadline_text") or "")}</span>' if job.get("deadline_text") else ""}
</div>
<div class="description-text job-page-description">{desc_html}</div>
<p style="margin-top: 1.5rem;">
{apply_btn}
<a href="/" class="btn btn-outline" style="margin-left: 0.5rem;">Back to jobs</a>
</p>
</article>
</main>
<footer class="footer" style="margin-top: 3rem;">
<div class="container"><p>&copy; {datetime.utcnow().year} Srafelagi. Made in Ethiopia. <a href="/">Home</a></p></div>
</footer>
<script>fetch("{base}/api/view?id={jid}").catch(function(){{}});</script>
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
        """Simple SVG OG image for a job (title + company)."""
        job = db.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Not found")
        title = (job.get("title") or "Job")[:50].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        company = (job.get("company") or "Srafelagi")[:30].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        w, h = 1200, 630
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<rect fill="#166534" width="{w}" height="{h}"/>
<text x="60" y="280" font-family="Arial,sans-serif" font-size="48" font-weight="bold" fill="white">{title}</text>
<text x="60" y="340" font-family="Arial,sans-serif" font-size="28" fill="rgba(255,255,255,0.9)">{company}</text>
<text x="60" y="420" font-family="Arial,sans-serif" font-size="24" fill="rgba(255,255,255,0.8)">EthioJobs — Apply now</text>
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
        content = """User-agent: *
Allow: /
Disallow: /api/
Sitemap: https://srafelagi.et/sitemap.xml
"""
        return PlainTextResponse(content)

    # sitemap.xml
    @app.get("/sitemap.xml")
    async def serve_sitemap():
        from fastapi.responses import Response
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ethiojobs.et/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>
  <url><loc>https://ethiojobs.et/privacy</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>
</urlset>
"""
        return Response(content=xml, media_type="application/xml")

else:
    print(f"⚠️ Frontend directory not found: {FRONTEND_DIR}")
    print("   Create 'frontend' folder with index.html, css/style.css, js/app.js")
    
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
    print("=" * 50)
    print("🚀 Srafelagi Portal")
    print("=" * 50)
    print(f"📍 Open: http://localhost:8080")
    print(f"📖 API Docs: http://localhost:8080/docs")
    print(f"💡 Hard refresh: Ctrl+Shift+R")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8080)