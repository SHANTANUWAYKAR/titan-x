/* ============================================================
   TITAN-X shared JS helpers for NEW dashboard pages (docs/UPGRADE_
   BRIEF.md Phase 12). getJson/toast/escapeHtml/safeUrl/fmtDate are
   copied verbatim from dashboard/index.html's own inline <script> (that
   file's <script> is not a module and cannot be imported from -- see
   this platform's own UI audit, 2026-09-13 -- so these are duplicated
   here rather than left unavailable to new pages; keep them in sync by
   hand if index.html's originals ever change).

   dirBadge()/pnlValue() are NEW: index.html was confirmed to
   differentiate buy/sell and P&L by color only, a real WCAG/colorblind
   gap. Every new page must render direction/P&L through these two
   functions, never through .tag/.positive/.negative directly.
   ============================================================ */

async function getJson(url) {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || ('Request failed: ' + res.status));
    return data;
}

async function postJson(url, body) {
    const res = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : ('HTTP ' + res.status));
    return data;
}

function toast(message, isError) {
    const stack = document.getElementById('toast-stack');
    if (!stack) return;
    const el = document.createElement('div');
    el.className = 'toast' + (isError ? ' error' : '');
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(() => el.remove(), 5000);
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

// See index.html's own comment on this exact function: escapeHtml alone
// does not neutralise a "javascript:" URL scheme. Only allow http/https.
function safeUrl(url) {
    if (url == null) return '#';
    try {
        const parsed = new URL(String(url), window.location.origin);
        return (parsed.protocol === 'http:' || parsed.protocol === 'https:') ? escapeHtml(parsed.href) : '#';
    } catch (e) {
        return '#';
    }
}

function fmtDate(d) {
    if (!d) return '—';
    try {
        return new Date(d).toLocaleString(undefined, {
            year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
        });
    } catch (e) { return String(d); }
}

function fmtNum(n, digits) {
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: digits ?? 2, maximumFractionDigits: digits ?? 2 });
}

/**
 * Colorblind-safe direction badge: a shape (▲ long/bullish, ▼ short/
 * bearish, ● neutral) ALWAYS accompanies color, per docs/UPGRADE_BRIEF.md
 * Phase 12's explicit mandate ("must differ in lightness or shape, not
 * hue alone"). `direction` accepts long/short/buy/sell/bullish/bearish/
 * neutral (case-insensitive); `label` overrides the displayed text
 * (defaults to the normalized direction, upper-cased).
 */
function dirBadge(direction, label) {
    const d = String(direction || '').toLowerCase();
    let cls = 'neutral', caret = '●', text = label || direction || 'N/A';
    if (d === 'long' || d === 'buy' || d === 'bullish') { cls = 'long'; caret = '▲'; }
    else if (d === 'short' || d === 'sell' || d === 'bearish') { cls = 'short'; caret = '▼'; }
    return `<span class="dir-badge ${cls}"><span class="caret">${caret}</span>${escapeHtml(text)}</span>`;
}

/**
 * Colorblind-safe P&L rendering: color + an explicit leading +/- sign
 * (shape substitute for a scalar value) -- never color alone.
 */
function pnlValue(value, suffix, digits) {
    if (value === null || value === undefined || Number.isNaN(value)) return '<span class="pnl-value neutral">—</span>';
    const num = Number(value);
    const cls = num > 0 ? 'positive' : (num < 0 ? 'negative' : 'neutral');
    const sign = num > 0 ? '+' : '';
    return `<span class="pnl-value ${cls}">${sign}${fmtNum(num, digits ?? 2)}${suffix || ''}</span>`;
}

/**
 * Renders the shared sidebar into #sidebar-root. `activeKey` marks which
 * nav-link gets .active. New pages link back to the original 5 SPA pages
 * via a real page load to /dashboard (that file's own in-page router is
 * inline script local to that document and cannot be driven from here).
 */
function renderSidebar(activeKey) {
    const root = document.getElementById('sidebar-root');
    if (!root) return;
    const links = [
        { key: 'overview', href: '/dashboard', label: 'Overview (Research Terminal)', icon: '<rect x="3" y="3" width="7" height="9" rx="1.5"></rect><rect x="14" y="3" width="7" height="5" rx="1.5"></rect><rect x="14" y="12" width="7" height="9" rx="1.5"></rect><rect x="3" y="16" width="7" height="5" rx="1.5"></rect>' },
        { key: 'market-structure', href: '/dashboard/market-structure', label: 'Market Structure', icon: '<path d="M3 3v18h18"></path><path d="M18.7 8l-5.1 5.1-3.9-3.9L4 14.9"></path>' },
        { key: 'risk', href: '/dashboard/risk', label: 'Risk Dashboard', icon: '<path d="M12 2 3 6v6c0 5 4 9 9 10 5-1 9-5 9-10V6z"></path>' },
        { key: 'portfolio', href: '/dashboard/portfolio', label: 'Portfolio & Positions', icon: '<circle cx="12" cy="12" r="9"></circle><path d="M12 3v18M3 12h18"></path>' },
        { key: 'news-sentiment', href: '/dashboard/news-sentiment', label: 'News & Sentiment', icon: '<path d="M4 4h16v12H7l-3 3z"></path>' },
        { key: 'options', href: '/dashboard/options', label: 'Options Chain (India)', icon: '<circle cx="12" cy="12" r="9"></circle><path d="M9 9h.01M15 9h.01M8 15c1.5 1 6.5 1 8 0"></path>' },
        { key: 'strategy-lab', href: '/dashboard/strategy-lab', label: 'Strategy Lab & Backtesting', icon: '<path d="M9 3h6l1 5-4 10-4-10z"></path>' },
    ];
    const navHtml = links.map(l => `
        <a class="nav-link${l.key === activeKey ? ' active' : ''}" href="${l.href}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${l.icon}</svg>
            ${escapeHtml(l.label)}
        </a>`).join('');
    root.innerHTML = `
        <div class="sidebar-brand">
            <div class="sidebar-logo">TX</div>
            <div class="sidebar-brand-text">TITAN-X<span>RESEARCH TERMINAL</span></div>
        </div>
        <div class="sidebar-section-label">Navigate</div>
        <nav class="sidebar-nav">${navHtml}</nav>
        <div class="sidebar-foot">
            <div class="sidebar-foot-note">Research platform only. No live execution. Human oversight is mandatory on every signal.</div>
        </div>`;
}
