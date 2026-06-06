// ============================================
// SRAFELAGI - MAIN APPLICATION SCRIPT
// ============================================

// ============ CONFIGURATION ============
function resolveApiBase() {
    if (typeof window.SRAFELAGI_API_BASE === 'string' && window.SRAFELAGI_API_BASE.trim()) {
        return window.SRAFELAGI_API_BASE.trim().replace(/\/$/, '');
    }
    try {
        const saved = window.localStorage.getItem('srafelagi_api_base');
        if (saved && saved.trim()) {
            return saved.trim().replace(/\/$/, '');
        }
    } catch (error) {
        // Fall back to same-origin requests when storage is unavailable.
    }
    return '';
}

const API_BASE = resolveApiBase();
const JOBS_PER_PAGE = 12;

// Channel username (no @) -> long display name for job cards and modal
const CHANNEL_DISPLAY_NAMES = {
    effoyjobs: 'Effoy Jobs',
    informationnegari: 'Information Negari',
    elelanajobs: 'Elelana Jobs',
    freelance_ethio: 'Freelance Ethio',
    geezjobs_ethiopia: 'GeezJobs Ethiopia',
    hahujobs: 'Hahu Jobs',
    addis_zemen_vacancy: 'Addis Zemen Vacancy',
    ethiojobs: 'EthioJobs',
    hagerejobs: 'Hagere Jobs',
    afriwork: 'Afriwork',
};

function getChannelSlug(job) {
    const raw = job.channel_username || job.telegram_channel || '';
    return String(raw).replace(/^@/, '').trim().toLowerCase();
}

function getChannelDisplayName(job) {
    const slug = getChannelSlug(job);
    if (!slug) return '';
    return CHANNEL_DISPLAY_NAMES[slug] || (slug ? '@' + slug : '');
}

const CHANNEL_SVG_ONLY = new Set(['afriwork', 'ethiojobs', 'hagerejobs']);

function getChannelPhotoPath(job) {
    const slug = getChannelSlug(job);
    if (!slug) return '';
    const ext = CHANNEL_SVG_ONLY.has(slug) ? 'svg' : 'jpg';
    return `/images/channels/${slug}.${ext}`;
}

function getChannelHtml(job, options = {}) {
    const name = getChannelDisplayName(job);
    const slug = getChannelSlug(job);
    if (!name && !slug) return '';
    const photoPath = getChannelPhotoPath(job);
    const size = options.size || 28;
    const showLongName = options.longName !== false;
    const displayText = showLongName ? (name || '@' + slug) : ('@' + slug);
    const cssClass = options.className ? ` ${options.className}` : '';
    return `
        <div class="job-source-channel${cssClass}">
            <img src="${escapeHtml(photoPath)}" alt="" class="channel-avatar" width="${size}" height="${size}" loading="lazy" decoding="async"
                 onerror="this.style.display='none';this.nextElementSibling.style.display='inline-flex';">
            <span class="channel-avatar-fallback" style="display:none;">${displayText.charAt(0).toUpperCase()}</span>
            <span class="channel-name">${escapeHtml(displayText)}</span>
        </div>
    `;
}

// ============ EMPLOYER IDENTITY (logos) ============
/** Deterministic avatar color from a company name — stable across sessions, readable in both themes. */
function colorFromString(str) {
    const s = String(str || '?');
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (s.charCodeAt(i) + ((h << 5) - h)) | 0;
    return `hsl(${Math.abs(h) % 360}, 48%, 52%)`;
}

// Job boards / link shorteners / mail hosts — these are NOT the employer, so don't show their logo.
const LOGO_SKIP_DOMAINS = new Set([
    't.me', 'telegram.org', 'telegram.me', 'telegram.dog',
    'ethiojobs.net', 'hahu.jobs', 'geezjobs.com', 'afriwork.com', 'freelance.et',
    'linkedin.com', 'facebook.com', 'twitter.com', 'x.com', 'instagram.com',
    'docs.google.com', 'forms.gle', 'goo.gl', 'google.com', 'bit.ly', 'tinyurl.com',
    'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'wa.me',
]);

/** Best-effort employer domain from an apply URL (skips aggregators/shorteners). */
function getEmployerDomain(job) {
    const url = job && job.apply_url;
    if (!url || !/^https?:/i.test(url)) return '';
    try {
        const host = new URL(url).hostname.replace(/^www\./, '').toLowerCase();
        for (const d of LOGO_SKIP_DOMAINS) {
            if (host === d || host.endsWith('.' + d)) return '';
        }
        return host;
    } catch (e) {
        return '';
    }
}

/**
 * Logo markup for a job. Shows the real employer logo (via Clearbit) when we can
 * resolve a company domain; otherwise a colored initials avatar. The <img> fails
 * gracefully (onerror) so the initials always remain as a fallback.
 */
function getCompanyLogoHtml(job, opts = {}) {
    const size = opts.size || 48;
    const variant = opts.variant || 'card';
    const name = (job.company || job.title || '?').trim();
    const letters = variant === 'hero' ? (name.charAt(0) || '?').toUpperCase() : getInitials(name);
    const domain = getEmployerDomain(job);
    const img = domain
        ? `<img src="https://logo.clearbit.com/${escapeAttr(domain)}" alt="" class="company-logo-img" width="${size}" height="${size}" loading="lazy" decoding="async" onerror="this.remove()">`
        : '';
    if (variant === 'hero') {
        return `<div class="modal-hero-logo" aria-hidden="true">${img}<span class="company-logo-letter">${escapeHtml(letters)}</span></div>`;
    }
    const color = colorFromString(job.company || job.title || '?');
    return `<div class="job-logo" style="background:${color};color:#fff;border-color:transparent" aria-hidden="true">${img}<span class="company-logo-letter">${escapeHtml(letters)}</span></div>`;
}

// ============ STATE ============
let currentPage = 1;
let currentFilter = 'all';
let currentSearch = '';
let currentLocation = '';
let currentSort = 'newest';
let currentMinSalary = 0;
let isLoading = false;
/** Job objects by id from the current list (for instant modal open). */
const jobsCache = {};

// ============ DOM ELEMENTS ============
const elements = {
    loader: document.getElementById('loader'),
    navbar: document.getElementById('navbar'),
    heroSearch: document.getElementById('heroSearch'),
    heroLocation: document.getElementById('heroLocation'),
    heroSearchBtn: document.getElementById('heroSearchBtn'),
    jobsGrid: document.getElementById('jobsGrid'),
    categoriesGrid: document.getElementById('categoriesGrid'),
    loadMoreBtn: document.getElementById('loadMoreBtn'),
    jobModal: document.getElementById('jobModal'),
    modalBody: document.getElementById('modalBody'),
    modalClose: document.getElementById('modalClose'),
    modalStickyApply: document.getElementById('modalStickyApply'),
    modalStickyTitle: document.getElementById('modalStickyTitle'),
    modalStickyActions: document.getElementById('modalStickyActions'),
    backToTop: document.getElementById('backToTop'),
    darkModeToggle: document.getElementById('darkModeToggle'),
    filterTabs: document.querySelectorAll('.filter-tab'),
    sortSelect: document.getElementById('sortSelect'),
    salarySelect: document.getElementById('salarySelect'),
    popularTags: document.querySelectorAll('.popular-searches .tag'),
    liveJobCount: document.getElementById('liveJobCount'),
    statTotalJobs: document.getElementById('statTotalJobs'),
    statCompanies: document.getElementById('statCompanies'),
    statToday: document.getElementById('statToday'),
    statFreshGrad: document.getElementById('statFreshGrad'),
    bigStatJobs: document.getElementById('bigStatJobs'),
    jobsFreshness: document.getElementById('jobsFreshness'),
    activeFiltersChips: document.getElementById('activeFiltersChips'),
};

// ============ SAVED JOBS (localStorage) ============
const SAVED_JOBS_KEY = 'srafelagi_saved';
function getSavedJobIds() {
    try {
        const raw = localStorage.getItem(SAVED_JOBS_KEY);
        return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch (e) { return new Set(); }
}
function setSavedJobIds(ids) {
    localStorage.setItem(SAVED_JOBS_KEY, JSON.stringify([...ids]));
}
function toggleSavedJobId(jobId) {
    const ids = getSavedJobIds();
    let saved;
    if (ids.has(jobId)) { ids.delete(jobId); saved = false; }
    else { ids.add(jobId); saved = true; }
    setSavedJobIds(ids);
    // Mirror to the server when signed in, so saves follow the user across devices.
    if (getAuthToken()) {
        fetch(`${API_BASE}/api/saved/${jobId}`, { method: saved ? 'POST' : 'DELETE', headers: authHeaders() }).catch(() => {});
    }
    return saved;
}

// ============ INTEREST PROFILE (powers "Recommended for you") ============
const INTERESTS_KEY = 'srafelagi_interests';
const INTEREST_STOPWORDS = new Set([
    'the', 'and', 'for', 'with', 'job', 'jobs', 'vacancy', 'vacancies', 'needed',
    'urgent', 'new', 'wanted', 'ethiopia', 'addis', 'ababa', 'fresh', 'graduate',
    'company', 'plc', 'position', 'role', 'hiring', 'apply', 'required',
]);

/** Significant lowercase keywords from text (keeps Latin + Amharic, drops noise). */
function extractKeywords(text) {
    return String(text || '')
        .toLowerCase()
        .replace(/[^a-z0-9ሀ-፿\s]/g, ' ')
        .split(/\s+/)
        .filter(w => w.length >= 3 && !INTEREST_STOPWORDS.has(w));
}

/** Add a weighted interest term (search query, role, etc.) to the local profile. */
function addInterest(term, weight) {
    term = String(term || '').trim().toLowerCase();
    if (term.length < 3) return;
    try {
        const obj = JSON.parse(localStorage.getItem(INTERESTS_KEY) || '{}');
        obj[term] = Math.min((obj[term] || 0) + (weight || 1), 50);
        const keys = Object.keys(obj);
        if (keys.length > 40) {
            keys.sort((a, b) => obj[a] - obj[b]);
            delete obj[keys[0]]; // evict the weakest signal
        }
        localStorage.setItem(INTERESTS_KEY, JSON.stringify(obj));
    } catch (e) { /* storage unavailable — recommendations just stay empty */ }
}

/** Record interest in a job by its role keywords (used on view/save). */
function addJobInterest(job, weight) {
    if (!job || !job.title) return;
    const kws = extractKeywords(job.title).slice(0, 2);
    if (kws.length) addInterest(kws.join(' '), weight);
}

/** Top N interest terms by weight (most-wanted first). */
function getTopInterests(n) {
    try {
        const obj = JSON.parse(localStorage.getItem(INTERESTS_KEY) || '{}');
        return Object.entries(obj).sort((a, b) => b[1] - a[1]).slice(0, n).map(e => e[0]);
    } catch (e) {
        return [];
    }
}

// ============ TELEGRAM LOGIN (no password) ============
const AUTH_TOKEN_KEY = 'srafelagi_auth_token';
let currentUser = null;

function getAuthToken() {
    try { return localStorage.getItem(AUTH_TOKEN_KEY) || ''; } catch (e) { return ''; }
}
function setAuthToken(t) {
    try { localStorage.setItem(AUTH_TOKEN_KEY, t || ''); } catch (e) {}
}
function clearAuth() {
    try { localStorage.removeItem(AUTH_TOKEN_KEY); } catch (e) {}
    currentUser = null;
}
function authHeaders() {
    const t = getAuthToken();
    return t ? { 'Authorization': 'Bearer ' + t } : {};
}
function authJsonHeaders() {
    return Object.assign({ 'Content-Type': 'application/json' }, authHeaders());
}

/** Inject Telegram's official login widget into the navbar (logged-out state). */
function renderTelegramWidget() {
    const c = document.getElementById('tgLoginContainer');
    if (!c) return;
    const botUser = window.SRAFELAGI_BOT_USERNAME;
    if (!botUser) { c.innerHTML = ''; return; }
    if (c.querySelector('script, iframe')) return; // already rendered
    c.innerHTML = '';
    const s = document.createElement('script');
    s.async = true;
    s.src = 'https://telegram.org/js/telegram-widget.js?22';
    s.setAttribute('data-telegram-login', botUser);
    s.setAttribute('data-size', 'medium');
    s.setAttribute('data-userpic', 'false');
    s.setAttribute('data-radius', '10');
    s.setAttribute('data-onauth', 'onTelegramAuth(user)');
    s.setAttribute('data-request-access', 'write'); // lets the bot message the user later (alerts)
    c.appendChild(s);
}

/** Show either the login widget or the user menu based on auth state. */
function renderAuthUI() {
    const loginC = document.getElementById('tgLoginContainer');
    const menu = document.getElementById('userMenu');
    const signedIn = !!(currentUser && getAuthToken());
    if (signedIn) {
        if (loginC) { loginC.hidden = true; loginC.innerHTML = ''; }
        if (menu) {
            menu.hidden = false;
            const name = document.getElementById('userMenuName');
            const av = document.getElementById('userMenuAvatar');
            if (name) name.textContent = currentUser.first_name || currentUser.username || 'Me';
            if (av) {
                if (currentUser.photo_url) { av.src = currentUser.photo_url; av.style.display = ''; }
                else { av.removeAttribute('src'); av.style.display = 'none'; }
            }
        }
    } else {
        if (menu) menu.hidden = true;
        if (loginC) { loginC.hidden = false; renderTelegramWidget(); }
    }
}

/** Telegram widget callback (global) — exchange the signed payload for a session. */
window.onTelegramAuth = async function (user) {
    try {
        const res = await fetch(`${API_BASE}/api/auth/telegram`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(user),
        });
        if (!res.ok) { showToast('Telegram sign-in failed. Try again.', 'error'); return; }
        const data = await res.json();
        setAuthToken(data.access_token);
        currentUser = data.user;
        await mergeAndSyncSaved();           // migrate this device's saves into the account
        renderAuthUI();
        showToast('Signed in as ' + (currentUser.first_name || 'you'), 'success');
        if (currentFilter === 'saved') loadJobs(true);
    } catch (e) {
        showToast('Sign-in error. Check your connection.', 'error');
    }
};

/** On login: push local saves to the server, then pull the merged set back into localStorage. */
async function mergeAndSyncSaved() {
    const localIds = [...getSavedJobIds()];
    try {
        let serverIds = [];
        if (localIds.length) {
            const res = await fetch(`${API_BASE}/api/saved/merge`, {
                method: 'POST', headers: authJsonHeaders(), body: JSON.stringify({ job_ids: localIds }),
            });
            if (res.ok) serverIds = (await res.json()).ids || [];
        } else {
            const res = await fetch(`${API_BASE}/api/saved`, { headers: authHeaders() });
            if (res.ok) serverIds = (await res.json()).ids || [];
        }
        setSavedJobIds(new Set([...localIds, ...serverIds]));
    } catch (e) { /* keep local saves on failure */ }
}

function initAuth() {
    setupUserMenu();
    const token = getAuthToken();
    if (!token) { renderAuthUI(); return; }
    // Restore the session, then reconcile saved jobs across devices.
    fetch(`${API_BASE}/api/me`, { headers: authHeaders() })
        .then(res => {
            if (!res.ok) { clearAuth(); renderAuthUI(); return null; }
            return res.json();
        })
        .then(user => {
            if (!user) return;
            currentUser = user;
            renderAuthUI();
            return mergeAndSyncSaved();
        })
        .catch(() => { renderAuthUI(); });
}

function setupUserMenu() {
    const btn = document.getElementById('userMenuBtn');
    const dd = document.getElementById('userMenuDropdown');
    if (btn && dd) {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const willOpen = dd.hidden;
            dd.hidden = !willOpen;
            btn.setAttribute('aria-expanded', String(willOpen));
        });
        document.addEventListener('click', () => {
            if (!dd.hidden) { dd.hidden = true; btn.setAttribute('aria-expanded', 'false'); }
        });
    }
    document.getElementById('userMenuSaved')?.addEventListener('click', () => {
        currentFilter = 'saved';
        currentPage = 1;
        elements.filterTabs.forEach(t => t.classList.toggle('active', (t.dataset.filter || '') === 'saved'));
        updateUrlFromState(false);
        loadJobs(true);
        document.getElementById('jobs')?.scrollIntoView({ behavior: 'smooth' });
    });
    document.getElementById('userMenuSignout')?.addEventListener('click', () => {
        clearAuth();
        renderAuthUI();
        showToast('Signed out', 'success');
        if (currentFilter === 'saved') loadJobs(true);
    });
}

// ============ URL PARAMS (SEO-friendly shareable links) ============
function getParamsFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const exp = params.get('expiring');
    const cat = params.get('category');
    let filter = 'all';
    if (exp === 'today') filter = 'expiring_today';
    else if (exp === 'tomorrow') filter = 'expiring_tomorrow';
    else if (exp === 'week') filter = 'expiring_week';
    else if (cat) filter = cat;
    return {
        search: params.get('search') || '',
        location: params.get('location') || '',
        filter,
        sort: params.get('sort') || 'newest',
        minSalary: parseInt(params.get('min_salary') || '0', 10) || 0,
        page: parseInt(params.get('page') || '1', 10) || 1,
    };
}

function updateUrlFromState(replace) {
    const params = new URLSearchParams();
    if (currentSearch) params.set('search', currentSearch);
    if (currentLocation) params.set('location', currentLocation);
    if (currentFilter !== 'all') {
        if (currentFilter === 'expiring_today') params.set('expiring', 'today');
        else if (currentFilter === 'expiring_tomorrow') params.set('expiring', 'tomorrow');
        else if (currentFilter === 'expiring_week') params.set('expiring', 'week');
        else if (currentFilter !== 'saved') params.set('category', currentFilter);
    }
    if (currentSort !== 'newest') params.set('sort', currentSort);
    if (currentMinSalary > 0) params.set('min_salary', String(currentMinSalary));
    if (currentPage > 1) params.set('page', String(currentPage));
    const query = params.toString();
    const url = query ? `${window.location.pathname || '/'}?${query}` : window.location.pathname || '/';
    const method = replace ? 'replaceState' : 'pushState';
    window.history[method]({}, '', url);
}

// ============ INITIALIZATION ============
document.addEventListener('DOMContentLoaded', () => {
    init();
});

async function init() {
    // Hide the intro loader as soon as the shell is ready (no artificial delay)
    requestAnimationFrame(() => elements.loader?.classList.add('hidden'));
    
    // Initialize components
    initNavbar();
    initSearch();
    initFilters();
    initSort();
    initModal();
    initBackToTop();
    initDarkMode();
    initFooter();
    initAlertsForm();
    initAlertsOnboarding();
    initAuth();

    // Show confirmation message if user just confirmed email alert
    const params = new URLSearchParams(window.location.search);
    if (params.get('confirmed') === '1') {
        showToast('Email confirmed! You\'ll receive job alerts.', 'success');
        window.history.replaceState({}, '', window.location.pathname + (window.location.hash || ''));
    }

    // Read URL and apply state (SEO: each search/filter has its own URL)
    const urlParams = getParamsFromUrl();
    currentSearch = urlParams.search;
    currentLocation = urlParams.location;
    currentFilter = urlParams.filter;
    currentSort = urlParams.sort;
    currentMinSalary = urlParams.minSalary;
    currentPage = urlParams.page;
    if (elements.heroSearch) elements.heroSearch.value = currentSearch;
    if (elements.heroLocation) elements.heroLocation.value = currentLocation;
    if (elements.sortSelect) elements.sortSelect.value = currentSort;
    if (elements.salarySelect) elements.salarySelect.value = String(currentMinSalary);
    elements.filterTabs.forEach(t => {
        t.classList.toggle('active', (t.dataset.filter || '') === currentFilter);
    });

    window.addEventListener('popstate', () => {
        const p = getParamsFromUrl();
        currentSearch = p.search;
        currentLocation = p.location;
        currentFilter = p.filter;
        currentSort = p.sort;
        currentMinSalary = p.minSalary;
        currentPage = p.page;
        if (elements.heroSearch) elements.heroSearch.value = currentSearch;
        if (elements.heroLocation) elements.heroLocation.value = currentLocation;
        if (elements.sortSelect) elements.sortSelect.value = currentSort;
        if (elements.salarySelect) elements.salarySelect.value = String(currentMinSalary);
        elements.filterTabs.forEach(t => t.classList.toggle('active', (t.dataset.filter || '') === currentFilter));
        loadJobs(true);
    });
    
    // Load data
    await Promise.all([
        loadStats(),
        loadCategories(),
    ]);
    await loadJobs(true);
    loadRecommended(); // personalized rail for returning visitors (fire and forget)

    // Open job from hash (e.g. shared link #job=123)
    const hashMatch = window.location.hash.match(/^#job=(\d+)$/);
    if (hashMatch) {
        const jobId = parseInt(hashMatch[1], 10);
        if (jobId) openJobModal(jobId);
    }
}

// ============ NAVBAR ============
function initNavbar() {
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            elements.navbar.classList.add('scrolled');
        } else {
            elements.navbar.classList.remove('scrolled');
        }
    });

    // Mobile menu toggle
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const navLinks = document.getElementById('navLinks');
    if (mobileMenuBtn && navLinks) {
        mobileMenuBtn.addEventListener('click', () => {
            const isOpen = navLinks.classList.toggle('open');
            mobileMenuBtn.classList.toggle('open', isOpen);
            mobileMenuBtn.setAttribute('aria-expanded', isOpen);
            mobileMenuBtn.setAttribute('aria-label', isOpen ? 'Close menu' : 'Open menu');
        });
        // Close menu on nav link click
        navLinks.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                navLinks.classList.remove('open');
                mobileMenuBtn.classList.remove('open');
                mobileMenuBtn.setAttribute('aria-expanded', 'false');
            });
        });
        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!mobileMenuBtn.contains(e.target) && !navLinks.contains(e.target)) {
                navLinks.classList.remove('open');
                mobileMenuBtn.classList.remove('open');
                mobileMenuBtn.setAttribute('aria-expanded', 'false');
            }
        });
    }

    // In-page anchor links: smooth scroll to section (fixes #about, #jobs, #categories, #stats)
    document.querySelectorAll('a[href^="#"]').forEach(a => {
        if (a.hasAttribute('data-category')) return; // footer category links use their own handler
        const href = a.getAttribute('href');
        if (href === '#') return;
        const id = href.slice(1);
        const target = document.getElementById(id);
        if (!target) return;
        a.addEventListener('click', (e) => {
            e.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    });
}

// ============ SEARCH ============
function initSearch() {
    // Hero search button
    elements.heroSearchBtn?.addEventListener('click', () => {
        performSearch();
        document.getElementById('jobs')?.scrollIntoView({ behavior: 'smooth' });
    });

    // Search only on Enter or button click (no search while typing)
    // Enter key in search
    elements.heroSearch?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            performSearch();
            document.getElementById('jobs')?.scrollIntoView({ behavior: 'smooth' });
        }
    });

    // Popular tags
    elements.popularTags.forEach(tag => {
        tag.addEventListener('click', () => {
            const searchTerm = tag.dataset.search;
            elements.heroSearch.value = searchTerm;
            performSearch();
            document.getElementById('jobs')?.scrollIntoView({ behavior: 'smooth' });
        });
    });
}

function performSearch() {
    currentSearch = elements.heroSearch?.value || '';
    currentLocation = elements.heroLocation?.value || '';
    currentPage = 1;
    if (currentSearch.trim()) addInterest(currentSearch.trim(), 3);
    updateUrlFromState(false);
    loadJobs(true);
}

// ============ FILTERS ============
function initFilters() {
    elements.filterTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            elements.filterTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentFilter = tab.dataset.filter || 'all';
            currentPage = 1;
            updateUrlFromState(false);
            loadJobs(true);
        });
    });
}

// ============ SORT ============
function initSort() {
    elements.sortSelect?.addEventListener('change', () => {
        currentSort = elements.sortSelect.value || 'newest';
        currentPage = 1;
        updateUrlFromState(false);
        loadJobs(true);
    });
    elements.salarySelect?.addEventListener('change', () => {
        currentMinSalary = parseInt(elements.salarySelect.value || '0', 10) || 0;
        currentPage = 1;
        updateUrlFromState(false);
        loadJobs(true);
    });
}

// ============ LOAD STATS ============
async function loadStats() {
    try {
        const res = await fetch(`${API_BASE}/api/stats`);
        const stats = await res.json();
        
        // Animate numbers
        animateNumber(elements.statTotalJobs, stats.total_jobs || 0);
        animateNumber(elements.statCompanies, Math.floor((stats.total_jobs || 0) / 3)); // Estimate
        animateNumber(elements.statToday, stats.last_24h || 0);
        animateNumber(elements.statFreshGrad, Math.floor((stats.total_jobs || 0) * 0.15)); // Estimate
        animateNumber(elements.bigStatJobs, stats.total_jobs || 0);
        
        if (elements.liveJobCount) {
            elements.liveJobCount.textContent = formatNumber(stats.total_jobs || 0);
        }
        if (elements.jobsFreshness) {
            const n = stats.last_24h || 0;
            elements.jobsFreshness.textContent = n === 1 ? '1 job added in the last 24 hours.' : `${formatNumber(n)} jobs added in the last 24 hours.`;
        }
    } catch (e) {
        console.error('Failed to load stats:', e);
    }
}

const PREFERS_REDUCED_MOTION = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

function animateNumber(element, target) {
    if (!element) return;
    target = Number(target) || 0;
    // Skip the animation entirely when the device is low on power/data or the
    // user asked for less motion — one rAF loop is far cheaper than setInterval.
    if (PREFERS_REDUCED_MOTION || target <= 0) {
        element.textContent = formatNumber(target);
        return;
    }
    const duration = 1200;
    const start = performance.now();
    function tick(now) {
        const t = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
        element.textContent = formatNumber(Math.floor(target * eased));
        if (t < 1) requestAnimationFrame(tick);
        else element.textContent = formatNumber(target);
    }
    requestAnimationFrame(tick);
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

// ============ LOAD CATEGORIES ============
async function loadCategories() {
    try {
        const res = await fetch(`${API_BASE}/api/categories`);
        const categories = await res.json();
        
        const styles = {
            'Software & IT':  { icon: 'fas fa-laptop-code',     tone: 'blue' },
            'IT & Tech':      { icon: 'fas fa-laptop-code',     tone: 'blue' },
            'Accounting':     { icon: 'fas fa-calculator',      tone: 'emerald' },
            'Finance':        { icon: 'fas fa-chart-line',      tone: 'emerald' },
            'Engineering':    { icon: 'fas fa-cogs',            tone: 'slate' },
            'Healthcare':     { icon: 'fas fa-heart-pulse',     tone: 'teal' },
            'Sales':          { icon: 'fas fa-chart-bar',       tone: 'amber' },
            'Marketing':      { icon: 'fas fa-bullhorn',        tone: 'fuchsia' },
            'Driver':         { icon: 'fas fa-car',             tone: 'orange' },
            'Education':      { icon: 'fas fa-graduation-cap',  tone: 'indigo' },
            'NGO':            { icon: 'fas fa-hands-helping',   tone: 'rose' },
            'Banking':        { icon: 'fas fa-university',      tone: 'indigo' },
            'Administration': { icon: 'fas fa-tasks',           tone: 'slate' },
            'Fresh Graduate': { icon: 'fas fa-user-graduate',   tone: 'emerald' },
            'Hospitality':    { icon: 'fas fa-utensils',        tone: 'orange' },
            'Construction':   { icon: 'fas fa-hard-hat',        tone: 'amber' },
            'Logistics':      { icon: 'fas fa-truck',           tone: 'slate' },
            'Legal':          { icon: 'fas fa-scale-balanced',  tone: 'indigo' },
            'Customer Service': { icon: 'fas fa-headset',       tone: 'fuchsia' },
        };
        const fallback = { icon: 'fas fa-briefcase', tone: 'emerald' };

        if (elements.categoriesGrid && categories.length > 0) {
            elements.categoriesGrid.innerHTML = categories.slice(0, 12).map(cat => {
                const style = styles[cat.name] || fallback;
                const count = Number(cat.count || 0);
                return `
                <button class="category-card category-card--${style.tone}" onclick="filterByCategory('${escapeHtml(cat.slug || cat.name)}')">
                    <span class="category-icon" aria-hidden="true">
                        <i class="${style.icon}"></i>
                    </span>
                    <span class="category-info">
                        <span class="category-name">${escapeHtml(cat.name)}</span>
                        <span class="category-count">
                            <strong>${count.toLocaleString()}</strong> ${count === 1 ? 'open role' : 'open roles'}
                        </span>
                    </span>
                    <span class="category-arrow" aria-hidden="true">
                        <i class="fas fa-arrow-right"></i>
                    </span>
                </button>`;
            }).join('');
        }
    } catch (e) {
        console.error('Failed to load categories:', e);
    }
}

const CATEGORY_SLUGS = new Set(['it', 'finance', 'banking', 'ngo', 'fresh_graduate', 'engineering', 'health', 'teaching', 'marketing', 'admin', 'logistics', 'hr', 'government']);

function filterByCategory(slugOrName) {
    if (CATEGORY_SLUGS.has(slugOrName)) {
        currentFilter = slugOrName;
        currentSearch = '';
        currentPage = 1;
        if (elements.heroSearch) elements.heroSearch.value = '';
        elements.filterTabs.forEach(t => t.classList.toggle('active', (t.dataset.filter || '') === currentFilter));
        updateUrlFromState(false);
        loadJobs(true);
        document.getElementById('jobs')?.scrollIntoView({ behavior: 'smooth' });
    } else {
        elements.heroSearch.value = slugOrName;
        performSearch();
    }
}

// ============ LOAD JOBS ============
async function loadJobs(reset = false) {
    if (isLoading) return;
    isLoading = true;
    setLoadMoreButtonState(true);

    if (reset) {
        elements.jobsGrid.innerHTML = getSkeletonCardsHtml(6);
    }

    try {
        // Signed-in "Saved" tab: pull the account's saved jobs from the server
        // (full objects, all of them — not limited to the latest page).
        if (currentFilter === 'saved' && getAuthToken()) {
            const sres = await fetch(`${API_BASE}/api/saved`, { headers: authHeaders() });
            const sdata = await sres.json();
            const savedJobs = sdata.jobs || [];
            setSavedJobIds(new Set(sdata.ids || savedJobs.map(j => j.id)));
            elements.jobsGrid.innerHTML = '';
            Object.keys(jobsCache).forEach(k => delete jobsCache[k]);
            if (!savedJobs.length) {
                elements.jobsGrid.innerHTML = renderEmptyState();
            } else {
                savedJobs.forEach(j => { jobsCache[j.id] = j; });
                elements.jobsGrid.innerHTML = savedJobs.map(job => renderJobCard(job)).join('');
            }
            elements.loadMoreBtn.style.display = 'none';
            setLoadMoreButtonState(false);
            renderActiveFilterChips();
            isLoading = false;
            return;
        }

        const perPage = currentFilter === 'saved' ? 60 : JOBS_PER_PAGE;
        let url = `${API_BASE}/api/jobs?page=${currentPage}&per_page=${perPage}`;
        if (currentSearch) url += `&search=${encodeURIComponent(currentSearch)}`;
        if (currentLocation) url += `&location=${encodeURIComponent(currentLocation)}`;
        if (currentFilter === 'expiring_today') url += '&expiring=today';
        else if (currentFilter === 'expiring_tomorrow') url += '&expiring=tomorrow';
        else if (currentFilter === 'expiring_week') url += '&expiring=week';
        else if (currentFilter && currentFilter !== 'all' && currentFilter !== 'saved') {
            url += `&category=${encodeURIComponent(currentFilter)}`;
        }
        if (currentSort && currentSort !== 'newest') url += `&sort=${encodeURIComponent(currentSort)}`;
        if (currentMinSalary > 0) url += `&min_salary=${currentMinSalary}`;
        const res = await fetch(url);
        const data = await res.json();
        let jobs = data.jobs || [];
        if (currentFilter === 'saved') {
            const savedIds = getSavedJobIds();
            jobs = jobs.filter(j => savedIds.has(j.id));
        }
        if (reset) {
            elements.jobsGrid.innerHTML = '';
            Object.keys(jobsCache).forEach(k => delete jobsCache[k]);
        }
        if (!jobs.length) {
            if (reset) {
                elements.jobsGrid.innerHTML = renderEmptyState();
            }
            elements.loadMoreBtn.style.display = 'none';
        } else {
            jobs.forEach(j => { jobsCache[j.id] = j; });
            const jobsHtml = jobs.map(job => renderJobCard(job)).join('');
            elements.jobsGrid.innerHTML += jobsHtml;
            const pages = currentFilter === 'saved' ? 1 : data.pages;
            elements.loadMoreBtn.style.display = currentPage >= pages ? 'none' : 'inline-flex';
            if (reset) injectJobListStructuredData(jobs);
        }
    } catch (e) {
        console.error('Failed to load jobs:', e);
        if (reset) {
            elements.jobsGrid.innerHTML = `
                <div class="empty-state" style="grid-column: 1/-1;">
                    <i class="fas fa-exclamation-circle empty-icon"></i>
                    <h3>Error loading jobs</h3>
                    <p>Please refresh the page</p>
                    <button type="button" class="btn btn-outline btn-empty-state" onclick="clearAllFiltersAndReload()"><i class="fas fa-redo"></i> Try again</button>
                </div>
            `;
        }
    }

    setLoadMoreButtonState(false);
    renderActiveFilterChips();
    isLoading = false;
}

function setLoadMoreButtonState(loading) {
    if (!elements.loadMoreBtn) return;
    elements.loadMoreBtn.disabled = loading;
    if (loading) {
        elements.loadMoreBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading…';
    } else {
        elements.loadMoreBtn.innerHTML = '<i class="fas fa-plus"></i> Load More Jobs';
    }
}

const POPULAR_KEYWORDS = ['Developer', 'Accountant', 'Engineer', 'Manager', 'Sales', 'Marketing', 'Driver', 'Teacher', 'Designer', 'Nurse'];
const POPULAR_EMPTY_CATEGORIES = [
    { slug: 'it', label: 'IT & Tech' },
    { slug: 'finance', label: 'Finance' },
    { slug: 'banking', label: 'Banking' },
    { slug: 'engineering', label: 'Engineering' },
    { slug: 'ngo', label: 'NGO' },
    { slug: 'health', label: 'Health' },
    { slug: 'teaching', label: 'Teaching' },
    { slug: 'fresh_graduate', label: 'Fresh Graduate' },
];

function renderEmptyState() {
    if (currentFilter === 'saved') {
        return '<div class="empty-state" style="grid-column: 1/-1;"><i class="far fa-bookmark empty-icon"></i><h3>No saved jobs</h3><p>Click the bookmark on any job to save it here.</p></div>';
    }
    const searchTerm = (currentSearch || '').trim();
    const headerText = searchTerm
        ? `No jobs found for "${escapeHtml(searchTerm)}"`
        : 'No jobs match your filters';
    const lowerSearch = searchTerm.toLowerCase();
    const kwChips = POPULAR_KEYWORDS
        .filter(kw => kw.toLowerCase() !== lowerSearch)
        .slice(0, 8)
        .map(kw => `<button type="button" class="suggestion-chip" onclick="filterByCategory('${escapeHtml(kw)}')">${escapeHtml(kw)}</button>`)
        .join('');
    const catChips = POPULAR_EMPTY_CATEGORIES
        .filter(c => c.slug !== currentFilter)
        .slice(0, 8)
        .map(c => `<button type="button" class="suggestion-chip suggestion-chip-cat" onclick="filterByCategory('${c.slug}')">${escapeHtml(c.label)}</button>`)
        .join('');
    return `
        <div class="empty-state" style="grid-column: 1/-1;">
            <i class="fas fa-search empty-icon"></i>
            <h3>${headerText}</h3>
            <p>Try one of these popular searches:</p>
            <div class="suggestion-chips">${kwChips}</div>
            <p class="suggestion-divider">Or browse by category:</p>
            <div class="suggestion-chips">${catChips}</div>
            <button type="button" class="btn btn-outline btn-empty-state" onclick="clearAllFiltersAndReload()"><i class="fas fa-times-circle"></i> Show all jobs</button>
        </div>
    `;
}

function clearAllFiltersAndReload() {
    currentSearch = '';
    currentLocation = '';
    currentFilter = 'all';
    currentPage = 1;
    if (elements.heroSearch) elements.heroSearch.value = '';
    if (elements.heroLocation) elements.heroLocation.value = '';
    elements.filterTabs.forEach(t => t.classList.toggle('active', (t.dataset.filter || '') === 'all'));
    if (elements.sortSelect) elements.sortSelect.value = 'newest';
    currentSort = 'newest';
    updateUrlFromState(false);
    loadJobs(true);
    document.getElementById('jobs')?.scrollIntoView({ behavior: 'smooth' });
}

const FILTER_LABELS = {
    it: 'IT & Tech',
    finance: 'Finance',
    banking: 'Banking',
    ngo: 'NGO',
    fresh_graduate: 'Fresh Graduate',
    expiring_today: 'Expiring today',
    expiring_tomorrow: 'Expiring tomorrow',
    expiring_week: 'Expiring this week',
    saved: 'Saved',
};

function renderActiveFilterChips() {
    if (!elements.activeFiltersChips) return;
    const chips = [];
    if (currentSearch.trim()) {
        chips.push({ type: 'search', label: escapeHtml(currentSearch.trim()), value: currentSearch.trim() });
    }
    if (currentLocation.trim()) {
        chips.push({ type: 'location', label: escapeHtml(currentLocation.trim()), value: currentLocation.trim() });
    }
    if (currentFilter && currentFilter !== 'all') {
        chips.push({ type: 'filter', label: FILTER_LABELS[currentFilter] || currentFilter, value: currentFilter });
    }
    if (chips.length === 0) {
        elements.activeFiltersChips.innerHTML = '';
        elements.activeFiltersChips.classList.remove('has-chips');
        return;
    }
    elements.activeFiltersChips.classList.add('has-chips');
    elements.activeFiltersChips.innerHTML = chips.map(c => `
        <span class="filter-chip" data-type="${escapeHtml(c.type)}" data-value="${escapeHtml(c.value)}">
            ${c.label}<button type="button" class="filter-chip-remove" aria-label="Remove filter"><i class="fas fa-times"></i></button>
        </span>
    `).join('');
    elements.activeFiltersChips.querySelectorAll('.filter-chip').forEach(chip => {
        chip.addEventListener('click', (e) => {
            if (e.target.closest('.filter-chip-remove')) {
                const type = chip.dataset.type;
                const value = chip.dataset.value;
                if (type === 'search') { currentSearch = ''; if (elements.heroSearch) elements.heroSearch.value = ''; }
                else if (type === 'location') { currentLocation = ''; if (elements.heroLocation) elements.heroLocation.value = ''; }
                else if (type === 'filter') {
                    currentFilter = 'all';
                    elements.filterTabs.forEach(t => t.classList.toggle('active', (t.dataset.filter || '') === 'all'));
                }
                currentPage = 1;
                updateUrlFromState(false);
                loadJobs(true);
            }
        });
    });
}

/** Remove raw markdown symbols from a single scraped field value */
function cleanField(val) {
    if (!val) return '';
    const raw = String(val).trim();
    const cleaned = raw
        .replace(/\*+/g, '')
        .replace(/^#+\s*/gm, '')
        .replace(/^:\s*/gm, '')
        .replace(/\s{2,}/g, ' ')
        .trim();
    return cleaned || raw;
}

/** Strip markdown from job description preview text only */
function stripDescMarkdown(text) {
    if (!text) return '';
    return String(text)
        .replace(/\*\*/g, '')
        .replace(/^#+\s*/gm, '')
        .replace(/^-\s+/gm, '')
        .trim();
}

function renderJobCard(job) {
    const preview = stripDescMarkdown(job.description || '').substring(0, 120);
    const deadline = cleanField(job.deadline || job.deadline_text);
    const salary = cleanField(job.salary);
    const saved = getSavedJobIds().has(job.id);
    let tags = '';
    if (job.apply_email) tags += '<span class="tag tag-email">Email</span>';
    else if (job.apply_url) tags += '<span class="tag tag-link">Apply</span>';
    else tags += '<span class="tag tag-success">View</span>';
    return `
        <div class="job-card" onclick="openJobModal(${job.id})" data-job-id="${job.id}">
            <div class="job-card-header">
                ${getCompanyLogoHtml(job, { size: 48 })}
                <div class="job-card-title">
                    <h3>${escapeHtml(job.title || 'Untitled Job')}</h3>
                    ${job.company ? `<span class="company">${escapeHtml(job.company)}</span>` : ''}
                </div>
                <button class="btn job-card-save ${saved ? 'saved' : ''}" onclick="event.stopPropagation(); toggleSaveCard(${job.id}, this)" aria-label="Save job">
                    <i class="${saved ? 'fas' : 'far'} fa-bookmark"></i>
                </button>
            </div>
            <div class="job-card-meta">
                ${job.location ? `<span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(job.location)}</span>` : ''}
                ${deadline ? `<span><i class="fas fa-clock"></i> ${escapeHtml(deadline)}</span>` : ''}
                ${salary ? `<span class="salary-badge"><i class="fas fa-coins"></i> ${escapeHtml(salary)}</span>` : ''}
            </div>
            <div class="job-card-preview">${escapeHtml(preview)}...</div>
            <div class="job-card-footer">
                <div class="job-card-tags">${tags}</div>
                <button type="button" class="btn btn-icon job-card-share" onclick="event.stopPropagation(); shareJob(${job.id})" aria-label="Share job"><i class="fas fa-share-alt"></i></button>
                ${getChannelSlug(job) ? `<div class="job-card-source">${getChannelHtml(job, { size: 24, longName: true })}</div>` : ''}
            </div>
        </div>
    `;
}

function toggleSaveCard(jobId, btn) {
    const saved = toggleSavedJobId(jobId);
    if (saved) addJobInterest(jobsCache[jobId], 2);
    if (!btn) return;
    const icon = btn.querySelector('i');
    if (icon) {
        icon.className = saved ? 'fas fa-bookmark' : 'far fa-bookmark';
        btn.classList.toggle('saved', saved);
    }
    showToast(saved ? 'Job saved' : 'Job removed from saved', 'success');
}

function getInitials(text) {
    return text.split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
}

function getSkeletonCardsHtml(n) {
    const card = () => `
        <div class="job-card-skeleton">
            <div class="skeleton skeleton-title"></div>
            <div class="skeleton skeleton-company"></div>
            <div class="skeleton skeleton-meta"></div>
            <div class="skeleton skeleton-preview"></div>
            <div class="skeleton skeleton-preview"></div>
        </div>
    `;
    return Array(n).fill(0).map(card).join('');
}

// Load more button
elements.loadMoreBtn?.addEventListener('click', () => {
    currentPage++;
    updateUrlFromState(false);
    loadJobs(false);
});

// ============ RECOMMENDED FOR YOU ============
/**
 * Build a personalized rail from the local interest profile. Queries the top
 * interest terms, interleaves the results for variety, and renders job cards.
 * Stays hidden when there isn't enough signal (e.g. a first-time visitor).
 */
async function loadRecommended() {
    const section = document.getElementById('recommended');
    const rail = document.getElementById('recoRail');
    if (!section || !rail) return;

    const terms = getTopInterests(3);
    if (!terms.length) { section.hidden = true; return; }

    try {
        const lists = await Promise.all(terms.map(t =>
            fetch(`${API_BASE}/api/jobs?per_page=8&page=1&search=${encodeURIComponent(t)}`)
                .then(r => (r.ok ? r.json() : { jobs: [] }))
                .then(d => d.jobs || [])
                .catch(() => [])
        ));

        // Round-robin interleave so one strong interest doesn't dominate the rail.
        const seen = new Set();
        const merged = [];
        const maxLen = Math.max(0, ...lists.map(l => l.length));
        for (let i = 0; i < maxLen && merged.length < 12; i++) {
            for (const list of lists) {
                const j = list[i];
                if (j && !seen.has(j.id)) { seen.add(j.id); merged.push(j); }
            }
        }

        if (merged.length < 4) { section.hidden = true; return; }
        merged.forEach(j => { jobsCache[j.id] = j; });
        rail.innerHTML = merged.slice(0, 12).map(job => renderJobCard(job)).join('');
        section.hidden = false;
    } catch (e) {
        section.hidden = true;
    }
}

// ============ MODAL ============
function initModal() {
    // Close button
    elements.modalClose?.addEventListener('click', closeModal);
    
    // Click outside to close
    document.querySelector('.modal-overlay')?.addEventListener('click', closeModal);
    
    // Escape key to close (only when modal is open)
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape' && e.key !== 'Tab') return;
        if (!elements.jobModal.classList.contains('active')) return;
        if (e.key === 'Escape') {
            closeModal();
            return;
        }
        // Focus trap: Tab cycles within modal
        if (e.key === 'Tab') {
            const focusable = elements.jobModal.querySelectorAll(
                'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            );
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey) {
                if (document.activeElement === first) {
                    e.preventDefault();
                    last?.focus();
                }
            } else {
                if (document.activeElement === last) {
                    e.preventDefault();
                    first?.focus();
                }
            }
        }
    });
}

function normalizeJob(job) {
    if (job.apply_url && typeof job.apply_url === 'string' && job.apply_url.startsWith('mailto:')) {
        job.apply_email = job.apply_url.substring(7).split('?')[0].trim();
        job.apply_url = null;
    }
    if ((job.apply_type === 'email' || job.apply_type === 'mailto') && !job.apply_email && job.apply_url && typeof job.apply_url === 'string') {
        if (job.apply_url.startsWith('mailto:')) {
            job.apply_email = job.apply_url.substring(7).split('?')[0].trim();
            job.apply_url = null;
        }
    }
    return job;
}

function renderModalContent(job, similarJobsHtml) {
    const deadline = cleanField(job.deadline || job.deadline_text || '');
    const salary = cleanField(job.salary);
    const saved = getSavedJobIds().has(job.id);
    const outUrl = `${API_BASE}/api/out?id=${job.id}`;
    const deadlineInfo = buildDeadlineBadge(deadline);

    // Primary apply action (inline in left column for visual prominence too)
    let applyBlockHtml = '';
    if (job.apply_email) {
        const safeEmail = escapeHtml(job.apply_email);
        const emailAttr = escapeAttr(job.apply_email);
        applyBlockHtml = `
            <div class="apply-section">
                <h4><i class="fas fa-paper-plane"></i> How to Apply</h4>
                <p>Send your CV to:</p>
                <div class="email-box">
                    <span class="email-display">${safeEmail}</span>
                    <button class="btn btn-copy" onclick="copyEmail('${safeEmail}', this)"><i class="fas fa-copy"></i> Copy</button>
                    <button type="button" class="btn btn-primary" data-job-id="${job.id}" data-apply-email="${emailAttr}" onclick="openApplyEmail(this)"><i class="fas fa-paper-plane"></i> Open email</button>
                </div>
            </div>
        `;
    } else if (job.apply_url) {
        applyBlockHtml = `
            <div class="apply-section">
                <h4><i class="fas fa-paper-plane"></i> How to Apply</h4>
                <a href="${escapeHtml(outUrl)}" target="_blank" class="btn btn-primary btn-lg"><i class="fas fa-external-link-alt"></i> Apply online</a>
            </div>
        `;
    }

    // Sticky bottom bar (mobile fallback)
    let stickyActionsHtml = '';
    if (job.apply_email) {
        const stickyEmail = escapeHtml(job.apply_email);
        const stickyEmailAttr = escapeAttr(job.apply_email);
        stickyActionsHtml = `
            <button class="btn btn-copy" onclick="copyEmail('${stickyEmail}', this)"><i class="fas fa-copy"></i> Copy email</button>
            <button type="button" class="btn btn-primary" data-job-id="${job.id}" data-apply-email="${stickyEmailAttr}" onclick="openApplyEmail(this)">Open email</button>
        `;
    } else if (job.apply_url) {
        stickyActionsHtml = `<a href="${escapeHtml(outUrl)}" target="_blank" class="btn btn-primary">Apply online</a>`;
    }

    // Sidebar apply card (desktop, always visible)
    let sidebarApplyHtml = '';
    if (job.apply_email) {
        const safeEmail = escapeHtml(job.apply_email);
        const emailAttr = escapeAttr(job.apply_email);
        sidebarApplyHtml = `
            <button type="button" class="btn btn-primary btn-lg apply-cta" data-job-id="${job.id}" data-apply-email="${emailAttr}" onclick="openApplyEmail(this)">
                <i class="fas fa-paper-plane"></i> Apply by email
            </button>
            <button class="btn btn-outline btn-block" onclick="copyEmail('${safeEmail}', this)">
                <i class="fas fa-copy"></i> Copy email address
            </button>
        `;
    } else if (job.apply_url) {
        sidebarApplyHtml = `
            <a href="${escapeHtml(outUrl)}" target="_blank" class="btn btn-primary btn-lg apply-cta">
                <i class="fas fa-external-link-alt"></i> Apply online
            </a>
        `;
    } else {
        sidebarApplyHtml = `<p class="apply-note">Apply via the source link in the description.</p>`;
    }

    elements.modalStickyTitle.textContent = job.title || 'Job';
    elements.modalStickyActions.innerHTML = stickyActionsHtml;
    elements.modalStickyApply.classList.remove('visible');

    const deadlineBadge = deadlineInfo
        ? `<span class="deadline-badge deadline-badge--${deadlineInfo.urgency}"><i class="fas fa-clock"></i> ${escapeHtml(deadlineInfo.label)}</span>`
        : '';

    const channelHtml = getChannelSlug(job)
        ? `<div class="modal-source-channel">${getChannelHtml(job, { size: 28, longName: true, className: 'modal-channel' })}</div>`
        : '';

    elements.modalBody.innerHTML = `
        <div class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="modalJobTitle">
            <button class="modal-close" onclick="closeModal()" aria-label="Close"><i class="fas fa-times"></i></button>

            <header class="modal-hero">
                <div class="modal-hero-bg"></div>
                <div class="modal-hero-inner">
                    ${getCompanyLogoHtml(job, { variant: 'hero', size: 76 })}
                    <div class="modal-hero-text">
                        <h2 id="modalJobTitle" class="modal-hero-title">${escapeHtml(job.title || 'Job Details')}</h2>
                        ${job.company ? `<p class="modal-hero-company">${escapeHtml(job.company)}</p>` : ''}
                        <div class="modal-hero-meta">
                            ${job.location ? `<span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(job.location)}</span>` : ''}
                            ${deadline ? `<span><i class="fas fa-calendar"></i> ${escapeHtml(deadline)}</span>` : ''}
                            ${salary ? `<span><i class="fas fa-coins"></i> ${escapeHtml(salary)}</span>` : ''}
                        </div>
                        ${deadlineBadge ? `<div class="modal-hero-badges">${deadlineBadge}</div>` : ''}
                    </div>
                </div>
            </header>

            <div class="modal-grid">
                <main class="modal-main">
                    ${applyBlockHtml}
                    <div class="description-section">
                        <div class="description-text">${formatJobDescription(job.description)}</div>
                    </div>
                    ${channelHtml ? `<div class="modal-channel-row">${channelHtml}</div>` : ''}
                    ${job.source_url ? `<div class="source-section"><a href="${escapeHtml(job.source_url)}" target="_blank" rel="noopener"><i class="fas fa-external-link-alt"></i> View original on source</a></div>` : ''}
                    <p class="modal-report">
                        <a href="mailto:info@srafelagi.et?subject=${encodeURIComponent('Report job: ' + (job.title || 'Untitled'))}&body=${encodeURIComponent('Job title: ' + (job.title || '') + '\nSource URL: ' + (job.source_url || window.location.href) + '\n\nPlease describe the issue:')}" class="link-muted">
                            <i class="fas fa-flag"></i> Report this job
                        </a>
                    </p>
                    <div id="similarJobsContainer">${similarJobsHtml || '<div class="similar-jobs-loading"><i class="fas fa-spinner fa-spin"></i> Loading more jobs…</div>'}</div>
                </main>

                <aside class="modal-side">
                    <div class="modal-side-card">
                        <div class="modal-side-apply">
                            ${sidebarApplyHtml}
                        </div>
                        <div class="modal-side-actions">
                            <button class="btn-side-action ${saved ? 'is-saved' : ''}" onclick="toggleSaveInModal(${job.id}, this)" aria-label="Save job">
                                <i class="${saved ? 'fas' : 'far'} fa-bookmark"></i>
                                <span>${saved ? 'Saved' : 'Save'}</span>
                            </button>
                            <button class="btn-side-action" onclick="shareJob(${job.id})" aria-label="Share job">
                                <i class="fas fa-share-alt"></i>
                                <span>Share</span>
                            </button>
                            <a class="btn-side-action" href="${escapeHtml(getJobShareUrl(job.id))}" target="_blank" rel="noopener" aria-label="Open job page">
                                <i class="fas fa-up-right-from-square"></i>
                                <span>Open</span>
                            </a>
                        </div>
                        ${deadlineInfo ? `
                            <div class="modal-side-deadline deadline-badge--${deadlineInfo.urgency}">
                                <i class="fas fa-clock"></i>
                                <div>
                                    <div class="modal-side-deadline-label">${escapeHtml(deadlineInfo.label)}</div>
                                    ${deadline ? `<div class="modal-side-deadline-date">${escapeHtml(deadline)}</div>` : ''}
                                </div>
                            </div>` : ''}
                        <div class="modal-side-trust" id="modalSideTrust"></div>
                        ${job.company ? `
                            <div class="modal-side-meta">
                                <div class="modal-side-meta-row">
                                    <span class="modal-side-meta-label">Company</span>
                                    <span class="modal-side-meta-value">${escapeHtml(job.company)}</span>
                                </div>
                                ${job.location ? `
                                <div class="modal-side-meta-row">
                                    <span class="modal-side-meta-label">Location</span>
                                    <span class="modal-side-meta-value">${escapeHtml(job.location)}</span>
                                </div>` : ''}
                            </div>` : ''}
                    </div>
                </aside>
            </div>
        </div>
    `;

    // Fire and forget — populate trust signals once the modal is on screen
    loadTrustSignals(job.id, job);

    elements.jobModal.classList.add('active');
    elements.jobModal.setAttribute('aria-modal', 'true');
    document.body.style.overflow = 'hidden';
    const modalContent = document.querySelector('.modal-content');
    if (modalContent) modalContent.scrollTop = 0;

    // Accessibility: save focus and move focus into modal
    const previousFocus = document.activeElement;
    window._modalPreviousFocus = previousFocus;
    const firstFocusable = elements.jobModal.querySelector('button.modal-close, [href], button:not([disabled]), input, select, textarea');
    if (firstFocusable) firstFocusable.focus();

    modalContent.removeEventListener('scroll', _modalScrollHandler);
    modalContent.addEventListener('scroll', _modalScrollHandler);
    function _modalScrollHandler() {
        elements.modalStickyApply.classList.toggle('visible', modalContent.scrollTop > 220);
    }
}

function recordJobView(jobId) {
    const url = `${API_BASE}/api/view?id=${jobId}`;
    if (navigator.sendBeacon) {
        navigator.sendBeacon(url);
    } else {
        fetch(url).catch(function () {});
    }
}

async function openJobModal(jobId) {
    try {
        const cached = jobsCache[jobId];
        let job;
        if (cached) {
            job = normalizeJob({ ...cached });
            renderModalContent(job, '');
            injectSimilarJobsInBackground(jobId);
        } else {
            const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
            job = normalizeJob(await res.json());
            renderModalContent(job, '');
            injectSimilarJobsInBackground(jobId);
        }
        recordJobView(jobId);
        addJobInterest(job, 1);
        document.dispatchEvent(new Event('srafelagi:jobview'));
    } catch (e) {
        console.error('Failed to load job:', e);
        showToast('Error loading job details', 'error');
    }
}

function injectSimilarJobsInBackground(jobId) {
    getSimilarJobsHtml(jobId).then(html => {
        const el = document.getElementById('similarJobsContainer');
        if (el) el.innerHTML = html || '';
    });
}

async function getSimilarJobsHtml(excludeId, searchHint) {
    try {
        const res = await fetch(`${API_BASE}/api/jobs?per_page=8&page=1`);
        const data = await res.json();
        const jobs = (data.jobs || []).filter(j => j.id !== excludeId).slice(0, 6);
        if (jobs.length === 0) return '';
        return `
            <section class="similar-jobs">
                <header class="similar-jobs-header">
                    <h4><i class="fas fa-fire"></i> More jobs like this</h4>
                    <a href="#jobs" class="similar-jobs-see-all" onclick="closeModal()">Browse all →</a>
                </header>
                <div class="similar-jobs-rail">
                    ${jobs.map(j => {
                        const letter = (j.company || j.title || '?').trim().charAt(0).toUpperCase();
                        const dl = buildDeadlineBadge(j.deadline || j.deadline_text || '');
                        return `
                        <button type="button" class="similar-job-card" onclick="closeModal(); openJobModal(${j.id});">
                            <span class="similar-job-logo" aria-hidden="true">${escapeHtml(letter)}</span>
                            <span class="similar-job-body">
                                <span class="similar-job-title">${escapeHtml(j.title || 'Job')}</span>
                                ${j.company ? `<span class="similar-job-company">${escapeHtml(j.company)}</span>` : ''}
                                <span class="similar-job-meta">
                                    ${j.location ? `<span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(j.location)}</span>` : ''}
                                    ${dl ? `<span class="similar-job-deadline deadline-badge--${dl.urgency}"><i class="fas fa-clock"></i> ${escapeHtml(dl.label)}</span>` : ''}
                                </span>
                            </span>
                        </button>`;
                    }).join('')}
                </div>
            </section>
        `;
    } catch (e) { return ''; }
}

function toggleSaveInModal(jobId, btn) {
    const saved = toggleSavedJobId(jobId);
    if (saved) addJobInterest(jobsCache[jobId], 2);
    const icon = btn?.querySelector('i');
    if (icon) {
        icon.className = saved ? 'fas fa-bookmark' : 'far fa-bookmark';
        btn.classList.toggle('saved', saved);
    }
    showToast(saved ? 'Saved' : 'Removed from saved', 'success');
}

function closeModal() {
    elements.jobModal.classList.remove('active');
    elements.jobModal.removeAttribute('aria-modal');
    elements.modalStickyApply?.classList.remove('visible');
    document.body.style.overflow = 'auto';
    if (window._modalPreviousFocus && typeof window._modalPreviousFocus.focus === 'function') {
        window._modalPreviousFocus.focus();
        window._modalPreviousFocus = null;
    }
}

// ============ COPY EMAIL ============
function copyEmail(email, button) {
    navigator.clipboard.writeText(email).then(() => {
        showToast(`✅ Email copied: ${email}`, 'success');
        
        if (button) {
            const originalHtml = button.innerHTML;
            button.innerHTML = '<i class="fas fa-check"></i> Copied!';
            button.style.background = '#2e7d32';
            setTimeout(() => {
                button.innerHTML = originalHtml;
                button.style.background = '';
            }, 2000);
        }
    }).catch(() => {
        // Fallback
        const textArea = document.createElement('textarea');
        textArea.value = email;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showToast('✅ Email copied!', 'success');
    });
}

// ============ BACK TO TOP ============
function initBackToTop() {
    window.addEventListener('scroll', () => {
        if (window.scrollY > 500) {
            elements.backToTop.classList.add('visible');
        } else {
            elements.backToTop.classList.remove('visible');
        }
    });
    
    elements.backToTop?.addEventListener('click', () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
}

// ============ DARK MODE ============
function initDarkMode() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
        updateDarkModeIcon(true);
    }
    
    elements.darkModeToggle?.addEventListener('click', () => {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        
        if (isDark) {
            document.documentElement.removeAttribute('data-theme');
            localStorage.setItem('theme', 'light');
            updateDarkModeIcon(false);
        } else {
            document.documentElement.setAttribute('data-theme', 'dark');
            localStorage.setItem('theme', 'dark');
            updateDarkModeIcon(true);
        }
    });
}

function updateDarkModeIcon(isDark) {
    const icon = elements.darkModeToggle?.querySelector('i');
    if (icon) {
        icon.className = isDark ? 'fas fa-sun' : 'fas fa-moon';
    }
}

// ============ JOB ALERTS FORM ============
function initAlertsForm() {
    const form = document.getElementById('alertsSubscribeForm');
    const messageEl = document.getElementById('alertsFormMessage');
    if (!form || !messageEl) return;
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('alertsEmail')?.value?.trim();
        const keywords = document.getElementById('alertsKeywords')?.value?.trim() || '';
        const frequency = document.getElementById('alertsFrequency')?.value || 'daily';
        if (!email) {
            messageEl.textContent = 'Please enter your email.';
            messageEl.className = 'alerts-form-message error';
            return;
        }
        messageEl.textContent = 'Subscribing…';
        messageEl.className = 'alerts-form-message';
        try {
            const res = await fetch(API_BASE + '/api/alerts/subscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, keywords: keywords || null, frequency }),
            });
            const data = await res.json().catch(() => ({}));
            if (res.ok) {
                messageEl.textContent = data.message || 'Check your email to confirm.';
                messageEl.className = 'alerts-form-message success';
                form.reset();
            } else {
                messageEl.textContent = data.detail || 'Something went wrong.';
                messageEl.className = 'alerts-form-message error';
            }
        } catch (err) {
            messageEl.textContent = 'Network error. Try again.';
            messageEl.className = 'alerts-form-message error';
        }
    });
}

// ============ JOB ALERTS ONBOARDING POPUP ============
function initAlertsOnboarding() {
    const STORAGE_KEY = 'srafelagi_alerts_onboard_dismissed';
    const COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
    const DELAY_MS = 90_000;          // show after 90s idle
    const VIEW_THRESHOLD = 4;         // or after 4 job views

    // Respect cooldown — skip if dismissed within the last 7 days
    try {
        const ts = localStorage.getItem(STORAGE_KEY);
        if (ts && Date.now() - parseInt(ts, 10) < COOLDOWN_MS) return;
    } catch (_) {}

    const overlay = document.getElementById('alertsPopupOverlay');
    if (!overlay) return;

    let shown = false;

    function showPopup() {
        if (shown) return;
        shown = true;
        overlay.hidden = false;
        // rAF so the hidden→visible transition fires after display:flex kicks in
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                overlay.classList.add('alerts-popup-visible');
            });
        });
        document.body.classList.add('popup-open');
        document.getElementById('alertsPopupEmail')?.focus();
    }

    function dismissPopup() {
        overlay.classList.remove('alerts-popup-visible');
        document.body.classList.remove('popup-open');
        setTimeout(() => { overlay.hidden = true; }, 320);
        try { localStorage.setItem(STORAGE_KEY, String(Date.now())); } catch (_) {}
    }

    // Close handlers
    document.getElementById('alertsPopupClose')?.addEventListener('click', dismissPopup);
    document.getElementById('alertsPopupSkip')?.addEventListener('click', dismissPopup);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) dismissPopup(); });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !overlay.hidden) dismissPopup();
    });

    // Trigger 1: 90-second timer
    const timer = setTimeout(showPopup, DELAY_MS);

    // Trigger 2: after VIEW_THRESHOLD job views
    let viewCount = 0;
    document.addEventListener('srafelagi:jobview', () => {
        viewCount++;
        if (viewCount >= VIEW_THRESHOLD && !shown) {
            clearTimeout(timer);
            setTimeout(showPopup, 2000); // small delay so modal can close first
        }
    });

    // Form submission
    const form = document.getElementById('alertsPopupForm');
    const msgEl = document.getElementById('alertsPopupMessage');
    if (!form || !msgEl) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('alertsPopupEmail')?.value?.trim();
        const keywords = document.getElementById('alertsPopupKeywords')?.value?.trim() || '';
        const frequency = document.getElementById('alertsPopupFrequency')?.value || 'daily';
        if (!email) {
            msgEl.textContent = 'Please enter your email.';
            msgEl.className = 'alerts-form-message error';
            return;
        }
        msgEl.textContent = 'Subscribing…';
        msgEl.className = 'alerts-form-message';
        try {
            const res = await fetch(API_BASE + '/api/alerts/subscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, keywords: keywords || null, frequency }),
            });
            const data = await res.json().catch(() => ({}));
            if (res.ok) {
                msgEl.textContent = data.message || 'Check your inbox to confirm!';
                msgEl.className = 'alerts-form-message success';
                form.reset();
                setTimeout(dismissPopup, 2500);
            } else {
                msgEl.textContent = data.detail || 'Something went wrong. Try again.';
                msgEl.className = 'alerts-form-message error';
            }
        } catch (err) {
            msgEl.textContent = 'Network error. Try again.';
            msgEl.className = 'alerts-form-message error';
        }
    });
}

// ============ FOOTER ============
function initFooter() {
    const yearEl = document.getElementById('footerYear');
    if (yearEl) yearEl.textContent = new Date().getFullYear();

    document.querySelectorAll('.footer a[data-category]').forEach(a => {
        a.addEventListener('click', (e) => {
            e.preventDefault();
            const slug = a.getAttribute('data-category');
            if (slug && CATEGORY_SLUGS.has(slug)) {
                filterByCategory(slug);
                document.getElementById('jobs')?.scrollIntoView({ behavior: 'smooth' });
            }
        });
    });
}

// ============ STRUCTURED DATA (SEO) ============
function injectJobListStructuredData(jobs) {
    const baseUrl = document.querySelector('link[rel="canonical"]')?.href || window.location.origin + '/';
    const jobPostings = (jobs || []).slice(0, 20).map(job => {
        const item = {
            '@type': 'JobPosting',
            title: job.title || 'Job',
            description: (job.description || '').substring(0, 500),
            datePosted: job.created_at ? job.created_at.split('T')[0] : new Date().toISOString().split('T')[0],
            hiringOrganization: { '@type': 'Organization', name: job.company || 'Employer' },
            jobLocation: { '@type': 'Place', address: { '@type': 'PostalAddress', addressLocality: job.location || 'Ethiopia' } },
        };
        if (job.deadline && job.deadline.trim()) item.validThrough = job.deadline.trim();
        return item;
    });
    const itemList = {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        numberOfItems: jobPostings.length,
        itemListElement: jobPostings.map((job, i) => ({ '@type': 'ListItem', position: i + 1, item: job })),
    };
    let existing = document.getElementById('job-list-ld');
    if (existing) existing.remove();
    const script = document.createElement('script');
    script.id = 'job-list-ld';
    script.type = 'application/ld+json';
    script.textContent = JSON.stringify(itemList);
    document.head.appendChild(script);
}

// ============ TOAST ============
function showToast(message, type = '') {
    // Create toast if doesn't exist
    let toast = document.getElementById('toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        toast.className = 'toast';
        document.body.appendChild(toast);
    }
    
    toast.textContent = message;
    toast.className = 'toast show ' + type;
    
    setTimeout(() => {
        toast.className = 'toast';
    }, 3000);
}

// ============ UTILITIES ============
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

const ALLOWED_DESC_TAGS = new Set(['A', 'BR', 'P', 'UL', 'OL', 'LI', 'STRONG', 'B', 'EM', 'I']);
const ALLOWED_ATTRS = { A: new Set(['href', 'target', 'rel']) };

function sanitizeDescriptionHtml(html) {
    if (!html) return '';
    const div = document.createElement('div');
    div.innerHTML = String(html);
    function sanitizeNode(parent) {
        const nodes = Array.from(parent.childNodes);
        for (const n of nodes) {
            if (n.nodeType === Node.TEXT_NODE) continue;
            if (n.nodeType === Node.ELEMENT_NODE) {
                const tag = n.tagName.toUpperCase();
                if (!ALLOWED_DESC_TAGS.has(tag)) {
                    parent.removeChild(n);
                    continue;
                }
                const attrs = ALLOWED_ATTRS[tag];
                if (attrs) {
                    for (const a of Array.from(n.attributes)) {
                        if (!attrs.has(a.name.toLowerCase())) n.removeAttribute(a.name);
                    }
                }
                sanitizeNode(n);
            }
        }
    }
    sanitizeNode(div);
    return div.innerHTML;
}

/** Protect <a> tags with placeholders so we can split on \n\n without breaking them. */
function protectLinks(html) {
    const links = [];
    const placeholder = '___LINK_PLACEHOLDER_';
    const out = html.replace(/<a\s[^>]*>[\s\S]*?<\/a>/gi, (m) => {
        links.push(m);
        return placeholder + (links.length - 1) + '___';
    });
    return { text: out, links };
}

function restoreLinks(text, links) {
    let out = text;
    for (let i = 0; i < links.length; i++) {
        out = out.replace('___LINK_PLACEHOLDER_' + i + '___', links[i]);
    }
    return out;
}

/** Turn plain text with newlines into <p> and optional <ul>/<li>. */
function normalizeDescriptionStructure(html) {
    if (!html || !html.trim()) return html;
    const trimmed = html.trim();
    if (/<p[\s>]|<ul[\s>]|<ol[\s>]/i.test(trimmed)) return html;
    const { text, links } = protectLinks(trimmed);
    const paragraphs = text.split(/\n\n+/);
    const result = paragraphs.map(block => {
        const lines = block.split('\n').map(l => l.trim()).filter(Boolean);
        const bulletLike = /^[\-\*•·]\s|^\d+[.)]\s/;
        const allBullets = lines.length >= 1 && lines.every(l => bulletLike.test(l));
        if (allBullets && lines.length >= 1) {
            const items = lines.map(l => restoreLinks(escapeHtml(l.replace(bulletLike, '')), links));
            return '<ul><li>' + items.join('</li><li>') + '</li></ul>';
        }
        const inner = restoreLinks(escapeHtml(block).replace(/\n/g, '<br>'), links);
        return '<p>' + inner + '</p>';
    }).join('');
    return restoreLinks(result, links);
}

function formatJobDescription(description) {
    if (!description) return escapeHtml('No description available.');
    const safe = sanitizeDescriptionHtml(description);
    const structured = normalizeDescriptionStructure(safe);
    return decorateSections(structured);
}

/** Section heading detector — matches AI output (English + Amharic) */
const SECTION_DEFS = [
    { key: 'about',   icon: 'fa-circle-info',         labels: ['about the role', 'about the position', 'about the job', 'role overview', 'overview', 'job summary', 'ስለ ስራው', 'ስለ ሥራው'] },
    { key: 'resp',    icon: 'fa-list-check',          labels: ['responsibilities', 'duties', 'key responsibilities', 'what you\'ll do', 'what you will do', 'role responsibilities', 'ኃላፊነቶች', 'ሃላፊነቶች', 'ተግባራት'] },
    { key: 'req',     icon: 'fa-user-check',          labels: ['requirements', 'qualifications', 'minimum qualifications', 'required skills', 'who you are', 'ብቃቶች', 'መስፈርቶች', 'ችሎታዎች'] },
    { key: 'benefits',icon: 'fa-gift',                labels: ['benefits', 'what we offer', 'perks', 'compensation', 'ጥቅማ ጥቅሞች', 'ጥቅማጥቅሞች'] },
    { key: 'apply',   icon: 'fa-paper-plane',         labels: ['how to apply', 'apply', 'application', 'application process', 'to apply', 'የመጠየቂያ ሂደት', 'እንዴት ማመልከት', 'ለማመልከት'] },
];

function matchSection(text) {
    const norm = String(text || '').toLowerCase().replace(/[:：.!?]+\s*$/, '').trim();
    if (!norm || norm.length > 60) return null;
    for (const def of SECTION_DEFS) {
        for (const label of def.labels) {
            if (norm === label || norm === label + ':') return def;
        }
    }
    return null;
}

/** Wrap detected sections in styled blocks with icons. Idempotent — bails if no sections found. */
function decorateSections(html) {
    if (!html) return html;
    if (html.indexOf('description-block') !== -1) return html; // already decorated

    const container = document.createElement('div');
    container.innerHTML = html;

    const children = Array.from(container.childNodes);
    const groups = []; // [{ section, nodes }]
    let current = { section: null, nodes: [] };

    for (const node of children) {
        if (node.nodeType !== 1) {
            current.nodes.push(node);
            continue;
        }
        // A paragraph that's only a heading-like text → split point
        if (node.tagName === 'P') {
            const textOnly = node.textContent.trim();
            const def = matchSection(textOnly);
            if (def && node.innerHTML.replace(/<[^>]+>/g, '').trim() === textOnly) {
                if (current.nodes.length || current.section) groups.push(current);
                current = { section: def, nodes: [] };
                continue;
            }
        }
        current.nodes.push(node);
    }
    if (current.nodes.length || current.section) groups.push(current);

    // Only restructure if we actually found at least one section heading
    const hasSections = groups.some(g => g.section);
    if (!hasSections) return html;

    const out = document.createElement('div');
    for (const g of groups) {
        if (!g.section) {
            // Lead-in content with no heading
            for (const n of g.nodes) out.appendChild(n);
            continue;
        }
        const block = document.createElement('div');
        block.className = `description-block description-block--${g.section.key}`;
        const h = document.createElement('h5');
        h.className = 'description-block-title';
        h.innerHTML = `<i class="fas ${g.section.icon}" aria-hidden="true"></i><span></span>`;
        h.querySelector('span').textContent = g.nodes.length === 0 ? '' : '';
        // Restore the heading text from the section definition's canonical label (first one)
        const label = g.section.labels[0].replace(/^\w/, c => c.toUpperCase());
        h.querySelector('span').textContent = label;
        block.appendChild(h);
        const body = document.createElement('div');
        body.className = 'description-block-body';
        for (const n of g.nodes) body.appendChild(n);
        block.appendChild(body);
        out.appendChild(block);
    }
    return out.innerHTML;
}

/** "5 minutes ago", "3 hours ago", "Yesterday", "Jan 4". */
function relativeTime(dateInput) {
    if (!dateInput) return '';
    const d = (dateInput instanceof Date) ? dateInput : new Date(dateInput);
    if (isNaN(d.getTime())) return '';
    const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
    if (seconds < 60) return 'Just now';
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins} min ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
    const days = Math.floor(hours / 24);
    if (days === 1) return 'Yesterday';
    if (days < 7) return `${days} days ago`;
    const weeks = Math.floor(days / 7);
    if (weeks < 4) return `${weeks} week${weeks === 1 ? '' : 's'} ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/** Fetch + render trust signals (views, applies, freshness) in the modal sidebar. */
async function loadTrustSignals(jobId, job) {
    const target = document.getElementById('modalSideTrust');
    if (!target) return;
    try {
        const res = await fetch(`${API_BASE}/api/jobs/${jobId}/stats`);
        if (!res.ok) return;
        const stats = await res.json();
        const items = [];

        const postedAt = stats.created_at || job?.created_at || job?.telegram_date;
        if (postedAt) {
            items.push({ icon: 'fa-clock', label: 'Posted', value: relativeTime(postedAt) });
        }
        const v24 = +stats.views_24h || 0;
        const vTotal = +stats.views_total || 0;
        if (v24 >= 1) {
            items.push({ icon: 'fa-eye', label: 'Viewed today', value: v24.toLocaleString() });
        } else if (vTotal >= 5) {
            items.push({ icon: 'fa-eye', label: 'Total views', value: vTotal.toLocaleString() });
        }
        const a24 = +stats.apply_clicks_24h || 0;
        const aTotal = +stats.apply_clicks_total || 0;
        if (a24 >= 1) {
            items.push({ icon: 'fa-paper-plane', label: 'Applied today', value: a24.toLocaleString(), hot: a24 >= 5 });
        } else if (aTotal >= 3) {
            items.push({ icon: 'fa-paper-plane', label: 'Total applies', value: aTotal.toLocaleString() });
        }

        if (!items.length) return;
        target.innerHTML = `
            <div class="trust-signals">
                ${items.map(it => `
                    <div class="trust-signal${it.hot ? ' trust-signal--hot' : ''}">
                        <i class="fas ${it.icon}"></i>
                        <div>
                            <div class="trust-signal-value">${escapeHtml(it.value)}</div>
                            <div class="trust-signal-label">${escapeHtml(it.label)}</div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (e) { /* silently fail — trust signals are non-critical */ }
}

/** Parse a deadline string and return { label, urgency } for the badge. */
function buildDeadlineBadge(deadlineStr) {
    if (!deadlineStr) return null;
    const raw = String(deadlineStr).trim();
    // Try to extract a date — accept yyyy-mm-dd, mm/dd/yyyy, "Jan 15, 2026", etc.
    let d = null;
    const iso = raw.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (iso) d = new Date(+iso[1], +iso[2] - 1, +iso[3]);
    if (!d || isNaN(d.getTime())) {
        const parsed = Date.parse(raw);
        if (!isNaN(parsed)) d = new Date(parsed);
    }
    if (!d || isNaN(d.getTime())) return { label: raw, urgency: 'none' };

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    d.setHours(0, 0, 0, 0);
    const days = Math.round((d - today) / 86400000);

    if (days < 0)  return { label: 'Closed', urgency: 'closed', date: d };
    if (days === 0) return { label: 'Closes today', urgency: 'urgent', date: d };
    if (days === 1) return { label: '1 day left', urgency: 'urgent', date: d };
    if (days <= 3) return { label: `${days} days left`, urgency: 'soon', date: d };
    if (days <= 7) return { label: `${days} days left`, urgency: 'week', date: d };
    return { label: `${days} days left`, urgency: 'far', date: d };
}

window.openJobModal = openJobModal;
window.closeModal = closeModal;
window.copyEmail = copyEmail;
window.filterByCategory = filterByCategory;
window.toggleSaveCard = toggleSaveCard;
window.clearAllFiltersAndReload = clearAllFiltersAndReload;

function getJobShareUrl(jobId) {
    const base = window.location.origin + (window.location.pathname || '/').replace(/\/$/, '') || '';
    return base + '/job/' + jobId;
}

function shareJob(jobId) {
    const job = jobsCache[jobId];
    const title = job ? (job.title || 'Job') : 'Job';
    const company = job && job.company ? ` at ${job.company}` : '';
    openShareSheet({ url: getJobShareUrl(jobId), title, text: `${title}${company}` });
}

/** Share menu with Telegram first (our audience's default channel), then WhatsApp, copy, and native share. */
function openShareSheet({ url, title, text }) {
    closeShareSheet();
    const tg = `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`;
    const wa = `https://wa.me/?text=${encodeURIComponent(text + ' ' + url)}`;
    const nativeBtn = navigator.share
        ? `<button type="button" class="share-sheet-btn" data-action="native"><i class="fas fa-ellipsis"></i><span>More apps</span></button>`
        : '';

    const overlay = document.createElement('div');
    overlay.className = 'share-sheet-overlay';
    overlay.id = 'shareSheetOverlay';
    overlay.innerHTML = `
        <div class="share-sheet" role="dialog" aria-modal="true" aria-label="Share this job">
            <div class="share-sheet-head">
                <span class="share-sheet-title">Share this job</span>
                <button type="button" class="share-sheet-close" data-action="close" aria-label="Close"><i class="fas fa-times"></i></button>
            </div>
            <a class="share-sheet-btn share-sheet-btn--telegram" href="${escapeHtml(tg)}" target="_blank" rel="noopener" data-action="link"><i class="fab fa-telegram"></i><span>Share on Telegram</span></a>
            <a class="share-sheet-btn share-sheet-btn--whatsapp" href="${escapeHtml(wa)}" target="_blank" rel="noopener" data-action="link"><i class="fab fa-whatsapp"></i><span>Share on WhatsApp</span></a>
            <button type="button" class="share-sheet-btn" data-action="copy"><i class="fas fa-link"></i><span>Copy link</span></button>
            ${nativeBtn}
        </div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('visible'));

    overlay.addEventListener('click', async (e) => {
        if (e.target === overlay) { closeShareSheet(); return; }
        const actEl = e.target.closest('[data-action]');
        if (!actEl) return;
        const action = actEl.dataset.action;
        if (action === 'close') {
            closeShareSheet();
        } else if (action === 'link') {
            e.preventDefault();
            window.open(actEl.href, '_blank', 'noopener'); // reliable within the click gesture
            closeShareSheet();
        } else if (action === 'copy') {
            e.preventDefault();
            try { await navigator.clipboard.writeText(url); showToast('Link copied!', 'success'); }
            catch (_) { showToast('Copy failed', 'error'); }
            closeShareSheet();
        } else if (action === 'native') {
            e.preventDefault();
            closeShareSheet();
            try { await navigator.share({ title, text, url }); } catch (_) { /* user cancelled */ }
        }
    });
    document.addEventListener('keydown', shareSheetEsc);
}

function shareSheetEsc(e) { if (e.key === 'Escape') closeShareSheet(); }

function closeShareSheet() {
    document.getElementById('shareSheetOverlay')?.remove();
    document.removeEventListener('keydown', shareSheetEsc);
}

function recordApplyEmailClick(jobId) {
    const u = `${API_BASE}/api/out?id=${jobId}&type=email`;
    if (navigator.sendBeacon) {
        navigator.sendBeacon(u);
    } else {
        fetch(u).catch(() => {});
    }
}

/** Escape for HTML attribute value so getAttribute returns the original string. */
function escapeAttr(str) {
    if (str == null) return '';
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

/** Open mail client for apply-by-email. Reads job id and email from button data attributes. */
function openApplyEmail(btn) {
    const jobId = btn && btn.getAttribute('data-job-id');
    const email = btn && btn.getAttribute('data-apply-email');
    if (jobId) {
        try { recordApplyEmailClick(parseInt(jobId, 10)); } catch (e) {}
    }
    if (email) {
        var a = document.createElement('a');
        a.href = 'mailto:' + email;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }
}

window.shareJob = shareJob;
window.recordApplyEmailClick = recordApplyEmailClick;
window.openApplyEmail = openApplyEmail;
