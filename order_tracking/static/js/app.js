/**
 * ORDER page bootstrap.
 *
 * base.html has historically loaded js/app.js, while the current vendored ORDER
 * bundle keeps the actual home-page logic in tracking.js.  Keep this tiny loader
 * as the stable entry point so Render and LAN templates do not need different
 * script lists.
 */
(function () {
    'use strict';

    const bootScript = document.currentScript;
    if (!bootScript || !bootScript.src) return;

    const bootUrl = new URL(bootScript.src, window.location.href);
    const jsBase = bootUrl.href.replace(/app\.js(?:\?.*)?$/i, '');
    const versionQuery = bootUrl.search || '';

    function waitForDom() {
        if (document.readyState !== 'loading') return Promise.resolve();
        return new Promise(resolve => {
            document.addEventListener('DOMContentLoaded', resolve, { once: true });
        });
    }

    function scriptAlreadyLoaded(name) {
        return Array.from(document.scripts).some(script => {
            try {
                const url = new URL(script.src || '', window.location.href);
                return url.pathname.endsWith('/' + name);
            } catch (_) {
                return false;
            }
        });
    }

    function loadScript(name) {
        if (scriptAlreadyLoaded(name)) return Promise.resolve();
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = jsBase + name + versionQuery;
            script.async = false;
            script.dataset.orderBootstrap = '1';
            script.onload = () => resolve();
            script.onerror = () => reject(new Error('Failed to load ' + name));
            document.head.appendChild(script);
        });
    }

    function showBootstrapError(error) {
        console.error('[ORDER bootstrap]', error);
        const tbody = document.getElementById('ordersTableBody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="16" style="padding:40px;text-align:center;color:#c62828">ORDER 前端脚本载入失败：' +
                String(error && error.message ? error.message : error) + '</td></tr>';
        }
        const mobileList = document.getElementById('mobileOrdersList');
        if (mobileList) {
            mobileList.innerHTML = '<div class="mobile-empty error">ORDER 前端脚本载入失败</div>';
        }
    }

    async function boot() {
        try {
            // ui_i18n is safe on every ORDER page and owns the language toggle in base.html.
            await loadScript('ui_i18n.js');
            await waitForDom();

            // Only the ORDER home page needs the large tracking bundle.
            if (!document.getElementById('ordersTableBody')) return;

            await loadScript('tracking.js');
            await loadScript('new_order.js');
            await loadScript('WORKSPACE_drawer_addon.js');

            // tracking.js normally hooks DOMContentLoaded itself.  Because this
            // bootstrap intentionally waits until the DOM is complete, call the
            // home loader explicitly instead of leaving the permanent
            // "正在载入订单资料…" placeholder on screen.
            if (typeof window.loadHomeOrdersData === 'function') {
                await window.loadHomeOrdersData(false);
            } else {
                throw new Error('loadHomeOrdersData is unavailable after tracking.js loaded');
            }
        } catch (error) {
            showBootstrapError(error);
        }
    }

    boot();
})();
