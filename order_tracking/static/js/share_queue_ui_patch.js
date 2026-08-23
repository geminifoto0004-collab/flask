/* 2026-08-23: make the global share queue dismissible without stopping background work. */
(function () {
    'use strict';

    const STORAGE_KEY = 'desktopGuestGlobalQueueDismissed';
    let dismissed = false;
    try { dismissed = sessionStorage.getItem(STORAGE_KEY) === '1'; } catch (_) {}

    function setDismissed(value) {
        dismissed = !!value;
        try {
            if (dismissed) sessionStorage.setItem(STORAGE_KEY, '1');
            else sessionStorage.removeItem(STORAGE_KEY);
        } catch (_) {}
    }

    function ensureClose(box) {
        if (!box || box.querySelector('.desktop-share-global-queue-close')) return;
        const close = document.createElement('span');
        close.className = 'desktop-share-global-queue-close';
        close.setAttribute('role', 'button');
        close.setAttribute('tabindex', '0');
        close.setAttribute('aria-label', '关闭分享队列');
        close.setAttribute('title', '关闭');
        close.textContent = '×';
        const dismiss = (event) => {
            event.preventDefault();
            event.stopPropagation();
            setDismissed(true);
            box.hidden = true;
        };
        close.addEventListener('click', dismiss);
        close.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') dismiss(event);
        });
        box.appendChild(close);
    }

    const original = window.desktopGuestUpdateGlobalQueue;
    if (typeof original === 'function') {
        window.desktopGuestUpdateGlobalQueue = function () {
            const result = original.apply(this, arguments);
            const box = document.getElementById('desktopGuestGlobalQueue');
            if (!box) return result;
            ensureClose(box);

            // If the original updater says there is no active/failed job, reset the
            // dismissal so a future new job can notify the user again.
            if (box.hidden) {
                if (!dismissed) return result;
                const items = Array.isArray(window.desktopGuestActiveItemsCache)
                    ? window.desktopGuestActiveItemsCache : [];
                const hasRelevant = items.some((item) => {
                    if (String(item?.status || 'active').toLowerCase() !== 'active') return false;
                    if (typeof window.desktopGuestImageSyncView !== 'function') return false;
                    const view = window.desktopGuestImageSyncView(item);
                    return !!(view && (view.active || view.failed));
                });
                if (!hasRelevant) setDismissed(false);
                return result;
            }

            if (dismissed) box.hidden = true;
            return result;
        };
    }

    function enhanceExisting() {
        const box = document.getElementById('desktopGuestGlobalQueue');
        if (!box) return;
        ensureClose(box);
        if (dismissed && !box.hidden) box.hidden = true;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(enhanceExisting, 0), { once: true });
    } else {
        setTimeout(enhanceExisting, 0);
    }
})();
