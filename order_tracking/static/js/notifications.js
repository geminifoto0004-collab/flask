/**
 * 通知系统 - 前端逻辑
 * 铃铛红点 + 居中面板 + 标记已读
 */
(function () {
    'use strict';

    // Render/cloud mode does not use the local SQLite notification subsystem.
    if (document.body && document.body.dataset.cloudMode === 'true') return;

    // ===== 状态 =====
    let notifCurrentTab = 'unread';
    let notifPage = 1;
    let notifLoading = false;
    let notifHasMore = true;
    let panelOpen = false;
    let unreadCountCache = 0;
    let unreadPollTimer = null;
    const UNREAD_POLL_MS = 15000; // keep badge responsive without manual refresh

    // 通知类型 → SVG 图标
    const TYPE_ICONS = {
        order_unlocked: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 9.9-1"></path></svg>',
        delivery_warning: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
        delivery_overdue: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>',
        red_light: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
        workflow_transferred: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2"><polyline points="17 1 21 5 17 9"></polyline><path d="M3 11V9a4 4 0 0 1 4-4h14"></path><polyline points="7 23 3 19 7 15"></polyline><path d="M21 13v2a4 4 0 0 1-4 4H3"></path></svg>',
        order_locked: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>',
        account_approved: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>',
    };

    const TYPE_ICON_DEFAULT = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>';

    // ===== 初始化 =====
    document.addEventListener('DOMContentLoaded', function () {
        fetchUnreadCount();
        if (!unreadPollTimer) {
            unreadPollTimer = setInterval(fetchUnreadCount, UNREAD_POLL_MS);
        }
        triggerAlertCheck();

        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) {
                fetchUnreadCount();
                if (panelOpen) {
                    notifPage = 1;
                    notifHasMore = true;
                    loadNotifications(false);
                }
            }
        });

        window.addEventListener('focus', function () {
            fetchUnreadCount();
            if (panelOpen) {
                notifPage = 1;
                notifHasMore = true;
                loadNotifications(false);
            }
        });

        const listEl = document.getElementById('notificationList');
        if (listEl) {
            listEl.addEventListener('scroll', function () {
                if (notifLoading || !notifHasMore) return;
                const { scrollTop, scrollHeight, clientHeight } = listEl;
                if (scrollTop + clientHeight >= scrollHeight - 30) {
                    notifPage++;
                    loadNotifications(true);
                }
            });
        }
    });

    // ===== 获取未读数量 =====
    function fetchUnreadCount() {
        fetch('/tracking/api/notifications/unread-count', { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                if (!data.success) return;
                const count = Number(data.count || 0);
                const increased = count > unreadCountCache;
                unreadCountCache = count;
                updateBadge(count);

                // If panel is open and unread count changed, keep list in sync.
                if (panelOpen && notifCurrentTab === 'unread' && increased) {
                    notifPage = 1;
                    notifHasMore = true;
                    loadNotifications(false);
                }
            })
            .catch(() => { });
    }

    // ===== 更新红点 =====
    function updateBadge(count) {
        const badge = document.getElementById('notificationBadge');
        if (!badge) return;
        if (count > 0) {
            badge.textContent = count > 99 ? '99+' : count;
            badge.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
        }
    }

    // ===== 触发告警检查（每个浏览器会话只调一次） =====
    function triggerAlertCheck() {
        const key = 'alert_check_' + new Date().toISOString().slice(0, 10); // 按天
        if (sessionStorage.getItem(key)) return; // 本次会话今天已检查过
        sessionStorage.setItem(key, '1');
        
        fetch('/tracking/api/notifications/check-alerts', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' }
        })
            .then(r => r.json())
            .then(data => {
                if (data.success && data.created > 0) fetchUnreadCount();
            })
            .catch(() => {
                sessionStorage.removeItem(key); // 失败时允许重试
            });
    }

    // ===== 切换面板 =====
    window.toggleNotificationPanel = function () {
        const panel = document.getElementById('notificationPanel');
        const backdrop = document.getElementById('notificationBackdrop');
        if (!panel) return;

        panelOpen = !panelOpen;
        if (panelOpen) {
            panel.classList.add('show');
            if (backdrop) backdrop.classList.add('show');
            notifCurrentTab = 'unread';
            notifPage = 1;
            notifHasMore = true;
            updateTabUI();
            loadNotifications(false);
        } else {
            panel.classList.remove('show');
            if (backdrop) backdrop.classList.remove('show');
        }
    };

    window.closeNotificationPanel = function () {
        const panel = document.getElementById('notificationPanel');
        const backdrop = document.getElementById('notificationBackdrop');
        if (panel) panel.classList.remove('show');
        if (backdrop) backdrop.classList.remove('show');
        panelOpen = false;
    };

    // ===== 切换 Tab =====
    window.switchNotifTab = function (tab) {
        if (tab === notifCurrentTab) return;
        notifCurrentTab = tab;
        notifPage = 1;
        notifHasMore = true;
        updateTabUI();
        loadNotifications(false);
    };

    function updateTabUI() {
        document.querySelectorAll('.notif-tab').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === notifCurrentTab);
        });
    }

    // ===== 加载通知列表 =====
    function loadNotifications(append) {
        if (notifLoading) return;
        notifLoading = true;

        const listEl = document.getElementById('notificationList');
        if (!listEl) return;

        if (!append) {
            listEl.innerHTML = '<div style="text-align:center; padding: 2rem; color: #9ca3af;">加载中...</div>';
        }

        const params = new URLSearchParams({
            tab: notifCurrentTab,
            page: notifPage,
            page_size: 20
        });

        fetch(`/tracking/api/notifications?${params}`, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                notifLoading = false;
                if (!data.success) return;

                const items = data.data || [];
                const total = data.total || 0;

                if (!append) listEl.innerHTML = '';

                if (items.length === 0 && !append) {
                    listEl.innerHTML = `
                        <div class="notification-empty">
                            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#d1d5db" stroke-width="1.5">
                                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
                                <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
                            </svg>
                            <p>${notifCurrentTab === 'unread' ? '没有未读通知' : '暂无通知'}</p>
                        </div>`;
                    notifHasMore = false;
                    return;
                }

                items.forEach(item => listEl.appendChild(createNotifElement(item)));

                const loaded = listEl.querySelectorAll('.notification-item').length;
                notifHasMore = loaded < total;
            })
            .catch(() => { notifLoading = false; });
    }

    // ===== 创建通知 DOM 元素 =====
    function createNotifElement(item) {
        const div = document.createElement('div');
        div.className = `notification-item${item.is_read ? '' : ' unread'}`;
        div.dataset.notifId = item.id;

        const iconSvg = TYPE_ICONS[item.type] || TYPE_ICON_DEFAULT;
        const timeStr = formatNotifTime(item.created_at);

        div.innerHTML = `
            <span class="notif-dot"></span>
            <div class="notif-icon type-${item.type}">${iconSvg}</div>
            <div class="notif-content">
                <div class="notif-title">${escapeHtml(item.title)}</div>
                ${item.message ? `<div class="notif-message">${escapeHtml(item.message)}</div>` : ''}
                <div class="notif-time">${timeStr}</div>
            </div>
        `;

        div.addEventListener('click', () => {
            markSingleRead(item);
            div.classList.remove('unread');
        });

        return div;
    }

    // ===== 标记单条已读 =====
    function markSingleRead(item) {
        if (item.is_read) return;
        item.is_read = true;
        fetch(`/tracking/api/notifications/${item.id}/read`, {
            method: 'PUT',
            credentials: 'same-origin'
        }).then(() => fetchUnreadCount()).catch(() => { });
    }

    // ===== 全部已读 =====
    window.markAllNotificationsRead = function () {
        fetch('/tracking/api/notifications/read-all', {
            method: 'PUT',
            credentials: 'same-origin'
        })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    fetchUnreadCount();
                    if (panelOpen) {
                        notifPage = 1;
                        notifHasMore = true;
                        loadNotifications(false);
                    }
                    if (typeof showToast === 'function') {
                        showToast('成功', '已全部标为已读', 'success');
                    }
                }
            })
            .catch(() => { });
    };

    // ===== 时间格式化 =====
    function formatNotifTime(dateStr) {
        if (!dateStr) return '';
        try {
            const d = new Date(dateStr.replace(' ', 'T'));
            const now = new Date();
            const diffMs = now - d;
            const diffMin = Math.floor(diffMs / 60000);
            const diffHr = Math.floor(diffMs / 3600000);
            const diffDay = Math.floor(diffMs / 86400000);

            if (diffMin < 1) return '刚刚';
            if (diffMin < 60) return `${diffMin} 分钟前`;
            if (diffHr < 24) return `${diffHr} 小时前`;
            if (diffDay < 7) return `${diffDay} 天前`;

            const mm = String(d.getMonth() + 1).padStart(2, '0');
            const dd = String(d.getDate()).padStart(2, '0');
            const hh = String(d.getHours()).padStart(2, '0');
            const mi = String(d.getMinutes()).padStart(2, '0');
            return `${mm}-${dd} ${hh}:${mi}`;
        } catch {
            return dateStr;
        }
    }

    // ===== HTML 转义 =====
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

})();
