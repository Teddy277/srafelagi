// Admin utilities
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

function getAuthHeaders() {
    return {'Authorization': `Bearer ${localStorage.getItem('admin_token')}`};
}

function checkAuth() {
    if (!localStorage.getItem('admin_token')) {
        window.location.href = '/admin/login.html';
    }
}

function logout() {
    localStorage.removeItem('admin_token');
    window.location.href = '/admin/login.html';
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}
