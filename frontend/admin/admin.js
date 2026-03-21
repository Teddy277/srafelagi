// Admin utilities
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
