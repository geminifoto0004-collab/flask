/**
 * 获取状态灯号的 SVG 图标（替代 emoji，确保跨平台兼容）
 */
function getStatusLightIcon(light) {
    const icons = {
        'red': '<svg class="status-light-icon" width="10" height="10" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" fill="#EF4444" stroke="#DC2626" stroke-width="1"/></svg>',
        'yellow': '<svg class="status-light-icon" width="10" height="10" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" fill="#F59E0B" stroke="#D97706" stroke-width="1"/></svg>',
        'green': '<svg class="status-light-icon" width="10" height="10" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" fill="#22C55E" stroke="#16A34A" stroke-width="1"/></svg>',
        'black': '<svg class="status-light-icon" width="10" height="10" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" fill="#6B7280" stroke="#4B5563" stroke-width="1"/></svg>'
    };
    return icons[light] || icons['green'];
}

// 在 DOMContentLoaded 之前，先檢查是否有自動觸發的 Toast
(function() {
    'use strict';
    
    // 儲存原始的 showToast 函數
    const originalShowToast = window.showToast;
    
    // 頁面載入完成前，禁止顯示 Toast
    let pageLoaded = false;
    
    // 覆寫 showToast 函數
    window.showToast = function(title, message, type = 'success', duration = 3000) {
        // 如果頁面還沒載入完成，忽略 Toast
        if (!pageLoaded) {
            console.log('[阻止] 頁面載入中，忽略 Toast:', title);
            return;
        }
        
        // 頁面載入後正常顯示
        if (originalShowToast) {
            originalShowToast(title, message, type, duration);
        }
    };
    
    // 頁面載入完成後，允許顯示 Toast
    window.addEventListener('DOMContentLoaded', function() {
        setTimeout(function() {
            pageLoaded = true;
            console.log('[允許] 頁面載入完成，現在可以顯示 Toast');
        }, 500); // 延遲 500ms，確保頁面完全載入
    });
    
    // 如果頁面已經載入完成
    if (document.readyState === 'complete') {
        setTimeout(function() {
            pageLoaded = true;
        }, 500);
    }
})();

// 修復 Toast 自動消失
function fixToastAutoHide() {
    const style = document.createElement('style');
    style.textContent = `
        .toast {
            pointer-events: auto !important;
        }
        .toast.show {
            display: flex !important;
            opacity: 1 !important;
            transform: translateX(0) !important;
        }
    `;
    document.head.appendChild(style);
}

// 頁面載入時執行
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fixToastAutoHide);
} else {
    fixToastAutoHide();
}
/**
 * 订单流程追踪系统
 */

/**
/**
 * 订单流程追踪系统 - 完整配置文件
 * 修改这个文件就能控制整个系统的行为
 */



// ==================== UTC时间处理函数（解决时区问题）====================

/**
 * 获取当前UTC日期（Date对象）
 */
function getTodayUTC() {
    const now = new Date();
    return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

/**
 * 解析日期字符串为UTC Date对象（只保留日期，时间设为00:00:00 UTC）
 */
function parseUTCDate(dateStr) {
    if (!dateStr) return null;
    // 只取日期部分 "2026-01-08"，加上UTC时间标记
    const dateOnly = dateStr.substring(0, 10);
    const dt = new Date(dateOnly + 'T00:00:00Z');
    return isNaN(dt.getTime()) ? null : dt;
}

/**
 * 计算两个日期之间的天数差（UTC）
 */
function diffDaysUTC(fromDateStr, toDateStr) {
    const from = parseUTCDate(fromDateStr);
    const to = parseUTCDate(toDateStr);
    
    if (!from || !to) return null;
    
    const diffMs = to - from;
    return Math.max(0, Math.round(diffMs / (1000 * 60 * 60 * 24)));
}

/**
 * 格式化UTC日期为显示字符串
 */
function formatUTCDate(dateStr) {
    const dt = parseUTCDate(dateStr);
    if (!dt) return '-';
    
    const year = dt.getUTCFullYear();
    const month = String(dt.getUTCMonth() + 1).padStart(2, '0');
    const day = String(dt.getUTCDate()).padStart(2, '0');
    
    return `${year}/${month}/${day}`;
}

/**
 * 解析日期字符串為本地日期（僅日期部分，時間設為 00:00 本地時間）
 * 用於 status_days 計算，與後端 date.today() 保持一致
 */
function parseLocalDate(dateStr) {
    if (!dateStr) return null;
    const dateOnly = dateStr.substring(0, 10);
    const parts = dateOnly.split('-');
    if (parts.length !== 3) return null;
    const dt = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
    return isNaN(dt.getTime()) ? null : dt;
}

/**
 * 獲取今天的本地日期（Date 對象，時間 00:00 本地時間）
 */
function getTodayLocal() {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

/**
 * 计算订单当前等待天数（与时间轴最后状态一致）
 * 使用本地日期計算，與後端 Python date.today() 保持一致，避免 UTC 時區偏差
 */
function getOrderWaitingDays(order) {
    const today = getTodayLocal();
    let lastDate = null;

    if (order && Array.isArray(order.history) && order.history.length > 0) {
        const lastItem = order.history[order.history.length - 1];
        lastDate = parseLocalDate(lastItem?.action_date || lastItem?.timestamp || lastItem?.date);
    }

    if (!lastDate && order) {
        lastDate = parseLocalDate(
            order.last_status_change_date ||
            order.status_updated_at ||
            order.current_status_date ||
            order.status_date ||
            order.order_date
        );
    }

    if (!lastDate) return order?.status_days || 0;

    const diffMs = today - lastDate;
    return Math.max(0, Math.round(diffMs / (1000 * 60 * 60 * 24)));
}

/**
 * 使用行資料更新表格中的等待天數
 */
function refreshStatusDaysFromRows() {
    const rows = document.querySelectorAll('#ordersTableBody tr[data-order-number]');
    rows.forEach(row => {
        const daysSpan = row.querySelector('.days');
        if (!daysSpan) return;
        const statusKey = row.dataset.status || '';
        if (typeof STATUS !== 'undefined' && (statusKey === STATUS.COMPLETED || statusKey === STATUS.CANCELLED)) {
            daysSpan.textContent = '-';
            return;
        }
        const orderData = {
            status_days: parseInt(daysSpan.textContent, 10) || 0,
            history: null,
            last_status_change_date: row.dataset.lastStatusChangeDate || '',
            status_updated_at: row.dataset.statusUpdatedAt || '',
            order_date: row.dataset.orderDate || ''
        };
        const statusDays = getOrderWaitingDays(orderData);
        daysSpan.textContent = `${statusDays}天`;
    });
}

// ==================== 共用工具函數 ====================

// Toast提示
function showToast(title, message, type = 'success', duration = 3000) {
    const existing = document.getElementById('toast');
    let toast = existing;

    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        toast.className = 'toast';
        toast.innerHTML = `
            <div class="toast-icon" style="font-size: 1.5rem;"></div>
            <div class="toast-content">
                <div class="toast-title" id="toastTitle"></div>
                <div class="toast-message" id="toastMessage"></div>
            </div>
            <button class="modal-close" onclick="this.parentElement.classList.remove('show'); setTimeout(() => this.parentElement.remove(), 300);" style="background: none; border: none; font-size: 1.2rem; color: #6b7280; cursor: pointer; padding: 0; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center;">×</button>
        `;
        document.body.appendChild(toast);
    }

    // 移除所有类型类
    toast.classList.remove('toast-success', 'toast-error', 'toast-danger', 'toast-warning');
    
    // 添加对应的类型类
    if (type === 'error' || type === 'danger') {
        toast.classList.add('toast-error');
    } else if (type === 'warning') {
        toast.classList.add('toast-warning');
    } else {
        toast.classList.add('toast-success');
    }

    // 设置图标 - 使用 CSS 类控制显示
    const iconEl = toast.querySelector('.toast-icon');
    if (iconEl) {
        iconEl.textContent = ''; // 图标由 CSS ::before 控制
    }

    const titleEl = document.getElementById('toastTitle');
    const msgEl = document.getElementById('toastMessage');
    if (titleEl) titleEl.textContent = title;
    if (msgEl) msgEl.textContent = message;

    toast.classList.add('show');

    setTimeout(() => {
        toast.classList.remove('show');
        if (!existing) {
            setTimeout(() => toast.remove(), 300);
        }
    }, duration);
}

// 日期格式化：今年显示月/日，非今年显示年/月/日
function formatDate(dateInput, currentYear = new Date().getUTCFullYear()) {
    if (!dateInput) return '-';
    const date = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (Number.isNaN(date.getTime())) return '-';
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    const day = String(date.getUTCDate()).padStart(2, '0');
    if (year === currentYear) {
        return `${month}/${day}`;
    }
    return `${year}/${month}/${day}`;
}

/**
 * 计算两个日期之间的天数
 */
function calculateDays(endDate, startDate) {
    const end = endDate instanceof Date ? endDate : parseUTCDate(endDate);
    const start = startDate instanceof Date ? startDate : parseUTCDate(startDate);
    if (!end || !start) return 0;
    const diffTime = end - start;
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    return diffDays >= 0 ? diffDays : 0;
}

/**
 * 根据天数获取状态 class
 */
function getDaysStatusClass(days, statusKey) {
    if (typeof getStatusThresholds !== 'function') return 'status-ok';
    const thresholds = getStatusThresholds(statusKey);
    const { yellowDays, redDays } = thresholds || {};
    if (yellowDays === null && redDays === null) {
        return 'status-ok';
    }
    if (redDays !== null && days > redDays) {
        return 'status-late';
    }
    if (yellowDays !== null && days > yellowDays) {
        return 'status-warning';
    }
    return 'status-ok';
}

/**
 * 生成完整时间轴 HTML
 */
function generateTimeline(statusHistory, lang = 'zh_tw', options = {}) {
    if (!statusHistory || statusHistory.length === 0) {
        return '<div class="timeline-empty">暂无历史记录</div>';
    }
    // 天數計算用本地日期（與後端 date.today() 一致），顯示格式仍用 UTC
    const todayLocal = typeof getTodayLocal === 'function' ? getTodayLocal() : new Date();
    const todayUTC = getTodayUTC();
    const currentYear = todayUTC.getUTCFullYear();
    const prependHtml = options.prependHtml || '';
    let html = `<div class="timeline-wrapper">${prependHtml}`;

    const lastStatusKey = statusHistory[statusHistory.length - 1]?.status
        || statusHistory[statusHistory.length - 1]?.to_status
        || statusHistory[statusHistory.length - 1]?.current_status;
    const isTerminalLast = (typeof STATUS !== 'undefined')
        && (lastStatusKey === STATUS.COMPLETED || lastStatusKey === STATUS.CANCELLED);

    statusHistory.forEach((record, index) => {
        const isLast = index === statusHistory.length - 1;
        const isActive = isLast;
        const isDone = !isLast;

        const statusKey = record.status || record.to_status || record.current_status || '';
        const statusLabel = typeof displayStatus === 'function'
            ? displayStatus(statusKey, lang)
            : statusKey;
        const statusIcon = typeof getStatusIcon === 'function'
            ? getStatusIcon(statusKey)
            : '';
        const dateStr = record.timestamp || record.action_date || record.date;
        const recordDate = parseUTCDate(dateStr);  // UTC 用於日期格式顯示
        const recordDateLocal = typeof parseLocalDate === 'function' ? parseLocalDate(dateStr) : recordDate;  // 本地用於天數計算
        const formattedDate = formatDate(recordDate, currentYear);

        html += `
        <div class="step-item ${isDone ? 'done' : ''} ${isActive ? 'active' : ''}">
            <div class="icon-circle">
                ${statusIcon}
            </div>
            <div class="label">${statusLabel}</div>
            <div class="date">${formattedDate}</div>`;

        if (isLast && !isTerminalLast) {
            // 用本地日期計算等待天數，與後端 date.today() 一致
            const waitingDays = Math.max(0, Math.floor((todayLocal - recordDateLocal) / (1000 * 60 * 60 * 24)));
            html += `
            <div class="wait-pill">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                已等 ${waitingDays} 天
            </div>`;
        }

        html += `</div>`;

        if (!isLast) {
            const nextRecord = statusHistory[index + 1];
            const nextDateStr = nextRecord?.timestamp || nextRecord?.action_date || nextRecord?.date;
            const nextDateLocal = typeof parseLocalDate === 'function' ? parseLocalDate(nextDateStr) : parseUTCDate(nextDateStr);
            const days = (nextDateLocal && recordDateLocal)
                ? Math.max(0, Math.floor((nextDateLocal - recordDateLocal) / (1000 * 60 * 60 * 24)))
                : 0;
            const lineClass = isTerminalLast ? 'solid' : ((index === statusHistory.length - 2) ? 'dashed-red' : 'solid');
            const daysStatusClass = getDaysStatusClass(days, statusKey);
            html += `
        <div class="connector">
            <div class="days-above ${daysStatusClass}">${days}天</div>
            <div class="line ${lineClass}"></div>
        </div>`;
        }
    });

    html += '</div>';
    return html;
}

// 获取今天日期
function getTodayDate() {
    return new Date().toISOString().split('T')[0];
}

// ==================== 日期输入统一显示（YYYY-MM-DD） ====================
function enhanceUnifiedDateInput(dateInput) {
    if (!dateInput || dateInput.type !== 'date') return null;
    if (dateInput.dataset.unifiedDateEnhanced === '1') return dateInput.parentElement;

    const wrapper = document.createElement('div');
    wrapper.className = 'unified-date-wrapper';

    const display = document.createElement('input');
    display.type = 'text';
    display.readOnly = true;
    display.className = `${dateInput.className} unified-date-display`.trim();
    display.placeholder = 'YYYY-MM-DD';

    const triggerBtn = document.createElement('button');
    triggerBtn.type = 'button';
    triggerBtn.className = 'unified-date-btn';
    triggerBtn.setAttribute('aria-label', '选择日期');
    triggerBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>';

    const syncState = () => {
        const v = (dateInput.value || '').trim();
        display.value = v;
        display.placeholder = 'YYYY-MM-DD';
        display.disabled = !!dateInput.disabled;
        triggerBtn.disabled = !!dateInput.disabled;
    };

    const openPicker = (e) => {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        if (dateInput.disabled || dateInput.readOnly) return;
        dateInput.focus({ preventScroll: true });
        if (typeof dateInput.showPicker === 'function') {
            try {
                dateInput.showPicker();
                return;
            } catch (_) {}
        }
        try { dateInput.click(); } catch (_) {}
    };

    dateInput.classList.add('unified-date-native');
    dateInput.dataset.unifiedDateEnhanced = '1';

    // Patch instance-level value setter so `input.value = 'YYYY-MM-DD'` can sync display.
    if (!dateInput.dataset.unifiedDateValuePatched) {
        const proto = Object.getPrototypeOf(dateInput);
        const valueDesc = Object.getOwnPropertyDescriptor(proto, 'value');
        if (valueDesc && valueDesc.configurable && valueDesc.get && valueDesc.set) {
            Object.defineProperty(dateInput, 'value', {
                get() {
                    return valueDesc.get.call(this);
                },
                set(v) {
                    valueDesc.set.call(this, v);
                    syncState();
                },
                configurable: true
            });
        }
        dateInput.dataset.unifiedDateValuePatched = '1';
    }

    const parent = dateInput.parentNode;
    if (!parent) return null;
    parent.insertBefore(wrapper, dateInput);
    wrapper.appendChild(display);
    wrapper.appendChild(triggerBtn);
    wrapper.appendChild(dateInput);

    dateInput.addEventListener('change', syncState);
    dateInput.addEventListener('input', syncState);
    display.addEventListener('click', openPicker);
    display.addEventListener('mousedown', (e) => e.stopPropagation());
    display.addEventListener('pointerdown', (e) => e.stopPropagation());
    triggerBtn.addEventListener('click', openPicker);
    triggerBtn.addEventListener('mousedown', (e) => e.stopPropagation());
    triggerBtn.addEventListener('pointerdown', (e) => e.stopPropagation());

    syncState();
    return wrapper;
}

function initUnifiedDateInputs(root = document) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('input[type="date"]:not([data-unified-date-enhanced="1"])').forEach((input) => {
        enhanceUnifiedDateInput(input);
    });
}

let unifiedDateObserverInitialized = false;
function observeUnifiedDateInputs() {
    if (unifiedDateObserverInitialized || !document.body || typeof MutationObserver === 'undefined') return;
    unifiedDateObserverInitialized = true;
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((m) => {
            m.addedNodes.forEach((node) => {
                if (!(node instanceof Element)) return;
                if (node.matches && node.matches('input[type="date"]')) {
                    initUnifiedDateInputs(node.parentElement || document);
                    return;
                }
                if (node.querySelectorAll) {
                    initUnifiedDateInputs(node);
                }
            });
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
}

// 通用确认 Modal（Promise 版本，替换 confirm）
let confirmModalResolver = null;
let _confirmModalCleanup = null;  // 用于在外部关闭时也能清理 ESC 监听

function showConfirmModal(message, title = '确认操作', confirmText = '确认', cancelText = '取消', danger = false, options = {}) {
    // 如果上一个 confirmModal 还没关闭，先安全关闭它
    if (typeof _confirmModalCleanup === 'function') {
        _confirmModalCleanup();
    }
    if (typeof confirmModalResolver === 'function') {
        const old = confirmModalResolver;
        confirmModalResolver = null;
        old(false);
    }
    return new Promise((resolve, reject) => {
        const modal = document.getElementById('confirmModal');
        const titleEl = document.getElementById('confirmModalTitle');
        const messageEl = document.getElementById('confirmModalMessage');
        const confirmBtn = document.getElementById('confirmModalConfirmBtn');
        const statusChangeEl = document.getElementById('confirmModalStatusChange');
        const currentStatusEl = document.getElementById('confirmModalCurrentStatus');
        const nextStatusEl = document.getElementById('confirmModalNextStatus');
        const orderInfoEl = document.getElementById('confirmModalOrderInfo');
        const orderNumberEl = document.getElementById('confirmModalOrderNumber');
        
        // 安全輸入確認區
        const inputArea = document.getElementById('confirmModalInputArea');
        const inputHint = document.getElementById('confirmModalInputHint');
        const inputEl = document.getElementById('confirmModalInput');
        const inputError = document.getElementById('confirmModalInputError');
        
        if (!modal) {
            // 如果 modal 不存在，使用 Toast 提示
            if (typeof showToast === 'function') {
                showToast('错误', '确认对话框无法显示，请刷新页面', 'error');
            }
            resolve(false);
            return;
        }
        
        // options.requireInput: 需要輸入的確認文字（例如 "DELETE"）
        const requireInput = options.requireInput || null;
        
        titleEl.textContent = title;
        confirmBtn.textContent = confirmText;
        confirmBtn.className = danger ? 'modal-btn danger' : 'modal-btn confirm';
        
        // 如果有状态转换信息，显示状态转换区域
        if (options.currentStatus && options.nextStatus) {
            const displayCurrent = typeof displayStatus === 'function' ? displayStatus(options.currentStatus) : options.currentStatus;
            const displayNext = typeof displayStatus === 'function' ? displayStatus(options.nextStatus) : options.nextStatus;
            
            if (currentStatusEl) currentStatusEl.textContent = displayCurrent;
            if (nextStatusEl) {
                nextStatusEl.textContent = displayNext;
                nextStatusEl.style.color = danger ? '#dc2626' : '#ff2442';
                nextStatusEl.style.borderColor = danger ? '#fecaca' : '#ffd6dd';
                nextStatusEl.style.background = danger ? '#fef2f2' : '#fff5f7';
            }
            if (statusChangeEl) statusChangeEl.style.display = 'flex';
            
            // 隐藏普通消息（因为状态转换区域已经显示了信息）
            if (messageEl) messageEl.style.display = 'none';
        } else {
            // 没有状态转换信息，显示普通消息
            if (statusChangeEl) statusChangeEl.style.display = 'none';
            if (messageEl) {
                messageEl.textContent = message;
                messageEl.style.display = 'block';
            }
        }
        
        // 如果有订单号，显示订单信息
        if (options.orderNumber) {
            if (orderNumberEl) orderNumberEl.textContent = options.orderNumber;
            if (orderInfoEl) orderInfoEl.style.display = 'block';
        } else {
            if (orderInfoEl) orderInfoEl.style.display = 'none';
        }
        
        // 處理安全輸入確認
        if (requireInput && inputArea && inputEl) {
            inputArea.style.display = 'block';
            if (inputHint) inputHint.textContent = `请输入「${requireInput}」以确认操作`;
            inputEl.value = '';
            inputEl.placeholder = requireInput;
            inputEl.style.borderColor = '';
            if (inputError) inputError.style.display = 'none';
        } else if (inputArea) {
            inputArea.style.display = 'none';
        }
        
        // 清除旧的事件监听器
        const newConfirmBtn = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
        
        // 如果需要輸入確認，初始禁用按鈕
        if (requireInput) {
            newConfirmBtn.disabled = true;
        }
        
        // 注册当前 resolver，供 closeConfirmModal 使用
        confirmModalResolver = resolve;
        
        // 輸入監聽：輸入正確時啟用確認按鈕
        let inputHandler = null;
        if (requireInput && inputEl) {
            inputHandler = () => {
                const val = inputEl.value.trim().toUpperCase();
                const match = val === requireInput.toUpperCase();
                newConfirmBtn.disabled = !match;
                // 輸入時更新邊框顏色
                if (val.length > 0) {
                    inputEl.style.borderColor = match ? '#10b981' : '#f59e0b';
                } else {
                    inputEl.style.borderColor = '';
                }
                if (inputError) inputError.style.display = 'none';
            };
            inputEl.addEventListener('input', inputHandler);
        }
        
        // 清理函數
        const cleanup = () => {
            if (inputHandler && inputEl) {
                inputEl.removeEventListener('input', inputHandler);
            }
            if (inputArea) inputArea.style.display = 'none';
            if (inputEl) inputEl.value = '';
            document.removeEventListener('keydown', handleEsc);
            _confirmModalCleanup = null;
        };
        _confirmModalCleanup = cleanup;  // 暴露给 closeConfirmModal 使用

        // 确认按钮
        newConfirmBtn.onclick = () => {
            // 如果需要輸入確認，再次驗證
            if (requireInput && inputEl) {
                if (inputEl.value.trim().toUpperCase() !== requireInput.toUpperCase()) {
                    inputEl.style.borderColor = '#ef4444';
                    if (inputError) inputError.style.display = 'block';
                    inputEl.focus();
                    return;
                }
            }
            cleanup();
            modal.classList.remove('show');
            confirmModalResolver = null;
            resolve(true);
        };
        
        // 显示 modal
        modal.classList.add('show');
        
        // 如果有輸入框，自動聚焦
        if (requireInput && inputEl) {
            setTimeout(() => inputEl.focus(), 100);
        }
        
        // ESC 键关闭
        const handleEsc = (e) => {
            if (e.key === 'Escape') {
                cleanup();
                modal.classList.remove('show');
                confirmModalResolver = null;
                resolve(false);
            }
        };
        document.addEventListener('keydown', handleEsc);
    });
}

// 通用提示 Modal（Promise 版本，替换 alert）
function showAlertModal(message, title = '提示', confirmText = '确定', type = 'info') {
    return new Promise((resolve) => {
        const modal = document.getElementById('alertModal');
        const titleEl = document.getElementById('alertModalTitle');
        const messageEl = document.getElementById('alertModalMessage');
        const confirmBtn = document.getElementById('alertModalConfirmBtn');
        
        if (!modal) {
            // 如果 modal 不存在，使用 Toast 提示
            if (typeof showToast === 'function') {
                showToast(title, message, type === 'error' || type === 'danger' ? 'error' : 'info');
            }
            resolve();
            return;
        }
        
        titleEl.textContent = title;
        messageEl.textContent = message;
        confirmBtn.textContent = confirmText;
        
        // 根据类型设置按钮样式
        if (type === 'error' || type === 'danger') {
            confirmBtn.className = 'modal-btn danger';
        } else if (type === 'warning') {
            confirmBtn.className = 'modal-btn warning';
        } else {
            confirmBtn.className = 'modal-btn confirm';
        }
        
        // 清除旧的事件监听器
        const newConfirmBtn = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
        
        // ESC 键关闭（先声明，以便 confirm 按钮也能清理）
        const handleEsc = (e) => {
            if (e.key === 'Escape') {
                modal.classList.remove('show');
                document.removeEventListener('keydown', handleEsc);
                resolve();
            }
        };

        // 确认按钮
        newConfirmBtn.onclick = () => {
            modal.classList.remove('show');
            document.removeEventListener('keydown', handleEsc);
            resolve();
        };
        
        // 显示 modal
        modal.classList.add('show');
        document.addEventListener('keydown', handleEsc);
    });
}

// 关闭确认 Modal
function closeConfirmModal() {
    const modal = document.getElementById('confirmModal');
    if (modal) {
        modal.classList.remove('show');
    }
    // 调用完整清理（移除 ESC 监听 + 輸入確認區）
    if (typeof _confirmModalCleanup === 'function') {
        _confirmModalCleanup();
    } else {
        // 后备清理
        const inputArea = document.getElementById('confirmModalInputArea');
        const inputEl = document.getElementById('confirmModalInput');
        if (inputArea) inputArea.style.display = 'none';
        if (inputEl) inputEl.value = '';
    }
    
    if (typeof confirmModalResolver === 'function') {
        const resolver = confirmModalResolver;
        confirmModalResolver = null;
        resolver(false);
    }
}

// 关闭提示 Modal
function closeAlertModal() {
    const modal = document.getElementById('alertModal');
    if (modal) {
        modal.classList.remove('show');
    }
}

// 输入提示 Modal（Promise 版本，替换 prompt）
function showPromptModal(message, title = '输入', defaultValue = '', placeholder = '') {
    return new Promise((resolve) => {
        const modal = document.getElementById('promptModal');
        const titleEl = document.getElementById('promptModalTitle');
        const messageEl = document.getElementById('promptModalMessage');
        const inputEl = document.getElementById('promptModalInput');
        const confirmBtn = document.getElementById('promptModalConfirmBtn');
        
        if (!modal) {
            // 如果 modal 不存在，使用 Toast 提示
            if (typeof showToast === 'function') {
                showToast('错误', '输入对话框无法显示，请刷新页面', 'error');
            }
            resolve(null);
            return;
        }
        
        titleEl.textContent = title;
        messageEl.textContent = message;
        inputEl.value = defaultValue;
        inputEl.placeholder = placeholder;
        
        // 清除旧的事件监听器
        const newConfirmBtn = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
        
        // 统一清理函数
        const cleanupAll = () => {
            inputEl.removeEventListener('keydown', handleEnter);
            document.removeEventListener('keydown', handleEsc);
        };

        // Enter 键确认
        const handleEnter = (e) => {
            if (e.key === 'Enter') {
                const value = inputEl.value.trim();
                modal.classList.remove('show');
                cleanupAll();
                resolve(value || null);
            }
        };

        // ESC 键关闭
        const handleEsc = (e) => {
            if (e.key === 'Escape') {
                modal.classList.remove('show');
                cleanupAll();
                resolve(null);
            }
        };
        
        // 确认按钮
        newConfirmBtn.onclick = () => {
            const value = inputEl.value.trim();
            modal.classList.remove('show');
            cleanupAll();
            resolve(value || null);
        };
        
        inputEl.addEventListener('keydown', handleEnter);
        
        // 显示 modal 并聚焦输入框
        modal.classList.add('show');
        setTimeout(() => inputEl.focus(), 100);
        
        document.addEventListener('keydown', handleEsc);
    });
}

// 关闭输入提示 Modal
function closePromptModal() {
    const modal = document.getElementById('promptModal');
    if (modal) {
        modal.classList.remove('show');
    }
}

// 確認對話框（保留兼容性，但使用新的 modal）
function confirmDialog(message, callback) {
    showConfirmModal(message).then(confirmed => {
        if (confirmed && callback) {
        callback();
    }
    });
}

// ==================== 客户订单报告 ====================
function getCustomerReportRows() {
    if (typeof applyFilters === 'function') applyFilters();
    if (homeDataReady && !isGlobalSearchMode) return homeFilteredOrdersData.slice();
    return (lastFilteredRowsForExport || []).slice();
}

function buildCustomerReportSelection(rows) {
    const seen = new Set();
    return (rows || []).map(item => {
        if (item && item.dataset) {
            return {workflow_number:(item.dataset.workflowNumber||'').trim(), order_number:(item.dataset.orderNumber||'').trim(), customer_name:(item.dataset.customerName||'').trim()};
        }
        return {workflow_number:String(item.workflow_number||item.workflowNumber||'').trim(), order_number:String(item.order_number||item.orderNumber||'').trim(), customer_name:String(item.customer_name||'').trim()};
    }).filter(item => {
        const key = item.workflow_number ? `w:${item.workflow_number}` : `o:${item.order_number}`;
        if (!item.workflow_number && !item.order_number) return false;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function getCustomerReportCustomerNames(selection = customerReportSelection) {
    const seen = new Set();
    const names = [];
    (selection || []).forEach(item => {
        const name = String(item && item.customer_name || '').trim();
        if (!name) return;
        const key = name.toLocaleUpperCase();
        if (seen.has(key)) return;
        seen.add(key);
        names.push(name);
    });
    return names;
}

function customerReportTooManyCustomers() {
    return getCustomerReportCustomerNames().length > CUSTOMER_REPORT_MAX_CUSTOMERS;
}

function showCustomerReportCustomerLimit() {
    const customers = getCustomerReportCustomerNames();
    const blocked = customers.length > CUSTOMER_REPORT_MAX_CUSTOMERS;
    const warning = document.getElementById('customerReportWarning');
    const warningText = document.getElementById('customerReportWarningText');
    const button = document.getElementById('customerReportGenerateBtn');
    const textEl = document.getElementById('customerReportGenerateText');
    if (blocked) {
        if (warning) {
            warning.style.display = 'flex';
            warning.classList.add('customer-report-limit-warning');
        }
        if (warningText) {
            warningText.textContent = `一次最多只能生成 ${CUSTOMER_REPORT_MAX_CUSTOMERS} 个客户的订单报告；目前筛选到 ${customers.length} 个客户。请先用客户/业务员/状态筛选缩小范围。`;
        }
        if (button) {
            button.disabled = true;
            button.classList.add('customer-report-limit-blocked');
            button.title = `一次最多 ${CUSTOMER_REPORT_MAX_CUSTOMERS} 个客户`;
        }
        if (textEl) textEl.textContent = `最多 ${CUSTOMER_REPORT_MAX_CUSTOMERS} 个客户`;
    } else {
        if (warning) warning.classList.remove('customer-report-limit-warning');
        if (button) {
            button.classList.remove('customer-report-limit-blocked');
            button.removeAttribute('title');
        }
    }
    return blocked;
}

// ==================== 首页客户名称 / 订单搜索建议 ====================
function getFrontEndSearchSuggestions(rawValue) {
    const keyword = String(rawValue || '').trim().toLocaleLowerCase();
    if (!keyword) return [];

    const customers = new Map();
    const orders = new Map();
    const suggestionSource = (homeDataReady && homeOrdersData.length)
        ? homeOrdersData.map(item => ({
            customerName: String(item.customer_name || '').trim(),
            orderNumber: String(item.order_number || '').trim(),
            workflowNumber: String(item.workflow_number || '').trim()
        }))
        : Array.from(document.querySelectorAll('#ordersTableBody tr[data-order-number]')).map(row => ({
            customerName: String(row.dataset.customerName || '').trim(),
            orderNumber: String(row.dataset.orderNumber || '').trim(),
            workflowNumber: String(row.dataset.workflowNumber || '').trim()
        }));
    suggestionSource.forEach(source => {
        const customerName = source.customerName;
        const orderNumber = source.orderNumber;
        const workflowNumber = source.workflowNumber;

        if (customerName && customerName !== '-') {
            const lower = customerName.toLocaleLowerCase();
            const index = lower.indexOf(keyword);
            if (index >= 0) {
                const key = lower;
                if (!customers.has(key)) customers.set(key, { type: 'customer', value: customerName, label: customerName, index });
            }
        }

        // 订单号建议：输入数字/订单片段时才会自然出现，不混入业务员名称。
        [workflowNumber, orderNumber].filter(Boolean).forEach(number => {
            const lower = number.toLocaleLowerCase();
            const index = lower.indexOf(keyword);
            if (index >= 0 && !orders.has(lower)) {
                orders.set(lower, {
                    type: 'order',
                    value: number,
                    label: customerName && customerName !== '-' ? `${number} · ${customerName}` : number,
                    index
                });
            }
        });
    });

    const sortMatches = (items) => items.sort((a, b) => {
        const aStarts = a.index === 0 ? 0 : 1;
        const bStarts = b.index === 0 ? 0 : 1;
        if (aStarts !== bStarts) return aStarts - bStarts;
        if (a.index !== b.index) return a.index - b.index;
        return a.label.localeCompare(b.label);
    });

    // 客户名称优先；如果输入能命中订单号，再补订单建议。完全不显示业务员。
    return [...sortMatches(Array.from(customers.values())), ...sortMatches(Array.from(orders.values()))].slice(0, 10);
}

function hideCustomerSearchSuggestions() {
    const box = document.getElementById('customerSearchSuggestions');
    if (!box) return;
    box.innerHTML = '';
    box.classList.remove('show');
}

function updateCustomerSearchSuggestions(rawValue) {
    const box = document.getElementById('customerSearchSuggestions');
    if (!box) return;
    const matches = getFrontEndSearchSuggestions(rawValue);

    box.innerHTML = '';
    if (!matches.length) {
        box.classList.remove('show');
        return;
    }

    matches.forEach(item => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'customer-search-suggestion';
        button.setAttribute('role', 'option');
        if (item.type === 'customer') {
            button.innerHTML = `<span class="customer-search-suggestion-name"></span>`;
        } else {
            button.innerHTML = `<span class="customer-search-suggestion-name"></span>`;
        }
        button.querySelector('.customer-search-suggestion-name').textContent = item.label;
        button.addEventListener('mousedown', event => {
            event.preventDefault();
            event.stopPropagation();
            if (item.type === 'customer') selectCustomerSearchSuggestion(item.value);
            else selectOrderSearchSuggestion(item.value);
        });
        box.appendChild(button);
    });
    box.classList.add('show');
}

function restoreHomeRowsFromGlobalSearchIfNeeded() {
    if (typeof isGlobalSearchMode !== 'undefined' && isGlobalSearchMode) {
        isGlobalSearchMode = false;
        originalOrders = null;
        if (homeDataReady) applyFilters();
    }
}

function selectCustomerSearchSuggestion(customerName) {
    const input = document.getElementById('searchInput');
    if (!input) return;
    restoreHomeRowsFromGlobalSearchIfNeeded();

    input.value = customerName;
    selectedCustomerNameFilter = customerName;
    selectedOrderNumberFilter = '';
    currentFilter.search = customerName;
    const clearBtn = document.getElementById('searchClearBtn');
    if (clearBtn) {
        clearBtn.style.opacity = '1';
        clearBtn.style.pointerEvents = 'auto';
    }
    hideCustomerSearchSuggestions();
    applyFilters();
    if (typeof saveFilterState === 'function') saveFilterState();
}

function selectOrderSearchSuggestion(orderNumber) {
    const input = document.getElementById('searchInput');
    if (!input) return;
    restoreHomeRowsFromGlobalSearchIfNeeded();

    input.value = orderNumber;
    selectedCustomerNameFilter = '';
    selectedOrderNumberFilter = orderNumber;
    currentFilter.search = orderNumber;
    const clearBtn = document.getElementById('searchClearBtn');
    if (clearBtn) {
        clearBtn.style.opacity = '1';
        clearBtn.style.pointerEvents = 'auto';
    }
    hideCustomerSearchSuggestions();
    applyFilters();
    if (typeof saveFilterState === 'function') saveFilterState();
}

function openCustomerReportModal(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    // 记录打开时间，防止打开 Modal 的同一次鼠标/触控动作误触底部“产生”按钮。
    customerReportModalOpenedAt = Date.now();
    resetCustomerReportGenerateState();
    const rows = getCustomerReportRows();
    customerReportSelection = buildCustomerReportSelection(rows);
    if (customerReportSelection.length === 0) {
        showToast('提示', '目前筛选结果没有可导出的订单', 'info');
        return;
    }

    const customers = getCustomerReportCustomerNames();
    const summary = document.getElementById('customerReportSummary');
    if (summary) {
        const customerText = customers.length === 1
            ? customers[0]
            : (customers.length > 1 ? `${customers.length} 个客户` : '未指定客户');
        summary.textContent = `已选取 ${customerReportSelection.length} 笔订单 · ${customerText}`;
    }

    // 恢复使用者上一次的汇出设定；第一次使用才采用默认值。
    customerReportOptions = loadCustomerReportPreferences();
    const source = document.getElementById('customerReportImageSource');
    if (source) source.value = customerReportOptions.image_source;
    setCustomerReportActive('[data-report-format]', 'data-report-format', customerReportOptions.format);
    setCustomerReportActive('[data-report-language]', 'data-report-language', customerReportOptions.language);
    setCustomerReportActive('[data-report-image-count]', 'data-report-image-count', customerReportOptions.image_count);
    setCustomerReportActive('[data-report-image-order]', 'data-report-image-order', customerReportOptions.image_order);
    setCustomerReportActive('[data-report-pdf-mode]', 'data-report-pdf-mode', customerReportOptions.pdf_attachment_mode);
    const pdfSection = document.getElementById('customerReportPdfAttachmentSection');
    if (pdfSection) pdfSection.style.display = '';
    clearCustomerReportDownloads();
    resetCustomerReportGenerateState();

    const modal = document.getElementById('customerReportModal');
    if (modal) {
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
    }
    if (!showCustomerReportCustomerLimit()) {
        scheduleCustomerReportEstimate(0);
    }
}

function closeCustomerReportModal() {
    if (customerReportEstimateTimer) {
        clearTimeout(customerReportEstimateTimer);
        customerReportEstimateTimer = null;
    }
    const modal = document.getElementById('customerReportModal');
    if (modal) {
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
    }
    // 关闭后恢复按钮，避免上一次异常/中断留下 disabled + “正在产生...”状态。
    if (!customerReportIsGenerating) resetCustomerReportGenerateState();
}

function customerReportBackdropClick(event) {
    if (event && event.target && event.target.id === 'customerReportModal') {
        closeCustomerReportModal();
    }
}

function setCustomerReportActive(selector, attr, value) {
    document.querySelectorAll(selector).forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute(attr) === value);
    });
}

function loadCustomerReportPreferences() {
    const defaults = {
        format: 'pdf',
        language: 'zh_cn',
        image_source: 'both',
        image_count: 'all',
        image_order: 'order_first',
        pdf_attachment_mode: 'pages'
    };
    try {
        const raw = localStorage.getItem('order_tracking_customer_report_preferences_v1');
        if (!raw) return { ...defaults };
        const saved = JSON.parse(raw);
        const allowed = {
            format: ['pdf', 'docx', 'xlsx'],
            language: ['zh_cn', 'es'],
            image_source: ['both', 'order', 'workflow', 'none'],
            image_count: ['representative', 'all'],
            image_order: ['order_first', 'workflow_first', 'newest'],
            pdf_attachment_mode: ['pages', 'skip']
        };
        const result = { ...defaults };
        Object.keys(allowed).forEach(key => {
            if (allowed[key].includes(saved?.[key])) result[key] = saved[key];
        });
        return result;
    } catch (error) {
        console.warn('读取客户报告偏好失败，将使用默认值:', error);
        return { ...defaults };
    }
}

function saveCustomerReportPreferences() {
    try {
        localStorage.setItem(
            'order_tracking_customer_report_preferences_v1',
            JSON.stringify(customerReportOptions)
        );
    } catch (error) {
        console.warn('保存客户报告偏好失败:', error);
    }
}

function selectCustomerReportFormat(value) {
    customerReportOptions.format = value;
    setCustomerReportActive('[data-report-format]', 'data-report-format', value);
    saveCustomerReportPreferences();
    clearCustomerReportDownloads();
    scheduleCustomerReportEstimate();
}

function selectCustomerReportLanguage(value) {
    customerReportOptions.language = value;
    setCustomerReportActive('[data-report-language]', 'data-report-language', value);
    saveCustomerReportPreferences();
    clearCustomerReportDownloads();
    scheduleCustomerReportEstimate();
}

function selectCustomerReportImageCount(value) {
    customerReportOptions.image_count = value;
    setCustomerReportActive('[data-report-image-count]', 'data-report-image-count', value);
    saveCustomerReportPreferences();
    clearCustomerReportDownloads();
    scheduleCustomerReportEstimate();
}

function selectCustomerReportImageOrder(value) {
    if (!['order_first', 'workflow_first', 'newest'].includes(value)) return;
    customerReportOptions.image_order = value;
    setCustomerReportActive('[data-report-image-order]', 'data-report-image-order', value);
    saveCustomerReportPreferences();
    clearCustomerReportDownloads();
    scheduleCustomerReportEstimate();
}

function selectCustomerReportPdfAttachmentMode(value) {
    if (!['pages', 'skip'].includes(value)) return;
    customerReportOptions.pdf_attachment_mode = value;
    setCustomerReportActive('[data-report-pdf-mode]', 'data-report-pdf-mode', value);
    saveCustomerReportPreferences();
    clearCustomerReportDownloads();
    scheduleCustomerReportEstimate();
}

function customerReportOptionChanged() {
    const source = document.getElementById('customerReportImageSource');
    customerReportOptions.image_source = source ? source.value : 'both';
    saveCustomerReportPreferences();
    clearCustomerReportDownloads();
    scheduleCustomerReportEstimate();
}

function customerReportPayload() {
    const source = document.getElementById('customerReportImageSource');
    customerReportOptions.image_source = source ? source.value : customerReportOptions.image_source;
    return {
        items: customerReportSelection.map(x => ({
            workflow_number: x.workflow_number,
            order_number: x.order_number
        })),
        format: customerReportOptions.format,
        language: customerReportOptions.language,
        image_source: customerReportOptions.image_source,
        image_count: customerReportOptions.image_count,
        image_order: customerReportOptions.image_order,
        pdf_attachment_mode: customerReportOptions.pdf_attachment_mode || 'pages'
    };
}

function scheduleCustomerReportEstimate(delay = 250) {
    if (customerReportEstimateTimer) clearTimeout(customerReportEstimateTimer);
    if (customerReportTooManyCustomers()) {
        customerReportEstimateTimer = null;
        showCustomerReportCustomerLimit();
        return;
    }
    customerReportEstimateTimer = setTimeout(updateCustomerReportEstimate, delay);
}

async function updateCustomerReportEstimate() {
    if (!customerReportSelection.length) return;
    if (customerReportTooManyCustomers()) {
        showCustomerReportCustomerLimit();
        return;
    }
    const warning = document.getElementById('customerReportWarning');
    if (isCloudMode()) {
        if (warning) warning.style.display = 'none';
        return;
    }
    const warningText = document.getElementById('customerReportWarningText');
    if (!warning || !warningText) return;

    warning.style.display = 'flex';
    warningText.textContent = '正在预估档案大小...';
    try {
        const response = await fetch('/tracking/api/customer-reports/estimate', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(customerReportPayload())
        });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || '预估失败');

        const mb = (Number(data.estimated_bytes || 0) / 1024 / 1024).toFixed(1);
        const fmtName = customerReportOptions.format === 'pdf' ? 'PDF'
            : customerReportOptions.format === 'docx' ? 'Word' : 'Excel';
        const customerCount = Number(data.customer_count || 1);
        const estimatedFiles = Number(data.estimated_files || data.estimated_parts || 1);
        const pdfAttachmentCount = Number(data.pdf_attachment_count || 0);
        const pdfSection = document.getElementById('customerReportPdfAttachmentSection');
        if (pdfSection) pdfSection.style.display = '';
        const pdfHint = document.getElementById('customerReportPdfAttachmentHint');
        if (pdfHint) {
            pdfHint.textContent = pdfAttachmentCount > 0
                ? `检测到 ${pdfAttachmentCount} 个 PDF 附件；可选择逐页拆图加入，或完全不加入。`
                : '目前未检测到 PDF 附件；此选项会保留，若筛选结果含 PDF 时自动套用。';
        }
        const pdfSuffix = pdfAttachmentCount > 0
            ? (customerReportOptions.pdf_attachment_mode === 'skip'
                ? ` 检测到 ${pdfAttachmentCount} 个 PDF 附件，目前设为不加入。`
                : ` 检测到 ${pdfAttachmentCount} 个 PDF 附件，生成时会逐页拆成图片加入。`)
            : '';

        if (customerReportOptions.format === 'pdf' && customerCount > 1) {
            warning.style.display = 'flex';
            if (estimatedFiles > customerCount) {
                warningText.textContent = `已筛选 ${customerCount} 个客户，将按客户分开产生约 ${estimatedFiles} 份${fmtName}；预估总大小约 ${mb} MB。${pdfSuffix}`;
            } else {
                warningText.textContent = `已筛选 ${customerCount} 个客户，将分别产生 ${customerCount} 份${fmtName}；预估总大小约 ${mb} MB。${pdfSuffix}`;
            }
        } else if (customerReportOptions.format !== 'xlsx' && estimatedFiles > 1) {
            warning.style.display = 'flex';
            warningText.textContent = `预估约 ${mb} MB，超过单档 50 MB 才会自动拆分，目前预计 ${estimatedFiles} 份 ${fmtName}。${pdfSuffix}`;
        } else if (Number(data.image_count || 0) > 0) {
            warning.style.display = 'flex';
            warningText.textContent = `预估约 ${mb} MB，包含 ${data.image_count} 张图片。${fmtName === 'Excel' ? 'Excel 会维持单一档案。' : ''}${pdfSuffix}`;
        } else if (pdfSuffix) {
            warning.style.display = 'flex';
            warningText.textContent = pdfSuffix.trim();
        } else {
            warning.style.display = 'none';
        }
    } catch (error) {
        // 预估只是辅助提示；失败不能阻止真正导出。
        warning.style.display = 'none';
        console.warn('Customer report estimate failed:', error);
    }
}

function clearCustomerReportDownloads() {
    const box = document.getElementById('customerReportDownloadLinks');
    if (box) {
        box.innerHTML = '';
        box.style.display = 'none';
    }
}

function formatCustomerReportBytes(bytes) {
    const n = Number(bytes || 0);
    if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function isCustomerReportPdf(file) {
    return !!(file && String(file.name || '').toLowerCase().endsWith('.pdf'));
}


function customerReportOpenLabel(file) {
    if (isCustomerReportPdf(file)) return window.getTrackingLanguage?.() === 'es' ? 'Abrir PDF' : '打开 PDF';
    return file?.name || (window.getTrackingLanguage?.() === 'es' ? 'Descargar' : '下载');
}

function customerReportInlineUrl(file) {
    const url = String(file && file.url || '');
    if (!url) return '#';
    return `${url}${url.includes('?') ? '&' : '?'}inline=1`;
}

function renderCustomerReportDownloadLinks(files) {
    const box = document.getElementById('customerReportDownloadLinks');
    if (!box) return;
    box.innerHTML = '';
    const title = document.createElement('strong');
    title.textContent = files.length > 1
        ? `已产生 ${files.length} 个档案（若浏览器未自动下载，请点下面档名）`
        : '报告已产生（若浏览器未自动下载，请点下面档名）';
    box.appendChild(title);
    files.forEach(file => {
        const row = document.createElement('div');
        row.className = 'customer-report-file-actions';
        const a = document.createElement('a');
        const shouldOpenInline = isCustomerReportPdf(file);
        a.href = shouldOpenInline ? customerReportInlineUrl(file) : file.url;
        a.textContent = shouldOpenInline
            ? `${customerReportOpenLabel(file)} · ${file.name} · ${formatCustomerReportBytes(file.size)}`
            : `${file.name} · ${formatCustomerReportBytes(file.size)}`;
        if (shouldOpenInline) { a.target = '_blank'; a.rel = 'noopener'; }
        else a.setAttribute('download', '');
        row.appendChild(a);
        if (shouldOpenInline) {
            const download = document.createElement('a');
            download.href = file.url;
            download.className = 'customer-report-download-explicit';
            download.textContent = window.getTrackingLanguage?.() === 'es' ? 'Descargar' : '下载';
            download.setAttribute('download', '');
            row.appendChild(download);
        }
        box.appendChild(row);
    });
    box.style.display = 'block';
}

function triggerCustomerReportDownloads(files) {
    files.forEach((file, index) => {
        setTimeout(() => {
            const a = document.createElement('a');
            a.href = file.url;
            a.setAttribute('download', '');
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }, index * 350);
    });
}

function resetCustomerReportGenerateState() {
    const button = document.getElementById('customerReportGenerateBtn');
    const textEl = document.getElementById('customerReportGenerateText');
    const blocked = customerReportTooManyCustomers();
    if (button) {
        button.disabled = blocked;
        button.classList.toggle('customer-report-limit-blocked', blocked);
        if (blocked) button.setAttribute('title', `请先缩小筛选范围至 ${CUSTOMER_REPORT_MAX_CUSTOMERS} 个客户以内`);
        else button.removeAttribute('title');
    }
    if (textEl) textEl.textContent = '加入生成队列';
}

async function generateCustomerReport(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    if (Date.now() - customerReportModalOpenedAt < 500) return;
    if (customerReportIsGenerating) return;
    if (!customerReportSelection.length) {
        showToast('提示', '目前筛选结果没有可导出的订单', 'info');
        return;
    }
    if (customerReportTooManyCustomers()) {
        showCustomerReportCustomerLimit();
        showToast('客户过多', `一次最多只能生成 ${CUSTOMER_REPORT_MAX_CUSTOMERS} 个客户的订单报告，请先缩小筛选范围。`, 'warning');
        return;
    }
    if (isCloudMode()) {
        showToast('云端报告', 'Render 只读版不会直接执行本机 PDF Worker；等 report_requests 接通后，这里会改为提交报告请求。', 'info');
        return;
    }

    const button = document.getElementById('customerReportGenerateBtn');
    const textEl = document.getElementById('customerReportGenerateText');
    customerReportIsGenerating = true;
    if (button) button.disabled = true;
    if (textEl) textEl.textContent = '正在加入队列...';

    try {
        const response = await fetch('/tracking/api/customer-reports/jobs', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(customerReportPayload())
        });
        let data = null;
        try { data = await response.json(); } catch (_) { data = null; }
        if (!response.ok || !data || !data.success || !data.job) {
            throw new Error((data && data.error) || `加入报告队列失败 (${response.status})`);
        }

        // 生成工作已经交给后端；立即释放前端，让使用者继续处理下一个客户。
        closeCustomerReportModal();
        mergeCustomerReportJob(data.job);
        customerReportQueueFabDismissed = false;
        if (customerReportOptions.format !== 'pdf') customerReportAutoDownloadPending.add(data.job.id);
        renderCustomerReportQueue();
        ensureCustomerReportQueuePolling(true);
        const customers = Array.isArray(data.job.customers) ? data.job.customers.filter(Boolean) : [];
        const who = customers.length === 1 ? customers[0] : `${customers.length || 1} 个客户`;
        if (data.deduplicated) {
            showToast('任务已在队列中', `${who} · 相同报告正在生成，不会重复建立`, 'info');
        } else {
            showToast('已加入报告队列', `${who} · ${data.job.order_count || 0} 笔订单正在后台生成`, 'success');
        }
    } catch (error) {
        console.error('Customer report queue error:', error);
        showToast('错误', error.message || '加入客户报告队列失败', 'error');
    } finally {
        customerReportIsGenerating = false;
        resetCustomerReportGenerateState();
    }
}

// ==================== 客户报告后台队列 ====================
let customerReportJobs = [];
let customerReportQueueTimer = null;
let customerReportQueueInitialLoaded = false;
let customerReportQueueFabDismissed = false;
const customerReportCompletedNotified = new Set();
const customerReportAutoDownloadPending = new Set();

function mergeCustomerReportJob(job) {
    if (!job || !job.id) return;
    const idx = customerReportJobs.findIndex(x => x.id === job.id);
    if (idx >= 0) customerReportJobs[idx] = { ...customerReportJobs[idx], ...job };
    else customerReportJobs.unshift(job);
    customerReportJobs.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
}

function reportQueueStatusText(status) {
    if (status === 'queued') return '等待中';
    if (status === 'processing') return '生成中';
    if (status === 'completed') return '已完成';
    if (status === 'failed') return '失败';
    return '等待中';
}

function reportQueueFormatLabel(job) {
    const fmt = job && job.format === 'docx' ? 'Word' : job && job.format === 'xlsx' ? 'Excel' : 'PDF';
    const lang = job && job.language === 'es' ? 'Español' : '中文';
    return `${fmt} · ${lang}`;
}

function reportQueueCustomerLabel(job) {
    const customers = Array.isArray(job && job.customers) ? job.customers.filter(Boolean) : [];
    if (customers.length === 1) return customers[0];
    if (customers.length > 1) return `${customers[0]} +${customers.length - 1}`;
    return '客户报告';
}

function escapeReportQueueHtml(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderCustomerReportQueue() {
    const list = document.getElementById('reportQueueList');
    const fab = document.getElementById('reportQueueFab');
    const badge = document.getElementById('reportQueueBadge');
    const mobileBadge = document.getElementById('mobileReportQueueBadge');
    const fabStatus = document.getElementById('reportQueueFabStatus');
    if (!list || !fab) return;

    const active = customerReportJobs.filter(j => j.status === 'queued' || j.status === 'processing');
    const completed = customerReportJobs.filter(j => j.status === 'completed');
    if (customerReportJobs.length && !customerReportQueueFabDismissed) fab.classList.add('show');
    else fab.classList.remove('show');

    if (badge) {
        badge.textContent = String(active.length || completed.length || 0);
        badge.classList.toggle('done', active.length === 0 && completed.length > 0);
    }
    if (mobileBadge) {
        const count = active.length || completed.length || 0;
        mobileBadge.textContent = String(count);
        mobileBadge.style.display = count ? 'inline-flex' : 'none';
        mobileBadge.classList.toggle('done', active.length === 0 && completed.length > 0);
    }
    if (fabStatus) {
        fabStatus.textContent = active.length
            ? `${active.length} 个任务处理中`
            : (completed.length ? `${completed.length} 个报告可下载` : '准备就绪');
    }

    if (!customerReportJobs.length) {
        list.innerHTML = '<div class="report-queue-empty"><strong>目前没有报告任务</strong><span>从首页筛选客户后，点击客户报告即可加入后台队列。</span></div>';
        return;
    }

    list.innerHTML = customerReportJobs.slice(0, 20).map(job => {
        const status = escapeReportQueueHtml(reportQueueStatusText(job.status));
        const customer = escapeReportQueueHtml(reportQueueCustomerLabel(job));
        const meta = escapeReportQueueHtml(`${reportQueueFormatLabel(job)} · ${job.order_count || 0} 笔订单`);
        const statusClass = escapeReportQueueHtml(job.status || 'queued');
        let body = '';
        if (job.status === 'completed' && Array.isArray(job.files) && job.files.length) {
            body = `<div class="report-queue-files">${job.files.map(file => {
                const isPdf = isCustomerReportPdf(file);
                const openInline = isPdf;
                const mainUrl = openInline ? customerReportInlineUrl(file) : (file.url || '#');
                const mainAttrs = openInline ? 'target="_blank" rel="noopener"' : 'download';
                const mainLabel = openInline ? customerReportOpenLabel(file) : (file.name || '下载报告');
                const downloadLink = openInline ? `<a class="report-queue-download-only" href="${escapeReportQueueHtml(file.url || '#')}" download>${window.getTrackingLanguage?.() === 'es' ? 'Descargar' : '下载'}</a>` : '';
                const mobileShareLink = (openInline && isMobileOrderViewport())
                    ? `<button type="button" class="report-queue-mobile-share" onclick="mobileShareQueuedReport('${escapeReportQueueHtml(job.id || '')}', ${job.files.indexOf(file)})">${window.getTrackingLanguage?.() === 'es' ? 'Compartir' : '分享'}</button>`
                    : '';
                return `<div class="report-queue-file-row"><a href="${escapeReportQueueHtml(mainUrl)}" ${mainAttrs}><span>${escapeReportQueueHtml(mainLabel)} · ${escapeReportQueueHtml(file.name || '')}</span><small>${formatCustomerReportBytes(file.size || 0)}</small><svg viewBox="0 0 24 24"><path d="M8 5h11v11"></path><path d="M19 5 9 15"></path><path d="M5 9v10h10"></path></svg></a>${mobileShareLink}${downloadLink}</div>`;
            }).join('')}</div>`;
        } else if (job.status === 'failed') {
            body = `<div class="report-queue-error">${escapeReportQueueHtml(job.error || '报告生成失败')}</div>`;
        } else {
            body = `<div class="report-queue-progress"><span></span></div>`;
        }
        return `<article class="report-queue-card ${statusClass}">
            <div class="report-queue-card-top">
                <div class="report-queue-card-title"><strong>${customer}</strong><span>${meta}</span></div>
                <span class="report-queue-status ${statusClass}">${status}</span>
            </div>
            ${body}
        </article>`;
    }).join('');
}

async function refreshCustomerReportQueue() {
    try {
        const previous = new Map(customerReportJobs.map(j => [j.id, j.status]));
        const response = await fetch('/tracking/api/customer-reports/jobs', { credentials: 'same-origin' });
        const data = await response.json();
        if (!response.ok || !data || !data.success) return;
        customerReportJobs = Array.isArray(data.jobs) ? data.jobs : [];
        renderCustomerReportQueue();

        if (customerReportQueueInitialLoaded) {
            customerReportJobs.forEach(job => {
                const was = previous.get(job.id);
                if (job.status === 'completed' && was && was !== 'completed' && !customerReportCompletedNotified.has(job.id)) {
                    customerReportCompletedNotified.add(job.id);
                    const shouldAutoDownload = customerReportAutoDownloadPending.has(job.id);
                    if (shouldAutoDownload) {
                        customerReportAutoDownloadPending.delete(job.id);
                        const files = Array.isArray(job.files) ? job.files.filter(file => file && file.url) : [];
                        if (files.length) triggerCustomerReportDownloads(files);
                    }
                    const hasPdf = Array.isArray(job.files) && job.files.some(isCustomerReportPdf);
                    showToast('报告已完成', shouldAutoDownload
                        ? `${reportQueueCustomerLabel(job)} 已生成，正在自动下载`
                        : (hasPdf ? `${reportQueueCustomerLabel(job)} PDF 已生成，可直接在报告队列打开预览` : `${reportQueueCustomerLabel(job)} 已生成，可以从报告队列下载`), 'success');
                } else if (job.status === 'failed' && was && was !== 'failed' && !customerReportCompletedNotified.has(job.id)) {
                    customerReportCompletedNotified.add(job.id);
                    showToast('报告生成失败', `${reportQueueCustomerLabel(job)}：${job.error || '请重试'}`, 'error');
                }
            });
        } else {
            customerReportQueueInitialLoaded = true;
            customerReportJobs.filter(j => j.status === 'completed' || j.status === 'failed').forEach(j => customerReportCompletedNotified.add(j.id));
        }

        const hasActive = customerReportJobs.some(j => j.status === 'queued' || j.status === 'processing');
        if (!hasActive && customerReportQueueTimer) {
            clearTimeout(customerReportQueueTimer);
            customerReportQueueTimer = null;
        }
        if (hasActive) ensureCustomerReportQueuePolling();
    } catch (error) {
        console.warn('Report queue refresh failed:', error);
    }
}

function ensureCustomerReportQueuePolling(immediate = false) {
    if (customerReportQueueTimer) clearTimeout(customerReportQueueTimer);
    const run = async () => {
        customerReportQueueTimer = null;
        await refreshCustomerReportQueue();
        if (customerReportJobs.some(j => j.status === 'queued' || j.status === 'processing')) {
            customerReportQueueTimer = setTimeout(run, 1600);
        }
    };
    if (immediate) run();
    else customerReportQueueTimer = setTimeout(run, 1600);
}

function closeReportQueueFab(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    customerReportQueueFabDismissed = true;
    const fab = document.getElementById('reportQueueFab');
    if (fab) fab.classList.remove('show');
}

function openReportQueueDrawer() {
    const drawer = document.getElementById('reportQueueDrawer');
    const backdrop = document.getElementById('reportQueueBackdrop');
    if (drawer) {
        drawer.classList.add('show');
        drawer.setAttribute('aria-hidden', 'false');
    }
    if (backdrop) backdrop.classList.add('show');
    refreshCustomerReportQueue();
}

function closeReportQueueDrawer() {
    const drawer = document.getElementById('reportQueueDrawer');
    const backdrop = document.getElementById('reportQueueBackdrop');
    if (drawer) {
        drawer.classList.remove('show');
        drawer.setAttribute('aria-hidden', 'true');
    }
    if (backdrop) backdrop.classList.remove('show');
}

// 页面进入时只做一次轻量查询；若服务器仍有未完成任务，自动继续轮询。
setTimeout(() => refreshCustomerReportQueue(), 900);

// Modal 键盘关闭
if (!window.__customerReportEscBound) {
    window.__customerReportEscBound = true;
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            const modal = document.getElementById('customerReportModal');
            if (modal && modal.classList.contains('show')) closeCustomerReportModal();
        }
    });
}

// 原内部 Excel 导出（恢复原按钮行为；客户报告使用独立按钮）
function exportData() {
    if (homeDataReady && !isGlobalSearchMode) applyFilters();
    const sourceRows = (homeDataReady && !isGlobalSearchMode) ? homeFilteredOrdersData : (lastFilteredRowsForExport || []);
    const selected = buildCustomerReportSelection(sourceRows);
    showToast('提示', `正在生成 Excel（${selected.length || '当前'} 笔）`, 'info');
    fetch('/tracking/api/workflows/export', {
        method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({selected_items:selected})
    }).then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || '导出失败'); }).catch(() => { throw new Error(`导出失败 (${response.status})`); });
        let filename = '';
        const disposition = response.headers.get('Content-Disposition');
        if (disposition) {
            const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
            if (utf8Match) filename = decodeURIComponent(utf8Match[1]);
            else { const match = disposition.match(/filename=\"?([^\";\n]+)\"?/i); if (match) filename = decodeURIComponent(match[1]); }
        }
        if (!filename) filename = `流程数据导出_${new Date().toISOString().replace(/[-:T]/g,'').slice(0,15)}.xlsx`;
        return response.blob().then(blob => ({blob,filename}));
    }).then(({blob,filename}) => {
        const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=filename; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
        showToast('成功','Excel 已下载','success');
    }).catch(error => { console.error('Export error:',error); showToast('错误',error.message || '导出失败，请稍后重试','error'); });
}

// 初始化：通用表单验证 & Alert 自动关闭
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 300);
        }, 5000);
    });
    
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const requiredInputs = form.querySelectorAll('[required]');
            let isValid = true;
            
            requiredInputs.forEach(input => {
                if (!input.value.trim()) {
                    isValid = false;
                    input.style.borderColor = 'var(--status-danger)';
                } else {
                    input.style.borderColor = '';
                }
            });
            
            if (!isValid) {
                e.preventDefault();
                showToast('错误', '请填写所有必填项');
            }
        });
    });
});

// 摺疊 / 展開側邊欄（主頁等共用）
function openSettings() {
    const modal = document.getElementById('settingsModal');
    if (!modal) {
        console.error('Settings modal not found');
        return;
    }

    // 栏位显示功能只在首页（有表格）时可用，admin-orders 页面隐藏该区块
    const columnsSection = document.getElementById('settingsColumns');
    const columnsMenuItem = document.querySelector('.settings-menu-item[onclick*="columns"]');
    if (isAdminOrdersPage()) {
        if (columnsSection) columnsSection.style.display = 'none';
        if (columnsMenuItem) columnsMenuItem.style.display = 'none';
        // 自动选中第一个可见的 menu item
        const firstVisible = document.querySelector('.settings-menu-item:not([style*="display: none"])');
        if (firstVisible) {
            firstVisible.click();
        }
    } else {
        if (columnsSection) columnsSection.style.display = '';
        if (columnsMenuItem) columnsMenuItem.style.display = '';
        // 檢測表格欄位
        detectTableColumns();
        // 載入已保存的設定
        loadColumnSettings();
    }
    
    // 顯示 modal
    modal.classList.add('show');
}

function closeSettingsModal(force) {
    const modal = document.getElementById('settingsModal');
    if (!modal) return;

    // 如果密码表单有内容且不是强制关闭，先确认
    if (!force) {
        const oldPwd = document.getElementById('cpOldPassword');
        const newPwd = document.getElementById('cpNewPassword');
        const confirmPwd = document.getElementById('cpConfirmPassword');
        const hasInput = (oldPwd && oldPwd.value.trim()) ||
                         (newPwd && newPwd.value.trim()) ||
                         (confirmPwd && confirmPwd.value.trim());
        if (hasInput) {
            // 使用 setTimeout 避免同步关闭
            showConfirmModal('密码尚未保存，确定要关闭吗？', '未保存的更改', '确定关闭', '继续编辑', true)
                .then(confirmed => {
                    if (confirmed) {
                        // 重置表单
                        const form = document.getElementById('changePasswordForm');
                        if (form) form.reset();
                        const errEl = document.getElementById('cpErrorMsg');
                        const successEl = document.getElementById('cpSuccessMsg');
                        if (errEl) errEl.style.display = 'none';
                        if (successEl) successEl.style.display = 'none';
                        modal.classList.remove('show');
                    }
                });
            return;
        }
    }

    modal.classList.remove('show');
}

// 首頁欄位權限只信任後端已渲染到 body 的權限結果。
// 不再由 JS 自己重新判斷角色，避免主管 / 業務員表頭與資料列欄位數不同步。
function homeCanViewUserColumns() {
    return !!(document.body && document.body.dataset.canViewUser === 'true');
}

function getTableColumnSettingsStorageKey() {
    return homeCanViewUserColumns()
        ? 'tableColumnSettings:manager'
        : 'tableColumnSettings:sales';
}

function readTableColumnSettings() {
    const storageKey = getTableColumnSettingsStorageKey();
    const raw = localStorage.getItem(storageKey);
    if (raw) {
        try {
            return JSON.parse(raw) || {};
        } catch (e) {
            console.error('Failed to parse saved settings:', e);
        }
    }

    // 舊版共用 tableColumnSettings 可能帶有錯誤 index。
    // 只遷移具有語義 key 的可見性，不遷移 col_13 / col_15 這種角色相依 index。
    const legacyRaw = localStorage.getItem('tableColumnSettings');
    if (!legacyRaw) return {};
    try {
        const legacy = JSON.parse(legacyRaw) || {};
        const migrated = {};
        Object.keys(legacy).forEach(key => {
            if (!key || /^col_\d+$/.test(key)) return;
            const item = legacy[key];
            if (item && Object.prototype.hasOwnProperty.call(item, 'visible')) {
                migrated[key] = { visible: !!item.visible };
            }
        });
        // 即使沒有可遷移項，也建立角色專用設定，避免每次再讀舊 index。
        localStorage.setItem(storageKey, JSON.stringify(migrated));
        return migrated;
    } catch (e) {
        console.error('Failed to migrate legacy column settings:', e);
        localStorage.setItem(storageKey, '{}');
        return {};
    }
}

function applyColumnVisibilityByKey(table, columnKey, isVisible) {
    if (!table || !columnKey) return;
    table.querySelectorAll(`[data-column-key="${columnKey}"]`).forEach(cell => {
        cell.style.display = isVisible ? '' : 'none';
    });
}

// 檢測表格欄位
function detectTableColumns() {
    if (isAdminOrdersPage()) return;
    const table = document.querySelector('.table-wrapper table');
    if (!table) return;

    const thead = table.querySelector('thead tr');
    if (!thead) return;

    const columns = [];
    const ths = thead.querySelectorAll('th');
    const savedSettings = readTableColumnSettings();

    ths.forEach((th, index) => {
        const text = th.textContent.trim();
        const sortAttr = th.getAttribute('data-sort');
        const columnKey = th.getAttribute('data-column-key') || sortAttr || `col_${index}`;
        const savedSetting = savedSettings[columnKey];
        const isVisible = savedSetting ? savedSetting.visible !== false : true;

        columns.push({
            index,
            key: columnKey,
            label: text || (columnKey === 'expand' ? '展開' : columnKey === 'light' ? '狀態' : `欄位 ${index + 1}`),
            visible: isVisible
        });
    });

    window.tableColumns = columns;
    renderColumnSettings(columns);
}

// 渲染欄位設定選項
function renderColumnSettings(columns) {
    const container = document.getElementById('columnSettingsList');
    if (!container) return;

    container.innerHTML = '';
    columns.forEach(col => {
        const item = document.createElement('div');
        item.className = 'column-setting-item';
        item.innerHTML = `
            <label class="column-toggle">
                <input type="checkbox"
                       data-column-index="${col.index}"
                       data-column-key="${col.key}"
                       ${col.visible ? 'checked' : ''}
                       onchange="toggleColumnVisibility(this)">
                <span class="column-label">${col.label}</span>
            </label>
        `;
        container.appendChild(item);
    });
}

// 切換欄位顯示/隱藏
function toggleColumnVisibility(checkbox) {
    if (isAdminOrdersPage()) return;
    const columnKey = checkbox.getAttribute('data-column-key');
    const isVisible = checkbox.checked;
    const table = document.querySelector('.table-wrapper table');
    if (!table || !columnKey) return;

    applyColumnVisibilityByKey(table, columnKey, isVisible);
    saveColumnSettings();
}

// 顯示設定區塊
function showSettingsSection(section) {
    // 移除所有 active 類
    document.querySelectorAll('.settings-section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.settings-menu-item').forEach(m => m.classList.remove('active'));
    
    // 添加 active 類到对应 section
    const sectionEl = document.getElementById(`settings${section.charAt(0).toUpperCase() + section.slice(1)}`);
    if (sectionEl) {
        sectionEl.classList.add('active');
    }
    
    // 通过 onclick 属性匹配正确的菜单按钮并高亮
    const menuItem = document.querySelector(`.settings-menu-item[onclick*="'${section}'"]`);
    if (menuItem) {
        menuItem.classList.add('active');
    }

    // 切换到密码页时重置表单状态
    if (section === 'password') {
        const form = document.getElementById('changePasswordForm');
        if (form) form.reset();
        const errEl = document.getElementById('cpErrorMsg');
        const successEl = document.getElementById('cpSuccessMsg');
        if (errEl) errEl.style.display = 'none';
        if (successEl) successEl.style.display = 'none';
    }
}

// 保存欄位設定到 localStorage；主管與業務員分開保存，只保存語義 key，不保存 index。
function saveColumnSettings() {
    const settings = {};
    const checkboxes = document.querySelectorAll('#columnSettingsList input[type="checkbox"]');

    checkboxes.forEach(checkbox => {
        const columnKey = checkbox.getAttribute('data-column-key');
        if (!columnKey) return;
        settings[columnKey] = { visible: checkbox.checked };
    });

    localStorage.setItem(getTableColumnSettingsStorageKey(), JSON.stringify(settings));
}

// 載入欄位設定
function loadColumnSettings() {
    if (isAdminOrdersPage()) return;
    const settings = readTableColumnSettings();
    const checkboxes = document.querySelectorAll('#columnSettingsList input[type="checkbox"]');
    const table = document.querySelector('.table-wrapper table');

    checkboxes.forEach(checkbox => {
        const columnKey = checkbox.getAttribute('data-column-key');
        if (settings[columnKey]) {
            checkbox.checked = settings[columnKey].visible !== false;
        }
        if (table && columnKey) {
            applyColumnVisibilityByKey(table, columnKey, checkbox.checked);
        }
    });
}

// 頁面載入 / 動態重繪後應用設定
function applyColumnSettings() {
    if (isAdminOrdersPage()) return;
    const settings = readTableColumnSettings();
    const table = document.querySelector('.table-wrapper table');
    if (!table) return;

    Object.keys(settings).forEach(columnKey => {
        const setting = settings[columnKey];
        applyColumnVisibilityByKey(table, columnKey, setting.visible !== false);
    });
}

function isAdminOrdersPage() {
    return !!document.querySelector('.admin-orders-page');
}

// ==================== 修改密码 ====================

// 防止 ESC 在密码输入框中冒泡关闭 Modal
(function () {
    const sm = document.getElementById('settingsModal');
    if (sm) {
        sm.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                const a = document.activeElement;
                if (a && sm.contains(a) && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA')) {
                    e.stopPropagation();   // 阻止冒泡到全局 ESC 处理器
                    e.stopImmediatePropagation();
                    a.blur();              // 只退出输入框
                }
            }
        });
    }
})();

function submitChangePassword(e) {
    e.preventDefault();
    const oldPwd = document.getElementById('cpOldPassword').value.trim();
    const newPwd = document.getElementById('cpNewPassword').value.trim();
    const confirmPwd = document.getElementById('cpConfirmPassword').value.trim();
    const errEl = document.getElementById('cpErrorMsg');
    const successEl = document.getElementById('cpSuccessMsg');
    const submitBtn = document.getElementById('cpSubmitBtn');

    errEl.style.display = 'none';
    successEl.style.display = 'none';

    if (!oldPwd || !newPwd || !confirmPwd) {
        errEl.textContent = '请填写所有字段';
        errEl.style.display = 'block';
        return false;
    }
    if (newPwd.length < 6) {
        errEl.textContent = '新密码至少6位';
        errEl.style.display = 'block';
        return false;
    }
    if (newPwd !== confirmPwd) {
        errEl.textContent = '两次输入的新密码不一致';
        errEl.style.display = 'block';
        return false;
    }
    if (oldPwd === newPwd) {
        errEl.textContent = '新密码不能与旧密码相同';
        errEl.style.display = 'block';
        return false;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = '提交中...';

    fetch('/tracking/api/auth/change-password', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            old_password: oldPwd,
            new_password: newPwd,
            confirm_password: confirmPwd
        })
    })
    .then(r => r.json())
    .then(data => {
        submitBtn.disabled = false;
        submitBtn.textContent = '确认修改';
        if (data.success) {
            successEl.textContent = '密码修改成功！';
            successEl.style.display = 'block';
            document.getElementById('changePasswordForm').reset();
            if (typeof showToast === 'function') {
                showToast('成功', '密码已修改', 'success');
            }
        } else {
            errEl.textContent = data.error || '修改失败';
            errEl.style.display = 'block';
        }
    })
    .catch(() => {
        submitBtn.disabled = false;
        submitBtn.textContent = '确认修改';
        errEl.textContent = '网络错误，请稍后重试';
        errEl.style.display = 'block';
    });

    return false;
}

function toggleSidebar() {
    const appLayout = document.getElementById('appLayout');
    if (!appLayout) return;

    // 一旦有互動，移除初始化凍結狀態，恢復過渡動畫
    appLayout.classList.remove('sidebar-state-init');
    const isCollapsed = appLayout.classList.toggle('collapsed');
    // 保存狀態到 localStorage
    localStorage.setItem('sidebarCollapsed', isCollapsed ? 'true' : 'false');
}

// 頁面載入時恢復側邊欄狀態
function restoreSidebarState() {
    const appLayout = document.getElementById('appLayout');
    if (!appLayout) return;

    const savedState = localStorage.getItem('sidebarCollapsed');
    if (savedState === 'true') {
        appLayout.classList.add('collapsed');
    } else if (savedState === 'false') {
        appLayout.classList.remove('collapsed');
    }

    // 等首屏渲染完成後再恢復動畫，避免初次閃動
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            appLayout.classList.remove('sidebar-state-init');
        });
    });
}

// 頁面載入時執行
document.addEventListener('DOMContentLoaded', function() {
    restoreSidebarState();
    // 應用表格欄位設定
    setTimeout(() => {
        applyColumnSettings();
    }, 500);
});

// ==================== 主页：筛选 / 快速更新 / 新增订单 / 时间轴 ====================

// 筛选状态（参考 v10.html 逻辑）
let currentFilter = {
    stageGroup: 'all',  // all, draft, sampling, production, quote, completed, cancelled
    stageGroups: ['all'], // 多選：all 或多個具體狀態
    substatus: 'all',   // 子状态筛选
    search: '',
    showCompleted: true,
    showCancelled: false,
    teamSales: [],
    lights: {  // 燈號篩選：true 表示顯示，false 表示隱藏
        red: true,
        yellow: true,
        green: true
    }
};

const TABLE_PAGE_SIZE = 50;
let currentTablePage = 1;
let lastFilterSignature = null;
let isPaginating = false;
let lastFilteredRowsForExport = [];
const CUSTOMER_REPORT_MAX_CUSTOMERS = 3;
let customerReportSelection = [];
let customerReportOptions = { format: 'pdf', language: 'zh_cn', image_source: 'both', image_count: 'all', image_order: 'order_first', pdf_attachment_mode: 'pages' };
let customerReportEstimateTimer = null;
let customerReportIsGenerating = false;
let customerReportModalOpenedAt = 0;
let selectedCustomerNameFilter = '';
let selectedOrderNumberFilter = '';

// ===== 首页数据层：全部资料保存在 JS 阵列，DOM 只渲染当前 50 笔 =====
let homeOrdersData = [];
let homeFilteredOrdersData = [];
let homeDataReady = false;
let homeDataLoading = false;
// Silent salesperson refreshes must not rebuild the whole table/card wall when nothing changed.
// Replacing the card DOM every 30s/on window focus was the source of the visible "flash".
let homeOrdersRenderSignature = '';

// ===== Desktop home view mode: keep the existing table and add a Xiaohongshu-style card wall. =====
// This is presentation state only. Filters, sorting, pagination and order management continue
// to use the same homeOrdersData/homeFilteredOrdersData source and the existing Workspace drawer.
const HOME_ORDER_VIEW_MODE_STORAGE_KEY = 'order_tracking_home_view_mode_v1';
let homeOrderViewMode = (() => {
    try {
        return localStorage.getItem(HOME_ORDER_VIEW_MODE_STORAGE_KEY) === 'cards' ? 'cards' : 'table';
    } catch (_) {
        return 'table';
    }
})();
let homeCardRenderGeneration = 0;
let homeCardCoverObserver = null;
const HOME_CARD_WALL_MEDIA_LIMIT = 6;
const HOME_CARD_MEDIA_CACHE_TTL = 60 * 1000;
const HOME_CARD_COVER_MAX_CONCURRENCY = 4;
const homeCardMediaCache = new Map();
const homeCardMediaInflight = new Map();
let homeCardCoverActiveLoads = 0;
let homeCardCoverQueue = [];
let homeCardFocusState = null;
let homeCardFocusRequestController = null;
let homeCardFocusOriginScrollTop = null;
let homeCardPendingScrollRestoreTop = null;
// Desktop card-mode only: remember the last order opened in the focus modal.
// This is presentation state only; it is not written to the database and no "last viewed" text is shown.
let homeCardLastViewedKey = '';
let homeCardFocusOpenedKey = '';

function homeCardApplyLastViewedMarker() {
    document.querySelectorAll('.home-order-card[data-home-card-key]').forEach(card => {
        card.classList.toggle('is-last-viewed', !!homeCardLastViewedKey && card.dataset.homeCardKey === homeCardLastViewedKey);
    });
}

function homeCaptureSilentRefreshScroll() {
    const wall = document.getElementById('homeCardWall');
    const main = document.querySelector('.main-content');
    return {
        cardTop: homeOrderViewMode === 'cards' && wall ? Number(wall.scrollTop || 0) : null,
        mainTop: main ? Number(main.scrollTop || 0) : null
    };
}

function homeRestoreSilentRefreshScroll(snapshot) {
    if (!snapshot) return;
    const restore = () => {
        const wall = document.getElementById('homeCardWall');
        const main = document.querySelector('.main-content');
        if (snapshot.cardTop !== null && homeOrderViewMode === 'cards' && wall) {
            wall.scrollTop = Math.max(0, Number(snapshot.cardTop) || 0);
        }
        if (snapshot.mainTop !== null && main) {
            main.scrollTop = Math.max(0, Number(snapshot.mainTop) || 0);
        }
    };
    requestAnimationFrame(() => {
        restore();
        // Card columns can finish their layout one frame later because of content-visibility.
        // Re-apply once after layout settles so salesperson auto-sync cannot snap to the top.
        window.setTimeout(restore, 70);
    });
}



function homeOrdersUiSignature(data) {
    const rows = Array.isArray(data) ? data : [];
    // Only fields that can change the visible home table/card wall belong here.
    // Image file lists are lazy-loaded separately.
    return rows.map(order => [
        order?.workflow_number || order?.workflowNumber || '',
        order?.order_number || order?.orderNumber || '',
        order?.updated_at || '',
        order?.current_status || '',
        order?.status_updated_at || '',
        order?.last_history_id || '',
        order?.last_action_date || order?.last_status_change_date || '',
        order?.handler_id || '',
        order?.handler_name || '',
        order?.customer_name || '',
        order?.product_name || '',
        order?.product_code || '',
        order?.quantity ?? '',
        order?.factory || '',
        order?.production_type || '',
        order?.expected_delivery_date || '',
        order?.order_date || '',
        order?.order_status || '',
        order?.visibility || '',
        order?.is_locked ? '1' : '0',
        order?.notes || '',
        order?.status_light || '',
        order?.status_days ?? '',
        order?.last_shipping_date || '',
        order?.last_shipping_status || '',
        order?.partial_ship_count ?? 0
    ].join('\u001f')).join('\u001e');
}


function homeCardEscape(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function homeCardDisplayNumber(order) {
    return String(order?.workflow_number || order?.workflowNumber || order?.order_number || order?.orderNumber || '').trim();
}

function homeCardLight(order) {
    const light = String(order?.status_light || '').toLowerCase();
    return ['red', 'yellow', 'green'].includes(light) ? light : 'none';
}

function homeCardFindRenderedRow(order) {
    const workflowNumber = String(order?.workflow_number || order?.workflowNumber || '').trim();
    const orderNumber = String(order?.order_number || order?.orderNumber || '').trim();
    return Array.from(document.querySelectorAll('#ordersTableBody tr[data-order-number]')).find(row => {
        const rowWorkflow = String(row.dataset.workflowNumber || '').trim();
        const rowOrder = String(row.dataset.orderNumber || '').trim();
        return (workflowNumber && rowWorkflow === workflowNumber) || (!workflowNumber && orderNumber && rowOrder === orderNumber);
    }) || null;
}

function homeCardOpenOrder(order) {
    // Card mode is image-first: open the compact focus modal in place. The original table mode
    // still uses WORKSPACE directly, and the focus modal keeps a "完整管理" escape hatch to it.
    if (typeof homeCardFocusOpen === 'function') {
        homeCardFocusOpen(order);
        return;
    }
    const row = homeCardFindRenderedRow(order);
    if (row && typeof openDetailDrawerFromRow === 'function') openDetailDrawerFromRow(row);
}

function homeCardShareCustomer(customerName) {
    const name = String(customerName || '').trim();
    if (!name || typeof openDesktopGuestShareDrawer !== 'function') return;
    openDesktopGuestShareDrawer(name);
}

function homeCardFocusEls() {
    const root = document.getElementById('homeCardFocusModal');
    if (!root) return null;
    return {
        root,
        panel: root.querySelector('.home-card-focus-modal'),
        close: document.getElementById('homeCardFocusClose'),
        loading: document.getElementById('homeCardFocusLoading'),
        layout: document.getElementById('homeCardFocusLayout'),
        stage: document.getElementById('homeCardFocusStage'),
        image: document.getElementById('homeCardFocusImage'),
        noImage: document.getElementById('homeCardFocusNoImage'),
        prev: document.getElementById('homeCardFocusPrev'),
        next: document.getElementById('homeCardFocusNext'),
        badge: document.getElementById('homeCardFocusMediaBadge'),
        source: document.getElementById('homeCardFocusMediaSource'),
        counter: document.getElementById('homeCardFocusMediaCounter'),
        zoom: document.getElementById('homeCardImageZoom'),
        zoomImage: document.getElementById('homeCardImageZoomImage'),
        zoomClose: document.getElementById('homeCardImageZoomClose'),
        zoomPrev: document.getElementById('homeCardImageZoomPrev'),
        zoomNext: document.getElementById('homeCardImageZoomNext'),
        zoomTitle: document.getElementById('homeCardImageZoomTitle'),
        zoomMeta: document.getElementById('homeCardImageZoomMeta'),
        caption: document.getElementById('homeCardFocusCaption'),
        orderNumber: document.getElementById('homeCardFocusOrderNumber'),
        customer: document.getElementById('homeCardFocusCustomer'),
        status: document.getElementById('homeCardFocusStatus'),
        workflows: document.getElementById('homeCardFocusWorkflows'),
        adminNote: document.getElementById('homeCardFocusAdminNote'),
        salesNote: document.getElementById('homeCardFocusSalesNote'),
        adminInput: document.getElementById('homeCardFocusAdminNoteInput'),
        salesInput: document.getElementById('homeCardFocusSalesNoteInput'),
        meta: document.getElementById('homeCardFocusMeta'),
        timeline: document.getElementById('homeCardFocusTimeline'),
        timelineSection: document.getElementById('homeCardFocusTimelineSection'),
        timelineToggle: document.getElementById('homeCardFocusTimelineToggle'),
        actions: document.getElementById('homeCardFocusActions'),
        actionSection: document.getElementById('homeCardFocusActionSection'),
        share: document.getElementById('homeCardFocusShare'),
        files: document.getElementById('homeCardFocusFiles'),
        manage: document.getElementById('homeCardFocusManage')
    };
}

async function homeCardFocusFetchJson(url, signal) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', signal});
    const payload = await response.json();
    if (!response.ok || payload?.success === false) throw new Error(payload?.error || `HTTP ${response.status}`);
    return payload;
}

function homeCardFocusSyncWorkspaceEngine() {
    const state = homeCardFocusState;
    const ws = window.WorkspaceDrawer;
    if (!state || !ws?.state) return;
    ws.state.currentOrderNumber = state.orderNumber || '';
    ws.state.currentWorkflowNumber = state.workflowNumber || '';
    ws.state.orderOnly = !state.workflowNumber;
    ws.state.workflowData = state.workflowData || null;
    ws.state.currentStatus = state.workflowData?.current_status || '';
    ws.state.lastHistoryId = state.workflowData?.last_history_id || null;
    ws.state.orderFiles = state.orderFiles || [];
    ws.state.workflowFiles = state.workflowFiles || [];
    ws.state.allWorkflows = state.allWorkflows || [];
}

function homeCardFocusCanEditNote(type) {
    const ws = window.WorkspaceDrawer;
    if (!homeCardFocusState || !ws) return false;
    homeCardFocusSyncWorkspaceEngine();
    const canOperate = typeof ws.canOperate === 'function' ? ws.canOperate() : false;
    if (!canOperate) return false;
    if (type === 'admin') return typeof ws.canEditAdminRemark === 'function' && ws.canEditAdminRemark();
    return !!homeCardFocusState.workflowNumber && typeof ws.canEditSalesRemark === 'function' && ws.canEditSalesRemark();
}

function homeCardFocusSourceLabel(media) {
    return media?.source === 'workflow' ? '业务图片' : '主管图片';
}

function homeCardFocusPreload(index) {
    const state = homeCardFocusState;
    if (!state?.media?.length) return;
    [index - 1, index + 1].forEach(i => {
        if (i < 0 || i >= state.media.length) return;
        const url = String(state.media[i]?.preview_url || '').trim();
        if (!url) return;
        const pre = new Image();
        pre.decoding = 'async';
        pre.src = url;
    });
}

function homeCardFocusSyncZoom() {
    const state = homeCardFocusState;
    const el = homeCardFocusEls();
    if (!state || !el?.zoom || el.zoom.hidden) return;
    const media = state.media || [];
    if (!media.length) {
        el.zoomImage?.removeAttribute('src');
        if (el.zoomTitle) el.zoomTitle.textContent = '图片预览';
        if (el.zoomMeta) el.zoomMeta.textContent = '-';
        return;
    }
    const safe = Math.max(0, Math.min(media.length - 1, Number(state.mediaIndex) || 0));
    const item = media[safe] || {};

    // Fullscreen must behave like the WORKSPACE drawer preview: use the original/download URL,
    // not the card thumbnail/preview URL. This prevents a tiny preview being stretched on a black page.
    const rawUrl = String(item.url || item.preview_url || '').trim();
    if (el.zoomImage && rawUrl) {
        const absolute = new URL(rawUrl, window.location.href).href;
        if (el.zoomImage.src !== absolute) el.zoomImage.src = rawUrl;
    }

    const fileName = String(item.file_name || item.original_filename || '').trim();
    const sourceLabel = homeCardFocusSourceLabel(item);
    const uploadedAt = String(item.uploaded_at || item.created_at || '').trim();
    if (el.zoomTitle) {
        el.zoomTitle.textContent = `${fileName || sourceLabel} (${safe + 1} / ${media.length})`;
    }
    if (el.zoomMeta) {
        el.zoomMeta.textContent = [sourceLabel, fileName, uploadedAt].filter(Boolean).join(' • ') || sourceLabel;
    }
    if (el.zoomPrev) {
        el.zoomPrev.hidden = media.length <= 1;
        el.zoomPrev.disabled = safe <= 0;
    }
    if (el.zoomNext) {
        el.zoomNext.hidden = media.length <= 1;
        el.zoomNext.disabled = safe >= media.length - 1;
    }
}

function homeCardFocusOpenZoom() {
    const state = homeCardFocusState;
    const el = homeCardFocusEls();
    if (!state?.media?.length || !el?.zoom) return;
    el.zoom.hidden = false;
    el.zoom.setAttribute('aria-hidden', 'false');
    homeCardFocusSyncZoom();
}

function homeCardFocusCloseZoom() {
    const el = homeCardFocusEls();
    if (!el?.zoom) return;
    el.zoom.hidden = true;
    el.zoom.setAttribute('aria-hidden', 'true');
    if (el.zoomImage) el.zoomImage.removeAttribute('src');
}

function homeCardFocusShowMedia(index, {instant = false} = {}) {
    const state = homeCardFocusState;
    const el = homeCardFocusEls();
    if (!state || !el) return;
    const media = state.media || [];
    if (!media.length) {
        state.mediaIndex = 0;
        el.image.removeAttribute('src');
        el.image.hidden = true;
        el.noImage.hidden = false;
        el.prev.hidden = true;
        el.next.hidden = true;
        el.badge.hidden = true;
        el.caption.textContent = '';
        return;
    }
    const safe = Math.max(0, Math.min(media.length - 1, Number(index) || 0));
    state.mediaIndex = safe;
    const item = media[safe];
    el.noImage.hidden = true;
    el.image.hidden = false;
    const previewUrl = String(item.preview_url || item.url || '').trim();
    const absolutePreviewUrl = previewUrl ? new URL(previewUrl, window.location.href).href : '';
    const sourceChanged = Boolean(previewUrl) && el.image.src !== absolutePreviewUrl;

    // Important: register the load handler BEFORE assigning src. Cached images can finish
    // synchronously; assigning onload afterwards leaves the image stuck at the loading opacity.
    if (sourceChanged) {
        el.image.classList.remove('loaded');
        el.image.onload = () => el.image.classList.add('loaded');
        el.image.onerror = () => el.image.classList.add('loaded');
        el.image.src = previewUrl;
    } else {
        // Boundary clicks / repeated navigation must never dim the current image.
        el.image.classList.add('loaded');
    }
    if (el.image.complete && el.image.naturalWidth > 0) el.image.classList.add('loaded');
    el.prev.hidden = media.length <= 1;
    el.next.hidden = media.length <= 1;
    el.prev.disabled = safe <= 0;
    el.next.disabled = safe >= media.length - 1;
    el.badge.hidden = false;
    el.source.textContent = homeCardFocusSourceLabel(item);
    el.counter.textContent = `${safe + 1}/${media.length}`;
    const fileName = String(item.file_name || item.original_filename || '').trim();
    const uploadedAt = String(item.uploaded_at || '').trim();
    el.caption.textContent = [homeCardFocusSourceLabel(item), fileName, uploadedAt].filter(Boolean).join(' · ');
    if (!instant) homeCardFocusPreload(safe);
    homeCardFocusSyncZoom();
}

function homeCardFocusStep(delta) {
    if (!homeCardFocusState?.media?.length) return;
    const media = homeCardFocusState.media;
    const current = Math.max(0, Math.min(media.length - 1, Number(homeCardFocusState.mediaIndex) || 0));
    const next = Math.max(0, Math.min(media.length - 1, current + Number(delta || 0)));
    // At the first/last image, extra clicks are a true no-op. Do not re-render or touch opacity.
    if (next === current) return;
    homeCardFocusShowMedia(next);
}

function homeCardFocusRenderWorkflows() {
    const state = homeCardFocusState;
    const el = homeCardFocusEls();
    if (!state || !el) return;
    const workflows = Array.isArray(state.allWorkflows) ? state.allWorkflows : [];
    if (workflows.length <= 1) {
        el.workflows.hidden = true;
        el.workflows.replaceChildren();
        return;
    }
    el.workflows.hidden = false;
    el.workflows.innerHTML = workflows.map(wf => {
        const number = String(wf.workflow_number || '').trim();
        const handler = String(wf.handler_name || '').trim();
        const active = number === state.workflowNumber;
        return `<button type="button" class="${active ? 'active' : ''}" data-focus-workflow="${homeCardEscape(number)}"><strong>${homeCardEscape(number)}</strong>${handler ? `<small>${homeCardEscape(handler)}</small>` : ''}</button>`;
    }).join('');
}

function homeCardFocusRenderMeta() {
    const state = homeCardFocusState;
    const el = homeCardFocusEls();
    if (!state || !el) return;
    const order = state.order || {};
    const data = state.workflowData || {};
    const items = [
        ['业务员', data.handler_name || order.handler_name || order.handlerName],
        ['产品', order.production_type || order.product_name],
        ['编号', order.product_code],
        ['工厂', order.factory],
        ['数量', order.quantity],
        ['下单', order.order_date],
        ['交期', order.expected_delivery_date]
    ].filter(([, value]) => String(value || '').trim());
    el.meta.innerHTML = items.length
        ? items.map(([label, value]) => `<div><span>${homeCardEscape(label)}</span><strong>${homeCardEscape(String(value))}</strong></div>`).join('')
        : '<p class="home-card-focus-muted">暂无更多资料</p>';
}

function homeCardFocusRenderTimeline() {
    const state = homeCardFocusState;
    const el = homeCardFocusEls();
    if (!state || !el?.timeline || !el.timelineSection) return;
    const history = Array.isArray(state.workflowData?.history) ? state.workflowData.history : [];
    if (!history.length) {
        el.timelineSection.hidden = true;
        el.timeline.replaceChildren();
        if (el.timelineToggle) el.timelineToggle.hidden = true;
        return;
    }
    el.timelineSection.hidden = false;

    // Match the WORKSPACE drawer idea: keep the latest five compact by default,
    // but allow older folded records to be expanded in-place when they exist.
    const hasOlder = history.length > 5;
    const expanded = hasOlder && !!state.timelineExpanded;
    const visibleHistory = expanded ? history : history.slice(-5);
    if (el.timelineToggle) {
        el.timelineToggle.hidden = !hasOlder;
        el.timelineToggle.textContent = expanded ? '收起' : '展开';
        el.timelineToggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }

    el.timeline.innerHTML = visibleHistory.map((item, index) => {
        const key = String(item.to_status || item.status || '').trim();
        const label = key && typeof displayStatus === 'function' ? displayStatus(key) : (key || '—');
        const date = String(item.action_date || item.created_at || '').trim();
        const note = String(item.notes || '').trim();
        const currentClass = index === visibleHistory.length - 1 ? ' is-current' : '';
        return `<div class="home-card-focus-timeline-item${currentClass}"><i></i><div><strong>${homeCardEscape(label)}</strong>${date ? `<time>${homeCardEscape(date)}</time>` : ''}${note ? `<small title="${homeCardEscape(note)}">${homeCardEscape(note)}</small>` : ''}</div></div>`;
    }).join('');
}

function homeCardFocusRenderActions() {
    const state = homeCardFocusState;
    const el = homeCardFocusEls();
    if (!state || !el) return;
    homeCardFocusSyncWorkspaceEngine();
    const ws = window.WorkspaceDrawer;
    const canOperate = !!(state.workflowNumber && ws && typeof ws.canOperate === 'function' && ws.canOperate());
    const actions = canOperate && typeof getQuickActions === 'function'
        ? (getQuickActions(state.workflowData?.current_status || '') || [])
        : [];
    if (!canOperate) {
        el.actionSection.hidden = true;
        el.actions.classList.remove('with-skip-icon');
        el.actions.replaceChildren();
        return;
    }
    el.actionSection.hidden = false;
    const actionHtml = actions.map(action => {
        const cls = action.color === 'confirm' ? 'primary' : 'warning';
        return `<button type="button" class="${cls}" data-focus-quick-action="${homeCardEscape(action.action)}"><span>${homeCardEscape(action.label || action.action)}</span></button>`;
    }).join('');
    // Keep the same WORKSPACE action engine. The compact modal only changes placement.
    // Cancel-order is intentionally omitted here: skip-stage already covers exceptional routing.
    // Match the right WORKSPACE drawer and show skip-stage as the compact double-arrow control.
    el.actions.classList.add('with-skip-icon');
    el.actions.innerHTML = `${actionHtml}<button type="button" class="secondary home-card-focus-skip-icon" data-focus-skip-action title="跳过阶段" aria-label="跳过阶段"><span class="material-symbols-rounded">double_arrow</span></button>`;
}

function homeCardFocusRender() {
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
        const btn = el.root.querySelector(`[data-focus-note-edit="${type}"]`);
        if (btn) btn.hidden = !homeCardFocusCanEditNote(type);
        const editor = el.root.querySelector(`[data-focus-note-editor="${type}"]`);
        if (editor) editor.hidden = true;
        const p = type === 'admin' ? el.adminNote : el.salesNote;
        if (p) p.hidden = false;
    });
    homeCardFocusRenderWorkflows();
    homeCardFocusRenderMeta();
    homeCardFocusRenderTimeline();
    homeCardFocusRenderActions();
    homeCardFocusShowMedia(Math.min(state.mediaIndex || 0, Math.max(0, (state.media || []).length - 1)), {instant: true});
}

async function homeCardFocusLoad(order, workflowOverride = '', {preserveIndex = false} = {}) {
    const el = homeCardFocusEls();
    if (!el) return;
    if (homeCardFocusRequestController) {
        try { homeCardFocusRequestController.abort(); } catch (_) {}
    }
    const controller = new AbortController();
    homeCardFocusRequestController = controller;
    const previousIndex = preserveIndex ? Number(homeCardFocusState?.mediaIndex || 0) : 0;
    const previousTimelineExpanded = preserveIndex ? !!homeCardFocusState?.timelineExpanded : false;
    const baseOrder = {...(order || homeCardFocusState?.order || {})};
    let orderNumber = String(baseOrder.order_number || baseOrder.orderNumber || homeCardFocusState?.orderNumber || '').trim();
    let workflowNumber = String(workflowOverride || baseOrder.workflow_number || baseOrder.workflowNumber || '').trim();

    el.loading.hidden = false;
    el.layout.hidden = true;
    el.loading.innerHTML = '<span class="home-orders-loading-spinner"></span><span>正在读取订单…</span>';

    try {
        let allWorkflows = [];
        if (orderNumber) {
            try {
                const allPayload = await homeCardFocusFetchJson(`/tracking/api/workflows?order=${encodeURIComponent(orderNumber)}`, controller.signal);
                allWorkflows = allPayload?.data?.workflows || [];
                if (!workflowNumber && allWorkflows.length) workflowNumber = String(allWorkflows[0]?.workflow_number || '').trim();
            } catch (_) {}
        }
        if (!orderNumber && workflowNumber) orderNumber = workflowNumber.split('-')[0];

        const workflowPromise = workflowNumber
            ? homeCardFocusFetchJson(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}`, controller.signal).catch(() => null)
            : Promise.resolve(null);
        const orderPromise = orderNumber
            ? homeCardFocusFetchJson(`/tracking/api/orders/${encodeURIComponent(orderNumber)}`, controller.signal).catch(() => null)
            : Promise.resolve(null);
        const mediaCacheKey = `${orderNumber}::${workflowNumber}`;
        const cachedMedia = homeCardMediaCache.get(mediaCacheKey);
        const canReuseMedia = !!(cachedMedia && (Date.now() - cachedMedia.at) < HOME_CARD_MEDIA_CACHE_TTL);
        const orderFilesPromise = (!canReuseMedia && orderNumber)
            ? homeCardFocusFetchJson(`/tracking/api/orders/${encodeURIComponent(orderNumber)}/files`, controller.signal).catch(() => ({data:{files:[]}}))
            : Promise.resolve({data:{files:[]}});
        const workflowFilesPromise = (!canReuseMedia && workflowNumber)
            ? homeCardFocusFetchJson(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}/files`, controller.signal).catch(() => ({data:{files:[]}}))
            : Promise.resolve({data:{files:[]}});

        const [workflowPayload, orderPayload, orderFilesPayload, workflowFilesPayload] = await Promise.all([
            workflowPromise, orderPromise, orderFilesPromise, workflowFilesPromise
        ]);
        const workflowData = workflowPayload?.data || (orderPayload?.data ? {
            order_number: orderPayload.data.order_number,
            customer_name: orderPayload.data.customer_name,
            order_notes: orderPayload.data.notes || '',
            workflow_number: '',
            current_status: '',
            workflow_notes: ''
        } : {});
        if (!orderNumber) orderNumber = String(workflowData?.order_number || '').trim();
        if (!allWorkflows.length && orderNumber) {
            try {
                const allPayload = await homeCardFocusFetchJson(`/tracking/api/workflows?order=${encodeURIComponent(orderNumber)}`, controller.signal);
                allWorkflows = allPayload?.data?.workflows || [];
            } catch (_) {}
        }

        const orderFiles = orderFilesPayload?.data?.files || [];
        const workflowFiles = workflowFilesPayload?.data?.files || [];
        const media = canReuseMedia
            ? cachedMedia.images
            : [
                ...workflowFiles.map(file => homeCardImageFromFile(file, 'workflow', workflowNumber)).filter(Boolean),
                ...orderFiles.map(file => homeCardImageFromFile(file, 'order', workflowNumber)).filter(Boolean)
            ].sort((a, b) => {
                if (a.source !== b.source) return a.source === 'workflow' ? -1 : 1;
                return String(b.uploaded_at || '').localeCompare(String(a.uploaded_at || ''));
            });
        if (!canReuseMedia) homeCardMediaCache.set(mediaCacheKey, {at: Date.now(), images: media});

        homeCardFocusState = {
            order: {...baseOrder, ...(orderPayload?.data || {})},
            orderNumber,
            workflowNumber,
            workflowData,
            allWorkflows,
            orderFiles,
            workflowFiles,
            media,
            mediaIndex: Math.min(previousIndex, Math.max(0, media.length - 1)),
            timelineExpanded: previousTimelineExpanded
        };
        homeCardFocusSyncWorkspaceEngine();
        homeCardFocusRender();
        el.loading.hidden = true;
        el.layout.hidden = false;
    } catch (error) {
        if (error?.name === 'AbortError') return;
        el.layout.hidden = true;
        el.loading.hidden = false;
        el.loading.innerHTML = `<strong>无法读取订单</strong><small>${homeCardEscape(String(error?.message || error))}</small>`;
    } finally {
        if (homeCardFocusRequestController === controller) homeCardFocusRequestController = null;
    }
}

function homeCardFocusOpen(order) {
    const el = homeCardFocusEls();
    if (!el) return;
    const wall = document.getElementById('homeCardWall');
    homeCardFocusOriginScrollTop = wall ? wall.scrollTop : null;
    homeCardFocusOpenedKey = String(getHomeOrderKey(order) || homeCardDisplayNumber(order) || '').trim();
    el.root.hidden = false;
    el.root.setAttribute('aria-hidden', 'false');
    document.body.classList.add('home-card-focus-open');
    homeCardFocusLoad(order);
}

function homeCardFocusClose() {
    const el = homeCardFocusEls();
    if (!el) return;
    homeCardFocusCloseZoom();
    if (homeCardFocusRequestController) {
        try { homeCardFocusRequestController.abort(); } catch (_) {}
        homeCardFocusRequestController = null;
    }
    el.root.hidden = true;
    el.root.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('home-card-focus-open');
    el.image.removeAttribute('src');
    el.layout.hidden = true;
    el.loading.hidden = false;
    homeCardFocusState = null;
    if (homeCardFocusOpenedKey) {
        homeCardLastViewedKey = homeCardFocusOpenedKey;
        homeCardFocusOpenedKey = '';
        homeCardApplyLastViewedMarker();
    }
    const restoreTop = homeCardFocusOriginScrollTop;
    homeCardFocusOriginScrollTop = null;
    if (restoreTop !== null) {
        requestAnimationFrame(() => {
            const wall = document.getElementById('homeCardWall');
            if (wall) wall.scrollTop = Math.max(0, Number(restoreTop) || 0);
        });
    }
}

function homeCardFocusOpenWorkspace(tab = 'process') {
    const state = homeCardFocusState;
    const ws = window.WorkspaceDrawer;
    if (!state || !ws) return;
    homeCardFocusClose();
    if (ws.state) ws.state.currentTab = tab || 'process';
    if (state.workflowNumber && typeof ws.open === 'function') ws.open(state.workflowNumber);
    else if (state.orderNumber && typeof ws.openFromOrder === 'function') ws.openFromOrder(state.orderNumber);
}

async function homeCardFocusRunQuickAction(action, button) {
    const state = homeCardFocusState;
    const ws = window.WorkspaceDrawer;
    if (!state?.workflowNumber || !ws || typeof ws.handleQuickActionWithLoading !== 'function') return;
    homeCardFocusSyncWorkspaceEngine();
    const label = button?.querySelector('span') || button;
    try {
        await ws.handleQuickActionWithLoading(action, button, label);
        window.setTimeout(() => {
            if (homeCardFocusState?.workflowNumber === state.workflowNumber) {
                homeCardFocusLoad(homeCardFocusState.order, state.workflowNumber, {preserveIndex: true});
            }
        }, 720);
    } catch (_) {}
}

function homeCardFocusToggleNoteEditor(type, editing) {
    const el = homeCardFocusEls();
    if (!el || !homeCardFocusState) return;
    const note = type === 'admin' ? el.adminNote : el.salesNote;
    const input = type === 'admin' ? el.adminInput : el.salesInput;
    const editor = el.root.querySelector(`[data-focus-note-editor="${type}"]`);
    const editButton = el.root.querySelector(`[data-focus-note-edit="${type}"]`);
    const box = note?.closest('.home-card-focus-note-box');
    if (!note || !input || !editor) return;
    if (editing && !homeCardFocusCanEditNote(type)) return;
    editor.hidden = !editing;
    note.hidden = !!editing;
    box?.classList.toggle('is-editing', !!editing);
    if (editButton) editButton.hidden = !!editing || !homeCardFocusCanEditNote(type);
    if (editing) {
        input.value = note.textContent === '暂无备注' ? '' : note.textContent;
        setTimeout(() => {
            input.focus();
            input.setSelectionRange(input.value.length, input.value.length);
        }, 0);
    }
}

async function homeCardFocusSaveNote(type, button) {
    const state = homeCardFocusState;
    const el = homeCardFocusEls();
    if (!state || !el || !homeCardFocusCanEditNote(type)) return;
    const input = type === 'admin' ? el.adminInput : el.salesInput;
    const notes = String(input?.value || '').trim();
    const identifier = type === 'admin' ? state.orderNumber : state.workflowNumber;
    if (!identifier) return;
    const url = type === 'admin'
        ? `/tracking/api/orders/${encodeURIComponent(identifier)}`
        : `/tracking/api/workflows/${encodeURIComponent(identifier)}`;
    const originalText = button?.textContent || '保存';
    if (button) { button.disabled = true; button.textContent = '保存中…'; }
    try {
        const response = await fetch(url, {
            method:'PUT', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({notes})
        });
        const payload = await response.json();
        if (!response.ok || payload?.success === false) throw new Error(payload?.error || '保存失败');
        if (type === 'admin') {
            state.workflowData.order_notes = notes;
            if (state.order) state.order.order_notes = notes;
            el.adminNote.textContent = notes || '暂无备注';
        } else {
            state.workflowData.workflow_notes = notes;
            state.workflowData.notes = notes;
            if (state.order) state.order.notes = notes;
            el.salesNote.textContent = notes || '暂无备注';
            if (typeof window.updateTableNotesAfterSave === 'function') window.updateTableNotesAfterSave(state.workflowNumber, notes);
        }
        homeCardFocusToggleNoteEditor(type, false);
        if (typeof showToast === 'function') showToast('成功', '备注已保存', 'success');
    } catch (error) {
        if (typeof showToast === 'function') showToast('错误', error?.message || '保存失败', 'error');
    } finally {
        if (button) { button.disabled = false; button.textContent = originalText; }
    }
}

function homeCardFocusInit() {
    const el = homeCardFocusEls();
    if (!el || el.root.dataset.bound === '1') return;
    el.root.dataset.bound = '1';
    el.close?.addEventListener('click', homeCardFocusClose);
    el.root.addEventListener('click', event => {
        if (event.target === el.root) { homeCardFocusClose(); return; }
        const workflowBtn = event.target.closest('[data-focus-workflow]');
        if (workflowBtn) {
            event.preventDefault();
            homeCardFocusLoad(homeCardFocusState?.order || {}, workflowBtn.dataset.focusWorkflow || '', {preserveIndex:false});
            return;
        }
        const quick = event.target.closest('[data-focus-quick-action]');
        if (quick) {
            event.preventDefault();
            homeCardFocusRunQuickAction(quick.dataset.focusQuickAction || '', quick);
            return;
        }
        if (event.target.closest('[data-focus-skip-action]')) {
            event.preventDefault();
            homeCardFocusSyncWorkspaceEngine();
            if (window.WorkspaceDrawer?.openSkipStageModal) window.WorkspaceDrawer.openSkipStageModal();
            return;
        }
        if (event.target.closest('#homeCardFocusTimelineToggle')) {
            event.preventDefault();
            if (homeCardFocusState) {
                homeCardFocusState.timelineExpanded = !homeCardFocusState.timelineExpanded;
                homeCardFocusRenderTimeline();
            }
            return;
        }
        const edit = event.target.closest('[data-focus-note-edit]');
        if (edit) { homeCardFocusToggleNoteEditor(edit.dataset.focusNoteEdit, true); return; }
        const cancel = event.target.closest('[data-focus-note-cancel]');
        if (cancel) { homeCardFocusToggleNoteEditor(cancel.dataset.focusNoteCancel, false); return; }
        const save = event.target.closest('[data-focus-note-save]');
        if (save) { homeCardFocusSaveNote(save.dataset.focusNoteSave, save); return; }
    });
    el.prev?.addEventListener('click', event => { event.stopPropagation(); homeCardFocusStep(-1); });
    el.next?.addEventListener('click', event => { event.stopPropagation(); homeCardFocusStep(1); });
    // The media stage captures the pointer so horizontal drag can switch images. Because of that,
    // a normal click may be retargeted to the stage instead of the <img>. Handle click-vs-swipe
    // in the pointer gesture below rather than relying on the image's click event.
    el.zoomClose?.addEventListener('click', event => {
        event.stopPropagation();
        homeCardFocusCloseZoom();
    });
    el.zoom?.addEventListener('click', event => {
        if (event.target === el.zoom) homeCardFocusCloseZoom();
    });
    el.zoomPrev?.addEventListener('click', event => {
        event.stopPropagation();
        homeCardFocusStep(-1);
    });
    el.zoomNext?.addEventListener('click', event => {
        event.stopPropagation();
        homeCardFocusStep(1);
    });
    let pointerId = null, startX = 0, startY = 0, pointerStartedOnImage = false;
    el.stage?.addEventListener('pointerdown', event => {
        if (event.target.closest('button')) return;
        pointerId = event.pointerId;
        startX = event.clientX;
        startY = event.clientY;
        pointerStartedOnImage = event.target === el.image;
        try { el.stage.setPointerCapture(pointerId); } catch (_) {}
    });
    const finishSwipe = event => {
        if (pointerId === null || event.pointerId !== pointerId) return;
        const dx = event.clientX - startX;
        const dy = event.clientY - startY;
        const startedOnImage = pointerStartedOnImage;
        try { el.stage.releasePointerCapture(pointerId); } catch (_) {}
        pointerId = null;
        pointerStartedOnImage = false;

        const isHorizontalSwipe = Math.abs(dx) > 55 && Math.abs(dx) > Math.abs(dy) * 1.2;
        if (isHorizontalSwipe) {
            homeCardFocusStep(dx < 0 ? 1 : -1);
            return;
        }

        // A short press/release on the visible image means "zoom". Small hand/mouse movement is
        // tolerated so an ordinary click still works even though the stage owns pointer capture.
        if (startedOnImage && Math.hypot(dx, dy) < 18) {
            homeCardFocusOpenZoom();
        }
    };
    el.stage?.addEventListener('pointerup', finishSwipe);
    el.stage?.addEventListener('pointercancel', () => { pointerId = null; pointerStartedOnImage = false; });
    document.addEventListener('keydown', event => {
        if (el.root.hidden) return;
        if (event.key === 'Escape') {
            if (el.zoom && !el.zoom.hidden) homeCardFocusCloseZoom();
            else homeCardFocusClose();
            return;
        }
        if (event.key === 'ArrowLeft') homeCardFocusStep(-1);
        if (event.key === 'ArrowRight') homeCardFocusStep(1);
    });
    window.addEventListener('tracking:workspace-updated', event => {
        if (el.root.hidden || !homeCardFocusState) return;
        const workflowNumber = String(event.detail?.workflowNumber || '').trim();
        if (workflowNumber && workflowNumber !== homeCardFocusState.workflowNumber) return;
        const current = homeCardFocusState;
        window.setTimeout(() => {
            if (!el.root.hidden && homeCardFocusState?.workflowNumber === current.workflowNumber) {
                homeCardFocusLoad(current.order, current.workflowNumber, {preserveIndex:true});
            }
        }, 220);
    });
}

window.homeCardFocusOpen = homeCardFocusOpen;
window.homeCardFocusClose = homeCardFocusClose;
document.addEventListener('DOMContentLoaded', homeCardFocusInit);

function homeCardIsImageFile(file) {
    const type = String(file?.file_type || file?.mime_type || '').toLowerCase();
    const name = String(file?.file_name || file?.original_filename || '').toLowerCase();
    return type.startsWith('image') || /\.(jpg|jpeg|png|gif|webp|bmp|heic)$/i.test(name);
}

function homeCardImageFromFile(file, source, workflowNumber = '') {
    if (!file || !homeCardIsImageFile(file)) return null;
    const id = Number(file.id || 0);
    if (!id) return null;
    const rawUrl = source === 'workflow'
        ? `/tracking/api/workflows/${encodeURIComponent(workflowNumber)}/files/${id}/download`
        : `/tracking/api/orders/files/${id}/download`;
    return {
        ...file,
        source,
        media_type: 'image',
        url: rawUrl,
        preview_url: `${rawUrl}?preview=1`
    };
}

async function homeCardFetchJson(url) {
    const response = await fetch(url, {credentials: 'same-origin'});
    const payload = await response.json();
    if (!response.ok || payload?.success === false) throw new Error(payload?.error || `HTTP ${response.status}`);
    return payload;
}

async function homeCardLoadOrderImages(order, options = {}) {
    if (typeof isCloudMode === 'function' && isCloudMode()) return [];
    const orderNumber = String(order?.order_number || order?.orderNumber || '').trim();
    const workflowNumber = String(order?.workflow_number || order?.workflowNumber || '').trim();
    const key = `${orderNumber}::${workflowNumber}`;
    const force = !!options.force;
    const cached = homeCardMediaCache.get(key);
    if (!force && cached && (Date.now() - cached.at) < HOME_CARD_MEDIA_CACHE_TTL) return cached.images;
    if (!force && homeCardMediaInflight.has(key)) return homeCardMediaInflight.get(key);

    const task = (async () => {
        // Card mode intentionally requests normal file lists WITHOUT visual=1. PDF page previews
        // are never prepared here; only real image files participate in the wall/focus viewer.
        const workflowTask = workflowNumber
            ? homeCardFetchJson(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}/files`)
                .then(payload => (payload?.data?.files || [])
                    .map(file => homeCardImageFromFile(file, 'workflow', workflowNumber))
                    .filter(Boolean))
                .catch(() => [])
            : Promise.resolve([]);
        const orderTask = orderNumber
            ? homeCardFetchJson(`/tracking/api/orders/${encodeURIComponent(orderNumber)}/files`)
                .then(payload => (payload?.data?.files || [])
                    .map(file => homeCardImageFromFile(file, 'order'))
                    .filter(Boolean))
                .catch(() => [])
            : Promise.resolve([]);

        const [workflowImages, orderImages] = await Promise.all([workflowTask, orderTask]);
        const newestFirst = list => list.sort((a, b) => String(b.uploaded_at || '').localeCompare(String(a.uploaded_at || '')));
        const images = [...newestFirst(workflowImages), ...newestFirst(orderImages)];
        homeCardMediaCache.set(key, {at: Date.now(), images});
        return images;
    })();
    homeCardMediaInflight.set(key, task);
    try { return await task; }
    finally { homeCardMediaInflight.delete(key); }
}

function homeCardPickWallImages(images) {
    const list = Array.isArray(images) ? images : [];
    if (list.length <= HOME_CARD_WALL_MEDIA_LIMIT) return list;
    const sales = list.filter(item => item.source === 'workflow');
    const admin = list.filter(item => item.source !== 'workflow');
    if (!sales.length || !admin.length) return list.slice(0, HOME_CARD_WALL_MEDIA_LIMIT);
    const salesSlots = Math.min(4, Math.max(1, HOME_CARD_WALL_MEDIA_LIMIT - 2));
    const adminSlots = HOME_CARD_WALL_MEDIA_LIMIT - salesSlots;
    return [...sales.slice(0, salesSlots), ...admin.slice(0, adminSlots)];
}

function homeCardMediaLoadImage(img) {
    if (!img || img.src || !img.dataset.src) return;
    img.src = img.dataset.src;
    img.removeAttribute('data-src');
}

function homeCardMediaSync(cover, index) {
    if (!cover) return;
    const track = cover.querySelector('[data-home-card-media-track]');
    const count = Number(track?.dataset.imageCount || 0);
    if (!track || !count) return;
    const safeIndex = Math.max(0, Math.min(count - 1, Number(index) || 0));
    track.dataset.imageIndex = String(safeIndex);

    [safeIndex - 1, safeIndex, safeIndex + 1].forEach(i => {
        if (i < 0 || i >= count) return;
        homeCardMediaLoadImage(track.querySelector(`[data-home-card-media-index="${i}"]`));
    });

    const slide = track.querySelector(`[data-home-card-media-slide="${safeIndex}"]`);
    const source = cover.querySelector('[data-home-card-media-source]');
    const counter = cover.querySelector('[data-home-card-media-counter]');
    const label = slide?.dataset.mediaSource === 'workflow' ? '业务' : '主管';
    if (source) source.textContent = label;
    const totalCount = Math.max(count, Number(track.dataset.totalImageCount || count));
    if (counter) counter.textContent = totalCount > count
        ? `${safeIndex + 1}/${count} · 共${totalCount}`
        : `${safeIndex + 1}/${count}`;

    cover.querySelectorAll('[data-home-card-media-dot]').forEach(dot => {
        dot.classList.toggle('active', Number(dot.dataset.homeCardMediaDot) === safeIndex);
    });

    const prev = cover.querySelector('[data-home-card-media-prev]');
    const next = cover.querySelector('[data-home-card-media-next]');
    if (prev) prev.disabled = safeIndex <= 0;
    if (next) next.disabled = safeIndex >= count - 1;
}

function homeCardMediaScrolled(track) {
    if (!track) return;
    const cover = track.closest('[data-home-card-cover]');
    const card = track.closest('.home-order-card');
    const width = track.clientWidth || 1;
    const count = Number(track.dataset.imageCount || 0);
    if (!count) return;
    const index = Math.max(0, Math.min(count - 1, Math.round(track.scrollLeft / width)));
    if (card) card.dataset.suppressOpenUntil = String(Date.now() + 450);
    homeCardMediaSync(cover, index);
}

function homeCardMediaStep(button, delta) {
    const cover = button?.closest('[data-home-card-cover]');
    const track = cover?.querySelector('[data-home-card-media-track]');
    if (!track) return;
    const card = cover.closest('.home-order-card');
    const count = Number(track.dataset.imageCount || 0);
    const current = Number(track.dataset.imageIndex || 0);
    const next = Math.max(0, Math.min(count - 1, current + Number(delta || 0)));
    if (card) card.dataset.suppressOpenUntil = String(Date.now() + 520);
    track.scrollTo({left: next * (track.clientWidth || 1), behavior: 'smooth'});
    homeCardMediaSync(cover, next);
}

function createHomeOrderCard(order, pageIndex) {
    const article = document.createElement('article');
    const light = homeCardLight(order);
    const displayNumber = homeCardDisplayNumber(order) || '—';
    const customer = String(order?.customer_name || '—');
    const status = order?.no_workflow
        ? ((typeof window.getTrackingLanguage === 'function' && window.getTrackingLanguage() === 'es') ? 'Sin proceso' : '尚无流程')
        : ((typeof displayStatus === 'function') ? displayStatus(order?.current_status || '') : (order?.current_status || '—'));
    const productType = String(order?.production_type || order?.product_name || '').trim();
    const productCode = String(order?.product_code || '').trim();
    const factory = String(order?.factory || '').trim();
    const handler = String(order?.handler_name || order?.handlerName || '').trim();
    const notes = String(order?.notes || '').trim();
    const orderDate = String(order?.order_date || '').trim();
    const delivery = String(order?.expected_delivery_date || '').trim();
    const quantity = String(order?.quantity || '').trim();

    const cardKey = String(getHomeOrderKey(order) || displayNumber || '').trim();
    article.className = `home-order-card light-${light}${order?.no_workflow ? ' is-no-workflow' : ''}${homeCardLastViewedKey && homeCardLastViewedKey === cardKey ? ' is-last-viewed' : ''}`;
    article.dataset.homeCardKey = cardKey;
    article.dataset.homeCardPageIndex = String(pageIndex || 0);
    article.__homeOrder = order;
    article.innerHTML = `
        <div class="home-order-card-main" data-home-card-action="detail" role="button" tabindex="0" aria-label="打开 ${homeCardEscape(displayNumber)} 详情">
            <div class="home-order-card-cover" data-home-card-cover>
                <div class="home-order-card-cover-placeholder">
                    <span>${homeCardEscape((productType || customer || displayNumber).slice(0, 2).toUpperCase())}</span>
                    <small>图片载入中</small>
                </div>
                <div class="home-order-card-media-track" data-home-card-media-track aria-label="订单图片"></div>
                <button type="button" class="home-order-card-media-nav prev" data-home-card-media-prev aria-label="上一张图片">‹</button>
                <button type="button" class="home-order-card-media-nav next" data-home-card-media-next aria-label="下一张图片">›</button>
                <div class="home-order-card-media-info" data-home-card-media-info hidden>
                    <span data-home-card-media-source></span>
                    <span data-home-card-media-counter></span>
                </div>
                <div class="home-order-card-media-dots" data-home-card-media-dots></div>
                <span class="home-order-card-light light-${light}" aria-label="${light}"></span>
            </div>
            <div class="home-order-card-body">
                <div class="home-order-card-number-row">
                    <strong>${homeCardEscape(displayNumber)}</strong>
                    ${orderDate ? `<time>${homeCardEscape(orderDate)}</time>` : ''}
                </div>
                <div class="home-order-card-customer-row">
                    <div class="home-order-card-customer">${homeCardEscape(customer)}</div>
                    <span class="home-order-card-status">${homeCardEscape(status)}</span>
                </div>
                ${(productType || productCode) ? `<div class="home-order-card-product">${homeCardEscape(productType || '产品')}${productCode ? ` · ${homeCardEscape(productCode)}` : ''}</div>` : ''}
                ${notes ? `<div class="home-order-card-note" title="${homeCardEscape(notes)}">${homeCardEscape(notes)}</div>` : '<div class="home-order-card-note is-empty">暂无备注</div>'}
                <div class="home-order-card-meta">
                    ${factory ? `<span><b>工厂</b>${homeCardEscape(factory)}</span>` : ''}
                    ${quantity ? `<span><b>数量</b>${homeCardEscape(quantity)}</span>` : ''}
                    ${delivery ? `<span><b>交期</b>${homeCardEscape(delivery)}</span>` : ''}
                    ${handler ? `<span><b>业务</b>${homeCardEscape(handler)}</span>` : ''}
                </div>
            </div>
        </div>`;

    const main = article.querySelector('.home-order-card-main');
    main?.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        homeCardOpenOrder(order);
    });

    article.addEventListener('click', event => {
        if (event.target.closest('[data-home-card-media-prev], [data-home-card-media-next]')) return;
        const action = event.target.closest('[data-home-card-action]')?.dataset.homeCardAction;
        if (!action) return;
        if (action === 'detail' && Date.now() < Number(article.dataset.suppressOpenUntil || 0)) return;
        event.preventDefault();
        event.stopPropagation();
        homeCardOpenOrder(order);
    });
    return article;
}

async function homeCardHydrateCover(card, order, generation) {
    if (!card || generation !== homeCardRenderGeneration || homeOrderViewMode !== 'cards') return;
    const cover = card.querySelector('[data-home-card-cover]');
    if (!cover || cover.dataset.coverLoaded === '1') return;
    cover.dataset.coverLoaded = '1';
    try {
        const allImages = await homeCardLoadOrderImages(order);
        const images = homeCardPickWallImages(allImages);
        if (generation !== homeCardRenderGeneration || !card.isConnected) return;
        const track = cover.querySelector('[data-home-card-media-track]');
        const dots = cover.querySelector('[data-home-card-media-dots]');
        const info = cover.querySelector('[data-home-card-media-info]');
        const prev = cover.querySelector('[data-home-card-media-prev]');
        const next = cover.querySelector('[data-home-card-media-next]');
        if (!images.length || !track) {
            cover.classList.add('no-image');
            const small = cover.querySelector('.home-order-card-cover-placeholder small');
            if (small) small.textContent = '暂无图片';
            if (prev) prev.hidden = true;
            if (next) next.hidden = true;
            return;
        }

        track.replaceChildren();
        track.dataset.imageCount = String(images.length);
        track.dataset.totalImageCount = String(allImages.length);
        track.dataset.imageIndex = '0';
        images.forEach((image, imageIndex) => {
            const slide = document.createElement('span');
            slide.className = 'home-order-card-media-slide';
            slide.dataset.homeCardMediaSlide = String(imageIndex);
            slide.dataset.mediaSource = image.source || 'order';

            const img = document.createElement('img');
            img.className = 'home-order-card-cover-img';
            img.alt = `${homeCardDisplayNumber(order)} ${image.source === 'workflow' ? '业务图片' : '主管图片'}`;
            img.loading = imageIndex === 0 ? 'eager' : 'lazy';
            img.decoding = 'async';
            img.dataset.homeCardMediaIndex = String(imageIndex);
            const url = String(image.preview_url || image.url || '').trim();
            if (imageIndex === 0) img.src = url;
            else img.dataset.src = url;
            img.addEventListener('load', () => cover.classList.add('has-image'));
            slide.appendChild(img);
            track.appendChild(slide);
        });

        if (dots) {
            dots.replaceChildren();
            if (images.length > 1) {
                images.forEach((_, imageIndex) => {
                    const dot = document.createElement('span');
                    dot.className = `home-order-card-media-dot${imageIndex === 0 ? ' active' : ''}`;
                    dot.dataset.homeCardMediaDot = String(imageIndex);
                    dots.appendChild(dot);
                });
            }
        }
        if (info) info.hidden = false;
        if (prev) {
            prev.hidden = images.length <= 1;
            prev.addEventListener('click', event => {
                event.preventDefault();
                event.stopPropagation();
                homeCardMediaStep(prev, -1);
            });
        }
        if (next) {
            next.hidden = images.length <= 1;
            next.addEventListener('click', event => {
                event.preventDefault();
                event.stopPropagation();
                homeCardMediaStep(next, 1);
            });
        }
        track.addEventListener('scroll', () => homeCardMediaScrolled(track), {passive: true});
        // Do not suppress on pointerdown: a normal click on the image must open the focus modal.
        // Actual horizontal movement is detected by the scroll handler above, which temporarily
        // suppresses opening so a swipe never turns into an accidental modal click.
        homeCardMediaSync(cover, 0);
    } catch (_) {
        cover.classList.add('no-image');
        const small = cover.querySelector('.home-order-card-cover-placeholder small');
        if (small) small.textContent = '暂无图片';
    }
}

function homeCardCoverQueueReset() {
    // Do not zero active loads: in-flight fetches from the previous generation still finish
    // asynchronously. Keeping the counter truthful prevents a rapid view toggle from briefly
    // doubling the network/decode concurrency.
    homeCardCoverQueue = [];
}

function homeCardQueueCover(card, generation) {
    if (!card || card.dataset.coverQueued === '1' || card.dataset.coverLoaded === '1') return;
    card.dataset.coverQueued = '1';
    homeCardCoverQueue.push({card, generation});
    homeCardPumpCoverQueue();
}

function homeCardPumpCoverQueue() {
    while (homeCardCoverActiveLoads < HOME_CARD_COVER_MAX_CONCURRENCY && homeCardCoverQueue.length) {
        const job = homeCardCoverQueue.shift();
        const card = job?.card;
        if (!card) continue;
        card.dataset.coverQueued = '0';
        if (!card.isConnected || job.generation !== homeCardRenderGeneration || homeOrderViewMode !== 'cards') continue;
        homeCardCoverActiveLoads += 1;
        Promise.resolve(homeCardHydrateCover(card, card.__homeOrder, job.generation))
            .finally(() => {
                homeCardCoverActiveLoads = Math.max(0, homeCardCoverActiveLoads - 1);
                homeCardPumpCoverQueue();
            });
    }
}

function homeCardObserveCovers(cards, generation) {
    if (homeCardCoverObserver) {
        try { homeCardCoverObserver.disconnect(); } catch (_) {}
        homeCardCoverObserver = null;
    }
    homeCardCoverQueueReset();
    if (!cards.length || homeOrderViewMode !== 'cards') return;

    // Only the first visible row is eager. Everything else is fetched with a small bounded
    // concurrency window when it approaches the viewport. This prevents 50 cards from firing
    // 100 file-list requests and decoding dozens of images at the same time.
    const eagerCount = Math.min(cards.length, Math.max(2, homeCardColumnCount()));
    cards.slice(0, eagerCount).forEach(card => homeCardQueueCover(card, generation));
    const remaining = cards.slice(eagerCount);
    if (!remaining.length) return;
    if (!('IntersectionObserver' in window)) {
        remaining.forEach(card => homeCardQueueCover(card, generation));
        return;
    }
    const scrollRoot = document.getElementById('homeCardWall');
    homeCardCoverObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const card = entry.target;
            homeCardCoverObserver?.unobserve(card);
            homeCardQueueCover(card, generation);
        });
    }, {root: scrollRoot || null, rootMargin: '140px 0px', threshold: 0.01});
    remaining.forEach(card => homeCardCoverObserver.observe(card));
}

function homeCardColumnCount() {
    const wall = document.getElementById('homeCardWall');
    const width = wall?.clientWidth || window.innerWidth;
    if (width >= 1560) return 5;
    if (width >= 1180) return 4;
    if (width >= 860) return 3;
    return 2;
}

function renderHomeCardPagination(total, startIndex, endIndex) {
    const info = document.getElementById('homeCardPaginationInfo');
    const controls = document.getElementById('homeCardPaginationControls');
    if (!info || !controls) return;
    if (!total) {
        info.textContent = '显示 0 到 0 共 0 条结果';
        controls.innerHTML = '';
        return;
    }
    const totalPages = Math.max(1, Math.ceil(total / TABLE_PAGE_SIZE));
    info.textContent = `显示 ${startIndex + 1} - ${endIndex}，共 ${total} 条（第 ${currentTablePage} / ${totalPages} 页）`;
    controls.innerHTML = '';
    const addButton = (label, page, active = false, disabled = false) => {
        const btn = document.createElement('button');
        btn.className = `page-btn${active ? ' active' : ''}`;
        btn.textContent = label;
        btn.disabled = disabled;
        if (!disabled) btn.onclick = () => setTablePage(page);
        controls.appendChild(btn);
    };
    addButton('上一页', currentTablePage - 1, false, currentTablePage <= 1);
    const tokens = typeof buildCompactTablePaginationTokens === 'function'
        ? buildCompactTablePaginationTokens(currentTablePage, totalPages)
        : Array.from({length:totalPages}, (_, i) => i + 1).slice(0, 9);
    tokens.forEach(token => {
        if (token === '...') {
            const span = document.createElement('span');
            span.className = 'page-ellipsis';
            span.textContent = '...';
            controls.appendChild(span);
        } else {
            addButton(String(token), Number(token), Number(token) === currentTablePage, false);
        }
    });
    addButton('下一页', currentTablePage + 1, false, currentTablePage >= totalPages);
}

function homeCardClearMultiSort() {
    if (Array.isArray(homeMultiSortRules) && homeMultiSortRules.length) {
        homeMultiSortRules = [];
        if (typeof saveHomeMultiSortRules === 'function') saveHomeMultiSortRules();
        if (typeof syncHomeMultiSortControls === 'function') syncHomeMultiSortControls();
    }
}

function syncHomeCardSortControls() {
    const select = document.getElementById('homeCardSortSelect');
    const direction = document.getElementById('homeCardSortDirection');
    if (select) select.value = currentSort?.column || '';
    if (direction) {
        direction.textContent = currentSort?.direction === 'asc' ? '↑' : '↓';
        direction.title = currentSort?.direction === 'asc' ? '目前由小到大，点击改为由大到小' : '目前由大到小，点击改为由小到大';
    }
}

function homeCardSortBy(column) {
    homeCardClearMultiSort();
    currentSort.column = String(column || '').trim() || null;
    if (currentSort.column && !['asc', 'desc'].includes(currentSort.direction)) currentSort.direction = 'desc';
    currentTablePage = 1;
    applyFilters();
    syncHomeCardSortControls();
}

function homeCardToggleSortDirection() {
    homeCardClearMultiSort();
    if (!currentSort.column) currentSort.column = 'order_date';
    currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
    currentTablePage = 1;
    applyFilters();
    syncHomeCardSortControls();
}

window.homeCardSortBy = homeCardSortBy;
window.homeCardToggleSortDirection = homeCardToggleSortDirection;

function renderHomeCardView() {
    const wall = document.getElementById('homeCardWall');
    const count = document.getElementById('homeCardViewCount');
    if (!wall) return;
    const total = homeFilteredOrdersData.length;
    const totalPages = Math.max(1, Math.ceil(total / TABLE_PAGE_SIZE));
    if (currentTablePage > totalPages) currentTablePage = totalPages;
    const startIndex = (currentTablePage - 1) * TABLE_PAGE_SIZE;
    const endIndex = Math.min(startIndex + TABLE_PAGE_SIZE, total);
    const pageItems = homeFilteredOrdersData.slice(startIndex, endIndex);
    if (count) count.textContent = `${total} 笔订单`;
    syncHomeCardSortControls();
    wall.replaceChildren();
    const generation = ++homeCardRenderGeneration;
    if (!pageItems.length) {
        const empty = document.createElement('div');
        empty.className = 'home-card-empty';
        empty.innerHTML = '<strong>没有找到符合条件的订单</strong><small>当前搜索与筛选会同时套用到表格和卡片模式。</small>';
        wall.appendChild(empty);
        renderHomeCardPagination(total, startIndex, endIndex);
        return;
    }
    const columnCount = homeCardColumnCount();
    const columns = Array.from({length:columnCount}, () => {
        const col = document.createElement('div');
        col.className = 'home-card-wall-column';
        wall.appendChild(col);
        return col;
    });
    const cards = pageItems.map((order, index) => {
        const card = createHomeOrderCard(order, index);
        columns[index % columnCount].appendChild(card);
        return card;
    });
    renderHomeCardPagination(total, startIndex, endIndex);
    homeCardObserveCovers(cards, generation);
    // A workflow action can refresh the card wall while the focus modal is open. Salesperson
    // auto-sync also rebuilds this wall every 30s/on window focus. Preserve either source.
    const restoreTop = homeCardFocusOriginScrollTop !== null
        ? homeCardFocusOriginScrollTop
        : homeCardPendingScrollRestoreTop;
    if (restoreTop !== null) {
        requestAnimationFrame(() => {
            if (wall && homeOrderViewMode === 'cards') wall.scrollTop = Math.max(0, Number(restoreTop) || 0);
        });
    }
    homeCardPendingScrollRestoreTop = null;
}

function syncHomeOrderViewModeUI() {
    const tableView = document.getElementById('desktopOrderTableView');
    const cardView = document.getElementById('homeOrderCardView');
    const switcher = document.getElementById('homeOrderViewSwitch');
    if (!tableView || !cardView || !switcher) return;
    const cards = homeOrderViewMode === 'cards';
    tableView.style.display = cards ? 'none' : '';
    cardView.hidden = !cards;
    switcher.querySelectorAll('[data-home-view-mode]').forEach(button => {
        const active = button.dataset.homeViewMode === homeOrderViewMode;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    if (cards && homeDataReady) renderHomeCardView();
    if (!cards && homeCardCoverObserver) {
        try { homeCardCoverObserver.disconnect(); } catch (_) {}
        homeCardCoverObserver = null;
        homeCardCoverQueueReset();
        homeCardRenderGeneration += 1;
    }
}

function setHomeOrderViewMode(mode) {
    const next = mode === 'cards' ? 'cards' : 'table';
    if (homeOrderViewMode === next) {
        syncHomeOrderViewModeUI();
        return;
    }
    homeOrderViewMode = next;
    try { localStorage.setItem(HOME_ORDER_VIEW_MODE_STORAGE_KEY, next); } catch (_) {}
    syncHomeOrderViewModeUI();
}

window.setHomeOrderViewMode = setHomeOrderViewMode;

document.addEventListener('DOMContentLoaded', syncHomeOrderViewModeUI);

function getHomeOrderKey(order) {
    if (!order) return '';
    const wf = String(order.workflow_number || order.workflowNumber || '').trim();
    const on = String(order.order_number || order.orderNumber || '').trim();
    return wf ? `w:${wf}` : (on ? `o:${on}` : '');
}

function mergeRenderedRowsIntoHomeData() {
    if (!homeDataReady || isGlobalSearchMode || !homeOrdersData.length) return;
    const map = new Map(homeOrdersData.map(item => [getHomeOrderKey(item), item]));
    document.querySelectorAll('#ordersTableBody tr[data-order-number]').forEach(row => {
        const key = row.dataset.workflowNumber ? `w:${row.dataset.workflowNumber}` : `o:${row.dataset.orderNumber || ''}`;
        let item = map.get(key);
        if (!item) {
            item = {
                workflow_number: row.dataset.workflowNumber || '', order_number: row.dataset.orderNumber || '',
                customer_name: row.dataset.customerName || '', order_date: row.dataset.orderDate || '',
                handler_id: row.dataset.handlerId || null, handler_name: row.dataset.handlerName || '',
                production_type: row.dataset.productionType || '', product_code: row.dataset.productCode || '',
                quantity: row.dataset.quantity || '', factory: row.dataset.factory || '', notes: row.dataset.notes || '',
                current_status: row.dataset.status || '', status_light: row.dataset.light || '',
                expected_delivery_date: row.dataset.expectedDeliveryDate || '',
                last_status_change_date: row.dataset.lastStatusChangeDate || '', status_updated_at: row.dataset.statusUpdatedAt || '',
                last_history_id: row.dataset.historyId || '', no_workflow: row.classList.contains('no-workflow-row'),
                can_edit_notes: !!row.querySelector('.notes-edit-btn')
            };
            homeOrdersData.unshift(item);
            map.set(key, item);
        }
        item.customer_name = row.dataset.customerName || item.customer_name || '';
        item.current_status = row.dataset.status || item.current_status || '';
        item.status_light = row.dataset.light || (item.current_status === STATUS.COMPLETED || item.current_status === STATUS.CANCELLED ? '' : item.status_light);
        item.handler_id = row.dataset.handlerId || item.handler_id || null;
        item.handler_name = row.dataset.handlerName || item.handler_name || '';
        item.production_type = row.dataset.productionType || item.production_type || '';
        item.product_code = row.dataset.productCode || item.product_code || '';
        item.quantity = row.dataset.quantity || item.quantity || '';
        item.factory = row.dataset.factory || item.factory || '';
        item.notes = row.dataset.notes !== undefined ? row.dataset.notes : (item.notes || '');
        item.expected_delivery_date = row.dataset.expectedDeliveryDate || item.expected_delivery_date || '';
        item.last_status_change_date = row.dataset.lastStatusChangeDate || item.last_status_change_date || '';
        item.status_updated_at = row.dataset.statusUpdatedAt || item.status_updated_at || '';
        item.last_history_id = row.dataset.historyId || item.last_history_id || '';
        item.last_shipping_date = row.dataset.lastShippingDate || item.last_shipping_date || '';
        item.last_shipping_status = row.dataset.lastShippingStatus || item.last_shipping_status || '';
        item.partial_ship_count = Number(row.dataset.partialShipCount || item.partial_ship_count || 0);
    });
}

function getHomeStageGroup(order) {
    if (order && order.no_workflow) return 'no_workflow';
    const status = normalizeStatusForLogic((order && order.current_status) || '');
    if (!status) return 'all';
    if (typeof getStageGroup === 'function') return getStageGroup(status) || 'all';
    return 'all';
}

function homeOrderMatchesCurrentFilters(order) {
    if (!order) return false;
    const workflowNumber = String(order.workflow_number || order.workflowNumber || '');
    const orderNumber = String(order.order_number || order.orderNumber || '');
    const customerName = String(order.customer_name || '');
    const status = normalizeStatusForLogic(order.current_status || '');
    const actualStageGroup = getHomeStageGroup(order);

    const selectedGroups = currentFilter.stageGroups || ['all'];
    let stageMatch = selectedGroups.includes('all');
    if (!stageMatch) {
        stageMatch = selectedGroups.includes(actualStageGroup);
        if (!stageMatch && selectedGroups.includes('waiting_confirm')) {
            if (typeof isStatusInFilter === 'function') stageMatch = isStatusInFilter(status, 'waiting_confirm');
            else stageMatch = [STATUS.QUOTE_CONFIRMING, STATUS.DRAFT_CONFIRMING, STATUS.SAMPLE_CONFIRMING].includes(status);
        }
        if (!stageMatch && selectedGroups.includes('no_workflow') && order.no_workflow) stageMatch = true;
    }
    if (!stageMatch) return false;

    if (currentFilter.substatus && currentFilter.substatus !== 'all') {
        const wanted = normalizeStatusForLogic(currentFilter.substatus);
        if (status !== wanted) return false;
    }

    if (!isGlobalSearchMode && selectedOrderNumberFilter) {
        const wanted = selectedOrderNumberFilter.trim().toLocaleLowerCase();
        if (orderNumber.toLocaleLowerCase() !== wanted && workflowNumber.toLocaleLowerCase() !== wanted) return false;
    } else if (!isGlobalSearchMode && selectedCustomerNameFilter) {
        if (customerName.trim().toLocaleLowerCase() !== selectedCustomerNameFilter.trim().toLocaleLowerCase()) return false;
    } else if (!isGlobalSearchMode && currentFilter.search) {
        const displayNumber = workflowNumber || orderNumber;
        if (!matchesMainSearch(displayNumber, customerName, currentFilter.search, order.production_type || order.product_name || '', order.product_code || '', order.factory || '', order.handler_name || '', order.notes || '')) return false;
    }

    const selectedTeam = currentFilter.teamSales || [];
    if (selectedTeam.length > 0) {
        const handlerId = String(order.handler_id || order.handlerId || '');
        if (!handlerId || !selectedTeam.includes(handlerId)) return false;
    }

    const light = String(order.status_light || '');
    if (currentFilter.lights) {
        if (light && ['red','yellow','green'].includes(light)) {
            if (currentFilter.lights[light] === false) return false;
        } else {
            const allOn = currentFilter.lights.red !== false && currentFilter.lights.yellow !== false && currentFilter.lights.green !== false;
            if (!allOn) return false;
        }
    }
    return true;
}


const HOME_MULTI_SORT_STORAGE_KEY = 'order_tracking_home_multi_sort_v1';
const HOME_MULTI_SORT_KEYS = ['order', 'kc', 'g', 'elapsed', 'date'];
let homeMultiSortRules = [];

function homeMultiSortDefaultDirection(key) {
    return ['order','kc','g'].includes(key) ? 'desc' : 'desc';
}

function loadHomeMultiSortRules() {
    try {
        const raw = localStorage.getItem(HOME_MULTI_SORT_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        if (!Array.isArray(parsed)) return [];
        return parsed.filter(item => item && HOME_MULTI_SORT_KEYS.includes(item.key)).map(item => ({
            key:item.key,
            direction:item.direction === 'asc' ? 'asc' : 'desc'
        })).slice(0, HOME_MULTI_SORT_KEYS.length);
    } catch (_) { return []; }
}

function saveHomeMultiSortRules() {
    try { localStorage.setItem(HOME_MULTI_SORT_STORAGE_KEY, JSON.stringify(homeMultiSortRules)); } catch (_) {}
}

function homeNaturalCompare(a, b, direction='desc') {
    const av = String(a || '').trim();
    const bv = String(b || '').trim();
    const cmp = av.localeCompare(bv, 'zh-CN', {numeric:true, sensitivity:'base'});
    return direction === 'asc' ? cmp : -cmp;
}

function homeOrderSortNumber(order) {
    return String(order?.workflow_number || order?.order_number || '').trim();
}

function compareHomeMultiRule(a, b, rule) {
    const key = rule?.key || '';
    const dir = rule?.direction === 'asc' ? 'asc' : 'desc';
    if (key === 'order') return homeNaturalCompare(homeOrderSortNumber(a), homeOrderSortNumber(b), dir);
    if (key === 'kc' || key === 'g') {
        const wanted = key;
        const at = mobileOrderPrefixType(a) === wanted;
        const bt = mobileOrderPrefixType(b) === wanted;
        if (at !== bt) return at ? -1 : 1;
        if (at && bt) return homeNaturalCompare(homeOrderSortNumber(a), homeOrderSortNumber(b), dir);
        return 0;
    }
    if (key === 'elapsed') {
        const av = Number(a?.status_days || 0), bv = Number(b?.status_days || 0);
        return dir === 'asc' ? av - bv : bv - av;
    }
    if (key === 'date') {
        const av = a?.order_date ? new Date(a.order_date).getTime() : NaN;
        const bv = b?.order_date ? new Date(b.order_date).getTime() : NaN;
        if (Number.isNaN(av) && Number.isNaN(bv)) return 0;
        if (Number.isNaN(av)) return 1;
        if (Number.isNaN(bv)) return -1;
        return dir === 'asc' ? av - bv : bv - av;
    }
    return 0;
}

function applyHomeMultiSort(data) {
    if (!Array.isArray(homeMultiSortRules) || !homeMultiSortRules.length) return null;
    return data.slice().sort((a,b) => {
        for (const rule of homeMultiSortRules) {
            const cmp = compareHomeMultiRule(a,b,rule);
            if (cmp) return cmp;
        }
        return homeNaturalCompare(homeOrderSortNumber(a), homeOrderSortNumber(b), 'desc');
    });
}

function toggleHomeMultiSortRule(key) {
    if (!HOME_MULTI_SORT_KEYS.includes(key)) return;
    const idx = homeMultiSortRules.findIndex(item => item.key === key);
    if (idx >= 0) homeMultiSortRules.splice(idx, 1);
    else homeMultiSortRules.push({key, direction:homeMultiSortDefaultDirection(key)});
    saveHomeMultiSortRules();
    syncHomeMultiSortControls();
    currentTablePage = 1;
    applyFilters();
}

function toggleHomeMultiSortDirection(key, event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const item = homeMultiSortRules.find(rule => rule.key === key);
    if (!item) {
        homeMultiSortRules.push({key, direction:homeMultiSortDefaultDirection(key)});
    } else {
        item.direction = item.direction === 'asc' ? 'desc' : 'asc';
    }
    saveHomeMultiSortRules();
    syncHomeMultiSortControls();
    currentTablePage = 1;
    applyFilters();
}

function clearHomeMultiSortRules() {
    homeMultiSortRules = [];
    saveHomeMultiSortRules();
    syncHomeMultiSortControls();
    currentTablePage = 1;
    applyFilters();
}

function syncHomeMultiSortControls() {
    document.querySelectorAll('[data-home-multi-sort]').forEach(button => {
        const key = button.dataset.homeMultiSort;
        const idx = homeMultiSortRules.findIndex(item => item.key === key);
        button.classList.toggle('active', idx >= 0);
        const priority = button.querySelector('[data-sort-priority]');
        if (priority) priority.textContent = idx >= 0 ? String(idx + 1) : '';
    });
    document.querySelectorAll('[data-home-sort-dir]').forEach(button => {
        const item = homeMultiSortRules.find(rule => rule.key === button.dataset.homeSortDir);
        button.hidden = !item;
        if (item) button.textContent = item.direction === 'asc' ? '↑' : '↓';
    });
    document.querySelectorAll('[data-home-sort-clear]').forEach(button => { button.hidden = !homeMultiSortRules.length; });
}

homeMultiSortRules = loadHomeMultiSortRules();

// Mobile "按订单" controls: type visibility is multi-select; sorting is single-select.
// [全部 / 订单 / KC / G] decides which number families are visible.
// Sorting is always exactly one mode: number (implicit), elapsed days, or date.
const MOBILE_ORDER_VIEW_PREF_KEY = 'order_tracking_mobile_order_view_v2';
let mobileOrderTypeFilters = new Set(['order', 'kc', 'g']);
let mobileOrderSortMode = 'number';
let mobileOrderSortDirection = 'desc';

function loadMobileOrderViewPrefs() {
    try {
        const raw = localStorage.getItem(MOBILE_ORDER_VIEW_PREF_KEY);
        if (!raw) return;
        const saved = JSON.parse(raw);
        const types = Array.isArray(saved?.types) ? saved.types.filter(x => ['order','kc','g'].includes(x)) : [];
        if (types.length) mobileOrderTypeFilters = new Set(types);
        if (['number','elapsed','date'].includes(saved?.sortMode)) mobileOrderSortMode = saved.sortMode;
        mobileOrderSortDirection = saved?.direction === 'asc' ? 'asc' : 'desc';
    } catch (_) {}
}

function saveMobileOrderViewPrefs() {
    try {
        localStorage.setItem(MOBILE_ORDER_VIEW_PREF_KEY, JSON.stringify({
            types:Array.from(mobileOrderTypeFilters),
            sortMode:mobileOrderSortMode,
            direction:mobileOrderSortDirection
        }));
    } catch (_) {}
}

function mobileOrderViewType(order) {
    const type = mobileOrderPrefixType(order);
    return type === 'kc' ? 'kc' : (type === 'g' ? 'g' : 'order');
}

function mobileSetOrderTypeAll() {
    mobileOrderTypeFilters = new Set(['order','kc','g']);
    saveMobileOrderViewPrefs();
    syncMobileOrderViewControls();
    mobileVisibleLimit = 60;
    renderMobileExperience(true);
}

function mobileToggleOrderType(type) {
    if (!['order','kc','g'].includes(type)) return;
    const next = new Set(mobileOrderTypeFilters);
    if (next.has(type)) {
        // Never allow an empty result family selection.
        if (next.size === 1) return;
        next.delete(type);
    } else {
        next.add(type);
    }
    mobileOrderTypeFilters = next;
    saveMobileOrderViewPrefs();
    syncMobileOrderViewControls();
    mobileVisibleLimit = 60;
    renderMobileExperience(true);
}

function mobileSetOrderSortMode(mode) {
    if (!['number','elapsed','date'].includes(mode)) return;
    // Clicking the active elapsed/date chip again returns to normal number sorting.
    if (mode !== 'number' && mobileOrderSortMode === mode) mobileOrderSortMode = 'number';
    else mobileOrderSortMode = mode;
    saveMobileOrderViewPrefs();
    syncMobileOrderViewControls();
    mobileVisibleLimit = 60;
    renderMobileExperience(true);
}

function mobileToggleOrderSortDirection() {
    mobileOrderSortDirection = mobileOrderSortDirection === 'asc' ? 'desc' : 'asc';
    saveMobileOrderViewPrefs();
    syncMobileOrderViewControls();
    renderMobileExperience(true);
}

function syncMobileOrderViewControls() {
    const allSelected = ['order','kc','g'].every(key => mobileOrderTypeFilters.has(key));
    document.querySelectorAll('[data-mobile-order-type]').forEach(btn => {
        const key = btn.dataset.mobileOrderType;
        const active = key === 'all' ? allSelected : mobileOrderTypeFilters.has(key);
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    document.querySelectorAll('[data-mobile-order-sort-mode]').forEach(btn => {
        const key = btn.dataset.mobileOrderSortMode;
        const active = mobileOrderSortMode === key;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    const dir = document.getElementById('mobileOrderSortDirection');
    if (dir) {
        dir.textContent = mobileOrderSortDirection === 'asc' ? '↑' : '↓';
        const es = window.getTrackingLanguage?.() === 'es';
        const modeLabel = mobileOrderSortMode === 'elapsed'
            ? (es ? 'días' : '历时')
            : mobileOrderSortMode === 'date'
                ? (es ? 'fecha' : '日期')
                : (es ? 'número' : '编号');
        const directionLabel = mobileOrderSortDirection === 'asc'
            ? (es ? 'ascendente' : '由小到大')
            : (es ? 'descendente' : '由大到小');
        dir.title = `${modeLabel} · ${directionLabel}`;
        dir.setAttribute('aria-label', dir.title);
    }
}

function mobileCompareOrderView(a, b) {
    const dir = mobileOrderSortDirection === 'asc' ? 1 : -1;
    if (mobileOrderSortMode === 'elapsed') {
        const av = Number(a?.status_days || 0);
        const bv = Number(b?.status_days || 0);
        if (av !== bv) return (av - bv) * dir;
    } else if (mobileOrderSortMode === 'date') {
        const av = a?.order_date ? new Date(a.order_date).getTime() : NaN;
        const bv = b?.order_date ? new Date(b.order_date).getTime() : NaN;
        if (Number.isNaN(av) !== Number.isNaN(bv)) return Number.isNaN(av) ? 1 : -1;
        if (!Number.isNaN(av) && av !== bv) return (av - bv) * dir;
    } else {
        // When more than one number family is visible, keep the business grouping
        // stable regardless of ↑/↓: normal 100... orders first, then G, then KC.
        // The arrow only changes the numeric order INSIDE each family.
        if (mobileOrderTypeFilters.size > 1) {
            const familyRank = {order:0, g:1, kc:2};
            const aRank = familyRank[mobileOrderViewType(a)] ?? 9;
            const bRank = familyRank[mobileOrderViewType(b)] ?? 9;
            if (aRank !== bRank) return aRank - bRank;
        }
        const av = String(mobileOrderDisplayNumber(a) || '').trim();
        const bv = String(mobileOrderDisplayNumber(b) || '').trim();
        const cmp = av.localeCompare(bv, 'zh-CN', {numeric:true, sensitivity:'base'});
        if (cmp) return cmp * dir;
    }
    return String(getHomeOrderKey(a) || '').localeCompare(String(getHomeOrderKey(b) || ''), 'zh-CN', {numeric:true, sensitivity:'base'}) * dir;
}

loadMobileOrderViewPrefs();

const MOBILE_FILTER_EXPANDED_KEY = 'order_tracking_mobile_filters_expanded_v1';
const DESKTOP_FILTER_COLLAPSED_KEY = 'order_tracking_desktop_filters_collapsed_v1';

function setMobileExtraFiltersExpanded(expanded) {
    const box = document.getElementById('mobileExtraFilters');
    const btn = document.getElementById('mobileFilterExpandBtn');
    if (box) box.classList.toggle('collapsed', !expanded);
    if (btn) btn.textContent = expanded
        ? (window.getTrackingLanguage?.() === 'es' ? 'Ocultar' : '收起')
        : (window.getTrackingLanguage?.() === 'es' ? 'Mostrar todo' : '展开全部');
    try { localStorage.setItem(MOBILE_FILTER_EXPANDED_KEY, expanded ? '1':'0'); } catch (_) {}
}

function toggleMobileExtraFilters() {
    const box = document.getElementById('mobileExtraFilters');
    const expanded = !!box && box.classList.contains('collapsed');
    setMobileExtraFiltersExpanded(expanded);
}

function restoreMobileExtraFilters() {
    let expanded = false;
    try { expanded = localStorage.getItem(MOBILE_FILTER_EXPANDED_KEY) === '1'; } catch (_) {}
    setMobileExtraFiltersExpanded(expanded);
}

function setDesktopFilterDetailsCollapsed(collapsed) {
    const box = document.getElementById('desktopFilterDetails');
    const btn = document.getElementById('desktopFilterExpandBtn');
    if (box) box.classList.toggle('collapsed', !!collapsed);
    if (btn) btn.textContent = collapsed ? '展开全部筛选' : '收起筛选';
    try { localStorage.setItem(DESKTOP_FILTER_COLLAPSED_KEY, collapsed ? '1':'0'); } catch (_) {}
}

function toggleDesktopFilterDetails() {
    const box = document.getElementById('desktopFilterDetails');
    setDesktopFilterDetailsCollapsed(!(box?.classList.contains('collapsed')));
}

function restoreDesktopFilterDetails() {
    // First visit keeps only the first filter row visible. Each workstation/browser
    // remembers its own preference after the user expands or collapses it.
    let collapsed = true;
    try {
        const saved = localStorage.getItem(DESKTOP_FILTER_COLLAPSED_KEY);
        if (saved === '0') collapsed = false;
        else if (saved === '1') collapsed = true;
    } catch (_) {}
    setDesktopFilterDetailsCollapsed(collapsed);
}


document.addEventListener('DOMContentLoaded', () => {
    syncHomeMultiSortControls();
    syncMobileOrderViewControls();
    restoreMobileExtraFilters();
    // Desktop keeps the full filter area visible; collapse/expand is mobile-only.
});

function getHomeSortValue(order, column) {
    if (!order) return '';
    const today = new Date();
    switch (column) {
        case 'order_number': return order.workflow_number || order.order_number || '';
        case 'customer_name': return order.customer_name || '';
        case 'production_type': return order.production_type || order.product_name || '';
        case 'product_code': return order.product_code || '';
        case 'quantity': return parseFloat(order.quantity) || 0;
        case 'factory': return order.factory || '';
        case 'current_status': return (typeof displayStatus === 'function') ? displayStatus(order.current_status || '') : (order.current_status || '');
        case 'status_days': return Number(order.status_days || 0);
        case 'order_date': return order.order_date || '';
        case 'expected_delivery_date': return order.expected_delivery_date || '';
        case 'order_age': {
            const d = order.order_date ? new Date(`${String(order.order_date).slice(0,10)}T00:00:00`) : null;
            return d && !Number.isNaN(d.getTime()) ? Math.max(0, Math.floor((today - d) / 86400000)) : 0;
        }
        default: return '';
    }
}

function sortHomeOrders(data) {
    const multi = applyHomeMultiSort(data);
    if (multi) return multi;
    if (!currentSort || !currentSort.column) return data;
    const col = currentSort.column;
    const dir = currentSort.direction === 'desc' ? -1 : 1;
    return data.slice().sort((a,b) => {
        const av = getHomeSortValue(a,col);
        const bv = getHomeSortValue(b,col);
        if (['quantity','status_days','order_age'].includes(col)) return ((Number(av)||0) - (Number(bv)||0)) * dir;
        if (['order_date','expected_delivery_date'].includes(col)) {
            const at = av ? new Date(av).getTime() : NaN;
            const bt = bv ? new Date(bv).getTime() : NaN;
            if (Number.isNaN(at) && Number.isNaN(bt)) return 0;
            if (Number.isNaN(at)) return 1;
            if (Number.isNaN(bt)) return -1;
            return (at - bt) * dir;
        }
        return String(av || '').localeCompare(String(bv || ''), 'zh-CN', {numeric:true, sensitivity:'base'}) * dir;
    });
}

function renderHomeOrdersPage() {
    const tbody = document.getElementById('ordersTableBody');
    if (!tbody) return;
    const total = homeFilteredOrdersData.length;
    const totalPages = Math.max(1, Math.ceil(total / TABLE_PAGE_SIZE));
    if (currentTablePage > totalPages) currentTablePage = totalPages;
    const startIndex = (currentTablePage - 1) * TABLE_PAGE_SIZE;
    const endIndex = Math.min(startIndex + TABLE_PAGE_SIZE, total);
    tbody.innerHTML = '';
    const fragment = document.createDocumentFragment();
    homeFilteredOrdersData.slice(startIndex, endIndex).forEach(order => fragment.appendChild(createOrderRow(order)));
    tbody.appendChild(fragment);
    applyColumnSettings();
    const emptyState = document.getElementById('emptyState');
    if (emptyState) {
        emptyState.style.display = total === 0 ? 'block' : 'none';
        const textNode = emptyState.querySelector('[data-empty-message]');
        if (textNode) {
            const es = typeof window.getTrackingLanguage === 'function' && window.getTrackingLanguage() === 'es';
            textNode.textContent = (isCloudMode() && !cloudProviderReady)
                ? (es ? 'Aún no hay pedidos sincronizados; Render está funcionando correctamente.' : '尚未同步云端订单资料；Render 已可正常运行。')
                : (es ? 'No se encontraron pedidos que coincidan.' : '没有找到符合条件的订单');
        }
    }
    renderTablePagination(total, startIndex, endIndex);
    syncHomeOrderViewModeUI();
    if (typeof renderMobileExperience === 'function') renderMobileExperience();
    if (typeof updateOrderAgeColumn === 'function') updateOrderAgeColumn();
    if (typeof initQuickActionsForAllRows === 'function') initQuickActionsForAllRows();
    if (typeof refreshStatusDaysFromRows === 'function') refreshStatusDaysFromRows();
}

async function loadHomeOrdersData(silent = false) {
    if (homeDataLoading) return;
    // Salesperson accounts run an automatic 30s/focus refresh while managers do not.
    // Capture the current viewport before that silent refresh; otherwise rebuilding the
    // table/card DOM can clamp the scroll container back to 0.
    const silentScrollSnapshot = silent ? homeCaptureSilentRefreshScroll() : null;
    if (silentScrollSnapshot && silentScrollSnapshot.cardTop !== null) {
        homeCardPendingScrollRestoreTop = silentScrollSnapshot.cardTop;
    }
    homeDataLoading = true;
    try {
        const response = await fetch('/tracking/api/orders/all-for-filter', {credentials:'same-origin'});
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || ((window.getTrackingLanguage?.() === 'es') ? 'Error al cargar' : '载入失败'));
        const nextHomeOrdersData = Array.isArray(result.data) ? result.data : [];
        const nextRenderSignature = homeOrdersUiSignature(nextHomeOrdersData);
        const shouldRenderHome = !homeDataReady || !silent || nextRenderSignature !== homeOrdersRenderSignature;
        if (shouldRenderHome) {
            homeOrdersData = nextHomeOrdersData;
            homeOrdersRenderSignature = nextRenderSignature;
        }
        if (typeof result.provider_ready === 'boolean') {
            cloudProviderReady = result.provider_ready;
            if (document.body) document.body.dataset.cloudProviderReady = result.provider_ready ? 'true' : 'false';
        }
        if (isCloudMode()) {
            const syncStatus = document.getElementById('cloudSyncStatus');
            const banner = document.getElementById('cloudReadonlyBanner');
            if (banner) banner.classList.toggle('cloud-provider-waiting', !cloudProviderReady);
            if (syncStatus) {
                const updatedLabel = typeof window.trackingT === 'function' ? window.trackingT('cloud.updated_at') : '资料更新于：';
                const waitLabel = typeof window.trackingT === 'function' ? window.trackingT('cloud.wait_first') : '等待首次同步';
                const noDataLabel = typeof window.trackingT === 'function' ? window.trackingT('cloud.no_data') : '尚未连接云端订单资料';
                syncStatus.innerHTML = cloudProviderReady
                    ? `<span data-i18n="cloud.updated_at">${updatedLabel}</span><strong id="cloudLastSyncedAt">${result.last_synced_at || waitLabel}</strong>`
                    : `<strong data-i18n="cloud.no_data">${noDataLabel}</strong>`;
            }
        }
        homeDataReady = true;
        if (shouldRenderHome) {
            updateFilterCounts();
            applyFilters();
            if (silentScrollSnapshot) homeRestoreSilentRefreshScroll(silentScrollSnapshot);
        }
    } catch (error) {
        console.error('[home data] load failed:', error);
        const tbody = document.getElementById('ordersTableBody');
        if (tbody) tbody.innerHTML = `<tr><td colspan="16" style="padding:40px;text-align:center;color:#c62828">${window.getTrackingLanguage?.() === 'es' ? 'Error al cargar pedidos' : '订单资料载入失败'}：${String(error.message || error)}</td></tr>`;
        const cardWall = document.getElementById('homeCardWall');
        if (cardWall) cardWall.innerHTML = `<div class="home-card-empty error"><strong>${window.getTrackingLanguage?.() === 'es' ? 'Error al cargar pedidos' : '订单资料载入失败'}</strong><small>${homeCardEscape(String(error.message || error))}</small></div>`;
        const mobileList = document.getElementById('mobileOrdersList');
        if (mobileList) mobileList.innerHTML = `<div class="mobile-empty error">${window.getTrackingLanguage?.() === 'es' ? 'Error al cargar pedidos' : '订单资料载入失败'}：${String(error.message || error)}</div>`;
        if (!silent && typeof showToast === 'function') showToast(window.getTrackingLanguage?.() === 'es' ? 'Error' : '错误', window.getTrackingLanguage?.() === 'es' ? 'No se pudieron cargar los pedidos.' : '首页订单资料载入失败', 'error');
    } finally {
        homeDataLoading = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => loadHomeOrdersData(false), 0);
});

// ==================== 狀態正規化（Key / 中文兼容）====================
// 統一處理：數據庫可能存 key（如 'NEW_ORDER'）或中文（如 '新订单'）
// 這個函數確保邏輯判斷時使用統一的格式
function normalizeStatusForLogic(status) {
    const s = (status || '').trim();
    if (!s) return '';
    
    // 如果是 key（在 STATUS 中），直接返回
    if (typeof STATUS !== 'undefined' && Object.values(STATUS).includes(s)) {
        return s;
    }
    
    // 如果是中文，嘗試找到對應的 key（向后兼容）
    if (typeof STATUS !== 'undefined' && typeof STATUS_LABELS !== 'undefined') {
        for (const [key, labels] of Object.entries(STATUS_LABELS)) {
            if (labels.zh_cn === s || labels.zh_tw === s) {
                return STATUS[key];  // 返回 key
            }
        }
    }
    
    // 如果找不到對應的 key，可能是舊的中文狀態，嘗試繁簡轉換
    if (typeof DISPLAY_MAP !== 'undefined') {
        // DISPLAY_MAP: { 简体: 繁体 } → 反查繁体對應的简体
        for (const [simp, trad] of Object.entries(DISPLAY_MAP)) {
            if (trad === s) return simp;
        }
    }
    
    // 如果都找不到，返回原值（向后兼容）
    return s;
}

// 阶段映射（用于动态生成阶段筛选按钮）- 统一使用 STATUS_SYSTEM.js
// 等待 STATUS_SYSTEM.js 加载后初始化
let stageMap = {
    'all': ['all', 'new_and_quote', 'draft', 'sampling', 'production']
};

// 初始化阶段映射（从 STATUS_SYSTEM.js 获取）
function initStageMap() {
    if (typeof getStageMap === 'function') {
        const systemMap = getStageMap();
        stageMap = {
            'all': ['all', 'new_and_quote', 'draft', 'sampling', 'production'],
            ...systemMap
        };
    }
}

// 页面加载后初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initStageMap);
} else {
    // 如果已经加载，延迟一点确保 STATUS_SYSTEM.js 已加载
    setTimeout(initStageMap, 100);
}

const stageNames = {
    '全部': 'all',
    '新订单': '新订单',
    '报价待确认': '报价待确认',
    '图稿待确认': '图稿待确认',
    '图稿修改中': '图稿修改中',
    '待打样': '待打样',
    '打样中': '打样中',
    '打样待确认': '打样待确认',
    '打样修改中': '打样修改中',
    '待生产': '待生产',
    '生产中': '生产中'
};

function parseOrderSearchToken(token) {
    const text = String(token || '').trim();
    const match = text.match(/^([A-Za-z]*)(\d+)$/);
    if (!match) return null;
    const prefix = (match[1] || '').toUpperCase();
    const digitsRaw = match[2];
    return {
        prefix,
        digits: parseInt(digitsRaw, 10),
        normalized: `${prefix}${digitsRaw}`
    };
}

function matchesMainSearch(orderNumber, customerName, searchText, productionType = '', productCode = '', factory = '', handlerName = '', notes = '') {
    const rawSearch = String(searchText || '').trim();
    if (!rawSearch) return true;
    const orderRaw = String(orderNumber || '');
    const customerRaw = String(customerName || '');
    const searchLower = rawSearch.toLowerCase();

    // 範圍搜索（含 ~）走專門邏輯
    if (rawSearch.includes('~')) {
        const orderUpper = orderRaw.toUpperCase();
        const customerLower = customerRaw.toLowerCase();
        const startToken = rawSearch.split('~')[0].trim();
        const rightPart = rawSearch.slice(rawSearch.indexOf('~') + 1).trim();
        if (!startToken || !rightPart) return false;
        const rightSegs = rightPart.split(/\s+/, 2);
        const endToken = (rightSegs[0] || '').trim();
        const customerKeyword = rightPart.slice(endToken.length).trim().toLowerCase();
        const start = parseOrderSearchToken(startToken);
        const end = parseOrderSearchToken(endToken);
        const current = parseOrderSearchToken(orderRaw);
        if (!start || !end || !current) return false;
        if (start.prefix !== end.prefix || current.prefix !== start.prefix) return false;
        if (start.digits > end.digits) return false;
        const inRange = current.digits >= start.digits && current.digits <= end.digits;
        if (!inRange) return false;
        return customerKeyword ? customerLower.includes(customerKeyword) : true;
    }

    // 所有欄位模糊搜索
    const allFields = [orderRaw, customerRaw, productionType, productCode, factory, handlerName, notes];
    return allFields.some(f => String(f || '').toLowerCase().includes(searchLower));
}


function buildCompactTablePaginationTokens(page, totalPages) {
    if (totalPages <= 0) return [];
    const out = [];
    const push = (v) => {
        if (out[out.length - 1] !== v) out.push(v);
    };
    if (totalPages <= 7) {
        for (let i = 1; i <= totalPages; i++) push(i);
    } else if (page <= 3) {
        push(1); push(2); push(3); push(4); push('...'); push(totalPages);
    } else if (page >= totalPages - 2) {
        push(1); push('...'); push(totalPages - 3); push(totalPages - 2); push(totalPages - 1); push(totalPages);
    } else {
        push(1); push('...'); push(page - 1); push(page); push(page + 1); push('...'); push(totalPages);
    }
    return out;
}

// 筛选函数（参考 v10.html 逻辑）
function applyFiltersLegacyDom() {
    const rows = Array.from(document.querySelectorAll('#ordersTableBody tr'));
    const mainRows = rows.filter(row => row.dataset.orderNumber);
    const detailRows = rows.filter(row => row.classList.contains('detail-row'));
    let visibleCount = 0;
    const matchedRows = [];
    const signature = JSON.stringify({
        stageGroups: currentFilter.stageGroups,
        substatus: currentFilter.substatus,
        search: currentFilter.search,
        customerExact: selectedCustomerNameFilter,
        orderExact: selectedOrderNumberFilter,
        lights: currentFilter.lights,
        teamSales: currentFilter.teamSales
    });
    if (!isPaginating && lastFilterSignature !== signature) {
        currentTablePage = 1;
    }
    lastFilterSignature = signature;
    isPaginating = false;

    mainRows.forEach(row => {
        const orderNumber = row.dataset.workflowNumber || row.dataset.orderNumber || '';
        const customerName = row.dataset.customerName || '';
        const productionType = row.dataset.productionType || '';
        const productCode = row.dataset.productCode || '';
        const factory = row.dataset.factory || '';
        const handlerName = row.dataset.handlerName || '';
        const notes = row.dataset.notes || '';
        const statusRaw = row.dataset.status || '';
        const status = normalizeStatusForLogic(statusRaw);
        const stageGroup = row.dataset.stageGroup || '';
        
        // Stage Group 篩選（多選）
        let stageGroupMatch = false;
        const selectedGroups = currentFilter.stageGroups || ['all'];
        if (selectedGroups.includes('all')) {
                    stageGroupMatch = true;
                } else {
            let actualStageGroup = stageGroup;
            if (typeof getStageGroup === 'function' && status) {
                actualStageGroup = getStageGroup(status);
            }

            if (selectedGroups.includes('waiting_confirm')) {
                if (typeof isStatusInFilter === 'function') {
                    stageGroupMatch = isStatusInFilter(status, 'waiting_confirm');
                } else if (typeof STAGE_GROUPS !== 'undefined' && STAGE_GROUPS.waiting_confirm) {
                    const waitingConfirmStatuses = STAGE_GROUPS.waiting_confirm.statuses;
                    stageGroupMatch = waitingConfirmStatuses && waitingConfirmStatuses.includes(status);
                } else {
                    stageGroupMatch = status === STATUS.QUOTE_CONFIRMING || 
                                     status === STATUS.DRAFT_CONFIRMING || 
                                     status === STATUS.SAMPLE_CONFIRMING;
                }
            }

            if (!stageGroupMatch && actualStageGroup) {
                stageGroupMatch = selectedGroups.includes(actualStageGroup);
            }
            // 無流程篩選
            if (!stageGroupMatch && selectedGroups.includes('no_workflow')) {
                stageGroupMatch = row.classList.contains('no-workflow-row');
            }
        }
        
        // 子状态筛选（支持 key 和中文）
        let substatusMatch = true;
        if (currentFilter.substatus !== 'all') {
            const filterStatus = currentFilter.substatus;
            // 正規化 filterStatus：如果是中文，轉換成 key
            let filterStatusKey = filterStatus;
            if (typeof STATUS_LABELS !== 'undefined') {
                // 嘗試從中文找到對應的 key
                for (const [key, labels] of Object.entries(STATUS_LABELS)) {
                    if (labels.zh_cn === filterStatus || labels.zh_tw === filterStatus) {
                        filterStatusKey = STATUS[key];
                        break;
                    }
                }
            }
            // 匹配：status 可能是 key 或中文，filterStatus 也可能是 key 或中文
            substatusMatch = (
                status === filterStatus ||  // 直接匹配
                status === filterStatusKey ||  // status 是 key，filterStatus 是中文
                normalizeStatusForLogic(status) === filterStatusKey  // status 是中文，轉換後匹配
            );
        }
        
        // 已完成/已取消筛选（当选择了特定阶段时）
        let completedMatch = true;
        if (currentFilter.stageGroup === 'completed' && !currentFilter.showCompleted) {
            completedMatch = false;
        }
        if (currentFilter.stageGroup === 'cancelled' && !currentFilter.showCancelled) {
            completedMatch = false;
        }
        
        // 搜索筛选（全局搜索模式下後端已處理，跳過前端過濾）
        let searchMatch = true;
        if (!isGlobalSearchMode && selectedOrderNumberFilter) {
            const rowOrder = String(row.dataset.orderNumber || '').trim().toLocaleLowerCase();
            const rowWorkflow = String(row.dataset.workflowNumber || '').trim().toLocaleLowerCase();
            const expected = selectedOrderNumberFilter.trim().toLocaleLowerCase();
            searchMatch = rowOrder === expected || rowWorkflow === expected;
        } else if (!isGlobalSearchMode && selectedCustomerNameFilter) {
            searchMatch = String(customerName || '').trim().toLocaleLowerCase() === selectedCustomerNameFilter.trim().toLocaleLowerCase();
        } else if (currentFilter.search && !isGlobalSearchMode) {
            searchMatch = matchesMainSearch(orderNumber, customerName, currentFilter.search, productionType, productCode, factory, handlerName, notes);
        }

        // 我的团队筛选（主管多选）
        let teamMatch = true;
        const selectedTeam = currentFilter.teamSales || [];
        if (selectedTeam.length > 0) {
        const handlerId = row.dataset.handlerId || '';
        teamMatch = handlerId && selectedTeam.includes(handlerId);
        }
        
        // 燈號篩選
        let lightMatch = true;
        const light = row.dataset.light || '';
        if (currentFilter.lights) {
            if (light) {
                // 有燈的：該燈號被設為 false 則隱藏
                lightMatch = currentFilter.lights[light] !== false;
            } else {
                // 沒燈的（已完成/已取消）：三個燈都亮才顯示，否則隱藏
                const allOn = currentFilter.lights['red'] !== false
                           && currentFilter.lights['yellow'] !== false
                           && currentFilter.lights['green'] !== false;
                lightMatch = allOn;
            }
        }
        
        // 显示或隐藏
        if (stageGroupMatch && substatusMatch && completedMatch && searchMatch && teamMatch && lightMatch) {
            matchedRows.push(row);
        }
    });

    lastFilteredRowsForExport = matchedRows.slice();

    const total = matchedRows.length;
    const totalPages = Math.max(1, Math.ceil(total / TABLE_PAGE_SIZE));
    if (currentTablePage > totalPages) currentTablePage = totalPages;
    const startIndex = (currentTablePage - 1) * TABLE_PAGE_SIZE;
    const endIndex = startIndex + TABLE_PAGE_SIZE;

    mainRows.forEach(row => {
        row.style.display = 'none';
    });

    matchedRows.forEach((row, index) => {
        if (index >= startIndex && index < endIndex) {
            row.style.display = '';
            visibleCount++;
        }
    });

    detailRows.forEach(row => {
        const key = row.dataset.detailFor || '';
        const mainRow = document.querySelector(`#ordersTableBody tr[data-workflow-number="${key}"], #ordersTableBody tr[data-order-number="${key}"]`);
        if (!mainRow || mainRow.style.display === 'none') {
            row.style.display = 'none';
        } else if (row.classList.contains('show')) {
            row.style.display = 'table-row';
        } else {
            row.style.display = 'none';
        }
    });
    
    // 更新空状态显示
    const emptyState = document.getElementById('emptyState');
    if (emptyState) {
        emptyState.style.display = total === 0 ? 'block' : 'none';
    }
    renderTablePagination(total, startIndex, Math.min(endIndex, total));
}

function applyFilters() {
    if (isGlobalSearchMode || !homeDataReady) {
        if (isGlobalSearchMode) return applyFiltersLegacyDom();
        return;
    }
    mergeRenderedRowsIntoHomeData();
    const signature = JSON.stringify({stageGroups:currentFilter.stageGroups, substatus:currentFilter.substatus, search:currentFilter.search, customerExact:selectedCustomerNameFilter, orderExact:selectedOrderNumberFilter, lights:currentFilter.lights, teamSales:currentFilter.teamSales, sort:currentSort, multiSort:homeMultiSortRules});
    if (!isPaginating && lastFilterSignature !== signature) currentTablePage = 1;
    lastFilterSignature = signature;
    isPaginating = false;
    homeFilteredOrdersData = sortHomeOrders(homeOrdersData.filter(homeOrderMatchesCurrentFilters));
    lastFilteredRowsForExport = homeFilteredOrdersData.slice();
    renderHomeOrdersPage();
}

function renderTablePagination(total, startIndex, endIndex) {
    const info = document.getElementById('paginationInfo');
    const controls = document.getElementById('paginationControls');
    if (!info || !controls) return;

    if (total === 0) {
        info.textContent = '显示 0 到 0 共 0 条结果';
        controls.innerHTML = '';
        return;
    }

    const totalPages = Math.max(1, Math.ceil(total / TABLE_PAGE_SIZE));
    const start = startIndex + 1;
    const end = endIndex;
    info.textContent = `显示 ${start} - ${end}，共 ${total} 条（第 ${currentTablePage} / ${totalPages} 页）`;

    controls.innerHTML = '';
    const prevBtn = document.createElement('button');
    prevBtn.className = 'page-btn';
    prevBtn.textContent = '上一页';
    prevBtn.disabled = currentTablePage === 1;
    prevBtn.onclick = () => setTablePage(currentTablePage - 1);
    controls.appendChild(prevBtn);

    const tokens = buildCompactTablePaginationTokens(currentTablePage, totalPages);
    tokens.forEach(token => {
        if (token === '...') {
            const span = document.createElement('span');
            span.className = 'page-ellipsis';
            span.textContent = '...';
            controls.appendChild(span);
            return;
        }
        const btn = document.createElement('button');
        btn.className = 'page-btn' + (token === currentTablePage ? ' active' : '');
        btn.textContent = String(token);
        btn.onclick = () => setTablePage(token);
        controls.appendChild(btn);
    });

    const nextBtn = document.createElement('button');
    nextBtn.className = 'page-btn';
    nextBtn.textContent = '下一页';
    nextBtn.disabled = currentTablePage === totalPages;
    nextBtn.onclick = () => setTablePage(currentTablePage + 1);
    controls.appendChild(nextBtn);
}

function setTablePage(page) {
    const total = (homeDataReady && !isGlobalSearchMode)
        ? homeFilteredOrdersData.length
        : document.querySelectorAll('#ordersTableBody tr[data-order-number]').length;
    const totalPages = Math.max(1, Math.ceil(total / TABLE_PAGE_SIZE));
    const targetPage = Math.min(Math.max(1, page), totalPages);
    if (targetPage === currentTablePage) return;
    currentTablePage = targetPage;
    isPaginating = true;
    applyFilters();
}

// 更新筛选提示（目前未在模板中使用，但保留）
function updateFilterHint(count) {
    const tabNames = {
        'all': '全部进行中',
        'waiting_confirm': '等国外确认',
        'draft': '图稿阶段',
        'sampling': '打样阶段',
        'production': '生产阶段',
        'completed': '已完成',
        'cancelled': '已取消'
    };
    
    const stageNamesMap = {
        'all': '全部流程',
        '新订单': '新订单',
        '图稿待确认': '图稿待确认',
        '图稿修改中': '图稿修改中',
        '待打样': '待打样',
        '打样中': '打样中',
        '打样待确认': '打样待确认',
        '打样修改中': '打样修改中',
        '待生产': '待生产',
        '生产中': '生产中'
    };
    
    const lightNames = {
        'all': '全部状态',
        'red': '逾期',
        'yellow': '需注意',
        'green': '正常'
    };
    
    const tabName = tabNames[currentFilter.tab] || '全部进行中';
    const stageName = stageNamesMap[currentFilter.stage] || '全部流程';
    const lightName = lightNames[currentFilter.light] || '全部状态';
    
    const hintEl = document.getElementById('filterHint');
    if (hintEl) {
        hintEl.innerHTML = `
        当前显示: <strong>${tabName}</strong> · <strong>${stageName}</strong> · <strong>${lightName}</strong> · 共 <strong id="filterCount">${count}</strong> 个订单
        <span style="color: var(--text-muted); margin-left: 2rem;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="16" x2="12" y2="12"></line>
                <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
            提示：悬停在订单行上可以看到快速操作按钮 · 按住 <strong>Shift</strong> + 点击快捷按钮可填写日期和备注
        </span>
    `;
    }
}

// Stage Group 筛选（参考 v10.html）
function filterByStageGroup(stageGroup, button) {
    if (!stageGroup) return;
        event?.preventDefault();
        currentFilter.substatus = 'all';
        
    if (stageGroup === 'all') {
        currentFilter.stageGroups = ['all'];
    } else {
        const selected = new Set(currentFilter.stageGroups || []);
        selected.delete('all');
        if (selected.has(stageGroup)) {
            selected.delete(stageGroup);
        } else {
            selected.add(stageGroup);
        }
        currentFilter.stageGroups = selected.size > 0 ? Array.from(selected) : ['all'];
    }

    currentFilter.stageGroup = currentFilter.stageGroups.includes('all')
        ? 'all'
        : (currentFilter.stageGroups.length === 1 ? currentFilter.stageGroups[0] : 'multi');

    syncStageGroupButtons();
    document.querySelectorAll('.substatus-dropdown').forEach(dropdown => dropdown.classList.remove('show'));
        applyFilters();
    saveFilterState();
}

// 切换子状态下拉菜单
function toggleSubstatus(stageGroup, button) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    
    const dropdown = document.getElementById(`dropdown-${stageGroup}`);
    
    // 如果下拉菜单已经展开，就收起
    if (dropdown && dropdown.classList.contains('show')) {
        dropdown.classList.remove('show');
        return;
    }
    
    // 否则，先按多选规则切换该阶段
    currentFilter.substatus = 'all';
    const selected = new Set(currentFilter.stageGroups || []);
    selected.delete('all');
    if (selected.has(stageGroup)) {
        selected.delete(stageGroup);
    } else {
        selected.add(stageGroup);
    }
    currentFilter.stageGroups = selected.size > 0 ? Array.from(selected) : ['all'];
    currentFilter.stageGroup = currentFilter.stageGroups.includes('all')
        ? 'all'
        : (currentFilter.stageGroups.length === 1 ? currentFilter.stageGroups[0] : 'multi');
    
    // 更新按钮状态
    syncStageGroupButtons();
    
    // 应用筛选
    applyFilters();
    
    // 然后展开下拉菜单（如果需要细选）
    const allDropdowns = document.querySelectorAll('.substatus-dropdown');
    allDropdowns.forEach(d => {
        if (d !== dropdown) {
            d.classList.remove('show');
        }
    });
    
    if (dropdown) {
        dropdown.classList.add('show');
        // 重置下拉菜单的「全部」为选中状态
        dropdown.querySelectorAll('.substatus-option').forEach(opt => {
            opt.classList.remove('active');
        });
        const allOption = dropdown.querySelector('.substatus-option[onclick*="\'all\'"]');
        if (allOption) {
            allOption.classList.add('active');
        }
    }
}

// 子状态筛选
function filterBySubstatus(stageGroup, substatus, option) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    
    currentFilter.stageGroup = stageGroup;
    currentFilter.stageGroups = [stageGroup];
    currentFilter.substatus = substatus;
    
    const dropdown = document.getElementById(`dropdown-${stageGroup}`);
    if (dropdown) {
        dropdown.querySelectorAll('.substatus-option').forEach(opt => {
            opt.classList.remove('active');
        });
        if (option) {
            option.classList.add('active');
        }
    }
    
    syncStageGroupButtons(stageGroup);
    
    if (dropdown) {
        dropdown.classList.remove('show');
    }
    
    applyFilters();
}

// 保留阶段 / 灯号筛选接口（目前未在 UI 使用）
function filterByStage(stage, event) {
    event.preventDefault();
    currentFilter.stage = stage;
    applyFilters();
}

function filterByLight(light, event) {
    event.preventDefault();
    currentFilter.light = light;
    applyFilters();
}

// 切換燈號篩選（點擊按鈕切換亮/灰）
function toggleLightFilter(light, button) {
    if (!currentFilter.lights) {
        currentFilter.lights = { red: true, yellow: true, green: true };
    }
    
    // 切換該燈號的顯示狀態
    const isActive = currentFilter.lights[light];
    currentFilter.lights[light] = !isActive;
    
    // 更新按鈕樣式
    if (button) {
        if (currentFilter.lights[light]) {
            button.classList.add('active');
            button.classList.remove('inactive');
        } else {
            button.classList.remove('active');
            button.classList.add('inactive');
        }
    }
    
    // 應用篩選
    applyFilters();
    
    // 保存狀態到 localStorage
    saveFilterState();
}

// 更新阶段筛选按钮
function updateStageFilters(tab) {
    const stageBar = document.getElementById('stageFilterBar');
    if (!stageBar) return;
    
    let html = '<span class="filter-label">细分流程:</span>';
    html += '<a href="#" class="filter-btn ' + (currentFilter.stage === 'all' ? 'active' : '') + '" data-stage="all" onclick="filterByStage(\'all\', event)">全部</a>';
    
    if (tab === 'all' || tab === 'quote') {
        // 使用 STATUS 常量和 displayStatus 函数（与 STATUS_SYSTEM.js 保持一致）
        const quoteStatus = typeof STATUS !== 'undefined' ? STATUS.QUOTE_CONFIRMING : '报价待确认';
        const displayQuote = typeof displayStatus !== 'undefined' ? displayStatus(quoteStatus) : quoteStatus;
        html += '<a href="#" class="filter-btn ' + (currentFilter.stage === quoteStatus ? 'active' : '') + '" data-stage="' + quoteStatus + '" onclick="filterByStage(\'' + quoteStatus + '\', event)"> ' + displayQuote + '</a>';
    }
    if (tab === 'all' || tab === 'draft') {
        if (typeof STATUS !== 'undefined' && typeof displayStatus !== 'undefined') {
            const newOrderStatus = STATUS.NEW_ORDER;
            const draftConfirmStatus = STATUS.DRAFT_CONFIRMING;
            const draftRevisingStatus = STATUS.DRAFT_REVISING;
            html += '<a href="#" class="filter-btn ' + (currentFilter.stage === newOrderStatus ? 'active' : '') + '" data-stage="' + newOrderStatus + '" onclick="filterByStage(\'' + newOrderStatus + '\', event)">' + displayStatus(newOrderStatus) + '</a>';
            html += '<a href="#" class="filter-btn ' + (currentFilter.stage === draftConfirmStatus ? 'active' : '') + '" data-stage="' + draftConfirmStatus + '" onclick="filterByStage(\'' + draftConfirmStatus + '\', event)">' + displayStatus(draftConfirmStatus) + '</a>';
            html += '<a href="#" class="filter-btn ' + (currentFilter.stage === draftRevisingStatus ? 'active' : '') + '" data-stage="' + draftRevisingStatus + '" onclick="filterByStage(\'' + draftRevisingStatus + '\', event)">' + displayStatus(draftRevisingStatus) + '</a>';
        }
    }
    if (tab === 'all' || tab === 'sampling') {
        if (typeof STATUS !== 'undefined' && typeof displayStatus !== 'undefined') {
            const pendingSampleStatus = STATUS.PENDING_SAMPLE;
            const samplingStatus = STATUS.SAMPLING;
            const sampleConfirmStatus = STATUS.SAMPLE_CONFIRMING;
            const sampleRevisingStatus = STATUS.SAMPLE_REVISING;
            html += '<a href="#" class="filter-btn ' + (currentFilter.stage === pendingSampleStatus ? 'active' : '') + '" data-stage="' + pendingSampleStatus + '" onclick="filterByStage(\'' + pendingSampleStatus + '\', event)">' + displayStatus(pendingSampleStatus) + '</a>';
            html += '<a href="#" class="filter-btn ' + (currentFilter.stage === samplingStatus ? 'active' : '') + '" data-stage="' + samplingStatus + '" onclick="filterByStage(\'' + samplingStatus + '\', event)">' + displayStatus(samplingStatus) + '</a>';
            html += '<a href="#" class="filter-btn ' + (currentFilter.stage === sampleConfirmStatus ? 'active' : '') + '" data-stage="' + sampleConfirmStatus + '" onclick="filterByStage(\'' + sampleConfirmStatus + '\', event)">' + displayStatus(sampleConfirmStatus) + '</a>';
            html += '<a href="#" class="filter-btn ' + (currentFilter.stage === sampleRevisingStatus ? 'active' : '') + '" data-stage="' + sampleRevisingStatus + '" onclick="filterByStage(\'' + sampleRevisingStatus + '\', event)">' + displayStatus(sampleRevisingStatus) + '</a>';
        }
    }
    if (tab === 'all' || tab === 'production') {
        if (typeof STATUS !== 'undefined' && typeof displayStatus !== 'undefined') {
            const pendingProductionStatus = STATUS.PENDING_PRODUCTION;
            const producingStatus = STATUS.PRODUCING;
            html += '<a href="#" class="filter-btn ' + (currentFilter.stage === pendingProductionStatus ? 'active' : '') + '" data-stage="' + pendingProductionStatus + '" onclick="filterByStage(\'' + pendingProductionStatus + '\', event)">' + displayStatus(pendingProductionStatus) + '</a>';
            html += '<a href="#" class="filter-btn ' + (currentFilter.stage === producingStatus ? 'active' : '') + '" data-stage="' + producingStatus + '" onclick="filterByStage(\'' + producingStatus + '\', event)">' + displayStatus(producingStatus) + '</a>';
        }
    }
    
    stageBar.innerHTML = html;
}

let currentUpdateData = {};

// 快速更新相关
function setToday() {
    const dateInput = document.getElementById('updateDate');
    if (dateInput) {
        dateInput.value = getTodayDate();
    }
}

function handleQuickUpdate(event, button) {
    event.stopPropagation();
    
    const orderNumber = button.dataset.order;
    const action = button.dataset.action;
    const current = button.dataset.current;
    const next = button.dataset.next;
    const row = button.closest('tr[data-order-number]') || button.closest('tr[data-workflow-number]');
    const expectedHistoryId = row ? row.dataset.historyId || '' : '';

    // 特殊处理：询价转为订单
    if (action === 'quote_to_order') {
        showPromptModal('请输入订单号：', '输入订单号', '', '例如：1007001').then(newOrderNumber => {
            if (!newOrderNumber) {
                return;
            }
            // 立即禁用按钮
            const originalText = button.textContent;
            button.disabled = true;
            button.style.opacity = '0.5';
            button.textContent = '处理中...';
            updateOrderNumber(orderNumber, newOrderNumber, action, button, originalText);
        });
        return;
    }

    // 所有其他操作都显示 Modal（除了已完成状态）
    // 已完成状态不会有下一步，所以不需要 Modal
    if (next && next !== '已完成' && next !== '已取消') {
        // 存储操作信息
        currentQuickAction = {
            orderNumber,
            action,
            currentStatus: current,
            nextStatus: next,
            button: button,
            expectedHistoryId
        };
        
        // 显示 Modal
        showQuickActionModal(orderNumber, current, next);
    } else {
        // 如果是最后一步（已完成），直接执行（但这种情况不应该有按钮）
        const originalText = button.textContent;
        button.disabled = true;
        button.style.opacity = '0.5';
        button.textContent = '处理中...';
        performQuickUpdate(orderNumber, action, current, next, getTodayDate(), '', expectedHistoryId, button, originalText);
    }
}

function showModal(orderNumber, current, next) {
    const modalTitle = document.getElementById('modalTitle');
    if (modalTitle) modalTitle.textContent = `快速更新 #${orderNumber}`;
    const currentStage = document.getElementById('currentStage');
    const nextStage = document.getElementById('nextStage');
    const updateDate = document.getElementById('updateDate');
    const updateNotes = document.getElementById('updateNotes');
    
    if (currentStage) currentStage.textContent = current;
    if (nextStage) nextStage.textContent = next;
    if (updateDate) updateDate.value = getTodayDate();
    if (updateNotes) updateNotes.value = '';
    document.getElementById('updateModal').classList.add('show');
}

function closeUpdateModal() {
    document.getElementById('updateModal').classList.remove('show');
}

function confirmUpdate() {
    const date = document.getElementById('updateDate').value;
    const notes = document.getElementById('updateNotes').value;
    
    performQuickUpdate(
        currentUpdateData.orderNumber,
        currentUpdateData.action,
        currentUpdateData.current,
        currentUpdateData.next,
        date,
        notes,
        currentUpdateData.expectedHistoryId || ''
    );
    
    closeUpdateModal();
}

function updateOrderNumber(oldOrderNumber, newOrderNumber, action, button = null, originalText = '') {
    fetch('/tracking/api/orders/update-order-number', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            old_order_number: oldOrderNumber, 
            new_order_number: newOrderNumber,
            action: action
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            showToast('转换成功', `询价已转为订单 #${newOrderNumber}`);
            setTimeout(() => location.reload(), 1000);
        } else {
            showToast('错误', '转换失败：' + data.error, 'error');
            // 恢复按钮
            if (button) {
                button.disabled = false;
                button.style.opacity = '1';
                button.textContent = originalText;
            }
        }
    })
    .catch(err => {
        showToast('错误', '错误：' + err.message, 'error');
        // 恢复按钮
        if (button) {
            button.disabled = false;
            button.style.opacity = '1';
            button.textContent = originalText;
        }
    });
}

function performQuickUpdate(orderNumber, action, current, next, date, notes, expectedHistoryId = '', button = null, originalText = '') {
    // 检查是否是 workflow_number（包含 '-' 分隔符）还是 order_number
    const isWorkflowNumber = orderNumber && orderNumber.includes('-');
    const requestBody = {
        action: action,
        date: date,
        notes: notes
    };
    
    if (isWorkflowNumber) {
        requestBody.workflow_number = orderNumber;
        requestBody.expected_status = current;
        if (expectedHistoryId) {
            requestBody.expected_history_id = expectedHistoryId;
        }
    } else {
        requestBody.order_number = orderNumber;
    }
    
    fetch('/tracking/api/orders/quick-update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            let message = `订单 #${orderNumber} · ${date}`;
            if (notes) {
                message += ` · ${notes}`;
            }
            showToast('更新成功', message);
            
            // 立即更新订单行（使用新的状态）
            // 支持通过 workflow_number 或 order_number 查找行
            const isWorkflowNumber = orderNumber && orderNumber.includes('-');
            const row = isWorkflowNumber 
                ? document.querySelector(`tr[data-workflow-number="${orderNumber}"]`)
                : document.querySelector(`tr[data-order-number="${orderNumber}"]`);
            if (row) {
                // 先更新状态，立即刷新按钮
                row.dataset.status = next;
                const latestHistoryId = (data && data.data && data.data.latest_history_id) || data.latest_history_id;
                if (latestHistoryId) {
                    row.dataset.historyId = latestHistoryId;
                    const actionsCell = row.querySelector('.actions-cell');
                    if (actionsCell) {
                        actionsCell.dataset.historyId = latestHistoryId;
                    }
                }
                showQuickActionsForRow(row, next);
            }
            
            // 清除缓存，强制重新加载
            if (typeof orderDetailCache !== 'undefined') {
                delete orderDetailCache[orderNumber];
            }
            
            // 统一的刷新函数 - 更新所有相关组件
            const refreshOrderNumber = (data && data.data && data.data.order_number)
                || data.order_number
                || (isWorkflowNumber ? orderNumber.split('-')[0] : orderNumber);
            const refreshWorkflowNumber = (data && data.data && (data.data.workflow_number || data.data.workflowNumber))
                || data.workflow_number
                || (isWorkflowNumber ? orderNumber : '');
            refreshAllComponents(refreshOrderNumber, refreshWorkflowNumber || '');
        } else {
            showToast('错误', '更新失败：' + data.error, 'error');
            // 恢复按钮
            if (button) {
                button.disabled = false;
                button.style.opacity = '1';
                button.textContent = originalText;
            }
        }
    })
    .catch(err => {
        showToast('错误', '错误：' + err.message, 'error');
        // 恢复按钮
        if (button) {
            button.disabled = false;
            button.style.opacity = '1';
            button.textContent = originalText;
        }
    });
}

// ==================== 新增订单（分步骤表单） ====================

let currentOrderStep = 1;
const totalOrderSteps = 4;
let productCount = 1;

function showNewOrderModal() {
    // 使用 editOrderModal 来新增订单
    const modal = document.getElementById('editOrderModal');
    if (!modal) {
        console.error('editOrderModal not found');
        return;
    }
    
    // 设置标题
    const title = document.getElementById('editOrderModalTitle');
    if (title) {
        title.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 6px;"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>新增订单';
    }
    
    // 设置提交按钮文本
    const submitBtn = document.getElementById('editOrderSubmitBtn');
    if (submitBtn) submitBtn.textContent = '保存 ';
    
    // 清空表单
    const orderNumberInput = document.getElementById('editOrderNumber');
    orderNumberInput.value = '';
    orderNumberInput.readOnly = false;
    orderNumberInput.style.background = '';
    orderNumberInput.removeAttribute('data-original-order-number');
    
    document.getElementById('editCustomerName').value = '';
    document.getElementById('editOrderDate').value = '';
    document.getElementById('editProductCode').value = '';
    document.getElementById('editQuantity').value = '';
    document.getElementById('editFactory').value = '';
    document.getElementById('editExpectedDeliveryDate').value = '';
    document.getElementById('editProductionType').value = '';
    document.getElementById('editNotes').value = '';
    
    // 隐藏所有提示
    document.getElementById('editOrderNumberHint').style.display = 'none';
    document.getElementById('editOrderNumberWarning').style.display = 'none';
    document.getElementById('editOrderNumberError').style.display = 'none';
    document.getElementById('toggleOrderNumberEdit').style.display = 'none';
    
    // 设置默认日期
    const today = new Date();
    document.getElementById('editOrderDate').value = today.toISOString().split('T')[0];
    
    // 預計交貨日期留空（因為訂單確認後還有很多流程要走，此時無法確定）
    document.getElementById('editExpectedDeliveryDate').value = '';
    
    // 获取下一个询价编号提示
    fetch('/tracking/api/orders/next-quote-number')
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                const hint = document.getElementById('editOrderNumberHint');
                if (hint) {
                    hint.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>不填订单号将创建询价/修图需求（将自动生成：${data.next_number}）`;
                    hint.style.display = 'block';
                }
            }
        })
        .catch(err => console.error('获取询价编号失败:', err));
    
    // 添加订单号输入监听（新增模式）
    setupOrderNumberValidation(orderNumberInput, true);
    
    // 显示 Modal
    modal.classList.add('show');
    
    // 标记为新增模式
    modal.setAttribute('data-mode', 'new');
}

function nextStep() {
    if (!validateOrderStep(currentOrderStep)) {
        return;
    }
    
    if (currentOrderStep < totalOrderSteps) {
        currentOrderStep++;
        updateOrderStep();
    }
}

function prevStep() {
    if (currentOrderStep > 1) {
        currentOrderStep--;
        updateOrderStep();
    }
}

function updateOrderStep() {
    document.querySelectorAll('.form-step').forEach(step => {
        step.classList.remove('active');
    });
    const currentStepEl = document.querySelector(`.form-step[data-step="${currentOrderStep}"]`);
    if (currentStepEl) {
        currentStepEl.classList.add('active');
    }
    
    document.querySelectorAll('.progress-step').forEach((step, index) => {
        step.classList.remove('active', 'completed');
        if (index + 1 < currentOrderStep) {
            step.classList.add('completed');
        } else if (index + 1 === currentOrderStep) {
            step.classList.add('active');
        }
    });
    
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');
    const submitBtn = document.getElementById('submitBtn');
    
    if (prevBtn) prevBtn.style.display = currentOrderStep > 1 ? 'block' : 'none';
    
    if (currentOrderStep === totalOrderSteps) {
        if (nextBtn) nextBtn.style.display = 'none';
        if (submitBtn) submitBtn.style.display = 'block';
        updateOrderSummary();
    } else {
        if (nextBtn) nextBtn.style.display = 'block';
        if (submitBtn) submitBtn.style.display = 'none';
    }
}

function validateOrderStep(step) {
    let isValid = true;
    const currentStepEl = document.querySelector(`.form-step[data-step="${step}"]`);
    if (!currentStepEl) return false;
    
    const requiredInputs = currentStepEl.querySelectorAll('[required]');
    
    requiredInputs.forEach(input => {
        input.classList.remove('error');
        const errorEl = input.parentElement.querySelector('.form-error');
        if (errorEl) errorEl.classList.remove('show');
        
        if (!input.value.trim()) {
            input.classList.add('error');
            if (errorEl) errorEl.classList.add('show');
            isValid = false;
        }
    });
    
    if (step === 1) {
        const customerName = document.getElementById('newCustomerName');
        if (customerName && !customerName.value.trim()) {
            customerName.classList.add('error');
            isValid = false;
        }
    }
    
    if (step === 2) {
        const productItems = document.querySelectorAll('.product-item');
        if (productItems.length === 0) {
            showToast('错误', '至少需要添加一个产品');
            isValid = false;
        } else {
            let hasValidProduct = false;
            productItems.forEach(item => {
                const productType = item.querySelector('select[name="product_type[]"]');
                if (productType && productType.value.trim()) {
                    hasValidProduct = true;
                    productType.classList.remove('error');
                } else if (productType) {
                    productType.classList.add('error');
                    const errorEl = productType.parentElement.querySelector('.form-error');
                    if (errorEl) errorEl.classList.add('show');
                }
            });
            if (!hasValidProduct) {
                showToast('错误', '请为至少一个产品选择产品类型');
                isValid = false;
            }
        }
    }
    
    if (!isValid) {
        showToast('错误', '请填写所有必填项目');
    }
    
    return isValid;
}

function updateOrderSummary() {
    const orderNumber = document.getElementById('newOrderNumber').value.trim();
    const orderDate = document.getElementById('newOrderDate').value;
    const customer = document.getElementById('newCustomerName').value;
    const patternCode = document.getElementById('newPatternCode').value;
    const deliveryDate = document.getElementById('newExpectedDeliveryDate')?.value || '';
    const needSampling = document.querySelector('input[name="needSampling"]:checked')?.value || 'yes';
    const notes = document.getElementById('newNotes').value;
    
    document.getElementById('summaryOrderNumber').textContent = orderNumber || '自动生成（询价/修图）';
    document.getElementById('summaryOrderDate').textContent = orderDate || '-';
    document.getElementById('summaryCustomer').textContent = customer || '-';
    
    const productItems = document.querySelectorAll('.product-item');
    const summaryProducts = document.getElementById('summaryProducts');
    if (summaryProducts) {
        if (productItems.length === 0) {
            summaryProducts.innerHTML = '<div class="summary-row"><span class="summary-label">无产品信息</span></div>';
        } else {
            summaryProducts.innerHTML = '';
            productItems.forEach((item, index) => {
                const productType = item.querySelector('select[name="product_type[]"]')?.value || '-';
                const productCode = item.querySelector('input[name="product_code[]"]')?.value || '-';
                const quantity = item.querySelector('input[name="quantity[]"]')?.value || '-';
                const unit = item.querySelector('select[name="unit[]"]')?.value || '';
                
                summaryProducts.innerHTML += `
                    <div class="summary-row">
                        <span class="summary-label">产品 ${index + 1}</span>
                        <span class="summary-value">${productType}</span>
                    </div>
                    ${productCode ? `<div class="summary-row">
                        <span class="summary-label">产品编号</span>
                        <span class="summary-value">${productCode}</span>
                    </div>` : ''}
                    ${quantity ? `<div class="summary-row">
                        <span class="summary-label">数量</span>
                        <span class="summary-value">${quantity} ${unit || ''}</span>
                    </div>` : ''}
                    ${index < productItems.length - 1 ? '<div style="margin: 0.5rem 0;"></div>' : ''}
                `;
            });
        }
    }
    
    document.getElementById('summaryPatternCode').textContent = patternCode || '-';
    document.getElementById('summaryDeliveryDate').textContent = deliveryDate || '-';
    document.getElementById('summarySampling').textContent = needSampling === 'yes' ? '需要打样' : '直接生产';
    document.getElementById('summaryNotes').textContent = notes || '-';
}

function addProduct() {
    productCount++;
    const productList = document.getElementById('productList');
    if (!productList) return;
    
    const newProduct = document.createElement('div');
    newProduct.className = 'product-item';
    newProduct.innerHTML = `
        <div class="product-item-header">
            <div class="product-item-title">产品 #${productCount}</div>
            <button type="button" class="remove-product-btn" onclick="removeProduct(this)">× 移除</button>
        </div>
        <div class="form-grid">
            <div class="form-group">
                <label class="form-label">产品类型 <span class="required">*</span></label>
                <select name="product_type[]" class="form-select" required>
                    <option value="">请选择</option>
                    <option value="數碼印花">數碼印花</option>
                    <option value="活性印花">活性印花</option>
                    <option value="冰絲印花">冰絲印花</option>
                    <option value="冰絲確剪碼印花">冰絲確剪碼印花</option>
                </select>
                <span class="form-error">请选择产品类型</span>
            </div>
            <div class="form-group">
                <label class="form-label">产品编号</label>
                <input type="text" name="product_code[]" class="form-input" placeholder="PRD-2026-XXX">
            </div>
            <div class="form-group">
                <label class="form-label">数量</label>
                <input type="text" name="quantity[]" class="form-input" placeholder="例如：500 碼">
            </div>
            <div class="form-group">
                <label class="form-label">单位</label>
                <select name="unit[]" class="form-select">
                    <option value="碼">碼</option>
                    <option value="米">米</option>
                    <option value="件">件</option>
                    <option value="打">打</option>
                </select>
            </div>
            <div class="form-group full-width">
                <label class="form-label">产品备注</label>
                <textarea name="product_notes[]" class="form-textarea" placeholder="产品相关的特殊要求或备注"></textarea>
            </div>
        </div>
    `;
    productList.appendChild(newProduct);
}

async function removeProduct(btn) {
    const confirmed = await showConfirmModal('确定要移除这个产品吗？', '确认移除', '确认', '取消');
    if (confirmed) {
        btn.closest('.product-item').remove();
        const productItems = document.querySelectorAll('.product-item');
        productItems.forEach((item, index) => {
            const titleEl = item.querySelector('.product-item-title');
            if (titleEl) {
                titleEl.textContent = `产品 #${index + 1}`;
            }
        });
        productCount = productItems.length;
    }
}

function checkOrderNumber() {
    const orderNumber = document.getElementById('newOrderNumber').value.trim();
    const errorDiv = document.getElementById('orderNumberError');
    
    if (!orderNumber) {
        errorDiv.style.display = 'none';
        return;
    }
    
    fetch(`/tracking/api/orders/check-number?order_number=${encodeURIComponent(orderNumber)}`)
        .then(res => res.json())
        .then(data => {
            if (data.exists) {
                errorDiv.textContent = '错误：' + data.message;
                errorDiv.style.display = 'block';
            } else {
                errorDiv.style.display = 'none';
            }
        })
        .catch(err => {
            console.error('檢查訂單號失敗:', err);
        });
}

let customerSearchTimeout;
function searchCustomers(query) {
    if (query.length < 1) {
        document.getElementById('customerSuggestions').style.display = 'none';
        return;
    }
    
    clearTimeout(customerSearchTimeout);
    customerSearchTimeout = setTimeout(() => {
        fetch(`/tracking/api/customers/search?q=${encodeURIComponent(query)}`)
            .then(res => res.json())
            .then(data => {
                const suggestionsDiv = document.getElementById('customerSuggestions');
                
                if (data.success && data.data.length > 0) {
                    suggestionsDiv.innerHTML = data.data.map(customer => 
                        `<div class="customer-suggestion-item" onclick="selectCustomer('${customer.replace(/'/g, "\\'")}')">${customer}</div>`
                    ).join('');
                    suggestionsDiv.style.display = 'block';
                } else {
                    suggestionsDiv.style.display = 'none';
                }
            })
            .catch(err => {
                console.error('搜索客戶失敗:', err);
            });
    }, 300);
}

function selectCustomer(customerName) {
    document.getElementById('newCustomerName').value = customerName;
    document.getElementById('customerSuggestions').style.display = 'none';
}

function hideCustomerSuggestions() {
    setTimeout(() => {
        document.getElementById('customerSuggestions').style.display = 'none';
    }, 200);
}

// 注意：此函數已被 new_order.js 中的 closeNewWorkflowModal 覆蓋
// 保留此函數僅作為後備方案（如果 new_order.js 未加載）
async function closeNewOrderModal() {
    // 如果 window.closeNewWorkflowModal 或 window.closeNewOrderModal 已被 new_order.js 定義，調用它並返回
    // 避免重複定義
    if (typeof window.closeNewWorkflowModal === 'function') {
        await window.closeNewWorkflowModal();
        return;
    }
    if (typeof window.closeNewOrderModal === 'function' && window.closeNewOrderModal !== closeNewOrderModal) {
        await window.closeNewOrderModal();
        return;
    }
    
    const confirmed = await showConfirmModal('确定要关闭吗？未保存的数据将丢失。', '确认关闭', '确认', '取消', true);
    if (confirmed) {
        const modal = document.getElementById('newOrderModal');
        if (modal) {
            modal.classList.remove('show');
        }
        if (typeof resetOrderForm === 'function') {
            resetOrderForm();
        }
    }
}

function resetOrderForm() {
    currentOrderStep = 1;
    productCount = 1;
    updateOrderStep();
    const form = document.getElementById('newOrderForm');
    if (form) form.reset();
    const confirmCheck = document.getElementById('confirmCheck');
    if (confirmCheck) confirmCheck.checked = false;
    document.querySelectorAll('.form-input, .form-select, .form-textarea').forEach(input => {
        input.classList.remove('error');
    });
    document.querySelectorAll('.form-error').forEach(error => {
        error.classList.remove('show');
    });
}

function submitNewOrder() {
    const confirmCheck = document.getElementById('confirmCheck');
    if (!confirmCheck || !confirmCheck.checked) {
        showToast('错误', '请确认订单信息后勾选确认框');
        return;
    }
    
    const orderNumber = document.getElementById('newOrderNumber').value.trim();
    const errorDiv = document.getElementById('orderNumberError');
    
    const checkAndSubmit = () => {
        const formData = new FormData(document.getElementById('newOrderForm'));
        
        const firstProduct = document.querySelector('.product-item');
        let productType = '';
        let productCode = '';
        
        if (firstProduct) {
            productType = firstProduct.querySelector('select[name="product_type[]"]')?.value || '';
            productCode = firstProduct.querySelector('input[name="product_code[]"]')?.value || '';
        }
        
        const data = {
            order_date: formData.get('order_date'),
            order_number: orderNumber || null,
            customer_name: formData.get('customer_name'),
            production_type: formData.get('production_type') || '',
            pattern_code: formData.get('pattern_code') || '',
            expected_delivery_date: formData.get('expected_delivery_date') || null,
            notes: formData.get('notes') || '',
            product_name: productType || '',
            product_code: productCode || ''
        };
        
        fetch('/tracking/orders/new', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(res => res.json())
        .then(result => {
            if (result.success) {
                showToast('创建成功', `订单 ${result.message || '已创建'}`);
                closeNewOrderModal();
                setTimeout(() => location.reload(), 1500);
            } else {
                if (result.error && result.error.includes('已存在')) {
                    if (errorDiv) {
                        errorDiv.textContent = '错误：' + result.error;
                        errorDiv.style.display = 'block';
                    }
                    currentOrderStep = 1;
                    updateOrderStep();
                } else {
                    showToast('错误', '创建失败：' + (result.error || '未知错误'), 'error');
                }
            }
        })
        .catch(err => {
            showToast('错误', '错误：' + err.message, 'error');
        });
    };
    
    if (orderNumber) {
        fetch(`/tracking/api/orders/check-number?order_number=${encodeURIComponent(orderNumber)}`)
            .then(res => res.json())
            .then(data => {
                if (data.exists) {
                    if (errorDiv) {
                        errorDiv.textContent = '错误：' + data.message;
                        errorDiv.style.display = 'block';
                    }
                    currentOrderStep = 1;
                    updateOrderStep();
                } else {
                    checkAndSubmit();
                }
            })
            .catch(err => {
                    showToast('错误', '检查订单号失败：' + err.message, 'error');
            });
    } else {
        checkAndSubmit();
    }
}

// ==================== 列表詳情時間軸 ====================

const orderDetailCache = {};

function toggleDetail(workflowNumber, event) {
    if (event && (event.target.closest('.actions-cell') || event.target.closest('.quick-btn'))) {
        return;
    }

    // 支持通过 workflow_number 或 order_number 查找行
    const row = document.querySelector(`tr[data-workflow-number="${workflowNumber}"]`) || 
                document.querySelector(`tr[data-order-number="${workflowNumber}"]`);
    if (!row) return;

    const expandBtn = document.getElementById(`expand-${workflowNumber}`);

    const existingDetail = document.querySelector(`tr.detail-row[data-detail-for="${workflowNumber}"]`);
    if (existingDetail) {
        existingDetail.parentNode.removeChild(existingDetail);
        if (expandBtn) expandBtn.classList.remove('expanded');
        return;
    }

    document.querySelectorAll('tr.detail-row').forEach(tr => tr.parentNode.removeChild(tr));
    document.querySelectorAll('.expand-btn').forEach(btn => btn.classList.remove('expanded'));

    const detailRow = document.createElement('tr');
    detailRow.className = 'detail-row show';
    detailRow.dataset.detailFor = workflowNumber;
    
    // 使用表头的列数，确保和表头完全一致
    const table = row.closest('table');
    const theadRow = table ? table.querySelector('thead tr') : null;
    let colSpan = 0;
    
    if (theadRow) {
        // 计算表头中可见的列数（排除 display: none 的列）
        const ths = theadRow.querySelectorAll('th');
        ths.forEach(th => {
            const style = window.getComputedStyle(th);
            if (style.display !== 'none' && style.visibility !== 'hidden') {
                colSpan++;
            }
        });
    }
    
    // 如果表头列数为0，使用数据行的列数作为后备
    if (colSpan === 0) {
        const tds = row.querySelectorAll('td');
        colSpan = tds.length;
    }
    
    // 如果还是0，使用 row.cells
    if (colSpan === 0 && row.cells) {
        colSpan = row.cells.length;
    }
    
    detailRow.innerHTML = `
        <td colspan="${colSpan}" style="padding: 0; width: 100%;">
            <div class="detail-content" id="detail-content-${workflowNumber}">
                <div class="timeline-title"> 載入中...</div>
            </div>
        </td>
    `;
    row.parentNode.insertBefore(detailRow, row.nextSibling);
    if (expandBtn) expandBtn.classList.add('expanded');

    if (orderDetailCache[workflowNumber]) {
        renderOrderTimeline(workflowNumber, orderDetailCache[workflowNumber], 'row');
        return;
    }

    // 优先使用 workflow API，如果失败则回退到 order API（向后兼容）
    fetch(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}`)
        .then(res => {
            if (!res.ok && res.status === 404) {
                // 如果 workflow API 返回 404，尝试使用 order API（向后兼容）
                return fetch(`/tracking/api/orders/${encodeURIComponent(workflowNumber)}`);
            }
            return res;
        })
        .then(res => res.json())
        .then(result => {
            if (!result.success) {
                document.getElementById(`detail-content-${workflowNumber}`).innerHTML =
                    `<div class="timeline-title">错误：載入失敗：${result.error || '未知錯誤'}</div>`;
                return;
            }
            orderDetailCache[workflowNumber] = result.data;
            renderOrderTimeline(workflowNumber, result.data, 'row');
        })
        .catch(err => {
            document.getElementById(`detail-content-${workflowNumber}`).innerHTML =
                `<div class="timeline-title">错误：載入失敗：${err.message}</div>`;
        });
}

// Ensure toggleDetail is available for inline onclick handlers.
if (typeof window !== 'undefined' && typeof window.toggleDetail !== 'function') {
    window.toggleDetail = toggleDetail;
}


function renderOrderTimeline(orderNumber, orderData) {
    const container = document.getElementById(`detail-content-${orderNumber}`);
    if (!container) return;

    const history = orderData.history || [];
    if (!history.length) {
        container.innerHTML = '<div class="timeline-empty">暂无历史记录</div>';
        return;
    }

    // 使用本地日期計算（與後端 date.today() 一致，避免 UTC 偏差）
    function parseDate(d) {
        return typeof parseLocalDate === 'function' ? parseLocalDate(d) : parseUTCDate(d);
    }
    function diffDays(from, to) {
        if (!from || !to) return null;
        return Math.max(0, Math.round((to - from) / (1000 * 60 * 60 * 24)));
    }
    function formatDateDisplay(d) {
        const dt = parseDate(d);
        if (!dt) return '-';
        const currentYear = today.getFullYear();
        const year = dt.getFullYear();
        const m = String(dt.getMonth() + 1).padStart(2, '0');
        const day = String(dt.getDate()).padStart(2, '0');
        if (year === currentYear) {
        return `${m}/${day}`;
        }
        return `${year}/${m}/${day}`;
    }

    const today = getTodayLocal();  // 使用本地日期，與後端 date.today() 一致
    
    // 修正：不使用后端的 status_days，而是前端实时计算
    // 因为后端的值可能不准确或有延迟
    const lastHistoryItem = history[history.length - 1];
    const lastDate = parseDate(lastHistoryItem?.action_date);
    const currentStatusDays = lastDate ? diffDays(lastDate, today) : 0;

    // 折叠配置：如果超过5条记录，默认只显示最近的5条
    const MAX_VISIBLE_DEFAULT = 5;
    const TOTAL_THRESHOLD = 5;
    const shouldCollapse = history.length > TOTAL_THRESHOLD;
    const visibleCount = shouldCollapse ? MAX_VISIBLE_DEFAULT : history.length;
    const hiddenCount = history.length - visibleCount;
    
    // 检查是否已展开（从容器数据属性获取）
    const isExpanded = container.dataset.isExpanded === 'true';
    const displayCount = isExpanded ? history.length : visibleCount;
    const displayHistory = isExpanded ? history : history.slice(-displayCount);

    const collapsedIndicator = `
        <div class="step-item collapsed-indicator">
            <div class="icon-circle">⋯</div>
            <div class="label">已折叠 ${hiddenCount} 条记录</div>
            <div class="date"></div>
            </div>
        `;
    let horizontalHtml = generateTimeline(
        displayHistory,
        'zh_tw',
        { prependHtml: (shouldCollapse && !isExpanded) ? collapsedIndicator : '' }
    );
    if (!container.classList.contains('timeline-horizontal')) {
        horizontalHtml = `<div class="timeline-horizontal">${horizontalHtml}</div>`;
    }

    // 生成展开/折叠按钮
    let toggleButtonHtml = '';
    if (shouldCollapse) {
        toggleButtonHtml = isExpanded
            ? `
                <button class="btn btn-secondary timeline-toggle-btn" 
                        onclick="toggleTimelineExpand('${orderNumber}', false); event.stopPropagation();"
                        style="padding: 0.5rem 1rem; font-size: 0.85rem; margin-left: 0.5rem; width: auto;">
                    📕 折叠早期记录
                </button>
            `
            : `
                <button class="btn btn-secondary timeline-toggle-btn" 
                        onclick="toggleTimelineExpand('${orderNumber}', true); event.stopPropagation();"
                        style="padding: 0.5rem 1rem; font-size: 0.85rem; margin-left: 0.5rem; width: auto;">
                    📖 展开全部 (${hiddenCount} 条)
                </button>
            `;
    }

    container.innerHTML = `
        <div style="margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem;">
            ${toggleButtonHtml}
        </div>
        ${horizontalHtml}
    `;
    
    // 保存完整历史数据到容器，以便展开时使用
    container.dataset.fullHistory = JSON.stringify(history);
    container.dataset.isExpanded = isExpanded ? 'true' : 'false';
    container.dataset.statusDays = currentStatusDays;
    container.dataset.customerName = orderData.customer_name || '';
}

/**
 * 切换时间轴展开/折叠状态
 */
function toggleTimelineExpand(orderNumber, expand) {
    const container = document.getElementById(`detail-content-${orderNumber}`);
    if (!container) return;
    
    const fullHistory = JSON.parse(container.dataset.fullHistory || '[]');
    if (!fullHistory.length) return;
    
    // 重新渲染时间轴（展开或折叠）
    const orderData = {
        history: fullHistory,
        status_days: parseInt(container.dataset.statusDays) || 0,
        customer_name: container.dataset.customerName || ''
    };
    
    // 临时设置展开状态
    container.dataset.isExpanded = expand ? 'true' : 'false';
    
    // 重新渲染
    renderOrderTimeline(orderNumber, orderData);
}


// ==================== v10.html 的操作類 Modal（Action + Details + Note...） ====================

let currentAction = '';
let currentOrderId = '';
let fromStatus = '';
let toStatus = '';

function showActionModal(action, from, to, orderId) {
    currentAction = action;
    currentOrderId = orderId;
    fromStatus = from;
    toStatus = to;
    
    const modal = document.getElementById('actionModal');
    const title = document.getElementById('modalTitle');
    const info = document.getElementById('modalInfo');
    const confirmBtn = document.getElementById('confirmBtn');
    const noteField = document.getElementById('modalNote');
    
    if (!modal || !title || !info || !confirmBtn || !noteField) return;

    noteField.value = '';
    info.textContent = `订单 ${orderId}`;

    // 移除旧的箭头区块
    const infoParent = info.parentElement;
    Array.from(infoParent.querySelectorAll('.modal-arrow-line')).forEach(el => el.remove());

    const arrow = document.createElement('div');
    arrow.className = 'modal-arrow-line';
    arrow.style.display = 'flex';
    arrow.style.alignItems = 'center';
    arrow.style.gap = '0.5rem';
    arrow.style.marginTop = '0.5rem';

    if (action === 'confirm') {
        title.textContent = '确认：国外确认';
        arrow.innerHTML = `<span style="color: var(--text-2);">${from}</span> <span style="color: var(--text-3); font-weight: 600;">→</span> <span style="color: var(--blue); font-weight: 600;">${to}</span>`;
        confirmBtn.textContent = '✓ 确认';
        confirmBtn.className = 'modal-btn confirm';
    } else if (action === 'revise') {
        title.textContent = '确认：需要修改';
        arrow.innerHTML = `<span style="color: var(--text-2);">${from}</span> <span style="color: var(--text-3); font-weight: 600;">→</span> <span style="color: var(--yellow); font-weight: 600;">${to}</span>`;
        confirmBtn.textContent = '🔄 确认修改';
        confirmBtn.className = 'modal-btn confirm';
        noteField.placeholder = '建议说明修改原因...';
    } else if (action === 'send') {
        title.textContent = '确认：重新发图给国外';
        arrow.innerHTML = `<span style="color: var(--text-2);">${from}</span> <span style="color: var(--text-3); font-weight: 600;">→</span> <span style="color: var(--blue); font-weight: 600;">${to}</span>`;
        confirmBtn.textContent = '→ 确认发图';
        confirmBtn.className = 'modal-btn confirm';
    } else if (action === 'start') {
        title.textContent = '确认：开始下一步';
        arrow.innerHTML = `<span style="color: var(--text-2);">${from}</span> <span style="color: var(--text-3); font-weight: 600;">→</span> <span style="color: var(--blue); font-weight: 600;">${to}</span>`;
        confirmBtn.textContent = '✓ 确认开始';
        confirmBtn.className = 'modal-btn confirm';
    } else if (action === 'complete') {
        title.textContent = '确认：生产完成';
        arrow.innerHTML = `<span style="color: var(--text-2);">${from}</span> <span style="color: var(--text-3); font-weight: 600;">→</span> <span style="color: var(--green); font-weight: 600;">${to}</span>`;
        confirmBtn.textContent = '✓ 确认完成';
        confirmBtn.className = 'modal-btn confirm';
    } else if (action === 'skip') {
        title.textContent = '警告：确认跳过打样阶段';
        info.textContent = `将直接从当前阶段进入生产阶段`;
        confirmBtn.textContent = '✓ 确认跳过';
        confirmBtn.className = 'modal-btn confirm';
    }

    infoParent.appendChild(arrow);
    modal.classList.add('show');
}

function showDetailsMenu(orderId) {
    currentOrderId = orderId;
    const modal = document.getElementById('detailsModal');
    if (modal) modal.classList.add('show');
}

// 只关闭旧版详情菜单相关的 Modal，不影响其他 Modal（confirmModal / alertModal / settingsModal 等）
const _legacyModalIds = ['detailsModal', 'actionModal', 'noteModal', 'deliveryDateModal',
    'skipSamplingModal', 'backStepModal', 'cancelOrderModal'];
function closeModal() {
    _legacyModalIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove('show');
    });
}

function confirmAction() {
    const note = document.getElementById('modalNote').value;
    console.log('Action:', currentAction);
    console.log('Order ID:', currentOrderId);
    console.log('From:', fromStatus);
    console.log('To:', toStatus);
    console.log('Note:', note);
    
    showToast('成功', `订单 ${currentOrderId} 已从 "${fromStatus}" 变更为 "${toStatus}"`, 'success');
    closeModal();
}

function showNoteModal() {
    closeModal();
    document.getElementById('noteOrderId').textContent = currentOrderId;
    document.getElementById('noteModal').classList.add('show');
}

function confirmAddNote() {
    const note = document.getElementById('noteText').value;
    if (note.trim()) {
        console.log('Add note for', currentOrderId, ':', note);
        showToast('成功', '备注已添加', 'success');
        closeModal();
    } else {
        showToast('提示', '请输入备注内容', 'warning');
    }
}

function showDeliveryDateModal() {
    closeModal();
    document.getElementById('deliveryOrderId').textContent = currentOrderId;
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    document.getElementById('deliveryDate').valueAsDate = tomorrow;
    document.getElementById('deliveryDateModal').classList.add('show');
}

function confirmDeliveryDate() {
    const date = document.getElementById('deliveryDate').value;
    if (date) {
        console.log('Set delivery date for', currentOrderId, ':', date);
        showToast('成功', `预计交货日期已设定为：${date}`, 'success');
        closeModal();
    } else {
        showToast('提示', '请选择日期', 'warning');
    }
}

function showSkipSamplingModal() {
    closeModal();
    document.getElementById('skipSamplingModal').classList.add('show');
}

function confirmSkipSampling() {
    const reason = document.getElementById('skipReason').value;
    console.log('Skip sampling for', currentOrderId, 'Reason:', reason);
    showToast('成功', '已跳过打样阶段，进入生产阶段', 'success');
    closeModal();
}

function showBackStepModal() {
    closeModal();
    document.getElementById('backStepModal').classList.add('show');
}

// backToDetailsMenu 函数已删除，因为旧的 detailsModal 已经移除
// 现在所有 Modal 的返回按钮都使用 closeModal()

function confirmBackStep() {
    const selectedStep = document.querySelector('input[name="backStep"]:checked');
    const note = document.getElementById('backStepNote').value;
    
    if (selectedStep) {
        console.log('Back to:', selectedStep.value, 'Note:', note);
        showToast('成功', `已退回到：${selectedStep.value}`, 'success');
        closeModal();
    } else {
        showToast('提示', '请选择要退回的步骤', 'warning');
    }
}

function showCancelOrderModal() {
    closeModal();
    document.getElementById('cancelOrderModal').classList.add('show');
}

async function confirmCancelOrder() {
    const reason = document.getElementById('cancelReason').value;
    if (reason && reason.trim()) {
        const confirmed = await showConfirmModal(`确定要取消订单 ${currentOrderId} 吗？\n原因：${reason}`, '确认取消订单', '确认取消', '取消', true);
        if (confirmed) {
            console.log('Cancel order', currentOrderId, 'Reason:', reason);
            showToast('成功', '订单已取消', 'success');
            closeModal();
        }
    } else {
        showToast('提示', '取消订单需要填写原因', 'warning');
    }
}

function toggleCompletedOrders(target) {
    let isActive = currentFilter.showCompleted;
    if (typeof target === 'boolean') {
        isActive = target;
    } else if (target && target.classList) {
        isActive = !target.classList.contains('active');
        target.classList.toggle('active', isActive);
    } else if (target && target.checked !== undefined) {
        isActive = target.checked;
    }
    currentFilter.showCompleted = isActive;
    const selected = new Set(currentFilter.stageGroups || []);
    selected.delete('all');
    if (isActive) {
        selected.add('completed');
    } else {
        selected.delete('completed');
    }
    currentFilter.stageGroups = selected.size > 0 ? Array.from(selected) : ['all'];
    syncStageGroupButtons();
    applyFilters();
    saveFilterState(); // 保存狀態
}

function toggleCancelledOrders(target) {
    let isActive = currentFilter.showCancelled;
    if (typeof target === 'boolean') {
        isActive = target;
    } else if (target && target.classList) {
        isActive = !target.classList.contains('active');
        target.classList.toggle('active', isActive);
    } else if (target && target.checked !== undefined) {
        isActive = target.checked;
    }
    currentFilter.showCancelled = isActive;
    const selected = new Set(currentFilter.stageGroups || []);
    selected.delete('all');
    if (isActive) {
        selected.add('cancelled');
    } else {
        selected.delete('cancelled');
    }
    currentFilter.stageGroups = selected.size > 0 ? Array.from(selected) : ['all'];
    syncStageGroupButtons();
    applyFilters();
    saveFilterState(); // 保存狀態
}

function toggleNoWorkflowOrders(target) {
    let isActive = currentFilter.showNoWorkflow;
    if (typeof target === 'boolean') {
        isActive = target;
    } else if (target && target.classList) {
        isActive = !target.classList.contains('active');
        target.classList.toggle('active', isActive);
    }
    currentFilter.showNoWorkflow = isActive;
    const selected = new Set(currentFilter.stageGroups || []);
    selected.delete('all');
    if (isActive) {
        selected.add('no_workflow');
    } else {
        selected.delete('no_workflow');
    }
    currentFilter.stageGroups = selected.size > 0 ? Array.from(selected) : ['all'];
    syncStageGroupButtons();
    applyFilters();
}

// 清空搜尋框
function clearSearchInput() {
    const input = document.getElementById('searchInput');
    const clearBtn = document.getElementById('searchClearBtn');
    if (input) {
        input.value = '';
        selectedCustomerNameFilter = '';
        selectedOrderNumberFilter = '';
        if (clearBtn) { clearBtn.style.opacity = '0'; clearBtn.style.pointerEvents = 'none'; }
        hideCustomerSearchSuggestions();
        // 觸發搜尋重置
        if (typeof exitSearchMode === 'function') {
            exitSearchMode();
        } else {
            currentFilter.search = '';
            if (typeof isGlobalSearchMode !== 'undefined') isGlobalSearchMode = false;
            if (typeof originalOrders !== 'undefined') originalOrders = null;
            applyFilters();
        }
    }
}

function openAdvancedFilterModal() {
    const modal = document.getElementById('advancedFilterModal');
    if (modal) modal.classList.add('show');
    restoreAdvancedFilterState();
}

function closeAdvancedFilterModal(event) {
    const modal = document.getElementById('advancedFilterModal');
    if (!modal) return;
    if (!event || (event.target && event.target.classList.contains('modal-overlay'))) {
        saveAdvancedFilterState();
        modal.classList.remove('show');
    }
}

function toggleAdvancedSales(tag) {
    const allTag = document.querySelector('#advancedSalesTags .tag.all');
    if (!tag || !allTag) return;

    if (tag.classList.contains('all')) {
        if (!tag.classList.contains('active')) {
            document.querySelectorAll('#advancedSalesTags .tag').forEach(t => t.classList.remove('active'));
            tag.classList.add('active');
        }
        return;
    }

    allTag.classList.remove('active');
    tag.classList.toggle('active');

    const anyActive = document.querySelectorAll('#advancedSalesTags .tag.active:not(.all)').length > 0;
    if (!anyActive) {
        allTag.classList.add('active');
    }
}

function filterAdvancedSales() {
    const input = document.getElementById('advancedSalesSearch');
    const keyword = (input?.value || '').trim().toLowerCase();
    document.querySelectorAll('#advancedSalesTags .tag:not(.all)').forEach(tag => {
        const text = tag.textContent.toLowerCase();
        tag.style.display = text.includes(keyword) ? '' : 'none';
    });
}

function toggleAdvancedStatus(button) {
    if (!button) return;
    button.classList.toggle('active');
    const activeCount = document.querySelectorAll('#advancedFilterModal .s-btn.active').length;
    if (activeCount === 0) {
        button.classList.add('active');
    }
    updateAdvancedStatusHint(true);
}

function updateAdvancedStatusHint(allowAutoExpand = false) {
    const completed = document.querySelector('#advancedFilterModal .s-btn[data-status="completed"]')?.classList.contains('active');
    const cancelled = document.querySelector('#advancedFilterModal .s-btn[data-status="cancelled"]')?.classList.contains('active');
    const timeExpanded = document.getElementById('advancedTimeDetail')?.classList.contains('show');
    const hint = document.getElementById('advancedStatusHint');

    if (!hint) return;
    if ((completed || cancelled) && !timeExpanded) {
        hint.classList.add('show');
        if (allowAutoExpand) {
            toggleAdvancedTime();
        }
    } else {
        hint.classList.remove('show');
    }
}

function toggleAdvancedTime() {
    const toggle = document.getElementById('advancedTimeToggle');
    const detail = document.getElementById('advancedTimeDetail');
    if (!toggle || !detail) return;

    const isOpen = detail.classList.toggle('show');
    toggle.classList.toggle('active', isOpen);

    if (isOpen) {
        const defaultTag = document.querySelector('#advancedFilterModal .q-tag.active')
            || document.querySelector('#advancedFilterModal .q-tag[data-range="last-3-months"]');
        if (defaultTag) setAdvancedQuickRange(defaultTag);
    } else {
        document.querySelectorAll('#advancedFilterModal .q-tag').forEach(tag => tag.classList.remove('active'));
        const fromInput = document.getElementById('advancedDateFrom');
        const toInput = document.getElementById('advancedDateTo');
        if (fromInput) fromInput.value = '';
        if (toInput) toInput.value = '';
    }

    updateAdvancedStatusHint();
}

function setAdvancedQuickRange(tag) {
    if (!tag) return;
    const rangeKey = tag.dataset.range || '';
    const fromInput = document.getElementById('advancedDateFrom');
    const toInput = document.getElementById('advancedDateTo');
    if (!fromInput || !toInput) return;

    const today = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const format = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

    let start = new Date(today);
    let end = new Date(today);

    if (rangeKey === 'week') {
        const day = (today.getDay() + 6) % 7;
        start.setDate(today.getDate() - day);
    } else if (rangeKey === 'month') {
        start = new Date(today.getFullYear(), today.getMonth(), 1);
    } else if (rangeKey === 'last-month') {
        start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
        end = new Date(today.getFullYear(), today.getMonth(), 0);
    } else if (rangeKey === 'last-3-months') {
        start = new Date(today.getFullYear(), today.getMonth() - 3, today.getDate());
    } else if (rangeKey.startsWith('year-')) {
        const year = parseInt(rangeKey.replace('year-', ''), 10);
        if (!Number.isNaN(year)) {
            start = new Date(year, 0, 1);
            end = new Date(year, 11, 31);
        }
    }

    document.querySelectorAll('#advancedFilterModal .q-tag').forEach(t => t.classList.remove('active'));
    tag.classList.add('active');
    fromInput.value = format(start);
    toInput.value = format(end);
}

const ADVANCED_FILTER_STATE_KEY = 'advancedFilterState';
let advancedFilterSkipDefault = false;

function saveAdvancedFilterState(state) {
    const payload = state || collectAdvancedFilters();
    try {
        localStorage.setItem(ADVANCED_FILTER_STATE_KEY, JSON.stringify(payload));
    } catch (error) {
        console.warn('Save advanced filter state failed:', error);
    }
}

function loadAdvancedFilterState() {
    try {
        const raw = localStorage.getItem(ADVANCED_FILTER_STATE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch (error) {
        console.warn('Load advanced filter state failed:', error);
        return null;
    }
}

function clearAdvancedFilterState() {
    try {
        localStorage.removeItem(ADVANCED_FILTER_STATE_KEY);
    } catch (error) {
        console.warn('Clear advanced filter state failed:', error);
    }
}

function ensureDefaultAdvancedDateRange() {
    if (advancedFilterSkipDefault) return;
    const state = loadAdvancedFilterState();
    if (state && (state.quickRange || state.dateFrom || state.dateTo)) return;
    const tag = document.querySelector('#advancedFilterModal .q-tag[data-range="last-3-months"]');
    if (tag) {
        setAdvancedQuickRange(tag);
        tag.classList.add('active');
    } else {
        setAdvancedDateRangeByDays(90);
    }
}

function applyAdvancedSalesSelection() {
    const state = loadAdvancedFilterState();
    if (!state || !state.salesperson) return;
    const allTag = document.querySelector('#advancedSalesTags .tag.all');
    if (!allTag) return;

    if (state.salesperson === 'all') {
        document.querySelectorAll('#advancedSalesTags .tag').forEach(tag => {
            tag.classList.toggle('active', tag.classList.contains('all'));
        });
        return;
    }

    const selected = Array.isArray(state.salesperson) ? state.salesperson : [state.salesperson];
    document.querySelectorAll('#advancedSalesTags .tag').forEach(tag => {
        if (tag.classList.contains('all')) {
            tag.classList.remove('active');
        } else {
            tag.classList.toggle('active', selected.includes(tag.dataset.value));
        }
    });
}

function restoreAdvancedFilterState() {
    const state = loadAdvancedFilterState();
    if (!state) return;

    const orderNumber = document.getElementById('advancedOrderNumber');
    const customerName = document.getElementById('advancedCustomerName');
    if (orderNumber) orderNumber.value = state.orderNumber || '';
    if (customerName) customerName.value = state.customerName || '';

    document.querySelectorAll('#advancedFilterModal .s-btn').forEach(btn => {
        const key = btn.dataset.status;
        if (key === 'ongoing') btn.classList.toggle('active', state.statusOngoing !== false);
        if (key === 'completed') btn.classList.toggle('active', !!state.statusCompleted);
        if (key === 'cancelled') btn.classList.toggle('active', !!state.statusCancelled);
    });

    const detail = document.getElementById('advancedTimeDetail');
    const toggle = document.getElementById('advancedTimeToggle');
    if (detail && toggle) {
        detail.classList.toggle('show', !!state.dateEnabled);
        toggle.classList.toggle('active', !!state.dateEnabled);
    }

    const fromInput = document.getElementById('advancedDateFrom');
    const toInput = document.getElementById('advancedDateTo');
    if (fromInput) fromInput.value = state.dateFrom || '';
    if (toInput) toInput.value = state.dateTo || '';

    if (state.quickRange) {
        const tag = document.querySelector(`#advancedFilterModal .q-tag[data-range="${state.quickRange}"]`);
        if (tag) {
            setAdvancedQuickRange(tag);
            tag.classList.add('active');
        }
    }

    applyAdvancedSalesSelection();
    updateAdvancedStatusHint();
}

function setAdvancedDateRangeByDays(days) {
    const fromInput = document.getElementById('advancedDateFrom');
    const toInput = document.getElementById('advancedDateTo');
    if (!fromInput || !toInput) return;

    const today = new Date();
    const start = new Date(today);
    start.setDate(today.getDate() - days);

    const pad = (n) => String(n).padStart(2, '0');
    const format = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

    fromInput.value = format(start);
    toInput.value = format(today);
}

function resetAdvancedFilters() {
    const orderNumber = document.getElementById('advancedOrderNumber');
    const customerName = document.getElementById('advancedCustomerName');
    if (orderNumber) orderNumber.value = '';
    if (customerName) customerName.value = '';

    document.querySelectorAll('#advancedSalesTags .tag').forEach(tag => {
        if (tag.classList.contains('all')) {
            tag.classList.add('active');
        } else {
            tag.classList.remove('active');
            tag.style.display = '';
        }
    });

    const searchInput = document.getElementById('advancedSalesSearch');
    if (searchInput) searchInput.value = '';

    document.querySelectorAll('#advancedFilterModal .s-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.status === 'ongoing');
    });

    const toggle = document.getElementById('advancedTimeToggle');
    const detail = document.getElementById('advancedTimeDetail');
    if (toggle) toggle.classList.remove('active');
    if (detail) detail.classList.remove('show');
    document.querySelectorAll('#advancedFilterModal .q-tag').forEach(tag => tag.classList.remove('active'));

    const fromInput = document.getElementById('advancedDateFrom');
    const toInput = document.getElementById('advancedDateTo');
    if (fromInput) fromInput.value = '';
    if (toInput) toInput.value = '';

    updateAdvancedStatusHint();
    clearAdvancedFilterState();
    advancedFilterSkipDefault = true;
}

function getAdvancedSalesSelection() {
    const allTag = document.querySelector('#advancedSalesTags .tag.all');
    if (!allTag) return 'all';
    if (allTag.classList.contains('active')) return 'all';

    const selected = Array.from(document.querySelectorAll('#advancedSalesTags .tag.active:not(.all)'))
        .map(tag => tag.dataset.value)
        .filter(Boolean);

    return selected.length > 0 ? selected : 'all';
}

function collectAdvancedFilters() {
    const timeEnabled = document.getElementById('advancedTimeDetail')?.classList.contains('show');
    return {
        orderNumber: document.getElementById('advancedOrderNumber')?.value?.trim() || '',
        customerName: document.getElementById('advancedCustomerName')?.value?.trim() || '',
        dateEnabled: !!timeEnabled,
        dateFrom: document.getElementById('advancedDateFrom')?.value || null,
        dateTo: document.getElementById('advancedDateTo')?.value || null,
        statusOngoing: document.querySelector('#advancedFilterModal .s-btn[data-status="ongoing"]')?.classList.contains('active'),
        statusCompleted: document.querySelector('#advancedFilterModal .s-btn[data-status="completed"]')?.classList.contains('active'),
        statusCancelled: document.querySelector('#advancedFilterModal .s-btn[data-status="cancelled"]')?.classList.contains('active'),
        salesperson: getAdvancedSalesSelection(),
        quickRange: document.querySelector('#advancedFilterModal .q-tag.active')?.dataset?.range || null
    };
}

async function applyAdvancedFilters() {
    const filters = collectAdvancedFilters();
    const hasSalesFilter = Array.isArray(filters.salesperson)
        ? (filters.salesperson.length > 0 && !filters.salesperson.includes('all'))
        : (filters.salesperson && filters.salesperson !== 'all');

    if ((filters.statusCompleted || filters.statusCancelled) && !filters.dateEnabled) {
        toggleAdvancedTime();
        setAdvancedDateRangeByDays(365);
        filters.dateEnabled = true;
        filters.dateFrom = document.getElementById('advancedDateFrom')?.value || null;
        filters.dateTo = document.getElementById('advancedDateTo')?.value || null;
    }

    if (!filters.orderNumber && !filters.customerName && !filters.dateEnabled && !hasSalesFilter) {
        showToast('提示', '请至少填写一个查询条件', 'warning');
        return;
    }

    if ((filters.statusCompleted || filters.statusCancelled) && !filters.dateEnabled) {
        showToast('提示', '查询已完成或已取消时，必须指定时间范围', 'warning');
        return;
    }

    if (filters.dateEnabled && (!filters.dateFrom || !filters.dateTo)) {
        setAdvancedDateRangeByDays(365);
        filters.dateFrom = document.getElementById('advancedDateFrom')?.value || null;
        filters.dateTo = document.getElementById('advancedDateTo')?.value || null;
    }

    try {
        showToast('查询中', '正在查询，请稍候...', 'warning');

        if (!isGlobalSearchMode && originalOrders === null) {
            const tbody = document.getElementById('ordersTableBody');
            if (tbody) {
                originalOrders = tbody.innerHTML;
            }
        }

        const response = await fetch('/tracking/api/orders/advanced-search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                orderNumber: filters.orderNumber || null,
                customerName: filters.customerName || null,
                dateFrom: filters.dateEnabled ? filters.dateFrom : null,
                dateTo: filters.dateEnabled ? filters.dateTo : null,
                statusOngoing: filters.statusOngoing,
                statusCompleted: filters.statusCompleted,
                statusCancelled: filters.statusCancelled,
                salesperson: filters.salesperson || 'all'
            })
        });

        const result = await response.json();

        if (!result.success) {
            showToast('查询失败', result.error || '未知错误', 'error');
            return;
        }

        isGlobalSearchMode = true;
        renderSearchResults(result.orders || []);
        updateOrderAgeColumn();
        initQuickActionsForAllRows();
        refreshStatusDaysFromRows();

        showToast('查询完成', `找到 ${result.count || (result.orders || []).length} 条订单`);
        saveAdvancedFilterState(filters);
    } catch (error) {
        console.error('高级筛选失败:', error);
        showToast('查询失败', '网络错误，请稍后再试', 'error');
    }
}

async function loadAdvancedSalespeople() {
    const container = document.getElementById('advancedSalesTags');
    if (!container) return;
    try {
        const response = await fetch('/tracking/api/users');
        const result = await response.json();
        if (!result.success || !Array.isArray(result.data)) return;

        container.querySelectorAll('.tag:not(.all)').forEach(tag => tag.remove());

        const isSelectableRole = (role) => {
            const normalized = String(role || '').toLowerCase();
            return [
                'admin',
                'administrator',
                'superuser',
                'root',
                '主管',
                '管理员',
                'sales',
                'seller',
                'biz',
                'business',
                '业务员',
                '業務員'
            ].includes(normalized);
        };

        result.data
            .filter(user => isSelectableRole(user.role))
            .filter(user => Number(user.workflow_count || user.product_count || 0) > 0)
            .forEach(user => {
            const name = user.real_name || user.display_name || user.username;
            const tag = document.createElement('div');
            tag.className = 'tag';
            tag.dataset.value = user.user_id;
            tag.textContent = name;
            tag.onclick = () => toggleAdvancedSales(tag);
            container.appendChild(tag);
        });
        applyAdvancedSalesSelection();
    } catch (error) {
        console.warn('Load salespeople failed:', error);
    }
}

function updateTeamSalesFilter() {
    const selected = Array.from(document.querySelectorAll('#teamSalesTags .team-tag.active'))
        .map(tag => tag.dataset.value)
        .filter(Boolean);
    currentFilter.teamSales = selected;
    applyFilters();
}

function toggleTeamSales(tag) {
    tag.classList.toggle('active');
    updateTeamSalesFilter();
}

function filterTeamSalesTags() {
    const input = document.getElementById('teamSalesSearch');
    const keyword = input ? input.value.trim().toLowerCase() : '';
    document.querySelectorAll('#teamSalesTags .team-tag').forEach(tag => {
        const text = tag.textContent.trim().toLowerCase();
        tag.style.display = text.includes(keyword) ? '' : 'none';
    });
}

async function loadTeamSalespeople() {
    const container = document.getElementById('teamSalesTags');
    if (!container) return;
    try {
        const response = await fetch('/tracking/api/users');
        const result = await response.json();
        if (!result.success || !Array.isArray(result.data)) return;

        container.innerHTML = '';

        const isSelectableRole = (role) => {
            const normalized = String(role || '').toLowerCase();
            return [
                'admin',
                'administrator',
                'superuser',
                'root',
                '主管',
                '管理员',
                'sales',
                'seller',
                'biz',
                'business',
                '业务员',
                '業務員'
            ].includes(normalized);
        };

        const users = result.data
            .filter(user => isSelectableRole(user.role))
            .filter(user => Number(user.workflow_count || user.product_count || 0) > 0);

        if (users.length === 0) {
            container.innerHTML = '<span class="team-placeholder">暂无成员</span>';
            return;
        }

        users.forEach(user => {
            const name = user.real_name || user.display_name || user.username;
            const tag = document.createElement('button');
            tag.type = 'button';
            tag.className = 'team-tag';
            tag.dataset.value = String(user.user_id || user.id || '');
            tag.textContent = name;
            tag.onclick = () => toggleTeamSales(tag);
            container.appendChild(tag);
        });
    } catch (error) {
        console.warn('Load team sales failed:', error);
    }
}

function initAdvancedFilterModal() {
    const yearsContainer = document.getElementById('advancedQuickYears');
    if (yearsContainer) {
        const yearNow = new Date().getFullYear();
        [yearNow, yearNow - 1].forEach(year => {
            const tag = document.createElement('div');
            tag.className = 'q-tag year';
            tag.dataset.range = `year-${year}`;
            tag.textContent = `${year}年`;
            tag.onclick = () => setAdvancedQuickRange(tag);
            yearsContainer.appendChild(tag);
        });
    }

    updateAdvancedStatusHint();
    loadAdvancedSalespeople();
    loadTeamSalespeople();
    ensureDefaultAdvancedDateRange();
}

function syncStageGroupButtons(primaryGroup) {
    const selected = new Set(currentFilter.stageGroups || ['all']);
    document.querySelectorAll('.stage-btn[data-stage-group]').forEach(btn => {
        const group = btn.dataset.stageGroup || '';
        if (selected.has('all')) {
            btn.classList.toggle('active', group === 'all');
        } else {
            btn.classList.toggle('active', selected.has(group));
        }
    });
    currentFilter.showCompleted = selected.has('completed');
    currentFilter.showCancelled = selected.has('cancelled');
    currentFilter.showNoWorkflow = selected.has('no_workflow');

    if (primaryGroup) {
        const dropdown = document.getElementById(`dropdown-${primaryGroup}`);
        if (dropdown) {
            dropdown.querySelectorAll('.substatus-option').forEach(opt => opt.classList.remove('active'));
            const allOption = dropdown.querySelector('.substatus-option[onclick*="\'all\'"]');
            if (allOption) allOption.classList.add('active');
        }
    }
}

// ==================== 首頁額外初始化 ====================

document.addEventListener('DOMContentLoaded', () => {
    initUnifiedDateInputs(document);
    observeUnifiedDateInputs();

    // 初始化筛选状态 - 根据按钮的初始状态
    const completedBtn = document.getElementById('toggleCompletedBtn');
    const cancelledBtn = document.getElementById('toggleCancelledBtn');
    const noWorkflowBtn = document.getElementById('toggleNoWorkflowBtn');
    
    const selected = [];
    if (completedBtn?.classList.contains('active')) selected.push('completed');
    if (cancelledBtn?.classList.contains('active')) selected.push('cancelled');
    if (noWorkflowBtn?.classList.contains('active')) selected.push('no_workflow');
    currentFilter.stageGroups = selected.length > 0 ? selected : ['all'];
    currentFilter.showCompleted = completedBtn?.classList.contains('active');
    currentFilter.showCancelled = cancelledBtn?.classList.contains('active');
    currentFilter.showNoWorkflow = noWorkflowBtn?.classList.contains('active') || false;
    syncStageGroupButtons();
    
    // 应用初始筛选
    applyFilters();
    
    // 初始化今天-订单日期（仅管理员）
    updateOrderAgeColumn();
    
    // 初始化表格排序功能
    initTableSorting();
    
    // 为所有订单行初始化悬停按钮（基于 STATUS_SYSTEM.js）
    initQuickActionsForAllRows();
    
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            selectedCustomerNameFilter = '';
            selectedOrderNumberFilter = '';
            (function(){var _b=document.getElementById('searchClearBtn');if(_b){_b.style.opacity=this.value?'1':'0';_b.style.pointerEvents=this.value?'auto':'none';}}).call(this);
            // 若在全局搜索模式，先恢復原始資料，回到前端篩選
            if (isGlobalSearchMode) {
                isGlobalSearchMode = false;
                originalOrders = null;
            }
            currentFilter.search = this.value;
            applyFilters();
            updateCustomerSearchSuggestions(this.value);
        });

        searchInput.addEventListener('focus', function() {
            if (this.value.trim()) updateCustomerSearchSuggestions(this.value);
        });
        
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                hideCustomerSearchSuggestions();
                globalSearch();
                // Enter 搜尋後也更新 X 按鈕狀態
                (function(v){var _b=document.getElementById('searchClearBtn');if(_b){_b.style.opacity=v?'1':'0';_b.style.pointerEvents=v?'auto':'none';}})(this.value);
            }
        });
    }

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.customer-search-box')) {
            hideCustomerSearchSuggestions();
        }
        if (!e.target.closest('.stage-filter')) {
            document.querySelectorAll('.substatus-dropdown').forEach(dropdown => {
                dropdown.classList.remove('show');
            });
        }
        if (e.target.classList.contains('modal-overlay')) {
            if (e.target.id === 'orderDetailModal') {
                closeOrderDetailModal();
            }
        }
    });

    const orderDateInput = document.getElementById('newOrderDate');
    if (orderDateInput && !orderDateInput.value) {
        orderDateInput.value = getTodayDate();
    }

    const stageBar = document.getElementById('stageFilterBar');
    if (stageBar) {
        updateStageFilters('all');
    }

    initAdvancedFilterModal();
});

// ==================== 撤销最后一步功能 ====================

async function undoLastStep(orderNumber, restoreStatus, currentStatus) {
    // 使用状态转换样式显示（和确认下一步骤一样）
    const confirmed = await showConfirmModal(
        '', // 消息留空，因为用状态转换区域显示
        '确认撤销',
        '确认撤销',
        '取消',
        true,
        {
            currentStatus: currentStatus,
            nextStatus: restoreStatus,
            orderNumber: orderNumber
        }
    );
    
    if (!confirmed) return;
    
    // 可选：询问原因 - 暂时跳过，使用空字符串
    const reason = '';
    
    try {
        const response = await fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}/undo-last-step`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason: reason || '' })
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (typeof showToast === 'function') {
                showToast('撤销成功', result.message);
            } else {
                showToast('成功', result.message, 'success');
            }
            
            // 使用统一的刷新函数，不刷新整个页面
            refreshAllComponents(orderNumber);
        } else {
            showToast('错误', '撤销失败：' + result.error, 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showToast('错误', '网络错误', 'error');
    }
}



// ==================== 删除订单功能 ====================

/**
 * 从菜单确认删除订单
 */
function confirmDeleteOrderFromMenu() {
    // 关闭菜单
    closeModal();
    
    // 获取当前订单信息
    const orderNumber = currentOrderId;
    
    // 从页面获取订单详细信息
    const orderRow = document.querySelector(`tr[data-order="${orderNumber}"]`);
    if (!orderRow) {
        showToast('错误', '找不到订单信息', 'error');
        return;
    }
    
    const customerCell = orderRow.querySelector('td:nth-child(4)');
    const statusCell = orderRow.querySelector('td:nth-child(5)');
    
    const customerName = customerCell ? customerCell.textContent.trim() : '未知客户';
    const currentStatus = statusCell ? statusCell.textContent.trim().replace(/||/g, '').trim() : '未知状态';
    
    // 调用删除确认
    confirmDeleteOrder(orderNumber, customerName, currentStatus);
}

/**
 * 确认并删除订单
 */
async function confirmDeleteOrder(orderNumber, customerName, currentStatus) {
    // 第一步：基本确认
    const confirmed = await showConfirmModal(
        `警告：确认删除订单？\n\n` +
        `订单号：${orderNumber}\n` +
        `客户：${customerName}\n` +
        `状态：${currentStatus}\n\n` +
        `警告：此操作会永久删除订单！\n` +
        `• 删除订单记录\n` +
        `• 删除所有状态历史\n` +
        `• 删除所有备注\n` +
        `• 无法恢复！\n\n` +
        `确定要继续吗？`
    );
    
    if (!confirmed) return;
    
    // 第二步：输入订单号确认
    showPromptModal(
        `警告：最后确认\n\n为防止误操作，请输入订单号确认删除：\n${orderNumber}`,
        '确认删除',
        '',
        '请输入订单号'
    ).then(confirmInput => {
        if (confirmInput !== orderNumber) {
            showToast('错误', '订单号不匹配，已取消删除', 'error');
            return;
        }
        
        // 第三步：询问原因（可选）
        showPromptModal('删除原因（选填）：', '删除原因', '输入错误', '请输入删除原因').then(reason => {
            // 执行删除
            deleteOrder(orderNumber, reason || '输入错误');
        });
    });
}

/**
 * 执行删除订单
 */
async function deleteOrder(orderNumber, reason) {
    try {
        const response = await fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                confirm_order_number: orderNumber,
                reason: reason || ''
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (typeof showToast === 'function') {
                showToast('删除成功', result.message);
            } else {
                showToast('成功', result.message, 'success');
            }
            setTimeout(() => location.reload(), 1000);
        } else {
            showToast('错误', '删除失败：' + result.error, 'error');
        }
    } catch (error) {
        console.error('Delete order error:', error);
        showToast('错误', '网络错误：' + error.message, 'error');
    }
}

// ==================== 訂單詳情頁：專用功能 ====================

/**
 * 渲染水平流程時間軸
 */
function renderProcessTimeline() {
    const container = document.getElementById('processTimeline');
    if (!container) return;
    
    const orderDataElement = document.getElementById('orderData');
    if (!orderDataElement) return;
    
    const orderData = JSON.parse(orderDataElement.textContent);
    const orderHistory = orderData.history;
    
    if (!orderHistory || orderHistory.length === 0) return;
    
    // 折叠配置：如果超过5条记录，默认只显示最近的5条
    const MAX_VISIBLE_DEFAULT = 5;
    const TOTAL_THRESHOLD = 5;
    const shouldCollapse = orderHistory.length > TOTAL_THRESHOLD;
    const visibleCount = shouldCollapse ? MAX_VISIBLE_DEFAULT : orderHistory.length;
    const hiddenCount = orderHistory.length - visibleCount;
    
    // 检查是否已展开（从容器数据属性获取）
    const isExpanded = container.dataset.isExpanded === 'true';
    const displayCount = isExpanded ? orderHistory.length : visibleCount;
    const displayHistory = isExpanded ? orderHistory : orderHistory.slice(-displayCount);
    
    let html = '';
    
    const collapsedIndicator = `
        <div class="step-item collapsed-indicator">
            <div class="icon-circle">⋯</div>
            <div class="label">已折叠 ${hiddenCount} 条记录</div>
            <div class="date"></div>
            </div>
        `;
    html = generateTimeline(
        displayHistory,
        'zh_tw',
        { prependHtml: (shouldCollapse && !isExpanded) ? collapsedIndicator : '' }
    );
    
    container.innerHTML = html;
    
    // 添加展开/折叠按钮（如果超过阈值）
    if (shouldCollapse) {
        // 移除旧的按钮（如果存在）
        const oldButton = container.parentElement.querySelector('.timeline-toggle-container');
        if (oldButton) oldButton.remove();
        
        const toggleButton = document.createElement('div');
        toggleButton.className = 'timeline-toggle-container';
        toggleButton.style.cssText = 'margin-top: 1rem; text-align: center;';
        toggleButton.innerHTML = isExpanded
            ? `<button class="btn btn-secondary" onclick="toggleProcessTimelineExpand(false);" style="padding: 0.5rem 1rem; font-size: 0.85rem;">
                📕 折叠早期记录
            </button>`
            : `<button class="btn btn-secondary" onclick="toggleProcessTimelineExpand(true);" style="padding: 0.5rem 1rem; font-size: 0.85rem;">
                📖 展开全部记录 (${hiddenCount} 条)
            </button>`;
        container.parentElement.appendChild(toggleButton);
    }
    
    // 保存完整历史数据到容器，以便展开时使用
    container.dataset.fullHistory = JSON.stringify(orderHistory);
    container.dataset.isExpanded = isExpanded ? 'true' : 'false';
}

/**
 * 切换详情页时间轴展开/折叠状态
 */
function toggleProcessTimelineExpand(expand) {
    const container = document.getElementById('processTimeline');
    if (!container) return;
    
    container.dataset.isExpanded = expand ? 'true' : 'false';
    
    // 重新渲染
    renderProcessTimeline();
}

// 订单详情页初始化
document.addEventListener('DOMContentLoaded', function() {
    // 如果存在流程時間軸容器，則渲染
    if (document.getElementById('processTimeline')) {
        renderProcessTimeline();
    }
});
/**
 * 從表格中的「⋯ 详情」按鈕開啟 WORKSPACE 抽屜
 * 避免在 HTML 裡直接寫一大串 JS + Jinja，降低 IDE 語法誤判
 */
async function openDetailDrawerFromRow(buttonEl) {
    if (!buttonEl) return;
    const row = buttonEl.tagName === 'TR'
        ? buttonEl
        : (buttonEl.closest('tr[data-order-number]') || buttonEl.closest('tr[data-workflow-number]'));
    if (!row) return;
    if (row.dataset.inlineEditing === 'true') return;

    // 优先使用 workflow_number，如果没有则使用 order_number
    const workflowNumber = row.dataset.workflowNumber || '';
    const orderNumber = row.dataset.orderNumber || '';
    
    // 如果有 workflowNumber，直接使用 WORKSPACE 抽屜
    if (workflowNumber && typeof WorkspaceDrawer !== 'undefined' && WorkspaceDrawer.open) {
        WorkspaceDrawer.open(workflowNumber);
        return;
    }
    
    // 如果只有 orderNumber，嘗試獲取該訂單的第一個工作流
    if (orderNumber && typeof WorkspaceDrawer !== 'undefined' && WorkspaceDrawer.openFromOrder) {
        try {
            await WorkspaceDrawer.openFromOrder(orderNumber);
            return;
        } catch (error) {
            console.warn('[openDetailDrawerFromRow] 無法打開 WORKSPACE 抽屜:', error);
        }
    }
    
    console.warn('[openDetailDrawerFromRow] WORKSPACE 抽屜不可用，已略過舊抽屜入口');
}

/**
 * 显示跳过阶段 Modal
 */
function showSkipStageModal(orderNumber, currentStatus, workflowNumber = '') {
    const modal = document.getElementById('skipStageModal');
    if (!modal) {
        console.error('Skip stage modal not found');
        return;
    }
    
    const currentStatusEl = document.getElementById('skipCurrentStatus');
    const optionsContainer = document.getElementById('skipStageOptions');
    
    if (currentStatusEl) {
        currentStatusEl.textContent = displayStatus(currentStatus);
    }
    
    // 获取可跳转的状态
    const skippableStatuses = getSkippableStatuses(currentStatus);
    
    if (!skippableStatuses || skippableStatuses.length === 0) {
        showToast('提示', '当前状态无法跳过到其他阶段');
        return;
    }
    
    let optionsHTML = '';
    skippableStatuses.forEach((status, index) => {
        const displayName = displayStatus(status);
        const icon = getStatusIcon(status);
        const stageName = getStageName(status);
        
        optionsHTML += `
            <label class="skip-option">
                <input type="radio" name="skipTarget" value="${status}" ${index === 0 ? 'checked' : ''}>
                <span class="skip-option-content">
                    <span class="skip-option-icon">${icon}</span>
                    <span class="skip-option-text">
                        <strong>${displayName}</strong>
                        <small>${stageName}</small>
                    </span>
                </span>
            </label>
        `;
    });
    
    if (optionsContainer) {
        optionsContainer.innerHTML = optionsHTML;
    }
    
    // 保存订单号/工作流号和当前状态
    modal.dataset.orderNumber = orderNumber;
    modal.dataset.workflowNumber = workflowNumber || '';
    modal.dataset.currentStatus = currentStatus;
    const row = workflowNumber
        ? document.querySelector(`tr[data-workflow-number="${workflowNumber}"]`)
        : document.querySelector(`tr[data-order-number="${orderNumber}"]`);
    modal.dataset.expectedHistoryId = row ? row.dataset.historyId || '' : '';
    
    modal.classList.add('show');
}

/**
 * 关闭跳过阶段 Modal
 */
function closeSkipStageModal() {
    const modal = document.getElementById('skipStageModal');
    if (modal) {
        modal.classList.remove('show');
        // 清空备注
        const notesField = document.getElementById('skipStageNotes');
        if (notesField) {
            notesField.value = '';
        }
    }
}

/**
 * 确认跳过阶段
 */
async function confirmSkipStage() {
    const modal = document.getElementById('skipStageModal');
    if (!modal) return;
    
    const orderNumber = modal.dataset.orderNumber;
    const workflowNumber = modal.dataset.workflowNumber;
    const currentStatus = modal.dataset.currentStatus;
    const expectedHistoryId = modal.dataset.expectedHistoryId || '';
    const selectedTarget = document.querySelector('input[name="skipTarget"]:checked');
    const notes = document.getElementById('skipStageNotes').value;
    
    if (!selectedTarget) {
        showToast('错误', '请选择目标阶段', 'error');
        return;
    }
    
    const targetStatus = selectedTarget.value;
    const targetDisplayName = displayStatus(targetStatus);

    let actionDate = getTodayDate();
    let finalNotes = notes || `跳过阶段：${displayStatus(currentStatus)} → ${targetDisplayName}`;
    if (isShippingStatus(targetStatus)) {
        const details = await requestShippingActionDetails({
            action: targetStatus === 'PARTIAL_SHIPPED' ? 'ship_partial' : (targetStatus === 'ALL_SHIPPED' ? 'ship_all' : 'shipping_complete'),
            orderNumber: workflowNumber || orderNumber,
            currentStatus,
            nextStatus: targetStatus,
            notes
        });
        if (!details) return;
        actionDate = details.date;
        finalNotes = details.notes || finalNotes;
    }

    // 准备请求数据
    const requestData = {
        action_date: actionDate,
        notes: finalNotes
    };
    if (expectedHistoryId) {
        requestData.expected_history_id = expectedHistoryId;
    }
    
    // 调用 API 执行状态更新
    const endpoint = workflowNumber
        ? `/tracking/api/workflows/${workflowNumber}/status-direct`
        : `/tracking/api/orders/${orderNumber}/status`;
    fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            new_status: targetStatus,
            expected_status: currentStatus,
            action_date: requestData.action_date,
            notes: requestData.notes,
            expected_history_id: requestData.expected_history_id
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            showToast('跳过成功', `已从「${displayStatus(currentStatus)}」跳到「${targetDisplayName}」`);
            
            // 1. 立即关闭 Modal
            closeSkipStageModal();
            
            // 2. 刷新列表（仅旧抽屉时）
            if (!(window.WorkspaceDrawer && WorkspaceDrawer.state && WorkspaceDrawer.state.isOpen)) {
                setTimeout(() => {
                    refreshAndHighlightOrder(orderNumber);
                }, 300);
            }
        } else {
            showToast('跳过失败', data.error || '操作失败', 'error');
        }
    })
    .catch(err => {
        console.error('跳过阶段失败:', err);
        showToast('跳过失败', '网络错误', 'error');
    });
}

/**
 * 刷新页面并高亮显示指定订单
 */
function refreshAndHighlightOrder(orderNumber) {
    // 刷新页面并通过 URL 参数传递高亮订单号
    const url = new URL(window.location.href);
    url.searchParams.set('highlight', orderNumber);
    window.location.href = url.toString();
}

/**
 * 高亮显示订单行
 */
function highlightOrderRow(orderNumber) {
    // 找到订单行
    const orderRow = document.querySelector(`tr[data-order-number="${orderNumber}"]`) ||
        document.querySelector(`tr[data-workflow-number="${orderNumber}"]`);
    if (!orderRow) {
        console.warn(`找不到订单 ${orderNumber} 的行`);
        return;
    }
    
    // 添加高亮类
    orderRow.classList.add('order-highlight');
    
    // 滚动到可见区域
    orderRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
    
    // 5秒后移除高亮
    setTimeout(() => {
        orderRow.classList.remove('order-highlight');
    }, 10000);
}

/**
 * 页面加载时检查是否有需要高亮的订单
 */
document.addEventListener('DOMContentLoaded', function() {
    const urlParams = new URLSearchParams(window.location.search);
    const highlightOrder = urlParams.get('highlight');
    
    if (highlightOrder) {
        setTimeout(() => {
            highlightOrderRow(highlightOrder);
            // 清除 URL 参数
            const url = new URL(window.location.href);
            url.searchParams.delete('highlight');
            window.history.replaceState({}, '', url.toString());
        }, 500);
    }
});


/**
 * 从表格行编辑订单（使用 Modal）
 */
function editOrderFromTable(orderNumber) {
    if (!orderNumber) {
        showToast('错误', '无法获取订单号');
        return;
    }
    
    // 获取订单数据
    fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}`)
        .then(res => res.json())
        .then(result => {
            if (result.success && result.data) {
                const order = result.data;
                
                // 设置标题
                const title = document.getElementById('editOrderModalTitle');
                if (title) {
                    title.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 6px;"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>编辑订单';
                }
                
                // 设置提交按钮文本
                const submitBtn = document.getElementById('editOrderSubmitBtn');
                if (submitBtn) submitBtn.textContent = '保存修改 ';
                
                // 填充表单
                const orderNumberInput = document.getElementById('editOrderNumber');
                orderNumberInput.value = orderNumber;
                orderNumberInput.readOnly = true;
                orderNumberInput.style.background = '#f3f4f6';
                orderNumberInput.setAttribute('data-original-order-number', orderNumber);
                
                document.getElementById('editCustomerName').value = order.customer_name || '';
                document.getElementById('editOrderDate').value = order.order_date || '';
                document.getElementById('editProductCode').value = order.product_code || '';
                document.getElementById('editQuantity').value = order.quantity || '';
                document.getElementById('editFactory').value = order.factory || '';
                document.getElementById('editExpectedDeliveryDate').value = order.expected_delivery_date || '';
                document.getElementById('editProductionType').value = order.production_type || '';
                document.getElementById('editNotes').value = order.notes || '';
                
                // 显示"修改订单号"按钮
                const toggleBtn = document.getElementById('toggleOrderNumberEdit');
                const warning = document.getElementById('editOrderNumberWarning');
                const errorDiv = document.getElementById('editOrderNumberError');
                if (toggleBtn) toggleBtn.style.display = 'block';
                if (warning) warning.style.display = 'none';
                if (errorDiv) errorDiv.style.display = 'none';
                
                // 添加订单号输入监听
                setupOrderNumberValidation(orderNumberInput, false);
                
                // 隐藏提示
                const hint = document.getElementById('editOrderNumberHint');
                if (hint) hint.style.display = 'none';
                
                // 显示 Modal
                const modal = document.getElementById('editOrderModal');
                if (modal) {
                    modal.classList.add('show');
                    modal.setAttribute('data-mode', 'edit');
                }
            } else {
                showToast('错误', result.error || '无法获取订单数据');
            }
        })
        .catch(err => {
            console.error('Error fetching order:', err);
            showToast('错误', '获取订单数据失败');
        });
}

/**
 * 内联编辑备注功能
 */
function toggleNotesEdit(identifier, buttonEl) {
    const notesCell = buttonEl.closest('.order-notes');
    if (!notesCell) return;

    const displayDiv = notesCell.querySelector('.notes-display');
    const viewRow = notesCell.querySelector('.notes-view-row');
    const editDiv = notesCell.querySelector('.notes-edit');
    const textarea = editDiv ? editDiv.querySelector('.notes-input') : null;
    if (!displayDiv || !editDiv || !textarea) return;

    const isHidden = editDiv.style.display === 'none' || getComputedStyle(editDiv).display === 'none';
    if (isHidden) {
        // 主頁恢復原始行為：鉛筆只編輯備註，不連動其他欄位。
        notesCell.classList.add('notes-editing');
        const editingRow = notesCell.closest('tr');
        if (editingRow) editingRow.dataset.inlineEditing = 'true';
        if (viewRow) {
            viewRow.style.display = 'none';
        } else {
            displayDiv.style.display = 'none';
        }
        editDiv.style.display = 'flex';

        const preview = displayDiv.querySelector('.notes-preview');
        if (preview) {
            let fullNote = '';
            const encoded = preview.dataset ? preview.dataset.fullNote : '';
            if (encoded) {
                try { fullNote = decodeURIComponent(encoded); } catch (_) { fullNote = preview.title || preview.textContent || ''; }
            } else {
                fullNote = preview.title || preview.textContent || '';
            }
            textarea.value = fullNote;
        } else {
            textarea.value = '';
        }

        setTimeout(() => {
            textarea.focus();
            textarea.select();
        }, 10);

        const finalIdentifier = identifier || notesCell.dataset.workflowNumber || notesCell.dataset.orderNumber || '';
        textarea.onkeydown = function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                const saveBtn = editDiv.querySelector('.notes-save-btn');
                if (saveBtn && !saveBtn.disabled) saveNotes(finalIdentifier, saveBtn);
            } else if (e.key === 'Escape') {
                e.preventDefault();
                const cancelBtn = editDiv.querySelector('.notes-cancel-btn');
                if (cancelBtn) cancelNotesEdit(finalIdentifier, cancelBtn);
            }
        };
    } else {
        const cancelBtn = editDiv.querySelector('.notes-cancel-btn');
        if (cancelBtn) cancelNotesEdit(identifier, cancelBtn);
    }
}

function saveNotes(identifier, buttonEl) {
    const notesCell = buttonEl.closest('.order-notes');
    if (!notesCell) return;

    const textarea = notesCell.querySelector('.notes-input');
    const displayDiv = notesCell.querySelector('.notes-display');
    const viewRow = notesCell.querySelector('.notes-view-row');
    const editDiv = notesCell.querySelector('.notes-edit');
    if (!textarea || !displayDiv || !editDiv) return;

    const notes = textarea.value.trim();
    const row = notesCell.closest('tr');

    buttonEl.disabled = true;
    buttonEl.textContent = '保存中...';

    const isWorkflowNumber = identifier && identifier.includes('-');
    const workflowNumber = notesCell.dataset.workflowNumber || (isWorkflowNumber ? identifier : '');
    const orderNumber = notesCell.dataset.orderNumber || (!isWorkflowNumber ? identifier : '');

    let apiUrl;
    if (isWorkflowNumber && workflowNumber) {
        apiUrl = `/tracking/api/workflows/${encodeURIComponent(workflowNumber)}`;
    } else if (orderNumber) {
        apiUrl = `/tracking/api/orders/${encodeURIComponent(orderNumber)}`;
    } else {
        buttonEl.disabled = false;
        buttonEl.textContent = '保存';
        showToast('错误', '無法確定備註類型');
        return;
    }

    fetch(apiUrl, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes })
    })
    .then(res => res.json())
    .then(data => {
        if (!data.success) {
            showToast('错误', data.error || '保存失敗');
            buttonEl.disabled = false;
            buttonEl.textContent = '保存';
            return;
        }

        if (notes) {
            const displayText = notes.length > 30 ? notes.substring(0, 30) + '...' : notes;
            const escapedNotes = notes.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
            const escapedDisplay = displayText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            displayDiv.innerHTML = `<span class="notes-preview" title="${escapedNotes}" data-full-note="${encodeURIComponent(notes)}" onclick="showFullNotePopover(event, this)">${escapedDisplay}</span>`;
        } else {
            displayDiv.innerHTML = '<span class="notes-empty">-</span>';
        }

        buttonEl.disabled = false;
        buttonEl.textContent = '保存';
        editDiv.style.display = 'none';
        displayDiv.style.display = 'block';
        if (viewRow) viewRow.style.display = 'flex';
        notesCell.classList.remove('notes-editing');

        if (row) {
            row.dataset.notes = notes;
            delete row.dataset.inlineEditing;
        }
        showToast('成功', '備註已保存');
    })
    .catch(err => {
        console.error('Error saving notes:', err);
        showToast('错误', '網絡錯誤');
        buttonEl.disabled = false;
        buttonEl.textContent = '保存';
    });
}

function cancelNotesEdit(identifier, buttonEl) {
    const notesCell = buttonEl.closest('.order-notes');
    if (!notesCell) return;

    const displayDiv = notesCell.querySelector('.notes-display');
    const viewRow = notesCell.querySelector('.notes-view-row');
    const editDiv = notesCell.querySelector('.notes-edit');
    const textarea = editDiv ? editDiv.querySelector('.notes-input') : null;
    const saveBtn = editDiv ? editDiv.querySelector('.notes-save-btn') : null;
    if (!displayDiv || !editDiv || !textarea) return;

    const preview = displayDiv.querySelector('.notes-preview');
    if (preview) {
        const encoded = preview.dataset ? preview.dataset.fullNote : '';
        if (encoded) {
            try { textarea.value = decodeURIComponent(encoded); } catch (_) { textarea.value = preview.title || preview.textContent || ''; }
        } else {
            textarea.value = preview.title || preview.textContent || '';
        }
    } else {
        textarea.value = '';
    }

    if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存';
    }

    editDiv.style.display = 'none';
    displayDiv.style.display = 'block';
    if (viewRow) viewRow.style.display = 'flex';
    notesCell.classList.remove('notes-editing');
    const row = notesCell.closest('tr');
    if (row) delete row.dataset.inlineEditing;
}

/**
 * 更新主表格中对应行的备注显示（保存后同步）
 */
function updateTableNotesAfterSave(identifier, notes) {
    // 支持通过 workflow_number 或 order_number 查找行
    const isWorkflowNumber = identifier && identifier.includes('-');
    const row = isWorkflowNumber 
        ? document.querySelector(`tr[data-workflow-number="${identifier}"]`)
        : document.querySelector(`tr[data-order-number="${identifier}"]`);
    if (!row) return;
    
    const notesCell = row.querySelector('.order-notes');
    if (!notesCell) return;
    
    const displayDiv = notesCell.querySelector('.notes-display');
    if (!displayDiv) return;
    
    // 更新显示内容
    if (notes) {
        const displayText = notes.length > 30 ? notes.substring(0, 30) + '...' : notes;
        // 转义 HTML 特殊字符
        const escapedNotes = notes.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        const escapedDisplay = displayText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        displayDiv.innerHTML = `<span class="notes-preview" title="${escapedNotes}" data-full-note="${encodeURIComponent(notes)}" onclick="showFullNotePopover(event, this)">${escapedDisplay}</span>`;
    } else {
        displayDiv.innerHTML = '<span class="notes-empty">-</span>';
    }
}

/**
 * 设置订单号输入验证
 */
let orderNumberCheckTimeout;
function setupOrderNumberValidation(input, isNewMode) {
    // 移除旧的监听器
    const newInput = input.cloneNode(true);
    input.parentNode.replaceChild(newInput, input);
    
    // 添加新的监听器
    newInput.addEventListener('input', function() {
        const orderNumber = this.value.trim();
        const errorDiv = document.getElementById('editOrderNumberError');
        const originalOrderNumber = this.getAttribute('data-original-order-number');
        
        // 清除之前的定时器
        clearTimeout(orderNumberCheckTimeout);
        
        // 如果是编辑模式且订单号未改变，不检查
        if (!isNewMode && originalOrderNumber && orderNumber === originalOrderNumber) {
            if (errorDiv) errorDiv.style.display = 'none';
            return;
        }
        
        // 如果订单号为空，隐藏错误提示
        if (!orderNumber) {
            if (errorDiv) errorDiv.style.display = 'none';
            return;
        }
        
        // 防抖：延迟 500ms 后检查
        orderNumberCheckTimeout = setTimeout(() => {
            fetch(`/tracking/api/orders/check-number?order_number=${encodeURIComponent(orderNumber)}`)
                .then(res => res.json())
                .then(data => {
                    if (data.exists) {
                        if (errorDiv) {
                            errorDiv.textContent = '错误：' + data.message;
                            errorDiv.style.display = 'block';
                        }
                    } else {
                        if (errorDiv) errorDiv.style.display = 'none';
                    }
                })
                .catch(err => {
                    console.error('檢查訂單號失敗:', err);
                });
        }, 500);
    });
}

/**
 * 切换订单号编辑状态
 */
function toggleOrderNumberEdit() {
    const orderNumberInput = document.getElementById('editOrderNumber');
    const toggleBtn = document.getElementById('toggleOrderNumberEdit');
    const warning = document.getElementById('editOrderNumberWarning');
    const errorDiv = document.getElementById('editOrderNumberError');
    
    if (orderNumberInput.readOnly) {
        // 解锁编辑
        orderNumberInput.readOnly = false;
        orderNumberInput.style.background = '';
        orderNumberInput.focus();
        if (toggleBtn) {
            toggleBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>锁定订单号';
        }
        if (warning) warning.style.display = 'block';
        // 解锁后立即检查订单号
        const orderNumber = orderNumberInput.value.trim();
        if (orderNumber) {
            const originalOrderNumber = orderNumberInput.getAttribute('data-original-order-number');
            if (orderNumber !== originalOrderNumber) {
                fetch(`/tracking/api/orders/check-number?order_number=${encodeURIComponent(orderNumber)}`)
                    .then(res => res.json())
                    .then(data => {
                        if (data.exists) {
                            if (errorDiv) {
                                errorDiv.textContent = '错误：' + data.message;
                                errorDiv.style.display = 'block';
                            }
                        } else {
                            if (errorDiv) errorDiv.style.display = 'none';
                        }
                    })
                    .catch(err => console.error('檢查訂單號失敗:', err));
            }
        }
    } else {
        // 锁定编辑
        orderNumberInput.readOnly = true;
        orderNumberInput.style.background = '#f3f4f6';
        if (toggleBtn) {
            toggleBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>修改订单号';
        }
        if (warning) warning.style.display = 'none';
        if (errorDiv) errorDiv.style.display = 'none';
    }
}

/**
 * 关闭编辑订单 Modal
 */
function closeEditOrderModal() {
    const modal = document.getElementById('editOrderModal');
    if (modal) {
        modal.classList.remove('show');
        modal.removeAttribute('data-mode');
    }
    
    // 重置订单号编辑状态
    const orderNumberInput = document.getElementById('editOrderNumber');
    const toggleBtn = document.getElementById('toggleOrderNumberEdit');
    const warning = document.getElementById('editOrderNumberWarning');
    if (orderNumberInput) {
        orderNumberInput.readOnly = true;
        orderNumberInput.style.background = '#f3f4f6';
        orderNumberInput.removeAttribute('data-original-order-number');
    }
    if (toggleBtn) toggleBtn.style.display = 'none';
    if (warning) warning.style.display = 'none';
}

/**
 * 确认编辑/新增订单
 */
function confirmEditOrder() {
    const modal = document.getElementById('editOrderModal');
    const isNewMode = modal && modal.getAttribute('data-mode') === 'new';
    
    const orderNumber = document.getElementById('editOrderNumber').value.trim();
    const customerName = document.getElementById('editCustomerName').value.trim();
    const orderDate = document.getElementById('editOrderDate').value;
    
    // 验证必填项
    if (!customerName) {
        showToast('错误', '客户名称不能为空', 'error');
        document.getElementById('editCustomerName').focus();
        return;
    }
    
    if (!orderDate) {
        showToast('错误', '订单日期不能为空', 'error');
        document.getElementById('editOrderDate').focus();
        return;
    }
    
    // 准备数据
    const orderData = {
        order_number: orderNumber || '', // 新增时可以为空
        customer_name: customerName,
        order_date: orderDate,
        product_code: document.getElementById('editProductCode').value.trim(),
        product_name: document.getElementById('editProductCode').value.trim(),
        quantity: document.getElementById('editQuantity').value.trim(),
        factory: document.getElementById('editFactory').value.trim(),
        expected_delivery_date: document.getElementById('editExpectedDeliveryDate').value,
        production_type: document.getElementById('editProductionType').value.trim(),
        pattern_code: '',
        notes: document.getElementById('editNotes').value.trim()
    };
    
    if (isNewMode) {
        // 新增订单
        fetch('/tracking/api/orders', {
            method: 'POST',
        headers: { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
            body: JSON.stringify(orderData)
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
                showToast('创建成功', '订单已创建');
                closeEditOrderModal();
                
                // 刷新页面
                setTimeout(() => {
                    window.location.reload();
                }, 500);
            } else {
                showToast('创建失败', data.error || data.message || '操作失败', 'error');
            }
        })
        .catch(err => {
            console.error('创建订单失败:', err);
            showToast('创建失败', '网络错误', 'error');
        });
    } else {
        // 编辑订单
        if (!orderNumber) {
            showToast('错误', '订单号不能为空', 'error');
            return;
        }
        
        // 检查订单号是否被修改
        const orderNumberInput = document.getElementById('editOrderNumber');
        const originalOrderNumber = orderNumberInput.getAttribute('data-original-order-number');
        const orderNumberChanged = originalOrderNumber && orderNumber !== originalOrderNumber;
        
        // 如果订单号被修改，使用特殊的更新 API
        const apiUrl = orderNumberChanged 
            ? `/tracking/api/orders/${encodeURIComponent(originalOrderNumber)}/change-number`
            : `/tracking/api/orders/${encodeURIComponent(orderNumber)}`;
        
        // 如果订单号被修改，需要在数据中包含新订单号
        if (orderNumberChanged) {
            orderData.new_order_number = orderNumber;
        }
        
        fetch(apiUrl, {
            method: orderNumberChanged ? 'POST' : 'PUT',
            headers: { 
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(orderData)
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                if (orderNumberChanged) {
                    showToast('保存成功', `订单号已从 ${originalOrderNumber} 修改为 ${orderNumber}`);
                    // 订单号已改变，需要刷新页面
                    closeEditOrderModal();
                    setTimeout(() => {
                        window.location.reload();
                    }, 500);
                } else {
            showToast('保存成功', '订单信息已更新');
            // 1. 关闭 Modal
            closeEditOrderModal();
            
            // 2. 刷新并高亮显示
            setTimeout(() => {
                refreshAndHighlightOrder(orderNumber);
            }, 300);
                }
        } else {
                showToast('保存失败', data.error || data.message || '操作失败', 'error');
        }
    })
    .catch(err => {
        console.error('编辑订单失败:', err);
            showToast('保存失败', '网络错误', 'error');
    });
    }
}

/**
 * 关闭取消订单 Modal
 */
function closeCancelOrderModal() {
    const modal = document.getElementById('cancelOrderModal');
    if (modal) {
        modal.classList.remove('show');
    }
}

/**
 * 确认取消订单
 */
function confirmCancelOrder() {
    const orderNumber = document.getElementById('cancelOrderNumber').textContent.replace('#', '').trim();
    const reason = document.getElementById('cancelReason').value.trim();
    
    if (!reason) {
        showToast('错误', '请填写取消原因', 'error');
        document.getElementById('cancelReason').focus();
        return;
    }
    
    // 调用 API
    fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            new_status: STATUS.CANCELLED,
            action_date: getTodayDate(),
            notes: `取消订单：${reason}`
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            showToast('取消成功', `订单 ${orderNumber} 已取消`);
            
            // 1. 立即关闭 Modal
            closeCancelOrderModal();
            
            // 2. 刷新并高亮显示
            setTimeout(() => {
                refreshAndHighlightOrder(orderNumber);
            }, 300);
        } else {
            showToast('取消失败', data.error || '操作失败', 'error');
        }
    })
    .catch(err => {
        console.error('取消订单失败:', err);
        showToast('取消失败', '网络错误', 'error');
    });
}



/**
 * 撤销后更新主页面的订单行
 */
function updateOrderRowAfterUndo(orderNumber, orderData) {
    const row = document.querySelector(`tr[data-order-number="${orderNumber}"]`) ||
                document.querySelector(`tr[data-workflow-number="${orderNumber}"]`);
    if (!row) return;
    
    // 更新状态
    row.dataset.status = orderData.current_status;
    row.dataset.light = orderData.status_light;
    row.dataset.statusUpdatedAt = orderData.status_updated_at || orderData.last_status_change_date || '';
    row.dataset.lastStatusChangeDate = orderData.last_status_change_date || orderData.status_updated_at || '';
    
    // 使用STATUS_SYSTEM获取stage
    const stageGroup = getStageGroup(orderData.current_status);
    
    row.dataset.stageGroup = stageGroup;
    row.className = orderData.status_light;
    
    // 更新灯号（使用 SVG 图标）
    const lightCell = row.querySelector('.light');
    if (lightCell) {
        let lightType = 'green';
        if (orderData.status_light === 'red') lightType = 'red';
        else if (orderData.status_light === 'yellow') lightType = 'yellow';
        else if (orderData.current_status === STATUS.CANCELLED || orderData.current_status === STATUS.COMPLETED) lightType = 'none';
        lightCell.innerHTML = lightType === 'none' ? '' : getStatusLightIcon(lightType);
    }
    
    // 更新阶段显示 - 使用STATUS_SYSTEM
    const stageCurrent = row.querySelector('.stage-current');
    if (stageCurrent) {
        stageCurrent.textContent = displayStatus(orderData.current_status);
    }
    
    // 更新等待天数
    const daysSpan = row.querySelector('.days');
    if (daysSpan) {
        if (orderData.current_status === STATUS.COMPLETED || orderData.current_status === STATUS.CANCELLED) {
            daysSpan.textContent = '-';
            daysSpan.className = 'days';
        } else {
            const statusDays = getOrderWaitingDays(orderData);
            daysSpan.textContent = `${statusDays}天`;
        daysSpan.className = 'days';
        if (orderData.status_light === 'red') daysSpan.className += ' danger';
        else if (orderData.status_light === 'yellow') daysSpan.className += ' warning';
        }
    }
    
    // 重要：更新悬停按钮（根据新状态显示新的操作按钮）
    showQuickActionsForRow(row, orderData.current_status);
    
    // 重新应用筛选（如果当前有筛选）
    if (typeof applyFilters === 'function') {
        applyFilters();
    }
    
    // 高亮显示订单行
    setTimeout(() => {
        if (typeof highlightOrderRow === 'function') {
            highlightOrderRow(orderNumber);
        }
    }, 200);
}

/**
 * 更新筛选按钮的计数（统一使用 STATUS_SYSTEM.js）
 */
function updateFilterCountsFromData(data) {
    const counts = {all:0,new_and_quote:0,draft:0,sampling:0,production:0,shipping:0,waiting_confirm:0,completed:0,cancelled:0,no_workflow:0,red:0,yellow:0,green:0};
    const sub = {};
    (data || []).forEach(item => {
        const status = normalizeStatusForLogic(item.current_status || '');
        const group = getHomeStageGroup(item);
        counts.all++;
        if (item.no_workflow) counts.no_workflow++;
        if (status === STATUS.COMPLETED) counts.completed++;
        else if (status === STATUS.CANCELLED) counts.cancelled++;
        else {
            if (counts.hasOwnProperty(group)) counts[group]++;
            const light = item.status_light || '';
            if (['red','yellow','green'].includes(light)) counts[light]++;
        }
        if ((typeof isStatusInFilter === 'function' && isStatusInFilter(status,'waiting_confirm')) || [STATUS.QUOTE_CONFIRMING,STATUS.DRAFT_CONFIRMING,STATUS.SAMPLE_CONFIRMING].includes(status)) counts.waiting_confirm++;
        sub[status] = (sub[status] || 0) + 1;
    });
    const set=(sel,val)=>{const e=document.querySelector(sel);if(e)e.textContent=val;};
    set('#totalOrders', counts.all); set('#redOrders',counts.red); set('#yellowOrders',counts.yellow); set('#greenOrders',counts.green);
    set('#lightCountRed',counts.red); set('#lightCountYellow',counts.yellow); set('#lightCountGreen',counts.green);
    set('#allCount',counts.all); set('#newAndQuoteCount',counts.new_and_quote); set('#draftCount',counts.draft); set('#samplingCount',counts.sampling); set('#productionCount',counts.production); set('#shippingCount',counts.shipping); set('#waitingConfirmCount',counts.waiting_confirm); set('#quoteCount',counts.waiting_confirm); set('#completedCount',counts.completed); set('#cancelledCount',counts.cancelled); set('#noWorkflowCount',counts.no_workflow);
    const map = new Map([
        ['#new_and_quote-new-count',STATUS.NEW_ORDER],['#new_and_quote-quoting-count',STATUS.QUOTE_CONFIRMING],
        ['#draft-making-count',STATUS.DRAFT_MAKING],['#draft-confirm-count',STATUS.DRAFT_CONFIRMING],['#draft-revise-count',STATUS.DRAFT_REVISING],
        ['#sampling-pending-count',STATUS.PENDING_SAMPLE],['#sampling-making-count',STATUS.SAMPLING],['#sampling-confirm-count',STATUS.SAMPLE_CONFIRMING],['#sampling-revise-count',STATUS.SAMPLE_REVISING],
        ['#production-pending-count',STATUS.PENDING_PRODUCTION],['#production-making-count',STATUS.PRODUCING],['#production-done-count',STATUS.PRODUCTION_DONE],
        ['#shipping-partial-count',STATUS.PARTIAL_SHIPPED],['#shipping-all-shipped-count',STATUS.ALL_SHIPPED]
    ]);
    map.forEach((status,sel)=>set(sel,sub[status]||0));
    set('#new_and_quote-all-count',counts.new_and_quote); set('#draft-all-count',counts.draft); set('#sampling-all-count',counts.sampling); set('#production-all-count',counts.production); set('#shipping-all-count',counts.shipping);
}

function updateFilterCounts() {
    if (homeDataReady && !isGlobalSearchMode) return updateFilterCountsFromData(homeOrdersData);
    const allRows = document.querySelectorAll('#ordersTableBody tr[data-order-number]');
    
    // 统计各状态的数量（使用 STATUS_SYSTEM.js 的阶段分组）
    let counts = {
        all: 0,
        new_and_quote: 0,
        draft: 0,
        sampling: 0,
        production: 0,
        shipping: 0,
        waiting_confirm: 0,  // 等国外确认（虚拟筛选器）
        completed: 0,
        cancelled: 0,
        no_workflow: 0,
        red: 0,
        yellow: 0,
        green: 0
    };

    // 圖稿階段子狀態計數（图稿制作中 / 图稿待确认 / 图稿修改中）
    const draftStatusCounts = {};
    if (typeof STATUS !== 'undefined') {
        draftStatusCounts[STATUS.DRAFT_MAKING] = 0;
        draftStatusCounts[STATUS.DRAFT_CONFIRMING] = 0;
        draftStatusCounts[STATUS.DRAFT_REVISING] = 0;
    }
    
    allRows.forEach(row => {
        const statusRaw = row.dataset.status || '';
        const status = normalizeStatusForLogic(statusRaw); // 用於邏輯的狀態（簡體）
        const stageGroup = row.dataset.stageGroup || '';
        const light = row.dataset.light || '';
        
        // 使用 STATUS_SYSTEM.js 获取阶段分组（如果可用）
        let actualStageGroup = stageGroup;
        if (typeof getStageGroup === 'function' && status) {
            actualStageGroup = getStageGroup(status);
        }
        
        counts.all++;
        
        // 统计进行中的订单（排除已完成和已取消）- 使用 key 判断
        const completedKey = STATUS.COMPLETED;  // 现在是 'COMPLETED'
        const cancelledKey = STATUS.CANCELLED;  // 现在是 'CANCELLED'
        if (status !== completedKey && status !== cancelledKey) {
            // 统计各阶段的数量（只统计进行中的订单）
            if (actualStageGroup && counts.hasOwnProperty(actualStageGroup)) {
                counts[actualStageGroup]++;
            }

            // 如果是圖稿階段，細分三個子狀態
            if (actualStageGroup === 'draft' && draftStatusCounts.hasOwnProperty(status)) {
                draftStatusCounts[status] = (draftStatusCounts[status] || 0) + 1;
            }
            
            // 统计燈號（只統計進行中的訂單）
            if (light === 'red') counts.red++;
            else if (light === 'yellow') counts.yellow++;
            else if (light === 'green') counts.green++;
        }
        
        // 特殊处理：等国外确认（虚拟筛选器 - 使用新的 isStatusInFilter 函数）
        if (typeof isStatusInFilter === 'function') {
            if (isStatusInFilter(status, 'waiting_confirm')) {
                counts.waiting_confirm++;
            }
        } else if (typeof STAGE_GROUPS !== 'undefined' && STAGE_GROUPS.waiting_confirm) {
            // 降级方案：直接检查 STAGE_GROUPS
            const waitingConfirmStatuses = STAGE_GROUPS.waiting_confirm.statuses;
            if (waitingConfirmStatuses && waitingConfirmStatuses.includes(status)) {
                counts.waiting_confirm++;
            }
        }
        
        // 特殊处理：已完成和已取消（独立统计，不重复）
        if (status === STATUS.COMPLETED) {
            counts.completed++;
        } else if (status === STATUS.CANCELLED) {
            counts.cancelled++;
        }
        // 無流程訂單
        if (row.classList.contains('no-workflow-row')) {
            counts.no_workflow++;
        }
    });
    
    // 更新按钮显示
    const updateCount = (selector, count) => {
        const elem = document.querySelector(selector);
        if (elem) elem.textContent = count;
    };
    
    // 更新统计卡片
    updateCount('#totalOrders', counts.all);
    updateCount('#redOrders', counts.red);
    updateCount('#yellowOrders', counts.yellow);
    updateCount('#greenOrders', counts.green);
    
    // 更新燈號篩選按鈕的計數
    updateCount('#lightCountRed', counts.red);
    updateCount('#lightCountYellow', counts.yellow);
    updateCount('#lightCountGreen', counts.green);
    
    // 更新各个按钮的计数
    updateCount('#allCount', counts.all);
    updateCount('#newAndQuoteCount', counts.new_and_quote);
    updateCount('#draftCount', counts.draft);
    updateCount('#samplingCount', counts.sampling);
    updateCount('#productionCount', counts.production);
    updateCount('#shippingCount', counts.shipping);
    updateCount('#waitingConfirmCount', counts.waiting_confirm);  // 更新为新的 ID
    updateCount('#quoteCount', counts.waiting_confirm);  // 兼容旧 ID
    updateCount('#completedCount', counts.completed);
    updateCount('#cancelledCount', counts.cancelled);
    updateCount('#noWorkflowCount', counts.no_workflow);
    
    // ==================== 更新所有階段的子狀態計數（統一處理）====================
    if (typeof STATUS !== 'undefined') {
        // 1. 新訂單/詢價階段
        const newQuoteIdMap = {};
        newQuoteIdMap[STATUS.NEW_ORDER] = '#new_and_quote-new-count';
        newQuoteIdMap[STATUS.QUOTE_CONFIRMING] = '#new_and_quote-quoting-count';
        
        Object.keys(newQuoteIdMap).forEach(statusKey => {
            const selector = newQuoteIdMap[statusKey];
            const value = Array.from(allRows).filter(row => {
                const rowStatus = normalizeStatusForLogic(row.dataset.status || '');
                return rowStatus === statusKey && rowStatus !== STATUS.COMPLETED && rowStatus !== STATUS.CANCELLED;
            }).length;
            updateCount(selector, value);
        });
        updateCount('#new_and_quote-all-count', counts.new_and_quote || 0);
        
        // 2. 圖稿階段
        const draftIdMap = {};
        draftIdMap[STATUS.DRAFT_MAKING] = '#draft-making-count';
        draftIdMap[STATUS.DRAFT_CONFIRMING] = '#draft-confirm-count';
        draftIdMap[STATUS.DRAFT_REVISING] = '#draft-revise-count';

        Object.keys(draftIdMap).forEach(statusKey => {
            const selector = draftIdMap[statusKey];
            const value = draftStatusCounts[statusKey] || 0;
            updateCount(selector, value);
        });
        updateCount('#draft-all-count', counts.draft || 0);
        
        // 3. 打樣階段
        const samplingIdMap = {};
        samplingIdMap[STATUS.PENDING_SAMPLE] = '#sampling-pending-count';
        samplingIdMap[STATUS.SAMPLING] = '#sampling-making-count';
        samplingIdMap[STATUS.SAMPLE_CONFIRMING] = '#sampling-confirm-count';
        samplingIdMap[STATUS.SAMPLE_REVISING] = '#sampling-revise-count';

        Object.keys(samplingIdMap).forEach(statusKey => {
            const selector = samplingIdMap[statusKey];
            const value = Array.from(allRows).filter(row => {
                const rowStatus = normalizeStatusForLogic(row.dataset.status || '');
                return rowStatus === statusKey && rowStatus !== STATUS.COMPLETED && rowStatus !== STATUS.CANCELLED;
            }).length;
            updateCount(selector, value);
        });
        updateCount('#sampling-all-count', counts.sampling || 0);
        
        // 4. 生產階段
        const productionIdMap = {};
        productionIdMap[STATUS.PENDING_PRODUCTION] = '#production-pending-count';
        productionIdMap[STATUS.PRODUCING] = '#production-making-count';
        productionIdMap[STATUS.PRODUCTION_DONE] = '#production-done-count';

        Object.keys(productionIdMap).forEach(statusKey => {
            const selector = productionIdMap[statusKey];
            const value = Array.from(allRows).filter(row => {
                const rowStatus = normalizeStatusForLogic(row.dataset.status || '');
                return rowStatus === statusKey && rowStatus !== STATUS.COMPLETED && rowStatus !== STATUS.CANCELLED;
            }).length;
            updateCount(selector, value);
        });
        updateCount('#production-all-count', counts.production || 0);

        // 5. 出貨階段
        const shippingIdMap = {};
        shippingIdMap[STATUS.PARTIAL_SHIPPED] = '#shipping-partial-count';
        shippingIdMap[STATUS.ALL_SHIPPED] = '#shipping-all-shipped-count';

        Object.keys(shippingIdMap).forEach(statusKey => {
            const selector = shippingIdMap[statusKey];
            const value = Array.from(allRows).filter(row => {
                const rowStatus = normalizeStatusForLogic(row.dataset.status || '');
                return rowStatus === statusKey;
            }).length;
            updateCount(selector, value);
        });
        updateCount('#shipping-all-count', counts.shipping || 0);
    }
}

document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('processTimeline')) {
        renderProcessTimeline();
    }
    refreshStatusDaysFromRows();
});

// ==================== 筛选状态记忆功能 ====================

// 页面加载时恢复筛选状态
function restoreFilterState() {
    try {
        const saved = localStorage.getItem('orderFilterState');
        if (saved) {
            const state = JSON.parse(saved);
            
            // 恢复阶段筛选
            if (state.stageGroups && Array.isArray(state.stageGroups) && state.stageGroups.length) {
                currentFilter.stageGroups = state.stageGroups;
                currentFilter.stageGroup = state.stageGroups.includes('all')
                    ? 'all'
                    : (state.stageGroups.length === 1 ? state.stageGroups[0] : 'multi');
                currentFilter.substatus = state.substatus || 'all';
                syncStageGroupButtons();
            } else if (state.stageGroup && state.stageGroup !== 'all') {
                currentFilter.stageGroups = [state.stageGroup];
                currentFilter.stageGroup = state.stageGroup;
                currentFilter.substatus = state.substatus || 'all';
                syncStageGroupButtons(state.stageGroup);
            }
            
            // 恢复显示已完成/已取消按钮状态
            if (state.showCompleted !== undefined) {
                const completedBtn = document.getElementById('toggleCompletedBtn');
                if (completedBtn) {
                    completedBtn.classList.toggle('active', state.showCompleted);
                    currentFilter.showCompleted = state.showCompleted;
                }
            }
            
            if (state.showCancelled !== undefined) {
                const cancelledBtn = document.getElementById('toggleCancelledBtn');
                if (cancelledBtn) {
                    cancelledBtn.classList.toggle('active', state.showCancelled);
                    currentFilter.showCancelled = state.showCancelled;
                }
            }
            if (!state.stageGroups) {
                const selected = [];
                if (currentFilter.showCompleted) selected.push('completed');
                if (currentFilter.showCancelled) selected.push('cancelled');
                currentFilter.stageGroups = selected.length > 0 ? selected : ['all'];
                syncStageGroupButtons();
            }
            
            // 恢復燈號篩選狀態
            if (state.lights) {
                currentFilter.lights = state.lights;
                // 更新按鈕樣式
                ['red', 'yellow', 'green'].forEach(light => {
                    const button = document.getElementById(`lightFilter${light.charAt(0).toUpperCase() + light.slice(1)}`);
                    if (button) {
                        if (currentFilter.lights[light]) {
                            button.classList.add('active');
                            button.classList.remove('inactive');
                        } else {
                            button.classList.remove('active');
                            button.classList.add('inactive');
                        }
                    }
                });
            }
            
            // 应用筛选
            applyFilters();
        } else {
            // 即使没有保存的筛选状态，也要初始化一次筛选（确保显示正确）
            applyFilters();
        }
    } catch (err) {
        console.error('恢复筛选状态失败:', err);
        // 出错时也要初始化筛选
        try {
            applyFilters();
        } catch (e) {
            console.error('初始化筛选失败:', e);
        }
    }
}

// 保存筛选状态
function saveFilterState() {
    try {
        const state = {
            stageGroup: currentFilter.stageGroup,
            stageGroups: currentFilter.stageGroups,
            substatus: currentFilter.substatus,
            showCompleted: currentFilter.showCompleted,
            showCancelled: currentFilter.showCancelled,
            lights: currentFilter.lights || { red: true, yellow: true, green: true }
        };
        localStorage.setItem('orderFilterState', JSON.stringify(state));
    } catch (err) {
        console.error('保存筛选状态失败:', err);
    }
}

// 页面加载时自动恢复
document.addEventListener('DOMContentLoaded', function() {
    // 初始化燈號按鈕狀態（默認全部激活）
    if (!currentFilter.lights) {
        currentFilter.lights = { red: true, yellow: true, green: true };
    }
    ['red', 'yellow', 'green'].forEach(light => {
        const button = document.getElementById(`lightFilter${light.charAt(0).toUpperCase() + light.slice(1)}`);
        if (button && currentFilter.lights[light]) {
            button.classList.add('active');
        }
    });
    
    restoreFilterState();
    // 转换HTML中硬编码的简体中文为繁体中文
    convertSimplifiedToTraditional();
    
    // 初始化筛选按钮计数（页面加载时）
    if (typeof updateFilterCounts === 'function') {
        // 等待 STATUS_SYSTEM.js 加载完成后再统计
        setTimeout(() => {
            updateFilterCounts();
        }, 100);
    }

    startSalesAutoSync();
    setTimeout(startSalesAutoSync, 500);
});

// ==================== 繁简转换功能 ====================
/**
 * 将HTML中硬编码的简体中文转换为繁体中文
 * 确保与 STATUS_SYSTEM.js 中的 USER_LANG 设置一致
 */
function convertSimplifiedToTraditional() {
    // UI must stay simplified; disable conversion.
    return;
    // 检查是否应该使用繁体中文
    if (typeof USER_LANG === 'undefined' || USER_LANG === 'simplified') {
        return; // 如果使用简体，不需要转换
    }
    
    // 如果 STATUS_SYSTEM.js 未加载，等待一下
    if (typeof displayStatus === 'undefined' || typeof displayText === 'undefined') {
        setTimeout(convertSimplifiedToTraditional, 100);
        return;
    }
    
    // 转换阶段名称
    const stageTextMap = {
        '图稿阶段': '圖稿階段',
        '打样阶段': '打樣階段',
        '生产阶段': '生產階段',
        '新订单/询价': '新訂單/詢價',
        '新订单': '新訂單',
        '已完成': '已完成',
        '已取消': '已取消',
        '其他': '其他'
    };
    
    // 转换状态文本（在表格中的 stage-current 类）
    document.querySelectorAll('.stage-current').forEach(el => {
        const text = el.textContent.trim();
        if (text && typeof displayStatus === 'function') {
            el.textContent = displayStatus(text);
        }
    });
    
    // 转换阶段名称（在表格中的 stage-major 类）
    document.querySelectorAll('.stage-major').forEach(el => {
        let text = el.textContent.trim();
        // 移除emoji，只转换文字部分
        const emojiMatch = text.match(/^([^\s]+)\s+(.+)$/);
        if (emojiMatch) {
            const emoji = emojiMatch[1];
            const stageText = emojiMatch[2];
            if (stageTextMap[stageText]) {
                el.textContent = `${emoji} ${stageTextMap[stageText]}`;
            }
        } else {
            // 如果没有emoji，直接转换
            if (stageTextMap[text]) {
                el.textContent = stageTextMap[text];
            }
        }
    });
    
    // 转换筛选按钮中的文本
    document.querySelectorAll('.stage-btn').forEach(btn => {
        let text = btn.textContent.trim();
        // 移除计数，只转换文字部分
        const textMatch = text.match(/^([^\d]+)/);
        if (textMatch) {
            const stageText = textMatch[1].trim();
            if (stageTextMap[stageText]) {
                const countPart = text.substring(textMatch[0].length);
                btn.childNodes[0].textContent = stageTextMap[stageText] + countPart;
            }
        }
    });
    
    // 转换子状态选项中的文本
    document.querySelectorAll('.substatus-option span').forEach(span => {
        const text = span.textContent.trim();
        if (stageTextMap[text]) {
            span.textContent = stageTextMap[text];
        }
    });
}


// ==================== 全局搜索功能 ====================

let originalOrders = null;  // 保存原始订单数据
let isGlobalSearchMode = false;  // 是否在全局搜索模式
let salesAutoSyncTimer = null;
let salesAutoSyncRunning = false;
let salesAutoSyncLastRequestedAt = 0;

/**
 * 全局搜索函数
 */
async function globalSearch() {
    const searchInput = document.getElementById('searchInput');
    const keyword = searchInput ? searchInput.value.trim() : '';
    // 確保 X 按鈕跟輸入框同步
    (function(v){var _b=document.getElementById('searchClearBtn');if(_b){_b.style.opacity=v?'1':'0';_b.style.pointerEvents=v?'auto':'none';}})(keyword);
    
    try {
        // 显示加载状态
        showToast('搜索中...', '正在查询数据库');
        
        // 如果是第一次搜索，保存原始订单数据
        if (!isGlobalSearchMode && originalOrders === null) {
            const tbody = document.getElementById('ordersTableBody');
            if (tbody) {
                originalOrders = tbody.innerHTML;
            }
        }
        
        // 调用后端API
        const response = await fetch(`/tracking/api/search?q=${encodeURIComponent(keyword)}`);
        const result = await response.json();
        
        if (!result.success) {
            showToast('搜索失败', result.error || '未知错误', 'error');
            return;
        }
        
        // 标记为搜索模式
        isGlobalSearchMode = true;
        
        // 渲染搜索结果
        renderSearchResults(result.orders);
        
        // Toast通知搜索结果
        if (result.limit_reached) {
            showToast('提示', `找到 200+ 条订单（显示前200条）\n💡 建议输入更精确的关键字或使用高级筛选`, 'warning');
        } else if (!keyword && result.type === 'recent') {
            showToast('已刷新', '已重新載入最新数据');
        } else {
            showToast('搜索完成', `✅ 找到 ${result.total} 条订单`);
        }
        
    } catch (error) {
        console.error('全局搜索错误:', error);
        showToast('搜索失败', '网络错误，请稍后再试', 'error');
    }
}

/**
 * 显示搜索结果提示 - 已移除，改用Toast
 */
function showSearchResultHeader(result) {
    // 不再需要此函数
}

/**
 * 渲染搜索结果
 */
function renderSearchResults(orders) {
    const tbody = document.getElementById('ordersTableBody');
    if (!tbody) return;
    
    if (orders.length === 0) {
        const colCount = document.querySelectorAll('table thead th').length || 13;
        tbody.innerHTML = `
            <tr>
                <td colspan="${colCount}" style="text-align: center; padding: 3rem; color: var(--text-3);">
                    <div style="margin-bottom: 1rem;">
                        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin: 0 auto;">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="7 10 12 15 17 10"></polyline>
                            <line x1="12" y1="15" x2="12" y2="3"></line>
                        </svg>
                    </div>
                    <div>未找到匹配的订单</div>
                </td>
            </tr>
        `;
        return;
    }
    
    // 清空现有内容
    tbody.innerHTML = '';
    
    // 渲染每个订单行
    orders.forEach(order => {
        const row = createOrderRow(order);
        tbody.appendChild(row);
    });
    applyColumnSettings();

    if (typeof updateFilterCounts === 'function') {
        updateFilterCounts();
    }
    if (typeof updateOrderAgeColumn === 'function') {
        updateOrderAgeColumn();
    }
    if (typeof initQuickActionsForAllRows === 'function') {
        initQuickActionsForAllRows();
    }
    if (typeof refreshStatusDaysFromRows === 'function') {
        refreshStatusDaysFromRows();
    }
    if (typeof applyFilters === 'function') {
        applyFilters();
    }
}

function escapeOrderHtml(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}


let activeFullNotePopover = null;

function closeFullNotePopover() {
    if (activeFullNotePopover) {
        activeFullNotePopover.remove();
        activeFullNotePopover = null;
    }
}

function showFullNotePopover(event, element) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const encoded = element ? (element.dataset.fullNote || '') : '';
    let note = '';
    try { note = decodeURIComponent(encoded); } catch (_) { note = element?.getAttribute('title') || ''; }
    note = String(note || '').trim();
    if (!note) return;

    closeShippingHistoryPopover();
    closeFullNotePopover();

    const pop = document.createElement('div');
    pop.className = 'full-note-popover';
    pop.innerHTML = `
        <div class="full-note-popover-head">
            <strong>完整備註</strong>
            <button type="button" aria-label="關閉">×</button>
        </div>
        <div class="full-note-popover-body"></div>`;
    pop.querySelector('.full-note-popover-body').textContent = note;
    pop.querySelector('button').addEventListener('click', (e) => {
        e.preventDefault(); e.stopPropagation(); closeFullNotePopover();
    });
    document.body.appendChild(pop);
    activeFullNotePopover = pop;

    const rect = element ? element.getBoundingClientRect() : {left: 20, right: 20, bottom: 40, top: 20};
    const width = Math.min(360, Math.max(260, window.innerWidth - 24));
    pop.style.width = `${width}px`;
    let left = rect.left;
    if (left + width > window.innerWidth - 12) left = window.innerWidth - width - 12;
    left = Math.max(12, left);
    let top = rect.bottom + 6;
    const expectedHeight = Math.min(240, pop.scrollHeight || 160);
    if (top + expectedHeight > window.innerHeight - 12) top = Math.max(12, rect.top - expectedHeight - 6);
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
}

function formatShippingSummaryDate(value) {
    const raw = String(value || '').trim().slice(0, 10);
    const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return raw;
    const year = Number(m[1]), month = Number(m[2]), day = Number(m[3]);
    const nowYear = new Date().getFullYear();
    return year === nowYear ? `${month}/${day}` : `${year}/${month}/${day}`;
}

function shippingStatusLabel(status) {
    const key = normalizeStatusForLogic(status || '');
    if (key === STATUS.PARTIAL_SHIPPED) return '部分出货';
    // 业务上“全部出货”即代表该订单已经完成；主列表只强调实际出货日，
    // 避免与“阶段/状态”栏里的“已完成”重复表达。
    if (key === STATUS.ALL_SHIPPED || key === STATUS.COMPLETED) return '已出货';
    return (typeof displayStatus === 'function') ? displayStatus(key || status) : (status || '');
}

function buildShippingSummaryHtml(order) {
    const dateValue = order && order.last_shipping_date;
    const status = order && order.last_shipping_status;
    const workflowNumber = String((order && (order.workflow_number || order.workflowNumber)) || '');
    if (!dateValue || !status || !workflowNumber) return '';
    const partialCount = Number(order.partial_ship_count || 0);
    const normalized = normalizeStatusForLogic(status);
    // 主列表保持一行高度：多次部分出货只用 ×N 表示，完整日期点开再看。
    const suffix = normalized === STATUS.PARTIAL_SHIPPED && partialCount > 1 ? ` ×${partialCount}` : '';
    const text = `${formatShippingSummaryDate(dateValue)} ${shippingStatusLabel(status)}${suffix}`;
    return `<button type="button" class="shipping-note-summary" onclick="showShippingHistoryPopover(event, '${escapeOrderHtml(workflowNumber)}')" title="点击查看全部出货日期"><span>${escapeOrderHtml(text)}</span></button>`;
}

let activeShippingHistoryPopover = null;

function closeShippingHistoryPopover() {
    if (activeShippingHistoryPopover) {
        activeShippingHistoryPopover.remove();
        activeShippingHistoryPopover = null;
    }
}

function positionShippingHistoryPopover(pop, target) {
    if (!pop) return;
    const rect = target ? target.getBoundingClientRect() : {left: 20, right: 20, bottom: 40, top: 20, width: 0};
    const viewportPadding = 12;
    const gap = 6;
    const popWidth = pop.offsetWidth || 292;
    const popHeight = Math.min(pop.scrollHeight || pop.offsetHeight || 120, 310);

    // Horizontal: keep aligned with the clicked shipping badge while staying in viewport.
    let left = rect.left;
    if (left + popWidth > window.innerWidth - viewportPadding) {
        left = Math.max(viewportPadding, window.innerWidth - popWidth - viewportPadding);
    }
    left = Math.max(viewportPadding, left);

    // Vertical: always prefer below. Only flip above when the real rendered card
    // cannot fit below and there is materially more room above.
    const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - viewportPadding - gap);
    const spaceAbove = Math.max(0, rect.top - viewportPadding - gap);
    let top;
    if (spaceBelow >= popHeight || spaceBelow >= spaceAbove || spaceBelow >= 120) {
        top = rect.bottom + gap;
        pop.style.maxHeight = `${Math.max(90, Math.min(310, spaceBelow || 310))}px`;
    } else {
        top = Math.max(viewportPadding, rect.top - gap - popHeight);
        pop.style.maxHeight = `${Math.max(90, Math.min(310, spaceAbove || 310))}px`;
    }

    pop.style.left = `${Math.round(left)}px`;
    pop.style.top = `${Math.round(top)}px`;
}

async function showShippingHistoryPopover(event, workflowNumber) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    closeShippingHistoryPopover();
    if (!workflowNumber) return;
    const target = event && event.currentTarget;
    const pop = document.createElement('div');
    pop.className = 'shipping-history-popover';
    pop.innerHTML = '<div class="shipping-history-title">出货记录</div><div class="shipping-history-loading">载入中...</div>';
    document.body.appendChild(pop);
    activeShippingHistoryPopover = pop;
    positionShippingHistoryPopover(pop, target);
    try {
        const res = await fetch(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}`);
        const result = await res.json();
        if (!res.ok || !result.success) throw new Error(result.error || '载入失败');
        const rows = (result.data && Array.isArray(result.data.history) ? result.data.history : [])
            .filter(item => {
                const st = normalizeStatusForLogic(item.to_status || '');
                if (![STATUS.PARTIAL_SHIPPED, STATUS.ALL_SHIPPED, STATUS.COMPLETED].includes(st)) return false;
                if (st === STATUS.COMPLETED && String(item.notes || '') === '系統自動：已全部出貨後轉為已完成') return false;
                return true;
            })
            .sort((a,b) => String(a.action_date || '').localeCompare(String(b.action_date || '')) || Number(a.id || 0) - Number(b.id || 0));
        if (!rows.length) {
            pop.innerHTML = '<div class="shipping-history-title">出货记录</div><div class="shipping-history-empty">暂无出货记录</div>';
            positionShippingHistoryPopover(pop, target);
            return;
        }
        pop.innerHTML = `<div class="shipping-history-title">出货记录 <span>${rows.length}</span></div><div class="shipping-history-list">${rows.map((item) => {
            const label = shippingStatusLabel(item.to_status || '');
            const note = String(item.notes || '').trim();
            const rawDate = String(item.action_date || '').slice(0, 10);
            return `<div class="shipping-history-item" data-history-id="${Number(item.id || 0)}" data-action-date="${escapeOrderHtml(rawDate)}">
                <div class="shipping-history-dot"></div>
                <div class="shipping-history-main">
                    <div class="shipping-history-line"><strong>${escapeOrderHtml(formatShippingSummaryDate(item.action_date))}</strong><span>${escapeOrderHtml(label)}</span></div>
                    ${note ? `<small>${escapeOrderHtml(note)}</small>` : ''}
                </div>
                <button type="button" class="shipping-history-edit-btn" onclick="startShippingHistoryDateEdit(event, '${escapeOrderHtml(workflowNumber)}', ${Number(item.id || 0)}, '${escapeOrderHtml(rawDate)}')" title="修改出货日期">修改</button>
            </div>`;
        }).join('')}</div>`;
        positionShippingHistoryPopover(pop, target);
    } catch (err) {
        pop.innerHTML = `<div class="shipping-history-title">出货记录</div><div class="shipping-history-empty">${escapeOrderHtml(err.message || '载入失败')}</div>`;
        positionShippingHistoryPopover(pop, target);
    }
}

function startShippingHistoryDateEdit(event, workflowNumber, historyId, currentDate) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const row = event && event.currentTarget ? event.currentTarget.closest('.shipping-history-item') : null;
    if (!row || row.querySelector('.shipping-history-date-editor')) return;
    const btn = event.currentTarget;
    btn.style.display = 'none';
    const editor = document.createElement('div');
    editor.className = 'shipping-history-date-editor';
    editor.innerHTML = `
        <input type="date" value="${escapeOrderHtml(String(currentDate || '').slice(0, 10))}">
        <button type="button" class="save">保存</button>
        <button type="button" class="cancel">取消</button>`;
    row.appendChild(editor);
    const input = editor.querySelector('input');
    if (input) input.focus();
    editor.querySelector('.cancel').addEventListener('click', (e) => {
        e.stopPropagation();
        editor.remove();
        btn.style.display = '';
    });
    editor.querySelector('.save').addEventListener('click', async (e) => {
        e.stopPropagation();
        const nextDate = input ? input.value : '';
        if (!nextDate) return;
        const saveBtn = e.currentTarget;
        saveBtn.disabled = true;
        try {
            const res = await fetch(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}/history/${historyId}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action_date: nextDate})
            });
            const result = await res.json();
            if (!res.ok || !result.success) throw new Error(result.error || '修改失败');
            const strong = row.querySelector('.shipping-history-line strong');
            if (strong) strong.textContent = formatShippingSummaryDate(result.data.action_date || nextDate);
            row.dataset.actionDate = result.data.action_date || nextDate;
            editor.remove();
            btn.style.display = '';
            if (typeof showToast === 'function') showToast('成功', '出货日期已更新', 'success');
            if (typeof loadHomeOrdersData === 'function') loadHomeOrdersData(true);
            if (window.WorkspaceDrawer && typeof window.WorkspaceDrawer.loadData === 'function' && window.WorkspaceDrawer.state && window.WorkspaceDrawer.state.currentWorkflowNumber === workflowNumber) {
                window.WorkspaceDrawer.loadData(workflowNumber);
            }
        } catch (err) {
            saveBtn.disabled = false;
            if (typeof showToast === 'function') showToast('错误', err.message || '修改失败', 'error');
        }
    });
}

document.addEventListener('click', (event) => {
    if (activeShippingHistoryPopover && !event.target.closest('.shipping-history-popover') && !event.target.closest('.shipping-note-summary')) closeShippingHistoryPopover();
    if (activeFullNotePopover && !event.target.closest('.full-note-popover') && !event.target.closest('.notes-preview')) closeFullNotePopover();
});
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        closeShippingHistoryPopover();
        closeFullNotePopover();
    }
});

/**
 * 创建订单行元素
 */
function createOrderRow(order) {
    // ── 無流程 / 別人有流程：顯示簡化行，點擊開 orderOnly 抽屜，無任何按鈕 ──
    if (order.no_workflow) {
        const tr = document.createElement('tr');
        tr.className = 'no-workflow-row';
        tr.dataset.orderNumber = order.order_number || '';
        tr.dataset.workflowNumber = '';
        tr.dataset.customerName = order.customer_name || '';
        tr.dataset.orderDate = order.order_date || '';
        tr.dataset.handlerId = '';
        tr.dataset.handlerName = '';
        tr.dataset.productionType = '';
        tr.dataset.productCode = '';
        tr.dataset.quantity = '';
        tr.dataset.factory = '';
        tr.dataset.notes = '';
        tr.dataset.status = '';
        tr.dataset.light = '';
        tr.dataset.stageGroup = 'no_workflow';
        tr.dataset.expectedDeliveryDate = '';
        tr.style.cssText = 'opacity:0.65;cursor:pointer;';
        tr.onclick = (event) => {
        const target = event && event.target;
        if (target && (
            target.closest('button') ||
            target.closest('input') ||
            target.closest('textarea') ||
            target.closest('select') ||
            target.closest('a') ||
            target.closest('.order-notes') ||
            target.closest('.notes-edit') ||
            target.closest('.actions-cell') ||
            target.closest('.expand-cell')
        )) return;
        openDetailDrawerFromRow(tr);
    };
        const showAdminCols = homeCanViewUserColumns();

        // 狀態欄文字：無流程 or 別人有 N 個流程
        let stageText;
        const isEsUi = typeof window.getTrackingLanguage === 'function' && window.getTrackingLanguage() === 'es';
        if (order.others_workflow && order.workflow_count > 0) {
            stageText = `<div class="stage-current" style="color:#9ca3af;font-style:italic;">
                ${isEsUi ? `Ya existen ${order.workflow_count} procesos; este pedido no está asignado a ti.` : `已有 ${order.workflow_count} 个流程，你目前不负责该项目`}
            </div>`;
        } else {
            stageText = `<div class="stage-current" style="color:#9ca3af;font-style:italic;">${isEsUi ? 'Sin proceso' : '尚无流程'}</div>`;
        }

        tr.innerHTML = `
            <td class="expand-cell" data-column-key="expand" data-label=""></td>
            <td class="light" data-column-key="light" data-label="燈號"><svg viewBox="0 0 12 12" width="12" height="12"><circle cx="6" cy="6" r="5" fill="#d1d5db" stroke="#9ca3af" stroke-width="1"/></svg></td>
            <td class="order-date" data-column-key="order_date" data-label="訂單日期">${order.order_date || '-'}</td>
            ${showAdminCols ? '<td class="order-age" data-column-key="order_age" data-label="訂單歷時">-</td>' : ''}
            <td class="order-no" data-column-key="order_number" data-label="訂單號" style="color:#6b7280;">${order.order_number}</td>
            <td class="customer" data-column-key="customer_name" data-label="客戶" title="${(order.customer_name || '').replace(/"/g, '&quot;')}">${order.customer_name || '-'}</td>
            <td data-column-key="production_type" data-label="產品類型">-</td><td data-column-key="product_code" data-label="產品編號">-</td><td data-column-key="quantity" data-label="數量">-</td><td data-column-key="factory" data-label="工廠">-</td>
            <td class="stage-cell" data-column-key="current_status" data-label="階段 / 狀態">${stageText}</td>
            <td data-column-key="status_days" data-label="階段歷時"><span class="days">-</span></td>
            <td data-column-key="expected_delivery_date" data-label="交期">-</td>
            <td class="order-notes" data-column-key="notes" data-label="備註"><span class="notes-empty">-</span></td>
            ${showAdminCols ? '<td class="handler-name" data-column-key="handler_name" data-label="業務員">-</td>' : ''}
            <td class="actions-cell" data-column-key="actions" data-label="操作"></td>
        `;
        return tr;
    }

    const tr = document.createElement('tr');
    tr.className = order.status_light;
    tr.dataset.orderNumber = order.order_number;
    tr.dataset.workflowNumber = order.workflow_number || order.workflowNumber || '';
    tr.dataset.customerName = order.customer_name;
    tr.dataset.orderDate = order.order_date || '';
    tr.dataset.handlerId = order.handler_id || order.handlerId || '';
    tr.dataset.productionType = order.production_type || order.productionType || '';
    tr.dataset.productCode = order.product_code || order.productCode || '';
    tr.dataset.factory = order.factory || '';
    tr.dataset.handlerName = order.handler_name || order.handlerName || '';
    tr.dataset.notes = order.notes || '';
    tr.dataset.status = order.current_status;
    tr.dataset.light = order.status_light;
    tr.dataset.statusUpdatedAt = order.status_updated_at || order.last_status_change_date || '';
    tr.dataset.lastStatusChangeDate = order.last_status_change_date || order.status_updated_at || '';
    tr.dataset.historyId = order.last_history_id || '';
    tr.dataset.lastShippingDate = order.last_shipping_date || '';
    tr.dataset.lastShippingStatus = order.last_shipping_status || '';
    tr.dataset.partialShipCount = Number(order.partial_ship_count || 0);
    tr.onclick = (event) => {
        const target = event && event.target;
        if (target && (
            target.closest('button') ||
            target.closest('input') ||
            target.closest('textarea') ||
            target.closest('select') ||
            target.closest('a') ||
            target.closest('.order-notes') ||
            target.closest('.notes-edit') ||
            target.closest('.actions-cell') ||
            target.closest('.expand-cell')
        )) return;
        openDetailDrawerFromRow(tr);
    };
    
    // 使用STATUS_SYSTEM确定stage-group
    const stageGroup = getStageGroup(order.current_status);
    tr.dataset.stageGroup = stageGroup;
    tr.dataset.isLocked = (order.is_locked === 1 || order.is_locked === true || String(order.is_locked) === '1') ? '1' : '0';
    tr.dataset.orderStatus = order.order_status || '';
    
    // 灯号图标
    let lightType = 'green';
    if (order.status_light === 'red') lightType = 'red';
    else if (order.status_light === 'yellow') lightType = 'yellow';
    else if (typeof STATUS !== 'undefined' && order.current_status === STATUS.CANCELLED) lightType = 'none';
    else if (typeof STATUS !== 'undefined' && order.current_status === STATUS.COMPLETED) lightType = 'none';

    if (typeof STATUS !== 'undefined' && (order.current_status === STATUS.CANCELLED || order.current_status === STATUS.COMPLETED)) {
        tr.dataset.light = '';
    }
    
    const workflowNumber = order.workflow_number || order.workflowNumber || '';
    const orderNumber = order.order_number || order.orderNumber || '';
    // 订单号前缀
    const displayNumber = workflowNumber || orderNumber;
    const orderNumberDisplay = displayNumber;
    
    // 阶段显示
    const stageCurrentText = typeof displayStatus === 'function'
        ? displayStatus(order.current_status)
        : (order.current_status || '-');
    
    // 等待天数显示和样式
    let daysClass = '';
    let daysDisplay = '';
    const statusDays = getOrderWaitingDays(order);
    
    const uiIsEs = typeof window.getTrackingLanguage === 'function' && window.getTrackingLanguage() === 'es';
    const normalDaysText = `${statusDays} ${uiIsEs ? (Math.abs(statusDays) === 1 ? 'día' : 'días') : '天'}`;
    const overdueDaysText = uiIsEs
        ? `Atrasado ${Math.abs(statusDays)} ${Math.abs(statusDays) === 1 ? 'día' : 'días'}`
        : `已超时 ${Math.abs(statusDays)} 天`;
    if (order.status_light === 'red') {
        daysClass = ' danger';
        daysDisplay = statusDays < 0 ? overdueDaysText : normalDaysText;
    } else if (order.status_light === 'yellow') {
        daysClass = ' warning';
        daysDisplay = statusDays < 0 ? overdueDaysText : normalDaysText;
    } else {
        if (statusDays < 0) {
            daysDisplay = overdueDaysText;
            daysClass = ' warning';
        } else {
            daysDisplay = normalDaysText;
        }
    }
    
    const notesText = order.notes || '';
    const notesDisplay = notesText.length > 30 ? `${notesText.slice(0, 30)}...` : notesText;
    const notesEscaped = notesText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const notesDisplayEscaped = notesDisplay.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const shippingSummaryHtml = buildShippingSummaryHtml(order);
    const isLocked = order.is_locked === 1 || order.is_locked === true || String(order.is_locked) === '1';
    const currentUserId = document.body ? (document.body.dataset.userId || '') : '';
    const handlerId = order.handler_id || order.handlerId || '';
    const isOwner = currentUserId && handlerId && String(handlerId) === String(currentUserId);
    const isAdminUser = typeof isAdminRole === 'function' && isAdminRole();
    const permissionFromServer = order.can_edit_notes;
    const canInlineEditNotes = !isCloudReadOnly() && permissionFromServer === true;

    const currentStatusText = typeof displayStatus === 'function'
        ? displayStatus(order.current_status)
        : (order.current_status || '-');

    const displayProductionType = order.production_type || order.product_name || '-';
    tr.dataset.productionType = order.production_type || order.product_name || '';
    tr.dataset.productCode = order.product_code || '';
    tr.dataset.quantity = order.quantity || '';
    tr.dataset.factory = order.factory || '';
    tr.dataset.expectedDeliveryDate = order.expected_delivery_date || '';
    const showAdminColumns = homeCanViewUserColumns();
    tr.innerHTML = `
        <td class="expand-cell" data-column-key="expand" data-label="">
            <span class="expand-btn" id="expand-${displayNumber}" onclick="toggleDetail('${displayNumber}', event); event.stopPropagation();">▶</span>
        </td>
        <td class="light" data-column-key="light" data-label="燈號">${lightType === 'none' ? '' : getStatusLightIcon(lightType)}</td>
        <td class="order-date" data-column-key="order_date" data-label="訂單日期">${order.order_date || '-'}</td>
        ${showAdminColumns ? '<td class="order-age" data-column-key="order_age" data-order-age="" data-label="訂單歷時">-</td>' : ''}
        <td class="order-no" data-column-key="order_number" data-label="訂單號">${orderNumberDisplay}</td>
        <td class="customer" data-column-key="customer_name" data-label="客戶" title="${(order.customer_name || '').replace(/"/g, '&quot;')}">${order.customer_name || '-'}</td>
        <td class="production-type" data-column-key="production_type" data-label="產品類型">${displayProductionType}</td>
        <td class="product-code" data-column-key="product_code" data-label="產品編號">${order.product_code || '-'}</td>
        <td class="quantity" data-column-key="quantity" data-label="數量">${order.quantity || '-'}</td>
        <td class="factory" data-column-key="factory" data-label="工廠">${order.factory || '-'}</td>
        <td class="stage-cell" data-column-key="current_status" data-label="階段 / 狀態">
            <div class="stage-current" data-status-key="${order.current_status}">
                ${stageCurrentText}
            </div>
        </td>
        <td class="status-days-col" data-column-key="status_days" data-label="階段歷時">
            ${order.current_status === STATUS.COMPLETED || order.current_status === STATUS.CANCELLED
                ? '<span class="days">-</span>'
                : `<span class="days${daysClass}">${daysDisplay}</span>`}
        </td>
        <td class="expected-delivery-date" data-column-key="expected_delivery_date" data-label="交期">${order.expected_delivery_date || '-'}</td>
        <td class="order-notes" data-column-key="notes" data-label="備註" data-order-number="${orderNumber}" data-workflow-number="${workflowNumber}">
            <div class="notes-container">
                ${canInlineEditNotes
                    ? `<button class="notes-edit-btn" id="notes-edit-btn-${workflowNumber}" onclick="toggleNotesEdit('${workflowNumber}', this); event.stopPropagation();" title="编辑备注">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                    </button>`
                    : ''}
                <div class="notes-content-stack">
                    <div class="notes-view-row">
                        ${shippingSummaryHtml}
                        <div class="notes-display">
                            ${notesText ? `<span class="notes-preview" title="${notesEscaped}" data-full-note="${encodeURIComponent(notesText)}" onclick="showFullNotePopover(event, this)">${notesDisplayEscaped}</span>` : '<span class="notes-empty">-</span>'}
                        </div>
                    </div>
                    <div class="notes-edit" style="display: none;">
                        <textarea class="notes-input" rows="2" placeholder="输入备注...">${notesText}</textarea>
                        <div class="notes-edit-actions">
                            <button class="notes-save-btn" onclick="saveNotes('${workflowNumber}', this); event.stopPropagation();">保存</button>
                            <button class="notes-cancel-btn" onclick="cancelNotesEdit('${workflowNumber}', this); event.stopPropagation();">取消</button>
                        </div>
                    </div>
                </div>
            </div>
        </td>
        ${showAdminColumns ? `<td class="handler-name" data-column-key="handler_name" data-label="業務員">${order.handler_name || '-'}</td>` : ''}
        <td class="actions-cell" data-column-key="actions" data-label="操作" data-order-number="${orderNumber}" data-workflow-number="${workflowNumber}" data-current-status="${order.current_status}" data-history-id="${order.last_history_id || ''}">
            <div class="actions-container">
                <div class="quick-actions"></div>
            </div>
        </td>
    `;
    
    return tr;
}

/**
 * 業務員自動同步：移除已不屬於自己的流程列
 */
async function pruneSalesRowsFromServer() {
    if (salesAutoSyncRunning || isGlobalSearchMode) return;
    if (document.hidden) return;

    if (homeDataReady) {
        salesAutoSyncRunning = true;
        try { await loadHomeOrdersData(true); } finally { salesAutoSyncRunning = false; }
        return;
    }

    const tbody = document.getElementById('ordersTableBody');
    if (!tbody) return;

    salesAutoSyncRunning = true;
    try {
        const response = await fetch('/tracking/api/orders?page=1&page_size=500');
        const result = await response.json();
        if (!response.ok || !result.success) {
            return;
        }

        const dataList = result.data || [];
        const serverWorkflows = new Set(dataList.map(item => item.workflow_number || item.workflowNumber));
        const serverOrders = new Set(dataList.map(item => item.order_number || item.orderNumber));
        const totalCount = result.total || dataList.length;
        const isPaginated = totalCount > dataList.length;
        const rows = Array.from(document.querySelectorAll('#ordersTableBody tr[data-workflow-number]'));
        const existingWorkflows = new Set(rows.map(row => row.dataset.workflowNumber || row.dataset.orderNumber || ''));
        let removedAny = false;
        let addedAny = false;

        rows.forEach(row => {
            const wf = row.dataset.workflowNumber || '';
            const orderNo = row.dataset.orderNumber || '';
            const statusRaw = row.dataset.status || '';
            const status = normalizeStatusForLogic(statusRaw);
            const isCompleted = status === STATUS.COMPLETED;
            const isCancelled = status === STATUS.CANCELLED;

            if (isCompleted || isCancelled) {
                return;
            }

            const isMissing = (wf && !serverWorkflows.has(wf)) || (orderNo && !serverOrders.has(orderNo));
            if (isMissing) {
                const detailRow = document.querySelector(`tr.detail-row[data-detail-for="${orderNo || wf}"]`);
                row.remove();
                if (detailRow) detailRow.remove();
                removedAny = true;
            }
        });

        dataList.forEach(item => {
            const wf = item.workflow_number || item.workflowNumber || '';
            const orderNo = item.order_number || item.orderNumber || '';
            const key = wf || orderNo;
            if (!key || existingWorkflows.has(key)) return;
            const newRow = createOrderRow(item);
            tbody.prepend(newRow);
            addedAny = true;
        });

        if (removedAny || addedAny) {
            applyColumnSettings();
            applyFilters();
            if (typeof updateFilterCounts === 'function') {
                updateFilterCounts();
            }
        }

        if (typeof WorkspaceDrawer !== 'undefined' && WorkspaceDrawer.state && WorkspaceDrawer.state.currentWorkflowNumber) {
            const currentWf = WorkspaceDrawer.state.currentWorkflowNumber;
            if (currentWf && !serverWorkflows.has(currentWf)) {
                const currentStatusRaw = WorkspaceDrawer.state.currentStatus || '';
                const currentStatus = normalizeStatusForLogic(currentStatusRaw);
                const isCompleted = currentStatus === STATUS.COMPLETED;
                const isCancelled = currentStatus === STATUS.CANCELLED;
                if (isCompleted || isCancelled) {
                    WorkspaceDrawer.close();
                    return;
                }
                if (isPaginated) {
                    return;
                }
                if (typeof showToast === 'function') {
                    showToast('提示', '该流程已转移给其他业务员', 'info');
                }
                WorkspaceDrawer.close();
            }
        }
    } catch (error) {
        console.warn('[salesAutoSync] 同步失败:', error);
    } finally {
        salesAutoSyncRunning = false;
    }
}

function requestSalesAutoSync() {
    const now = Date.now();
    // visibilitychange + focus often fire back-to-back.
    if (now - salesAutoSyncLastRequestedAt < 4000) return;
    salesAutoSyncLastRequestedAt = now;
    pruneSalesRowsFromServer();
}

function startSalesAutoSync() {
    if (!homeDataReady) { setTimeout(startSalesAutoSync, 1200); return; }
    const isSales = typeof appPerm.isSales === 'function'
        ? appPerm.isSales()
        : (appPerm.can ? appPerm.can('edit', 'workflow') : false);
    if (!isSales) return;
    if (salesAutoSyncTimer) return;
    salesAutoSyncTimer = setInterval(requestSalesAutoSync, 30000);
    requestSalesAutoSync();
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) requestSalesAutoSync();
    });
    window.addEventListener('focus', requestSalesAutoSync);
}

function updateWorkflowHandlerInRow(workflowNumber, handlerName) {
    if (!workflowNumber) return;
    const row = document.querySelector(`tr[data-workflow-number="${workflowNumber}"]`) ||
        document.querySelector(`tr[data-order-number="${workflowNumber}"]`);
    if (!row) return;
    const handlerCell = row.querySelector('.handler-name');
    if (handlerCell) {
        handlerCell.textContent = handlerName || '-';
    }
    if (handlerName) {
        row.dataset.handlerName = handlerName;
    }
}

/**
 * 清除全局搜索，返回原始列表
 */
function clearGlobalSearch() {
    if (!isGlobalSearchMode) return;
    const searchInput = document.getElementById('searchInput');
    if (searchInput) searchInput.value = '';
    selectedCustomerNameFilter = '';
    selectedOrderNumberFilter = '';
    currentFilter.search = '';
    isGlobalSearchMode = false;
    originalOrders = null;
    if (homeDataReady) applyFilters();
    showToast('已返回', '返回首页订单列表');
}

// 获取session role（用于渲染操作列）
var appPerm = window.AppPermissions || window.appPerm || {};
const isCloudMode = () => document.body && document.body.dataset.cloudMode === 'true';
const isCloudReadOnly = () => document.body && document.body.dataset.cloudReadOnly === 'true';
let cloudProviderReady = document.body ? document.body.dataset.cloudProviderReady === 'true' : true;
window.isCloudMode = isCloudMode;
window.isCloudReadOnly = isCloudReadOnly;
const canEditWorkflow = !isCloudReadOnly() && (appPerm.can ? appPerm.can('edit', 'workflow') : false);
var isAdminRole = window.isAdminRole || (() => (typeof appPerm.isAdmin === 'function'
    ? appPerm.isAdmin()
    : (appPerm.can ? appPerm.can('view', 'user') : false)));
window.isAdminRole = isAdminRole;


// ==================== 动态悬停按钮管理 ====================

/**
 * 为订单行动态生成悬停按钮
 */
function showQuickActionsForRow(row, currentStatus) {
    const actionsCell = row.querySelector('.actions-cell');
    if (!actionsCell) return;
    
    if (!canEditWorkflow) {
        const quickActions = actionsCell.querySelector('.quick-actions');
        if (quickActions) {
            quickActions.innerHTML = '';
        }
        return;
    }
    
    // 获取当前状态（如果没有提供，从 data 属性获取）
    if (!currentStatus) {
        currentStatus = row.dataset.status || actionsCell.dataset.currentStatus || '';
    }
    const statusForLogic = typeof normalizeStatusForLogic === 'function'
        ? normalizeStatusForLogic(currentStatus)
        : currentStatus;
    
    // 获取 workflow_number（优先）或 order_number（向后兼容）
    const workflowNumber = row.dataset.workflowNumber || actionsCell.dataset.workflowNumber || '';
    const orderNumber = row.dataset.orderNumber || actionsCell.dataset.orderNumber || '';
    
    // 特殊情况：已完成、已取消不显示悬停按钮
    // 訂單被鎖定（已完成或已取消）時也不顯示
    const rowIsLocked = row.dataset.isLocked === '1';
    const rowOrderStatus = row.dataset.orderStatus || '';
    if (!statusForLogic || 
        statusForLogic === STATUS.COMPLETED || 
        statusForLogic === STATUS.CANCELLED ||
        rowIsLocked) {
        const quickActions = actionsCell.querySelector('.quick-actions');
        if (quickActions) {
            quickActions.innerHTML = '';
        }
        return;
    }
    
    // 从 STATUS_SYSTEM.js 获取快捷操作
    if (typeof getQuickActions !== 'function') {
        console.error('getQuickActions function not found. Make sure STATUS_SYSTEM.js is loaded.');
        return;
    }
    
    const actions = getQuickActions(statusForLogic);
    if (!actions || actions.length === 0) {
        console.warn(`No quick actions found for status: ${statusForLogic}`);
        const quickActions = actionsCell.querySelector('.quick-actions');
        if (quickActions) {
            quickActions.innerHTML = '';
        }
        return;
    }
    
    // 生成按钮HTML
    let buttonsHTML = '';
    actions.forEach(action => {
        // 优先使用 workflow_number，如果没有则使用 order_number（向后兼容）
        const identifier = workflowNumber || orderNumber;
        // 转义标识符和状态，避免XSS
        const safeIdentifier = String(identifier).replace(/'/g, "\\'");
        const safeWorkflowNumber = workflowNumber ? String(workflowNumber).replace(/'/g, "\\'") : '';
        const safeOrderNumber = orderNumber ? String(orderNumber).replace(/'/g, "\\'") : '';
        const safeAction = String(action.action).replace(/'/g, "\\'");
        const safeCurrentStatus = String(currentStatus).replace(/'/g, "\\'");
        const safeNextStatus = String(action.next || '').replace(/'/g, "\\'");
        
        buttonsHTML += `
            <button 
                class="quick-btn quick-btn-${action.color || 'confirm'}" 
                onclick="handleQuickAction('${safeIdentifier}', '${safeAction}', '${safeCurrentStatus}', '${safeNextStatus}', event)"
                data-workflow-number="${safeWorkflowNumber}"
                data-order-number="${safeOrderNumber}"
            >
                ${action.label || '操作'}
            </button>
        `;
    });
    
    // 更新按钮容器（保留详情按钮）
    const quickActions = actionsCell.querySelector('.quick-actions');
    if (quickActions) {
        quickActions.innerHTML = buttonsHTML;
    } else {
        // 如果没有容器，创建新的
        const actionsContainer = actionsCell.querySelector('.actions-container');
        if (actionsContainer) {
            const newQuickActions = document.createElement('div');
            newQuickActions.className = 'quick-actions';
            newQuickActions.innerHTML = buttonsHTML;
            actionsContainer.insertBefore(newQuickActions, actionsContainer.firstChild);
        }
    }
}

/**
 * 为所有订单行初始化悬停按钮
 */
function initQuickActionsForAllRows() {
    if (!canEditWorkflow) {
        const quickActions = document.querySelectorAll('.quick-actions');
        quickActions.forEach(container => {
            container.innerHTML = '';
        });
        return;
    }
    const allRows = document.querySelectorAll('#ordersTableBody tr[data-order-number]');
    allRows.forEach(row => {
        const currentStatus = row.dataset.status || '';
        if (currentStatus) {
            showQuickActionsForRow(row, currentStatus);
        }
        bindAdminHandlerVisibility(row);
    });
}

function bindAdminHandlerVisibility(row) {
    if (!isAdminRole()) return;
    if (!row || row.dataset.handlerHoverBound === 'true') return;
    const handlerCell = row.querySelector('.handler-name');
    if (!handlerCell) return;
    row.dataset.handlerHoverBound = 'true';
    row.addEventListener('mouseenter', () => {
        handlerCell.style.opacity = '1';
        handlerCell.style.pointerEvents = 'auto';
    });
    row.addEventListener('mouseleave', () => {
        handlerCell.style.opacity = '';
        handlerCell.style.pointerEvents = '';
    });
}

// 存储当前快速操作的数据
let currentQuickAction = null;

// 出货相关动作需要记录实际发生日期；其他状态仍沿用系统当天。
const SHIPPING_ACTION_KEYS = new Set(['ship_partial', 'ship_all', 'shipping_complete']);
const SHIPPING_STATUS_KEYS = new Set(['PARTIAL_SHIPPED', 'ALL_SHIPPED', 'COMPLETED']);
let shippingActionResolver = null;

function isShippingAction(action) {
    return SHIPPING_ACTION_KEYS.has(String(action || ''));
}

function isShippingStatus(status) {
    return SHIPPING_STATUS_KEYS.has(String(status || ''));
}

function getTomorrowDate() {
    const now = new Date();
    now.setDate(now.getDate() + 1);
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function requestShippingActionDetails(options = {}) {
    const modal = document.getElementById('shippingActionModal');
    const dateInput = document.getElementById('shippingActionDate');
    const notesInput = document.getElementById('shippingActionNotes');
    if (!modal || !dateInput || !notesInput) {
        return Promise.resolve({ date: getTodayDate(), notes: '' });
    }

    // If another request somehow remains open, cancel it cleanly first.
    if (shippingActionResolver) {
        shippingActionResolver(null);
        shippingActionResolver = null;
    }

    const orderEl = document.getElementById('shippingActionOrderNumber');
    const currentEl = document.getElementById('shippingActionCurrentStatus');
    const nextEl = document.getElementById('shippingActionNextStatus');
    const titleEl = document.getElementById('shippingActionTitle');

    const action = String(options.action || '');
    const titles = {
        ship_partial: '记录部分出货',
        ship_all: '记录全部出货',
        shipping_complete: '确认出货完成'
    };
    if (titleEl) titleEl.textContent = titles[action] || '记录出货日期';
    if (orderEl) orderEl.textContent = options.orderNumber ? `#${options.orderNumber}` : '-';
    if (currentEl) currentEl.textContent = displayStatus(options.currentStatus || '');
    if (nextEl) nextEl.textContent = displayStatus(options.nextStatus || '');

    dateInput.value = getTodayDate();
    dateInput.max = getTomorrowDate();
    notesInput.value = options.notes || '';
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');

    setTimeout(() => dateInput.focus(), 50);

    return new Promise(resolve => {
        shippingActionResolver = resolve;
    });
}

function closeShippingActionModal(result = null) {
    const modal = document.getElementById('shippingActionModal');
    if (modal) {
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
    }
    const resolver = shippingActionResolver;
    shippingActionResolver = null;
    if (resolver) resolver(result);
}

function confirmShippingActionModal() {
    const dateInput = document.getElementById('shippingActionDate');
    const notesInput = document.getElementById('shippingActionNotes');
    const selectedDate = dateInput ? dateInput.value : '';
    if (!selectedDate) {
        if (typeof showToast === 'function') showToast('提示', '请选择实际出货日期', 'error');
        if (dateInput) dateInput.focus();
        return;
    }
    if (selectedDate > getTomorrowDate()) {
        if (typeof showToast === 'function') showToast('日期错误', '出货日期不能晚于明天', 'error');
        return;
    }
    closeShippingActionModal({
        date: selectedDate,
        notes: notesInput ? notesInput.value.trim() : ''
    });
}

/**
 * 处理快捷按钮点击
 */
async function handleQuickAction(orderNumber, action, currentStatus, nextStatus, event) {
    event.stopPropagation();

    // 从按钮获取 workflow_number（优先）或 order_number
    const button = event.currentTarget || event.target;
    const workflowNumber = button.dataset.workflowNumber ||
                          button.closest('.actions-cell')?.dataset.workflowNumber ||
                          button.closest('tr')?.dataset.workflowNumber || '';
    const finalIdentifier = workflowNumber || orderNumber;
    const row = button.closest('tr[data-order-number]') || button.closest('tr[data-workflow-number]');
    const expectedHistoryId = row ? row.dataset.historyId || '' : '';

    // 出货动作不使用“日期自动今天”的普通确认框，直接要求选择实际出货日。
    if (isShippingAction(action)) {
        const details = await requestShippingActionDetails({
            action,
            orderNumber: finalIdentifier,
            currentStatus,
            nextStatus
        });
        if (!details) return;

        const originalText = button ? button.textContent : '';
        if (button) {
            button.disabled = true;
            button.style.opacity = '0.5';
            button.textContent = '处理中...';
        }
        performQuickUpdate(
            finalIdentifier,
            action,
            currentStatus,
            nextStatus,
            details.date,
            details.notes,
            expectedHistoryId,
            button,
            originalText
        );
        return;
    }

    // 非出货动作维持原本快速确认流程。
    currentQuickAction = {
        orderNumber: finalIdentifier,
        workflowNumber: workflowNumber,
        action,
        currentStatus,
        nextStatus,
        button: button,
        expectedHistoryId
    };
    showQuickActionModal(finalIdentifier, currentStatus, nextStatus);
}

/**
 * 显示快速操作 Modal
 */
function showQuickActionModal(orderNumber, currentStatus, nextStatus) {
    const modal = document.getElementById('quickActionModal');
    const title = document.getElementById('quickActionTitle');
    const currentStatusEl = document.getElementById('quickActionCurrentStatus');
    const nextStatusEl = document.getElementById('quickActionNextStatus');
    const orderNumberEl = document.getElementById('quickActionOrderNumber');
    const dateEl = document.getElementById('quickActionDate');
    const noteEl = document.getElementById('quickActionNote');
    
    if (!modal) return;
    
    // 设置内容
    if (title) title.textContent = '確認操作';
    if (currentStatusEl) currentStatusEl.textContent = displayStatus(currentStatus);
    if (nextStatusEl) nextStatusEl.textContent = displayStatus(nextStatus);
    if (orderNumberEl) orderNumberEl.textContent = `#${orderNumber}`;
    
    // 设置日期（今天）
    const today = getTodayDate();
    if (dateEl) dateEl.textContent = today;
    
    // 清空备注
    if (noteEl) noteEl.value = '';
    
    // 显示 Modal
    modal.classList.add('show');
    
    // 聚焦到备注框
    setTimeout(() => {
        if (noteEl) noteEl.focus();
    }, 100);
}

/**
 * 关闭快速操作 Modal
 */
function closeQuickActionModal() {
    const modal = document.getElementById('quickActionModal');
    if (modal) {
        modal.classList.remove('show');
    }
    // 恢复按钮状态（如果用户取消）
    if (currentQuickAction && currentQuickAction.button) {
        const button = currentQuickAction.button;
        // 检查按钮是否还在处理中（如果用户还没确认就关闭）
        if (button.disabled && button.textContent === '处理中...') {
            button.disabled = false;
            button.style.opacity = '1';
            // 恢复原始文本（需要从按钮的data属性或重新获取）
            const actions = getQuickActions(currentQuickAction.currentStatus);
            const action = actions.find(a => a.action === currentQuickAction.action);
            if (action) {
                button.textContent = action.label;
            }
        }
    }
    currentQuickAction = null;
}

// ==================== 统一 ESC 键处理（按 z-index 从高到低依次关闭最上层 Modal）====================
// showConfirmModal / showAlertModal / showPromptModal 有各自内部的 ESC 处理器并自行清理，
// 此全局处理器覆盖其他没有内建 ESC 处理的 Modal。
document.addEventListener('keydown', function(event) {
    if (event.key !== 'Escape') return;

    // 按优先级从高到低检查（z-index 越大越先关闭）
    // confirmModal/alertModal/promptModal 由各自的 Promise 内部 handleEsc 处理，这里跳过
    const confirmModal = document.getElementById('confirmModal');
    const alertModal = document.getElementById('alertModal');
    const promptModal = document.getElementById('promptModal');
    if ((confirmModal && confirmModal.classList.contains('show')) ||
        (alertModal && alertModal.classList.contains('show')) ||
        (promptModal && promptModal.classList.contains('show'))) {
        return; // 由内部 handleEsc 处理，不要重复关闭
    }

    // 通知面板
    if (typeof closeNotificationPanel === 'function') {
        const notifPanel = document.getElementById('notificationPanel');
        if (notifPanel && notifPanel.classList.contains('show')) {
            closeNotificationPanel();
            return;
        }
    }

    // 设置面板 — 如果焦点在表单输入框内，ESC 只移除焦点不关闭 Modal
    const settingsModal = document.getElementById('settingsModal');
    if (settingsModal && settingsModal.classList.contains('show')) {
        const active = document.activeElement;
        if (active && settingsModal.contains(active) &&
            (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) {
            active.blur();          // ESC 第一次 → 只退出输入框
            event.preventDefault(); // 阻止浏览器默认行为
            return;
        }
        closeSettingsModal();
        return;
    }

    // shippingActionModal（Promise 型弹窗必须通过专用关闭函数结束）
    const shippingActionModal = document.getElementById('shippingActionModal');
    if (shippingActionModal && shippingActionModal.classList.contains('show')) {
        closeShippingActionModal(null);
        return;
    }

    // quickActionModal
    const quickActionModal = document.getElementById('quickActionModal');
    if (quickActionModal && quickActionModal.classList.contains('show')) {
        closeQuickActionModal();
        return;
    }

    // newOrderModal（建立业务流程）— 输入中 ESC 先退出焦点
    const newOrderModal = document.getElementById('newOrderModal');
    if (newOrderModal && newOrderModal.classList.contains('show')) {
        const active = document.activeElement;
        if (active && newOrderModal.contains(active) &&
            (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) {
            active.blur();
            event.preventDefault();
            return;
        }
        if (typeof closeNewWorkflowModal === 'function') closeNewWorkflowModal(true);
        return;
    }

    // 其他通用 modal-overlay（旧版 detailsModal 系列等）
    const allOverlays = document.querySelectorAll('.modal-overlay.show');
    if (allOverlays.length > 0) {
        // 关闭最后一个（DOM 顺序最后 = 通常在最上面）
        allOverlays[allOverlays.length - 1].classList.remove('show');
        return;
    }
});

/**
 * 确认快速操作
 */
function confirmQuickAction() {
    if (!currentQuickAction) return;
    
    const noteEl = document.getElementById('quickActionNote');
    const notes = noteEl ? noteEl.value.trim() : '';
    const today = getTodayDate();
    
    const { orderNumber, workflowNumber, action, currentStatus, nextStatus, button, expectedHistoryId } = currentQuickAction;
    // 优先使用 workflowNumber
    const identifier = workflowNumber || orderNumber;
    
    // 关闭 Modal
    closeQuickActionModal();
    
    // 立即禁用按钮，防止重复点击
    if (button) {
        const originalText = button.textContent;
        button.disabled = true;
        button.style.opacity = '0.5';
        button.textContent = '处理中...';
        
        // 执行更新
        performQuickUpdate(identifier, action, currentStatus, nextStatus, today, notes, expectedHistoryId || '', button, originalText);
    } else {
        // 如果没有按钮引用，直接执行
        performQuickUpdate(identifier, action, currentStatus, nextStatus, today, notes, expectedHistoryId || '');
    }
}

/**
 * 统一的订单行更新函数
 */
function updateOrderRowAfterUpdate(orderNumber, orderData) {
    const row = document.querySelector(`tr[data-order-number="${orderNumber}"]`) ||
                document.querySelector(`tr[data-workflow-number="${orderNumber}"]`);
    if (!row) return;
    
    row.dataset.status = orderData.current_status;
    row.dataset.light = orderData.status_light;
    row.dataset.statusUpdatedAt = orderData.status_updated_at || orderData.last_status_change_date || '';
    row.dataset.lastStatusChangeDate = orderData.last_status_change_date || orderData.status_updated_at || '';
    row.dataset.stageGroup = getStageGroup(orderData.current_status);
    row.className = orderData.status_light;
    row.dataset.expectedDeliveryDate = orderData.expected_delivery_date || '';

    const latestHistoryId = orderData.latest_history_id
        || orderData.last_history_id
        || (orderData.history && orderData.history.length ? orderData.history[orderData.history.length - 1].id : '');
    if (latestHistoryId) {
        row.dataset.historyId = latestHistoryId;
        const actionsCell = row.querySelector('.actions-cell');
        if (actionsCell) {
            actionsCell.dataset.historyId = latestHistoryId;
        }
    }
    
    const lightCell = row.querySelector('.light');
    if (lightCell) {
        let lightType = 'green';
        if (orderData.status_light === 'red') lightType = 'red';
        else if (orderData.status_light === 'yellow') lightType = 'yellow';
        else if (orderData.current_status === STATUS.CANCELLED || orderData.current_status === STATUS.COMPLETED) lightType = 'none';
        lightCell.innerHTML = lightType === 'none' ? '' : getStatusLightIcon(lightType);
    }
    
    const stageCurrent = row.querySelector('.stage-current');
    if (stageCurrent) {
        stageCurrent.textContent = displayStatus(orderData.current_status);
    }
    
    const daysSpan = row.querySelector('.days');
    if (daysSpan) {
        if (orderData.current_status === STATUS.COMPLETED || orderData.current_status === STATUS.CANCELLED) {
            daysSpan.textContent = '-';
            daysSpan.className = 'days';
        } else {
            const statusDays = getOrderWaitingDays(orderData);
            daysSpan.textContent = `${statusDays}天`;
        daysSpan.className = 'days';
        if (orderData.status_light === 'red') daysSpan.className += ' danger';
        else if (orderData.status_light === 'yellow') daysSpan.className += ' warning';
        }
    }

    const deliveryCell = row.querySelector('.expected-delivery-date');
    if (deliveryCell) {
        deliveryCell.textContent = orderData.expected_delivery_date || '-';
    }
    
    showQuickActionsForRow(row, orderData.current_status);
    
    if (typeof applyFilters === 'function') {
        applyFilters();
    }
    
    // 高亮显示订单行
    setTimeout(() => {
        if (typeof highlightOrderRow === 'function') {
            highlightOrderRow(orderNumber);
        }
    }, 200);
}

// ==================== 表格排序功能 ====================

let currentSort = {
    column: null,
    direction: 'asc'  // 'asc' 或 'desc'
};

/**
 * 更新「今天-訂單日期」欄位（僅管理員）
 * 使用本地日期計算，與後端 date.today() 保持一致
 */
function updateOrderAgeColumn() {
    if (!isAdminRole()) return;
    const rows = document.querySelectorAll('#ordersTableBody tr[data-order-number]');
    const todayLocal = (typeof getTodayLocal === 'function') ? getTodayLocal() : new Date();
    rows.forEach(row => {
        const dateStr = row.dataset.orderDate || '';
        const cell = row.querySelector('.order-age');
        if (!cell) return;
        const orderDateLocal = (typeof parseLocalDate === 'function') ? parseLocalDate(dateStr) : (dateStr ? new Date(dateStr) : null);
        if (!orderDateLocal || Number.isNaN(orderDateLocal.getTime())) {
            row.dataset.orderAge = '';
            cell.textContent = '-';
            return;
        }
        // 使用本地日期計算，與後端 Python date.today() 保持一致
        const diffMs = todayLocal - orderDateLocal;
        const diffDays = Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)));
        row.dataset.orderAge = String(diffDays);
        cell.textContent = `${diffDays}天`;
    });
}

/**
 * 初始化表格排序功能
 */
function initTableSorting() {
    const sortableHeaders = document.querySelectorAll('th.sortable');
    sortableHeaders.forEach(header => {
        header.style.cursor = 'pointer';
        header.style.userSelect = 'none';
        header.addEventListener('click', function(e) {
            e.stopPropagation(); // 阻止事件冒泡到行点击
            const column = this.dataset.sort;
            toggleSort(column, this);
        });
    });
}

/**
 * 切换排序
 */
function toggleSort(column, headerElement) {
    // Clicking a table header switches back to the classic single-column sort.
    if (Array.isArray(homeMultiSortRules) && homeMultiSortRules.length) {
        homeMultiSortRules = [];
        saveHomeMultiSortRules();
        syncHomeMultiSortControls();
    }
    // 如果点击的是当前列，切换排序方向；否则设置为升序
    if (currentSort.column === column) {
        currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
    } else {
        currentSort.column = column;
        currentSort.direction = 'asc';
    }
    
    // 更新所有表头的排序图标
    document.querySelectorAll('th.sortable .sort-icon').forEach(icon => {
        icon.textContent = '⇅';
    });
    
    // 更新当前表头的排序图标
    const icon = headerElement.querySelector('.sort-icon');
    if (icon) {
        icon.textContent = currentSort.direction === 'asc' ? '↑' : '↓';
    }
    
    // 执行排序
    sortTable(column, currentSort.direction);

    // 加這兩行 👇
    currentTablePage = 1;
    applyFilters();
}

/**
 * 执行表格排序
 */
function sortTable(column, direction) {
    if (homeDataReady && !isGlobalSearchMode) return;
    const tbody = document.getElementById('ordersTableBody');
    if (!tbody) return;
    
    const rows = Array.from(tbody.querySelectorAll('tr[data-order-number]'));
    const detailRows = Array.from(tbody.querySelectorAll('tr.detail-row[data-detail-for]'));
    const detailRowMap = new Map();
    detailRows.forEach(detailRow => {
        detailRowMap.set(detailRow.dataset.detailFor, detailRow);
    });
    
    rows.sort((a, b) => {
        let aValue = getCellValue(a, column);
        let bValue = getCellValue(b, column);
        
        // 处理数字排序
        if (column === 'status_days' || column === 'quantity' || column === 'order_age') {
            aValue = parseFloat(aValue) || 0;
            bValue = parseFloat(bValue) || 0;
            return direction === 'asc' ? aValue - bValue : bValue - aValue;
        }
        
        // 处理日期排序
        if (column === 'order_date' || column === 'expected_delivery_date') {
            const aDate = aValue ? new Date(aValue) : null;
            const bDate = bValue ? new Date(bValue) : null;
            const aValid = aDate && !Number.isNaN(aDate.getTime());
            const bValid = bDate && !Number.isNaN(bDate.getTime());
            if (!aValid && !bValid) return 0;
            if (!aValid) return direction === 'asc' ? 1 : -1;
            if (!bValid) return direction === 'asc' ? -1 : 1;
            return direction === 'asc' ? aDate - bDate : bDate - aDate;
        }
        
        // 处理字符串排序
        aValue = (aValue || '').toString().toLowerCase();
        bValue = (bValue || '').toString().toLowerCase();
        
        if (direction === 'asc') {
            return aValue.localeCompare(bValue, 'zh-CN');
        } else {
            return bValue.localeCompare(aValue, 'zh-CN');
        }
    });
    
    // 重新插入排序后的行
    rows.forEach(row => {
        tbody.appendChild(row);
        const detailKey = row.dataset.workflowNumber || row.dataset.orderNumber || '';
        const detailRow = detailRowMap.get(detailKey);
        if (detailRow) {
            tbody.appendChild(detailRow);
        }
    });

    // 清理无主的详情行，避免排序后漂浮
    detailRows.forEach(detailRow => {
        if (!detailRow.parentNode) return;
        const detailFor = detailRow.dataset.detailFor || '';
        const hasOwner = rows.some(row => {
            const key = row.dataset.workflowNumber || row.dataset.orderNumber || '';
            return key === detailFor;
        });
        if (!hasOwner) {
            detailRow.remove();
        }
    });
}

/**
 * 获取单元格的值
 */
function getCellValue(row, column) {
    const isAdmin = isAdminRole();
    const headerMap = isAdmin ? {
        'order_date': 2,  // 订单日期（跳过展开和灯号）
        'order_age': 3,  // 今天-订单日期
        'order_number': 4,  // 订单号
        'customer_name': 5,  // 客户名称
        'production_type': 6,  // 产品类型
        'product_code': 7,  // 产品编号
        'quantity': 8,  // 数量
        'factory': 9,  // 生产工厂
        'current_status': 10,  // 阶段/状态
        'status_days': 11,  // 等待天数
        'expected_delivery_date': 12  // 交期
    } : {
        'order_date': 2,  // 订单日期（跳过展开和灯号）
        'order_number': 3,  // 订单号
        'customer_name': 4,  // 客户名称
        'production_type': 5,  // 产品类型
        'product_code': 6,  // 产品编号
        'quantity': 7,  // 数量
        'factory': 8,  // 生产工厂
        'current_status': 9,  // 阶段/状态
        'status_days': 10,  // 等待天数
        'expected_delivery_date': 11  // 交期
    };
    
    // 优先从 data 属性获取值（更可靠）
    if (column === 'order_number') {
        return row.dataset.orderNumber || '';
    }
    if (column === 'customer_name') {
        return row.dataset.customerName || '';
    }
    if (column === 'current_status') {
        return row.dataset.status || '';
    }
    if (column === 'order_age') {
        return row.dataset.orderAge || '';
    }
    if (column === 'expected_delivery_date') {
        return row.dataset.expectedDeliveryDate || '';
    }
    
    // 从单元格获取值
    const cellIndex = headerMap[column];
    if (cellIndex !== undefined) {
        const cells = row.querySelectorAll('td');
        if (cells[cellIndex]) {
            // 获取文本内容，去除图标和格式
            let text = cells[cellIndex].textContent.trim();
            
            // 处理天数（提取数字）
            if (column === 'status_days') {
                const match = text.match(/(\d+)/);
                return match ? match[1] : '0';
            }
            
            // 处理状态（只取状态文本，不包括阶段信息）
            if (column === 'current_status') {
                const statusText = cells[cellIndex].querySelector('.stage-current');
                return statusText ? statusText.textContent.trim() : text;
            }
            
            // 处理订单号（去除 # 符号）
            if (column === 'order_number') {
                return text.replace(/^#/, '').replace(/^\s*/, '');
            }
            
            return text;
        }
    }
    
    return '';
}

/**
 * 统一的刷新所有组件函数
 * 更新：订单行、时间轴、抽屉、筛选、悬停按钮
 */
function refreshAllComponents(orderNumber, workflowNumberOverride) {
    // 重新获取完整订单数据
    fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}`)
        .then(res => res.json())
        .then(result => {
            if (!result.success || !result.data) {
                console.error('获取订单数据失败:', result.error);
                return;
            }
            
            const orderData = result.data;
            const rowForOrder = document.querySelector(`tr[data-order-number="${orderNumber}"]`);
            const workflowNumber = workflowNumberOverride || (rowForOrder ? rowForOrder.dataset.workflowNumber : '');
            
            // 1. 清除缓存，强制重新加载
            if (typeof orderDetailCache !== 'undefined') {
                delete orderDetailCache[orderNumber];
                if (workflowNumber) {
                    delete orderDetailCache[workflowNumber];
                }
            }
            
            // 2. 更新主页面订单行（完整更新，包括悬停按钮）
            if (!workflowNumber) {
                if (typeof updateOrderRowAfterUpdate === 'function') {
                    updateOrderRowAfterUpdate(orderNumber, orderData);
                } else if (typeof updateOrderRowAfterUndo === 'function') {
                    updateOrderRowAfterUndo(orderNumber, orderData);
                }
            }
            
            // 3. 更新时间轴（如果列表详情展开）- 不折叠
            const detailRow = document.querySelector(`tr.detail-row[data-detail-for="${orderNumber}"]`);
            const detailContent = document.getElementById(`detail-content-${orderNumber}`);
            if (!workflowNumber && detailContent && detailRow) {
                // 检查时间轴是否展开（通过检查 detailRow 是否可见）
                const isExpanded = detailRow.offsetParent !== null || detailRow.style.display !== 'none';
                if (isExpanded) {
                    // 时间轴已展开，直接更新内容，不折叠
                    if (typeof renderOrderTimeline === 'function') {
                        renderOrderTimeline(orderNumber, orderData);
                    }
                }
            }
            
            // 4. 更新时间轴（如果抽屉打开）
            if (workflowNumber) {
                fetch(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}`)
                    .then(res => {
                        if (!res.ok && res.status === 404) {
                            return fetch(`/tracking/api/orders/${encodeURIComponent(workflowNumber)}`);
                        }
                        return res;
                    })
                    .then(res => res.json())
                    .then(result => {
                        if (!result || !result.success || !result.data) return;
                        const workflowData = result.data;
                        if (typeof orderDetailCache !== 'undefined') {
                            orderDetailCache[workflowNumber] = workflowData;
                        }
                        if (typeof updateOrderRowAfterUpdate === 'function') {
                            updateOrderRowAfterUpdate(workflowNumber, workflowData);
                        } else if (typeof updateOrderRowAfterUndo === 'function') {
                            updateOrderRowAfterUndo(workflowNumber, workflowData);
                        }
                        const wfDetailRow = document.querySelector(`tr.detail-row[data-detail-for="${workflowNumber}"]`);
                        const wfDetailContent = document.getElementById(`detail-content-${workflowNumber}`);
                        if (wfDetailContent && wfDetailRow) {
                            const wfExpanded = wfDetailRow.offsetParent !== null || wfDetailRow.style.display !== 'none';
                            if (wfExpanded && typeof renderOrderTimeline === 'function') {
                                renderOrderTimeline(workflowNumber, workflowData);
                            }
                        }
                        if (typeof updateFilterCounts === 'function') {
                            updateFilterCounts();
                        }
                        if (typeof applyFilters === 'function') {
                            applyFilters();
                        }
                    })
                    .catch(err => console.error('workflow refresh failed:', err));
            }
            
            // 5. 更新筛选按钮计数
            if (window.WorkspaceDrawer && WorkspaceDrawer.state && WorkspaceDrawer.state.isOpen) {
                if (WorkspaceDrawer.state.currentOrderNumber === orderNumber) {
                    const currentWorkflow = WorkspaceDrawer.state.currentWorkflowNumber;
                    if (currentWorkflow && typeof WorkspaceDrawer.loadData === 'function') {
                        setTimeout(() => {
                            WorkspaceDrawer.loadData(currentWorkflow);
                        }, 300);
                    }
                }
            }

            if (typeof updateFilterCounts === 'function') {
                updateFilterCounts();
            }
            
            // 6. 重新应用筛选（确保订单在正确的筛选组中）
            if (typeof applyFilters === 'function') {
                applyFilters();
            }
            if (typeof initQuickActionsForAllRows === 'function') {
                setTimeout(() => {
                    initQuickActionsForAllRows();
                }, 50);
            }
            if (typeof refreshVisibleTimelines === 'function') {
                setTimeout(() => {
                    refreshVisibleTimelines();
                }, 80);
            }
            
            // 7. 高亮显示订单行（新增）
            setTimeout(() => {
                const highlightKey = workflowNumber || orderNumber;
                highlightOrderRow(highlightKey);
            }, 200);
            // 状态/撤回后重新取得轻量首页资料，让出货摘要与日期即时同步。
            if (homeDataReady && !isGlobalSearchMode) {
                setTimeout(() => loadHomeOrdersData(true), 120);
            }
        })
        .catch(err => {
            console.error('刷新组件失败:', err);
        });
}
// Refresh visible timelines after status updates. 
function refreshVisibleTimelines() { 
    if (typeof renderOrderTimeline !== 'function') return; 
    const detailRows = document.querySelectorAll('tr.detail-row'); 
    if (!detailRows || detailRows.length === 0) return; 
 
    detailRows.forEach(row => { 
        const isVisible = row.offsetParent !== null || row.style.display !== 'none'; 
        if (!isVisible) return; 
 
        const key = row.dataset.detailFor || ''; 
        if (!key) return; 
 
        fetch(`/tracking/api/workflows/${encodeURIComponent(key)}`) 
            .then(res => { 
                if (!res.ok && res.status === 404) { 
                    return fetch(`/tracking/api/orders/${encodeURIComponent(key)}`); 
                } 
                return res; 
            }) 
            .then(res => res.json()) 
            .then(result => { 
                if (result && result.success && result.data) { 
                    if (typeof orderDetailCache !== 'undefined') { 
                        orderDetailCache[key] = result.data; 
                    } 
                    renderOrderTimeline(key, result.data); 
                } 
            }) 
            .catch(err => console.error('refresh visible timeline failed:', err)); 
    }); 
}

// 支持從 URL 直接定位到指定流程
document.addEventListener('DOMContentLoaded', function() {
    const params = new URLSearchParams(window.location.search);
    const workflowNumber = params.get('workflow');
    if (!workflowNumber) return;

    let attempts = 0;
    const maxAttempts = 10;

    const tryOpen = () => {
        const row = document.querySelector(`tr[data-workflow-number="${workflowNumber}"]`) ||
                    document.querySelector(`tr[data-order-number="${workflowNumber}"]`);
        if (row) {
            toggleDetail(workflowNumber);
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return;
        }
        attempts += 1;
        if (attempts < maxAttempts) {
            setTimeout(tryOpen, 300);
        }
    };

    tryOpen();
});

// ==================== WhatsApp 快速撥號（海外模式）====================

const waContacts = {}; // { "JORGE MONTANO": "5219991234567" }

async function loadWhatsAppContacts() {
    try {
        const res = await fetch('/contacto');
        if (!res.ok) return;
        const data = await res.json();
        data.forEach(item => {
            const name = (item.nombre || '').trim().toUpperCase();
            const phone = (item.telefono || item.telefono1 || '').replace(/\D/g, '');
            if (name && phone) waContacts[name] = phone;
        });
        console.log(`[WA] 已載入 ${Object.keys(waContacts).length} 筆聯絡人`);
        console.log(`[WA] 查詢缺少電話的客戶：${location.origin}/tracking/api/missing-contacts`);
    } catch (e) {
        console.log('[WA] 無法連接聯絡人 API，WhatsApp 功能不可用');
    }
}

function openWhatsApp(customerName) {
    const name = (customerName || '').trim().toUpperCase();
    const phone = waContacts[name];
    if (!phone) {
        showToast('找不到電話', `${customerName} 沒有電話號碼`, 'error');
        return;
    }
    window.open(`https://wa.me/${phone}`, '_blank');
}

function wsOpenWhatsApp() {
    const waBtn = document.getElementById('wsWaBtn');
    const customerName = waBtn ? waBtn.dataset.customer : '';
    const orderNumber = waBtn ? waBtn.dataset.order : '';
    const name = (customerName || '').trim().toUpperCase();
    const phone = waContacts[name];
    if (!phone) {
        showToast('找不到電話', `${customerName || '此客戶'} 沒有電話號碼`, 'error');
        return;
    }
    const orderPart = orderNumber ? `, Le informo sobre contrato ${orderNumber}` : '';
    const msg = encodeURIComponent(`Hola Sr(a) ${customerName}${orderPart}`);
    window.open(`https://web.whatsapp.com/send?phone=${phone}&text=${msg}`, '_blank');
}

document.addEventListener('DOMContentLoaded', function () {
    // 只有海外模式才載入（IS_OVERSEAS 由後端注入）
    if (!window.IS_OVERSEAS) return;

    loadWhatsAppContacts();

    // 用事件委託，點擊 wa-btn 就開 WhatsApp
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.wa-btn');
        if (!btn) return;
        e.stopPropagation();
        openWhatsApp(btn.dataset.customer);
    });
});


// ==================== 訂金字典（Deposit Map）====================
// 頁面載入時打一次 API，把所有有餘額的訂單號存成字典
// 格式：{ "1007549": 500.00, "1007123": 200.50, ... }

const wsDepositMap = {};  // 全域字典

async function wsLoadDepositMap() {
    try {
        const res = await fetch('/costo_laboral/deposit_map');
        if (!res.ok) return;
        const data = await res.json();
        if (!data.ok || !data.last6) return;

        // last6 的 key 是末6碼純數字，value 是餘額
        // 存進全域字典
        Object.assign(wsDepositMap, data.last6);
        console.log(`[Deposit] 已載入 ${Object.keys(wsDepositMap).length} 筆訂金資料`);
    } catch (e) {
        console.log('[Deposit] 無法載入訂金資料');
    }
}

// 開抽屜時呼叫這個函數查字典並更新徽章
function wsShowDepositBadge(orderNumber) {
    const badge  = document.getElementById('wsDepositBadge');
    const amtEl  = document.getElementById('wsDepositAmount');
    if (!badge || !amtEl) return;

    // 先隱藏
    badge.style.display = 'none';
    if (!orderNumber) return;

    // 把訂單號轉成末6碼純數字（跟 deposit_map 的 key 格式對齊）
    const digits = String(orderNumber).replace(/\D/g, '');
    if (!digits) return;
    const key6 = ('000000' + digits).slice(-6);

    const balance = wsDepositMap[key6];
    if (balance === undefined || balance === null || Math.abs(balance) < 0.01) return;

    // 格式化金額
    const fmt = Math.abs(balance).toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
    amtEl.textContent = (balance < 0 ? '-US$' : 'US$') + fmt;

    // 顏色：正數黃（有訂金未用完）、負數紅（欠款）
    if (balance < 0) {
        badge.style.background  = '#fee2e2';
        badge.style.borderColor = '#fca5a5';
        badge.style.color       = '#991b1b';
    } else {
        badge.style.background  = '#fef9c3';
        badge.style.borderColor = '#fde047';
        badge.style.color       = '#854d0e';
    }
    badge.style.display = 'inline-flex';
}

// 點擊徽章 → 新分頁開訂金頁
function wsOpenDepositDetail() {
    const orderNum = document.getElementById('wsOrderNumber')?.textContent?.trim();
    if (!orderNum || orderNum === '-') return;
    window.open('/costo_laboral/deposit?nota=' + encodeURIComponent(orderNum), '_blank');
}

// 頁面載入時執行
document.addEventListener('DOMContentLoaded', function () {
    wsLoadDepositMap();
});


// ============================================================================
// Mobile UI (<= 768px)
// CC UI specification: WhatsApp-like rows, order/customer modes, stacked filters.
// Data/filter/security logic stays shared with the desktop implementation.
// ============================================================================
let mobileBrowseMode = 'orders';
let mobileCustomerDetailName = '';
let mobileOrderDetailKey = '';
let mobileOrderDetailReturn = 'orders';
let mobileOrderDetailData = null;
let mobileVisibleLimit = 60;
let mobileLastFilterSignature = '';
let mobileBrowseScrollTop = 0;
let mobileCustomerScrollTop = 0;
let mobileCustomerFocusOffset = null;
let mobileCustomerRestoreTimers = [];
let mobileLastFocusOrderKey = '';
let mobileLastFocusCustomerName = '';
// Session-only viewed markers for the mobile customer gallery.
// Intentionally kept only in JS memory: refresh/reload clears everything.
const mobileCustomerViewedOrderKeys = new Set();
let mobileCustomerLastViewedIdentity = '';
let mobileReportPollTimer = null;
let mobileCurrentReportFiles = [];
let mobileReportRequestContext = null;
let mobileReportDraftOptions = null;
let mobileImageItems = [];
let mobileImageIndex = 0;
const mobileCustomerCoverCache = new Map();
const mobileCustomerImagesCache = new Map();
const mobileCustomerStatusFilters = new Map();
const mobileCustomerHistorySettings = new Map();
const mobileCustomerHistoryResults = new Map();
let mobileCustomerHistoryRequestSeq = 0;
let mobileCustomerCoverGeneration = 0;

function isMobileOrderViewport() {
    return !!(window.matchMedia && window.matchMedia('(max-width: 768px)').matches);
}

function mobileCustomerViewedIdentity(customerName, orderKey) {
    return `${String(customerName || '')}\u0000${String(orderKey || '')}`;
}

function markMobileCustomerOrderViewed(customerName, orderKey) {
    if (!customerName || !orderKey) return;
    const identity = mobileCustomerViewedIdentity(customerName, orderKey);
    mobileCustomerViewedOrderKeys.add(identity);
    mobileCustomerLastViewedIdentity = identity;
}

function mobileCustomerOrderViewedState(customerName, orderKey) {
    const identity = mobileCustomerViewedIdentity(customerName, orderKey);
    if (identity && identity === mobileCustomerLastViewedIdentity) return 'last';
    if (mobileCustomerViewedOrderKeys.has(identity)) return 'viewed';
    return '';
}

// iOS Safari may try to restore the scroll container after popstate, which can
// fight our customer-gallery anchor restore and jump to a different place.
// Mobile order navigation owns this scroll position, so keep browser restoration manual.
try {
    if (isMobileOrderViewport() && 'scrollRestoration' in history) history.scrollRestoration = 'manual';
} catch (_) {}

function mobileT(key, fallback = '') {
    if (typeof window.trackingT === 'function') {
        const value = window.trackingT(key);
        return value === key && fallback ? fallback : value;
    }
    return fallback || key;
}

function mobileOrderCountText(count) {
    return window.getTrackingLanguage?.() === 'es'
        ? `${count} ${count === 1 ? 'pedido' : 'pedidos'}`
        : `${count} 笔订单`;
}

function mobileCustomerCountText(count) {
    return window.getTrackingLanguage?.() === 'es'
        ? `${count} ${count === 1 ? 'cliente' : 'clientes'}`
        : `${count} 位客户`;
}

function mobileUnitText(count) {
    return window.getTrackingLanguage?.() === 'es'
        ? `${count} ${count === 1 ? 'pedido' : 'pedidos'}`
        : `${count} 笔`;
}

function mobileStatusText(status) {
    return typeof displayStatus === 'function' ? displayStatus(status || '') : (status || '-');
}

function mobileOrderDisplayNumber(order) {
    return String(order?.workflow_number || order?.workflowNumber || order?.order_number || order?.orderNumber || '-');
}

function mobileSafeDate(value) {
    if (!value) return '';
    const raw = String(value).trim();
    if (!raw) return '';
    const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
    const lang = typeof window.getTrackingLanguage === 'function' ? window.getTrackingLanguage() : 'zh_cn';
    if (match) return lang === 'es' ? `${match[3]}-${match[2]}` : `${match[2]}-${match[3]}`;
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return raw.slice(0, 10);
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return lang === 'es' ? `${dd}-${mm}` : `${mm}-${dd}`;
}

function mobileTimestamp(order) {
    const raw = order?.status_updated_at || order?.last_status_change_date || order?.order_date || '';
    const t = raw ? new Date(raw).getTime() : 0;
    return Number.isFinite(t) ? t : 0;
}

function mobileLightClass(order) {
    const light = String(order?.status_light || '').toLowerCase();
    return ['red', 'yellow', 'green'].includes(light) ? light : 'none';
}

function mobileLightRank(light) {
    return light === 'red' ? 3 : light === 'yellow' ? 2 : light === 'green' ? 1 : 0;
}

function mobileCustomerInitial(name) {
    const s = String(name || '?').trim();
    return (s.charAt(0) || '?').toUpperCase();
}

function syncMobileControlsFromCurrentFilter() {
    const input = document.getElementById('mobileSearchInput');
    const clear = document.getElementById('mobileSearchClear');
    const searchText = selectedCustomerNameFilter || selectedOrderNumberFilter || currentFilter.search || '';
    if (input && document.activeElement !== input) input.value = searchText;
    if (clear) clear.classList.toggle('show', !!String(searchText).trim());

    const groups = currentFilter.stageGroups || ['all'];
    const mobileStage = groups.length === 1 ? groups[0] : 'all';
    document.querySelectorAll('[data-mobile-stage]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mobileStage === mobileStage);
    });

    const lights = currentFilter.lights || {red:true, yellow:true, green:true};
    let mobileLight = 'all';
    const enabled = ['red','yellow','green'].filter(k => lights[k] !== false);
    if (enabled.length === 1) mobileLight = enabled[0];
    document.querySelectorAll('[data-mobile-light]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mobileLight === mobileLight);
    });
}

function mobileSearchInputChanged(value) {
    restoreHomeRowsFromGlobalSearchIfNeeded();
    selectedCustomerNameFilter = '';
    selectedOrderNumberFilter = '';
    currentFilter.search = String(value || '').trim();
    const desktopInput = document.getElementById('searchInput');
    if (desktopInput) desktopInput.value = currentFilter.search;
    const clear = document.getElementById('mobileSearchClear');
    if (clear) clear.classList.toggle('show', !!currentFilter.search);
    updateMobileSearchSuggestions(value);
    applyFilters();
}

function hideMobileSearchSuggestions() {
    const box = document.getElementById('mobileSearchSuggestions');
    if (!box) return;
    box.innerHTML = '';
    box.classList.remove('show');
}

function updateMobileSearchSuggestions(rawValue) {
    const box = document.getElementById('mobileSearchSuggestions');
    if (!box) return;
    const matches = typeof getFrontEndSearchSuggestions === 'function'
        ? getFrontEndSearchSuggestions(rawValue)
        : [];
    box.innerHTML = '';
    if (!matches.length || !String(rawValue || '').trim()) {
        box.classList.remove('show');
        return;
    }
    matches.forEach((item, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'mobile-search-suggestion';
        button.dataset.index = String(index);
        const type = document.createElement('span');
        type.className = `mobile-search-suggestion-type ${item.type}`;
        type.textContent = item.type === 'customer'
            ? mobileT('mobile.search_customer', '客户')
            : mobileT('mobile.search_order', '订单');
        const label = document.createElement('span');
        label.className = 'mobile-search-suggestion-label';
        label.textContent = item.label;
        button.append(type, label);
        button.addEventListener('click', event => {
            event.preventDefault();
            selectMobileSearchSuggestion(item);
        });
        box.appendChild(button);
    });
    box.classList.add('show');
}

function selectMobileSearchSuggestion(item) {
    if (!item) return;
    restoreHomeRowsFromGlobalSearchIfNeeded();
    const input = document.getElementById('mobileSearchInput');
    const desktopInput = document.getElementById('searchInput');
    const value = String(item.value || '').trim();
    if (item.type === 'customer') {
        selectedCustomerNameFilter = value;
        selectedOrderNumberFilter = '';
    } else {
        selectedCustomerNameFilter = '';
        selectedOrderNumberFilter = value;
        mobileBrowseMode = 'orders';
    }
    currentFilter.search = value;
    if (input) input.value = value;
    if (desktopInput) desktopInput.value = value;
    const clear = document.getElementById('mobileSearchClear');
    if (clear) clear.classList.toggle('show', !!value);
    hideMobileSearchSuggestions();
    applyFilters();
    if (typeof saveFilterState === 'function') saveFilterState();
    renderMobileExperience(true);
}

function mobileSearchKeydown(event) {
    if (!event) return;
    if (event.key === 'Escape') {
        hideMobileSearchSuggestions();
        event.currentTarget?.blur();
        return;
    }
    if (event.key !== 'Enter') return;
    const box = document.getElementById('mobileSearchSuggestions');
    const first = box?.querySelector('.mobile-search-suggestion');
    if (first) {
        event.preventDefault();
        first.click();
    } else {
        hideMobileSearchSuggestions();
    }
}

function clearMobileSearch() {
    const input = document.getElementById('mobileSearchInput');
    if (input) input.value = '';
    selectedCustomerNameFilter = '';
    selectedOrderNumberFilter = '';
    currentFilter.search = '';
    const desktopInput = document.getElementById('searchInput');
    if (desktopInput) desktopInput.value = '';
    const desktopClear = document.getElementById('searchClearBtn');
    if (desktopClear) {
        desktopClear.style.opacity = '0';
        desktopClear.style.pointerEvents = 'none';
    }
    hideMobileSearchSuggestions();
    applyFilters();
    if (input) input.focus();
}

function mobileSetStage(stageGroup) {
    currentFilter.substatus = 'all';
    currentFilter.stageGroups = [stageGroup || 'all'];
    currentFilter.stageGroup = stageGroup || 'all';
    if (typeof syncStageGroupButtons === 'function') syncStageGroupButtons();
    applyFilters();
    if (typeof saveFilterState === 'function') saveFilterState();
}

function syncDesktopLightButtonsFromState() {
    ['red','yellow','green'].forEach(light => {
        const button = document.getElementById(`lightFilter${light.charAt(0).toUpperCase() + light.slice(1)}`);
        if (!button) return;
        const on = currentFilter.lights?.[light] !== false;
        button.classList.toggle('active', on);
        button.classList.toggle('inactive', !on);
    });
}

function mobileSetLight(light) {
    if (light === 'all') {
        currentFilter.lights = {red:true, yellow:true, green:true};
    } else {
        currentFilter.lights = {
            red: light === 'red',
            yellow: light === 'yellow',
            green: light === 'green'
        };
    }
    syncDesktopLightButtonsFromState();
    applyFilters();
    if (typeof saveFilterState === 'function') saveFilterState();
}

function getMobileSalespeople() {
    const counts = new Map();
    (homeOrdersData || []).forEach(order => {
        const id = String(order.handler_id || order.handlerId || '').trim();
        const name = String(order.handler_name || order.handlerName || '').trim();
        if (!id || !name || name === '-') return;
        const old = counts.get(id) || {id, name, count:0};
        old.count += 1;
        counts.set(id, old);
    });
    return Array.from(counts.values()).sort((a,b) => (b.count - a.count) || a.name.localeCompare(b.name, 'zh-CN'));
}

function renderMobileSalesFilters() {
    if (!document.body || document.body.dataset.canViewUser !== 'true') return;
    const container = document.getElementById('mobileSalesFilters');
    const sheetOptions = document.getElementById('mobileSalesSheetOptions');
    if (!container) return;

    const sales = getMobileSalespeople();
    const selected = String((currentFilter.teamSales || [])[0] || '');
    container.innerHTML = '';

    const allBtn = document.createElement('button');
    allBtn.type = 'button';
    allBtn.className = 'mobile-chip' + (!selected ? ' active' : '');
    allBtn.textContent = mobileT('filter.all_salespeople', '全部业务员');
    allBtn.onclick = () => mobileSetSalesperson('');
    container.appendChild(allBtn);

    sales.slice(0, 5).forEach(person => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'mobile-chip' + (selected === person.id ? ' active' : '');
        btn.textContent = person.name;
        btn.onclick = () => mobileSetSalesperson(person.id);
        container.appendChild(btn);
    });

    if (sales.length > 5) {
        const more = document.createElement('button');
        more.type = 'button';
        more.className = 'mobile-chip mobile-more-chip';
        more.textContent = mobileT('filter.more', '更多…');
        more.onclick = openMobileSalesSheet;
        container.appendChild(more);
    }

    if (sheetOptions) {
        sheetOptions.innerHTML = '';
        const makeOption = (id, name, countText='') => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'mobile-sheet-option' + (selected === id ? ' active' : '');
            const nameEl = document.createElement('span');
            nameEl.textContent = name;
            const countEl = document.createElement('small');
            countEl.textContent = countText;
            btn.append(nameEl, countEl);
            btn.onclick = () => mobileSetSalesperson(id);
            sheetOptions.appendChild(btn);
        };
        makeOption('', mobileT('filter.all_salespeople', '全部业务员'), mobileUnitText(homeOrdersData.length));
        sales.forEach(person => makeOption(person.id, person.name, mobileUnitText(person.count)));
    }
}

function mobileSetSalesperson(handlerId) {
    currentFilter.teamSales = handlerId ? [String(handlerId)] : [];
    applyFilters();
    closeMobileSalesSheet();
    if (typeof saveFilterState === 'function') saveFilterState();
}

function openMobileSalesSheet() {
    const sheet = document.getElementById('mobileSalesSheet');
    const backdrop = document.getElementById('mobileSalesSheetBackdrop');
    if (sheet) {
        sheet.classList.add('show');
        sheet.setAttribute('aria-hidden', 'false');
    }
    if (backdrop) backdrop.classList.add('show');
}

function closeMobileSalesSheet() {
    const sheet = document.getElementById('mobileSalesSheet');
    const backdrop = document.getElementById('mobileSalesSheetBackdrop');
    if (sheet) {
        sheet.classList.remove('show');
        sheet.setAttribute('aria-hidden', 'true');
    }
    if (backdrop) backdrop.classList.remove('show');
}

function setMobileBrowseMode(mode) {
    hideMobileSearchSuggestions();
    mobileBrowseMode = mode === 'customers' ? 'customers' : 'orders';
    mobileCustomerDetailName = '';
    mobileOrderDetailKey = '';
    mobileOrderDetailData = null;
    mobileVisibleLimit = 60;
    const ui = document.getElementById('mobileOrderUi');
    if (ui) ui.classList.remove('customer-detail-open');
    const detail = document.getElementById('mobileCustomerDetail');
    if (detail) detail.hidden = true;

    const ordersBtn = document.getElementById('mobileModeOrders');
    const customersBtn = document.getElementById('mobileModeCustomers');
    if (ordersBtn) ordersBtn.classList.toggle('active', mobileBrowseMode === 'orders');
    if (customersBtn) customersBtn.classList.toggle('active', mobileBrowseMode === 'customers');
    const mobileSort = document.getElementById('mobileHomeMultiSort');
    if (mobileSort) mobileSort.hidden = mobileBrowseMode !== 'orders';
    mobileReplaceBrowseHistoryState(mobileBrowseMode, 0);
    renderMobileExperience(true);
}



function mobileOrderPrefixType(order) {
    const number = String(mobileOrderDisplayNumber(order) || '').trim().toUpperCase();
    if (/^KC/.test(number)) return 'kc';
    if (/^G/.test(number)) return 'g';
    return 'normal';
}

function mobileHasRealCustomer(order) {
    const name = String(order?.customer_name || '').trim();
    if (!name) return false;
    const normalized = name.toLowerCase();
    const placeholders = new Set([
        '未指定客户', '未指定客戶', 'sin cliente', 'no customer',
        'unassigned customer', 'unassigned', '-', '—'
    ]);
    return !placeholders.has(normalized);
}

function mobileOrderIsExplicitlySearched() {
    return !!String(
        selectedOrderNumberFilter ||
        selectedCustomerNameFilter ||
        currentFilter.search ||
        ''
    ).trim();
}

function mobileShouldShowInOrderMode(order) {
    const type = mobileOrderPrefixType(order);

    // Main mobile use-case = customer orders.
    // Normal orders always show.
    if (type === 'normal') return true;

    // G / KC are internal-style numbers, but some are real customer orders.
    // Keep those when a customer is assigned.
    if (mobileHasRealCustomer(order)) return true;

    // Do not clutter the default list with anonymous G/KC rows.
    // However, an explicit search can still surface them when somebody needs one.
    return mobileOrderIsExplicitlySearched();
}

function mobileOrderBusinessPriority(order) {
    const type = mobileOrderPrefixType(order);
    if (type === 'normal') return 0;
    if (mobileHasRealCustomer(order)) return 1;
    return 2;
}

function mobileCompareOrderNumberDesc(a, b) {
    const av = String(mobileOrderDisplayNumber(a) || '').trim();
    const bv = String(mobileOrderDisplayNumber(b) || '').trim();

    // Mobile "按订单" means order-number order, newest/larger order first.
    // numeric:true keeps 1008212-10 after 1008212-2 correctly and also
    // handles G/KC style numbers naturally without changing desktop sorting.
    const cmp = bv.localeCompare(av, 'zh-CN', {
        numeric: true,
        sensitivity: 'base'
    });
    if (cmp !== 0) return cmp;

    // Stable fallback for duplicated display numbers / workflow suffixes.
    const ak = String(getHomeOrderKey(a) || '');
    const bk = String(getHomeOrderKey(b) || '');
    return bk.localeCompare(ak, 'zh-CN', {numeric:true, sensitivity:'base'});
}

function getMobileOrdersSortedByOrderNumber() {
    const source = (homeFilteredOrdersData || [])
        .filter(mobileShouldShowInOrderMode)
        .filter(order => mobileOrderTypeFilters.has(mobileOrderViewType(order)))
        .slice();
    return source.sort(mobileCompareOrderView);
}

function makeMobileOrderRow(order) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = `mobile-order-row light-${mobileLightClass(order)}`;
    row.dataset.orderKey = getHomeOrderKey(order);

    const avatar = document.createElement('span');
    avatar.className = 'mobile-order-avatar';
    avatar.textContent = mobileCustomerInitial(order.customer_name);

    const copy = document.createElement('span');
    copy.className = 'mobile-order-copy';

    const line1 = document.createElement('span');
    line1.className = 'mobile-order-primary';
    const name = document.createElement('strong');
    name.textContent = order.customer_name || mobileT('mobile.unassigned_customer', '未指定客户');
    const dot = document.createElement('span');
    dot.className = `mobile-status-dot ${mobileLightClass(order)}`;
    line1.append(name, dot);

    const line2 = document.createElement('span');
    line2.className = 'mobile-order-secondary';
    const statusAndNumber = document.createElement('span');
    statusAndNumber.textContent = `${mobileStatusText(order.current_status)} · ${mobileOrderDisplayNumber(order)}`;
    const handler = document.createElement('small');
    handler.textContent = order.handler_name || order.handlerName || '';
    line2.append(statusAndNumber, handler);

    copy.append(line1, line2);
    if (mobileOrderSortMode === 'elapsed') {
        const metric = document.createElement('span');
        metric.className = 'mobile-order-sort-metric';
        metric.textContent = `${Math.max(0, Number(order.status_days || 0))}${window.getTrackingLanguage?.() === 'es' ? ' días' : '天'}`;
        copy.appendChild(metric);
    } else if (mobileOrderSortMode === 'date') {
        const metric = document.createElement('span');
        metric.className = 'mobile-order-sort-metric';
        metric.textContent = mobileSafeDate(order.order_date) || '—';
        copy.appendChild(metric);
    }
    row.append(avatar, copy);
    if (row.dataset.orderKey === mobileLastFocusOrderKey && mobileLastFocusCustomerName === '') {
        row.classList.add('mobile-return-focus');
    }
    row.addEventListener('click', () => {
        const main = document.getElementById('mainContent');
        mobileBrowseScrollTop = main?.scrollTop || 0;
        mobileLastFocusOrderKey = row.dataset.orderKey;
        mobileLastFocusCustomerName = '';
        // The parent history entry must be the ORDER LIST, never a stale customer state.
        mobileReplaceBrowseHistoryState('orders', mobileBrowseScrollTop);
        mobileOpenOrderDetail(row.dataset.orderKey, {returnView:'orders'});
    });
    return row;
}

function renderMobileOrderList() {
    const list = document.getElementById('mobileOrdersList');
    const loadMore = document.getElementById('mobileLoadMoreBtn');
    if (!list) return;

    list.innerHTML = '';
    const data = getMobileOrdersSortedByOrderNumber();
    if (!data.length) {
        const empty = document.createElement('div');
        empty.className = 'mobile-empty';
        empty.textContent = isCloudMode() && !cloudProviderReady
            ? mobileT('mobile.no_cloud_orders', '尚未同步云端订单资料')
            : mobileT('mobile.no_orders', '没有符合条件的订单');
        list.appendChild(empty);
        if (loadMore) loadMore.style.display = 'none';
        return;
    }

    data.slice(0, mobileVisibleLimit).forEach(order => list.appendChild(makeMobileOrderRow(order)));
    if (loadMore) {
        const moreCount = Math.max(0, data.length - mobileVisibleLimit);
        loadMore.style.display = moreCount > 0 ? 'block' : 'none';
        loadMore.textContent = moreCount > 0
            ? (window.getTrackingLanguage?.() === 'es' ? `Mostrar más (${moreCount} restantes)` : `显示更多（还有 ${moreCount} 笔）`)
            : mobileT('mobile.more', '显示更多');
    }
}

function buildMobileCustomerGroups() {
    const map = new Map();
    (homeFilteredOrdersData || []).forEach(order => {
        const prefixType = mobileOrderPrefixType(order);
        if ((prefixType === 'g' || prefixType === 'kc') && !mobileHasRealCustomer(order)) return;

        const fallbackCustomer = mobileT('mobile.unassigned_customer', '未指定客户');
        const name = String(order.customer_name || fallbackCustomer).trim() || fallbackCustomer;
        let group = map.get(name);
        if (!group) {
            group = {name, orders:[], severity:'none', latest:null, latestTs:0};
            map.set(name, group);
        }
        group.orders.push(order);
        const light = mobileLightClass(order);
        if (mobileLightRank(light) > mobileLightRank(group.severity)) group.severity = light;
        const ts = mobileTimestamp(order);
        if (!group.latest || ts >= group.latestTs) {
            group.latest = order;
            group.latestTs = ts;
        }
    });
    return Array.from(map.values()).sort((a,b) => (b.latestTs - a.latestTs) || a.name.localeCompare(b.name, 'zh-CN'));
}

function renderMobileCustomerList() {
    const list = document.getElementById('mobileCustomersList');
    if (!list) return;
    const groups = buildMobileCustomerGroups();
    list.innerHTML = '';

    if (!groups.length) {
        const empty = document.createElement('div');
        empty.className = 'mobile-empty';
        empty.textContent = mobileT('mobile.no_customers', '没有符合条件的客户');
        list.appendChild(empty);
        return;
    }

    groups.forEach(group => {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = `mobile-customer-row light-${group.severity}`;

        const avatar = document.createElement('span');
        avatar.className = 'mobile-order-avatar';
        avatar.textContent = mobileCustomerInitial(group.name);

        const copy = document.createElement('span');
        copy.className = 'mobile-order-copy';

        const primary = document.createElement('span');
        primary.className = 'mobile-order-primary';
        const name = document.createElement('strong');
        name.textContent = group.name;
        const badge = document.createElement('span');
        badge.className = `mobile-customer-count ${group.severity}`;
        badge.textContent = mobileUnitText(group.orders.length);
        primary.append(name, badge);

        const secondary = document.createElement('span');
        secondary.className = 'mobile-customer-secondary';
        const latest = group.latest || {};
        const latestDate = mobileSafeDate(latest.status_updated_at || latest.last_status_change_date || latest.order_date);
        secondary.textContent = `${mobileT('mobile.latest', '最新')}：${mobileStatusText(latest.current_status)}${latestDate ? ` · ${latestDate}` : ''}`;

        copy.append(primary, secondary);
        row.append(avatar, copy);
        row.onclick = () => openMobileCustomerDetail(group.name);
        list.appendChild(row);
    });
}


function mobileCustomerCoverKey(order) {
    return String(getHomeOrderKey(order) || mobileOrderDisplayNumber(order) || '').trim();
}

function mobilePickOrderCover(images) {
    if (!Array.isArray(images) || !images.length) return null;
    return images.find(img => img?.source === 'order') || images[0] || null;
}

async function mobileLoadCustomerOrderImages(order) {
    if (isCloudMode()) return [];
    const key = mobileCustomerCoverKey(order);
    if (!key) return [];
    // Freshness rule: never keep a resolved attachment/media list in browser memory.
    // The map is only an in-flight dedupe so simultaneous requests do not duplicate work.
    if (mobileCustomerImagesCache.has(key)) {
        return await Promise.resolve(mobileCustomerImagesCache.get(key));
    }
    const promise = mobileLoadOrderImages(order)
        .then(images => Array.isArray(images) ? images : [])
        .catch(() => [])
        .finally(() => mobileCustomerImagesCache.delete(key));
    mobileCustomerImagesCache.set(key, promise);
    return await promise;
}

async function mobileLoadOrderCover(order) {
    if (isCloudMode()) return null;
    const key = mobileCustomerCoverKey(order);
    if (!key) return null;
    if (mobileCustomerCoverCache.has(key)) {
        return await Promise.resolve(mobileCustomerCoverCache.get(key));
    }
    const promise = mobileLoadCustomerOrderImages(order)
        .then(images => mobilePickOrderCover(images))
        .catch(() => null)
        .finally(() => mobileCustomerCoverCache.delete(key));
    mobileCustomerCoverCache.set(key, promise);
    return await promise;
}

function mobileCustomerTileLoadImage(img) {
    if (!img || img.src || !img.dataset.src) return;
    img.src = img.dataset.src;
    img.removeAttribute('data-src');
}

function mobileCustomerTileMediaScrolled(track) {
    if (!track) return;
    const width = track.clientWidth || 1;
    const count = Number(track.dataset.imageCount || 0);
    if (!count) return;

    const index = Math.max(0, Math.min(count - 1, Math.round(track.scrollLeft / width)));
    track.dataset.imageIndex = String(index);

    // A swipe should browse photos, not accidentally open the order.
    const tile = track.closest('.mobile-customer-order-tile');
    if (tile) tile.dataset.suppressOpenUntil = String(Date.now() + 420);

    // Lazy-load current / adjacent images only.
    [index - 1, index, index + 1].forEach(i => {
        if (i < 0 || i >= count) return;
        const img = track.querySelector(`[data-tile-image-index="${i}"]`);
        mobileCustomerTileLoadImage(img);
    });

    const cover = track.closest('.mobile-customer-order-cover');
    cover?.querySelectorAll('[data-tile-dot]').forEach(dot => {
        dot.classList.toggle('active', Number(dot.dataset.tileDot) === index);
    });

    const counter = cover?.querySelector('.mobile-customer-order-image-counter');
    if (counter) counter.textContent = `${index + 1}/${count}`;
}

async function mobileHydrateCustomerOrderCovers(customerName, orders) {
    if (isCloudMode() || !Array.isArray(orders) || !orders.length) return;
    const generation = ++mobileCustomerCoverGeneration;
    let cursor = 0;
    const workerCount = Math.min(4, orders.length);

    async function worker() {
        while (cursor < orders.length) {
            const index = cursor++;
            const order = orders[index];
            const orderKey = mobileCustomerCoverKey(order);
            if (!orderKey) continue;

            const images = await mobileLoadCustomerOrderImages(order);
            if (generation !== mobileCustomerCoverGeneration) return;
            if (String(mobileCustomerDetailName || '') !== String(customerName || '')) return;

            const content = document.getElementById('mobileCustomerDetailContent');
            const tile = content?.querySelector(`[data-order-key="${CSS.escape(orderKey)}"]`);
            if (!tile) continue;

            const fallback = tile.querySelector('.mobile-customer-order-cover-fallback');
            const track = tile.querySelector('.mobile-customer-order-carousel-track');
            const dots = tile.querySelector('.mobile-customer-order-image-dots');
            const counter = tile.querySelector('.mobile-customer-order-image-counter');

            if (!images.length) {
                tile.classList.remove('has-cover');
                if (fallback) fallback.hidden = false;
                if (track) track.innerHTML = '';
                if (dots) dots.innerHTML = '';
                if (counter) counter.hidden = true;
                continue;
            }

            tile.classList.add('has-cover');
            if (fallback) fallback.hidden = true;

            if (track) {
                track.innerHTML = '';
                track.dataset.imageCount = String(images.length);
                track.dataset.imageIndex = '0';

                images.forEach((image, imageIndex) => {
                    const slide = document.createElement('span');
                    slide.className = 'mobile-customer-order-carousel-slide';

                    const img = document.createElement('img');
                    img.className = 'mobile-customer-order-cover-img';
                    img.alt = '';
                    img.loading = (imageIndex === 0 && index < 4) ? 'eager' : 'lazy';
                    img.decoding = 'async';
                    if (imageIndex === 0 && index < 2) img.fetchPriority = 'high';
                    img.dataset.tileImageIndex = String(imageIndex);

                    // Only the first photo gets a real src immediately.
                    // Others load when the user swipes near them.
                    const cardUrl = image.preview_url || image.url;
                    if (imageIndex === 0) img.src = cardUrl;
                    else img.dataset.src = cardUrl;

                    slide.appendChild(img);
                    track.appendChild(slide);
                });
            }

            if (dots) {
                dots.innerHTML = '';
                if (images.length > 1) {
                    images.forEach((_, imageIndex) => {
                        const dot = document.createElement('span');
                        dot.className = `mobile-customer-order-image-dot${imageIndex === 0 ? ' active' : ''}`;
                        dot.dataset.tileDot = String(imageIndex);
                        dots.appendChild(dot);
                    });
                }
            }

            if (counter) {
                counter.hidden = images.length <= 1;
                counter.textContent = `1/${images.length}`;
            }
        }
    }

    await Promise.all(Array.from({length: workerCount}, worker));
}

function mobileOpenCustomerProfileFromOrder(customerName, orderKey) {
    const name = String(customerName || '').trim();
    const key = String(orderKey || mobileOrderDetailKey || '').trim();
    if (!name || !key) return;

    // Navigation rule: how you enter is how you return.
    // Order -> customer profile must always have the current ORDER as the immediate
    // browser-history entry underneath the customer profile.  This makes iOS/Android
    // edge-swipe Back return to the exact order instead of the customer's previous page.
    const currentState = history.state || {};
    const returnView = mobileOrderDetailReturn || 'orders';
    const returnCustomer = returnView === 'customer'
        ? (mobileCustomerDetailName || name)
        : '';

    history.replaceState({
        ...currentState,
        __trackingMobile: true,
        trackingMobileView: 'order',
        browseMode: mobileBrowseMode,
        orderKey: key,
        returnView,
        customerName: returnCustomer
    }, '', window.location.href);

    mobileLastFocusOrderKey = key;
    mobileLastFocusCustomerName = name;
    mobileCustomerScrollTop = 0;
    mobileCustomerFocusOffset = null;

    // Reuse the SAME customer-detail screen as 首页 -> 按客户 -> 点击客户,
    // but create the history entry explicitly so its parent is guaranteed to be this order.
    openMobileCustomerDetail(name, {pushHistory:false, instant:true});
    mobilePushViewState('customer', {
        customerName: name,
        originView: 'order',
        originOrderKey: key
    });
}


function mobileCustomerHistorySetting(customerName) {
    const key = String(customerName || '');
    const saved = mobileCustomerHistorySettings.get(key);
    if (saved) return {...saved};
    return {scope:'current', includeCancelled:false};
}

function mobileCustomerHistoryLabel(scope) {
    const es = window.getTrackingLanguage?.() === 'es';
    const labels = es
        ? {current:'Actual', '6m':'6 meses', '12m':'1 año', all:'Todo'}
        : {current:'目前', '6m':'半年', '12m':'一年', all:'全部历史'};
    return labels[String(scope || 'current')] || labels.current;
}

function mobileCustomerViewOrders(customerName) {
    const name = String(customerName || '').trim();
    const setting = mobileCustomerHistorySetting(name);
    if (setting.scope === 'current' && !setting.includeCancelled) {
        return (homeOrdersData || []).filter(order => String(order.customer_name || '').trim() === name);
    }
    const stored = mobileCustomerHistoryResults.get(name);
    if (stored && stored.scope === setting.scope && stored.includeCancelled === setting.includeCancelled) {
        return Array.isArray(stored.orders) ? stored.orders : [];
    }
    return [];
}

async function mobileLoadCustomerHistory(customerName, setting, options = {}) {
    const name = String(customerName || '').trim();
    const scope = ['current','6m','12m','all'].includes(setting?.scope) ? setting.scope : 'current';
    const includeCancelled = !!setting?.includeCancelled;
    const requestId = ++mobileCustomerHistoryRequestSeq;
    if (scope === 'current' && !includeCancelled) {
        mobileCustomerHistorySettings.set(name, {scope, includeCancelled});
        mobileCustomerHistoryResults.delete(name);
        if (options.render !== false && mobileCustomerDetailName === name) renderMobileCustomerDetail(name);
        return (homeOrdersData || []).filter(order => String(order.customer_name || '').trim() === name);
    }
    if (options.loading !== false && mobileCustomerDetailName === name) {
        const indicator = document.querySelector('#mobileCustomerDetailContent .mobile-customer-history-loading');
        if (indicator) {
            indicator.hidden = false;
            indicator.textContent = mobileReportLanguageText('正在查询历史…','Consultando historial…');
        }
    }
    try {
        const url = `/tracking/api/customers/history-orders?customer_name=${encodeURIComponent(name)}&scope=${encodeURIComponent(scope)}&include_cancelled=${includeCancelled ? '1':'0'}`;
        const response = await fetch(url, {credentials:'same-origin', cache:'no-store'});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload?.success === false) throw new Error(payload?.error || `HTTP ${response.status}`);
        if (requestId !== mobileCustomerHistoryRequestSeq && options.ignoreStale !== false) return [];
        const orders = Array.isArray(payload.data) ? payload.data : [];
        mobileCustomerHistorySettings.set(name, {scope, includeCancelled});
        mobileCustomerHistoryResults.set(name, {scope, includeCancelled, orders, loadedAt:Date.now()});
        if (options.render !== false && mobileCustomerDetailName === name) renderMobileCustomerDetail(name);
        return orders;
    } catch (error) {
        if (typeof showToast === 'function') {
            showToast(mobileReportLanguageText('历史查询失败','Error al consultar historial'), String(error?.message || error), 'error');
        }
        return [];
    }
}

function mobileSetCustomerHistoryScope(customerName, scope) {
    const current = mobileCustomerHistorySetting(customerName);
    const next = {scope:['current','6m','12m','all'].includes(scope) ? scope : 'current', includeCancelled:!!current.includeCancelled};
    mobileCustomerHistorySettings.set(String(customerName || ''), next);
    if (next.scope === 'current' && !next.includeCancelled) {
        mobileCustomerHistoryResults.delete(String(customerName || ''));
        renderMobileCustomerDetail(customerName);
    } else {
        renderMobileCustomerDetail(customerName);
        mobileLoadCustomerHistory(customerName, next, {render:true});
    }
}

function mobileToggleCustomerCancelled(customerName, checked) {
    const current = mobileCustomerHistorySetting(customerName);
    const next = {scope:current.scope || 'current', includeCancelled:!!checked};
    mobileCustomerHistorySettings.set(String(customerName || ''), next);
    if (next.scope === 'current' && !next.includeCancelled) {
        mobileCustomerHistoryResults.delete(String(customerName || ''));
        renderMobileCustomerDetail(customerName);
    } else {
        renderMobileCustomerDetail(customerName);
        mobileLoadCustomerHistory(customerName, next, {render:true});
    }
}

function renderMobileCustomerDetail(customerName) {
    const content = document.getElementById('mobileCustomerDetailContent');
    if (!content) return;
    const historySetting = mobileCustomerHistorySetting(customerName);
    const orders = mobileCustomerViewOrders(customerName);
    const sorted = orders.slice().sort((a,b) => mobileTimestamp(b) - mobileTimestamp(a));
    let severity = 'none';
    sorted.forEach(order => {
        const light = mobileLightClass(order);
        if (mobileLightRank(light) > mobileLightRank(severity)) severity = light;
    });

    content.innerHTML = '';

    const navShell = document.createElement('div');
    navShell.className = 'mobile-profile-nav-shell';

    const back = document.createElement('button');
    back.type = 'button';
    back.className = 'mobile-profile-nav-back';
    back.setAttribute('aria-label', mobileT('mobile.back', '返回'));
    back.innerHTML = '<span aria-hidden="true">‹</span>';
    back.onclick = () => closeMobileCustomerDetail();

    const head = document.createElement('button');
    head.type = 'button';
    head.className = `mobile-profile-nav-main mobile-customer-header-topbar light-${severity}`;
    head.setAttribute('aria-label', customerName || mobileT('mobile.unassigned_customer', '未指定客户'));
    head.onclick = () => {
        const main = document.getElementById('mainContent');
        if (main) main.scrollTo({top:0, behavior:'smooth'});
    };

    const avatar = document.createElement('span');
    avatar.className = 'mobile-order-avatar';
    avatar.textContent = mobileCustomerInitial(customerName);

    const heading = document.createElement('span');
    heading.className = 'mobile-profile-nav-copy mobile-customer-heading';
    const strong = document.createElement('strong');
    strong.textContent = customerName || mobileT('mobile.unassigned_customer', '未指定客户');
    const small = document.createElement('small');
    small.textContent = mobileOrderCountText(orders.length);
    heading.append(strong, small);

    const link = document.createElement('span');
    link.className = 'mobile-profile-nav-link mobile-customer-header-link';
    link.setAttribute('aria-hidden', 'true');
    link.textContent = '›';

    head.append(avatar, heading, link);
    navShell.append(back, head);
    content.appendChild(navShell);

    if (document.body?.dataset.canViewUser === 'true') {
        const actions = document.createElement('div');
        actions.className = 'mobile-customer-actions mobile-customer-profile-actions';

        const report = document.createElement('button');
        report.type = 'button';
        report.className = 'mobile-primary-action';
        report.innerHTML = isCloudMode()
            ? `<span>${mobileT('mobile.report.request', '申请完整报告')}</span><small>${mobileT('mobile.report.queue_hint', 'TiDB 接通后启用')}</small>`
            : `<span>${mobileT('mobile.report.all_orders', '全部订单报告')}</span><small>${mobileT('mobile.report.all_orders_hint', '按当前查看范围生成')}</small>`;
        report.onclick = () => mobileCustomerReportAction(customerName);

        const token = document.createElement('button');
        token.type = 'button';
        token.className = 'mobile-secondary-action';
        token.innerHTML = isCloudMode()
            ? `<span>${mobileT('mobile.customer_link', '查询链接')}</span><small>${mobileT('mobile.customer_token', '客户 Token')}</small>`
            : `<span>${mobileReportLanguageText('临时查看','Vista temporal')}</span><small>${mobileReportLanguageText('30分 / 1小时 / 4小时','30 min / 1 h / 4 h')}</small>`;
        token.onclick = () => mobileCustomerLinkAction(customerName);

        actions.append(report, token);
        content.appendChild(actions);
    }

    const historyBox = document.createElement('div');
    historyBox.className = 'mobile-customer-history-box';
    const historyTop = document.createElement('div');
    historyTop.className = 'mobile-customer-history-top';
    const historyTitle = document.createElement('strong');
    historyTitle.textContent = mobileReportLanguageText('查看范围', 'Rango de historial');
    const historyTopActions = document.createElement('div');
    historyTopActions.className = 'mobile-customer-history-top-actions';
    const historyLoading = document.createElement('small');
    historyLoading.className = 'mobile-customer-history-loading';
    historyLoading.hidden = true;

    // Keep “include cancelled” beside the history title instead of consuming
    // a full extra row. This is an internal-view switch only; QR sharing still
    // has its own explicit permission choice.
    const cancelRow = document.createElement('label');
    cancelRow.className = 'mobile-customer-cancelled-toggle compact';
    cancelRow.title = mobileReportLanguageText('包含已取消订单（只影响内部查看）','Incluir pedidos cancelados (solo vista interna)');
    const cancelLabel = document.createElement('span');
    cancelLabel.className = 'mobile-customer-cancelled-compact-label';
    cancelLabel.textContent = mobileReportLanguageText('包含取消','Cancelados');
    const cancelInput = document.createElement('input');
    cancelInput.type = 'checkbox';
    cancelInput.checked = !!historySetting.includeCancelled;
    cancelInput.onchange = () => mobileToggleCustomerCancelled(customerName, cancelInput.checked);
    const cancelSwitch = document.createElement('span');
    cancelSwitch.className = 'mobile-customer-history-switch';
    cancelSwitch.innerHTML = '<i></i>';
    cancelRow.append(cancelLabel, cancelInput, cancelSwitch);
    historyTopActions.append(historyLoading, cancelRow);
    historyTop.append(historyTitle, historyTopActions);

    const historyChips = document.createElement('div');
    historyChips.className = 'mobile-chip-row mobile-customer-history-chips';
    [['current', mobileReportLanguageText('目前','Actual')], ['6m', mobileReportLanguageText('半年','6 meses')], ['12m', mobileReportLanguageText('一年','1 año')], ['all', mobileReportLanguageText('全部历史','Todo')]].forEach(([key,label]) => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = `mobile-chip mobile-history-chip${historySetting.scope === key ? ' active' : ''}`;
        chip.textContent = label;
        chip.onclick = () => mobileSetCustomerHistoryScope(customerName, key);
        historyChips.appendChild(chip);
    });

    historyBox.append(historyTop, historyChips);
    content.appendChild(historyBox);

    const sectionHead = document.createElement('div');
    sectionHead.className = 'mobile-customer-gallery-heading';
    sectionHead.innerHTML = `<strong>${mobileT('mobile.orders','订单')}</strong><span>${mobileCustomerHistoryLabel(historySetting.scope)} · ${mobileOrderCountText(sorted.length)}${historySetting.includeCancelled ? ` · ${mobileReportLanguageText('含取消','con cancelados')}` : ''}</span>`;
    content.appendChild(sectionHead);

    // Customer-level exact-status filter. Keep the currently selected status while
    // opening an order and returning with iPhone edge-swipe / browser Back.
    const statusCounts = new Map();
    sorted.forEach(order => {
        const key = String(order.current_status || '__order__');
        const item = statusCounts.get(key) || {
            key,
            label: order.current_status ? mobileStatusText(order.current_status) : mobileT('mobile.order','订单'),
            count: 0
        };
        item.count += 1;
        statusCounts.set(key, item);
    });

    const statusFilter = document.createElement('div');
    statusFilter.className = 'mobile-customer-status-filter';
    const statusLabel = document.createElement('div');
    statusLabel.className = 'mobile-customer-status-filter-label';
    statusLabel.textContent = mobileReportLanguageText('状态', 'Estado');
    const statusRow = document.createElement('div');
    statusRow.className = 'mobile-chip-row mobile-customer-status-chip-row';
    statusFilter.append(statusLabel, statusRow);
    content.appendChild(statusFilter);

    let selectedStatus = mobileCustomerStatusFilters.get(String(customerName || '')) || 'all';
    if (selectedStatus !== 'all' && !statusCounts.has(selectedStatus)) selectedStatus = 'all';
    mobileCustomerStatusFilters.set(String(customerName || ''), selectedStatus);

    const orderedStatuses = Array.from(statusCounts.values()).sort((a, b) => {
        const flow = (typeof STATUS_FLOW_ORDER !== 'undefined' && Array.isArray(STATUS_FLOW_ORDER)) ? STATUS_FLOW_ORDER : [];
        const ai = flow.indexOf(a.key), bi = flow.indexOf(b.key);
        if (ai >= 0 || bi >= 0) return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
        return String(a.label || '').localeCompare(String(b.label || ''), 'zh-CN');
    });

    function makeStatusChip(key, label, count) {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'mobile-chip mobile-customer-status-chip';
        chip.dataset.statusKey = key;
        const chipText = document.createElement('span');
        chipText.textContent = label;
        const chipCount = document.createElement('small');
        chipCount.textContent = String(count);
        chip.append(chipText, chipCount);
        statusRow.appendChild(chip);
        return chip;
    }

    makeStatusChip('all', mobileReportLanguageText('全部', 'Todos'), sorted.length);
    orderedStatuses.forEach(item => makeStatusChip(item.key, item.label, item.count));

    const orderGrid = document.createElement('div');
    orderGrid.className = 'mobile-customer-order-grid';
    sorted.forEach(order => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `mobile-customer-order-tile light-${mobileLightClass(order)}`;
        const orderKey = getHomeOrderKey(order);
        btn.dataset.orderKey = orderKey;
        btn.dataset.statusKey = String(order.current_status || '__order__');
        const viewedState = mobileCustomerOrderViewedState(customerName, orderKey);
        if (viewedState) btn.dataset.viewedState = viewedState;
        if (orderKey === mobileLastFocusOrderKey && String(customerName || '') === String(mobileLastFocusCustomerName || '')) {
            btn.classList.add('mobile-return-focus');
        }

        const cover = document.createElement('span');
        cover.className = 'mobile-customer-order-cover';

        const track = document.createElement('span');
        track.className = 'mobile-customer-order-carousel-track';
        track.addEventListener('scroll', () => mobileCustomerTileMediaScrolled(track), {passive:true});

        const fallback = document.createElement('span');
        fallback.className = 'mobile-customer-order-cover-fallback';
        fallback.innerHTML = `<small>${mobileT('mobile.no_image','暂无图片')}</small>`;

        const dots = document.createElement('span');
        dots.className = 'mobile-customer-order-image-dots';

        const imageCounter = document.createElement('span');
        imageCounter.className = 'mobile-customer-order-image-counter';
        imageCounter.hidden = true;

        const viewedBadge = document.createElement('span');
        viewedBadge.className = 'mobile-customer-order-viewed-badge';
        if (viewedState === 'last') {
            viewedBadge.classList.add('is-last');
            viewedBadge.textContent = mobileReportLanguageText('最後查看', 'Último visto');
        } else if (viewedState === 'viewed') {
            viewedBadge.classList.add('is-viewed');
            viewedBadge.textContent = mobileReportLanguageText('✓ 已查看', '✓ Visto');
        } else {
            viewedBadge.hidden = true;
        }

        cover.append(track, fallback, dots, imageCounter, viewedBadge);

        const body = document.createElement('span');
        body.className = 'mobile-customer-order-body';

        const note = document.createElement('span');
        note.className = 'mobile-customer-order-note';
        const noteText = String(order.notes || '').trim();
        if (noteText) {
            note.textContent = noteText;
            note.title = noteText;
        } else {
            note.hidden = true;
        }

        const meta = document.createElement('span');
        meta.className = 'mobile-customer-order-meta';

        const number = document.createElement('strong');
        number.className = 'mobile-customer-order-number';
        number.textContent = mobileOrderDisplayNumber(order);

        const status = document.createElement('small');
        status.className = `mobile-customer-order-status light-${mobileLightClass(order)}`;
        status.textContent = mobileStatusText(order.current_status);

        meta.append(number, status);
        body.append(note, meta);

        btn.append(cover, body);
        btn.onclick = () => {
            if (Date.now() < Number(btn.dataset.suppressOpenUntil || 0)) return;
            const main = document.getElementById('mainContent');
            mobileCustomerScrollTop = main?.scrollTop || 0;
            if (main) {
                const mainRect = main.getBoundingClientRect();
                const tileRect = btn.getBoundingClientRect();
                mobileCustomerFocusOffset = tileRect.top - mainRect.top;
            } else {
                mobileCustomerFocusOffset = null;
            }
            mobileLastFocusOrderKey = orderKey;
            mobileLastFocusCustomerName = customerName || '';
            markMobileCustomerOrderViewed(customerName, orderKey);

            // Persist the exact clicked card into the CURRENT customer history entry
            // before pushing the order detail. This is more reliable than globals on
            // iOS edge-swipe Back / bfcache restoration.
            try {
                const currentState = history.state || {};
                history.replaceState({
                    ...currentState,
                    __trackingMobile: true,
                    trackingMobileView: 'customer',
                    browseMode: 'customers',
                    customerName: customerName || '',
                    customerScrollTop: mobileCustomerScrollTop,
                    customerFocusKey: orderKey,
                    customerFocusOffset: mobileCustomerFocusOffset
                }, '', window.location.href);
            } catch (_) {}

            mobileOpenOrderDetail(orderKey, {returnView:'customer', customerName});
        };
        orderGrid.appendChild(btn);
    });
    content.appendChild(orderGrid);

    function applyCustomerStatusFilter(statusKey, options = {}) {
        const key = statusKey || 'all';
        mobileCustomerStatusFilters.set(String(customerName || ''), key);
        let visible = 0;
        orderGrid.querySelectorAll('.mobile-customer-order-tile').forEach(tile => {
            const show = key === 'all' || String(tile.dataset.statusKey || '') === key;
            tile.hidden = !show;
            if (show) visible += 1;
        });
        statusRow.querySelectorAll('.mobile-customer-status-chip').forEach(chip => {
            const active = String(chip.dataset.statusKey || '') === key;
            chip.classList.toggle('active', active);
            chip.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        const countNode = sectionHead.querySelector('span');
        if (countNode) countNode.textContent = mobileOrderCountText(visible);
        if (options.scrollIntoView) {
            const main = document.getElementById('mainContent');
            if (main) {
                const top = Math.max(0, statusFilter.offsetTop - 8);
                main.scrollTo({top, behavior:'smooth'});
            }
        }
    }

    statusRow.querySelectorAll('.mobile-customer-status-chip').forEach(chip => {
        chip.addEventListener('click', () => applyCustomerStatusFilter(chip.dataset.statusKey || 'all', {scrollIntoView:true}));
    });
    applyCustomerStatusFilter(selectedStatus);

    mobileHydrateCustomerOrderCovers(customerName, sorted);
}

function mobileReplaceBrowseHistoryState(mode = mobileBrowseMode, scrollTop = null) {
    if (!isMobileOrderViewport()) return;
    const nextMode = mode === 'customers' ? 'customers' : 'orders';
    const main = document.getElementById('mainContent');
    const resolvedScroll = Number.isFinite(Number(scrollTop)) ? Number(scrollTop) : Number(main?.scrollTop || 0);
    try {
        // IMPORTANT: do not spread a previous customer/order state here.  A stale
        // customer state underneath an order detail made iOS edge-swipe Back jump
        // into that customer's profile instead of the order list.
        history.replaceState({
            __trackingMobile: true,
            trackingMobileView: 'browse',
            browseMode: nextMode,
            browseScrollTop: Math.max(0, resolvedScroll || 0)
        }, '', window.location.href);
    } catch (_) {}
}

function mobilePushViewState(view, extra = {}) {
    if (!isMobileOrderViewport()) return;
    const state = {
        __trackingMobile: true,
        trackingMobileView: view,
        browseMode: mobileBrowseMode,
        ...extra
    };
    history.pushState(state, '', window.location.href);
}

function mobileRestoreCustomerGalleryPosition(customerDetail, focusKey = '', savedScrollTop = null, savedFocusOffset = null) {
    const main = document.getElementById('mainContent');
    if (!main) return;

    mobileCustomerRestoreTimers.forEach(timer => clearTimeout(timer));
    mobileCustomerRestoreTimers = [];

    const rawScrollTop = Number(savedScrollTop);
    const restoreTop = Number.isFinite(rawScrollTop) ? rawScrollTop : Number(mobileCustomerScrollTop || 0);
    const rawOffset = Number(savedFocusOffset);
    const desiredOffset = Number.isFinite(rawOffset) ? rawOffset : Number(mobileCustomerFocusOffset);

    if (Number.isFinite(restoreTop)) main.scrollTop = Math.max(0, restoreTop);

    function anchorOnce() {
        if (!focusKey || !customerDetail || !customerDetail.isConnected) return;
        const target = customerDetail.querySelector(`[data-order-key="${CSS.escape(focusKey)}"]`);
        if (!target) return;

        target.classList.add('mobile-return-focus');
        target.dataset.returnFocus = '1';
        if (!target.dataset.returnLabel) {
            target.dataset.returnLabel = window.getTrackingLanguage?.() === 'es' ? 'Recién visto' : '刚刚查看';
            setTimeout(() => {
                if (target?.isConnected) delete target.dataset.returnLabel;
            }, 2400);
        }
        if (Number.isFinite(desiredOffset)) {
            const mainRect = main.getBoundingClientRect();
            const targetRect = target.getBoundingClientRect();
            const delta = (targetRect.top - mainRect.top) - desiredOffset;
            if (Math.abs(delta) > 0.5) main.scrollTop += delta;
        }
        try { target.focus({preventScroll:true}); } catch (_) {}
    }

    // Re-apply the same tile anchor for a short period. Safari can finish its
    // history/bfcache layout after popstate, and PDF/image hydration can also land
    // between frames. Re-anchoring keeps the clicked order at the exact old spot.
    requestAnimationFrame(() => requestAnimationFrame(anchorOnce));
    [70, 180, 360, 650].forEach(delay => {
        mobileCustomerRestoreTimers.push(setTimeout(anchorOnce, delay));
    });
}

function openMobileCustomerDetail(customerName, options = {}) {
    const mainBefore = document.getElementById('mainContent');
    if (options.pushHistory !== false) mobileBrowseScrollTop = mainBefore?.scrollTop || 0;
    mobileCustomerDetailName = customerName;
    mobileBrowseMode = 'customers';
    mobileOrderDetailKey = '';
    mobileOrderDetailData = null;
    const ui = document.getElementById('mobileOrderUi');
    const detail = document.getElementById('mobileCustomerDetail');
    const orderDetail = document.getElementById('mobileOrderDetail');
    if (ui) {
        ui.classList.remove('order-detail-open');
        ui.classList.add('customer-detail-open');
    }
    if (detail) detail.hidden = false;
    if (orderDetail) orderDetail.hidden = true;
    renderMobileCustomerDetail(customerName);
    const historySetting = mobileCustomerHistorySetting(customerName);
    if (historySetting.scope !== 'current' || historySetting.includeCancelled) {
        mobileLoadCustomerHistory(customerName, historySetting, {render:true, loading:true});
    }
    if (options.pushHistory !== false) {
        mobilePushViewState('customer', {customerName});
    }
    const main = document.getElementById('mainContent');
    const focusKey = options.restoreFocusKey || ((mobileLastFocusCustomerName === customerName) ? mobileLastFocusOrderKey : '');
    if (options.restoreScroll) {
        mobileRestoreCustomerGalleryPosition(
            detail,
            focusKey,
            options.restoreScrollTop,
            options.restoreFocusOffset
        );
    } else if (main) {
        main.scrollTo({top:0, behavior: options.instant ? 'auto' : 'smooth'});
    }
}

function closeMobileCustomerDetail(options = {}) {
    if (options.useHistory !== false && history.state?.__trackingMobile && history.state?.trackingMobileView === 'customer') {
        history.back();
        return;
    }
    mobileCustomerDetailName = '';
    const ui = document.getElementById('mobileOrderUi');
    const detail = document.getElementById('mobileCustomerDetail');
    if (ui) ui.classList.remove('customer-detail-open');
    if (detail) detail.hidden = true;
    renderMobileExperience(true);
    requestAnimationFrame(() => {
        const main = document.getElementById('mainContent');
        if (main) main.scrollTop = mobileBrowseScrollTop || 0;
    });
}

function mobileValue(value) {
    const text = String(value ?? '').trim();
    return text || mobileT('mobile.no_value', '—');
}

function mobileDetailDate(value) {
    if (!value) return '';
    const raw = String(value).trim();
    const m = raw.match(/(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return raw;
    return window.getTrackingLanguage?.() === 'es' ? `${m[3]}/${m[2]}/${m[1]}` : `${m[2]}-${m[3]}`;
}

function mobileTimelineStageKey(status) {
    const group = typeof getStageGroup === 'function' ? getStageGroup(status || '') : '';
    if (group === 'draft') return 'draft';
    if (group === 'sampling') return 'sampling';
    if (group === 'production') return 'production';
    if (group === 'shipping' || group === 'completed') return 'shipping';
    return 'order';
}

function mobileBuildTimeline(order, detail) {
    const history = Array.isArray(detail?.history) ? detail.history : [];
    const stageDates = (order && typeof order.stage_dates === 'object' && order.stage_dates) ? order.stage_dates : {};
    const stages = [
        {key:'order', label:mobileT('mobile.timeline_order','下单'), date: order?.order_date || stageDates.order || stageDates.order_date || ''},
        {key:'draft', label:mobileT('mobile.timeline_draft','图稿'), date: order?.draft_date || stageDates.draft || stageDates.design || ''},
        {key:'sampling', label:mobileT('mobile.timeline_sample','打样'), date: stageDates.sampling || stageDates.sample || ''},
        {key:'production', label:mobileT('mobile.timeline_production','生产'), date: stageDates.production || ''},
        {key:'shipping', label:mobileT('mobile.timeline_shipping','出货'), date: order?.last_shipping_date || stageDates.shipping || stageDates.shipped || ''},
    ];
    history.forEach(item => {
        const stage = mobileTimelineStageKey(item.to_status);
        const target = stages.find(x => x.key === stage);
        if (target && !target.date && item.action_date) target.date = item.action_date;
    });
    const currentStage = mobileTimelineStageKey(detail?.current_status || order?.current_status || '');
    let currentIndex = stages.findIndex(x => x.key === currentStage);
    if (currentIndex < 0) currentIndex = 0;
    return stages.map((stage, index) => ({...stage, state:index < currentIndex ? 'done' : (index === currentIndex ? 'current' : 'future')}));
}

function mobileDetailItem(label, value, extraClass = '') {
    return `<div class="mobile-detail-item ${extraClass}"><span>${escapeReportQueueHtml(label)}</span><strong>${escapeReportQueueHtml(mobileValue(value))}</strong></div>`;
}

function mobileIsImageFile(file) {
    const type = String(file?.file_type || file?.mime_type || '').toLowerCase();
    const name = String(file?.file_name || file?.original_filename || '').toLowerCase();
    return type.startsWith('image') || /\.(jpg|jpeg|png|gif|webp|bmp|heic)$/i.test(name);
}

function mobileIsPdfFile(file) {
    const type = String(file?.mime_type || file?.file_type || '').toLowerCase().split(';', 1)[0].trim();
    const name = String(file?.file_name || file?.original_filename || '').toLowerCase();
    return type === 'application/pdf' || type === 'pdf' || name.endsWith('.pdf');
}

function mobileExpandVisualFiles(files, source, workflowNumber = '') {
    const result = [];
    const withVersion = (url, version, hasQuery = false) => {
        const v = String(version || '').trim();
        if (!v) return url;
        return `${url}${hasQuery ? '&' : '?'}v=${encodeURIComponent(v)}`;
    };
    (Array.isArray(files) ? files : []).forEach(file => {
        const version = String(file.media_version || '').trim();
        if (mobileIsImageFile(file)) {
            const rawFullUrl = source === 'workflow'
                ? `/tracking/api/workflows/${encodeURIComponent(workflowNumber)}/files/${file.id}/download`
                : `/tracking/api/orders/files/${file.id}/download`;
            const fullUrl = withVersion(rawFullUrl, version, false);
            result.push({
                ...file,
                source,
                media_type:'image',
                url: fullUrl,
                preview_url: withVersion(`${rawFullUrl}?preview=1`, version, true)
            });
            return;
        }
        if (!mobileIsPdfFile(file)) return;
        const pageCount = Math.max(0, Number(file.pdf_page_count || 0));
        if (!pageCount) return;
        const baseName = String(file.file_name || file.original_filename || 'PDF');
        for (let page = 1; page <= pageCount; page += 1) {
            const rawPageUrl = source === 'workflow'
                ? `/tracking/api/workflows/${encodeURIComponent(workflowNumber)}/files/${file.id}/pdf-page/${page}`
                : `/tracking/api/orders/files/${file.id}/pdf-page/${page}`;
            const rawDownloadUrl = source === 'workflow'
                ? `/tracking/api/workflows/${encodeURIComponent(workflowNumber)}/files/${file.id}/download`
                : `/tracking/api/orders/files/${file.id}/download`;
            result.push({
                ...file,
                source,
                media_type:'pdf_page',
                pdf_page_number:page,
                pdf_page_count:pageCount,
                original_pdf_name:baseName,
                file_name:`${baseName} · PDF ${page}/${pageCount}`,
                url: withVersion(rawPageUrl, version, false),
                preview_url: withVersion(`${rawPageUrl}?preview=1`, version, true),
                download_url: withVersion(rawDownloadUrl, version, false)
            });
        }
    });
    return result;
}

async function mobileFetchJson(url) {
    const response = await fetch(url, {credentials:'same-origin'});
    const payload = await response.json();
    if (!response.ok || payload?.success === false) throw new Error(payload?.error || `HTTP ${response.status}`);
    return payload;
}

async function mobileLoadOrderImages(order, detail = null) {
    if (isCloudMode()) return [];
    const orderNumber = String(detail?.order_number || order?.order_number || order?.orderNumber || '').trim();
    const workflowNumber = String(detail?.workflow_number || order?.workflow_number || order?.workflowNumber || '').trim();
    const tasks = [];
    if (orderNumber) {
        tasks.push(mobileFetchJson(`/tracking/api/orders/${encodeURIComponent(orderNumber)}/files?visual=1`)
            .then(payload => mobileExpandVisualFiles(payload?.data?.files || [], 'order'))
            .catch(() => []));
    }
    if (workflowNumber) {
        tasks.push(mobileFetchJson(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}/files?visual=1`)
            .then(payload => mobileExpandVisualFiles(payload?.data?.files || [], 'workflow', workflowNumber))
            .catch(() => []));
    }
    if (!tasks.length) return [];
    const groups = await Promise.all(tasks);
    const all = groups.flat();
    all.sort((a,b) => String(b.uploaded_at || '').localeCompare(String(a.uploaded_at || '')));
    return all;
}

function mobileOrderMediaHtml(images, loading = false) {
    // Mobile-only order detail media. Desktop/web rendering is intentionally untouched.
    if (loading) {
        return `<section class="mobile-order-media mobile-order-media-loading" aria-label="${mobileT('mobile.images','图片')}">
            <div class="mobile-order-media-skeleton"><span></span></div>
            <div class="mobile-order-media-loading-text">${mobileT('mobile.images_loading','正在载入图片…')}</div>
        </section>`;
    }
    if (!Array.isArray(images) || !images.length) return '';

    const firstName = String(images[0]?.file_name || images[0]?.original_filename || mobileT('mobile.image','图片'));
    const firstSource = images[0]?.media_type === 'pdf_page'
        ? mobileT('mobile.pdf_page','PDF 附件')
        : (images[0]?.source === 'workflow'
            ? mobileT('mobile.workflow_image','流程图片')
            : mobileT('mobile.order_image','订单图片'));

    const slides = images.map((img, index) => {
        const name = String(img.file_name || img.original_filename || mobileT('mobile.image','图片'));
        const source = img.media_type === 'pdf_page'
            ? mobileT('mobile.pdf_page','PDF 附件')
            : (img.source === 'workflow'
                ? mobileT('mobile.workflow_image','流程图片')
                : mobileT('mobile.order_image','订单图片'));
        const loadingAttr = index === 0 ? 'eager' : 'lazy';
        return `<button type="button"
                    class="mobile-order-media-slide"
                    data-media-index="${index}"
                    data-media-name="${escapeReportQueueHtml(name)}"
                    data-media-source="${escapeReportQueueHtml(source)}"
                    onclick="openMobileImageViewer(${index})"
                    aria-label="${escapeReportQueueHtml(name)}">
            <img src="${escapeReportQueueHtml(img.url)}"
                 alt="${escapeReportQueueHtml(name)}"
                 loading="${loadingAttr}">
        </button>`;
    }).join('');

    const dots = images.map((_, index) =>
        `<span class="mobile-order-media-dot${index === 0 ? ' active' : ''}" data-media-dot="${index}"></span>`
    ).join('');

    return `<section class="mobile-order-media xhs-mobile-order-media" aria-label="${mobileT('mobile.images','图片')}">
        <div class="mobile-order-media-stage">
            <div class="mobile-order-media-carousel" onscroll="mobileOrderMediaScrolled(this)">${slides}</div>
            <div class="mobile-order-media-overlay">
                <span class="mobile-order-media-counter">1 / ${images.length}</span>
            </div>
        </div>
        ${images.length > 1 ? `<div class="mobile-order-media-dots">${dots}</div>` : ''}
        <div class="mobile-order-media-meta">
            <span class="mobile-order-media-source current-source">${escapeReportQueueHtml(firstSource)}</span>
            <strong class="mobile-order-media-name current-name">${escapeReportQueueHtml(firstName)}</strong>
        </div>
    </section>`;
}

function mobileOrderMediaScrolled(carousel) {
    if (!carousel) return;
    const width = carousel.clientWidth || 1;
    const index = Math.max(0, Math.min(mobileImageItems.length - 1, Math.round(carousel.scrollLeft / width)));
    if (Number(carousel.dataset.mediaIndex || -1) === index) return;
    carousel.dataset.mediaIndex = String(index);

    const media = carousel.closest('.mobile-order-media');
    const counter = media?.querySelector('.mobile-order-media-counter');
    if (counter) counter.textContent = `${index + 1} / ${mobileImageItems.length}`;

    const currentImage = mobileImageItems[index] || null;
    const currentSource = media?.querySelector('.mobile-order-media-source.current-source');
    const currentName = media?.querySelector('.mobile-order-media-name.current-name');
    if (currentSource && currentImage) {
        currentSource.textContent = currentImage.media_type === 'pdf_page'
            ? mobileT('mobile.pdf_page','PDF 附件')
            : (currentImage.source === 'workflow'
                ? mobileT('mobile.workflow_image','流程图片')
                : mobileT('mobile.order_image','订单图片'));
    }
    if (currentName && currentImage) {
        currentName.textContent = currentImage.file_name || currentImage.original_filename || mobileT('mobile.image','图片');
    }

    media?.querySelectorAll('[data-media-dot]').forEach(dot => {
        dot.classList.toggle('active', Number(dot.dataset.mediaDot) === index);
    });
}

function openMobileImageViewer(index, options = {}) {
    if (!mobileImageItems.length) return;
    mobileImageIndex = Math.max(0, Math.min(Number(index) || 0, mobileImageItems.length - 1));
    const viewer = document.getElementById('mobileImageViewer');
    if (!viewer) return;
    viewer.classList.add('show');
    viewer.setAttribute('aria-hidden', 'false');
    document.body.classList.add('mobile-image-viewer-open');
    renderMobileImageViewer();
    if (options.pushHistory !== false && history.state?.trackingMobileView !== 'image') {
        mobilePushViewState('image', {
            orderKey: mobileOrderDetailKey,
            returnView: mobileOrderDetailReturn,
            customerName: mobileCustomerDetailName || '',
            imageIndex: mobileImageIndex
        });
    }
}

function renderMobileImageViewer() {
    const img = mobileImageItems[mobileImageIndex];
    if (!img) return;
    const image = document.getElementById('mobileImageViewerImg');
    const title = document.getElementById('mobileImageViewerTitle');
    const count = document.getElementById('mobileImageViewerCount');
    if (image) {
        image.src = img.url;
        image.alt = img.file_name || img.original_filename || '';
    }
    if (title) title.textContent = img.file_name || img.original_filename || mobileT('mobile.image','图片');
    if (count) count.textContent = `${mobileImageIndex + 1}/${mobileImageItems.length}`;
}

function mobileStepImage(delta) {
    if (mobileImageItems.length < 2) return;
    mobileImageIndex = (mobileImageIndex + Number(delta || 0) + mobileImageItems.length) % mobileImageItems.length;
    renderMobileImageViewer();
}

function closeMobileImageViewer(options = {}) {
    if (options.useHistory !== false && history.state?.__trackingMobile && history.state?.trackingMobileView === 'image') {
        history.back();
        return;
    }
    const viewer = document.getElementById('mobileImageViewer');
    if (viewer) {
        viewer.classList.remove('show');
        viewer.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('mobile-image-viewer-open');
}


function renderMobileOrderDetail(order, detail = null, loading = false, errorText = '') {
    if (detail) mobileOrderDetailData = detail;
    const content = document.getElementById('mobileOrderDetailContent');
    if (!content || !order) return;
    const light = mobileLightClass(detail || order);
    const customer = order.customer_name || detail?.customer_name || mobileT('mobile.unassigned_customer','未指定客户');
    const status = detail?.current_status || order.current_status || '';
    const product = detail?.production_type || detail?.product_name || order.production_type || order.product_name || '';
    const productCode = detail?.product_code || order.product_code || '';
    const quantity = detail?.quantity ?? order.quantity ?? '';
    const factory = detail?.factory || order.factory || '';
    const handler = detail?.handler_name || order.handler_name || order.handlerName || '';
    const notes = isCloudMode() ? '' : String(detail?.notes ?? order.notes ?? '').trim();
    const orderDate = detail?.order_date || order.order_date || '';
    const delivery = detail?.expected_delivery_date || order.expected_delivery_date || '';
    const statusDays = Number(order.status_days || detail?.status_days || 0);
    const timeline = mobileBuildTimeline(order, detail);
    const detailImages = Array.isArray(detail?._mobile_images) ? detail._mobile_images : [];
    const imagesLoading = !!detail?._mobile_images_loading;
    mobileImageItems = detailImages;
    const timelineHtml = timeline.map((step, index) => `
        <div class="mobile-timeline-step ${step.state}">
            <div class="mobile-timeline-track">
                ${index ? '<span class="mobile-timeline-line before"></span>' : ''}
                <span class="mobile-timeline-node"></span>
                ${index < timeline.length - 1 ? '<span class="mobile-timeline-line after"></span>' : ''}
            </div>
            <strong>${escapeReportQueueHtml(step.label)}</strong>
            <small>${escapeReportQueueHtml(mobileDetailDate(step.date) || '—')}</small>
        </div>`).join('');
    const footerAction = isCloudMode()
        ? `<div class="mobile-detail-readonly-note">${mobileT('mobile.readonly_hint','云端只读，只显示已同步资料')}</div>`
        : '';
    const mediaHtml = isCloudMode() ? '' : mobileOrderMediaHtml(detailImages, imagesLoading);
    content.innerHTML = `
        <div class="mobile-profile-nav-shell">
            <button type="button" class="mobile-profile-nav-back" onclick="closeMobileOrderDetail()" aria-label="${mobileT('mobile.back','返回')}">
                <span aria-hidden="true">‹</span>
            </button>
            <button type="button" class="mobile-profile-nav-main"
                    onclick="mobileOpenCustomerProfileFromOrder('${escapeReportQueueHtml(customer)}','${escapeReportQueueHtml(getHomeOrderKey(order))}')"
                    aria-label="${escapeReportQueueHtml(customer)}">
                <span class="mobile-order-avatar">${escapeReportQueueHtml(mobileCustomerInitial(customer))}</span>
                <span class="mobile-profile-nav-copy">
                    <strong>${escapeReportQueueHtml(customer)}</strong>
                </span>
                <span class="mobile-profile-nav-link" aria-hidden="true">›</span>
            </button>
        </div>
        ${mediaHtml}
        <section class="mobile-order-detail-hero mobile-order-summary-hero light-${light}">
            <div class="mobile-order-detail-title">
                <span class="mobile-order-detail-kicker">${mobileT('mobile.order_detail','订单详情')}</span>
                <strong>${escapeReportQueueHtml(mobileOrderDisplayNumber(order))}</strong>
                <small>${escapeReportQueueHtml(product || customer)}</small>
            </div>
            <span class="mobile-order-status-pill status-${light}">${escapeReportQueueHtml(mobileStatusText(status))}</span>
        </section>
        ${loading ? `<div class="mobile-detail-loading">${mobileT('mobile.loading_detail','正在载入订单详情…')}</div>` : ''}
        ${errorText ? `<div class="mobile-detail-error">${escapeReportQueueHtml(errorText)}</div>` : ''}
        ${notes ? `<section class="mobile-detail-section mobile-order-notes-section"><div class="mobile-detail-section-title">${mobileT('mobile.notes','备注')}</div><div class="mobile-order-notes-full">${escapeReportQueueHtml(notes)}</div></section>` : ''}
        <section class="mobile-detail-section mobile-timeline-priority-section"><div class="mobile-detail-section-title">${mobileT('mobile.timeline','进度时间轴')}</div><div class="mobile-compact-timeline">${timelineHtml}</div></section>
        <section class="mobile-detail-section mobile-order-info-section"><div class="mobile-detail-section-title">${mobileT('mobile.order_info','订单资料')}</div><div class="mobile-detail-grid">
            ${mobileDetailItem(mobileT('mobile.current_status','当前状态'), mobileStatusText(status), 'wide')}
            ${mobileDetailItem(mobileT('mobile.product','产品'), product)}
            ${mobileDetailItem(mobileT('mobile.product_code','编号'), productCode)}
            ${mobileDetailItem(mobileT('mobile.quantity','数量'), quantity)}
            ${mobileDetailItem(mobileT('mobile.factory','工厂'), factory)}
            ${mobileDetailItem(mobileT('mobile.order_date','订单日期'), mobileDetailDate(orderDate))}
            ${mobileDetailItem(mobileT('mobile.delivery_date','预计交期'), mobileDetailDate(delivery))}
            ${mobileDetailItem(mobileT('mobile.status_days','当前阶段'), `${statusDays} ${mobileT('mobile.days','天')}`)}
            ${mobileDetailItem(mobileT('mobile.salesperson','业务员'), handler)}
        </div></section>
        ${footerAction}
        <button type="button" class="mobile-single-report-float" onclick="mobileSingleOrderReportAction('${escapeReportQueueHtml(getHomeOrderKey(order))}')" aria-label="${mobileT('mobile.report.single_action','生成 / 分享本单 PDF')}">
            <span aria-hidden="true">↗</span>
            <strong>${window.getTrackingLanguage?.() === 'es' ? 'PDF pedido' : '本单 PDF'}</strong>
        </button>`;
}

async function mobileLoadOrderDetail(order) {
    const workflowNumber = String(order.workflow_number || order.workflowNumber || '').trim();
    let detail = null;
    if (!isCloudMode()) {
        detail = {...order, _mobile_images_loading:true};
        renderMobileOrderDetail(order, detail, !!workflowNumber);
    } else {
        renderMobileOrderDetail(order, null, false);
        return;
    }

    try {
        if (workflowNumber) {
            const response = await fetch(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}`, {credentials:'same-origin'});
            const payload = await response.json();
            if (!response.ok || !payload.success) throw new Error(payload.error || mobileT('mobile.detail_load_failed','订单详情载入失败'));
            detail = {...(payload.data || {}), _mobile_images_loading:true};
            renderMobileOrderDetail(order, detail, false);
        }
        const images = await mobileLoadOrderImages(order, detail || order);
        detail = {...(detail || order), _mobile_images:images, _mobile_images_loading:false};
        renderMobileOrderDetail(order, detail, false);
    } catch (error) {
        console.warn('[mobile detail] load failed', error);
        detail = {...(detail || order), _mobile_images:[], _mobile_images_loading:false};
        renderMobileOrderDetail(order, detail, false, error.message || mobileT('mobile.detail_load_failed','订单详情载入失败'));
    }
}

function mobileFocusOrderDetailMedia(orderKey) {
    const main = document.getElementById('mainContent');
    const detail = document.getElementById('mobileOrderDetail');
    if (!main || !detail || detail.hidden) return;

    const expectedKey = String(orderKey || '');
    const focusOnce = () => {
        if (expectedKey && String(mobileOrderDetailKey || '') !== expectedKey) return;
        if (detail.hidden || !detail.isConnected) return;

        // 进入单张订单时，直接把第一张图片（或图片载入骨架）顶到内容区最上方。
        // 不再停在客户导航条顶部，避免用户还要手动向上滑一次。
        const target = detail.querySelector('.mobile-order-media') || detail;
        const mainRect = main.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const top = Math.max(0, main.scrollTop + targetRect.top - mainRect.top);
        main.scrollTo({top, behavior:'auto'});
    };

    // iOS Safari 在 hidden 切换 + innerHTML 重绘后的第一帧可能还没完成布局，
    // 连续等两帧再定位，确保媒体顶部位置准确。
    requestAnimationFrame(() => requestAnimationFrame(focusOnce));
}

function mobileOpenOrderDetail(key, options = {}) {
    const order = (homeOrdersData || []).find(item => getHomeOrderKey(item) === key);
    if (!order) return;
    const returnView = options.returnView || (mobileCustomerDetailName ? 'customer' : 'orders');
    const returnCustomer = options.customerName !== undefined ? options.customerName : mobileCustomerDetailName;
    mobileOrderDetailKey = key;
    mobileOrderDetailData = null;
    mobileOrderDetailReturn = returnView;
    if (returnView === 'customer' && returnCustomer) mobileCustomerDetailName = returnCustomer;
    const ui = document.getElementById('mobileOrderUi');
    const detail = document.getElementById('mobileOrderDetail');
    const customerDetail = document.getElementById('mobileCustomerDetail');
    if (ui) {
        ui.classList.remove('customer-detail-open');
        ui.classList.add('order-detail-open');
    }
    if (detail) detail.hidden = false;
    if (customerDetail) customerDetail.hidden = true;
    if (options.pushHistory !== false) {
        mobilePushViewState('order', {
            orderKey: key,
            returnView: mobileOrderDetailReturn,
            customerName: returnCustomer || ''
        });
    }
    mobileLoadOrderDetail(order);
    mobileFocusOrderDetailMedia(key);
}

function closeMobileOrderDetail(options = {}) {
    if (options.useHistory !== false && history.state?.__trackingMobile && history.state?.trackingMobileView === 'order') {
        history.back();
        return;
    }
    mobileOrderDetailKey = '';
    mobileOrderDetailData = null;
    const ui = document.getElementById('mobileOrderUi');
    const detail = document.getElementById('mobileOrderDetail');
    const customerDetail = document.getElementById('mobileCustomerDetail');
    if (ui) ui.classList.remove('order-detail-open');
    if (detail) detail.hidden = true;
    if (mobileOrderDetailReturn === 'customer' && mobileCustomerDetailName) {
        if (ui) ui.classList.add('customer-detail-open');
        if (customerDetail) customerDetail.hidden = false;
        renderMobileCustomerDetail(mobileCustomerDetailName);
        mobileRestoreCustomerGalleryPosition(customerDetail, mobileLastFocusOrderKey || '');
    } else {
        renderMobileExperience(true);
        requestAnimationFrame(() => {
            const main = document.getElementById('mainContent');
            if (main) main.scrollTop = mobileBrowseScrollTop || 0;
        });
    }
}

function applyMobileHistoryState(state) {
    if (!isMobileOrderViewport()) return false;
    const mobileState = state && state.__trackingMobile ? state : null;
    closeMobileImageViewer({useHistory:false});

    if (mobileState?.browseMode === 'customers' || mobileState?.browseMode === 'orders') {
        mobileBrowseMode = mobileState.browseMode;
    }


    if (mobileState?.trackingMobileView === 'browse') {
        mobileOrderDetailKey = '';
        mobileOrderDetailData = null;
        mobileCustomerDetailName = '';
        mobileOrderDetailReturn = 'orders';
        mobileBrowseMode = mobileState.browseMode === 'customers' ? 'customers' : 'orders';
        renderMobileExperience(true);
        const savedTop = Number(mobileState.browseScrollTop);
        requestAnimationFrame(() => {
            const main = document.getElementById('mainContent');
            if (main && Number.isFinite(savedTop)) main.scrollTop = Math.max(0, savedTop);
            if (mobileBrowseMode === 'orders' && mobileLastFocusOrderKey && mobileLastFocusCustomerName === '') {
                const target = document.querySelector(`#mobileOrdersList [data-order-key="${CSS.escape(mobileLastFocusOrderKey)}"]`);
                if (target) target.classList.add('mobile-return-focus');
            }
        });
        return true;
    }

    if (mobileState?.trackingMobileView === 'image' && mobileState.orderKey) {
        mobileCustomerDetailName = mobileState.returnView === 'customer' ? (mobileState.customerName || '') : '';
        mobileOpenOrderDetail(mobileState.orderKey, {
            pushHistory: false,
            instant: true,
            returnView: mobileState.returnView || 'orders',
            customerName: mobileState.customerName || ''
        });
        requestAnimationFrame(() => openMobileImageViewer(Number(mobileState.imageIndex || 0), {pushHistory:false}));
        return true;
    }

    if (mobileState?.trackingMobileView === 'order' && mobileState.orderKey) {
        mobileCustomerDetailName = mobileState.returnView === 'customer' ? (mobileState.customerName || '') : '';
        mobileOpenOrderDetail(mobileState.orderKey, {
            pushHistory: false,
            instant: true,
            returnView: mobileState.returnView || 'orders',
            customerName: mobileState.customerName || ''
        });
        return true;
    }

    if (mobileState?.trackingMobileView === 'customer' && mobileState.customerName) {
        mobileOrderDetailKey = '';
        mobileOrderDetailData = null;
        mobileOrderDetailReturn = 'orders';

        const savedFocusKey = String(mobileState.customerFocusKey || '');
        const savedScrollTop = Number(mobileState.customerScrollTop);
        const savedFocusOffset = Number(mobileState.customerFocusOffset);
        if (savedFocusKey) {
            mobileLastFocusOrderKey = savedFocusKey;
            mobileLastFocusCustomerName = mobileState.customerName;
        }
        if (Number.isFinite(savedScrollTop)) mobileCustomerScrollTop = savedScrollTop;
        if (Number.isFinite(savedFocusOffset)) mobileCustomerFocusOffset = savedFocusOffset;

        openMobileCustomerDetail(mobileState.customerName, {
            pushHistory: false,
            instant: true,
            restoreScroll: true,
            restoreFocusKey: savedFocusKey || (mobileLastFocusCustomerName === mobileState.customerName ? mobileLastFocusOrderKey : ''),
            restoreScrollTop: Number.isFinite(savedScrollTop) ? savedScrollTop : null,
            restoreFocusOffset: Number.isFinite(savedFocusOffset) ? savedFocusOffset : null
        });
        return true;
    }

    // 回到本页原始 history state：关闭手机内页，而不是让浏览器离开 order_tracking。
    if (mobileOrderDetailKey || mobileCustomerDetailName) {
        mobileOrderDetailKey = '';
        mobileOrderDetailData = null;
        mobileCustomerDetailName = '';
        mobileOrderDetailReturn = 'orders';
        const ui = document.getElementById('mobileOrderUi');
        const orderDetail = document.getElementById('mobileOrderDetail');
        const customerDetail = document.getElementById('mobileCustomerDetail');
        if (ui) ui.classList.remove('order-detail-open', 'customer-detail-open');
        if (orderDetail) orderDetail.hidden = true;
        if (customerDetail) customerDetail.hidden = true;
        renderMobileExperience(true);
        requestAnimationFrame(() => {
            const main = document.getElementById('mainContent');
            if (main) main.scrollTop = mobileBrowseScrollTop || 0;
            if (mobileLastFocusOrderKey && mobileLastFocusCustomerName === '') {
                const target = document.querySelector(`#mobileOrdersList [data-order-key="${CSS.escape(mobileLastFocusOrderKey)}"]`);
                if (target) {
                    target.classList.add('mobile-return-focus');
                    target.scrollIntoView({block:'nearest', behavior:'auto'});
                }
            }
        });
        return true;
    }
    return false;
}

window.handleTrackingPopState = function(event) {
    return applyMobileHistoryState(event?.state || null);
};

function openMobileReportSheet(titleText, subtitleText = '') {
    const sheet = document.getElementById('mobileReportSheet');
    const backdrop = document.getElementById('mobileReportSheetBackdrop');
    const title = document.getElementById('mobileReportSheetTitle');
    const subtitle = document.getElementById('mobileReportSheetSubtitle');
    if (title) title.textContent = titleText || mobileT('mobile.report.title','客户完整报告');
    if (subtitle) subtitle.textContent = subtitleText || mobileT('mobile.report.subtitle','报告会在本地服务器生成');
    if (sheet) {
        sheet.classList.add('show');
        sheet.setAttribute('aria-hidden', 'false');
    }
    if (backdrop) backdrop.classList.add('show');
}

function closeMobileReportSheet() {
    if (mobileReportPollTimer) {
        clearTimeout(mobileReportPollTimer);
        mobileReportPollTimer = null;
    }
    const sheet = document.getElementById('mobileReportSheet');
    const backdrop = document.getElementById('mobileReportSheetBackdrop');
    if (sheet) {
        sheet.classList.remove('show');
        sheet.setAttribute('aria-hidden', 'true');
    }
    if (backdrop) backdrop.classList.remove('show');
}


function mobileReportLanguageText(zh, es) {
    return window.getTrackingLanguage?.() === 'es' ? es : zh;
}

function mobileLoadReportOptions() {
    const prefs = typeof loadCustomerReportPreferences === 'function' ? loadCustomerReportPreferences() : {};
    return {
        format: 'pdf',
        language: ['zh_cn', 'es'].includes(prefs.language) ? prefs.language : 'zh_cn',
        image_source: ['both', 'order', 'workflow', 'none'].includes(prefs.image_source) ? prefs.image_source : 'both',
        image_count: ['representative', 'all'].includes(prefs.image_count) ? prefs.image_count : 'all',
        image_order: ['order_first', 'workflow_first', 'newest'].includes(prefs.image_order) ? prefs.image_order : 'order_first',
        pdf_attachment_mode: ['pages', 'skip'].includes(prefs.pdf_attachment_mode) ? prefs.pdf_attachment_mode : 'pages'
    };
}

function mobileSaveReportOptions(options) {
    try {
        const existing = typeof loadCustomerReportPreferences === 'function' ? loadCustomerReportPreferences() : {};
        const merged = {...existing, ...options, format:'pdf'};
        localStorage.setItem('order_tracking_customer_report_preferences_v1', JSON.stringify(merged));
        if (typeof customerReportOptions === 'object' && customerReportOptions) {
            Object.assign(customerReportOptions, merged);
        }
    } catch (error) {
        console.warn('[mobile report] save preferences failed', error);
    }
}

function mobileReportOptionButton(group, value, label) {
    const active = mobileReportDraftOptions && mobileReportDraftOptions[group] === value ? ' active' : '';
    return `<button type="button" class="mobile-report-choice${active}" data-mobile-report-group="${group}" data-mobile-report-value="${value}" onclick="mobileSetReportOption('${group}','${value}')">${label}</button>`;
}

function mobileRenderReportOptions() {
    if (!mobileReportRequestContext) return;
    if (!mobileReportDraftOptions) mobileReportDraftOptions = mobileLoadReportOptions();

    const noImages = mobileReportDraftOptions.image_source === 'none';
    const html = `
        <div class="mobile-report-config">

            <section class="mobile-report-config-section">
                <div class="mobile-report-config-label">${mobileReportLanguageText('报告语言','Idioma del informe')}</div>
                <div class="mobile-report-choice-grid two">
                    ${mobileReportOptionButton('language','zh_cn','简体中文')}
                    ${mobileReportOptionButton('language','es','Español')}
                </div>
            </section>

            <section class="mobile-report-config-section">
                <div class="mobile-report-config-label">${mobileReportLanguageText('图片来源','Origen de imágenes')}</div>
                <div class="mobile-report-choice-list">
                    ${mobileReportOptionButton('image_source','both',mobileReportLanguageText('主管参考图 + 业务员附件图','Imagen principal + imágenes del vendedor'))}
                    ${mobileReportOptionButton('image_source','order',mobileReportLanguageText('只要主管参考图','Solo imagen principal'))}
                    ${mobileReportOptionButton('image_source','workflow',mobileReportLanguageText('只要业务员附件图','Solo imágenes del vendedor'))}
                    ${mobileReportOptionButton('image_source','none',mobileReportLanguageText('不要图片','Sin imágenes'))}
                </div>
            </section>

            <section class="mobile-report-config-section${noImages ? ' mobile-report-disabled-section' : ''}">
                <div class="mobile-report-config-label">${mobileReportLanguageText('图片数量','Cantidad de imágenes')}</div>
                <div class="mobile-report-choice-grid two">
                    ${mobileReportOptionButton('image_count','representative',mobileReportLanguageText('每笔 1 张代表图','1 imagen por pedido'))}
                    ${mobileReportOptionButton('image_count','all',mobileReportLanguageText('全部图片','Todas las imágenes'))}
                </div>
            </section>

            <section class="mobile-report-config-section${noImages ? ' mobile-report-disabled-section' : ''}">
                <div class="mobile-report-config-label">${mobileReportLanguageText('图片顺序','Orden de imágenes')}</div>
                <div class="mobile-report-choice-list">
                    ${mobileReportOptionButton('image_order','order_first',mobileReportLanguageText('主管参考图优先','Imagen principal primero'))}
                    ${mobileReportOptionButton('image_order','workflow_first',mobileReportLanguageText('业务员附件图优先','Imágenes del vendedor primero'))}
                    ${mobileReportOptionButton('image_order','newest',mobileReportLanguageText('依上传时间（最新优先）','Más recientes primero'))}
                </div>
            </section>

            <section class="mobile-report-config-section${noImages ? ' mobile-report-disabled-section' : ''}">
                <div class="mobile-report-config-label">${mobileReportLanguageText('PDF 附件','Adjuntos PDF')}</div>
                <div class="mobile-report-choice-grid two">
                    ${mobileReportOptionButton('pdf_attachment_mode','pages',mobileReportLanguageText('逐页拆成图片','Convertir páginas'))}
                    ${mobileReportOptionButton('pdf_attachment_mode','skip',mobileReportLanguageText('不加入 PDF','Omitir PDF'))}
                </div>
                <div class="mobile-report-config-inline-hint">${mobileReportLanguageText('有 PDF 附件时才生效；原始 PDF 不会修改。','Solo aplica si hay PDF; el archivo original no se modifica.')}</div>
            </section>

            <div class="mobile-report-config-actions">
                <button type="button" class="mobile-report-config-cancel" onclick="closeMobileReportSheet()">${mobileReportLanguageText('取消','Cancelar')}</button>
                <button type="button" class="mobile-report-config-submit" onclick="mobileSubmitConfiguredReport()">${mobileReportLanguageText('加入生成队列','Agregar a la cola')}</button>
            </div>
            <div class="mobile-report-config-note">${mobileReportLanguageText('加入后可以离开此页面继续工作，报告完成时会通知你。','Después de agregarlo puedes seguir usando el sistema; te avisaremos cuando el informe esté listo.')}</div>
        </div>`;
    renderMobileReportStatus(html);
}

function mobileSetReportOption(group, value) {
    if (!mobileReportDraftOptions) mobileReportDraftOptions = mobileLoadReportOptions();
    const allowed = {
        format:['pdf'],
        language:['zh_cn','es'],
        image_source:['both','order','workflow','none'],
        image_count:['representative','all'],
        image_order:['order_first','workflow_first','newest'],
        pdf_attachment_mode:['pages','skip']
    };
    if (!allowed[group] || !allowed[group].includes(value)) return;
    mobileReportDraftOptions[group] = value;
    mobileRenderReportOptions();
}

function mobileOpenReportConfigurator(context) {
    mobileReportRequestContext = context;
    mobileReportDraftOptions = mobileLoadReportOptions();
    openMobileReportSheet(context.title, context.subtitle);
    mobileRenderReportOptions();
}

async function mobileSubmitConfiguredReport() {
    const context = mobileReportRequestContext;
    if (!context || !Array.isArray(context.items) || !context.items.length) return;
    const options = mobileReportDraftOptions || mobileLoadReportOptions();
    const submit = document.querySelector('#mobileReportBody .mobile-report-config-submit');
    if (submit) {
        submit.disabled = true;
        submit.textContent = mobileReportLanguageText('正在加入队列…','Agregando…');
    }
    const payload = {
        items: context.items,
        // 手机客户完整报告固定为 PDF；不再允许旧 localStorage / 旧 HTML 选项影响请求。
        format:'pdf',
        language:options.language,
        image_source:options.image_source,
        image_count:options.image_count,
        image_order:options.image_order,
        pdf_attachment_mode:options.pdf_attachment_mode || 'pages'
    };
    mobileSaveReportOptions(options);
    try {
        const response = await fetch('/tracking/api/customer-reports/jobs', {
            method:'POST',
            credentials:'same-origin',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(payload)
        });
        let data = null;
        try { data = await response.json(); } catch (_) { data = null; }
        if (!response.ok || !data?.success || !data?.job?.id) {
            throw new Error(data?.error || mobileReportLanguageText('加入报告队列失败','No se pudo agregar a la cola'));
        }

        closeMobileReportSheet();
        mergeCustomerReportJob(data.job);
        customerReportQueueFabDismissed = false;
        renderCustomerReportQueue();
        ensureCustomerReportQueuePolling(true);
        const label = context.label || (Array.isArray(data.job.customers) && data.job.customers[0]) || '';
        if (typeof showToast === 'function') {
            if (data.deduplicated) {
                showToast(
                    mobileReportLanguageText('任务已在队列中','La tarea ya está en la cola'),
                    `${label}${label ? ' · ' : ''}${mobileReportLanguageText('相同报告正在生成，不会重复建立','el mismo informe ya se está generando')}`,
                    'info'
                );
            } else {
                showToast(
                    mobileReportLanguageText('已加入报告队列','Agregado a la cola'),
                    `${label}${label ? ' · ' : ''}${mobileReportLanguageText('正在后台生成，可以继续做其他事情','se está generando en segundo plano; puedes seguir usando el sistema')}`,
                    'success'
                );
            }
        }
        mobileReportRequestContext = null;
        mobileReportDraftOptions = null;
    } catch (error) {
        if (submit) {
            submit.disabled = false;
            submit.textContent = mobileReportLanguageText('加入生成队列','Agregar a la cola');
        }
        if (typeof showToast === 'function') {
            showToast(
                mobileReportLanguageText('错误','Error'),
                error.message || mobileReportLanguageText('加入报告队列失败','No se pudo agregar a la cola'),
                'error'
            );
        }
    }
}

function mobileReportPayloadForCustomer(customerName) {
    const rows = mobileCustomerViewOrders(customerName);
    const selection = buildCustomerReportSelection(rows);
    return {
        items: selection.map(x => ({workflow_number:x.workflow_number, order_number:x.order_number}))
    };
}

function renderMobileReportStatus(html) {
    const body = document.getElementById('mobileReportBody');
    if (body) body.innerHTML = html;
}

async function mobileShareReportFile(file) {
    const openUrl = customerReportInlineUrl(file);
    try {
        const response = await fetch(file.url, {credentials:'same-origin'});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const blob = await response.blob();
        const fallbackType = isCustomerReportPdf(file) ? 'application/pdf' : 'application/octet-stream';
        const shareFile = new File([blob], file.name || 'report.bin', {type:blob.type || fallbackType});
        if (navigator.share && (!navigator.canShare || navigator.canShare({files:[shareFile]}))) {
            await navigator.share({files:[shareFile], title:file.name || 'PDF'});
            return;
        }
    } catch (error) {
        console.warn('[mobile report] share failed/fallback', error);
    }
    window.open(openUrl, '_blank', 'noopener');
}

function mobileShareQueuedReport(jobId, fileIndex) {
    const job = (customerReportJobs || []).find(item => String(item.id || '') === String(jobId || ''));
    const file = job && Array.isArray(job.files) ? job.files[Number(fileIndex)] : null;
    if (file) mobileShareReportFile(file);
}

function mobileRenderCompletedReport(job) {
    const files = Array.isArray(job?.files) ? job.files : [];
    if (!files.length) {
        renderMobileReportStatus(`<div class="mobile-report-error">${mobileT('mobile.report.no_file','报告完成，但没有可用档案')}</div>`);
        return;
    }
    const fileRows = files.map((file, index) => {
        const inlineUrl = customerReportInlineUrl(file);
        const openLabel = mobileT('mobile.report.open_pdf','打开 PDF');
        const shareLabel = mobileT('mobile.report.share','分享 PDF');
        const fallbackName = `PDF ${index+1}`;
        return `<div class="mobile-report-file">
            <div><strong>${escapeReportQueueHtml(file.name || fallbackName)}</strong><small>${escapeReportQueueHtml(formatCustomerReportBytes(file.size || 0))}</small></div>
            <div class="mobile-report-actions">
                <button type="button" class="mobile-report-share-primary" onclick="mobileShareReportFile(mobileCurrentReportFiles[${index}])">${shareLabel}</button>
                <a href="${escapeReportQueueHtml(inlineUrl)}" target="_blank" rel="noopener">${openLabel}</a>
                <a href="${escapeReportQueueHtml(file.url || '#')}" download>${mobileT('mobile.report.download','下载')}</a>
            </div>
        </div>`;
    }).join('');
    mobileCurrentReportFiles = files;
    renderMobileReportStatus(`<div class="mobile-report-success">${mobileReportLanguageText('报告已生成','Informe listo')}</div>${fileRows}`);
}

async function mobilePollReportJob(jobId) {
    // Legacy helper retained for compatibility. New mobile report requests use
    // the shared background report queue so the user does not need to wait here.
    try {
        const response = await fetch(`/tracking/api/customer-reports/jobs/${encodeURIComponent(jobId)}`, {credentials:'same-origin'});
        const payload = await response.json();
        if (!response.ok || !payload.success || !payload.job) throw new Error(payload.error || mobileT('mobile.report.failed','报告生成失败'));
        const job = payload.job;
        if (job.status === 'completed') {
            mobileReportPollTimer = null;
            mobileRenderCompletedReport(job);
            return;
        }
        if (job.status === 'failed') {
            mobileReportPollTimer = null;
            renderMobileReportStatus(`<div class="mobile-report-error">${escapeReportQueueHtml(job.error || mobileT('mobile.report.failed','报告生成失败'))}</div>`);
            return;
        }
        mobileReportPollTimer = setTimeout(() => mobilePollReportJob(jobId), 1500);
    } catch (error) {
        mobileReportPollTimer = null;
    }
}

async function mobileCustomerReportAction(customerName) {
    if (isCloudMode()) {
        if (typeof showToast === 'function') {
            showToast(mobileT('mobile.report_cloud_title', '云端报告'), mobileT('mobile.report_cloud_pending', '介面已预留；TiDB report_requests 接通后，这里会加入待处理队列。目前不会假装已送出。'), 'info');
        }
        return;
    }
    const selection = mobileReportPayloadForCustomer(customerName);
    if (!selection.items.length) {
        if (typeof showToast === 'function') showToast(mobileT('mobile.detail_missing_title','提示'), mobileT('mobile.report.no_orders','此客户目前没有可生成报告的订单'), 'info');
        return;
    }
    mobileOpenReportConfigurator({
        title:`${customerName} · ${mobileReportLanguageText('客户完整报告','Informe completo del cliente')}`,
        subtitle:mobileReportLanguageText('先选择语言与图片规则，再加入后台队列','Elige idioma e imágenes antes de agregar a la cola'),
        label:customerName,
        items:selection.items
    });
}

function mobileReportPayloadForOrder(order, detail = null) {
    const source = {...(order || {}), ...(detail || {})};
    const selection = buildCustomerReportSelection([source]);
    return {
        items: selection.map(x => ({workflow_number:x.workflow_number, order_number:x.order_number}))
    };
}

async function mobileSingleOrderReportAction(orderKey) {
    const order = (homeOrdersData || []).find(item => getHomeOrderKey(item) === String(orderKey || ''));
    if (!order) {
        if (typeof showToast === 'function') showToast(mobileT('mobile.detail_missing_title','提示'), mobileT('mobile.detail_missing','找不到此笔订单'), 'info');
        return;
    }
    if (isCloudMode()) {
        if (typeof showToast === 'function') {
            showToast(mobileT('mobile.report_cloud_title','云端报告'), mobileT('mobile.report_cloud_pending','TiDB report_requests 接通后，这里会申请本单 PDF。目前不会假装已送出。'), 'info');
        }
        return;
    }
    const selection = mobileReportPayloadForOrder(order, mobileOrderDetailData);
    if (!selection.items.length) {
        if (typeof showToast === 'function') showToast(mobileT('mobile.detail_missing_title','提示'), mobileT('mobile.report.no_orders','此笔订单目前无法生成报告'), 'info');
        return;
    }
    const number = mobileOrderDisplayNumber(order);
    mobileOpenReportConfigurator({
        title:`${number} · ${mobileReportLanguageText('本单报告','Informe de este pedido')}`,
        subtitle:mobileReportLanguageText('只生成当前订单；先选择语言与图片规则','Solo este pedido; elige idioma e imágenes'),
        label:number,
        items:selection.items
    });
}

function mobileGuestLinkText(zh, es) {
    return window.getTrackingLanguage?.() === 'es' ? es : zh;
}

function mobileGuestLinkEnsureModal() {
    let modal = document.getElementById('mobileGuestLinkModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'mobileGuestLinkModal';
    modal.className = 'mobile-guest-link-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
        <div class="mobile-guest-link-backdrop" onclick="mobileCloseGuestLinkModal()"></div>
        <section class="mobile-guest-link-sheet" role="dialog" aria-modal="true" aria-labelledby="mobileGuestLinkTitle">
            <div class="mobile-guest-link-handle"></div>
            <div class="mobile-guest-link-head">
                <div>
                    <strong id="mobileGuestLinkTitle"></strong>
                    <small id="mobileGuestLinkCustomer"></small>
                </div>
                <button type="button" class="mobile-guest-link-close" onclick="mobileCloseGuestLinkModal()" aria-label="Close">×</button>
            </div>
            <div class="mobile-guest-link-duration-label"></div>
            <div class="mobile-guest-link-duration">
                <button type="button" data-guest-minutes="30">30 min</button>
                <button type="button" data-guest-minutes="60" class="active">1 h</button>
                <button type="button" data-guest-minutes="240">4 h</button>
            </div>
            <div class="mobile-guest-link-duration-label" id="mobileGuestLinkHistoryLabel"></div>
            <div class="mobile-guest-link-history-scope">
                <button type="button" data-guest-history="current"></button>
                <button type="button" data-guest-history="6m"></button>
                <button type="button" data-guest-history="12m"></button>
                <button type="button" data-guest-history="all"></button>
            </div>
            <label class="mobile-guest-link-pdf-option mobile-guest-history-cancelled">
                <span class="mobile-guest-link-pdf-copy">
                    <strong id="mobileGuestLinkCancelledTitle"></strong>
                    <small id="mobileGuestLinkCancelledHint"></small>
                </span>
                <input type="checkbox" id="mobileGuestLinkIncludeCancelled">
                <span class="mobile-guest-link-switch" aria-hidden="true"><i></i></span>
            </label>
            <div class="mobile-guest-link-scope-preview" id="mobileGuestLinkScopePreview"></div>
            <!-- 原始 PDF 附件下载权限暂时隐藏；后台字段保留，方便以后恢复。 -->
            <input type="checkbox" id="mobileGuestLinkAllowPdf" hidden>
            <label class="mobile-guest-link-pdf-option">
                <span class="mobile-guest-link-pdf-copy">
                    <strong id="mobileGuestLinkShowPdfTitle"></strong>
                    <small id="mobileGuestLinkShowPdfHint"></small>
                </span>
                <input type="checkbox" id="mobileGuestLinkShowPdfPages" checked>
                <span class="mobile-guest-link-switch" aria-hidden="true"><i></i></span>
            </label>
            <label class="mobile-guest-link-pdf-option">
                <span class="mobile-guest-link-pdf-copy">
                    <strong id="mobileGuestLinkReportPdfTitle"></strong>
                    <small id="mobileGuestLinkReportPdfHint"></small>
                </span>
                <input type="checkbox" id="mobileGuestLinkAllowReportPdf">
                <span class="mobile-guest-link-switch" aria-hidden="true"><i></i></span>
            </label>
            <button type="button" class="mobile-guest-link-generate" id="mobileGuestLinkGenerate"></button>
            <div class="mobile-guest-link-result" id="mobileGuestLinkResult" hidden>
                <div class="mobile-guest-link-qr-wrap" id="mobileGuestLinkQrWrap" hidden>
                    <img id="mobileGuestLinkQr" alt="QR Code">
                    <small></small>
                </div>
                <div class="mobile-guest-link-expiry" id="mobileGuestLinkExpiry"></div>
                <div class="mobile-guest-link-url-row">
                    <input id="mobileGuestLinkUrl" type="text" readonly autocomplete="off" spellcheck="false">
                    <button type="button" id="mobileGuestLinkCopy"></button>
                    <button type="button" id="mobileGuestLinkOpen" class="mobile-guest-link-open-tab"></button>
                </div>
                <div class="mobile-guest-link-result-actions">
                    <button type="button" class="mobile-guest-link-revoke" id="mobileGuestLinkRevoke"></button>
                </div>
            </div>
            <div class="mobile-guest-active-section" id="mobileGuestActiveSection">
                <div class="mobile-guest-active-head">
                    <strong id="mobileGuestActiveTitle"></strong>
                    <span id="mobileGuestActiveCount"></span>
                </div>
                <div class="mobile-guest-active-list" id="mobileGuestActiveList"></div>
            </div>
            <p class="mobile-guest-link-hint"></p>
        </section>`;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-guest-minutes]').forEach(btn => {
        btn.addEventListener('click', () => {
            modal.querySelectorAll('[data-guest-minutes]').forEach(x => x.classList.toggle('active', x === btn));
            modal.dataset.minutes = btn.dataset.guestMinutes || '60';
        });
    });
    modal.querySelectorAll('[data-guest-history]').forEach(btn => {
        btn.addEventListener('click', () => {
            modal.dataset.historyScope = btn.dataset.guestHistory || 'current';
            modal.querySelectorAll('[data-guest-history]').forEach(x => x.classList.toggle('active', x === btn));
            mobilePreviewGuestScope();
        });
    });
    modal.querySelector('#mobileGuestLinkIncludeCancelled')?.addEventListener('change', () => mobilePreviewGuestScope());
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && modal.classList.contains('show')) mobileCloseGuestLinkModal();
    });
    return modal;
}

function mobileOpenGuestLinkModal(customerName) {
    const modal = mobileGuestLinkEnsureModal();
    modal.dataset.customerName = String(customerName || '');
    modal.dataset.minutes = '60';
    modal.dataset.linkId = '';
    const inheritedHistory = mobileCustomerHistorySetting(customerName);
    modal.dataset.historyScope = inheritedHistory.scope || 'current';
    modal.querySelectorAll('[data-guest-minutes]').forEach(btn => btn.classList.toggle('active', btn.dataset.guestMinutes === '60'));
    modal.querySelectorAll('[data-guest-history]').forEach(btn => btn.classList.toggle('active', btn.dataset.guestHistory === modal.dataset.historyScope));
    const includeCancelledInput = modal.querySelector('#mobileGuestLinkIncludeCancelled');
    if (includeCancelledInput) includeCancelledInput.checked = !!inheritedHistory.includeCancelled;
    modal.querySelector('#mobileGuestLinkTitle').textContent = mobileGuestLinkText('临时客户查看', 'Vista temporal del cliente');
    modal.querySelector('#mobileGuestLinkCustomer').textContent = customerName || '';
    modal.querySelector('.mobile-guest-link-duration-label').textContent = mobileGuestLinkText('选择有效时间', 'Duración del acceso');
    modal.querySelector('#mobileGuestLinkHistoryLabel').textContent = mobileGuestLinkText('分享订单范围', 'Rango de pedidos compartidos');
    const historyTexts = {
        current: mobileGuestLinkText('目前', 'Actual'),
        '6m': mobileGuestLinkText('半年', '6 meses'),
        '12m': mobileGuestLinkText('一年', '1 año'),
        all: mobileGuestLinkText('全部历史', 'Todo')
    };
    modal.querySelectorAll('[data-guest-history]').forEach(btn => { btn.textContent = historyTexts[btn.dataset.guestHistory] || btn.dataset.guestHistory; });
    modal.querySelector('#mobileGuestLinkCancelledTitle').textContent = mobileGuestLinkText('分享已取消订单', 'Compartir pedidos cancelados');
    modal.querySelector('#mobileGuestLinkCancelledHint').textContent = mobileGuestLinkText('只有开启后，客人才能看到该范围内的取消记录', 'Solo al activarlo el cliente podrá ver cancelados dentro de este rango');
    modal.querySelector('#mobileGuestLinkShowPdfTitle').textContent = mobileGuestLinkText('PDF 附件拆成图片显示', 'Mostrar PDF como imágenes');
    modal.querySelector('#mobileGuestLinkShowPdfHint').textContent = mobileGuestLinkText('关闭后，客人页面完全不显示 PDF 附件；开启才会逐页拆图', 'Si se desactiva, los PDF adjuntos no se muestran; al activarlo se convierten en páginas de imagen');
    modal.querySelector('#mobileGuestLinkReportPdfTitle').textContent = mobileGuestLinkText('允许查看 / 下载 PDF 报告', 'Permitir ver / descargar informe PDF');
    modal.querySelector('#mobileGuestLinkReportPdfHint').textContent = mobileGuestLinkText('客人可按需生成并下载当前客户的完整 PDF 报告', 'El cliente puede generar y descargar su informe PDF completo');
    modal.querySelector('#mobileGuestLinkAllowPdf').checked = false;
    modal.querySelector('#mobileGuestLinkShowPdfPages').checked = true;
    modal.querySelector('#mobileGuestLinkAllowReportPdf').checked = false;
    modal.querySelector('#mobileGuestLinkGenerate').textContent = mobileGuestLinkText('生成临时链接', 'Crear enlace temporal');
    modal.querySelector('#mobileGuestLinkCopy').textContent = mobileGuestLinkText('一键复制', 'Copiar');
    modal.querySelector('#mobileGuestLinkOpen').textContent = mobileGuestLinkText('新分頁打開', 'Abrir');
    modal.querySelector('#mobileGuestLinkRevoke').textContent = mobileGuestLinkText('立即失效', 'Desactivar ahora');
    modal.querySelector('#mobileGuestActiveTitle').textContent = mobileGuestLinkText('目前有效分享', 'Accesos activos');
    modal.querySelector('#mobileGuestActiveCount').textContent = '';
    modal.querySelector('.mobile-guest-link-hint').textContent = mobileGuestLinkText(
        '客人必须连接公司 Wi‑Fi。链接到期自动失效，只能查看这个客户自己的订单。',
        'El cliente debe estar conectado al Wi‑Fi de la oficina. El enlace caduca automáticamente y solo permite ver sus propios pedidos.'
    );
    modal.querySelector('#mobileGuestLinkResult').hidden = true;
    modal.querySelector('#mobileGuestLinkQrWrap').hidden = true;
    modal.querySelector('#mobileGuestLinkUrl').value = '';
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('mobile-guest-link-open');
    mobilePreviewGuestScope();
    mobileLoadActiveGuestLinks();
    if (window.mobileGuestActiveRefreshTimer) clearInterval(window.mobileGuestActiveRefreshTimer);
    window.mobileGuestActiveRefreshTimer = setInterval(() => {
        if (modal.classList.contains('show')) mobileLoadActiveGuestLinks({silent:true});
    }, 15000);

    modal.querySelector('#mobileGuestLinkGenerate').onclick = () => mobileGenerateGuestLink();
    modal.querySelector('#mobileGuestLinkCopy').onclick = () => mobileCopyGuestLink();
    modal.querySelector('#mobileGuestLinkOpen').onclick = () => mobileOpenGuestLinkTab();
    modal.querySelector('#mobileGuestLinkRevoke').onclick = () => mobileRevokeGuestLink();
}

function mobileCloseGuestLinkModal() {
    const modal = document.getElementById('mobileGuestLinkModal');
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('mobile-guest-link-open');
    if (window.mobileGuestActiveRefreshTimer) {
        clearInterval(window.mobileGuestActiveRefreshTimer);
        window.mobileGuestActiveRefreshTimer = null;
    }
}

function mobileGuestFormatEpoch(epoch, includeSeconds = false) {
    const n = Number(epoch || 0);
    if (!Number.isFinite(n) || n <= 0) return '—';
    const d = new Date(n * 1000);
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    return `${dd}/${mm} ${hh}:${mi}${includeSeconds ? `:${ss}` : ''}`;
}

function mobileGuestRemainingLabel(seconds) {
    const value = Math.max(0, Number(seconds || 0));
    if (value <= 0) return mobileGuestLinkText('已到期', 'Caducado');
    const mins = Math.max(1, Math.ceil(value / 60));
    if (mins < 60) return mobileGuestLinkText(`剩 ${mins} 分`, `Quedan ${mins} min`);
    const hours = Math.floor(mins / 60);
    const rest = mins % 60;
    return mobileGuestLinkText(`剩 ${hours} 小时${rest ? ` ${rest} 分` : ''}`, `Quedan ${hours} h${rest ? ` ${rest} min` : ''}`);
}

function mobileGuestDurationLabel(minutes) {
    const n = Number(minutes || 0);
    if (n === 30) return '30 min';
    if (n === 60) return '1 h';
    if (n === 240) return '4 h';
    return `${Math.max(1, n)} min`;
}

function mobileRenderActiveGuestLinks(items) {
    const modal = document.getElementById('mobileGuestLinkModal');
    if (!modal) return;
    const list = modal.querySelector('#mobileGuestActiveList');
    const count = modal.querySelector('#mobileGuestActiveCount');
    if (!list || !count) return;
    const now = Math.floor(Date.now() / 1000);
    const rows = (Array.isArray(items) ? items : []).filter(item => Number(item?.expires_at_epoch || 0) > now);
    count.textContent = rows.length ? String(rows.length) : '';
    list.innerHTML = '';
    if (!rows.length) {
        const empty = document.createElement('div');
        empty.className = 'mobile-guest-active-empty';
        empty.textContent = mobileGuestLinkText('目前没有有效分享', 'No hay accesos activos');
        list.appendChild(empty);
        return;
    }
    rows.forEach(item => {
        const card = document.createElement('div');
        card.className = 'mobile-guest-active-card';
        card.dataset.linkId = String(item.id || '');

        const body = document.createElement('div');
        body.className = 'mobile-guest-active-copy';
        const name = document.createElement('strong');
        name.textContent = String(item.customer_name || '—');
        const meta = document.createElement('small');
        const created = mobileGuestFormatEpoch(item.created_at_epoch, true);
        if (item.is_permanent) {
            meta.textContent = window.getTrackingLanguage?.() === 'es'
                ? `Creado ${created} · permanente${item.password_protected ? ' · con contraseña' : ''}`
                : `建立 ${created} · 永久${item.password_protected ? ' · 密码保护' : ''}`;
        } else {
            const expires = mobileGuestFormatEpoch(item.expires_at_epoch, false);
            const remaining = mobileGuestRemainingLabel(Number(item.expires_at_epoch || 0) - now);
            meta.textContent = window.getTrackingLanguage?.() === 'es'
                ? `Creado ${created} · vence ${expires} · ${mobileGuestDurationLabel(item.duration_minutes)} · ${remaining}`
                : `建立 ${created} · 到期 ${expires} · ${mobileGuestDurationLabel(item.duration_minutes)} · ${remaining}`;
        }
        body.append(name, meta);

        const revoke = document.createElement('button');
        revoke.type = 'button';
        revoke.className = 'mobile-guest-active-revoke';
        revoke.textContent = mobileGuestLinkText('立即失效', 'Desactivar');
        revoke.onclick = () => mobileRevokeActiveGuestLink(item.id, revoke);
        card.append(body, revoke);
        list.appendChild(card);
    });
}

async function mobileLoadActiveGuestLinks(options = {}) {
    const modal = document.getElementById('mobileGuestLinkModal');
    if (!modal) return;
    const list = modal.querySelector('#mobileGuestActiveList');
    const count = modal.querySelector('#mobileGuestActiveCount');
    if (!list || !count) return;
    if (!options.silent) {
        count.textContent = '';
        list.innerHTML = `<div class="mobile-guest-active-empty">${mobileGuestLinkText('正在读取有效分享…','Cargando accesos activos…')}</div>`;
    }
    try {
        const response = await fetch('/tracking/api/local-guest-links', {credentials:'same-origin', cache:'no-store'});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload?.success === false) throw new Error(payload?.error || `HTTP ${response.status}`);
        mobileRenderActiveGuestLinks(payload.data || []);
    } catch (err) {
        if (!options.silent) {
            count.textContent = '';
            list.innerHTML = `<div class="mobile-guest-active-empty error">${mobileGuestLinkText('无法读取有效分享','No se pudieron cargar los accesos')}</div>`;
        }
    }
}

async function mobileRevokeActiveGuestLink(linkId, button) {
    const id = String(linkId || '');
    if (!id) return;
    if (button) button.disabled = true;
    try {
        const response = await fetch(`/tracking/api/local-guest-links/${encodeURIComponent(id)}`, {
            method:'DELETE', credentials:'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload?.success === false) throw new Error(payload?.error || `HTTP ${response.status}`);
        const modal = document.getElementById('mobileGuestLinkModal');
        if (modal && String(modal.dataset.linkId || '') === id) {
            modal.dataset.linkId = '';
            modal.querySelector('#mobileGuestLinkUrl').value = '';
            modal.querySelector('#mobileGuestLinkResult').hidden = true;
        }
        await mobileLoadActiveGuestLinks({silent:true});
        if (typeof showToast === 'function') showToast(mobileGuestLinkText('已失效','Desactivado'), mobileGuestLinkText('该临时分享已立即关闭','El acceso temporal ya no funciona'), 'success');
    } catch (err) {
        if (typeof showToast === 'function') showToast(mobileGuestLinkText('操作失败','Error'), String(err?.message || err), 'error');
    } finally {
        if (button) button.disabled = false;
    }
}

async function mobilePreviewGuestScope() {
    const modal = document.getElementById('mobileGuestLinkModal');
    if (!modal || !modal.classList.contains('show')) return;
    const box = modal.querySelector('#mobileGuestLinkScopePreview');
    if (!box) return;
    const customerName = String(modal.dataset.customerName || '').trim();
    const scope = modal.dataset.historyScope || 'current';
    const includeCancelled = !!modal.querySelector('#mobileGuestLinkIncludeCancelled')?.checked;
    box.textContent = mobileGuestLinkText('正在计算可分享订单…','Calculando pedidos…');
    try {
        const url = `/tracking/api/customers/history-orders?customer_name=${encodeURIComponent(customerName)}&scope=${encodeURIComponent(scope)}&include_cancelled=${includeCancelled ? '1':'0'}`;
        const response = await fetch(url, {credentials:'same-origin', cache:'no-store'});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload?.success === false) throw new Error(payload?.error || `HTTP ${response.status}`);
        const rows = Array.isArray(payload.data) ? payload.data : [];
        const cancelledCount = rows.filter(item => normalizeStatusForLogic(item.current_status || '') === 'CANCELLED').length;
        const completedCount = rows.filter(item => normalizeStatusForLogic(item.current_status || '') === 'COMPLETED').length;
        const activeCount = Math.max(0, rows.length - cancelledCount - completedCount);
        box.textContent = window.getTrackingLanguage?.() === 'es'
            ? `Se compartirán ${rows.length} pedidos · ${activeCount} activos · ${completedCount} completados${includeCancelled ? ` · ${cancelledCount} cancelados` : ''}`
            : `预计分享 ${rows.length} 笔 · ${activeCount} 进行中 · ${completedCount} 已完成${includeCancelled ? ` · ${cancelledCount} 已取消` : ''}`;
    } catch (error) {
        box.textContent = mobileGuestLinkText('无法预估订单数量','No se pudo calcular la cantidad');
    }
}

async function mobileGenerateGuestLink() {
    const modal = document.getElementById('mobileGuestLinkModal');
    if (!modal) return;
    const button = modal.querySelector('#mobileGuestLinkGenerate');
    const original = button.textContent;
    button.disabled = true;
    button.textContent = mobileGuestLinkText('正在生成…', 'Creando…');
    try {
        const response = await fetch('/tracking/api/local-guest-links', {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({
                customer_name: modal.dataset.customerName || '',
                duration_minutes: Number(modal.dataset.minutes || 60),
                allow_pdf_download: false,
                show_pdf_pages: !!modal.querySelector('#mobileGuestLinkShowPdfPages')?.checked,
                allow_report_pdf_download: !!modal.querySelector('#mobileGuestLinkAllowReportPdf')?.checked,
                history_scope: modal.dataset.historyScope || 'current',
                include_cancelled: !!modal.querySelector('#mobileGuestLinkIncludeCancelled')?.checked
            })
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload?.success === false) throw new Error(payload?.error || `HTTP ${response.status}`);
        const data = payload.data || {};
        modal.dataset.linkId = String(data.id || '');
        modal.querySelector('#mobileGuestLinkUrl').value = data.url || '';
        const result = modal.querySelector('#mobileGuestLinkResult');
        result.hidden = false;
        const qrWrap = modal.querySelector('#mobileGuestLinkQrWrap');
        const qr = modal.querySelector('#mobileGuestLinkQr');
        if (data.qr_data_uri) {
            qr.src = data.qr_data_uri;
            qrWrap.hidden = false;
            qrWrap.querySelector('small').textContent = mobileGuestLinkText('扫码打开', 'Escanear para abrir');
        } else {
            qrWrap.hidden = true;
        }
        const expiry = new Date(Number(data.expires_at_epoch || 0) * 1000);
        modal.querySelector('#mobileGuestLinkExpiry').textContent = mobileGuestLinkText('有效至：', 'Válido hasta: ') +
            expiry.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
        mobileLoadActiveGuestLinks({silent:true});
    } catch (err) {
        if (typeof showToast === 'function') showToast(mobileGuestLinkText('生成失败','Error'), String(err?.message || err), 'error');
    } finally {
        button.disabled = false;
        button.textContent = original;
    }
}

function mobileOpenGuestLinkTab() {
    const input = document.getElementById('mobileGuestLinkUrl');
    const value = String(input?.value || '').trim();
    if (!value) return;
    const opened = window.open(value, '_blank', 'noopener');
    if (!opened && typeof showToast === 'function') {
        showToast(
            mobileGuestLinkText('无法打开新分頁', 'No se pudo abrir'),
            mobileGuestLinkText('浏览器阻止了新分頁，请长按链接或允许弹出视窗', 'El navegador bloqueó la nueva pestaña.'),
            'info'
        );
    }
}


async function mobileCopyGuestLink() {
    const input = document.getElementById('mobileGuestLinkUrl');
    const value = String(input?.value || '');
    if (!value) return;
    let ok = false;
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(value);
            ok = true;
        }
    } catch (_) {}
    if (!ok && input) {
        input.removeAttribute('readonly');
        input.select(); input.setSelectionRange(0, value.length);
        try { ok = document.execCommand('copy'); } catch (_) {}
        input.setAttribute('readonly', 'readonly');
        try { window.getSelection()?.removeAllRanges(); } catch (_) {}
    }
    if (typeof showToast === 'function') {
        showToast(ok ? mobileGuestLinkText('已复制','Copiado') : mobileGuestLinkText('请手动复制','Copiar manualmente'),
                  ok ? mobileGuestLinkText('临时链接已复制到剪贴板','Enlace temporal copiado') : value,
                  ok ? 'success' : 'info');
    }
}

async function mobileRevokeGuestLink() {
    const modal = document.getElementById('mobileGuestLinkModal');
    const linkId = String(modal?.dataset.linkId || '');
    if (!modal || !linkId) return;
    const button = modal.querySelector('#mobileGuestLinkRevoke');
    button.disabled = true;
    try {
        const response = await fetch(`/tracking/api/local-guest-links/${encodeURIComponent(linkId)}`, {
            method:'DELETE', credentials:'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload?.success === false) throw new Error(payload?.error || `HTTP ${response.status}`);
        modal.dataset.linkId = '';
        modal.querySelector('#mobileGuestLinkUrl').value = '';
        modal.querySelector('#mobileGuestLinkResult').hidden = true;
        await mobileLoadActiveGuestLinks({silent:true});
        if (typeof showToast === 'function') showToast(mobileGuestLinkText('已失效','Desactivado'), mobileGuestLinkText('该临时链接已立即关闭','El enlace temporal ya no funciona'), 'success');
    } catch (err) {
        if (typeof showToast === 'function') showToast(mobileGuestLinkText('操作失败','Error'), String(err?.message || err), 'error');
    } finally {
        button.disabled = false;
    }
}

function mobileCustomerLinkAction(customerName) {
    if (isCloudMode()) {
        if (typeof showToast === 'function') {
            showToast(mobileT('mobile.customer_link_title', '客户查询链接'), `${customerName}${mobileT('mobile.customer_link_pending', ' 的 /c/<token> 将在 TiDB Token 阶段接通，目前尚未建立链接。')}`, 'info');
        }
        return;
    }
    mobileOpenGuestLinkModal(customerName);
}

function mobileLoadMore() {
    mobileVisibleLimit += 60;
    renderMobileOrderList();
}

function renderMobileExperience(force = false) {
    if (!isMobileOrderViewport()) return;
    const ui = document.getElementById('mobileOrderUi');
    if (!ui) return;

    const signature = JSON.stringify({
        stageGroups: currentFilter.stageGroups || [],
        substatus: currentFilter.substatus || 'all',
        search: currentFilter.search || '',
        customer: selectedCustomerNameFilter || '',
        order: selectedOrderNumberFilter || '',
        lights: currentFilter.lights || {},
        team: currentFilter.teamSales || []
    });
    if (!force && mobileLastFilterSignature && mobileLastFilterSignature !== signature) mobileVisibleLimit = 60;
    mobileLastFilterSignature = signature;

    syncMobileControlsFromCurrentFilter();
    renderMobileSalesFilters();

    const ordersPanel = document.getElementById('mobileOrdersPanel');
    const customersPanel = document.getElementById('mobileCustomersPanel');
    const detail = document.getElementById('mobileCustomerDetail');
    const orderDetail = document.getElementById('mobileOrderDetail');
    const resultCount = document.getElementById('mobileResultCount');
    const resultHint = document.getElementById('mobileResultHint');
    const ordersBtn = document.getElementById('mobileModeOrders');
    const customersBtn = document.getElementById('mobileModeCustomers');

    if (ordersBtn) ordersBtn.classList.toggle('active', mobileBrowseMode === 'orders');
    if (customersBtn) customersBtn.classList.toggle('active', mobileBrowseMode === 'customers');

    if (mobileOrderDetailKey) {
        ui.classList.add('order-detail-open');
        if (orderDetail) orderDetail.hidden = false;
        if (detail) detail.hidden = true;
        return;
    }
    ui.classList.remove('order-detail-open');
    if (orderDetail) orderDetail.hidden = true;

    if (mobileCustomerDetailName) {
        ui.classList.add('customer-detail-open');
        if (detail) detail.hidden = false;
        renderMobileCustomerDetail(mobileCustomerDetailName);
        return;
    }

    ui.classList.remove('customer-detail-open');
    if (detail) detail.hidden = true;

    if (mobileBrowseMode === 'customers') {
        if (ordersPanel) ordersPanel.hidden = true;
        if (customersPanel) customersPanel.hidden = false;
        const customerCount = buildMobileCustomerGroups().length;
        if (resultCount) resultCount.textContent = mobileCustomerCountText(customerCount);
        if (resultHint) resultHint.textContent = mobileOrderCountText(homeFilteredOrdersData.length);
        renderMobileCustomerList();
    } else {
        if (ordersPanel) ordersPanel.hidden = false;
        if (customersPanel) customersPanel.hidden = true;
        if (resultCount) resultCount.textContent = mobileOrderCountText(homeFilteredOrdersData.length);
        if (resultHint) resultHint.textContent = mobileT('mobile.click_detail', '点击可查看详情');
        renderMobileOrderList();
    }
}

// Mobile top navigation
function openMobileNavMenu() {
    const sheet = document.getElementById('mobileNavSheet');
    const backdrop = document.getElementById('mobileNavBackdrop');
    if (sheet) {
        sheet.classList.add('show');
        sheet.setAttribute('aria-hidden', 'false');
    }
    if (backdrop) backdrop.classList.add('show');
}

function closeMobileNavMenu() {
    const sheet = document.getElementById('mobileNavSheet');
    const backdrop = document.getElementById('mobileNavBackdrop');
    if (sheet) {
        sheet.classList.remove('show');
        sheet.setAttribute('aria-hidden', 'true');
    }
    if (backdrop) backdrop.classList.remove('show');
}

document.addEventListener('tracking:languagechange', () => {
    if (isMobileOrderViewport()) {
        if (mobileOrderDetailKey) {
            const order = (homeOrdersData || []).find(item => getHomeOrderKey(item) === mobileOrderDetailKey);
            if (order) renderMobileOrderDetail(order, mobileOrderDetailData, false);
        } else {
            renderMobileExperience(true);
        }
        const reportSheet = document.getElementById('mobileReportSheet');
        if (mobileReportRequestContext && reportSheet?.classList.contains('show')) {
            mobileRenderReportOptions();
        }
    }
    // Desktop status labels are regenerated by the normal table renderer when available.
    if (typeof renderHomeOrdersPage === 'function' && Array.isArray(homeFilteredOrdersData)) {
        try { renderHomeOrdersPage(); } catch (e) { /* keep UI usable */ }
    }
});

window.addEventListener('resize', () => {
    if (isMobileOrderViewport()) {
        renderMobileExperience(true);
    } else {
        closeMobileNavMenu();
        closeMobileSalesSheet();
        closeMobileReportSheet();
        closeMobileImageViewer({useHistory:false});
        hideMobileSearchSuggestions();
    }
});

document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
        closeMobileNavMenu();
        closeMobileSalesSheet();
        closeMobileReportSheet();
        closeMobileImageViewer({useHistory:false});
        hideMobileSearchSuggestions();
    }
});


// ==================== WEB / ADMIN 客户分享管理 ====================
let desktopGuestShareMinutes = 60;
let desktopGuestShareScope = 'current';
let desktopGuestShareMode = 'lan';
let desktopGuestIsPermanent = false;
let desktopGuestPasswordKind = 'none';
let desktopGuestCurrentLinkId = '';
let desktopGuestCurrentLinkMode = 'lan';
let desktopGuestActiveTimer = null;
let desktopGuestCustomerOptions = [];
let desktopGuestFilteredCustomers = [];
let desktopGuestCustomerResultIndex = -1;
let desktopGuestCustomerSearchTimer = null;
let desktopGuestCustomerSearchSeq = 0;
let desktopGuestActiveMode = 'all';
let desktopGuestActiveItemsCache = [];
let desktopGuestActiveSearch = '';
let desktopGuestActivePage = 1;
let desktopGuestActivePageSize = 10;
let desktopGuestActiveShowDetails = false;

function desktopGuestIsAdmin() {
    return !!(window.AppPermissions && typeof window.AppPermissions.isAdmin === 'function' && window.AppPermissions.isAdmin());
}
function desktopGuestDrawer() { return document.getElementById('desktopGuestShareDrawer'); }
function desktopGuestSelectedCustomer() { return String(document.getElementById('desktopGuestCustomerSelect')?.value || '').trim(); }
function desktopGuestNormalizeCustomerSearch(value) {
    return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleUpperCase().replace(/\s+/g, ' ').trim();
}
function desktopGuestEscapeHtml(value) {
    return String(value || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function desktopGuestSameCustomer(a, b) {
    return desktopGuestNormalizeCustomerSearch(a) === desktopGuestNormalizeCustomerSearch(b);
}
function desktopGuestModeBadge(mode) {
    return String(mode || '').toLowerCase() === 'render' ? 'WEB' : 'LAN';
}
async function desktopGuestCollectActiveItems() {
    const root = desktopGuestDrawer();
    const wantsPublic = root?.dataset.renderEnabled === '1';
    const requests = [
        fetch('/tracking/api/local-guest-links?compact=1', {credentials:'same-origin', cache:'no-store'})
            .then(async r => ({r, p: await r.json().catch(() => ({}))}))
            .catch(() => null)
    ];
    if (wantsPublic) {
        requests.push(
            fetch('/tracking/api/public-guest-links?compact=1', {credentials:'same-origin', cache:'no-store'})
                .then(async r => ({r, p: await r.json().catch(() => ({}))}))
                .catch(() => null)
        );
    }
    const responses = await Promise.all(requests);
    let items = [];
    for (const item of responses) {
        if (!item || !item.r?.ok || item.p?.success === false) continue;
        items = items.concat(Array.isArray(item.p?.data) ? item.p.data : []);
    }
    desktopGuestActiveItemsCache = items;
    return items;
}
function desktopGuestRenderExistingLinksHint(customer, items) {
    const box = document.getElementById('desktopGuestExistingLinks');
    if (!box) return;
    const name = String(customer || '').trim();
    if (!name) {
        box.hidden = true;
        box.innerHTML = '';
        return;
    }
    const same = (Array.isArray(items) ? items : []).filter(item => desktopGuestSameCustomer(item.customer_name || '', name));
    if (!same.length) {
        box.hidden = true;
        box.innerHTML = '';
        return;
    }
    const modeCounts = same.reduce((acc, item) => {
        const key = String(item.share_mode || 'lan').toLowerCase() === 'render' ? 'render' : 'lan';
        acc[key] = (acc[key] || 0) + 1;
        return acc;
    }, {lan: 0, render: 0});
    const parts = [];
    if (modeCounts.lan) parts.push(`LAN ${modeCounts.lan} 个`);
    if (modeCounts.render) parts.push(`WEB ${modeCounts.render} 个`);
    box.hidden = false;
    box.innerHTML = `<div class="desktop-guest-existing-links-head"><strong>此客户目前已有 ${same.length} 个有效分享</strong><button type="button" onclick="desktopGuestSetTab('active')">查看有效分享</button></div><small>${parts.join(' · ')}。可继续建立新分享，不受限制。</small>`;
}
async function desktopGuestRefreshExistingLinksHint(forceReload = false) {
    const customer = desktopGuestSelectedCustomer();
    const box = document.getElementById('desktopGuestExistingLinks');
    if (!box) return;
    if (!customer) {
        box.hidden = true;
        box.innerHTML = '';
        return;
    }
    try {
        const items = forceReload ? await desktopGuestCollectActiveItems() : (desktopGuestActiveItemsCache.length ? desktopGuestActiveItemsCache : await desktopGuestCollectActiveItems());
        desktopGuestRenderExistingLinksHint(customer, items);
    } catch (_) {
        box.hidden = true;
        box.innerHTML = '';
    }
}
function desktopGuestUniqueNames(rows) {
    const seen = new Set(), out = [];
    (rows || []).forEach(item => {
        const name = String(item?.customer_name || item?.customerName || item?.dataset?.customerName || '').trim();
        if (!name) return;
        const key = desktopGuestNormalizeCustomerSearch(name);
        if (seen.has(key)) return;
        seen.add(key); out.push(name);
    });
    return out.sort((a,b)=>a.localeCompare(b,undefined,{sensitivity:'base',numeric:true}));
}
function desktopGuestCustomerMatches(name, query) {
    const haystack = desktopGuestNormalizeCustomerSearch(name);
    const terms = desktopGuestNormalizeCustomerSearch(query).split(' ').filter(Boolean);
    return !terms.length || terms.every(term => haystack.includes(term));
}
function desktopGuestHasMainSearchFilter() {
    const inputValue = String(document.getElementById('searchInput')?.value || '').trim();
    const filterValue = String((typeof currentFilter === 'object' && currentFilter?.search) || '').trim();
    const exactCustomer = String(typeof selectedCustomerNameFilter !== 'undefined' ? (selectedCustomerNameFilter || '') : '').trim();
    const exactOrder = String(typeof selectedOrderNumberFilter !== 'undefined' ? (selectedOrderNumberFilter || '') : '').trim();
    return !!(inputValue || filterValue || exactCustomer || exactOrder);
}
function desktopGuestCurrentPageCustomerNames() {
    if (!desktopGuestHasMainSearchFilter()) return [];
    if (homeDataReady && !isGlobalSearchMode) {
        const start = Math.max(0, (Number(currentTablePage || 1) - 1) * TABLE_PAGE_SIZE);
        return desktopGuestUniqueNames(homeFilteredOrdersData.slice(start, start + TABLE_PAGE_SIZE));
    }
    const visibleRows = Array.from(document.querySelectorAll('#ordersTableBody tr[data-order-number]')).filter(row => {
        if (row.hidden || row.style.display === 'none') return false;
        return getComputedStyle(row).display !== 'none';
    });
    return desktopGuestUniqueNames(visibleRows);
}
function desktopGuestUpdatePageCandidateHint() {
    const hint = document.getElementById('desktopGuestPageCandidateHint');
    if (!hint) return;
    const onShareAdminPage = !!document.querySelector('.share-admin-page');
    if (onShareAdminPage) {
        hint.textContent = '直接输入客户名称，可搜索全部客户';
        return;
    }
    if (!desktopGuestHasMainSearchFilter()) {
        hint.textContent = '主頁未搜尋，不預載客戶；直接輸入可搜尋全部客戶';
        return;
    }
    const count = desktopGuestFilteredCustomers.length;
    hint.textContent = count
        ? `主頁目前頁面找到 ${count} 個客戶，可直接點選；也可輸入搜尋全部客戶`
        : '主頁搜尋後目前頁面沒有客戶；可直接輸入搜尋全部客戶';
}
function desktopGuestRenderCustomerResults(query = '') {
    const list = document.getElementById('desktopGuestCustomerResults');
    if (!list) return;
    const q = String(query || '').trim();
    const source = q ? desktopGuestCustomerOptions : desktopGuestFilteredCustomers;
    const matches = source.filter(name => desktopGuestCustomerMatches(name, q)).slice(0, 12);
    desktopGuestCustomerResultIndex = matches.length ? 0 : -1;
    if (!matches.length) { list.hidden = true; list.innerHTML=''; return; }
    list.innerHTML = matches.map((name,index) => `<button type="button" data-customer-name="${desktopGuestEscapeHtml(name)}" class="${index===0?'is-keyboard-active':''}"><span>${desktopGuestEscapeHtml(name)}</span><small>${q ? '全部客户' : '主頁目前頁'}</small></button>`).join('');
    list.querySelectorAll('[data-customer-name]').forEach(btn => btn.addEventListener('click', () => desktopGuestChooseCustomer(btn.dataset.customerName || '')));
    list.hidden = false;
}
async function desktopGuestFetchCustomerOptions(query, seq) {
    const q = String(query || '').trim();
    if (!q) return;
    try {
        const response = await fetch(`/tracking/api/customers/search?q=${encodeURIComponent(q)}`, {credentials:'same-origin', cache:'no-store'});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload?.success === false || seq !== desktopGuestCustomerSearchSeq) return;
        const incoming = Array.isArray(payload?.data) ? payload.data : [];
        desktopGuestCustomerOptions = desktopGuestUniqueNames([
            ...desktopGuestCustomerOptions.map(customer_name => ({customer_name})),
            ...incoming.map(customer_name => ({customer_name}))
        ]);
        const input = document.getElementById('desktopGuestCustomerSearch');
        if (String(input?.value || '').trim() === q) desktopGuestRenderCustomerResults(q);
    } catch (_) {}
}
function desktopGuestFilterCustomers() {
    const input = document.getElementById('desktopGuestCustomerSearch');
    const clear = document.getElementById('desktopGuestCustomerClear');
    const value = String(input?.value || '');
    const query = value.trim();
    if (clear) clear.classList.toggle('show', !!query);
    desktopGuestRenderCustomerResults(value);
    if (desktopGuestCustomerSearchTimer) clearTimeout(desktopGuestCustomerSearchTimer);
    if (!query) return;
    const seq = ++desktopGuestCustomerSearchSeq;
    desktopGuestCustomerSearchTimer = setTimeout(() => desktopGuestFetchCustomerOptions(query, seq), 180);
}
function desktopGuestChooseCustomer(name) {
    const selected = String(name || '').trim(); if (!selected) return;
    const select = document.getElementById('desktopGuestCustomerSelect');
    const input = document.getElementById('desktopGuestCustomerSearch');
    const list = document.getElementById('desktopGuestCustomerResults');
    const label = document.getElementById('desktopGuestCustomerSelected');
    if (select) {
        if (!Array.from(select.options).some(o => o.value === selected)) select.add(new Option(selected, selected));
        select.value = selected;
    }
    // Search stays empty by design: selected customer is displayed separately below.
    if (input) input.value = '';
    document.getElementById('desktopGuestCustomerClear')?.classList.remove('show');
    if (list) list.hidden = true;
    if (label) { label.hidden = false; label.innerHTML = `<span>已选择客户</span><strong>${desktopGuestEscapeHtml(selected)}</strong><button type="button" onclick="desktopGuestUnselectCustomer()">更换</button>`; }
    desktopGuestUpdatePasswordHint();
    desktopGuestPreviewScope();
    desktopGuestRefreshExistingLinksHint(true);
}
function desktopGuestUnselectCustomer() {
    const select=document.getElementById('desktopGuestCustomerSelect'); if (select) select.value='';
    const label=document.getElementById('desktopGuestCustomerSelected'); if (label) label.hidden=true;
    const input=document.getElementById('desktopGuestCustomerSearch'); if (input) {input.value=''; input.focus();}
    desktopGuestRenderCustomerResults('');
    const preview=document.getElementById('desktopGuestScopePreview'); if (preview) preview.textContent='请先选择客户';
    const existing=document.getElementById('desktopGuestExistingLinks'); if (existing) { existing.hidden=true; existing.innerHTML=''; }
    desktopGuestUpdatePasswordHint();
}
function desktopGuestClearCustomerSearch() {
    const input=document.getElementById('desktopGuestCustomerSearch');
    if (input) { input.value=''; input.focus(); }
    document.getElementById('desktopGuestCustomerClear')?.classList.remove('show');
    desktopGuestRenderCustomerResults('');
}
function desktopGuestCustomerSearchKeydown(event) {
    const list=document.getElementById('desktopGuestCustomerResults'); if (!list) return;
    const buttons=Array.from(list.querySelectorAll('[data-customer-name]'));
    if (event.key==='Escape') { list.hidden=true; return; }
    if (!buttons.length) return;
    if (event.key==='ArrowDown' || event.key==='ArrowUp') {
        event.preventDefault(); desktopGuestCustomerResultIndex += event.key==='ArrowDown'?1:-1;
        desktopGuestCustomerResultIndex=(desktopGuestCustomerResultIndex+buttons.length)%buttons.length;
        buttons.forEach((btn,i)=>btn.classList.toggle('is-keyboard-active',i===desktopGuestCustomerResultIndex));
        buttons[desktopGuestCustomerResultIndex]?.scrollIntoView({block:'nearest'});
    } else if (event.key==='Enter') {
        event.preventDefault(); const btn=buttons[Math.max(0,desktopGuestCustomerResultIndex)]||buttons[0]; if (btn) desktopGuestChooseCustomer(btn.dataset.customerName||'');
    }
}
function desktopGuestFmtDate(epoch) {
    const d=new Date(Number(epoch||0)*1000); return Number.isNaN(d.getTime())?'—':d.toLocaleString([], {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
}
function desktopGuestRemaining(seconds) {
    if (seconds === null || seconds === undefined) return '永久';
    const value=Math.max(0,Number(seconds||0)), mins=Math.ceil(value/60);
    if (mins<60) return `剩 ${mins} 分`;
    const days=Math.floor(mins/1440); if (days) return `剩 ${days} 天 ${Math.floor((mins%1440)/60)} 小时`;
    const h=Math.floor(mins/60),m=mins%60; return `剩 ${h} 小时${m?` ${m} 分`:''}`;
}
function desktopGuestSetSegment(containerId, attr, value) {
    const box=document.getElementById(containerId); if (!box) return;
    box.querySelectorAll(`button[${attr}]`).forEach(btn=>btn.classList.toggle('active',btn.getAttribute(attr)===String(value)));
}
function desktopGuestSetTab(tab) {
    const root=desktopGuestDrawer(); if (!root) return;
    root.querySelectorAll('[data-share-tab]').forEach(btn=>btn.classList.toggle('active',btn.dataset.shareTab===tab));
    root.querySelectorAll('[data-share-panel]').forEach(panel=>panel.hidden=panel.dataset.sharePanel!==tab);
    if (tab==='active') desktopGuestLoadActiveLinks(false);
}
function desktopGuestSetMode(mode) {
    const root=desktopGuestDrawer(); if (!root) return;
    const button=root.querySelector(`#desktopGuestMode [data-share-mode="${mode}"]`);
    if (!button || button.disabled) return;
    desktopGuestShareMode=mode;
    desktopGuestSetSegment('desktopGuestMode','data-share-mode',mode);
    const lan=document.getElementById('desktopGuestLanDuration'), render=document.getElementById('desktopGuestRenderDuration');
    if (lan) lan.hidden=mode!=='lan';
    if (render) render.hidden=mode!=='render';
    desktopGuestIsPermanent=false;
    desktopGuestShareMinutes=mode==='lan'?60:1440;
    desktopGuestSetSegment(mode==='lan'?'desktopGuestLanDuration':'desktopGuestRenderDuration','data-minutes',String(desktopGuestShareMinutes));
    root.querySelectorAll('[data-permanent]').forEach(btn=>btn.classList.remove('active'));
    const title=document.getElementById('desktopGuestDurationTitle');
    const hint=document.getElementById('desktopGuestDurationHint');
    if (title) title.textContent=mode==='lan'?'局网有效时间':'Render 有效时间';
    if (hint) hint.textContent=mode==='lan'?'到期后链接自动失效，不可延长':'公网提供 1 天 / 7 天 / 14 天 / 永久';
    document.getElementById('desktopGuestGenerateBtn').textContent=mode==='lan'?'建立局网分享链接':'建立 Render 公网链接';
}
function desktopGuestSetDuration(button) {
    if (!button || button.disabled) return;
    const group=button.closest('.desktop-guest-segments'); if (!group) return;
    group.querySelectorAll('button').forEach(b=>b.classList.remove('active')); button.classList.add('active');
    desktopGuestIsPermanent=button.dataset.permanent==='1';
    if (!desktopGuestIsPermanent) desktopGuestShareMinutes=Number(button.dataset.minutes||60);
}
function desktopGuestSetPasswordKind(kind) {
    desktopGuestPasswordKind=kind;
    desktopGuestSetSegment('desktopGuestPasswordKind','data-password-kind',kind);
    const custom=document.getElementById('desktopGuestCustomPassword'); if (custom) custom.hidden=kind!=='custom';
    desktopGuestUpdatePasswordHint();
}
function desktopGuestUpdatePasswordHint() {
    const hint=document.getElementById('desktopGuestPasswordHint'), customer=desktopGuestSelectedCustomer(); if (!hint) return;
    if (desktopGuestPasswordKind==='none') { hint.textContent='此链接不要求密码'; return; }
    if (desktopGuestPasswordKind==='custom') { hint.textContent='密码只保存安全哈希；管理页面不会显示明文'; return; }
    const phone=customer && typeof waContacts==='object' ? String(waContacts[customer]||'') : '';
    hint.textContent=phone ? `将使用客户手机号码（末 4 位 ${phone.slice(-4)}）作为密码` : '此客户尚未找到手机号码，请改用自定义密码';
}
function desktopGuestResolvePassword() {
    if (desktopGuestPasswordKind==='none') return {kind:'none', password:''};
    if (desktopGuestPasswordKind==='custom') return {kind:'custom', password:String(document.getElementById('desktopGuestCustomPassword')?.value||'').trim()};
    const customer=desktopGuestSelectedCustomer();
    return {kind:'phone', password:String((typeof waContacts==='object' && waContacts[customer]) || '').trim()};
}
function openDesktopGuestShareDrawer(preferredCustomer='') {
    if (!desktopGuestIsAdmin()) return;
    const modal=desktopGuestDrawer(); if (!modal) return;
    desktopGuestCustomerOptions=desktopGuestUniqueNames(Array.isArray(homeOrdersData)?homeOrdersData:[]);
    desktopGuestFilteredCustomers=desktopGuestCurrentPageCustomerNames();
    desktopGuestUpdatePageCandidateHint();
    const preferred=String(preferredCustomer||'').trim();
    if (preferred && !desktopGuestCustomerOptions.some(x=>desktopGuestNormalizeCustomerSearch(x)===desktopGuestNormalizeCustomerSearch(preferred))) desktopGuestCustomerOptions.unshift(preferred);
    const select=document.getElementById('desktopGuestCustomerSelect');
    if (select) select.innerHTML='<option value=""></option>'+desktopGuestCustomerOptions.map(name=>`<option value="${desktopGuestEscapeHtml(name)}">${desktopGuestEscapeHtml(name)}</option>`).join('');
    if (select) select.value='';
    const input=document.getElementById('desktopGuestCustomerSearch'); if (input) input.value='';
    document.getElementById('desktopGuestCustomerClear')?.classList.remove('show');
    const selected=document.getElementById('desktopGuestCustomerSelected'); if (selected) selected.hidden=true;
    const existing=document.getElementById('desktopGuestExistingLinks'); if (existing) { existing.hidden=true; existing.innerHTML=''; }
    document.getElementById('desktopGuestCustomerResults').hidden=true;

    const exactPreferred=preferred && desktopGuestCustomerOptions.find(x=>desktopGuestNormalizeCustomerSearch(x)===desktopGuestNormalizeCustomerSearch(preferred));
    if (exactPreferred) desktopGuestChooseCustomer(exactPreferred);
    else if (desktopGuestFilteredCustomers.length===1) desktopGuestChooseCustomer(desktopGuestFilteredCustomers[0]);
    else if (desktopGuestFilteredCustomers.length>1) desktopGuestRenderCustomerResults('');

    desktopGuestShareScope='current'; desktopGuestSetSegment('desktopGuestScope','data-scope','current');
    const lanModeButton=modal.querySelector('#desktopGuestMode [data-share-mode="lan"]');
    const renderModeButton=modal.querySelector('#desktopGuestMode [data-share-mode="render"]');
    if (lanModeButton && !lanModeButton.disabled) desktopGuestSetMode('lan');
    else if (renderModeButton && !renderModeButton.disabled) desktopGuestSetMode('render');
    desktopGuestSetPasswordKind('none');
    document.getElementById('desktopGuestIncludeCancelled').checked=false;
    document.getElementById('desktopGuestShowPdfPages').checked=true;
    document.getElementById('desktopGuestAllowReportPdf').checked=false;
    document.getElementById('desktopGuestCustomPassword').value='';
    document.getElementById('desktopGuestResult').hidden=true;
    desktopGuestCurrentLinkId=''; desktopGuestCurrentLinkMode='lan';
    desktopGuestSetTab('create');
    modal.classList.add('show'); modal.setAttribute('aria-hidden','false'); document.body.classList.add('desktop-guest-share-open');
    if (!desktopGuestSelectedCustomer()) { const preview=document.getElementById('desktopGuestScopePreview'); if (preview) preview.textContent='请先选择客户'; }
    desktopGuestLoadActiveLinks(true);
    if (desktopGuestActiveTimer) clearInterval(desktopGuestActiveTimer);
    desktopGuestActiveTimer=setInterval(()=>{if(modal.classList.contains('show'))desktopGuestLoadActiveLinks(true);},15000);
}
function closeDesktopGuestShareDrawer() {
    const modal=desktopGuestDrawer(); if (!modal) return;
    modal.classList.remove('show'); modal.setAttribute('aria-hidden','true'); document.body.classList.remove('desktop-guest-share-open');
    if (desktopGuestActiveTimer) {clearInterval(desktopGuestActiveTimer); desktopGuestActiveTimer=null;}
}
async function desktopGuestPreviewScope() {
    const box=document.getElementById('desktopGuestScopePreview'), customer=desktopGuestSelectedCustomer();
    if (!box) return; if (!customer){box.textContent='请先选择客户';return;}
    const includeCancelled=!!document.getElementById('desktopGuestIncludeCancelled')?.checked;
    box.textContent='正在计算可分享订单…';
    try {
        const url=`/tracking/api/customers/history-orders?customer_name=${encodeURIComponent(customer)}&scope=${encodeURIComponent(desktopGuestShareScope)}&include_cancelled=${includeCancelled?'1':'0'}`;
        const response=await fetch(url,{credentials:'same-origin',cache:'no-store'}), payload=await response.json().catch(()=>({}));
        if(!response.ok||payload?.success===false)throw new Error();
        const rows=Array.isArray(payload.data)?payload.data:[];
        const cancelled=rows.filter(x=>normalizeStatusForLogic(x.current_status||'')==='CANCELLED').length;
        const completed=rows.filter(x=>normalizeStatusForLogic(x.current_status||'')==='COMPLETED').length;
        const active=Math.max(0,rows.length-cancelled-completed);
        box.textContent=`${rows.length} 笔 · ${active} 进行中 · ${completed} 已完成${includeCancelled?` · ${cancelled} 已取消`:''}`;
    } catch(_){box.textContent='无法预估订单数量';}
}
async function desktopGuestGenerateLink() {
    if (!desktopGuestIsAdmin()) return;
    const customer=desktopGuestSelectedCustomer(), button=document.getElementById('desktopGuestGenerateBtn');
    if (!customer) {showToast('提示','请先选择客户','info');return;}
    if (!button) return;
    const root=desktopGuestDrawer();
    if (desktopGuestShareMode==='lan' && root?.dataset.localEnabled!=='1') {showToast('未开放','此部署不允许局网客户分享','error');return;}
    if (desktopGuestShareMode==='render' && (root?.dataset.renderEnabled!=='1' || root?.dataset.publicProviderReady!=='1')) {showToast('未就绪','Render/B2 分享尚未授权或 Provider 未连接','error');return;}
    const password=desktopGuestResolvePassword();
    if (password.kind!=='none' && password.password.length<4) {showToast('密码','客户手机不存在或密码少于 4 位，请改用自定义密码','error');return;}
    button.disabled=true; const oldText=button.textContent; button.textContent='正在建立…';
    try {
        const endpoint=desktopGuestShareMode==='render'?'/tracking/api/public-guest-links':'/tracking/api/local-guest-links';
        const response=await fetch(endpoint,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({
            customer_name:customer,duration_minutes:desktopGuestShareMinutes,is_permanent:desktopGuestIsPermanent,
            password_kind:password.kind,password:password.password,allow_pdf_download:false,
            show_pdf_pages:!!document.getElementById('desktopGuestShowPdfPages')?.checked,
            allow_report_pdf_download:!!document.getElementById('desktopGuestAllowReportPdf')?.checked,
            history_scope:desktopGuestShareScope,include_cancelled:!!document.getElementById('desktopGuestIncludeCancelled')?.checked
        })});
        const payload=await response.json().catch(()=>({})); if(!response.ok||payload?.success===false)throw new Error(payload?.error||`HTTP ${response.status}`);
        const data=payload.data||{}; desktopGuestCurrentLinkId=String(data.id||data.share_id||''); desktopGuestCurrentLinkMode=desktopGuestShareMode;
        const shareUrl=String(data.url||data.public_url||data.share_url||data.guest_url||'').trim();
        const urlInput=document.getElementById('desktopGuestUrl'), qrImg=document.getElementById('desktopGuestQr');
        if (urlInput) urlInput.value=shareUrl;
        if (qrImg) { qrImg.src=data.qr_data_uri||''; qrImg.hidden=!data.qr_data_uri; }
        const resultTitle=document.getElementById('desktopGuestResultTitle');
        if (resultTitle) resultTitle.textContent=desktopGuestShareMode==='render'?'WEB 公网客户入口':'局网客户入口';
        document.getElementById('desktopGuestExpiry').textContent=data.is_permanent?'永久链接 · 可随时立即失效':`有效至 ${desktopGuestFmtDate(data.expires_at_epoch)}`;
        const resultBox=document.getElementById('desktopGuestResult');
        if (resultBox) {
            resultBox.hidden=false;
            requestAnimationFrame(()=>resultBox.scrollIntoView({behavior:'smooth',block:'nearest'}));
        }
        desktopGuestLoadActiveLinks(true);
    } catch(error){showToast('建立失败',String(error?.message||error),'error');}
    finally{button.disabled=false;button.textContent=oldText;}
}
async function desktopGuestCopyLink(){const input=document.getElementById('desktopGuestUrl'),value=String(input?.value||'');if(!value)return;try{await navigator.clipboard.writeText(value);showToast('已复制','分享链接已复制','success');}catch(_){input.select();try{document.execCommand('copy');}catch(_){}}}
function desktopGuestOpenLink(){const value=String(document.getElementById('desktopGuestUrl')?.value||'');if(value)window.open(value,'_blank','noopener');}
async function desktopGuestCopyValue(value){value=String(value||'').trim();if(!value)return;try{await navigator.clipboard.writeText(value);showToast('已复制','分享链接已复制','success');}catch(_){const input=document.createElement('input');input.value=value;input.style.position='fixed';input.style.opacity='0';document.body.appendChild(input);input.select();try{document.execCommand('copy');showToast('已复制','分享链接已复制','success');}catch(__){}input.remove();}}
function desktopGuestOpenValue(value){value=String(value||'').trim();if(value)window.open(value,'_blank','noopener');}
async function desktopGuestPopulateQuickDetail(detail,mode,id){
    if(!detail||detail.dataset.loaded==='1')return;
    detail.innerHTML='<div class="desktop-guest-active-empty">正在读取详细…</div>';
    try{
        const response=await fetch(`/tracking/api/admin/customer-shares/${encodeURIComponent(mode)}/${encodeURIComponent(id)}`,{credentials:'same-origin',cache:'no-store'});
        const payload=await response.json().catch(()=>({}));
        if(!response.ok||payload?.success===false)throw new Error(payload?.error||`HTTP ${response.status}`);
        const item=payload.data||{};
        const shareUrl=String(item.url||'').trim();
        const qr=String(item.qr_data_uri||'').trim();
        const entryLabel=mode==='render'?'WEB 访问网址':'客户访问网址';
        detail.innerHTML=shareUrl?`<div class="desktop-share-active-entry">${qr?`<img src="${desktopGuestEscapeHtml(qr)}" alt="QR Code">`:''}<div class="desktop-share-active-entry-copy"><small>${entryLabel}</small><input readonly value="${desktopGuestEscapeHtml(shareUrl)}"><div><button type="button" class="copy" data-copy-url="${desktopGuestEscapeHtml(shareUrl)}">一键复制</button><button type="button" class="open" data-open-url="${desktopGuestEscapeHtml(shareUrl)}">打开网页</button></div></div></div>`:`<div class="desktop-share-active-entry desktop-share-active-entry-missing"><div class="desktop-share-active-entry-copy"><small>此分享建立于旧版本，未保存原始网址／二维码；若需要请重新建立新的分享链接。</small></div></div>`;
        detail.querySelectorAll('[data-copy-url]').forEach(btn=>btn.onclick=()=>desktopGuestCopyValue(btn.dataset.copyUrl||''));
        detail.querySelectorAll('[data-open-url]').forEach(btn=>btn.onclick=()=>desktopGuestOpenValue(btn.dataset.openUrl||''));
        detail.dataset.loaded='1';
    }catch(error){
        detail.innerHTML=`<div class="desktop-guest-active-empty error">${desktopGuestEscapeHtml(error?.message||'无法读取详细')}</div>`;
    }
}
async function desktopGuestRevokeId(id,mode='lan'){if(!id)return;const endpoint=mode==='render'?`/tracking/api/public-guest-links/${encodeURIComponent(id)}`:`/tracking/api/local-guest-links/${encodeURIComponent(id)}`;const response=await fetch(endpoint,{method:'DELETE',credentials:'same-origin'}),payload=await response.json().catch(()=>({}));if(!response.ok||payload?.success===false)throw new Error(payload?.error||`HTTP ${response.status}`);}
async function desktopGuestRevokeCurrent(){try{await desktopGuestRevokeId(desktopGuestCurrentLinkId,desktopGuestCurrentLinkMode);document.getElementById('desktopGuestResult').hidden=true;desktopGuestCurrentLinkId='';await desktopGuestLoadActiveLinks(true);showToast('已失效','该分享已立即关闭','success');}catch(error){showToast('操作失败',String(error?.message||error),'error');}}
async function desktopGuestRevokeActive(id,mode,button){if(button)button.disabled=true;try{await desktopGuestRevokeId(id,mode);await desktopGuestLoadActiveLinks(true);}catch(error){showToast('操作失败',String(error?.message||error),'error');}finally{if(button)button.disabled=false;}}
function desktopGuestSetActiveMode(mode){
    desktopGuestActiveMode=mode;
    desktopGuestActivePage=1;
    document.querySelectorAll('[data-active-mode]').forEach(btn=>btn.classList.toggle('active',btn.dataset.activeMode===mode));
    desktopGuestRenderActiveLinks();
}
function desktopGuestActiveSearchChanged(value){
    desktopGuestActiveSearch=String(value||'').trim();
    desktopGuestActivePage=1;
    desktopGuestRenderActiveLinks();
}
function desktopGuestSetActivePage(page){
    const value=Math.max(1,Number(page||1));
    desktopGuestActivePage=value;
    desktopGuestRenderActiveLinks();
    document.querySelector('[data-share-panel="active"]')?.scrollTo?.({top:0,behavior:'smooth'});
}
function desktopGuestToggleAllDetails(){
    desktopGuestActiveShowDetails=!desktopGuestActiveShowDetails;
    const button=document.getElementById('desktopGuestActiveDetailToggle');
    if(button){
        button.classList.toggle('active',desktopGuestActiveShowDetails);
        button.textContent=desktopGuestActiveShowDetails?'收起详细':'显示详细';
    }
    desktopGuestRenderActiveLinks();
}
function desktopGuestActiveFilteredItems(){
    let items=Array.isArray(desktopGuestActiveItemsCache)?desktopGuestActiveItemsCache.slice():[];
    if(desktopGuestActiveMode!=='all')items=items.filter(x=>String(x.share_mode||'lan').toLowerCase()===desktopGuestActiveMode);
    const query=desktopGuestNormalizeCustomerSearch(desktopGuestActiveSearch);
    if(query)items=items.filter(x=>desktopGuestNormalizeCustomerSearch(x.customer_name||'').includes(query));
    items.sort((a,b)=>Number(b.created_at_epoch||b.created_at||0)-Number(a.created_at_epoch||a.created_at||0));
    return items;
}
function desktopGuestRenderActivePagination(total){
    const box=document.getElementById('desktopGuestActivePagination');
    if(!box)return;
    const pages=Math.max(1,Math.ceil(Number(total||0)/desktopGuestActivePageSize));
    if(desktopGuestActivePage>pages)desktopGuestActivePage=pages;
    if(total<=desktopGuestActivePageSize){box.hidden=true;box.innerHTML='';return;}
    const current=desktopGuestActivePage;
    const pageButtons=[];
    const first=Math.max(1,current-2),last=Math.min(pages,current+2);
    if(first>1)pageButtons.push(`<button type="button" onclick="desktopGuestSetActivePage(1)">1</button>${first>2?'<span>…</span>':''}`);
    for(let page=first;page<=last;page++)pageButtons.push(`<button type="button" class="${page===current?'active':''}" onclick="desktopGuestSetActivePage(${page})">${page}</button>`);
    if(last<pages)pageButtons.push(`${last<pages-1?'<span>…</span>':''}<button type="button" onclick="desktopGuestSetActivePage(${pages})">${pages}</button>`);
    box.hidden=false;
    box.innerHTML=`<button type="button" ${current<=1?'disabled':''} onclick="desktopGuestSetActivePage(${current-1})">‹</button>${pageButtons.join('')}<button type="button" ${current>=pages?'disabled':''} onclick="desktopGuestSetActivePage(${current+1})">›</button><small>${total} 条</small>`;
}
function desktopGuestRenderActiveLinks(){
    const list=document.getElementById('desktopGuestActiveList'),count=document.getElementById('desktopGuestActiveCount');
    if(!list)return;
    const allItems=Array.isArray(desktopGuestActiveItemsCache)?desktopGuestActiveItemsCache:[];
    if(count)count.textContent=String(allItems.length);
    let items=desktopGuestActiveFilteredItems();
    const total=items.length;
    const pages=Math.max(1,Math.ceil(total/desktopGuestActivePageSize));
    if(desktopGuestActivePage>pages)desktopGuestActivePage=pages;
    const start=(desktopGuestActivePage-1)*desktopGuestActivePageSize;
    items=items.slice(start,start+desktopGuestActivePageSize);
    const selectedCustomer=desktopGuestSelectedCustomer();
    if(selectedCustomer)desktopGuestRenderExistingLinksHint(selectedCustomer,allItems);
    desktopGuestRenderActivePagination(total);
    if(!items.length){
        const hasFilter=!!desktopGuestActiveSearch||desktopGuestActiveMode!=='all';
        list.innerHTML=`<div class="desktop-guest-active-empty desktop-share-empty-state"><strong>${hasFilter?'没有符合搜索条件的有效分享':'目前没有有效分享'}</strong><small>${hasFilter?'换一个客户名称或筛选条件试试':'建立一个局网或 WEB 链接，客户就能直接查看订单进度'}</small></div>`;
        return;
    }
    list.innerHTML=items.map((item,index)=>{
        const permanent=!!item.is_permanent;
        const mode=String(item.share_mode||'lan').toLowerCase();
        const label=desktopGuestModeBadge(mode);
        const expiry=permanent?'永久':desktopGuestRemaining(item.remaining_seconds);
        const creator=item.created_by_name||item.creator_name||item.created_by||'—';
        const id=item.id||item.share_id||'';
        const detailId=`desktopShareQuickDetail_${desktopGuestActivePage}_${index}`;
        const detailsClass=desktopGuestActiveShowDetails?' show-details':'';
        return `<div class="desktop-guest-active-row compact${detailsClass}">
            <div class="desktop-share-active-customer"><strong>${desktopGuestEscapeHtml(item.customer_name||'')}</strong></div>
            <div class="desktop-share-active-type"><span class="mode-${mode}">${label}</span>${permanent?'<span class="permanent">永久</span>':''}</div>
            <div class="desktop-share-active-expiry ${permanent?'permanent':''}">${desktopGuestEscapeHtml(expiry)}</div>
            <div class="desktop-share-active-actions"><button type="button" class="desktop-share-active-revoke" data-revoke-id="${desktopGuestEscapeHtml(id)}" data-revoke-mode="${mode}">立即失效</button></div>
            <div class="desktop-share-active-meta"><span>建立：${desktopGuestFmtDate(item.created_at_epoch||item.created_at)}</span><span>到期：${permanent?'永久':desktopGuestFmtDate(item.expires_at_epoch)}</span><span>范围：${desktopGuestEscapeHtml(item.history_scope||'current')}</span><span>建立者：${desktopGuestEscapeHtml(creator)}</span></div>
            <div class="desktop-share-quick-detail" id="${detailId}" data-loaded="0" data-detail-id="${desktopGuestEscapeHtml(id)}" data-detail-mode="${mode}" ${desktopGuestActiveShowDetails?'':'hidden'}></div>
        </div>`;
    }).join('');
    list.querySelectorAll('[data-revoke-id]').forEach(btn=>btn.onclick=()=>desktopGuestRevokeActive(btn.dataset.revokeId,btn.dataset.revokeMode||'lan',btn));
    if(desktopGuestActiveShowDetails){
        list.querySelectorAll('.desktop-share-quick-detail').forEach(detail=>desktopGuestPopulateQuickDetail(detail,detail.dataset.detailMode||'lan',detail.dataset.detailId||''));
    }
}
async function desktopGuestLoadActiveLinks(silent=false){
    const list=document.getElementById('desktopGuestActiveList');if(!list)return;
    if(!silent)list.innerHTML='<div class="desktop-guest-active-empty">正在读取…</div>';
    try{
        await desktopGuestCollectActiveItems();
        desktopGuestRenderActiveLinks();
    }catch(error){
        if(!silent)list.innerHTML=`<div class="desktop-guest-active-empty error">${desktopGuestEscapeHtml(error?.message||'无法读取有效分享')}</div>`;
    }
}

document.addEventListener('click',function(event){
    const mode=event.target.closest('#desktopGuestMode [data-share-mode]');if(mode){desktopGuestSetMode(mode.dataset.shareMode);return;}
    const duration=event.target.closest('#desktopGuestLanDuration [data-minutes],#desktopGuestLanDuration [data-permanent],#desktopGuestRenderDuration [data-minutes],#desktopGuestRenderDuration [data-permanent]');if(duration){desktopGuestSetDuration(duration);return;}
    const scope=event.target.closest('#desktopGuestScope [data-scope]');if(scope){desktopGuestShareScope=scope.dataset.scope||'current';desktopGuestSetSegment('desktopGuestScope','data-scope',desktopGuestShareScope);desktopGuestPreviewScope();return;}
    const pwd=event.target.closest('#desktopGuestPasswordKind [data-password-kind]');if(pwd&&!pwd.disabled){desktopGuestSetPasswordKind(pwd.dataset.passwordKind||'none');return;}
    const active=event.target.closest('[data-active-mode]');if(active){desktopGuestSetActiveMode(active.dataset.activeMode||'all');return;}
});
if (window.matchMedia && window.matchMedia('(min-width: 769px)').matches) {
    try {
        const shareParams = new URLSearchParams(window.location.search);
        if (shareParams.get('open_share') === '1') {
            let attempts = 0;
            const openWhenReady = () => {
                attempts += 1;
                if ((typeof homeDataReady !== 'undefined' && homeDataReady) || attempts >= 20) {
                    if (typeof openDesktopGuestShareDrawer === 'function') openDesktopGuestShareDrawer('');
                    shareParams.delete('open_share');
                    const clean = `${window.location.pathname}${shareParams.toString() ? `?${shareParams.toString()}` : ''}${window.location.hash || ''}`;
                    window.history.replaceState({}, '', clean);
                    return;
                }
                window.setTimeout(openWhenReady, 250);
            };
            window.setTimeout(openWhenReady, 250);
        }
    } catch (_) {}
}
document.addEventListener('pointerdown',function(event){const box=document.getElementById('desktopGuestCustomerSearchBox'),results=document.getElementById('desktopGuestCustomerResults');if(box&&results&&!box.contains(event.target))results.hidden=true;});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&desktopGuestDrawer()?.classList.contains('show'))closeDesktopGuestShareDrawer();});
