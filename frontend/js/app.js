// ============================================
// SRAFELAGI - MAIN APPLICATION SCRIPT
// ============================================

// ============ CONFIGURATION ============
const API_BASE = (window.location.port === '8080' || window.location.port === '') ? '' : 'http://localhost:8080';
const JOBS_PER_PAGE = 12;

// Channel username (no @) -> long display name for job cards and modal
const CHANNEL_DISPLAY_NAMES = {
    dailyjobethiopia: 'Daily Job Ethiopia',
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

function getChannelPhotoPath(job) {
    const slug = getChannelSlug(job);
    if (!slug) return '';
    return `/images/channels/${slug}.jpg`;
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
            <img src="${escapeHtml(photoPath)}" alt="" class="channel-avatar" width="${size}" height="${size}" loading="lazy"
                 onerror="this.style.display='none';this.nextElementSibling.style.display='inline-flex';">
            <span class="channel-avatar-fallback" style="display:none;">${displayText.charAt(0).toUpperCase()}</span>
            <span class="channel-name">${escapeHtml(displayText)}</span>
        </div>
    `;
}

// ============ STATE ============
let currentPage = 1;
let currentFilter = 'all';
let currentSearch = '';
let currentLocation = '';
let currentSort = 'newest';
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
    if (ids.has(jobId)) ids.delete(jobId);
    else ids.add(jobId);
    setSavedJobIds(ids);
    return ids.has(jobId);
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
    // Hide loader after content loads
    setTimeout(() => {
        elements.loader.classList.add('hidden');
    }, 1000);
    
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
    currentPage = urlParams.page;
    if (elements.heroSearch) elements.heroSearch.value = currentSearch;
    if (elements.heroLocation) elements.heroLocation.value = currentLocation;
    if (elements.sortSelect) elements.sortSelect.value = currentSort;
    elements.filterTabs.forEach(t => {
        t.classList.toggle('active', (t.dataset.filter || '') === currentFilter);
    });
    
    window.addEventListener('popstate', () => {
        const p = getParamsFromUrl();
        currentSearch = p.search;
        currentLocation = p.location;
        currentFilter = p.filter;
        currentSort = p.sort;
        currentPage = p.page;
        if (elements.heroSearch) elements.heroSearch.value = currentSearch;
        if (elements.heroLocation) elements.heroLocation.value = currentLocation;
        if (elements.sortSelect) elements.sortSelect.value = currentSort;
        elements.filterTabs.forEach(t => t.classList.toggle('active', (t.dataset.filter || '') === currentFilter));
        loadJobs(true);
    });
    
    // Load data
    await Promise.all([
        loadStats(),
        loadCategories(),
    ]);
    await loadJobs(true);

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

function animateNumber(element, target) {
    if (!element) return;
    
    const duration = 2000;
    const start = 0;
    const increment = target / (duration / 16);
    let current = start;
    
    const timer = setInterval(() => {
        current += increment;
        if (current >= target) {
            element.textContent = formatNumber(target);
            clearInterval(timer);
        } else {
            element.textContent = formatNumber(Math.floor(current));
        }
    }, 16);
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
        
        const icons = {
            'Software & IT': 'fas fa-laptop-code',
            'Accounting': 'fas fa-calculator',
            'Finance': 'fas fa-chart-line',
            'Engineering': 'fas fa-cogs',
            'Healthcare': 'fas fa-heartbeat',
            'Sales': 'fas fa-chart-bar',
            'Marketing': 'fas fa-bullhorn',
            'Driver': 'fas fa-car',
            'Education': 'fas fa-graduation-cap',
            'NGO': 'fas fa-hands-helping',
            'Banking': 'fas fa-university',
            'Administration': 'fas fa-tasks',
        };
        
        if (elements.categoriesGrid && categories.length > 0) {
            elements.categoriesGrid.innerHTML = categories.slice(0, 8).map(cat => `
                <div class="category-card" onclick="filterByCategory('${escapeHtml(cat.slug || cat.name)}')">
                    <div class="category-icon">
                        <i class="${icons[cat.name] || 'fas fa-briefcase'}"></i>
                    </div>
                    <div class="category-info">
                        <h3>${escapeHtml(cat.name)}</h3>
                        <span class="category-count">${cat.count} jobs</span>
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Failed to load categories:', e);
    }
}

const CATEGORY_SLUGS = new Set(['it', 'finance', 'banking', 'ngo', 'fresh_graduate']);

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
                const emptyMsg = currentFilter === 'saved'
                    ? '<div class="empty-state" style="grid-column: 1/-1;"><i class="far fa-bookmark empty-icon"></i><h3>No saved jobs</h3><p>Click the bookmark on any job to save it here.</p></div>'
                    : '<div class="empty-state" style="grid-column: 1/-1;"><i class="fas fa-search empty-icon"></i><h3>No jobs found</h3><p>Try different keywords or clear filters to see all jobs.</p><button type="button" class="btn btn-outline btn-empty-state" onclick="clearAllFiltersAndReload()"><i class="fas fa-times-circle"></i> Show all jobs</button></div>';
                elements.jobsGrid.innerHTML = emptyMsg;
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

function renderJobCard(job) {
    const initials = getInitials(job.company || job.title || 'JB');
    const preview = (job.description || '').substring(0, 120);
    const deadline = job.deadline || job.deadline_text;
    const saved = getSavedJobIds().has(job.id);
    let tags = '';
    if (job.apply_email) tags += '<span class="tag tag-email">Email</span>';
    else if (job.apply_url) tags += '<span class="tag tag-link">Apply</span>';
    else tags += '<span class="tag tag-success">View</span>';
    return `
        <div class="job-card" onclick="openJobModal(${job.id})" data-job-id="${job.id}">
            <div class="job-card-header">
                <div class="job-logo">${initials}</div>
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
    const deadline = job.deadline || job.deadline_text || '';
    const saved = getSavedJobIds().has(job.id);

    let applyHtml = '';
    const outUrl = `${API_BASE}/api/out?id=${job.id}`;
    const outEmailUrl = `${API_BASE}/api/out?id=${job.id}&type=email`;
    if (job.apply_email) {
        const safeEmail = escapeHtml(job.apply_email);
        const emailAttr = escapeAttr(job.apply_email);
        applyHtml = `
            <div class="apply-section">
                <h4>How to Apply</h4>
                <p>Send your CV to:</p>
                <div class="email-box">
                    <span class="email-display">${safeEmail}</span>
                    <button class="btn btn-copy" onclick="copyEmail('${safeEmail}', this)"><i class="fas fa-copy"></i> Copy</button>
                    <button type="button" class="btn btn-primary" data-job-id="${job.id}" data-apply-email="${emailAttr}" onclick="openApplyEmail(this)"><i class="fas fa-paper-plane"></i> Open email</button>
                </div>
            </div>
        `;
    } else if (job.apply_url) {
        applyHtml = `
            <div class="apply-section">
                <h4>How to Apply</h4>
                <a href="${escapeHtml(outUrl)}" target="_blank" class="btn btn-primary btn-lg"><i class="fas fa-external-link-alt"></i> Apply online</a>
            </div>
        `;
    }

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

    elements.modalStickyTitle.textContent = job.title || 'Job';
    elements.modalStickyActions.innerHTML = stickyActionsHtml;
    elements.modalStickyApply.classList.remove('visible');

    elements.modalBody.innerHTML = `
        <div class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="modalJobTitle">
            <button class="modal-close" onclick="closeModal()" aria-label="Close"><i class="fas fa-times"></i></button>
            <div class="modal-header">
                <h2 id="modalJobTitle">${escapeHtml(job.title || 'Job Details')}</h2>
                <div class="modal-meta">
                    ${job.company ? `<span><i class="fas fa-building"></i> ${escapeHtml(job.company)}</span>` : ''}
                    ${job.location ? `<span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(job.location)}</span>` : ''}
                    ${deadline ? `<span><i class="fas fa-clock"></i> ${escapeHtml(deadline)}</span>` : ''}
                </div>
                ${getChannelSlug(job) ? `<div class="modal-source-channel">${getChannelHtml(job, { size: 32, longName: true, className: 'modal-channel' })}</div>` : ''}
                <div class="modal-header-actions">
                    <button type="button" class="btn btn-icon modal-share" onclick="shareJob(${job.id})" aria-label="Share job"><i class="fas fa-share-alt"></i> Share</button>
                    <button class="btn job-card-save ${saved ? 'saved' : ''}" onclick="toggleSaveInModal(${job.id}, this)" aria-label="Save job">
                        <i class="${saved ? 'fas' : 'far'} fa-bookmark"></i>
                    </button>
                </div>
            </div>
            <div class="modal-body-content">
                ${applyHtml}
                <div class="description-section">
                    <h4>Full description</h4>
                    <div class="description-text">${formatJobDescription(job.description)}</div>
                </div>
                ${job.source_url ? `<div class="source-section"><a href="${escapeHtml(job.source_url)}" target="_blank">View original on source website</a></div>` : ''}
                <p class="modal-view-full"><a href="${escapeHtml(getJobShareUrl(job.id))}" target="_blank" rel="noopener"><i class="fas fa-external-link-alt"></i> View full page</a></p>
                <p class="modal-report"><a href="mailto:info@srafelagi.et?subject=${encodeURIComponent('Report job: ' + (job.title || 'Untitled'))}&body=${encodeURIComponent('Job title: ' + (job.title || '') + '\nSource URL: ' + (job.source_url || window.location.href) + '\n\nPlease describe the issue:')}" class="link-muted"><i class="fas fa-flag"></i> Report this job</a></p>
                <div id="similarJobsContainer">${similarJobsHtml || '<p class="similar-jobs-loading">Loading more jobs…</p>'}</div>
            </div>
        </div>
    `;

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
        const res = await fetch(`${API_BASE}/api/jobs?per_page=5&page=1`);
        const data = await res.json();
        const jobs = (data.jobs || []).filter(j => j.id !== excludeId).slice(0, 4);
        if (jobs.length === 0) return '';
        return `
            <div class="similar-jobs">
                <h4>More jobs</h4>
                <div class="similar-jobs-list">
                    ${jobs.map(j => `
                        <a href="#" class="similar-job-item" onclick="closeModal(); openJobModal(${j.id}); return false;">
                            <strong>${escapeHtml(j.title || 'Job')}</strong>
                            ${j.company ? `<span class="company">${escapeHtml(j.company)}</span>` : ''}
                        </a>
                    `).join('')}
                </div>
            </div>
        `;
    } catch (e) { return ''; }
}

function toggleSaveInModal(jobId, btn) {
    const saved = toggleSavedJobId(jobId);
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
    return normalizeDescriptionStructure(safe);
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

async function shareJob(jobId) {
    const job = jobsCache[jobId];
    const title = job ? (job.title || 'Job') : 'Job';
    const text = job && job.company ? job.company : '';
    const url = getJobShareUrl(jobId);
    if (navigator.share && navigator.canShare && navigator.canShare({ title, text, url })) {
        try {
            await navigator.share({ title, text, url });
            showToast('Shared!', 'success');
            return;
        } catch (e) {
            if (e.name === 'AbortError') return;
        }
    }
    try {
        await navigator.clipboard.writeText(url);
        showToast('Link copied!', 'success');
    } catch (e) {
        showToast('Copy failed', 'error');
    }
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