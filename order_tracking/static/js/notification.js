/**
 * Compatibility entry point for the legacy base.html script name.
 * The maintained implementation lives in notifications.js.
 */
(function () {
    'use strict';

    // Render unified mode is read-only and intentionally does not mirror local
    // notification history, so do not poll the empty cloud notification table.
    if (document.body && document.body.dataset.cloudReadOnly === 'true') return;

    const current = document.currentScript;
    if (!current || !current.src) return;
    const url = new URL(current.src, window.location.href);
    const src = url.href.replace(/notification\.js(?:\?.*)?$/i, 'notifications.js' + (url.search || ''));
    if (Array.from(document.scripts).some(s => (s.src || '').includes('/notifications.js'))) return;

    const script = document.createElement('script');
    script.src = src;
    script.async = false;
    document.head.appendChild(script);
})();
