// ============================================================
// Srafelagi AI Assistant — Chat Widget
// ============================================================

(function () {
    const API_BASE = (typeof window.SRAFELAGI_API_BASE === 'string' ? window.SRAFELAGI_API_BASE : '').replace(/\/$/, '');

    let history = [];   // [{role, content}]
    let cvText = '';
    let isOpen = false;
    let isLoading = false;

    // ── Inject HTML ─────────────────────────────────────────
    const html = `
<div id="ai-chat-btn" title="AI Job Assistant" aria-label="Open AI Job Assistant">
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>
    <span class="ai-chat-badge" id="aiChatBadge">AI</span>
</div>

<div id="ai-chat-panel" role="dialog" aria-modal="true" aria-label="AI Job Assistant" hidden>
    <div class="ai-chat-header">
        <div class="ai-chat-header-info">
            <div class="ai-chat-avatar">✦</div>
            <div>
                <div class="ai-chat-title">Srafelagi AI</div>
                <div class="ai-chat-subtitle" id="aiChatSubtitle">Your Ethiopian Job Assistant</div>
            </div>
        </div>
        <button class="ai-chat-close" id="aiChatClose" aria-label="Close">✕</button>
    </div>

    <div class="ai-chat-messages" id="aiChatMessages">
        <div class="ai-msg ai-msg--bot">
            <div class="ai-msg-bubble">
                👋 Hi! I'm <strong>Srafelagi AI</strong>, your Ethiopian job search assistant.<br><br>
                I can help you:<br>
                • Find jobs that match your skills<br>
                • Upload your CV for personalized matches<br>
                • Answer questions about any job<br><br>
                What are you looking for?
            </div>
        </div>
    </div>

    <div class="ai-chat-cv-bar" id="aiChatCvBar">
        <label class="ai-cv-upload-btn" for="aiCvFile" title="Upload your CV (PDF or TXT)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            Upload CV
        </label>
        <input type="file" id="aiCvFile" accept=".pdf,.txt" hidden>
        <span class="ai-cv-name" id="aiCvName"></span>
    </div>

    <div class="ai-chat-input-row">
        <input type="text" id="aiChatInput" placeholder="Ask me anything about jobs…" autocomplete="off" maxlength="500">
        <button id="aiChatSend" aria-label="Send">
            <svg id="aiSendIcon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            <svg id="aiStopIcon" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" style="display:none"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>
        </button>
    </div>
</div>`;

    const wrapper = document.createElement('div');
    wrapper.id = 'ai-assistant-root';
    wrapper.innerHTML = html;
    document.body.appendChild(wrapper);

    // ── Inject CSS ──────────────────────────────────────────
    const css = `
#ai-assistant-root { position: fixed; bottom: 24px; right: 24px; z-index: 9999; font-family: 'DM Sans', sans-serif; }
#ai-chat-btn {
    width: 58px; height: 58px; border-radius: 50%;
    background: linear-gradient(135deg, #065f46, #047857);
    color: #fff; display: flex; align-items: center; justify-content: center;
    cursor: pointer;
    position: relative; transition: transform .2s;
    -webkit-tap-highlight-color: transparent;
}
#ai-chat-btn:hover { transform: scale(1.08); }
.ai-chat-badge {
    position: absolute; top: -4px; right: -4px;
    background: #f59e0b; color: #fff; font-size: 9px; font-weight: 700;
    padding: 2px 5px; border-radius: 8px; letter-spacing: .5px;
}
#ai-chat-panel {
    position: fixed; bottom: 92px; right: 24px;
    width: 380px; max-height: 580px;
    background: var(--bg-primary, #fff); border-radius: 20px;
    box-shadow: 0 12px 48px rgba(0,0,0,.18); display: flex; flex-direction: column;
    overflow: hidden; border: 1px solid var(--divider, #e5e7eb);
    animation: aiSlideUp .25s ease;
}
@keyframes aiSlideUp { from { opacity:0; transform: translateY(20px); } to { opacity:1; transform: translateY(0); } }
#ai-chat-panel[hidden] { display: none !important; }
.ai-chat-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 16px; background: linear-gradient(135deg, #065f46, #047857);
    color: #fff;
}
.ai-chat-header-info { display: flex; align-items: center; gap: 10px; }
.ai-chat-avatar {
    width: 36px; height: 36px; border-radius: 50%;
    background: rgba(255,255,255,.2); display: flex; align-items: center;
    justify-content: center; font-size: 18px;
}
.ai-chat-title { font-weight: 700; font-size: 15px; }
.ai-chat-subtitle { font-size: 11px; opacity: .8; }
.ai-chat-close {
    background: rgba(255,255,255,.15); border: none; color: #fff;
    width: 28px; height: 28px; border-radius: 50%; cursor: pointer;
    font-size: 14px; display: flex; align-items: center; justify-content: center;
}
.ai-chat-messages {
    flex: 1; overflow-y: auto; padding: 16px; display: flex;
    flex-direction: column; gap: 12px;
}
/* Push messages to the bottom so a short conversation fills the panel
   from below instead of leaving a big blank space underneath. */
.ai-chat-messages::before { content: ""; margin-top: auto; }
.ai-msg { display: flex; }
.ai-msg--bot { justify-content: flex-start; }
.ai-msg--user { justify-content: flex-end; }
.ai-msg-bubble {
    max-width: 85%; padding: 10px 14px; border-radius: 16px;
    font-size: 14px; line-height: 1.5;
}
.ai-msg--bot .ai-msg-bubble {
    background: var(--bg-secondary, #f3f4f6); color: var(--text-primary, #111);
    border-bottom-left-radius: 4px;
}
.ai-msg--user .ai-msg-bubble {
    background: #065f46; color: #fff; border-bottom-right-radius: 4px;
}
.ai-typing { display: flex; gap: 4px; padding: 10px 14px; }
.ai-typing span {
    width: 7px; height: 7px; border-radius: 50%; background: #9ca3af;
    animation: aiDot 1.2s infinite;
}
.ai-typing span:nth-child(2) { animation-delay: .2s; }
.ai-typing span:nth-child(3) { animation-delay: .4s; }
@keyframes aiDot { 0%,80%,100%{transform:scale(.7);opacity:.5} 40%{transform:scale(1);opacity:1} }
.ai-job-cards { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.ai-job-card {
    background: var(--bg-primary, #fff); border: 1px solid var(--divider, #e5e7eb);
    border-radius: 10px; padding: 10px 12px; cursor: pointer;
    transition: border-color .2s, box-shadow .2s;
}
.ai-job-card:hover { border-color: #047857; box-shadow: 0 2px 8px rgba(4,120,87,.12); }
.ai-job-card-title { font-weight: 600; font-size: 13px; color: var(--text-primary, #111); }
.ai-job-card-meta { font-size: 12px; color: var(--text-secondary, #6b7280); margin-top: 2px; }
.ai-chat-cv-bar {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 12px; border-top: 1px solid var(--divider, #e5e7eb);
    background: var(--bg-secondary, #f9fafb);
}
.ai-cv-upload-btn {
    display: flex; align-items: center; gap: 5px; cursor: pointer;
    font-size: 12px; font-weight: 600; color: #047857;
    padding: 4px 10px; border-radius: 8px; border: 1px solid #047857;
    transition: background .2s;
}
.ai-cv-upload-btn:hover { background: #f0fdf4; }
.ai-cv-name { font-size: 11px; color: var(--text-secondary, #6b7280); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ai-chat-input-row {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 12px; border-top: 1px solid var(--divider, #e5e7eb);
}
#aiChatInput {
    flex: 1; border: 1px solid var(--divider, #e5e7eb); border-radius: 12px;
    padding: 9px 14px; font-size: 14px; outline: none;
    background: var(--bg-secondary, #f9fafb); color: var(--text-primary, #111);
    font-family: inherit;
}
#aiChatInput:focus { border-color: #047857; }
#aiChatSend {
    width: 38px; height: 38px; border-radius: 50%; border: none;
    background: #047857; color: #fff; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: background .2s; flex-shrink: 0;
}
#aiChatSend:hover { background: #065f46; }
#aiChatSend.ai-stop-mode { background: #dc2626; }
#aiChatSend.ai-stop-mode:hover { background: #b91c1c; }
#aiChatInput:disabled { opacity: 0.5; cursor: not-allowed; }
@media (max-width: 440px) {
    #ai-chat-panel { width: calc(100vw - 24px); right: 12px; bottom: 80px; }
    #ai-assistant-root { bottom: 16px; right: 16px; }
}`;

    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    // ── Elements ────────────────────────────────────────────
    const btn      = document.getElementById('ai-chat-btn');
    const panel    = document.getElementById('ai-chat-panel');
    const closeBtn = document.getElementById('aiChatClose');
    const messages = document.getElementById('aiChatMessages');
    const input    = document.getElementById('aiChatInput');
    const sendBtn  = document.getElementById('aiChatSend');
    const cvFile   = document.getElementById('aiCvFile');
    const cvName   = document.getElementById('aiCvName');

    // ── User identity (shared from app.js via window.SRAFELAGI_USER) ──
    function currentUserName() {
        const u = window.SRAFELAGI_USER;
        if (!u) return '';
        return u.first_name || u.username || (u.email ? u.email.split('@')[0] : '') || '';
    }
    function reflectUser() {
        const sub = document.getElementById('aiChatSubtitle');
        const name = currentUserName();
        if (sub) sub.textContent = name ? ('Hi ' + name + ' 👋') : 'Your Ethiopian Job Assistant';
    }
    document.addEventListener('srafelagi:auth', reflectUser);
    reflectUser();

    // ── Toggle ──────────────────────────────────────────────
    btn.addEventListener('click', () => {
        isOpen = !isOpen;
        panel.hidden = !isOpen;
        if (isOpen) { reflectUser(); input.focus(); scrollBottom(); }
    });
    closeBtn.addEventListener('click', () => { isOpen = false; panel.hidden = true; });

    // ── CV Upload ───────────────────────────────────────────
    cvFile.addEventListener('change', async () => {
        const file = cvFile.files[0];
        if (!file) return;
        cvName.textContent = file.name;
        addMessage('user', `📄 Uploaded CV: ${file.name}`);
        showTyping();

        const form = new FormData();
        form.append('file', file);
        try {
            const res = await fetch(`${API_BASE}/api/assistant/cv`, { method: 'POST', body: form });
            const data = await res.json();
            removeTyping();
            if (!res.ok) { addMessage('bot', data.detail || 'Could not read your CV. Try a text-based PDF.'); return; }
            cvText = data.cv_text || '';
            addMessage('bot', data.reply, data.jobs || []);
        } catch (e) {
            removeTyping();
            addMessage('bot', 'Upload failed. Please try again.');
        }
        cvFile.value = '';
    });

    // ── Send / Stop ─────────────────────────────────────────
    const sendIcon = document.getElementById('aiSendIcon');
    const stopIcon = document.getElementById('aiStopIcon');
    let _abortCtrl = null;

    function _setLoadingState(loading) {
        isLoading = loading;
        input.disabled = loading;
        sendBtn.classList.toggle('ai-stop-mode', loading);
        sendIcon.style.display = loading ? 'none' : '';
        stopIcon.style.display = loading ? '' : 'none';
        sendBtn.setAttribute('aria-label', loading ? 'Stop' : 'Send');
        if (!loading) input.focus();
    }

    function abort() {
        if (_abortCtrl) { _abortCtrl.abort(); _abortCtrl = null; }
        removeTyping();
        _setLoadingState(false);
    }

    async function send() {
        if (isLoading) { abort(); return; }
        const msg = input.value.trim();
        if (!msg) return;
        input.value = '';
        addMessage('user', msg);
        history.push({ role: 'user', content: msg });
        showTyping();
        _setLoadingState(true);
        _abortCtrl = new AbortController();

        try {
            const res = await fetch(`${API_BASE}/api/assistant/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: msg, history: history.slice(-8), cv_text: cvText, user_name: currentUserName() }),
                signal: _abortCtrl.signal,
            });
            const data = await res.json();
            removeTyping();
            const reply = data.reply || 'Sorry, I could not respond. Try again.';
            addMessage('bot', reply, data.jobs || []);
            history.push({ role: 'assistant', content: reply });
        } catch (e) {
            removeTyping();
            if (e.name !== 'AbortError') {
                addMessage('bot', 'Network error. Please check your connection.');
            }
        } finally {
            _abortCtrl = null;
            _setLoadingState(false);
        }
    }

    sendBtn.addEventListener('click', send);
    input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });

    // ── Helpers ─────────────────────────────────────────────
    function addMessage(role, text, jobs = []) {
        const div = document.createElement('div');
        div.className = `ai-msg ai-msg--${role === 'user' ? 'user' : 'bot'}`;

        const bubble = document.createElement('div');
        bubble.className = 'ai-msg-bubble';
        bubble.innerHTML = escapeAndFormat(text);

        div.appendChild(bubble);

        if (jobs.length > 0) {
            const cards = document.createElement('div');
            cards.className = 'ai-job-cards';
            jobs.forEach(j => {
                const card = document.createElement('div');
                card.className = 'ai-job-card';
                card.innerHTML = `
                    <div class="ai-job-card-title">${esc(j.title || 'Job')}</div>
                    <div class="ai-job-card-meta">${esc(j.company || '')}${j.location ? ' · ' + esc(j.location) : ''}${j.deadline ? ' · ' + esc(j.deadline) : ''}</div>`;
                card.addEventListener('click', () => {
                    window.location.hash = `job=${j.id}`;
                    // If app.js openModal exists, use it
                    if (typeof openJobModal === 'function') openJobModal(j.id);
                });
                cards.appendChild(card);
            });
            div.appendChild(cards);
        }

        messages.appendChild(div);
        scrollBottom();
    }

    function showTyping() {
        const div = document.createElement('div');
        div.className = 'ai-msg ai-msg--bot';
        div.id = 'aiTypingIndicator';
        div.innerHTML = '<div class="ai-msg-bubble ai-typing"><span></span><span></span><span></span></div>';
        messages.appendChild(div);
        scrollBottom();
    }

    function removeTyping() {
        document.getElementById('aiTypingIndicator')?.remove();
    }

    function scrollBottom() {
        setTimeout(() => { messages.scrollTop = messages.scrollHeight; }, 50);
    }

    function esc(str) {
        return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    function escapeAndFormat(text) {
        return esc(text)
            // Strip markdown headers (# ## ###)
            .replace(/^#{1,6}\s+/gm, '')
            // Strip horizontal rules
            .replace(/^[-*_]{3,}\s*$/gm, '')
            // Bold **text** → strong
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            // Strip remaining * _ ~ backtick formatting chars
            .replace(/\*(.*?)\*/g, '$1')
            .replace(/_(.*?)_/g, '$1')
            .replace(/~~(.*?)~~/g, '$1')
            .replace(/`([^`]+)`/g, '$1')
            // Bullet list lines (- item or * item) → • item
            .replace(/^[\-\*]\s+/gm, '• ')
            // Numbered list (1. item) → keep number, remove dot
            .replace(/^\d+\.\s+/gm, (m) => m)
            // Newlines to <br>
            .replace(/\n/g, '<br>');
    }

})();
