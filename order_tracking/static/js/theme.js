(function () {
    'use strict';

    const STORAGE_KEY = 'orderTrackingThemeMode';
    const root = document.documentElement;
    const themeScriptSrc = (document.currentScript && document.currentScript.src) ? document.currentScript.src : '';

    function loadShareQueueUiPatch() {
        if (!themeScriptSrc || document.querySelector('[data-share-queue-ui-patch]')) return;
        try {
            const jsUrl = new URL('share_queue_ui_patch.js', themeScriptSrc);
            const cssUrl = new URL('../css/share_queue_ui_patch.css', themeScriptSrc);
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = cssUrl.toString();
            link.dataset.shareQueueUiPatch = 'css';
            document.head.appendChild(link);
            const script = document.createElement('script');
            script.src = jsUrl.toString();
            script.dataset.shareQueueUiPatch = 'js';
            document.body.appendChild(script);
        } catch (_) {}
    }

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

        // Theme changes used to inherit the many `transition: all ...` rules in the
        // desktop dashboard. Rapid clicking could therefore leave different areas
        // visually half-way between light and dark for a short time. Apply the root
        // state atomically with transitions suspended, then re-enable them next frame.
        root.classList.add('theme-switching');
        root.dataset.themeMode = normalized;
        root.dataset.theme = theme;
        root.style.colorScheme = theme;
        if (persist) {
            try { localStorage.setItem(STORAGE_KEY, normalized); } catch (_) {}
        }
        updateButtons(theme);

        // Force style resolution while .theme-switching is still active.
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
        // Re-apply once DOM/CSS are ready. This also repairs pages restored from
        // browser cache where the DOM may carry an older theme state.
        applyMode(readMode(), false);
        loadShareQueueUiPatch();
    });

    window.addEventListener('pageshow', function () {
        applyMode(readMode(), false);
    });

    window.addEventListener('storage', function (event) {
        if (event.key === STORAGE_KEY) applyMode(readMode(), false);
    });
})();
