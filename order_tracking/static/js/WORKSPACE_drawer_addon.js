/**
 * WORKSPACE 决策工作台 - 新增功能补丁 v2.0 FIXED
 * 添加到 WORKSPACE_drawer.js 的末尾
 * 
 * 修复内容：
 * - ✅ 保留原始的 renderFooterActions 和 renderQuickActions 逻辑
 * - ✅ 撤销功能正常工作（使用原有逻辑）
 * - ✅ 时间轴折叠最早的记录，保留最新的
 * - ✅ 优雅的确认对话框
 * - ✅ 笔形 SVG 编辑图标
 * - ✅ 整体字体优化
 */

// ==================== 优雅的确认对话框系统 ====================

WorkspaceDrawer.confirmDialog = {
    createDialog() {
        if (document.getElementById('wsConfirmDialog')) return;
        
        const html = `
            <div id="wsConfirmDialog" class="ws-confirm-overlay hidden">
                <div class="ws-confirm-dialog">
                    <div class="ws-confirm-header">
                        <span class="material-symbols-rounded ws-confirm-icon">warning</span>
                        <h3 class="ws-confirm-title" id="wsConfirmTitle">确认操作</h3>
                    </div>
                    <p class="ws-confirm-message" id="wsConfirmMessage">确定要执行此操作吗？</p>
                    <div class="ws-confirm-actions">
                        <button class="ws-confirm-btn ws-confirm-cancel" id="wsConfirmCancel">
                            <span class="material-symbols-rounded">close</span>
                            取消
                        </button>
                        <button class="ws-confirm-btn ws-confirm-ok" id="wsConfirmOk">
                            <span class="material-symbols-rounded">check</span>
                            确定
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', html);
        
        const overlay = document.getElementById('wsConfirmDialog');
        const cancelBtn = document.getElementById('wsConfirmCancel');
        
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                this.hide();
            }
        });
        
        cancelBtn.addEventListener('click', () => {
            this.hide();
        });
    },
    
    show(options) {
        this.createDialog();
        
        const {
            title = '确认操作',
            message = '确定要执行此操作吗？',
            type = 'warning',
            confirmText = '确定',
            cancelText = '取消',
            onConfirm = () => {},
            onCancel = () => {}
        } = options;
        
        const overlay = document.getElementById('wsConfirmDialog');
        const titleEl = document.getElementById('wsConfirmTitle');
        const messageEl = document.getElementById('wsConfirmMessage');
        const okBtn = document.getElementById('wsConfirmOk');
        const cancelBtn = document.getElementById('wsConfirmCancel');
        const icon = overlay.querySelector('.ws-confirm-icon');
        
        titleEl.textContent = title;
        messageEl.textContent = message;
        okBtn.innerHTML = `<span class="material-symbols-rounded">check</span>${confirmText}`;
        cancelBtn.innerHTML = `<span class="material-symbols-rounded">close</span>${cancelText}`;
        
        icon.textContent = type === 'danger' ? 'error' : type === 'info' ? 'info' : 'warning';
        overlay.className = `ws-confirm-overlay ws-confirm-${type}`;
        
        okBtn.onclick = () => {
            this.hide();
            onConfirm();
        };
        
        overlay.classList.remove('hidden');
        requestAnimationFrame(() => {
            overlay.classList.add('show');
        });
        
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                this.hide();
                onCancel();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    },
    
    hide() {
        const overlay = document.getElementById('wsConfirmDialog');
        if (overlay) {
            overlay.classList.remove('show');
            setTimeout(() => {
                overlay.classList.add('hidden');
            }, 200);
        }
    }
};

// ==================== 时间轴折叠功能（折叠最早的，保留最新的） ====================

WorkspaceDrawer.timelineCollapse = {
    maxVisible: 5, // 默认显示最新的5个
    isCollapsed: true,
    
    init() {
        const container = document.getElementById('wsTimelineContainer');
        if (!container) return;
        
        const items = container.querySelectorAll('.ws-timeline-item');
        
        if (items.length <= this.maxVisible) {
            // 少于等于5个，不需要折叠
            const toggleBtn = container.querySelector('.ws-timeline-toggle');
            if (toggleBtn) {
                toggleBtn.remove();
            }
            return;
        }
        
        // 隐藏最早的项（保留最新的5个）
        this.collapse();
        
        // 添加或更新"展开更多"按钮
        this.addOrUpdateToggleButton();
    },
    
    collapse() {
        const container = document.getElementById('wsTimelineContainer');
        if (!container) return;
        
        const items = container.querySelectorAll('.ws-timeline-item');
        const totalItems = items.length;
        const hiddenCount = totalItems - this.maxVisible;
        
        // 隐藏最早的项（索引 0 到 hiddenCount-1）
        items.forEach((item, index) => {
            if (index < hiddenCount) {
                item.classList.add('ws-timeline-hidden');
            } else {
                item.classList.remove('ws-timeline-hidden');
            }
        });
        
        this.isCollapsed = true;
        this.updateToggleButton();
    },
    
    expand() {
        const container = document.getElementById('wsTimelineContainer');
        if (!container) return;
        
        const items = container.querySelectorAll('.ws-timeline-item');
        items.forEach(item => {
            item.classList.remove('ws-timeline-hidden');
        });
        
        this.isCollapsed = false;
        this.updateToggleButton();
    },
    
    toggle() {
        if (this.isCollapsed) {
            this.expand();
        } else {
            this.collapse();
        }
    },
    
    addOrUpdateToggleButton() {
        const container = document.getElementById('wsTimelineContainer');
        if (!container) return;
        
        const items = container.querySelectorAll('.ws-timeline-item');
        const totalItems = items.length;
        const hiddenCount = totalItems - this.maxVisible;
        
        if (hiddenCount <= 0) return;
        
        let button = container.querySelector('.ws-timeline-toggle');
        
        if (!button) {
            button = document.createElement('button');
            button.className = 'ws-timeline-toggle';
            button.onclick = () => this.toggle();
            container.insertBefore(button, container.firstChild); // 放在最上面
        }
        
        button.innerHTML = `
            <span class="material-symbols-rounded">expand_more</span>
            <span class="ws-timeline-toggle-text">显示更早的 ${hiddenCount} 条记录</span>
        `;
    },
    
    updateToggleButton() {
        const button = document.querySelector('.ws-timeline-toggle');
        if (!button) return;
        
        const container = document.getElementById('wsTimelineContainer');
        const items = container.querySelectorAll('.ws-timeline-item');
        const totalItems = items.length;
        const hiddenCount = totalItems - this.maxVisible;
        
        const icon = button.querySelector('.material-symbols-rounded');
        const text = button.querySelector('.ws-timeline-toggle-text');
        
        if (this.isCollapsed) {
            icon.textContent = 'expand_more';
            text.textContent = `显示更早的 ${hiddenCount} 条记录`;
        } else {
            icon.textContent = 'expand_less';
            text.textContent = '收起';
        }
    }
};

// ==================== 取消订单（使用优雅对话框） ====================

WorkspaceDrawer.handleCancelOrder = function() {
    const self = this;
    
    if (!this.state.currentOrderNumber) {
        console.error('[WorkspaceDrawer] 没有当前订单');
        return;
    }
    
    // 使用优雅的确认对话框
    this.confirmDialog.show({
        title: '取消订单',
        message: `确定要取消订单 #${this.state.currentOrderNumber} 吗？\n\n此操作不可撤销！`,
        type: 'danger',
        confirmText: '确定取消',
        cancelText: '返回',
        onConfirm: () => {
            fetch(`/tracking/api/orders/${this.state.currentOrderNumber}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    new_status: 'CANCELLED',
                    action_date: self.getTodayDate(),
                    notes: '订单已取消'
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    if (typeof showToast === 'function') {
                        showToast('成功', '订单已取消');
                    }
                    
                    if (typeof refreshAllComponents === 'function') {
                        refreshAllComponents(self.state.currentOrderNumber, self.state.currentWorkflowNumber);
                    }
                    
                    setTimeout(() => {
                        self.close();
                    }, 500);
                } else {
                    throw new Error(data.error || '取消失败');
                }
            })
            .catch(error => {
                console.error('[WorkspaceDrawer] 取消订单失败:', error);
                if (typeof showToast === 'function') {
                    showToast('错误', error.message || '取消失败', 'error');
                }
            });
        }
    });
};

// ==================== 获取今天日期 ====================

WorkspaceDrawer.getTodayDate = function() {
    const today = new Date();
    const year = today.getFullYear();
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
};

// ==================== 增强 renderTimeline（添加折叠 + 替换编辑按钮） ====================

WorkspaceDrawer._originalRenderTimeline = WorkspaceDrawer.renderTimeline;
WorkspaceDrawer.renderTimeline = function(history) {
    const self = this;
    
    // 调用原始渲染函数
    if (this._originalRenderTimeline) {
        this._originalRenderTimeline.call(this, history);
    }
    
    // 等待 DOM 更新后添加折叠功能
    setTimeout(() => {
        this.timelineCollapse.init();
        
        // 替换所有编辑按钮为 SVG 图标
        const container = document.getElementById('wsTimelineContainer');
        if (!container) return;
        
        const editButtons = container.querySelectorAll('button[onclick^="editStep"]');
        editButtons.forEach(btn => {
            const onclickValue = btn.getAttribute('onclick');
            
            btn.innerHTML = `
                <svg class="ws-edit-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
            `;
            
            btn.className = 'ws-timeline-edit-btn';
            btn.setAttribute('onclick', onclickValue);
        });
        
        // 替换撤销按钮图标（保持原有功能）
        const undoButtons = container.querySelectorAll('button[onclick*="WorkspaceDrawer.toggleTimelineUndo"]');
        undoButtons.forEach(btn => {
            const onclickValue = btn.getAttribute('onclick');
            btn.innerHTML = '<span class="material-symbols-rounded">undo</span>';
            btn.className = 'ws-timeline-undo-btn';
            btn.setAttribute('onclick', onclickValue);
        });
    }, 100);
};

// ==================== 增强 handleQuickAction（添加刷新逻辑） ====================

WorkspaceDrawer._originalHandleQuickAction = WorkspaceDrawer.handleQuickAction;
WorkspaceDrawer.handleQuickAction = async function(action) {
    const self = this;
    const orderNumber = this.state.currentOrderNumber;
    
    console.log('[WorkspaceDrawer] 快速操作:', action);

    try {
        const res = await fetch(`/tracking/api/workflows/${this.state.currentWorkflowNumber}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: action,
                expected_status: this.state.currentStatus,
                expected_history_id: this.state.lastHistoryId
            })
        });

        const data = await res.json();

        if (data.success) {
            if (typeof showToast === 'function') {
                showToast('成功', data.message || '状态已更新');
            }
            
            // 调用全局刷新
            if (typeof refreshAllComponents === 'function') {
                console.log('[WorkspaceDrawer] 调用 refreshAllComponents 刷新所有 UI');
                refreshAllComponents(orderNumber, self.state.currentWorkflowNumber);
            }
            
            // 重新加载抽屉数据
            setTimeout(() => {
                self.loadData(self.state.currentWorkflowNumber);
            }, 500);
        } else {
            throw new Error(data.error || '更新失败');
        }

    } catch (error) {
        console.error('[WorkspaceDrawer] 快速操作失败:', error);
        if (typeof showToast === 'function') {
            showToast('错误', error.message || '操作失败', 'error');
        }
    }
};

// ==================== 跳过阶段功能（如果需要） ====================

WorkspaceDrawer.skipStage = function() {
    const self = this;
    
    if (!this.state.currentWorkflowNumber) {
        console.error('[WorkspaceDrawer] 没有当前工作流');
        return;
    }
    
    if (!this.state.currentStatus) {
        console.error('[WorkspaceDrawer] 没有当前状态');
        return;
    }
    
    // 使用 tracking.js 中已有的 showSkipStageModal 函数
    if (typeof showSkipStageModal === 'function') {
        showSkipStageModal(this.state.currentOrderNumber, this.state.currentStatus, this.state.currentWorkflowNumber);
    } else {
        console.error('[WorkspaceDrawer] showSkipStageModal 函数未找到');
        if (typeof showToast === 'function') {
            showToast('错误', '跳过阶段功能暂不可用', 'error');
        }
    }
};

// ==================== 监听跳过阶段 Modal 的确认事件 ====================

WorkspaceDrawer.setupSkipStageListener = function() {
    const self = this;
    
    if (typeof confirmSkipStage === 'function' && !WorkspaceDrawer._originalConfirmSkipStage) {
        WorkspaceDrawer._originalConfirmSkipStage = confirmSkipStage;
        
        window.confirmSkipStage = function() {
            const modal = document.getElementById('skipStageModal');
            if (!modal) return;
            
            const orderNumber = modal.dataset.orderNumber;
            
            WorkspaceDrawer._originalConfirmSkipStage.call(this);
            
            setTimeout(() => {
                if (self.state.isOpen && self.state.currentOrderNumber === orderNumber) {
                    // 抽屉开启时只刷新抽屉数据，避免整页刷新导致抽屉关闭
                    setTimeout(() => {
                        self.loadData(self.state.currentWorkflowNumber);
                    }, 400);
                } else if (typeof refreshAllComponents === 'function') {
                    console.log('[WorkspaceDrawer] 跳过阶段成功，调用 refreshAllComponents');
                    refreshAllComponents(orderNumber, self.state.currentWorkflowNumber);
                }
            }, 500);
        };
        
        console.log('[WorkspaceDrawer] 已设置跳过阶段监听器');
    }
};

// ==================== 全局刷新监听器 ====================

WorkspaceDrawer.setupGlobalRefreshListener = function() {
    const self = this;
    
    document.addEventListener('orderStatusUpdated', function(e) {
        const orderNumber = e.detail?.orderNumber;
        if (orderNumber && typeof refreshAllComponents === 'function') {
            console.log('[WorkspaceDrawer] 检测到状态更新事件，刷新所有组件');
            refreshAllComponents(orderNumber);
            
            if (self.state.isOpen && self.state.currentOrderNumber === orderNumber) {
                setTimeout(() => {
                    self.loadData(self.state.currentWorkflowNumber);
                }, 800);
            }
        }
    });
    
    console.log('[WorkspaceDrawer] 已设置全局刷新监听器');
};

// ==================== 修复跳过阶段 Modal 的 z-index ====================

function fixSkipStageModalZIndex() {
    const modal = document.getElementById('skipStageModal');
    if (modal) {
        modal.style.zIndex = '10006';
        const backdrop = modal.previousElementSibling;
        if (backdrop && backdrop.classList.contains('modal-backdrop')) {
            backdrop.style.zIndex = '10005';
        }
    }
}

// ==================== DOM 加载完成后初始化 ====================

document.addEventListener('DOMContentLoaded', function() {
    // 绑定跳过按钮事件（如果有）
    const skipBtn = document.getElementById('wsSkipBtn');
    if (skipBtn) {
        // 如果新弹窗逻辑存在，则不绑定旧逻辑（避免弹出两个 modal）
        if (!WorkspaceDrawer.openSkipStageModal) {
            skipBtn.addEventListener('click', () => WorkspaceDrawer.skipStage());
        }
    }
    
    // 点击其他地方关闭菜单（如果有）
    document.addEventListener('click', function(e) {
        const moreBtn = document.getElementById('wsMoreBtn');
        const moreMenu = document.getElementById('wsMoreMenu');
        if (moreMenu && !moreMenu.classList.contains('hidden')) {
            if (!moreBtn?.contains(e.target) && !moreMenu.contains(e.target)) {
                moreMenu.classList.add('hidden');
            }
        }
    });
    
    // 设置监听器
    setTimeout(() => {
        WorkspaceDrawer.setupSkipStageListener();
        WorkspaceDrawer.setupGlobalRefreshListener();
        fixSkipStageModalZIndex();
    }, 100);
    
    // 监听 Modal 打开事件，修复 z-index
    const observer = new MutationObserver(() => {
        fixSkipStageModalZIndex();
    });
    
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
});

console.log('[WorkspaceDrawer] v2.0 FIXED 已加载：保留原有逻辑 + 优雅对话框 + SVG图标 + 智能折叠');