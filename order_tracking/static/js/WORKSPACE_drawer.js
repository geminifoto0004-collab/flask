/**
 * WORKSPACE 决策工作台 - JavaScript
 * 版本: 1.0.0
 * 依赖: STATUS_SYSTEM.js
 */

(function() {
    'use strict';

    const appPerm = window.AppPermissions || {};
    const isAdminRole = () => (typeof appPerm.isAdmin === 'function' ? appPerm.isAdmin() : false);
    const isSalesRole = () => (typeof appPerm.isSales === 'function' ? appPerm.isSales() : false);
    const canEditWorkflow = () => (typeof appPerm.can === 'function' ? appPerm.can('edit', 'workflow') : false);
    const isCloudReadOnly = () => document.body?.dataset.cloudReadOnly === 'true';

    const WorkspaceDrawer = {
        // 状态管理
        state: {
            isOpen: false,
            currentWorkflowNumber: null,
            currentOrderNumber: null,
            orderOnly: false,
            currentTab: 'admin_ref',
            workflowData: null,
            orderFiles: [],
            workflowFiles: [],
            currentStatus: null,
            allWorkflows: [],  // 同訂單下的所有工作流（用於卡片顯示）
            currentPreviewFileId: null,  // 當前預覽的文件 ID（用於下載）
            currentPreviewFileName: null,  // 當前預覽的文件名
            currentPreviewIsWorkflowFile: false,
            previewImages: [],
            currentPreviewIndex: 0,
            currentRole: 'ADMIN',  // 當前角色：'ADMIN' 或 'SALES'
            uploadContext: null,  // 上傳上下文：true=admin | false=sales
            adminImageFiles: [],
            salesImageFiles: [],
            adminSelectionMode: false,
            salesSelectionMode: false,
            adminSelectedIds: new Set(),
            salesSelectedIds: new Set(),
            showImageDate: true,
            adminRemarkEditing: false,
            salesRemarkEditing: false,
            transferUsers: []
        },

        // DOM 元素缓存
        elements: {},

        /**
         * 初始化
         */
        init() {
            console.log('[WorkspaceDrawer] 初始化中...');
            this.cacheElements();
            this.initImageDatePreference();
            this.attachEvents();
            console.log('[WorkspaceDrawer] 初始化完成');
        },

        /**
         * 缓存 DOM 元素
         */
        cacheElements() {
            const overlay = document.getElementById('wsOverlay');
            const container = document.getElementById('wsContainer');
            const closeBtn = document.getElementById('wsCloseBtn');
            
            console.log('[WorkspaceDrawer] 緩存 DOM 元素:', {
                overlay: !!overlay,
                container: !!container,
                closeBtn: !!closeBtn
            });
            
            if (!overlay) {
                console.error('[WorkspaceDrawer] 找不到 wsOverlay 元素！');
            }
            if (!container) {
                console.error('[WorkspaceDrawer] 找不到 wsContainer 元素！');
            }
            
            this.elements = {
                overlay: overlay,
                container: container,
                closeBtn: closeBtn,
                
                // 预览面板
                previewPanel: document.getElementById('wsPreviewPanel'),
                previewImg: document.getElementById('wsPreviewImg'),
                previewName: document.getElementById('wsPreviewName'),
                previewCloseBtn: document.getElementById('wsPreviewCloseBtn'),
                previewDownloadBtn: document.getElementById('wsPreviewDownloadBtn'),
                previewCounter: document.getElementById('wsPreviewCounter'),
                previewPrevBtn: document.getElementById('wsPreviewPrev'),
                previewNextBtn: document.getElementById('wsPreviewNext'),
                previewImageContainer: document.getElementById('wsPreviewImageContainer'),
                previewFullscreen: document.getElementById('wsPreviewFullscreen'),
                previewFullscreenImage: document.getElementById('wsPreviewFullscreenImage'),
                previewFullscreenTitle: document.getElementById('wsPreviewFullscreenTitle'),
                previewFullscreenClose: document.getElementById('wsPreviewFullscreenClose'),
                previewFullscreenPrev: document.getElementById('wsPreviewFullscreenPrev'),
                previewFullscreenNext: document.getElementById('wsPreviewFullscreenNext'),
                previewMeta: document.getElementById('wsPreviewMeta'),
                previewFullscreenMeta: document.getElementById('wsPreviewFullscreenMeta'),
                
                // Header
                orderNumber: document.getElementById('wsOrderNumber'),
                customerName: document.getElementById('wsCustomerName'),
                
                // 工作流卡片
                workflowCard: document.getElementById('wsWorkflowCard'),
                workflowPrevBtn: document.getElementById('wsWorkflowPrev'),
                workflowNextBtn: document.getElementById('wsWorkflowNext'),
                
                // TAB 按钮
                tabAdminRef: document.getElementById('wsTabAdminRef'),
                tabProcess: document.getElementById('wsTabProcess'),
                tabFiles: document.getElementById('wsTabFiles'),
                
                // TAB 内容
                contentAdminRef: document.getElementById('wsContentAdminRef'),
                contentProcess: document.getElementById('wsContentProcess'),
                contentFiles: document.getElementById('wsContentFiles'),
                
                // TAB 1: 主管参考
                adminRemark: document.getElementById('wsAdminRemark'),
                adminRemarkTime: document.getElementById('wsAdminRemarkTime'),
                adminRemarkEditBtn: document.getElementById('wsAdminRemarkEditBtn'),
                adminRemarkEdit: document.getElementById('wsAdminRemarkEdit'),
                adminRemarkInput: document.getElementById('wsAdminRemarkInput'),
                adminRemarkSaveBtn: document.getElementById('wsAdminRemarkSaveBtn'),
                adminRemarkCancelBtn: document.getElementById('wsAdminRemarkCancelBtn'),
                adminImageGrid: document.getElementById('wsAdminImageGrid'),
                adminFileList: document.getElementById('wsAdminFileList'),
                adminUploadBtn: document.getElementById('wsAdminUploadBtn'),
                adminSelectBtn: document.getElementById('wsAdminSelectBtn'),
                adminDeleteBtn: document.getElementById('wsAdminDeleteBtn'),
                adminDateToggleBtn: document.getElementById('wsAdminDateToggleBtn'),
                
                // TAB 2: 流程进度
                salesAvatar: document.getElementById('wsSalesAvatar'),
                salesRemark: document.getElementById('wsSalesRemark'),
                salesRemarkEditBtn: document.getElementById('wsSalesRemarkEditBtn'),
                salesRemarkEdit: document.getElementById('wsSalesRemarkEdit'),
                salesRemarkInput: document.getElementById('wsSalesRemarkInput'),
                salesRemarkSaveBtn: document.getElementById('wsSalesRemarkSaveBtn'),
                salesRemarkCancelBtn: document.getElementById('wsSalesRemarkCancelBtn'),
                transferBtn: document.getElementById('wsTransferBtn'),
                transferModal: document.getElementById('wsTransferModal'),
                transferUserSearch: document.getElementById('wsTransferUserSearch'),
                transferUserOptions: document.getElementById('wsTransferUserOptions'),
                transferUserId: document.getElementById('wsTransferUserId'),
                transferConfirmBtn: document.getElementById('wsTransferConfirmBtn'),
                timelineContainer: document.getElementById('wsTimelineContainer'),
                
                // TAB 3: 业务附件
                salesImageGrid: document.getElementById('wsSalesImageGrid'),
                salesFileList: document.getElementById('wsSalesFileList'),
                salesUploadBtn: document.getElementById('wsSalesUploadBtn'),
                salesSelectBtn: document.getElementById('wsSalesSelectBtn'),
                salesDeleteBtn: document.getElementById('wsSalesDeleteBtn'),
                salesDateToggleBtn: document.getElementById('wsSalesDateToggleBtn'),
                uploadModal: document.getElementById('wsUploadModal'),
                uploadModalTitle: document.getElementById('wsUploadModalTitle'),
                
                // 底部快速操作
                quickActionsFooter: document.getElementById('wsQuickActionsFooter'),
                quickActionsGrid: document.getElementById('wsQuickActionsGrid'),
                orderManagementGrid: document.getElementById('wsOrderManagementGrid'),
                quickActionBtn: document.getElementById('wsQuickActionBtn'),
                skipBtn: document.getElementById('wsSkipBtn'),
                footer: document.getElementById('wsFooter')
            };

            // 確保全屏預覽不受抽屜 transform 影響
            if (this.elements.previewFullscreen && this.elements.previewFullscreen.parentElement !== document.body) {
                document.body.appendChild(this.elements.previewFullscreen);
            }
        },

        /**
         * 绑定事件
         */
        attachEvents() {
            const self = this;

            // 关闭按钮
            if (this.elements.closeBtn) {
                this.elements.closeBtn.addEventListener('click', () => self.close());
            }
            // Overlay 不關閉抽屜，允許點擊主頁面

            // 预览关闭
            if (this.elements.previewCloseBtn) {
                this.elements.previewCloseBtn.addEventListener('click', () => self.closePreview());
            }
            if (this.elements.previewPrevBtn) {
                this.elements.previewPrevBtn.addEventListener('click', () => self.prevPreviewImage());
            }
            if (this.elements.previewNextBtn) {
                this.elements.previewNextBtn.addEventListener('click', () => self.nextPreviewImage());
            }
            if (this.elements.previewImageContainer) {
                this.elements.previewImageContainer.addEventListener('click', () => self.togglePreviewFullscreen(true));
            }
            if (this.elements.previewFullscreenClose) {
                this.elements.previewFullscreenClose.addEventListener('click', () => self.togglePreviewFullscreen(false));
            }
            if (this.elements.previewFullscreenPrev) {
                this.elements.previewFullscreenPrev.addEventListener('click', () => self.prevPreviewImage());
            }
            if (this.elements.previewFullscreenNext) {
                this.elements.previewFullscreenNext.addEventListener('click', () => self.nextPreviewImage());
            }

            // 预览下载
            if (this.elements.previewDownloadBtn) {
                this.elements.previewDownloadBtn.addEventListener('click', () => {
                    if (self.state.currentPreviewFileId) {
                        const downloadUrl = self.state.currentPreviewIsWorkflowFile
                            ? `/tracking/api/workflows/${self.state.currentWorkflowNumber}/files/${self.state.currentPreviewFileId}/download`
                            : `/tracking/api/orders/files/${self.state.currentPreviewFileId}/download`;
                        window.open(downloadUrl, '_blank');
                    }
                });
            }

            // TAB 切换
            if (this.elements.tabAdminRef) {
                this.elements.tabAdminRef.addEventListener('click', () => self.switchTab('admin_ref'));
            }
            if (this.elements.tabProcess) {
                this.elements.tabProcess.addEventListener('click', () => self.switchTab('process'));
            }
            if (this.elements.tabFiles) {
                this.elements.tabFiles.addEventListener('click', () => self.switchTab('files'));
            }

            // 工作流卡片导航
            if (this.elements.workflowPrevBtn) {
                this.elements.workflowPrevBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    self.scrollWorkflowCards(-1);
                });
            }
            if (this.elements.workflowNextBtn) {
                this.elements.workflowNextBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    self.scrollWorkflowCards(1);
                });
            }
            if (this.elements.workflowCard) {
                this.elements.workflowCard.addEventListener('scroll', () => self.updateWorkflowNav());
            }
            window.addEventListener('resize', () => self.updateWorkflowNav());

            // 上传拖拽区域
            const dropzone = document.getElementById('wsUploadDropzone');
            const fileInput = document.getElementById('wsUploadFiles');
            if (dropzone && fileInput) {
                dropzone.addEventListener('click', () => fileInput.click());
                dropzone.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    dropzone.classList.add('dragover');
                });
                dropzone.addEventListener('dragleave', () => {
                    dropzone.classList.remove('dragover');
                });
                dropzone.addEventListener('drop', (e) => {
                    e.preventDefault();
                    dropzone.classList.remove('dragover');
                    const dt = e.dataTransfer;
                    if (dt && dt.files && dt.files.length) {
                        const dataTransfer = new DataTransfer();
                        Array.from(dt.files).forEach(file => dataTransfer.items.add(file));
                        fileInput.files = dataTransfer.files;
                        self.updateUploadFileList(fileInput.files);
                    }
                });
                fileInput.addEventListener('change', () => {
                    self.updateUploadFileList(fileInput.files);
                });
            }

            // 上传附件（管理员/业务员分开）
                if (this.elements.adminUploadBtn) {
                    this.elements.adminUploadBtn.addEventListener('click', () => {
                        self.openUploadModal(true);
                    });
                }
                if (this.elements.adminSelectBtn) {
                    this.elements.adminSelectBtn.addEventListener('click', () => {
                        self.toggleSelectionMode(true);
                    });
                }
            if (this.elements.adminDeleteBtn) {
                this.elements.adminDeleteBtn.addEventListener('click', () => {
                    self.deleteSelectedImages(true);
                });
            }
                if (this.elements.salesUploadBtn) {
                    this.elements.salesUploadBtn.addEventListener('click', () => {
                        self.openUploadModal(false);
                    });
                }
                if (this.elements.salesSelectBtn) {
                    this.elements.salesSelectBtn.addEventListener('click', () => {
                        self.toggleSelectionMode(false);
                    });
                }
            if (this.elements.salesDeleteBtn) {
                this.elements.salesDeleteBtn.addEventListener('click', () => {
                    self.deleteSelectedImages(false);
                });
            }
            if (this.elements.adminDateToggleBtn) {
                this.elements.adminDateToggleBtn.addEventListener('click', () => {
                    self.toggleImageDate();
                });
            }
            if (this.elements.salesDateToggleBtn) {
                this.elements.salesDateToggleBtn.addEventListener('click', () => {
                    self.toggleImageDate();
                });
            }

            // 备注编辑（主管/业务员）
            if (this.elements.adminRemarkEditBtn) {
                this.elements.adminRemarkEditBtn.addEventListener('click', () => {
                    self.toggleRemarkEdit('admin', true);
                });
            }
            if (this.elements.adminRemarkSaveBtn) {
                this.elements.adminRemarkSaveBtn.addEventListener('click', () => {
                    self.saveRemark('admin');
                });
            }
            if (this.elements.adminRemarkCancelBtn) {
                this.elements.adminRemarkCancelBtn.addEventListener('click', () => {
                    self.toggleRemarkEdit('admin', false);
                });
            }
            if (this.elements.salesRemarkEditBtn) {
                this.elements.salesRemarkEditBtn.addEventListener('click', () => {
                    self.toggleRemarkEdit('sales', true);
                });
            }
            if (this.elements.salesRemarkSaveBtn) {
                this.elements.salesRemarkSaveBtn.addEventListener('click', () => {
                    self.saveRemark('sales');
                });
            }
            if (this.elements.salesRemarkCancelBtn) {
                this.elements.salesRemarkCancelBtn.addEventListener('click', () => {
                    self.toggleRemarkEdit('sales', false);
                });
            }
            if (this.elements.transferBtn) {
                this.elements.transferBtn.addEventListener('click', () => {
                    self.openTransferModal();
                });
            }
            if (this.elements.transferUserSearch) {
                this.elements.transferUserSearch.addEventListener('input', () => {
                    self.syncTransferUserIdFromInput();
                });
                this.elements.transferUserSearch.addEventListener('change', () => {
                    self.syncTransferUserIdFromInput();
                });
            }
            if (this.elements.transferConfirmBtn) {
                this.elements.transferConfirmBtn.addEventListener('click', () => {
                    self.confirmTransfer();
                });
            }

            // 跳过阶段
            if (this.elements.skipBtn) {
                this.elements.skipBtn.addEventListener('click', () => self.openSkipStageModal());
            }

            // ESC 键关闭
            document.addEventListener('keydown', (e) => {
                if (!self.state.isOpen) return;
                const confirmModal = document.getElementById('confirmModal');
                if (confirmModal && confirmModal.classList.contains('show')) {
                    return;
                }
                if (self.elements.previewFullscreen && !self.elements.previewFullscreen.classList.contains('hidden')) {
                    if (e.key === 'Escape') {
                        self.togglePreviewFullscreen(false);
                        return;
                    }
                    if (e.key === 'ArrowLeft') {
                        e.preventDefault();
                        self.prevPreviewImage();
                        return;
                    }
                    if (e.key === 'ArrowRight') {
                        e.preventDefault();
                        self.nextPreviewImage();
                        return;
                    }
                }
                if (e.key === 'Escape') {
                    self.close();
                }
            });
        },

        /**
         * 打开抽屉（使用 workflow_number）
         */
        open(workflowNumber) {
            const self = this;
            console.log('[WorkspaceDrawer] 打开工作流:', workflowNumber);
            console.log('[WorkspaceDrawer] DOM 元素:', {
                overlay: !!this.elements.overlay,
                container: !!this.elements.container,
                closeBtn: !!this.elements.closeBtn
            });

            this.state.currentWorkflowNumber = workflowNumber;
            this.state.currentOrderNumber = workflowNumber.split('-')[0];
            this.state.orderOnly = false;
            // 抽屜已開著：保持當前 tab；抽屜關閉後重新開：已在 close() 重置為 admin_ref

            // 显示抽屉
            this.show();
            console.log('[WorkspaceDrawer] show() 已調用，isOpen:', this.state.isOpen);

            // 加载数据
            this.loadData(workflowNumber);
        },

        /**
         * 确保跳过阶段弹窗存在
         */
        ensureSkipStageModal() {
            if (document.getElementById('wsSkipStageModal')) return;

            const modal = document.createElement('div');
            modal.id = 'wsSkipStageModal';
            modal.className = 'ws-skip-modal-overlay hidden';
            modal.innerHTML = `
                <div class="ws-skip-modal">
                    <div class="ws-skip-modal-header">
                        <h3>跳过阶段</h3>
                        <button class="ws-skip-modal-close" type="button">×</button>
                    </div>
                    <div class="ws-skip-modal-body">
                        <div class="ws-skip-current">
                            当前状态：<span id="wsSkipCurrentStatus">-</span>
                        </div>
                        <div id="wsSkipStageOptions" class="ws-skip-options"></div>
                        <div class="ws-skip-notes">
                            <label for="wsSkipStageNotes">备注</label>
                            <textarea id="wsSkipStageNotes" class="ws-inline-editor-input" rows="3" placeholder="輸入備註..."></textarea>
                        </div>
                    </div>
                    <div class="ws-skip-modal-actions">
                        <button class="ws-skip-cancel" type="button">取消</button>
                        <button class="ws-skip-confirm" type="button">确认跳过</button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            // 绑定关闭/取消
            modal.addEventListener('click', (e) => {
                if (e.target === modal) this.closeSkipStageModal();
            });
            modal.querySelector('.ws-skip-modal-close')
                .addEventListener('click', () => this.closeSkipStageModal());
            modal.querySelector('.ws-skip-cancel')
                .addEventListener('click', () => this.closeSkipStageModal());
            modal.querySelector('.ws-skip-confirm')
                .addEventListener('click', () => this.confirmSkipStage());
        },

        /**
         * 打开跳过阶段弹窗（WORKSPACE 专用）
         */
        openSkipStageModal() {
            if (!this.state.currentWorkflowNumber || !this.state.currentStatus) {
                if (typeof showToast === 'function') {
                    showToast('错误', '没有当前工作流或状态', 'error');
                }
                return;
            }

            if (typeof getSkippableStatuses !== 'function') {
                if (typeof showToast === 'function') {
                    showToast('错误', '跳过阶段功能暂不可用', 'error');
                }
                return;
            }

            this.ensureSkipStageModal();

            // 关闭旧的跳过阶段弹窗（避免出现两个 Modal）
            const legacyModal = document.getElementById('skipStageModal');
            if (legacyModal) {
                legacyModal.classList.remove('show');
                legacyModal.style.display = 'none';
            }

            const modal = document.getElementById('wsSkipStageModal');
            const currentStatusEl = document.getElementById('wsSkipCurrentStatus');
            const optionsContainer = document.getElementById('wsSkipStageOptions');
            const notesField = document.getElementById('wsSkipStageNotes');

            if (currentStatusEl) {
                currentStatusEl.textContent = typeof displayStatus === 'function'
                    ? displayStatus(this.state.currentStatus)
                    : this.state.currentStatus;
            }

            const skippableStatuses = getSkippableStatuses(this.state.currentStatus);
            if (!skippableStatuses || skippableStatuses.length === 0) {
                if (typeof showToast === 'function') {
                    showToast('提示', '当前状态无法跳过到其他阶段');
                }
                return;
            }

            let optionsHTML = '';
            skippableStatuses.forEach((status, index) => {
                const displayName = typeof displayStatus === 'function' ? displayStatus(status) : status;
                const icon = typeof getStatusIcon === 'function' ? getStatusIcon(status) : 'skip_next';
                const stageName = typeof getStageName === 'function' ? getStageName(status) : '';
                optionsHTML += `
                    <label class="ws-skip-option">
                        <input type="radio" name="wsSkipTarget" value="${status}" ${index === 0 ? 'checked' : ''}>
                        <span class="ws-skip-option-content">
                            <span class="ws-skip-option-icon">${icon}</span>
                            <span class="ws-skip-option-text">
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

            if (notesField) {
                notesField.value = '';
            }

            modal.classList.remove('hidden');
            modal.classList.add('show');
        },

        /**
         * 关闭跳过阶段弹窗
         */
        closeSkipStageModal() {
            const modal = document.getElementById('wsSkipStageModal');
            if (!modal) return;
            modal.classList.add('hidden');
            modal.classList.remove('show');
        },

        /**
         * 确认跳过阶段（WORKSPACE 专用）
         */
        async confirmSkipStage() {
            const modal = document.getElementById('wsSkipStageModal');
            if (!modal) return;

            const selectedTarget = modal.querySelector('input[name="wsSkipTarget"]:checked');
            const notesField = document.getElementById('wsSkipStageNotes');
            const notes = notesField ? notesField.value : '';

            if (!selectedTarget) {
                if (typeof showToast === 'function') {
                    showToast('错误', '请选择目标阶段', 'error');
                }
                return;
            }

            const targetStatus = selectedTarget.value;
            const targetDisplayName = typeof displayStatus === 'function' ? displayStatus(targetStatus) : targetStatus;

            let actionDate = getTodayDate ? getTodayDate() : new Date().toISOString().split('T')[0];
            let finalNotes = notes || '';
            if (typeof isShippingStatus === 'function' && isShippingStatus(targetStatus) && typeof requestShippingActionDetails === 'function') {
                const details = await requestShippingActionDetails({
                    action: targetStatus === 'PARTIAL_SHIPPED' ? 'ship_partial' : (targetStatus === 'ALL_SHIPPED' ? 'ship_all' : 'shipping_complete'),
                    orderNumber: this.state.currentWorkflowNumber || this.state.currentOrderNumber,
                    currentStatus: this.state.currentStatus,
                    nextStatus: targetStatus,
                    notes
                });
                if (!details) return;
                actionDate = details.date;
                finalNotes = details.notes || finalNotes;
            }

            try {
                const res = await fetch(`/tracking/api/workflows/${encodeURIComponent(this.state.currentWorkflowNumber)}/status-direct`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        new_status: targetStatus,
                        expected_status: this.state.currentStatus,
                        expected_history_id: this.state.lastHistoryId,
                        action_date: actionDate,
                        notes: finalNotes
                    })
                });
                const data = await res.json();
                if (!data.success) throw new Error(data.error || '操作失败');

                if (typeof showToast === 'function') {
                    showToast('跳过成功', `已从「${displayStatus(this.state.currentStatus)}」跳到「${targetDisplayName}」`);
                }

                this.closeSkipStageModal();
                if (typeof refreshAllComponents === 'function') {
                    refreshAllComponents(this.state.currentOrderNumber, this.state.currentWorkflowNumber);
                }
                this.loadData(this.state.currentWorkflowNumber);
                window.dispatchEvent(new CustomEvent('tracking:workspace-updated', {detail:{
                    orderNumber: this.state.currentOrderNumber || '',
                    workflowNumber: this.state.currentWorkflowNumber || ''
                }}));
            } catch (error) {
                if (typeof showToast === 'function') {
                    showToast('跳过失败', error.message || '操作失败', 'error');
                }
            }
        },

        /**
         * 从订单号打开抽屉（自动获取第一个工作流）
         */
        async openFromOrder(orderNumber) {
            const self = this;
            console.log('[WorkspaceDrawer] 从订单号打开:', orderNumber);

            try {
                // 获取该订单的所有工作流
                const res = await fetch(`/tracking/api/workflows?order=${encodeURIComponent(orderNumber)}`);
                const data = await res.json();

                const workflows = data.success && data.data && data.data.workflows;
                if (!workflows || workflows.length === 0) {
                    await self.openOrderOnly(orderNumber);
                    return;
                }

                // 使用第一个工作流打开抽屉
                const firstWorkflow = workflows[0];
                self.open(firstWorkflow.workflow_number);

            } catch (error) {
                console.error('[WorkspaceDrawer] 从订单号打开失败，降级为 orderOnly:', error);
                // 不 throw，改為降級開抽屜（order-only 模式）
                try { await self.openOrderOnly(orderNumber); } catch(e2) {}
            }
        },

        /**
         * 仅以订单号打开抽屉（没有工作流时）
         */
        async openOrderOnly(orderNumber) {
            const self = this;
            this.state.currentOrderNumber = orderNumber;
            this.state.currentWorkflowNumber = '';
            this.state.orderOnly = true;
            this.state.workflowFiles = [];
            this.state.allWorkflows = [];
            this.state.currentStatus = null;

            // 显示抽屉
            this.show();

            try {
                const [orderRes, orderFilesRes] = await Promise.all([
                    fetch(`/tracking/api/orders/${orderNumber}`),
                    fetch(`/tracking/api/orders/${orderNumber}/files`)
                ]);

                const orderData = await orderRes.json();
                const orderFilesData = await orderFilesRes.json();

                if (orderData.success && orderData.data) {
                    const order = orderData.data;
                    this.state.workflowData = {
                        order_number: order.order_number,
                        customer_name: order.customer_name,
                        order_notes: order.notes || '',
                        workflow_number: '',
                        current_status: '',
                        handler_name: ''
                    };
                } else {
                    throw new Error(orderData.error || '订单资料加载失败');
                }

                if (orderFilesData.success) {
                    this.state.orderFiles = orderFilesData.data.files || [];
                } else {
                    this.state.orderFiles = [];
                }

                self.renderAll();
            } catch (error) {
                console.error('[WorkspaceDrawer] 订单模式加载失败:', error);
                if (typeof showToast === 'function') {
                    showToast('错误', error.message || '无法加载订单资料', 'error');
                }
            }
        },

        /**
         * 显示抽屉（动画）
         */
        show() {
            console.log('[WorkspaceDrawer] show() 開始執行');
            
            if (!this.elements.overlay) {
                console.error('[WorkspaceDrawer] overlay 元素不存在！');
                return;
            }
            
            if (!this.elements.container) {
                console.error('[WorkspaceDrawer] container 元素不存在！');
                return;
            }

            // 顯示 overlay
            this.elements.overlay.classList.remove('hidden');
            this.elements.overlay.style.display = 'block';
            this.elements.overlay.style.visibility = 'visible';
            console.log('[WorkspaceDrawer] overlay 顯示設置完成');
            
            setTimeout(() => {
                this.elements.overlay.classList.remove('opacity-0');
                this.elements.overlay.classList.add('opacity-100');
                this.elements.overlay.style.opacity = '1';
                console.log('[WorkspaceDrawer] overlay 透明度設置完成');
            }, 10);

            // 顯示 container
            this.elements.container.style.display = 'flex';
            this.elements.container.style.visibility = 'visible';
            console.log('[WorkspaceDrawer] container 顯示設置完成');
            
            setTimeout(() => {
                this.elements.container.classList.remove('translate-x-full');
                this.elements.container.style.transform = 'translateX(0)';
                console.log('[WorkspaceDrawer] container 位置設置完成，transform:', this.elements.container.style.transform);
            }, 10);

            this.state.isOpen = true;
            console.log('[WorkspaceDrawer] show() 執行完成，isOpen:', this.state.isOpen);
        },

        /**
         * 关闭抽屉
         */
        close() {
            if (this.elements.container) {
                this.elements.container.classList.add('translate-x-full');
                this.elements.container.style.transform = 'translateX(100%)';
            }
            if (this.elements.overlay) {
                this.elements.overlay.classList.remove('opacity-100');
                this.elements.overlay.classList.add('opacity-0');
                this.elements.overlay.style.opacity = '0';
            }

            // 立即重置 tab，不等動畫結束
            this.state.currentTab = 'admin_ref';

            setTimeout(() => {
                if (this.elements.overlay) {
                    this.elements.overlay.classList.add('hidden');
                    this.elements.overlay.style.display = 'none';
                }
                if (this.elements.container) {
                    this.elements.container.style.display = 'none';
                }
                this.closePreview();
                this.closeTransferModal();
                this.state.isOpen = false;
            }, 300);
        },

        /**
         * 加载数据
         */
        async loadData(workflowNumber) {
            const self = this;
            const orderNumber = workflowNumber.split('-')[0];

            try {
                // 并行请求数据（包括获取同訂單的所有工作流）
                // 使用 allSettled 避免单个请求失败导致整体崩溃
                const [workflowResult, orderFilesResult, workflowFilesResult, allWorkflowsResult] = await Promise.allSettled([
                    fetch(`/tracking/api/workflows/${workflowNumber}`).then(r => r.json()),
                    fetch(`/tracking/api/orders/${orderNumber}/files`).then(r => r.json()),
                    fetch(`/tracking/api/workflows/${workflowNumber}/files`).then(r => r.json()),
                    fetch(`/tracking/api/workflows?order=${encodeURIComponent(orderNumber)}`).then(r => r.json())
                ]);

                const workflowData      = workflowResult.status      === 'fulfilled' ? workflowResult.value      : null;
                const orderFilesData    = orderFilesResult.status     === 'fulfilled' ? orderFilesResult.value     : null;
                const workflowFilesData = workflowFilesResult.status  === 'fulfilled' ? workflowFilesResult.value  : null;
                const allWorkflowsData  = allWorkflowsResult.status   === 'fulfilled' ? allWorkflowsResult.value   : null;

                // 主流程数据加载失败才报错（其他附件失败只 warn）
                if (!workflowData || !workflowData.success) {
                    console.error('[WorkspaceDrawer] 主流程数据加载失败', workflowResult.reason || workflowData);
                    if (typeof showToast === 'function') {
                        showToast('错误', '无法加载流程数据', 'error');
                    }
                    return;
                }

                self.state.workflowData = workflowData.data;
                self.state.currentStatus = workflowData.data.current_status;
                self.state.lastHistoryId = workflowData.data.last_history_id || null;

                if (orderFilesData && orderFilesData.success) {
                    self.state.orderFiles = orderFilesData.data.files || [];
                } else {
                    console.warn('[WorkspaceDrawer] 主管附件加载失败', orderFilesResult.reason);
                }

                if (workflowFilesData && workflowFilesData.success) {
                    self.state.workflowFiles = workflowFilesData.data.files || [];
                } else {
                    console.warn('[WorkspaceDrawer] 业务附件加载失败', workflowFilesResult.reason);
                }

                if (allWorkflowsData && allWorkflowsData.success) {
                    self.state.allWorkflows = allWorkflowsData.data.workflows || [];
                } else {
                    console.warn('[WorkspaceDrawer] 并行流程列表加载失败', allWorkflowsResult.reason);
                }

                // 渲染所有内容
                self.renderAll();

            } catch (error) {
                console.error('[WorkspaceDrawer] 加载数据失败:', error);
                if (typeof showToast === 'function') {
                    showToast('错误', '无法加载数据', 'error');
                }
            }
        },

        /**
         * 渲染所有内容
         */
        renderAll() {
            if (!this.state.workflowData) {
                console.warn('[WorkspaceDrawer] 无数据，跳过渲染');
                return;
            }
            this.applyPermissionVisibility();
            this.applyOrderOnlyLayout();
            this.renderHeader();

            if (this.state.orderOnly) {
                this.renderAdminRef();
                this.applyCloudReadonlyVisual();
                this._syncPreviewAfterRender();
                return;
            }

            this.renderWorkflowCard();
            this.renderAdminRef();
            this.renderProcess();
            this.renderFiles();
            this.renderQuickActions();
            this.renderFooterActions();
            this.applyCloudReadonlyVisual();

            this._syncPreviewAfterRender();
        },

        /**
         * 如果預覽面板是開著的，切換流程後同步更新預覽圖片。
         * 無論是有流程還是 orderOnly 模式都需要執行。
         */
        _syncPreviewAfterRender() {
            const isPreviewOpen = this.elements.previewPanel &&
                this.elements.previewPanel.style.width === '420px';
            if (!isPreviewOpen) return;

            // 依照當前 tab 決定預覽來源，不跨 tab 降級
            const currentTab = this.state.currentTab || 'admin_ref';
            if (currentTab === 'files') {
                this.state.currentPreviewIsWorkflowFile = true;
                const images = this.state.salesImageFiles || [];
                if (images.length > 0) {
                    this.openPreviewWorkflowImage(0);
                } else {
                    this._showPreviewNoImage();
                }
            } else if (currentTab === 'admin_ref') {
                this.state.currentPreviewIsWorkflowFile = false;
                const images = this.state.adminImageFiles || [];
                if (images.length > 0) {
                    this.openPreviewImage(0);
                } else {
                    this._showPreviewNoImage();
                }
            }
        },
        /**
         * 根据角色控制按钮可见性
         */
        applyPermissionVisibility() {
            const canOperate = this.canOperate();
            const isAdmin = this.isAdmin();
            const isSales = this.isSales();

            const toggleHidden = (el, hidden) => {
                if (!el) return;
                el.classList.toggle('hidden', hidden);
            };

            // 主管参考区按钮
            toggleHidden(this.elements.adminRemarkEditBtn, !canOperate || !isAdmin);
            toggleHidden(this.elements.adminUploadBtn, !canOperate || !isAdmin);
            toggleHidden(this.elements.adminSelectBtn, !canOperate || !isAdmin);
            toggleHidden(this.elements.adminDeleteBtn, !canOperate || !isAdmin);

            // 流程进度区按钮
            toggleHidden(this.elements.transferBtn, !canOperate || !isAdmin);
            toggleHidden(this.elements.salesRemarkEditBtn, !canOperate || !isSales);

            // 业务附件区按钮
            toggleHidden(this.elements.salesUploadBtn, !canOperate);
            toggleHidden(this.elements.salesSelectBtn, !canOperate);
            toggleHidden(this.elements.salesDeleteBtn, !canOperate);

            // 底部操作栏
            if (this.elements.footer) {
                this.elements.footer.style.display = canOperate ? '' : 'none';
            }
            if (this.elements.quickActionBtn) {
                this.elements.quickActionBtn.style.display = canOperate ? 'flex' : 'none';
            }
            if (this.elements.skipBtn) {
                this.elements.skipBtn.style.display = canOperate ? 'flex' : 'none';
            }
            if (this.elements.quickActionsGrid) {
                this.elements.quickActionsGrid.style.display = canOperate ? '' : 'none';
            }
            if (this.elements.orderManagementGrid) {
                this.elements.orderManagementGrid.style.display = canOperate ? '' : 'none';
            }
        },

        /**
         * Render 仍使用 LAN 的完整抽屜版面；寫入控制保持唯讀。
         * 這裡只把 LAN 原本存在的操作區顯示成 disabled，不會繞過後端唯讀保護。
         */
        applyCloudReadonlyVisual() {
            if (!isCloudReadOnly()) return;

            const disable = (el, show = true) => {
                if (!el) return;
                if (show) el.classList.remove('hidden');
                el.disabled = true;
                el.classList.add('is-disabled');
                el.setAttribute('aria-disabled', 'true');
                el.title = 'Render 云端唯读';
            };

            if (this.isAdmin()) {
                disable(this.elements.adminRemarkEditBtn);
                disable(this.elements.adminUploadBtn);
                disable(this.elements.adminSelectBtn);
                disable(this.elements.adminDeleteBtn);
                disable(this.elements.transferBtn);
            }
            if (this.isSales()) {
                disable(this.elements.salesRemarkEditBtn);
            }
            if (this.isAdmin() || this.isSales()) {
                disable(this.elements.salesUploadBtn);
                disable(this.elements.salesSelectBtn);
                disable(this.elements.salesDeleteBtn);
            }

            if (!this.state.orderOnly && (this.isAdmin() || this.isSales())) {
                if (this.elements.footer) this.elements.footer.style.display = '';
                if (this.elements.quickActionsGrid) this.elements.quickActionsGrid.style.display = '';
                if (this.elements.orderManagementGrid) this.elements.orderManagementGrid.style.display = '';
                disable(this.elements.quickActionBtn);
                disable(this.elements.skipBtn);
            }
        },

        /**
         * 订单-only 视图布局（隐藏流程相关区域）
         */
        applyOrderOnlyLayout() {
            const isOrderOnly = !!this.state.orderOnly;
            const workflowSection = this.elements.workflowCard ? this.elements.workflowCard.closest('section') : null;
            if (workflowSection) {
                workflowSection.classList.toggle('hidden', isOrderOnly);
            }

            if (this.elements.tabProcess) {
                this.elements.tabProcess.classList.toggle('hidden', isOrderOnly);
            }
            if (this.elements.tabFiles) {
                this.elements.tabFiles.classList.toggle('hidden', isOrderOnly);
            }
            if (this.elements.footer) {
                this.elements.footer.style.display = isOrderOnly ? 'none' : '';
            }
            if (isOrderOnly) {
                if (this.elements.contentProcess) this.elements.contentProcess.classList.add('hidden');
                if (this.elements.contentFiles) this.elements.contentFiles.classList.add('hidden');
                if (this.elements.tabAdminRef) {
                    this.switchTab('admin_ref');
                }
                return;
            }

            // 正常模式：保持当前 tab 的可见性
            this.switchTab(this.state.currentTab || 'admin_ref');
        },

        /**
         * 渲染 Header
         */
        renderHeader() {
            const data = this.state.workflowData;

            if (this.elements.orderNumber) {
                this.elements.orderNumber.textContent = (data.order_number || '-');
            }

            if (this.elements.customerName) {
                this.elements.customerName.textContent = data.customer_name || '-';
            }

            // 更新訂金徽章（從全域字典 wsDepositMap 查，不重複打 API）
            wsShowDepositBadge(data.order_number || this.state.currentOrderNumber);

            if (window.IS_OVERSEAS) {
                const waBtn = document.getElementById('wsWaBtn');
                if (waBtn) {
                    const name = (data.customer_name || '').trim().toUpperCase();
                    const phone = waContacts[name];
                    waBtn.dataset.customer = data.customer_name || '';
                    waBtn.dataset.order = this.state.currentOrderNumber || '';
                    if (phone) {
                        waBtn.title = `+${phone}`;
                        waBtn.style.opacity = '1';
                        waBtn.style.cursor = 'pointer';
                        waBtn.style.pointerEvents = 'auto';
                        waBtn.querySelector('svg').style.fill = '#25D366';
                    } else {
                        waBtn.title = '找不到電話號碼';
                        waBtn.style.opacity = '0.35';
                        waBtn.style.cursor = 'not-allowed';
                        waBtn.style.pointerEvents = 'none';
                        waBtn.querySelector('svg').style.fill = '#94a3b8';
                    }
                }
            }
        },

        scrollWorkflowCards(direction) {
            const container = this.elements.workflowCard;
            if (!container) return;
            const step = Math.max(180, Math.round(container.clientWidth * 0.8));
            container.scrollBy({ left: direction * step, behavior: 'smooth' });
        },

        updateWorkflowNav() {
            const container = this.elements.workflowCard;
            const prevBtn = this.elements.workflowPrevBtn;
            const nextBtn = this.elements.workflowNextBtn;
            if (!container || !prevBtn || !nextBtn) return;

            const canScroll = container.scrollWidth > container.clientWidth + 2;
            if (!canScroll) {
                prevBtn.style.display = 'none';
                nextBtn.style.display = 'none';
                prevBtn.disabled = true;
                nextBtn.disabled = true;
                return;
            }

            prevBtn.style.display = 'flex';
            nextBtn.style.display = 'flex';

            const maxScrollLeft = container.scrollWidth - container.clientWidth;
            const atStart = container.scrollLeft <= 0;
            const atEnd = container.scrollLeft >= maxScrollLeft - 1;
            prevBtn.disabled = atStart;
            nextBtn.disabled = atEnd;
        },

        /**
         * 渲染工作流卡片
         */
        renderWorkflowCard() {
            const currentWorkflowNumber = this.state.currentWorkflowNumber;
            let allWorkflows = this.state.allWorkflows;
            if (!this.elements.workflowCard) return;

            // 根據角色過濾工作流（業務員只能看到自己的）
            if (this.state.currentRole === 'SALES') {
                const userId = document.body.dataset.userId;
                if (userId) {
                    allWorkflows = allWorkflows.filter(wf => wf.handler_id === userId);
                }
            }

            // 如果沒有其他工作流，只顯示當前工作流
            if (!allWorkflows || allWorkflows.length === 0) {
                const data = this.state.workflowData;
                const html = `
                    <div class="ws-workflow-card active shrink-0 w-44 p-4 rounded-2xl border border-brand-600 bg-brand-50 shadow-[0_4px_12px_-2px_rgba(37,99,235,0.1)] cursor-pointer transition-all">
                        <div class="flex items-center justify-between mb-3">
                            <span class="text-[10px] font-black text-brand-600 uppercase tracking-widest">
                                ${data ? (data.workflow_number || '-') : '-'}
                            </span>
                        </div>
                        <p class="text-sm font-bold text-slate-800">${data ? (data.handler_name || '-') : '-'}</p>
                        <p class="text-[10px] text-slate-400 font-bold mt-1 uppercase">
                            ${data && typeof displayStatus === 'function' ? displayStatus(data.current_status) : (data ? data.current_status : '-')}
                        </p>
                    </div>
                `;
                this.elements.workflowCard.innerHTML = html;
                requestAnimationFrame(() => {
                    this.updateWorkflowNav();
                    const activeCard = this.elements.workflowCard.querySelector('.ws-workflow-card.active');
                    if (activeCard) {
                        activeCard.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
                    }
                });
                return;
            }

            // 渲染所有工作流卡片
            const html = allWorkflows.map(wf => {
                const isActive = wf.workflow_number === currentWorkflowNumber;
                const activeClass = isActive 
                    ? 'border-brand-600 bg-brand-50 shadow-[0_4px_12px_-2px_rgba(37,99,235,0.1)]' 
                    : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-sm';
                
                return `
                    <div onclick="WorkspaceDrawer.switchWorkflow('${wf.workflow_number}')"
                         class="ws-workflow-card ${isActive ? 'active' : ''} shrink-0 w-44 p-4 rounded-2xl border ${activeClass} cursor-pointer transition-all">
                        <div class="flex items-center justify-between mb-3">
                            <span class="text-[10px] font-black ${isActive ? 'text-brand-600' : 'text-slate-600'} uppercase tracking-widest">
                                ${wf.workflow_number || '-'}
                            </span>
                        </div>
                        <p class="text-sm font-bold text-slate-800">${wf.handler_name || '-'}</p>
                        <p class="text-[10px] text-slate-400 font-bold mt-1 uppercase">
                            ${typeof displayStatus === 'function' ? displayStatus(wf.current_status) : wf.current_status}
                        </p>
                    </div>
                `;
            }).join('');

            this.elements.workflowCard.innerHTML = html;
            requestAnimationFrame(() => {
                this.updateWorkflowNav();
                const activeCard = this.elements.workflowCard.querySelector('.ws-workflow-card.active');
                if (activeCard) {
                    activeCard.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
                }
            });
        },

        /**
         * 切換工作流
         */
        switchWorkflow(workflowNumber) {
            if (workflowNumber === this.state.currentWorkflowNumber) {
                return; // 已經是當前工作流，不需要切換
            }
            
            console.log('[WorkspaceDrawer] 切換工作流:', workflowNumber);
            this.open(workflowNumber);
        },

        /**
         * 渲染 TAB 1: 主管参考
         */
        renderAdminRef() {
            const data = this.state.workflowData;

            // 主管备注
            this.updateRemarkDisplay('admin', data.order_notes || '');

            if (this.elements.adminRemarkTime) {
                this.elements.adminRemarkTime.textContent = 'Updated by Admin';
            }

            const canEditAdminRemark = this.canEditAdminRemark();
            if (this.elements.adminRemarkEditBtn) {
                this.elements.adminRemarkEditBtn.classList.toggle('hidden', !canEditAdminRemark);
            }
            if (!canEditAdminRemark) {
                this.toggleRemarkEdit('admin', false);
            }

            // 参考图片
            if (this.elements.adminImageGrid) {
                const imageFiles = this.getSortedFiles(
                    this.state.orderFiles.filter(f => this.isImageFile(f))
                );
                this.state.adminImageFiles = imageFiles;

                if (imageFiles.length > 0) {
                    const selectedIds = this.state.adminSelectedIds;
                    const html = imageFiles.map((img, index) => {
                        const isSelected = selectedIds.has(img.id);
                        return `
                        <div class="ws-image-card ${isSelected ? 'selected' : ''}" onclick="WorkspaceDrawer.handleImageClick(true, ${index}, ${img.id})">
                            <div class="ws-image-thumb">
                                <img src="/tracking/api/orders/files/${img.id}/download" alt="${img.file_name || img.original_filename || ''}">
                                <div class="ws-image-check">
                                    <span class="material-symbols-rounded">check_circle</span>
                            </div>
                        </div>
                            <div class="ws-image-meta">
                                <div class="ws-image-name">${img.file_name || img.original_filename || '-'}</div>
                                <div class="ws-image-date">${this.formatFileSize(img.file_size)} • ${this.formatDateTime(this.getFileDate(img))}</div>
                            </div>
                        </div>
                    `;
                    }).join('');
                    this.elements.adminImageGrid.innerHTML = html;
                } else {
                    this.elements.adminImageGrid.innerHTML = '<p class="text-xs text-slate-400 italic text-center py-8 w-full">暂无参考图片</p>';
                }
            }

            // 管理员上传/删除按钮（仅管理员可用；业务员显示为禁用态）
            const canModifyAdminTab = this.isAdmin();
            if (this.elements.adminUploadBtn) {
                this.elements.adminUploadBtn.classList.toggle('hidden', false);
                this.elements.adminUploadBtn.classList.toggle('is-disabled', !canModifyAdminTab);
                this.elements.adminUploadBtn.disabled = !canModifyAdminTab;
            }
            if (this.elements.adminSelectBtn) {
                this.elements.adminSelectBtn.classList.toggle('hidden', !canModifyAdminTab);
            }
            if (this.elements.adminDeleteBtn) {
                this.elements.adminDeleteBtn.classList.toggle('hidden', !canModifyAdminTab);
            }
            if (this.elements.adminDateToggleBtn) {
                this.elements.adminDateToggleBtn.classList.toggle('active', this.state.showImageDate);
                const icon = this.elements.adminDateToggleBtn.querySelector('.material-symbols-rounded');
                if (icon) icon.textContent = this.state.showImageDate ? 'visibility' : 'visibility_off';
            }
            if (!canModifyAdminTab) {
                this.state.adminSelectionMode = false;
                this.state.adminSelectedIds.clear();
            }
            this.updateSelectionUI(true);

            // 官方文件
            if (this.elements.adminFileList) {
                const docFiles = this.getSortedFiles(
                    this.state.orderFiles.filter(f => !this.isImageFile(f))
                );

                if (docFiles.length > 0) {
                    const canDelete = this.isAdmin();
                    const html = docFiles.map(f => `
                        <div class="flex items-center gap-4 p-4 bg-purple-50 border border-purple-100 rounded-2xl hover:bg-purple-100 transition-all cursor-pointer"
                             onclick="window.open('/tracking/api/orders/files/${f.id}/download', '_blank')">
                            <div class="w-12 h-12 bg-purple-600 text-white flex items-center justify-center rounded-xl shadow-lg shadow-purple-200">
                                <span class="material-symbols-rounded">description</span>
                            </div>
                            <div class="flex-1 min-w-0 font-bold">
                                <p class="text-sm text-slate-800 truncate">${f.file_name}</p>
                                <p class="text-[10px] text-purple-600 uppercase tracking-widest italic">
                                    ${this.formatFileSize(f.file_size)} • ${this.formatDateTime(this.getFileDate(f))}
                                </p>
                            </div>
                            <div class="flex items-center gap-1">
                                <button onclick="event.stopPropagation(); window.open('/tracking/api/orders/files/${f.id}/download', '_blank');"
                                        class="ws-file-action-btn">
                                    <span class="material-symbols-rounded">file_download</span>
                                </button>
                                ${canDelete ? `
                                <button onclick="event.stopPropagation(); WorkspaceDrawer.deleteSingleFile(true, ${f.id});"
                                        class="ws-delete-btn">
                                    <span class="material-symbols-rounded">delete</span>
                                </button>
                                ` : ''}
                            </div>
                        </div>
                    `).join('');
                    this.elements.adminFileList.innerHTML = html;
                } else {
                    this.elements.adminFileList.innerHTML = '<p class="text-xs text-slate-400 italic text-center py-8">暂无标准文件</p>';
                }
            }
        },

        /**
         * 渲染 TAB 2: 流程进度
         */
        renderProcess() {
            const data = this.state.workflowData;

            // 业务员头像
            if (this.elements.salesAvatar) {
                const name = data.handler_name || '-';
                this.elements.salesAvatar.textContent = name.charAt(0);
            }

            // 业务员备注
            this.updateRemarkDisplay('sales', data.workflow_notes || data.notes || '');

            const canEditSalesRemark = this.canEditSalesRemark();
            if (this.elements.salesRemarkEditBtn) {
                this.elements.salesRemarkEditBtn.classList.toggle('hidden', !this.isSales() || !canEditSalesRemark);
            }
            if (this.elements.transferBtn) {
                this.elements.transferBtn.classList.toggle('hidden', !this.isAdmin());
            }
            if (!this.isSales() || !canEditSalesRemark) {
                this.toggleRemarkEdit('sales', false);
            }

            // 时间轴
            if (this.elements.timelineContainer && data.history) {
                this.renderTimeline(data.history);
            }
        },

        getUserRole() {
            return appPerm.role || '';
        },

        getCurrentUserId() {
            return parseInt(document.body.dataset.userId || '0', 10);
        },

        getHandlerId() {
            const handlerId = this.state.workflowData && this.state.workflowData.handler_id;
            return handlerId ? parseInt(handlerId, 10) : 0;
        },

        canEditAdminRemark() {
            return isAdminRole();
        },

        canEditSalesRemark() {
            if (!isSalesRole()) return false;
            const handlerId = this.getHandlerId();
            return handlerId > 0 && handlerId === this.getCurrentUserId();
        },
        isAdmin() {
            return isAdminRole();
        },
        isSales() {
            return isSalesRole();
        },
        canOperate() {
            return canEditWorkflow();
        },

        updateRemarkDisplay(type, text, force = false) {
            const displayEl = type === 'admin' ? this.elements.adminRemark : this.elements.salesRemark;
            const isEditing = type === 'admin' ? this.state.adminRemarkEditing : this.state.salesRemarkEditing;
            if (!displayEl || (isEditing && !force)) return;
            const content = (text || '').trim() || '暂无备注';
            displayEl.textContent = content;
        },

        toggleRemarkEdit(type, isEditing) {
            const isAdmin = type === 'admin';
            const canEdit = isAdmin ? this.canEditAdminRemark() : this.canEditSalesRemark();
            if (isEditing && !canEdit) return;

            const displayEl = isAdmin ? this.elements.adminRemark : this.elements.salesRemark;
            const editWrap = isAdmin ? this.elements.adminRemarkEdit : this.elements.salesRemarkEdit;
            const inputEl = isAdmin ? this.elements.adminRemarkInput : this.elements.salesRemarkInput;

            if (!displayEl || !editWrap || !inputEl) return;

            if (isEditing) {
                if (isAdmin) {
                    this.state.adminRemarkEditing = true;
                } else {
                    this.state.salesRemarkEditing = true;
                }

                const currentText = displayEl.textContent === '暂无备注' ? '' : displayEl.textContent;
                inputEl.value = currentText || '';
                displayEl.classList.add('hidden');
                editWrap.classList.remove('hidden');

                setTimeout(() => {
                    inputEl.focus();
                    inputEl.select();
                }, 10);

                inputEl.onkeydown = (e) => {
                    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                        e.preventDefault();
                        this.saveRemark(type);
                    }
                    if (e.key === 'Escape') {
                        e.preventDefault();
                        this.toggleRemarkEdit(type, false);
                    }
                };
            } else {
                if (isAdmin) {
                    this.state.adminRemarkEditing = false;
                } else {
                    this.state.salesRemarkEditing = false;
                }

                displayEl.classList.remove('hidden');
                editWrap.classList.add('hidden');
                inputEl.value = displayEl.textContent === '暂无备注' ? '' : displayEl.textContent;
            }
        },

        async saveRemark(type) {
            const isAdmin = type === 'admin';
            const inputEl = isAdmin ? this.elements.adminRemarkInput : this.elements.salesRemarkInput;
            const saveBtn = isAdmin ? this.elements.adminRemarkSaveBtn : this.elements.salesRemarkSaveBtn;
            const displayEl = isAdmin ? this.elements.adminRemark : this.elements.salesRemark;

            if (!inputEl || !saveBtn || !displayEl) return;

            const notes = inputEl.value.trim();
            const identifier = isAdmin ? this.state.currentOrderNumber : this.state.currentWorkflowNumber;
            if (!identifier) {
                if (typeof showToast === 'function') {
                    showToast('错误', '无法识别当前单号', 'error');
                }
                return;
            }

            const apiUrl = isAdmin
                ? `/tracking/api/orders/${encodeURIComponent(identifier)}`
                : `/tracking/api/workflows/${encodeURIComponent(identifier)}`;

            saveBtn.disabled = true;
            saveBtn.textContent = '保存中...';

            try {
                const response = await fetch(apiUrl, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ notes })
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '保存失败');
                }

                if (this.state.workflowData) {
                    if (isAdmin) {
                        this.state.workflowData.order_notes = notes;
                    } else {
                        this.state.workflowData.workflow_notes = notes;
                        this.state.workflowData.notes = notes;
                    }
                }

                this.updateRemarkDisplay(type, notes, true);
                this.toggleRemarkEdit(type, false);

                if (!isAdmin && typeof window.updateTableNotesAfterSave === 'function') {
                    window.updateTableNotesAfterSave(this.state.currentWorkflowNumber, notes);
                }

                if (typeof showToast === 'function') {
                    showToast('成功', '备注已保存', 'success');
                }
            } catch (error) {
                console.error('[WorkspaceDrawer] 备注保存失败:', error);
                if (typeof showToast === 'function') {
                    showToast('错误', error.message || '保存失败', 'error');
                }
            } finally {
                saveBtn.disabled = false;
                saveBtn.textContent = '保存';
            }
        },

        openTransferModal() {
            if (!this.isAdmin()) {
                if (typeof showToast === 'function') {
                    showToast('错误', '无权限', 'error');
                }
                return;
            }
            if (!this.state.currentWorkflowNumber) {
                if (typeof showToast === 'function') {
                    showToast('错误', '请先选择工作流', 'error');
                }
                return;
            }
            if (this.elements.transferModal) {
                this.elements.transferModal.classList.remove('hidden');
            }
            this.loadTransferUsers();
        },

        closeTransferModal() {
            if (this.elements.transferModal) {
                this.elements.transferModal.classList.add('hidden');
            }
            if (this.elements.transferUserSearch) {
                this.elements.transferUserSearch.value = '';
            }
            if (this.elements.transferUserOptions) {
                this.elements.transferUserOptions.innerHTML = '';
            }
            if (this.elements.transferUserId) {
                this.elements.transferUserId.value = '';
            }
        },

        async loadTransferUsers() {
            if (!this.elements.transferUserOptions) return;
            this.elements.transferUserOptions.innerHTML = '';

            try {
                const response = await fetch('/tracking/api/users?status=active');
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '获取业务员失败');
                }
                this.state.transferUsers = data.data || [];
                this.renderTransferUsers();
            } catch (error) {
                console.error('[WorkspaceDrawer] 获取业务员失败:', error);
                if (typeof showToast === 'function') {
                    showToast('错误', error.message || '获取业务员失败', 'error');
                }
                this.elements.transferUserOptions.innerHTML = '';
            }
        },

        renderTransferUsers() {
            if (!this.elements.transferUserOptions) return;
            const currentHandlerId = this.state.workflowData && this.state.workflowData.handler_id;
            const matrix = appPerm.matrix || {};
            const allowedRoles = Object.keys(matrix).filter(roleKey => {
                const actions = matrix[roleKey] && matrix[roleKey].workflow;
                return Array.isArray(actions) && actions.includes('edit');
            });
            const users = (this.state.transferUsers || []).filter(u => {
                if (!u || u.user_id === currentHandlerId) return false;
                if (u.status && u.status !== 'active') return false;
                if (allowedRoles.length === 0) return false;
                if (!allowedRoles.includes(u.role)) return false;
                return true;
            });
            if (users.length === 0) {
                this.elements.transferUserOptions.innerHTML = '';
                return;
            }
            const options = users.map(u => {
                const name = u.real_name || u.display_name || u.username || `用户${u.user_id}`;
                const roleLabel = u.role || '';
                const label = `${name} (${u.username}) · ${roleLabel}`;
                return `<option value="${label}" data-user-id="${u.user_id}"></option>`;
            }).join('');
            this.elements.transferUserOptions.innerHTML = options;
            this.syncTransferUserIdFromInput();
        },

        syncTransferUserIdFromInput() {
            if (!this.elements.transferUserSearch || !this.elements.transferUserId || !this.elements.transferUserOptions) return;
            const inputValue = this.elements.transferUserSearch.value.trim();
            if (!inputValue) {
                this.elements.transferUserId.value = '';
                return;
            }
            const option = Array.from(this.elements.transferUserOptions.options)
                .find(opt => opt.value === inputValue);
            const userId = option ? (option.dataset.userId || '') : '';
            this.elements.transferUserId.value = userId;
        },

        async confirmTransfer() {
            if (!this.state.currentWorkflowNumber || !this.elements.transferUserId) return;
            const targetUserId = parseInt(this.elements.transferUserId.value, 10);
            if (!targetUserId) {
                if (typeof showToast === 'function') {
                    showToast('错误', '请选择用户', 'error');
                }
                return;
            }

            if (this.elements.transferConfirmBtn) {
                this.elements.transferConfirmBtn.disabled = true;
                this.elements.transferConfirmBtn.textContent = '转移中...';
            }

            try {
                const response = await fetch(`/tracking/api/workflows/${encodeURIComponent(this.state.currentWorkflowNumber)}/transfer`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ to_user_id: targetUserId })
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '转移失败');
                }

                if (typeof showToast === 'function') {
                    showToast('成功', '流程已转移', 'success');
                }
                if (typeof window.updateWorkflowHandlerInRow === 'function') {
                    const handlerName = (data && data.data && data.data.handler_name) || '';
                    window.updateWorkflowHandlerInRow(this.state.currentWorkflowNumber, handlerName);
                }
                this.closeTransferModal();
                this.loadData(this.state.currentWorkflowNumber);
                if (typeof refreshAllComponents === 'function') {
                    refreshAllComponents(this.state.currentOrderNumber, this.state.currentWorkflowNumber);
                }
            } catch (error) {
                console.error('[WorkspaceDrawer] 转移失败:', error);
                if (typeof showToast === 'function') {
                    showToast('错误', error.message || '转移失败', 'error');
                }
            } finally {
                if (this.elements.transferConfirmBtn) {
                    this.elements.transferConfirmBtn.disabled = false;
                    this.elements.transferConfirmBtn.textContent = '确认转移';
                }
            }
        },

        /**
         * 渲染时间轴
         */
        renderTimeline(history) {
            if (!history || history.length === 0) {
                this.elements.timelineContainer.innerHTML = '<p class="text-xs text-slate-400 italic text-center py-8">暂无历史记录</p>';
                return;
            }

            const canEdit = true;
            const canCopy = typeof window.copyStep === 'function';
            // 使用本地日期計算（與後端 date.today() 一致，避免 UTC 偏差）
            const today = typeof getTodayLocal === 'function' ? getTodayLocal() : new Date();
            const parseDate = (d) => {
                if (typeof parseLocalDate === 'function') return parseLocalDate(d);
                if (typeof parseUTCDate === 'function') return parseUTCDate(d);
                const dt = new Date(d);
                return Number.isNaN(dt.getTime()) ? null : dt;
            };
            const calcDays = (endDate, startDate) => {
                if (!endDate || !startDate) return 0;
                const diff = endDate - startDate;
                return Math.max(0, Math.floor(diff / (1000 * 60 * 60 * 24)));
            };
            const getDaysClass = (days, statusKey) => {
                if (typeof getDaysStatusClass === 'function') return getDaysStatusClass(days, statusKey);
                return 'status-ok';
            };

            const lastStatusKey = history[history.length - 1]?.to_status;
            const isTerminalLast = (typeof STATUS !== 'undefined')
                && (lastStatusKey === STATUS.COMPLETED || lastStatusKey === STATUS.CANCELLED);

            const html = history.map((item, index) => {
                const isLast = index === history.length - 1;
                const statusKey = item.to_status;
                const isCompleted = (typeof STATUS !== 'undefined' && statusKey === STATUS.COMPLETED) || statusKey === 'COMPLETED';
                const isCancelled = (typeof STATUS !== 'undefined' && statusKey === STATUS.CANCELLED) || statusKey === 'CANCELLED';
                const nodeClass = isCancelled ? 'active' : (isCompleted ? 'done' : (isLast ? 'active' : 'done'));
                const statusLabel = typeof displayStatus === 'function'
                    ? displayStatus(statusKey, 'zh_tw')
                    : statusKey;
                const statusIcon = typeof getStatusIcon === 'function' ? getStatusIcon(statusKey) : '';
                const recordDate = parseDate(item.action_date);
                const waitingDays = calcDays(today, recordDate);
                const connectorDays = !isLast
                    ? calcDays(parseDate(history[index + 1]?.action_date), recordDate)
                    : null;
                const daysClass = connectorDays !== null ? getDaysClass(connectorDays, statusKey) : '';
                const lineClass = isLast
                    ? ''
                    : (isTerminalLast ? 'solid' : (index === history.length - 2 ? 'dashed-red' : 'solid'));

                const isAutoCompleted = isCompleted && String(item.notes || '') === '系統自動：已全部出貨後轉為已完成';
                // 系統自動產生的「已完成」只是全部出貨的結果，不是獨立人工操作，
                // 因此不提供編輯/複製按鈕；要改日期請編輯前一筆「已全部出貨」。
                const showEdit = canEdit && !isAutoCompleted;
                const showCopy = canCopy && !isLast && !isAutoCompleted;
                const actionsHtml = (showEdit || showCopy) ? `
                    <div class="ws-timeline-actions">
                        ${showEdit ? `<button class="ws-timeline-action-btn" onclick="editStep(${index})">编辑</button>` : ''}
                        ${showCopy ? `<button class="ws-timeline-action-btn" onclick="copyStep(${index})">复制</button>` : ''}
                    </div>
                ` : '';

                return `
                    <div class="ws-timeline-item relative pl-12 ${isLast ? 'ws-timeline-item-last' : ''}">
                        <div class="ws-timeline-icon ${nodeClass}">
                            ${statusIcon}
                        </div>
                        ${!isLast ? `
                            <div class="ws-timeline-connector">
                                <div class="ws-connector-line ${lineClass}"></div>
                                <div class="ws-days-above ${daysClass}">${connectorDays}天</div>
                            </div>
                        ` : ''}
                        <div class="ws-timeline-content ${!isLast ? 'pb-8' : ''}">
                            <h4 class="text-sm font-bold text-slate-900 mb-1">
                                ${statusLabel}
                                ${isLast && !isTerminalLast ? `<span class="ws-wait-inline">已等 ${waitingDays} 天</span>` : ''}
                            </h4>
                            <p class="text-xs text-slate-400">
                                ${item.action_date} ${item.operator ? '• ' + item.operator : ''}
                            </p>
                            ${item.notes ? `<p class="text-xs text-slate-600 mt-2 bg-slate-50 p-2 rounded">${item.notes}</p>` : ''}
                            ${actionsHtml}
                        </div>
                    </div>
                `;
            }).join('');

            this.elements.timelineContainer.innerHTML = html;

            // Add undo button for last step (admin only)
            if (this.state.currentRole === 'ADMIN') {
                const items = this.elements.timelineContainer.querySelectorAll('.ws-timeline-item');
                const lastIndex = items.length - 1;
                if (lastIndex >= 0) {
                    const lastHistory = history[lastIndex];
                    const lastStatus = lastHistory && lastHistory.to_status ? lastHistory.to_status : '';
                    const isNewOrder = lastStatus === 'NEW_ORDER' || (typeof STATUS !== 'undefined' && lastStatus === STATUS.NEW_ORDER);
                    if (isNewOrder) return;
                    const lastItem = items[lastIndex];
                    let actions = lastItem.querySelector('.ws-timeline-actions');
                    if (!actions) {
                        actions = lastItem.querySelector('.flex.gap-2.mt-2');
                        if (actions) actions.classList.add('ws-timeline-actions');
                    }
                    if (!actions) {
                        actions = document.createElement('div');
                        actions.className = 'ws-timeline-actions flex gap-2 mt-2';
                        const contentEl = lastItem.querySelector('.ws-timeline-content');
                        if (contentEl) contentEl.appendChild(actions);
                    }
                    if (actions && !actions.querySelector('.ws-timeline-undo-btn')) {
                        const btn = document.createElement('button');
                        btn.className = 'ws-timeline-undo-btn text-10px font-bold text-amber-600 hover:text-amber-700';
                        btn.textContent = '撤銷';
                        btn.addEventListener('click', () => this.toggleTimelineUndo(lastIndex));
                        actions.appendChild(btn);
                    }
                }
            }
        },

        toggleTimelineEdit(index) {
            const items = this.elements.timelineContainer
                ? this.elements.timelineContainer.querySelectorAll('.ws-timeline-item')
                : [];
            const itemEl = items[index];
            if (!itemEl) return;

            // Close undo confirm if open
            const undoEl = itemEl.querySelector('.ws-timeline-undo');
            if (undoEl) undoEl.classList.add('hidden');

            let editEl = itemEl.querySelector('.ws-inline-editor');
            if (!editEl) {
                editEl = document.createElement('div');
                editEl.className = 'ws-inline-editor';
                const data = this.state.workflowData;
                const history = data && data.history ? data.history : [];
                const editItem = history[index] || {};
                const editStatus = editItem.to_status || '';
                const isShippingRecord = editStatus === 'PARTIAL_SHIPPED' || editStatus === 'ALL_SHIPPED'
                    || (typeof STATUS !== 'undefined' && (editStatus === STATUS.PARTIAL_SHIPPED || editStatus === STATUS.ALL_SHIPPED));
                editEl.innerHTML = `
                    ${isShippingRecord ? `<label class="ws-inline-editor-date-label">出貨日期<input class="ws-inline-editor-date" type="date"></label>` : ''}
                    <textarea class="ws-inline-editor-input" rows="2" placeholder="輸入備註..."></textarea>
                    <div class="ws-inline-editor-actions">
                        <button class="ws-inline-editor-save">保存</button>
                        <button class="ws-inline-editor-cancel">取消</button>
                    </div>
                `;
                const contentEl = itemEl.querySelector('.ws-timeline-content');
                if (contentEl) contentEl.appendChild(editEl);

                editEl.querySelector('.ws-inline-editor-save')
                    .addEventListener('click', () => this.saveTimelineEdit(index));
                editEl.querySelector('.ws-inline-editor-cancel')
                    .addEventListener('click', () => this.cancelTimelineEdit(index));
            }

            const data = this.state.workflowData;
            const history = data && data.history ? data.history : [];
            const currentNotes = history[index] && history[index].notes ? history[index].notes : '';
            const input = editEl.querySelector('.ws-inline-editor-input');
            const dateInput = editEl.querySelector('.ws-inline-editor-date');
            if (dateInput && history[index]) dateInput.value = String(history[index].action_date || '').slice(0, 10);
            if (input) {
                input.value = currentNotes;
                setTimeout(() => (dateInput || input).focus(), 0);
            }
            editEl.classList.remove('hidden');
        },

        cancelTimelineEdit(index) {
            const items = this.elements.timelineContainer
                ? this.elements.timelineContainer.querySelectorAll('.ws-timeline-item')
                : [];
            const itemEl = items[index];
            if (!itemEl) return;
            const editEl = itemEl.querySelector('.ws-inline-editor');
            if (editEl) editEl.classList.add('hidden');
        },

        async saveTimelineEdit(index) {
            const data = this.state.workflowData;
            const history = data && data.history ? data.history : [];
            const item = history[index];
            if (!item || !item.id) return;

            const items = this.elements.timelineContainer
                ? this.elements.timelineContainer.querySelectorAll('.ws-timeline-item')
                : [];
            const itemEl = items[index];
            const editEl = itemEl ? itemEl.querySelector('.ws-inline-editor') : null;
            const input = editEl ? editEl.querySelector('.ws-inline-editor-input') : null;
            const newNotes = input ? input.value.trim() : '';
            const dateInput = editEl ? editEl.querySelector('.ws-inline-editor-date') : null;
            const newActionDate = dateInput ? dateInput.value : '';

            try {
                const payload = { notes: newNotes };
                if (dateInput) payload.action_date = newActionDate;
                const res = await fetch(`/tracking/api/workflows/${encodeURIComponent(this.state.currentWorkflowNumber)}/history/${item.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const result = await res.json();
                if (!result.success) throw new Error(result.error || '更新失敗');
                item.notes = newNotes;
                if (dateInput && result.data && result.data.action_date) {
                    item.action_date = result.data.action_date;
                    if (result.data.paired_auto_history_id) {
                        const paired = history.find(h => Number(h.id) === Number(result.data.paired_auto_history_id));
                        if (paired) paired.action_date = result.data.action_date;
                    }
                }
                this.renderTimeline(history);
                if (typeof loadHomeOrdersData === 'function') loadHomeOrdersData(true);
                if (typeof showToast === 'function') {
                    showToast('成功', dateInput ? '已更新出貨日期' : '已更新備註');
                }
            } catch (err) {
                if (typeof showToast === 'function') {
                    showToast('錯誤', err.message || '更新失敗', 'error');
                }
            }
        },

        toggleTimelineUndo(index) {
            const items = this.elements.timelineContainer
                ? this.elements.timelineContainer.querySelectorAll('.ws-timeline-item')
                : [];
            const itemEl = items[index];
            if (!itemEl) return;

            let undoEl = itemEl.querySelector('.ws-timeline-undo');
            if (!undoEl) {
                undoEl = document.createElement('div');
                undoEl.className = 'ws-timeline-undo';
                undoEl.innerHTML = `
                    <span class="ws-timeline-undo-text">確認撤銷最後一步？</span>
                    <button class="ws-timeline-undo-confirm">確認</button>
                    <button class="ws-timeline-undo-cancel">取消</button>
                `;
                const contentEl = itemEl.querySelector('.ws-timeline-content');
                if (contentEl) contentEl.appendChild(undoEl);
                undoEl.querySelector('.ws-timeline-undo-confirm')
                    .addEventListener('click', () => this.confirmTimelineUndo(index));
                undoEl.querySelector('.ws-timeline-undo-cancel')
                    .addEventListener('click', () => this.cancelTimelineUndo(index));
            }
            undoEl.classList.remove('hidden');
        },

        cancelTimelineUndo(index) {
            const items = this.elements.timelineContainer
                ? this.elements.timelineContainer.querySelectorAll('.ws-timeline-item')
                : [];
            const itemEl = items[index];
            if (!itemEl) return;
            const undoEl = itemEl.querySelector('.ws-timeline-undo');
            if (undoEl) undoEl.classList.add('hidden');
        },

        async confirmTimelineUndo(index) {
            const workflowNumber = this.state.currentWorkflowNumber;
            if (!workflowNumber) {
                if (typeof showToast === 'function') {
                    showToast('錯誤', '無法獲取工作流號', 'error');
                }
                return;
            }
            try {
                // 使用工作流级别的撤销端点
                const res = await fetch(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}/undo-last-step`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        reason: '',
                        expected_status: this.state.currentStatus,
                        expected_history_id: this.state.lastHistoryId
                    })
                });
                
                const result = await res.json();
                
                if (!res.ok || !result.success) {
                    // 显示详细的错误信息
                    const errorMsg = result.error || result.details || '撤銷失敗';
                    const errorCode = result.code || 'UNKNOWN_ERROR';
                    console.error('[WorkspaceDrawer] 撤銷失敗:', {
                        status: res.status,
                        error: errorMsg,
                        code: errorCode,
                        details: result.details
                    });
                    
                if (typeof showToast === 'function') {
                        showToast('撤銷失敗', errorMsg, 'error');
                    }
                    return;
                }
                
                if (typeof showToast === 'function') {
                    showToast('成功', result.message || '已撤銷', 'success');
                }
                if (typeof refreshAllComponents === 'function') {
                    refreshAllComponents(this.state.currentOrderNumber, this.state.currentWorkflowNumber);
                }
                this.loadData(this.state.currentWorkflowNumber);
            } catch (err) {
                console.error('[WorkspaceDrawer] 撤銷操作異常:', err);
                if (typeof showToast === 'function') {
                    showToast('錯誤', err.message || '撤銷失敗，請稍後再試', 'error');
                }
            } finally {
                this.cancelTimelineUndo(index);
            }
        },

        /**
         * 渲染 TAB 3: 业务附件
         */
        renderFiles() {
            const files = this.state.workflowFiles || [];

            if (this.elements.salesImageGrid) {
                const imageFiles = this.getSortedFiles(
                    files.filter(f => this.isImageFile(f))
                );
                this.state.salesImageFiles = imageFiles;

                if (imageFiles.length > 0) {
                    const selectedIds = this.state.salesSelectedIds;
                    const html = imageFiles.map((img, index) => {
                        const isSelected = selectedIds.has(img.id);
                        return `
                        <div class="ws-image-card ${isSelected ? 'selected' : ''}" onclick="WorkspaceDrawer.handleImageClick(false, ${index}, ${img.id})">
                            <div class="ws-image-thumb">
                                <img src="/tracking/api/workflows/${this.state.currentWorkflowNumber}/files/${img.id}/download" alt="${img.file_name || img.original_filename || ''}">
                                <div class="ws-image-check">
                                    <span class="material-symbols-rounded">check_circle</span>
                                </div>
                            </div>
                            <div class="ws-image-meta">
                                <div class="ws-image-name">${img.file_name || img.original_filename || '-'}</div>
                                <div class="ws-image-date">${this.formatFileSize(img.file_size)} • ${this.formatDateTime(this.getFileDate(img))}</div>
                            </div>
                        </div>
                    `;
                    }).join('');
                    this.elements.salesImageGrid.innerHTML = html;
            } else {
                    this.elements.salesImageGrid.innerHTML = '<p class="text-xs text-slate-400 italic text-center py-8 w-full">暂无参考图片</p>';
                }
            }

            if (this.elements.salesFileList) {
                const docFiles = this.getSortedFiles(
                    files.filter(f => !this.isImageFile(f))
                );

                if (docFiles.length > 0) {
                    const canDelete = this.isSales();
                    const html = docFiles.map(f => {
                const downloadUrl = `/tracking/api/workflows/${this.state.currentWorkflowNumber}/files/${f.id}/download`;
                return `
                            <div class="flex items-center gap-4 p-5 bg-white border border-slate-100 rounded-2xl hover:border-brand-600/30 hover:shadow-xl transition-all group">
                                <div class="w-12 h-12 bg-slate-100 text-slate-500 flex items-center justify-center rounded-xl shadow-inner group-hover:scale-110 transition-transform">
                                    <span class="material-symbols-rounded text-2xl">description</span>
                        </div>
                        <div class="flex-1 min-w-0">
                            <p class="text-sm font-bold text-slate-700 truncate">${f.file_name || f.original_filename || '-'}</p>
                            <p class="text-[10px] text-slate-400 font-bold uppercase tracking-widest mt-0.5">
                                        ${this.formatFileSize(f.file_size)} • ${this.formatDateTime(this.getFileDate(f))}
                            </p>
                        </div>
                                <div class="flex items-center gap-1">
                        <button onclick="event.stopPropagation(); window.open('${downloadUrl}', '_blank');"
                                            class="ws-file-action-btn">
                                        <span class="material-symbols-rounded">file_download</span>
                        </button>
                                    ${canDelete ? `
                                    <button onclick="event.stopPropagation(); WorkspaceDrawer.deleteSingleFile(false, ${f.id});"
                                            class="ws-delete-btn">
                                        <span class="material-symbols-rounded">delete</span>
                                    </button>
                                    ` : ''}
                                </div>
                    </div>
                `;
            }).join('');
                    this.elements.salesFileList.innerHTML = html;
                } else {
                    this.elements.salesFileList.innerHTML = '<p class="text-xs text-slate-400 italic text-center py-8">暂无规范文件</p>';
                }
            }

            // 业务员上传按钮（业务员可见，管理员也可管理业务附件）
            if (this.elements.salesUploadBtn) {
                this.elements.salesUploadBtn.classList.toggle('hidden', !this.canOperate());
            }
            if (this.elements.salesSelectBtn) {
                this.elements.salesSelectBtn.classList.toggle('hidden', !this.canOperate());
            }
            if (this.elements.salesDeleteBtn) {
                this.elements.salesDeleteBtn.classList.toggle('hidden', !this.canOperate());
            }
            if (this.elements.salesDateToggleBtn) {
                this.elements.salesDateToggleBtn.classList.toggle('active', this.state.showImageDate);
                const icon = this.elements.salesDateToggleBtn.querySelector('.material-symbols-rounded');
                if (icon) icon.textContent = this.state.showImageDate ? 'visibility' : 'visibility_off';
            }
            this.updateSelectionUI(false);
        },

        /**
         * 渲染底部快速操作（流程快速操作 + 訂單系統管理）
         */
        renderQuickActions() {
            // 渲染流程快速操作
            if (this.elements.quickActionsGrid) {
                if (!this.state.currentStatus) {
                    this.elements.quickActionsGrid.innerHTML = '';
                } else {
                    // 使用 STATUS_SYSTEM.js 的 getQuickActions 函数
                    const actions = typeof getQuickActions === 'function' ? 
                        getQuickActions(this.state.currentStatus) : [];

                    if (actions.length === 0) {
                        this.elements.quickActionsGrid.innerHTML = '';
                    } else {
                        const html = actions.map(action => {
                            // 根据 action.color 决定按钮样式（小红书风格）
                            const isConfirm = action.color === 'confirm';
                            const btnClass = isConfirm ? 'ws-action-btn-confirm' : 'ws-action-btn-warning';

                            return `
                                <button onclick="WorkspaceDrawer.handleQuickActionWithLoading('${action.action}', this, this.querySelector('.ws-action-btn-text'))"
                                        class="ws-action-btn ${btnClass}">
                                    <span class="material-symbols-rounded ws-action-btn-icon">
                                        ${isConfirm ? 'send' : 'edit'}
                                    </span>
                                    <span class="ws-action-btn-text">${action.label}</span>
                                </button>
                            `;
                        }).join('');

                        this.elements.quickActionsGrid.innerHTML = html;
                    }
                }
            }

            // 渲染訂單系統管理按鈕（只保留取消訂單）
            if (this.elements.orderManagementGrid) {
                const html = `
                    <button onclick="WorkspaceDrawer.handleCancelOrder()"
                            class="ws-action-btn ws-action-btn-danger">
                        <span class="material-symbols-rounded ws-action-btn-icon">block</span>
                        <span class="ws-action-btn-text">取消订单</span>
                    </button>
                `;
                this.elements.orderManagementGrid.innerHTML = html;
            }

            // 更新底部固定操作栏（根据当前状态显示主要操作）
            this.renderFooterActions();
        },

        /**
         * 渲染底部固定操作栏
         */
        renderFooterActions() {
            if (!this.elements.quickActionBtn) return;
            const canOperate = this.canOperate();
            if (!canOperate) {
                this.elements.quickActionBtn.style.display = 'none';
                if (this.elements.skipBtn) this.elements.skipBtn.style.display = 'none';
                if (this.elements.footer) this.elements.footer.style.display = 'none';
                return;
            }

            const textEl = this.elements.quickActionBtn.querySelector('.ws-footer-btn-text');
            const iconEl = this.elements.quickActionBtn.querySelector('.ws-footer-btn-icon');
            
            const statusText = typeof displayStatus === 'function' && this.state.currentStatus ?
                displayStatus(this.state.currentStatus) : 
                (this.state.currentStatus || '未知状态');
            
            // 检查是否有可执行的操作
            const actions = typeof getQuickActions === 'function' && this.state.currentStatus ? 
                getQuickActions(this.state.currentStatus) : [];

            const confirmActions = actions.filter(a => a.color === 'confirm');

            if (confirmActions.length > 1) {
                // 多個按鈕：隱藏主按鈕，在 footer 內動態插入多個按鈕
                this.elements.quickActionBtn.style.display = 'none';
                
                const footerContent = this.elements.footer.querySelector('.ws-footer-content');
                // 移除舊的多按鈕容器
                const oldMulti = footerContent.querySelector('.ws-footer-multi-btns');
                if (oldMulti) oldMulti.remove();
                
                const multiContainer = document.createElement('div');
                multiContainer.className = 'ws-footer-multi-btns';
                multiContainer.style.cssText = 'display:flex; gap:0.5rem; flex:1;';
                
                confirmActions.forEach(action => {
                    const btn = document.createElement('button');
                    btn.className = 'ws-footer-btn-primary';
                    btn.style.flex = '1';
                    btn.innerHTML = `<span class="ws-footer-btn-text">${action.label}</span><span class="material-symbols-rounded ws-footer-btn-icon">arrow_forward</span>`;
                    btn.onclick = () => this.handleQuickActionWithLoading(action.action, btn, btn.querySelector('.ws-footer-btn-text'));
                    multiContainer.appendChild(btn);
                });
                
                // 插入在 skipBtn 前面
                const skipBtn = footerContent.querySelector('#wsSkipBtn');
                footerContent.insertBefore(multiContainer, skipBtn);
                
            } else {
                // 移除舊的多按鈕容器
                const footerContent = this.elements.footer.querySelector('.ws-footer-content');
                const oldMulti = footerContent.querySelector('.ws-footer-multi-btns');
                if (oldMulti) oldMulti.remove();
                
                const mainAction = confirmActions[0];
                if (mainAction) {
                    this.elements.quickActionBtn.style.display = 'flex';
                    this.elements.quickActionBtn.onclick = () => this.handleQuickActionWithLoading(mainAction.action, this.elements.quickActionBtn, textEl);
                    this.elements.quickActionBtn.style.cursor = 'pointer';
                    this.elements.quickActionBtn.style.opacity = '1';
                    if (textEl) textEl.textContent = mainAction.label || statusText;
                    if (iconEl) iconEl.textContent = 'arrow_forward';
                } else {
                    this.elements.quickActionBtn.style.display = 'flex';
                    this.elements.quickActionBtn.onclick = null;
                    this.elements.quickActionBtn.style.cursor = 'default';
                    this.elements.quickActionBtn.style.opacity = '0.7';
                    if (textEl) textEl.textContent = statusText;
                    if (iconEl) iconEl.textContent = 'info';
                }
            }
        },

        /**
         * 處理取消訂單
         */
        handleCancelOrder() {
            console.log('[WorkspaceDrawer] 取消訂單:', this.state.currentOrderNumber);
            // TODO: 實現取消訂單功能
            if (typeof showToast === 'function') {
                showToast('提示', '取消訂單功能開發中', 'info');
            }
        },

        /**
         * 处理快速操作
         */
        // Quick action with loading state
        async handleQuickActionWithLoading(action, buttonEl, textEl) {
            const btn = buttonEl || document.getElementById('wsQuickActionBtn');
            const labelEl = textEl || document.getElementById('wsQuickActionText');
            const iconEl = btn ? btn.querySelector('.ws-footer-btn-icon') : null;
            const prevLabel = labelEl ? labelEl.textContent : '';
            const prevIcon = iconEl ? iconEl.textContent : '';

            // 出货动作先选择实际日期；用户取消时不进入 loading 状态。
            let actionDetails = null;
            if (typeof isShippingAction === 'function' && isShippingAction(action) && typeof requestShippingActionDetails === 'function') {
                const actionMap = typeof getQuickActions === 'function' ? getQuickActions(this.state.currentStatus) : [];
                const actionInfo = Array.isArray(actionMap) ? actionMap.find(item => item.action === action) : null;
                actionDetails = await requestShippingActionDetails({
                    action,
                    orderNumber: this.state.currentWorkflowNumber || this.state.currentOrderNumber,
                    currentStatus: this.state.currentStatus,
                    nextStatus: actionInfo ? actionInfo.next : ''
                });
                if (!actionDetails) return;
            }

            if (btn) {
                btn.disabled = true;
                btn.classList.add('ws-btn-loading');
            }
            if (labelEl) {
                labelEl.textContent = '處理中...';
            }
            if (iconEl) {
                iconEl.textContent = 'autorenew';
            }

            try {
                await this.handleQuickAction(action, actionDetails);
            } finally {
                setTimeout(() => {
                    if (btn) {
                        btn.disabled = false;
                        btn.classList.remove('ws-btn-loading');
                    }
                    if (iconEl) {
                        iconEl.textContent = prevIcon || 'arrow_forward';
                    }
                    if (labelEl && prevLabel) {
                        labelEl.textContent = prevLabel;
                    }
                    this.renderQuickActions();
                }, 600);
            }
        },

        async handleQuickAction(action, actionDetails = null) {
            const self = this;
            console.log('[WorkspaceDrawer] 快速操作:', action);

            try {
                const requestBody = {
                    action: action,
                    expected_status: this.state.currentStatus,
                    expected_history_id: this.state.lastHistoryId
                };
                if (actionDetails) {
                    requestBody.action_date = actionDetails.date;
                    requestBody.notes = actionDetails.notes || '';
                }
                const res = await fetch(`/tracking/api/workflows/${this.state.currentWorkflowNumber}/status`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                });

                const data = await res.json();

                if (data.success) {
                    if (typeof showToast === 'function') {
                        showToast('成功', data.message || '状态已更新');
                    }
                    const latestHistoryId = (data && data.data && data.data.latest_history_id)
                        || data.latest_history_id
                        || data.last_history_id
                        || '';
                    if (latestHistoryId) {
                        this.state.lastHistoryId = latestHistoryId;
                        const row = document.querySelector(`tr[data-workflow-number="${this.state.currentWorkflowNumber}"]`)
                            || document.querySelector(`tr[data-order-number="${this.state.currentOrderNumber}"]`);
                        if (row) {
                            row.dataset.historyId = latestHistoryId;
                            const actionsCell = row.querySelector('.actions-cell');
                            if (actionsCell) {
                                actionsCell.dataset.historyId = latestHistoryId;
                            }
                        }
                    }
                    if (typeof refreshAllComponents === 'function') {
                        refreshAllComponents(self.state.currentOrderNumber, self.state.currentWorkflowNumber);
                    }
                    // 重新加载数据
                    self.loadData(self.state.currentWorkflowNumber);
                    window.dispatchEvent(new CustomEvent('tracking:workspace-updated', {detail:{
                        orderNumber: self.state.currentOrderNumber || '',
                        workflowNumber: self.state.currentWorkflowNumber || ''
                    }}));
                } else {
                    throw new Error(data.error || '更新失败');
                }

            } catch (error) {
                console.error('[WorkspaceDrawer] 快速操作失败:', error);
                if (typeof showToast === 'function') {
                    showToast('错误', error.message || '操作失败', 'error');
                }
            }
        },

        /**
         * 切换 TAB
         */
        switchTab(tab) {
            this.state.currentTab = tab;

            // 更新 TAB 按钮样式
            const tabs = ['admin_ref', 'process', 'files'];
            tabs.forEach(t => {
                const btn = this.elements[`tab${t === 'admin_ref' ? 'AdminRef' : t === 'process' ? 'Process' : 'Files'}`];
                const content = this.elements[`content${t === 'admin_ref' ? 'AdminRef' : t === 'process' ? 'Process' : 'Files'}`];

                if (btn) {
                    if (t === tab) {
                        btn.classList.add('active', 'tab-active');
                        btn.classList.remove('text-slate-400');
                        btn.classList.add('text-brand-600');
                    } else {
                        btn.classList.remove('active', 'tab-active');
                        btn.classList.remove('text-brand-600');
                        btn.classList.add('text-slate-400');
                    }
                }

                if (content) {
                    content.classList.toggle('hidden', t !== tab);
                }
            });

            // 預覽面板跟著 tab 同步：切到業務附件顯示業務圖，切到主管參考顯示主管圖
            const isPreviewOpen = this.elements.previewPanel &&
                this.elements.previewPanel.style.width === '420px';
            if (isPreviewOpen) {
                if (tab === 'files') {
                    const images = this.state.salesImageFiles || [];
                    if (images.length > 0) {
                        this.state.currentPreviewIsWorkflowFile = true;
                        this.openPreviewWorkflowImage(0);
                    } else {
                        this._showPreviewNoImage();
                    }
                } else if (tab === 'admin_ref') {
                    const images = this.state.adminImageFiles || [];
                    if (images.length > 0) {
                        this.state.currentPreviewIsWorkflowFile = false;
                        this.openPreviewImage(0);
                    } else {
                        this._showPreviewNoImage();
                    }
                }
            }
        },

        /**
         * 打开预览
         */
        openPreview(fileId, filename, isWorkflowFile = false) {
            console.log('[WorkspaceDrawer] 打开预览:', fileId, filename, isWorkflowFile);

            // 保存當前預覽的文件信息
            this.state.currentPreviewFileId = fileId;
            this.state.currentPreviewFileName = filename;
            this.state.currentPreviewIsWorkflowFile = isWorkflowFile;
            const sourceFiles = isWorkflowFile ? this.state.workflowFiles : this.state.orderFiles;
            const matched = sourceFiles.find(f => String(f.id) === String(fileId));
            this.state.previewImages = [{
                id: fileId,
                file_name: filename,
                file_size: matched ? matched.file_size : null
            }];
            this.state.currentPreviewIndex = 0;
            this.updatePreviewDisplay();
        },

        openPreviewImage(index) {
            const images = this.state.adminImageFiles || [];
            if (images.length === 0) return;
            this.state.previewImages = images;
            this.state.currentPreviewIsWorkflowFile = false;
            this.state.currentPreviewIndex = index;
            this.updatePreviewDisplay();
        },

        openPreviewWorkflowImage(index) {
            const images = this.state.salesImageFiles || [];
            if (images.length === 0) return;
            this.state.previewImages = images;
            this.state.currentPreviewIsWorkflowFile = true;
            this.state.currentPreviewIndex = index;
            this.updatePreviewDisplay();
        },

        updatePreviewDisplay() {
            const images = this.state.previewImages || [];
            if (images.length === 0) return;
            const img = images[this.state.currentPreviewIndex];
            if (!img) return;

            this.state.currentPreviewFileId = img.id;
            this.state.currentPreviewFileName = img.file_name || img.original_filename || '';

            const previewUrl = this.state.currentPreviewIsWorkflowFile
                ? `/tracking/api/workflows/${this.state.currentWorkflowNumber}/files/${img.id}/download`
                : `/tracking/api/orders/files/${img.id}/download`;
            if (this.elements.previewImg) {
                this.elements.previewImg.src = previewUrl;
            }
            if (this.elements.previewName) {
                this.elements.previewName.textContent = this.state.currentPreviewFileName || '-';
            }
            if (this.elements.previewFullscreenImage) {
                this.elements.previewFullscreenImage.src = previewUrl;
            }
            if (this.elements.previewFullscreenTitle) {
                this.elements.previewFullscreenTitle.textContent = `${this.state.currentPreviewFileName || '-'} (${this.state.currentPreviewIndex + 1}/${images.length})`;
            }
            const sizeLabel = this.formatFileSize(img.file_size);
            const dateLabel = this.formatDateTime(this.getFileDate(img));
            if (this.elements.previewMeta) {
                this.elements.previewMeta.textContent = `${this.state.currentPreviewFileName || '-'} • ${sizeLabel} • ${dateLabel}`;
            }
            if (this.elements.previewFullscreenMeta) {
                this.elements.previewFullscreenMeta.textContent = `${this.state.currentPreviewFileName || '-'} • ${sizeLabel} • ${dateLabel}`;
            }
            if (this.elements.previewPanel) {
                this.elements.previewPanel.style.width = '420px';
                this.elements.previewPanel.style.opacity = '1';
            }
            this.updatePreviewCounter();
        },

        updatePreviewCounter() {
            if (this.elements.previewCounter) {
                const total = (this.state.previewImages || []).length;
                const current = total ? this.state.currentPreviewIndex + 1 : 0;
                this.elements.previewCounter.textContent = `${current} / ${total}`;
            }
            if (this.elements.previewPrevBtn) {
                this.elements.previewPrevBtn.style.display = (this.state.previewImages || []).length > 1 ? 'flex' : 'none';
            }
            if (this.elements.previewNextBtn) {
                this.elements.previewNextBtn.style.display = (this.state.previewImages || []).length > 1 ? 'flex' : 'none';
            }
        },

        prevPreviewImage() {
            const total = (this.state.previewImages || []).length;
            if (total <= 1) return;
            this.state.currentPreviewIndex = (this.state.currentPreviewIndex - 1 + total) % total;
            this.updatePreviewDisplay();
        },

        nextPreviewImage() {
            const total = (this.state.previewImages || []).length;
            if (total <= 1) return;
            this.state.currentPreviewIndex = (this.state.currentPreviewIndex + 1) % total;
            this.updatePreviewDisplay();
        },

        togglePreviewFullscreen(show) {
            if (!this.elements.previewFullscreen) return;
            if (show) {
                this.elements.previewFullscreen.classList.remove('hidden');
            } else {
                this.elements.previewFullscreen.classList.add('hidden');
            }
        },

        /**
         * 关闭预览
         */
        _showPreviewNoImage() {
            // 保持預覽面板開著，顯示暫無圖片
            if (this.elements.previewPanel) {
                this.elements.previewPanel.style.width = '420px';
                this.elements.previewPanel.style.opacity = '1';
            }
            if (this.elements.previewImg) {
                this.elements.previewImg.src = '';
                this.elements.previewImg.alt = '暫無圖片';
            }
            if (this.elements.previewName) {
                this.elements.previewName.textContent = '暫無圖片';
            }
            if (this.elements.previewMeta) {
                this.elements.previewMeta.textContent = '';
            }
            if (this.elements.previewCounter) {
                this.elements.previewCounter.textContent = '0 / 0';
            }
            if (this.elements.previewPrevBtn) this.elements.previewPrevBtn.style.display = 'none';
            if (this.elements.previewNextBtn) this.elements.previewNextBtn.style.display = 'none';
            this.state.previewImages = [];
            this.state.currentPreviewIndex = 0;
        },

        closePreview() {
            if (this.elements.previewPanel) {
                this.elements.previewPanel.style.width = '0';
                this.elements.previewPanel.style.opacity = '0';
            }
            if (this.elements.previewFullscreen) {
                this.elements.previewFullscreen.classList.add('hidden');
            }
            // 清除預覽狀態
            this.state.currentPreviewFileId = null;
            this.state.currentPreviewFileName = null;
            this.state.previewImages = [];
            this.state.currentPreviewIndex = 0;
        },

        /**
         * 格式化文件大小
         */
        formatFileSize(bytes) {
            if (bytes === null || bytes === undefined) return '-';
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
        },

        getFileDate(file) {
            return file.uploaded_at || file.created_at || file.date || '';
        },

        formatDateTime(value) {
            if (!value) return '-';
            const d = new Date(value);
            if (Number.isNaN(d.getTime())) {
                const parts = value.split('T');
                return parts.length > 1 ? `${parts[0]} ${parts[1].slice(0, 5)}` : value;
            }
            const y = d.getFullYear();
            const m = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            const hh = String(d.getHours()).padStart(2, '0');
            const mm = String(d.getMinutes()).padStart(2, '0');
            return `${y}-${m}-${day} ${hh}:${mm}`;
        },

        getSortedFiles(files) {
            return [...files].sort((a, b) => {
                const da = new Date(this.getFileDate(a) || 0).getTime() || 0;
                const db = new Date(this.getFileDate(b) || 0).getTime() || 0;
                return db - da;
            });
        },

        isImageFile(file) {
            const type = (file.file_type || file.mime_type || '').toLowerCase();
            const name = (file.file_name || file.original_filename || '').toLowerCase();
            if (type.startsWith('image')) return true;
            return /\.(jpg|jpeg|png|gif|webp)$/i.test(name);
        },

        /**
         * 打开上传模态框
         */
        openUploadModal(isAdminContext = true) {
            if (!this.state.currentOrderNumber) {
                if (typeof showToast === 'function') {
                    showToast('错误', '请先选择订单', 'error');
                }
                return;
            }
            const isAdmin = this.isAdmin();
            const isSales = this.isSales();
            if ((isAdminContext && !isAdmin) || (!isAdminContext && !isSales)) {
                if (typeof showToast === 'function') {
                    showToast('错误', '无权限', 'error');
                }
                return;
            }
            if (!isAdminContext && !this.state.currentWorkflowNumber) {
                if (typeof showToast === 'function') {
                    showToast('错误', '请先选择工作流', 'error');
                }
                return;
            }

            this.state.uploadContext = isAdminContext;

            if (this.elements.uploadModal) {
                this.elements.uploadModal.classList.remove('hidden');
            }
            const form = document.getElementById('wsUploadForm');
            if (form) form.reset();
            if (this.elements.uploadModalTitle) {
                this.elements.uploadModalTitle.textContent = isAdminContext ? '上传主管参考附件' : '上传业务附件';
            }
            this.updateUploadFileList([]);
        },

        /**
         * 关闭上传模态框
         */
        closeUploadModal() {
            if (this.elements.uploadModal) {
                this.elements.uploadModal.classList.add('hidden');
            }
            this.state.uploadContext = null;
            this.updateUploadFileList([]);
        },

        /**
         * 提交上传文件
         */
        async submitUploadFiles() {
            const filesInput = document.getElementById('wsUploadFiles');
            if (!filesInput || !filesInput.files || filesInput.files.length === 0) {
                if (typeof showToast === 'function') {
                    showToast('错误', '请选择文件', 'error');
                }
                return;
            }

            const files = filesInput.files;
            const formData = new FormData();
            for (let i = 0; i < files.length; i++) {
                formData.append('files', files[i]);
            }

            try {
                const isAdminContext = this.state.uploadContext !== false;
                const uploadUrl = isAdminContext
                    ? `/tracking/api/orders/${this.state.currentOrderNumber}/files/upload`
                    : `/tracking/api/workflows/${this.state.currentWorkflowNumber}/files/upload`;
                const response = await fetch(uploadUrl, {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();

                if (result.success) {
                    if (typeof showToast === 'function') {
                        showToast('成功', result.message || '文件上传成功', 'success');
                    }
                    this.closeUploadModal();
                    // 重新加载数据
                    await this.loadData(this.state.currentWorkflowNumber);
                } else {
                    if (typeof showToast === 'function') {
                        showToast('上传失败', result.error || '未知错误', 'error');
                    }
                }
            } catch (error) {
                console.error('[WorkspaceDrawer] 上传文件失败:', error);
                if (typeof showToast === 'function') {
                    showToast('错误', '网络错误', 'error');
                }
            }
        },

        updateUploadFileList(files) {
            const listEl = document.getElementById('wsUploadFileList');
            if (!listEl) return;
            const fileArray = Array.from(files || []);
            if (fileArray.length === 0) {
                listEl.classList.add('hidden');
                listEl.innerHTML = '';
                return;
            }
            listEl.classList.remove('hidden');
            listEl.innerHTML = fileArray.map(f => `
                <div class="ws-upload-file-item">
                    <span>${f.name}</span>
                    <span>${this.formatFileSize(f.size)}</span>
                </div>
            `).join('');
        },

        handleImageClick(isAdminContext, index, fileId) {
            const mode = isAdminContext ? this.state.adminSelectionMode : this.state.salesSelectionMode;
            if (mode) {
                this.toggleSelectImage(isAdminContext, fileId);
                return;
            }
            if (isAdminContext) {
                this.openPreviewImage(index);
            } else {
                this.openPreviewWorkflowImage(index);
            }
        },

        toggleSelectionMode(isAdminContext) {
            if (isAdminContext) {
                this.state.adminSelectionMode = !this.state.adminSelectionMode;
                if (!this.state.adminSelectionMode) this.state.adminSelectedIds.clear();
                this.renderAdminRef();
            } else {
                if (!this.canOperate()) {
                    if (typeof showToast === 'function') {
                        showToast('提示', '无权限', 'info');
                    }
                    return;
                }
                this.state.salesSelectionMode = !this.state.salesSelectionMode;
                if (!this.state.salesSelectionMode) this.state.salesSelectedIds.clear();
                this.renderFiles();
            }
        },

        toggleSelectImage(isAdminContext, fileId) {
            const set = isAdminContext ? this.state.adminSelectedIds : this.state.salesSelectedIds;
            if (set.has(fileId)) {
                set.delete(fileId);
            } else {
                set.add(fileId);
            }
            if (isAdminContext) {
                this.renderAdminRef();
            } else {
                this.renderFiles();
            }
        },

        updateSelectionUI(isAdminContext) {
            const isAdmin = isAdminContext;
            const grid = isAdmin ? this.elements.adminImageGrid : this.elements.salesImageGrid;
            const selectBtn = isAdmin ? this.elements.adminSelectBtn : this.elements.salesSelectBtn;
            const deleteBtn = isAdmin ? this.elements.adminDeleteBtn : this.elements.salesDeleteBtn;
            const selectedCount = isAdmin ? this.state.adminSelectedIds.size : this.state.salesSelectedIds.size;
            const mode = isAdmin ? this.state.adminSelectionMode : this.state.salesSelectionMode;

            if (grid) {
                grid.classList.toggle('selection-mode', mode);
                grid.classList.toggle('hide-date', !this.state.showImageDate);
            }
            if (selectBtn) {
                selectBtn.classList.toggle('active', mode);
            }
            if (deleteBtn) {
                deleteBtn.disabled = selectedCount === 0;
                deleteBtn.classList.toggle('disabled', selectedCount === 0);
                deleteBtn.title = selectedCount > 0 ? `删除所选（${selectedCount}）` : '删除所选';
            }
        },

        async deleteSelectedImages(isAdminContext) {
            const isAdmin = isAdminContext;
            const selected = isAdmin ? this.state.adminSelectedIds : this.state.salesSelectedIds;
            if (selected.size === 0) {
                if (typeof showToast === 'function') {
                    showToast('提示', '请先选择要删除的图片', 'info');
                }
                return;
            }
            const confirmMessage = `确认删除所选 ${selected.size} 个图片？`;
            const confirmed = typeof window.showConfirmModal === 'function'
                ? await window.showConfirmModal(confirmMessage, '确认删除', '确认删除', '取消', true)
                : confirm(confirmMessage);
            if (!confirmed) return;

            const ids = Array.from(selected);
            const deleteUrl = (id) => isAdmin
                ? `/tracking/api/orders/files/${id}`
                : `/tracking/api/workflows/files/${id}`;

            try {
                const results = await Promise.all(ids.map(async id => {
                    const res = await fetch(deleteUrl(id), { method: 'DELETE' });
                    let data = null;
                    try {
                        data = await res.json();
                    } catch (e) {
                        data = null;
                    }
                    return { ok: res.ok, data };
                }));
                const failed = results.find(r => !r.ok || (r.data && r.data.success === false));
                if (failed) {
                    const errorMsg = (failed.data && failed.data.error) || '删除失败';
                    if (typeof showToast === 'function') {
                        showToast('错误', errorMsg, 'error');
                    }
                    return;
                }
                if (typeof showToast === 'function') {
                    showToast('成功', '已删除所选图片', 'success');
                }
                selected.clear();
                if (isAdmin) {
                    this.state.adminSelectionMode = false;
                } else {
                    this.state.salesSelectionMode = false;
                }
                await this.loadData(this.state.currentWorkflowNumber);
            } catch (error) {
                if (typeof showToast === 'function') {
                    showToast('错误', '删除失败', 'error');
                }
            }
        },

        async deleteSingleFile(isAdminContext, fileId) {
            const isAdmin = isAdminContext;
            const allowed = isAdmin ? this.isAdmin() : this.isSales();
            if (!allowed) {
                if (typeof showToast === 'function') {
                    showToast('错误', '无权限', 'error');
                }
                return;
            }
            const confirmMessage = '确认删除该文件？';
            const confirmed = typeof window.showConfirmModal === 'function'
                ? await window.showConfirmModal(confirmMessage, '确认删除', '确认删除', '取消', true)
                : confirm(confirmMessage);
            if (!confirmed) return;
            const deleteUrl = isAdmin
                ? `/tracking/api/orders/files/${fileId}`
                : `/tracking/api/workflows/files/${fileId}`;
            try {
                const res = await fetch(deleteUrl, { method: 'DELETE' });
                let result = null;
                try {
                    result = await res.json();
                } catch (e) {
                    result = null;
                }
                if (!res.ok || (result && result.success === false)) {
                    const errorMsg = (result && result.error) || '删除失败';
                    if (typeof showToast === 'function') {
                        showToast('错误', errorMsg, 'error');
                    }
                    return;
                }
                if (typeof showToast === 'function') {
                    showToast('成功', '已删除文件', 'success');
                }
                await this.loadData(this.state.currentWorkflowNumber);
            } catch (error) {
                if (typeof showToast === 'function') {
                    showToast('错误', '删除失败', 'error');
                }
            }
        },

        initImageDatePreference() {
            const stored = localStorage.getItem('wsShowImageDate');
            this.state.showImageDate = stored === null ? true : stored === '1';
        },

        toggleImageDate() {
            this.state.showImageDate = !this.state.showImageDate;
            localStorage.setItem('wsShowImageDate', this.state.showImageDate ? '1' : '0');
            this.renderAdminRef();
            this.renderFiles();
        }
    };

    // 初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => WorkspaceDrawer.init());
    } else {
        WorkspaceDrawer.init();
    }

    // 导出到全局
    window.WorkspaceDrawer = WorkspaceDrawer;
    if (typeof window.editStep !== 'function') {
        window.editStep = function(index) {
            if (window.WorkspaceDrawer && typeof window.WorkspaceDrawer.toggleTimelineEdit === 'function') {
                window.WorkspaceDrawer.toggleTimelineEdit(index);
            }
        };
    }

})();