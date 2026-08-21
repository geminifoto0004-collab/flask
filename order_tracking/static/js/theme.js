(function () {
    'use strict';

    const STORAGE_KEY = 'orderTrackingThemeMode';
    const root = document.documentElement;

    function preferredTheme(mode) {
        if (mode === 'dark' || mode === 'light') return mode;
        try {
            return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        } catch (_) {
            return 'light';
        }
    }

    function readMode() {
        try {
            const saved = localStorage.getItem(STORAGE_KEY);
            return (saved === 'dark' || saved === 'light' || saved === 'system') ? saved : 'system';
        } catch (_) {
            return 'system';
        }
    }

    function updateButtons(theme) {
        document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
            const nextIsDark = theme !== 'dark';
            btn.dataset.themeState = theme;
            btn.setAttribute('aria-label', nextIsDark ? '切换深色模式' : '切换浅色模式');
            btn.setAttribute('title', nextIsDark ? '深色模式' : '浅色模式');

            // New UI uses line SVGs so the theme control matches the rest of the sidebar icons.
            // Keep legacy text-icon support for any old embedded template that may still exist.
            const moon = btn.querySelector('[data-theme-icon-moon]');
            const sun = btn.querySelector('[data-theme-icon-sun]');
            if (moon || sun) {
                if (moon) moon.hidden = theme === 'dark';
                if (sun) sun.hidden = theme !== 'dark';
            } else {
                const icon = btn.querySelector('[data-theme-icon]');
                if (icon) icon.textContent = theme === 'dark' ? '☀' : '☾';
            }
        });
    }

    let switchToken = 0;

    function applyMode(mode, persist) {
        const normalized = (mode === 'dark' || mode === 'light' || mode === 'system') ? mode : 'system';
        const theme = preferredTheme(normalized);
        const token = ++switchToken;

        root.classList.add('theme-switching');
        root.dataset.themeMode = normalized;
        root.dataset.theme = theme;
        root.style.colorScheme = theme;
        if (persist) {
            try { localStorage.setItem(STORAGE_KEY, normalized); } catch (_) {}
        }
        updateButtons(theme);

        try { void root.offsetWidth; } catch (_) {}
        requestAnimationFrame(() => requestAnimationFrame(() => {
            if (token === switchToken) root.classList.remove('theme-switching');
        }));
        return theme;
    }

    window.getTrackingThemeMode = readMode;
    window.applyTrackingTheme = function (mode) { return applyMode(mode, true); };
    window.toggleTrackingTheme = function () {
        const current = root.dataset.theme || preferredTheme(readMode());
        return applyMode(current === 'dark' ? 'light' : 'dark', true);
    };

    applyMode(readMode(), false);

    try {
        const media = window.matchMedia('(prefers-color-scheme: dark)');
        const onSystemThemeChanged = function () {
            if (readMode() === 'system') applyMode('system', false);
        };
        if (media.addEventListener) media.addEventListener('change', onSystemThemeChanged);
        else if (media.addListener) media.addListener(onSystemThemeChanged);
    } catch (_) {}

    document.addEventListener('DOMContentLoaded', function () {
        applyMode(readMode(), false);
    });

    window.addEventListener('pageshow', function () {
        applyMode(readMode(), false);
    });

    window.addEventListener('storage', function (event) {
        if (event.key === STORAGE_KEY) applyMode(readMode(), false);
    });
})();

/* Local ORDER hotfix retained while TiDB backend stays on the cloud branch. */
document.addEventListener('DOMContentLoaded', function () {
    if (typeof homeCardFocusRender !== 'function') return;
    window.homeCardFocusRender = function () {
        const state = homeCardFocusState;
        const el = homeCardFocusEls();
        if (!state || !el) return;
        const data = state.workflowData || {};
        const order = state.order || {};
        const statusKey = String(data.current_status || order.current_status || '').trim();
        const statusText = statusKey && typeof displayStatus === 'function' ? displayStatus(statusKey) : (statusKey || '尚无流程');
        el.orderNumber.textContent = state.workflowNumber || state.orderNumber || '—';
        el.customer.textContent = String(data.customer_name || order.customer_name || '—');
        el.status.textContent = statusText;
        el.adminNote.textContent = String(data.order_notes || order.order_notes || '').trim() || '暂无备注';
        el.salesNote.textContent = String(data.workflow_notes || data.notes || order.notes || '').trim() || '暂无备注';
        const rootCustomer = String(data.customer_name || order.customer_name || '').trim();
        if (el.share) el.share.hidden = !(rootCustomer && document.getElementById('desktopGuestShareDrawer') && typeof desktopGuestIsAdmin === 'function' && desktopGuestIsAdmin());

        ['admin', 'sales'].forEach(type => {
            const note = type === 'admin' ? el.adminNote : el.salesNote;
            const box = note?.closest('.home-card-focus-note-box');
            const isEditing = !!box?.classList.contains('is-editing');
            const btn = el.root.querySelector(`[data-focus-note-edit="${type}"]`);
            if (isEditing) {
                if (btn) btn.hidden = true;
                return;
            }
            if (btn) btn.hidden = !homeCardFocusCanEditNote(type);
            const editor = el.root.querySelector(`[data-focus-note-editor="${type}"]`);
            if (editor) editor.hidden = true;
            if (note) note.hidden = false;
        });
        homeCardFocusRenderWorkflows();
        homeCardFocusRenderMeta();
        homeCardFocusRenderTimeline();
        homeCardFocusRenderActions();
        homeCardFocusShowMedia(Math.min(state.mediaIndex || 0, Math.max(0, (state.media || []).length - 1)), {instant: true});
    };
});
