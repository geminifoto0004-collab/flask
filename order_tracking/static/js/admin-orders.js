// Admin 訂單管理頁面 JavaScript
console.log('=== admin-orders.js 已加載 ===');

var appPerm = window.AppPermissions || window.appPerm || {};
var isAdminRole = window.isAdminRole || (() => (typeof appPerm.isAdmin === 'function'
    ? appPerm.isAdmin()
    : (appPerm.can ? appPerm.can('view', 'user') : false)));
window.isAdminRole = isAdminRole;

let currentPage = 1;
let poolPageSize = parseInt(localStorage.getItem('poolPageSize') || '50', 10);
let skipPageSize = parseInt(localStorage.getItem('skipPageSize') || '50', 10);

// ==================== 訂單號管理 ====================
// 注意：loadNumberPool 函數已刪除，改用 loadAllOrders

function getStatusLabel(status) {
    const labels = {
        'available': '可用',
        'used': '已使用',
        'reserved': '預留',
        'skip': '跳號'
    };
    // 兼容舊數據：legacy 和 confirmed_skip 都顯示為跳號
    if (status === 'legacy' || status === 'confirmed_skip') {
        return '跳號';
    }
    return labels[status] || status;
}

// ==================== 生成號段 ====================
let currentGenerateType = 'numeric';

function parseOrderNumber(num) {
    const match = String(num || '').trim().match(/^([A-Za-z]*)(\d+)$/);
    if (!match) return null;
    return { prefix: match[1].toUpperCase(), digits: parseInt(match[2], 10) };
}

function getDefaultGenerateYear() {
    return String(new Date().getFullYear()).slice(-2);
}

function setGenerateType(type) {
    currentGenerateType = (type === 'KC' || type === 'G') ? type : 'numeric';
    const modeInput = document.getElementById('generate-mode');
    const numericFields = document.getElementById('generate-numeric-fields');
    const prefixFields = document.getElementById('generate-prefix-fields');

    if (modeInput) modeInput.value = currentGenerateType;
    if (numericFields) numericFields.style.display = currentGenerateType === 'numeric' ? 'block' : 'none';
    if (prefixFields) prefixFields.style.display = currentGenerateType === 'numeric' ? 'none' : 'block';

    const btnNumeric = document.getElementById('generate-type-numeric');
    const btnKC = document.getElementById('generate-type-kc');
    const btnG = document.getElementById('generate-type-g');
    if (btnNumeric) btnNumeric.className = `btn ${currentGenerateType === 'numeric' ? 'btn-primary' : 'btn-secondary'}`;
    if (btnKC) btnKC.className = `btn ${currentGenerateType === 'KC' ? 'btn-primary' : 'btn-secondary'}`;
    if (btnG) btnG.className = `btn ${currentGenerateType === 'G' ? 'btn-primary' : 'btn-secondary'}`;

    if (currentGenerateType !== 'numeric') {
        updateGeneratePreview();
    }
}

async function updateGeneratePreview() {
    const previewEl = document.getElementById('generate-preview');
    const prefix = currentGenerateType;
    const year = (document.getElementById('generate-year')?.value || '').trim();
    const quantity = parseInt(document.getElementById('generate-quantity')?.value || '0', 10);

    if (!previewEl) return;
    if (!(prefix === 'KC' || prefix === 'G')) {
        previewEl.textContent = '预览：-';
        return;
    }
    if (!/^\d{2}$/.test(year) || !Number.isInteger(quantity) || quantity <= 0) {
        previewEl.textContent = '预览：请先填写正确的年份和数量';
        return;
    }

    try {
        const response = await fetch(`/tracking/api/order-number-pool/next-preview?prefix=${encodeURIComponent(prefix)}&year=${encodeURIComponent(year)}`);
        const data = await response.json();
        if (!data.success) {
            previewEl.textContent = `预览：${data.error || '获取失败'}`;
            return;
        }

        const maxSerial = Number(data.data?.max_serial || 0);
        const startSerial = maxSerial + 1;
        const endSerial = maxSerial + quantity;
        if (endSerial > 999) {
            previewEl.textContent = `预览：超出上限（当前最大 ${String(maxSerial).padStart(3, '0')}，最多到 999）`;
            return;
        }
        const startNumber = `${prefix}${year}${String(startSerial).padStart(3, '0')}`;
        const endNumber = `${prefix}${year}${String(endSerial).padStart(3, '0')}`;
        previewEl.textContent = `预览：${startNumber} ~ ${endNumber}`;
    } catch (error) {
        previewEl.textContent = '预览：获取失败，请稍后重试';
    }
}

function openBatchCreateModal() {
    const modal = document.getElementById('generateModal');
    modal.classList.add('show');
    document.getElementById('start-number').value = '';
    document.getElementById('end-number').value = '';
    const yearInput = document.getElementById('generate-year');
    const qtyInput = document.getElementById('generate-quantity');
    if (yearInput) yearInput.value = getDefaultGenerateYear();
    if (qtyInput) qtyInput.value = '1';
    setGenerateType('numeric');
}

async function generateNumbers() {
    const mode = document.getElementById('generate-mode')?.value || 'numeric';
    let payload = {};
    if (mode === 'numeric') {
        const startNumber = document.getElementById('start-number').value.trim();
        const endNumber = document.getElementById('end-number').value.trim();
    if (!startNumber || !endNumber) {
        showToast('請填寫起始和結束號碼', 'error');
        return;
    }
    
        const parsedStart = parseOrderNumber(startNumber);
        const parsedEnd = parseOrderNumber(endNumber);
        if (!parsedStart || !parsedEnd || parsedStart.prefix || parsedEnd.prefix) {
            showToast('純數字模式僅支持數字號碼', 'error');
            return;
        }
        if (parsedStart.digits > parsedEnd.digits) {
        showToast('起始號碼不能大於結束號碼', 'error');
        return;
    }
        const count = parsedEnd.digits - parsedStart.digits + 1;
    if (count > 10000) {
        showToast('單次生成不能超過 10000 個號碼', 'error');
        return;
        }
        payload = { start_number: startNumber, end_number: endNumber, prefix: '' };
    } else {
        const prefix = mode.trim().toUpperCase();
        const year = document.getElementById('generate-year')?.value.trim() || '';
        const quantity = parseInt(document.getElementById('generate-quantity')?.value || '0', 10);
        if (!(prefix === 'KC' || prefix === 'G')) {
            showToast('請選擇正確前綴（KC 或 G）', 'error');
            return;
        }
        if (!/^\d{2}$/.test(year)) {
            showToast('年份需為2位數字，例如 26', 'error');
            return;
        }
        if (!Number.isInteger(quantity) || quantity <= 0) {
            showToast('數量需為大於 0 的整數', 'error');
            return;
        }
        payload = { prefix, year, quantity };
    }
    
    const confirmBtn = document.getElementById('generateModalConfirm');
    const originalText = confirmBtn ? confirmBtn.textContent : '';
    if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.textContent = '生成中...';
    }

    try {
        const response = await fetch('/tracking/api/order-number-pool/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`成功生成 ${data.data.created || 0} 個號碼`, 'success');
            closeAdminModal('generateModal');
            showGenerateResult(data.data);
            
            // 刷新当前TAB的数据
            const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
            if (activeTab === 'all-orders') {
                // 如果在"订单号管理"TAB，刷新该TAB
                loadAllOrders(1);
            } else {
                // 如果不在"订单号管理"TAB，切换到该TAB并刷新
                const allOrdersTab = document.querySelector('.tab-btn[data-tab="all-orders"]');
                if (allOrdersTab) {
                    allOrdersTab.click();
                } else {
                    loadAllOrders(1);
                }
            }
        } else {
            showToast(data.error || '生成失敗', 'error');
        }
    } catch (error) {
        console.error('生成號段失敗:', error);
        showToast('網絡錯誤，請稍後重試', 'error');
    } finally {
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = originalText;
        }
    }
}

function showGenerateResult(result) {
    const modal = document.getElementById('generateResultModal');
    if (!modal) return;

    const created = result.created || 0;
    const skipped = result.skipped || 0;
    const skippedNumbers = result.skipped_numbers || [];
    const truncated = result.skipped_truncated;

    document.getElementById('result-created').textContent = created;
    document.getElementById('result-skipped').textContent = skipped;

    const successIcon = document.getElementById('result-success');
    if (successIcon) {
        successIcon.style.display = created > 0 ? 'block' : 'none';
    }

    const skippedSection = document.getElementById('result-skipped-section');
    const skippedContainer = document.getElementById('result-skipped-numbers');
    const moreHint = document.getElementById('result-more-hint');

    if (skipped > 0 && skippedNumbers.length > 0 && skippedSection && skippedContainer) {
        skippedSection.style.display = 'block';
        skippedContainer.innerHTML = skippedNumbers.map(num =>
            `<span style="background: #fff; border: 1px solid #e5e7eb; padding: 0.25rem 0.5rem; border-radius: 4px; text-align: center;">${num}</span>`
        ).join('');

        if (moreHint) {
            moreHint.style.display = truncated ? 'block' : 'none';
        }
    } else if (skippedSection) {
        skippedSection.style.display = 'none';
    }

    modal.classList.add('show');
}

// ==================== 標記號碼 ====================
function openMarkSkipModal() {
    const modal = document.getElementById('markModal');
    document.getElementById('mark-modal-title').textContent = '標記為跳號';
    document.getElementById('mark-numbers').value = '';
    modal.classList.add('show');
}

async function markSkipNumbers() {
    const text = document.getElementById('mark-numbers').value;
    if (!text.trim()) {
        showToast('請輸入號碼', 'error');
        return;
    }
    
    // 解析號碼（支持逗號、空格、換行分隔）
    const numbers = text.split(/[\n,\s]+/).filter(n => n.trim()).map(n => n.trim());
    
    try {
        const response = await fetch('/tracking/api/order-number-pool/mark-skip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ numbers })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(data.message, 'success');
            closeAdminModal('markModal');
            loadAllOrders();
        } else {
            showToast(data.error, 'error');
        }
    } catch (error) {
        console.error('標記失敗:', error);
        showToast('標記失敗', 'error');
    }
}

// ==================== 解鎖訂單 ====================
let unlockFiles = []; // 存儲要上傳的文件
let unlockFileNames = {}; // index → 用户自定义文件名（不含扩展名）
let unlockCustomerSuggestDebounce = null;
let unlockCustomerSuggestSeq = 0;
let unlockJustAdded = false;

function normalizeCustomerNameForInput(value) {
    if (value == null) return '';
    return String(value)
        .toUpperCase()
        .replace(/\s+/g, ' ');
}

function normalizeCustomerName(value) {
    return normalizeCustomerNameForInput(value).trim();
}

function enforceUppercaseInput(inputEl) {
    if (!inputEl || inputEl.dataset.uppercaseBound === '1') return;
    inputEl.dataset.uppercaseBound = '1';
    inputEl.addEventListener('input', () => {
        const start = inputEl.selectionStart;
        const end = inputEl.selectionEnd;
        const next = normalizeCustomerNameForInput(inputEl.value);
        if (inputEl.value !== next) {
            inputEl.value = next;
            try {
                // upper() 不改变长度，直接恢复光标即可
                if (typeof start === 'number' && typeof end === 'number') {
                    inputEl.setSelectionRange(start, end);
                }
            } catch (_) {}
        }
    });
}

function hideUnlockCustomerSuggestions() {
    const box = document.getElementById('unlock-customer-suggestions');
    if (!box) return;
    box.style.display = 'none';
    box.innerHTML = '';
    box.dataset.activeIndex = '-1';
}

function setUnlockCustomerActiveIndex(index) {
    const box = document.getElementById('unlock-customer-suggestions');
    if (!box) return;
    const items = Array.from(box.querySelectorAll('.customer-suggestion-item'));
    if (!items.length) {
        box.dataset.activeIndex = '-1';
        return;
    }
    const next = Math.max(0, Math.min(index, items.length - 1));
    items.forEach((el, i) => el.classList.toggle('active', i === next));
    box.dataset.activeIndex = String(next);
    items[next].scrollIntoView({ block: 'nearest' });
}

function renderUnlockCustomerSuggestions(names, query) {
    const input = document.getElementById('unlock-customer-name');
    const box = document.getElementById('unlock-customer-suggestions');
    if (!input || !box) return;

    const q = normalizeCustomerName(query || '');
    if (!q) {
        hideUnlockCustomerSuggestions();
        return;
    }

    if (!names || names.length === 0) {
        box.innerHTML = `<div class="customer-suggestions-empty">无匹配客户</div>`;
        box.style.display = 'block';
        box.dataset.activeIndex = '-1';
        return;
    }

    box.innerHTML = names.map((name) => {
        const raw = normalizeCustomerName(name);
        const safe = escapeHtml(raw);
        const encoded = encodeURIComponent(raw);
        return `<button type="button" class="customer-suggestion-item" data-value="${encoded}">${safe}</button>`;
    }).join('');

    box.querySelectorAll('.customer-suggestion-item').forEach((btn, idx) => {
        // 用 mousedown 避免 input blur 先触发导致点不到
        btn.addEventListener('mousedown', (e) => {
            e.preventDefault();
            const encoded = btn.getAttribute('data-value') || '';
            const value = normalizeCustomerName(decodeURIComponent(encoded || ''));
            input.value = value;
            hideUnlockCustomerSuggestions();
            input.focus();
        });
        btn.addEventListener('mousemove', () => setUnlockCustomerActiveIndex(idx));
    });

    box.style.display = 'block';
    setUnlockCustomerActiveIndex(0);
}

function setupUnlockCustomerAutocomplete() {
    const input = document.getElementById('unlock-customer-name');
    const box = document.getElementById('unlock-customer-suggestions');
    if (!input || !box) return;
    enforceUppercaseInput(input);

    const triggerSearch = () => {
        const normalizedInput = normalizeCustomerNameForInput(input.value || '');
        if (input.value !== normalizedInput) input.value = normalizedInput;
        const q = normalizedInput.trim();
        if (!q) {
            hideUnlockCustomerSuggestions();
            return;
        }
        if (unlockCustomerSuggestDebounce) clearTimeout(unlockCustomerSuggestDebounce);
        unlockCustomerSuggestDebounce = setTimeout(async () => {
            const seq = ++unlockCustomerSuggestSeq;
            try {
                const resp = await fetch(`/tracking/api/customers/search?q=${encodeURIComponent(q)}`);
                const data = await resp.json();
                if (seq !== unlockCustomerSuggestSeq) return; // 避免乱序响应覆盖
                if (data && data.success) {
                    renderUnlockCustomerSuggestions(data.data || [], q);
                } else {
                    hideUnlockCustomerSuggestions();
                }
            } catch (e) {
                hideUnlockCustomerSuggestions();
            }
        }, 200);
    };

    input.addEventListener('input', triggerSearch);
    input.addEventListener('focus', () => {
        if ((input.value || '').trim()) triggerSearch();
    });
    input.addEventListener('blur', () => {
        setTimeout(() => hideUnlockCustomerSuggestions(), 150);
    });
    input.addEventListener('keydown', (e) => {
        if (box.style.display === 'none') return;
        const items = Array.from(box.querySelectorAll('.customer-suggestion-item'));
        if (!items.length) return;

        const activeIndex = parseInt(box.dataset.activeIndex || '-1', 10);
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setUnlockCustomerActiveIndex((Number.isFinite(activeIndex) ? activeIndex : -1) + 1);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setUnlockCustomerActiveIndex((Number.isFinite(activeIndex) ? activeIndex : 0) - 1);
        } else if (e.key === 'Enter') {
            const idx = Number.isFinite(activeIndex) ? activeIndex : 0;
            const btn = items[Math.max(0, Math.min(idx, items.length - 1))];
            if (btn) {
                e.preventDefault();
                input.value = btn.getAttribute('data-value') || '';
                hideUnlockCustomerSuggestions();
            }
        } else if (e.key === 'Escape') {
            hideUnlockCustomerSuggestions();
        }
    });
}

function openUnlockModal(orderNumber) {
    const modal = document.getElementById('unlockModal');
    document.getElementById('unlock-order-number').value = orderNumber;
    document.getElementById('unlock-customer-name').value = '';
    hideUnlockCustomerSuggestions();
    const unlockOrderDate = document.getElementById('unlock-order-date');
    if (unlockOrderDate) {
        unlockOrderDate.value = new Date().toISOString().split('T')[0];
        unlockOrderDate.setAttribute('readonly', 'readonly');
    }
    document.getElementById('unlock-notes').value = '';
    
    // 清空文件列表
    unlockFiles = [];
    unlockFileNames = {};
    clearUnlockFiles();
    
    // 設置文件上傳事件
    setupUnlockFileUpload();
    
    modal.classList.add('show');
}

function setupUnlockFileUpload() {
    const fileInput = document.getElementById('unlock-file-input');
    const dropzone = document.getElementById('unlock-file-dropzone');
    const dropzoneMini = document.getElementById('unlock-file-dropzone-mini');
    
    // 點擊選擇文件
    if (fileInput) {
        fileInput.onchange = function(e) {
            if (e.target.files && e.target.files.length > 0) {
                handleUnlockFiles(e.target.files);
                const newInput = fileInput.cloneNode(true);
                fileInput.parentNode.replaceChild(newInput, fileInput);
                setupUnlockFileUpload(); // 重新设置事件
            }
        };
    }
    
    // 大 dropzone 的拖拽事件
    if (dropzone) {
        dropzone.ondragover = function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('drag-over');
        };
        
        dropzone.ondragleave = function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('drag-over');
        };
        
        dropzone.ondrop = function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('drag-over');
            handleUnlockFiles(e.dataTransfer.files);
        };
        
        // 點擊dropzone也可以選擇文件（但不要阻止按钮点击）
        dropzone.onclick = function(e) {
            if (e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
            const fileInput = document.getElementById('unlock-file-input');
            if (fileInput) fileInput.click();
        };
    }

    // 迷你 dropzone 也支持拖拽
    if (dropzoneMini) {
        dropzoneMini.ondragover = function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzoneMini.classList.add('drag-over');
        };
        dropzoneMini.ondragleave = function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzoneMini.classList.remove('drag-over');
        };
        dropzoneMini.ondrop = function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzoneMini.classList.remove('drag-over');
            handleUnlockFiles(e.dataTransfer.files);
        };
    }
}

function handleUnlockFiles(files) {
    const before = unlockFiles.length;
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        // 檢查文件類型
        if (file.type.startsWith('image/') || 
            file.type === 'application/pdf' ||
            file.name.endsWith('.doc') || file.name.endsWith('.docx') ||
            file.name.endsWith('.xls') || file.name.endsWith('.xlsx')) {
            
            // 檢查是否已存在
            if (!unlockFiles.find(f => f.name === file.name && f.size === file.size)) {
                unlockFiles.push(file);
            }
        }
    }
    unlockJustAdded = unlockFiles.length > before;
    renderUnlockFiles();
}

function renderUnlockFiles() {
    const panel = document.getElementById('unlock-files-panel');
    const fileItems = document.getElementById('unlock-file-items');
    const header = document.getElementById('unlock-files-header');
    const dropzone = document.getElementById('unlock-file-dropzone');
    const badge = document.getElementById('unlock-file-badge');
    
    if (!panel || !fileItems) return;
    
    const count = unlockFiles.length;

    if (count === 0) {
        // 没文件：显示大dropzone，隐藏文件面板
        panel.style.display = 'none';
        if (dropzone) dropzone.style.display = 'block';
        if (badge) { badge.style.display = 'none'; badge.textContent = ''; }
    } else {
        // 有文件：隐藏大dropzone，显示文件面板
        if (dropzone) dropzone.style.display = 'none';
        panel.style.display = 'block';

        // 标签旁的小徽章
        if (badge) {
            badge.style.display = 'inline-flex';
            badge.textContent = count;
        }

        // 顶部成功提示条
        const totalSize = unlockFiles.reduce((s, f) => s + (f && f.size ? f.size : 0), 0);
        header.innerHTML = `
            <div class="uf-header-left">
                <svg class="uf-check-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span>已选择 <strong>${count}</strong> 个文件</span>
                <span class="uf-header-size">${formatFileSize(totalSize)}</span>
            </div>
            <div class="uf-header-actions">
                <button type="button" class="uf-btn uf-btn-add" onclick="document.getElementById('unlock-file-input').click()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                    添加
                </button>
                <button type="button" class="uf-btn uf-btn-clear" onclick="clearUnlockFiles()">清空</button>
            </div>
        `;

        // 文件缩略图列表
        fileItems.innerHTML = unlockFiles.map((file, index) => {
            const isImage = file.type.startsWith('image/');
            const fileSize = formatFileSize(file.size);
            const ext = file.name.includes('.') ? file.name.substring(file.name.lastIndexOf('.')) : '';
            const baseName = file.name.includes('.') ? file.name.substring(0, file.name.lastIndexOf('.')) : file.name;
            const customName = unlockFileNames[index] !== undefined ? unlockFileNames[index] : baseName;
            
            let preview = '';
            if (isImage) {
                const url = URL.createObjectURL(file);
                preview = `<img class="file-item-preview uf-clickable" src="${url}" alt="${escapeHtml(file.name)}" onclick="previewUnlockImage(${index})" title="点击放大预览">`;
            } else {
                preview = `
                    <div class="file-item-icon">
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                            <polyline points="14 2 14 8 20 8"></polyline>
                        </svg>
                    </div>
                `;
            }
            return `
                <div class="file-item">
                    <button class="file-item-remove" onclick="removeUnlockFile(${index})" title="移除">×</button>
                    ${preview}
                    <div class="file-item-name-edit">
                        <input type="text" class="uf-name-input" value="${escapeHtml(customName)}" data-index="${index}" data-ext="${escapeHtml(ext)}" onchange="renameUnlockFile(${index}, this.value)" onclick="event.stopPropagation(); this.select();" title="点击修改文件名">
                        <span class="uf-name-ext">${escapeHtml(ext)}</span>
                    </div>
                    <div class="file-item-size">${fileSize}</div>
                </div>
            `;
        }).join('');

        // 新增后：短暂高亮提示
        if (unlockJustAdded) {
            unlockJustAdded = false;
            requestAnimationFrame(() => {
                panel.classList.add('uf-flash');
                setTimeout(() => panel.classList.remove('uf-flash'), 900);
            });
        }
    }
}

function renameUnlockFile(index, newBaseName) {
    newBaseName = (newBaseName || '').trim();
    if (!newBaseName) {
        // 恢复原始名
        delete unlockFileNames[index];
        renderUnlockFiles();
        return;
    }
    unlockFileNames[index] = newBaseName;
}

function previewUnlockImage(index) {
    const file = unlockFiles[index];
    if (!file || !file.type.startsWith('image/')) return;
    const url = URL.createObjectURL(file);

    // 取显示名
    const ext = file.name.includes('.') ? file.name.substring(file.name.lastIndexOf('.')) : '';
    const baseName = file.name.includes('.') ? file.name.substring(0, file.name.lastIndexOf('.')) : file.name;
    const displayName = (unlockFileNames[index] !== undefined ? unlockFileNames[index] : baseName) + ext;

    // 建立或复用 lightbox
    let lb = document.getElementById('uf-lightbox');
    if (!lb) {
        lb = document.createElement('div');
        lb.id = 'uf-lightbox';
        lb.className = 'uf-lightbox-overlay';
        lb.innerHTML = `
            <div class="uf-lightbox-inner">
                <div class="uf-lightbox-topbar">
                    <span class="uf-lightbox-title"></span>
                    <button class="uf-lightbox-close" title="关闭">&times;</button>
                </div>
                <div class="uf-lightbox-body">
                    <img class="uf-lightbox-img" src="" alt="">
                </div>
            </div>
        `;
        document.body.appendChild(lb);
        lb.querySelector('.uf-lightbox-close').onclick = closeUnlockImagePreview;
        lb.onclick = function(e) { if (e.target === lb) closeUnlockImagePreview(); };
    }
    lb.querySelector('.uf-lightbox-img').src = url;
    lb.querySelector('.uf-lightbox-title').textContent = displayName;
    lb.classList.add('show');
    // 按 Esc 关闭
    lb._escHandler = function(e) { if (e.key === 'Escape') closeUnlockImagePreview(); };
    document.addEventListener('keydown', lb._escHandler);
}

function closeUnlockImagePreview() {
    const lb = document.getElementById('uf-lightbox');
    if (!lb) return;
    lb.classList.remove('show');
    const img = lb.querySelector('.uf-lightbox-img');
    if (img && img.src) { try { URL.revokeObjectURL(img.src); } catch(e) {} img.src = ''; }
    if (lb._escHandler) { document.removeEventListener('keydown', lb._escHandler); lb._escHandler = null; }
}

function removeUnlockFile(index) {
    unlockFiles.splice(index, 1);
    // 重新映射自定义名称（index 变了）
    const newNames = {};
    Object.keys(unlockFileNames).forEach(k => {
        const ki = parseInt(k);
        if (ki < index) newNames[ki] = unlockFileNames[ki];
        else if (ki > index) newNames[ki - 1] = unlockFileNames[ki];
    });
    unlockFileNames = newNames;
    renderUnlockFiles();
}

function clearUnlockFiles() {
    unlockFiles = [];
    unlockFileNames = {};
    renderUnlockFiles();
    const fileInput = document.getElementById('unlock-file-input');
    if (fileInput) fileInput.value = '';
}


async function unlockOrder() {
    const orderNumber = document.getElementById('unlock-order-number').value;
    const customerNameInput = document.getElementById('unlock-customer-name');
    const customerName = normalizeCustomerName(customerNameInput ? customerNameInput.value : '');
    if (customerNameInput) customerNameInput.value = customerName;
    const orderDate = document.getElementById('unlock-order-date').value;
    const notes = document.getElementById('unlock-notes').value;
    
    if (!customerName) {
        showToast('请输入客户名称', 'error');
        return;
    }
    
    try {
        // 創建 FormData 以支持文件上傳
        const formData = new FormData();
        formData.append('order_number', orderNumber);
        formData.append('customer_name', customerName);
        formData.append('order_date', orderDate);
        formData.append('notes', notes);
        
        // 添加文件（使用自定义文件名）
        unlockFiles.forEach((file, index) => {
            const ext = file.name.includes('.') ? file.name.substring(file.name.lastIndexOf('.')) : '';
            const baseName = file.name.includes('.') ? file.name.substring(0, file.name.lastIndexOf('.')) : file.name;
            const customBase = unlockFileNames[index] !== undefined ? unlockFileNames[index] : baseName;
            const finalName = customBase + ext;
            // 用 new File 重建，带上新文件名
            const renamedFile = new File([file], finalName, { type: file.type });
            formData.append('files', renamedFile);
        });
        
        const response = await fetch('/tracking/api/orders/unlock', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('订单已成功解锁！', 'success');
            closeAdminModal('unlockModal');
            
            // 清空文件列表
            unlockFiles = [];
            clearUnlockFiles();
            
            // 刷新当前TAB的数据，不跳转到其他页面
            const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
            if (activeTab === 'all-orders') {
                // 如果在"订单号管理"TAB，刷新该TAB
                loadAllOrders(allOrdersPage || 1);
            } else if (activeTab === 'unlocked') {
                // 如果在"未解锁订单"TAB，刷新该TAB（解锁后该订单会从列表中消失）
                loadAdminUnlockedOrders(unlockedPage || 1);
            } else if (activeTab === 'locked') {
                // 如果在"已解锁订单"TAB，刷新该TAB
                loadLockedOrders(lockedPage || 1);
            } else {
                // 默认刷新"订单号管理"TAB
                loadAllOrders(1);
            }
        } else {
            showToast(data.error, 'error');
        }
    } catch (error) {
        console.error('解锁失败:', error);
        showToast('解锁失败', 'error');
    }
}

// ==================== 全部訂單 ====================
let allOrdersPage = 1;
let allOrdersPageSize = parseInt(localStorage.getItem('allOrdersPageSize') || '50', 10);
let allOrdersSearchDebounce = null;
const storedAllOrdersSortKey = localStorage.getItem('allOrdersSortKey');
const storedAllOrdersSortDir = localStorage.getItem('allOrdersSortDir');
let allOrdersSortKey = storedAllOrdersSortKey || 'order_number';
let allOrdersSortDir = storedAllOrdersSortDir || 'desc';
const allOrdersSortMigrated = localStorage.getItem('allOrdersSortMigrated') === '1';
if (!allOrdersSortMigrated && allOrdersSortKey === 'order_number' && allOrdersSortDir === 'asc') {
    allOrdersSortDir = 'desc';
    localStorage.setItem('allOrdersSortDir', 'desc');
    localStorage.setItem('allOrdersSortMigrated', '1');
}

async function loadAllOrders(page = 1) {
    allOrdersPage = page;
    const statusFilter = document.getElementById('status-filter-all')?.value || '';
    const search = document.getElementById('search-input-all')?.value || '';
    const noProjectsOnly = document.getElementById('filter-no-projects')?.value === '1';
    const prefixFilter = document.getElementById('prefix-filter-all')?.value || 'all';
    const statusParam = noProjectsOnly ? 'ACTIVE' : (statusFilter || 'all');
    updateAllOrdersSortIndicators();
    
    try {
        // 同時載入統計數據和訂單列表
        const [statsResponse, ordersResponse] = await Promise.all([
            fetch(`/tracking/api/orders/stats?prefix=${encodeURIComponent(prefixFilter)}`),
            fetch(`/tracking/api/order-number-pool?page=${page}&page_size=${allOrdersPageSize}&status=${statusParam}&search=${encodeURIComponent(search)}&sort_by=${encodeURIComponent(allOrdersSortKey)}&sort_order=${encodeURIComponent(allOrdersSortDir)}&include_counts=1&prefix=${encodeURIComponent(prefixFilter)}${noProjectsOnly ? '&project_count=0' : ''}`)
        ]);
        
        const statsData = await statsResponse.json();
        const ordersData = await ordersResponse.json();
        
        if (statsData.success) {
            updateOrderStats(statsData.data);
        }
        
        if (ordersData.success) {
            renderAllOrders(ordersData.data.numbers || []);
            if (ordersData.data.pagination) {
                renderAllOrdersPagination(ordersData.data.pagination);
                updateCurrentListTotal(ordersData.data.pagination.total || 0);
            } else {
                updateCurrentListTotal((ordersData.data.numbers || []).length);
            }
            if (ordersData.data?.truncated) {
                const hasSearch = Boolean(search && search.trim());
                setAllOrdersTruncatedHint(hasSearch ? '结果过多，请缩小搜索范围' : '数据过多，请使用搜索缩小范围');
            } else {
                setAllOrdersTruncatedHint('');
            }
            updateBatchDeleteButton('all-orders');
        } else {
            setAllOrdersTruncatedHint('');
        }
    } catch (error) {
        console.error('載入訂單號失敗:', error);
        setAllOrdersTruncatedHint('');
        showToast('載入失敗', 'error');
    }
}

function setupAllOrdersSorting() {
    const headers = document.querySelectorAll('#tab-all-orders .admin-orders-table thead th.sortable');
    if (!headers.length) return;
    const descFirstKeys = new Set(['order_number', 'order_date', 'created_at', 'project_count']);
    headers.forEach(header => {
        header.addEventListener('click', () => {
            const key = header.dataset.sort;
            if (!key) return;
            if (allOrdersSortKey === key) {
                allOrdersSortDir = allOrdersSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                allOrdersSortKey = key;
                allOrdersSortDir = descFirstKeys.has(key) ? 'desc' : 'asc';
            }
            localStorage.setItem('allOrdersSortKey', allOrdersSortKey);
            localStorage.setItem('allOrdersSortDir', allOrdersSortDir);
            updateAllOrdersSortIndicators();
            loadAllOrders(1);
        });
    });
    updateAllOrdersSortIndicators();
}

function updateAllOrdersSortIndicators() {
    const headers = document.querySelectorAll('#tab-all-orders .admin-orders-table thead th.sortable');
    headers.forEach(header => {
        const indicator = header.querySelector('.sort-indicator');
        if (!indicator) return;
        if (header.dataset.sort === allOrdersSortKey) {
            indicator.textContent = allOrdersSortDir === 'asc' ? '▲' : '▼';
        } else {
            indicator.textContent = '';
        }
    });
}

function searchAllOrders() {
    if (allOrdersSearchDebounce) clearTimeout(allOrdersSearchDebounce);
    allOrdersSearchDebounce = setTimeout(() => {
        loadAllOrders(1);
    }, 300);
}

function updateOrderStats(stats) {
    document.getElementById('stat-unlocked').textContent = stats.unlocked || 0;
    document.getElementById('stat-active').textContent = stats.active || 0;
    document.getElementById('stat-skipped').textContent = stats.skipped || 0;
    document.getElementById('stat-total').textContent = stats.total || 0;
}

function updateCurrentListTotal(total) {
    const totalEl = document.getElementById('stat-total');
    if (totalEl) {
        totalEl.textContent = Number.isFinite(total) ? total : 0;
    }
}

function setAllOrdersTruncatedHint(message) {
    const hintEl = document.getElementById('all-orders-truncated-hint');
    if (!hintEl) return;
    if (message) {
        hintEl.textContent = message;
        hintEl.style.display = 'block';
    } else {
        hintEl.style.display = 'none';
        hintEl.textContent = '';
    }
}

function buildCompactPagination(page, totalPages, onClickFnName) {
    if (totalPages <= 0) return '';
    const pages = [];
    const push = (v) => {
        if (pages[pages.length - 1] !== v) pages.push(v);
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

    return pages.map((p) => {
        if (p === '...') return '<span class="pagination-ellipsis">...</span>';
        return `<button class="${p === page ? 'active' : ''}" onclick="${onClickFnName}(${p})">${p}</button>`;
    }).join('');
}

function renderAllOrders(orders) {
    const tbody = document.getElementById('all-orders-table-body');
    
    if (orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center">暫無訂單號</td></tr>';
        return;
    }
    
    tbody.innerHTML = orders.map(order => {
        const status = order.status || 'UNLOCKED';
        const isLocked = Boolean(order.is_locked);
        // 状态标签：已锁定的 ACTIVE 订单显示为"已完成"
        let statusLabel, statusClass;
        if (status === 'ACTIVE' && isLocked) {
            statusLabel = '已完成';
            statusClass = 'status-completed';
        } else if (status === 'UNLOCKED') {
            statusLabel = '未解锁';
            statusClass = 'status-reserved';
        } else if (status === 'ACTIVE') {
            statusLabel = '已启用';
            statusClass = 'status-available';
        } else if (status === 'CANCELLED') {
            statusLabel = '已取消';
            statusClass = 'status-cancelled';
        } else if (status === 'SKIPPED') {
            statusLabel = '跳号';
            statusClass = 'status-skip';
        } else {
            statusLabel = status;
            statusClass = '';
        }
        
        // 可见性显示
        const visibility = order.visibility || 'admin_only';
        const visibilityLabel = visibility === 'admin_only' ? '仅管理员' : '所有业务员';
        const visibilityClass = visibility === 'admin_only' ? 'status-reserved' : 'status-available';
        
        // 备注显示（可编辑）
        const notes = order.notes || '';
        const notesEscaped = escapeHtml(notes);
        const notesDisplay = notes.length > 30 ? notes.substring(0, 30) + '...' : notes;
        const notesDisplayEscaped = escapeHtml(notesDisplay);
        
        const projectCount = typeof order.project_count === 'number' ? order.project_count : 0;
        return `
        <tr class="order-row${isLocked ? ' order-locked' : ''}" 
            style="cursor: pointer;" 
            onclick="openWorkspaceDrawerFromOrder('${order.order_number}')">
            <td onclick="event.stopPropagation();"><input type="checkbox" class="order-checkbox" value="${order.order_number}" onchange="updateBatchDeleteButton('all-orders'); event.stopPropagation();"></td>
            <td>${order.order_date || '-'}</td>
            <td><strong>${order.order_number}</strong></td>
            <td class="order-customer" data-order-number="${order.order_number}" onclick="event.stopPropagation();">
                <div class="notes-container">
                    <button class="notes-edit-btn"
                            onclick="toggleAdminCustomerEdit('${order.order_number}', this); event.stopPropagation();"
                            title="编辑客户名称">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                    </button>
                    <div class="customer-display">
                        ${order.customer_name ?
                            `<span class="customer-preview" title="${escapeHtml(order.customer_name)}">${escapeHtml(order.customer_name)}</span>` :
                            '<span class="notes-empty">-</span>'}
                    </div>
                    <div class="customer-edit" style="display: none;">
                        <input class="customer-input" type="text" placeholder="输入客户名称..." value="${escapeHtml(order.customer_name || '')}" onclick="event.stopPropagation();">
                        <div class="notes-edit-actions">
                            <button class="notes-save-btn" onclick="saveAdminCustomerName('${order.order_number}', this); event.stopPropagation();">保存</button>
                            <button class="notes-cancel-btn" onclick="cancelAdminCustomerEdit('${order.order_number}', this); event.stopPropagation();">取消</button>
                        </div>
                    </div>
                </div>
            </td>
            <td><span class="status-badge ${statusClass}">${statusLabel}</span></td>
            <td><span class="status-badge ${visibilityClass}">${visibilityLabel}</span></td>
            <td class="text-muted">${projectCount}</td>
            <td class="order-notes" data-order-number="${order.order_number}" onclick="event.stopPropagation();">
                <div class="notes-container">
                    <button class="notes-edit-btn" 
                            onclick="toggleAdminNotesEdit('${order.order_number}', this); event.stopPropagation();"
                            title="編輯備註">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                    </button>
                    <div class="notes-display">
                        ${notes ? 
                            `<span class="notes-preview" title="${notesEscaped}">${notesDisplayEscaped}${notes.length > 30 ? '...' : ''}</span>` : 
                            '<span class="notes-empty">-</span>'}
                    </div>
                    <div class="notes-edit" style="display: none;">
                        <textarea class="notes-input" rows="2" placeholder="輸入備註..." onclick="event.stopPropagation();">${notesEscaped}</textarea>
                        <div class="notes-edit-actions">
                            <button class="notes-save-btn" onclick="saveAdminNotes('${order.order_number}', this); event.stopPropagation();">保存</button>
                            <button class="notes-cancel-btn" onclick="cancelAdminNotesEdit('${order.order_number}', this); event.stopPropagation();">取消</button>
                        </div>
                    </div>
                </div>
            </td>
            <td onclick="event.stopPropagation();">
                <div class="action-buttons">
                    ${(status === 'ACTIVE' && !isLocked) ?
                        `<button class="btn btn-primary btn-sm hover-btn" onclick="openNewWorkflowModalWithOrder('${order.order_number}'); event.stopPropagation();" title="快速建立业务流程">建立</button>` :
                        ''}
                    ${status === 'ACTIVE' ?
                        (isLocked
                            ? `<button class="btn btn-warning btn-sm hover-btn" onclick="unlockCompletedOrder('${order.order_number}'); event.stopPropagation();" title="解除锁定">解除锁定</button>`
                            : `<button class="btn btn-success btn-sm hover-btn" onclick="lockCompletedOrder('${order.order_number}'); event.stopPropagation();" title="标记完成">标记完成</button>`) :
                        ''}
                    ${status === 'UNLOCKED' ? 
                        `<button class="btn btn-success btn-sm hover-btn" onclick="openUnlockModal('${order.order_number}'); event.stopPropagation();" title="解锁订单">解锁</button>` : 
                        status === 'SKIPPED' ?
                            `<button class="btn btn-warning btn-sm hover-btn" onclick="removeSkip('${order.order_number}'); event.stopPropagation();" title="解除跳号">解除跳号</button>` :
                            ''}
                    <button class="btn btn-danger btn-sm hover-btn" onclick="confirmDeleteOrder('${order.order_number}', '${(order.customer_name || '').replace(/'/g, "\\'")}', '${statusLabel}'); event.stopPropagation();" title="删除订单">删除</button>
                    ${status === 'ACTIVE' ?
                        `<button class="btn btn-info btn-sm hover-btn" onclick="toggleVisibility('${order.order_number}', '${visibility}'); event.stopPropagation();" title="${visibility === 'admin_only' ? '設為所有業務員可見' : '設為僅管理員可見'}">
                            ${visibility === 'admin_only' ? '顯示' : '隱藏'}
                        </button>` :
                        ''}
                    ${(status === 'ACTIVE' || status === 'CANCELLED') ?
                        `<button class="btn ${status === 'CANCELLED' ? 'btn-warning' : 'btn-danger'} btn-sm hover-btn" onclick="toggleCancelOrder('${order.order_number}', '${status}'); event.stopPropagation();" title="${status === 'CANCELLED' ? '恢復訂單' : '標記取消'}">
                            ${status === 'CANCELLED' ? '解除取消' : '取消'}
                        </button>` :
                        ''}
                </div>
            </td>
        </tr>
    `;
    }).join('');
}

function renderAllOrdersPagination(pagination) {
    const container = document.getElementById('all-orders-pagination');
    if (!container) return;
    
    const { page, total_pages, total = 0, page_size = 50 } = pagination;
    const start = total > 0 ? ((page - 1) * page_size + 1) : 0;
    const end = total > 0 ? Math.min(page * page_size, total) : 0;
    let html = '';
    html += `<span class="pagination-summary">显示 ${start} - ${end}，共 ${total} 条（第 ${page} / ${total_pages} 页）</span>`;
    
    html += `<button ${page === 1 ? 'disabled' : ''} onclick="loadAllOrders(${page - 1})">上一頁</button>`;
    
    html += buildCompactPagination(page, total_pages, 'loadAllOrders');
    
    html += `<button ${page === total_pages ? 'disabled' : ''} onclick="loadAllOrders(${page + 1})">下一頁</button>`;
    
    container.innerHTML = html;
}

function setAllOrdersPageSize(size) {
    allOrdersPageSize = parseInt(size, 10);
    localStorage.setItem('allOrdersPageSize', allOrdersPageSize);
    loadAllOrders(1);
}


function handleAllOrdersSearch() {
    if (allOrdersSearchDebounce) clearTimeout(allOrdersSearchDebounce);
    allOrdersSearchDebounce = setTimeout(() => {
        loadAllOrders(1);
    }, 300);
}

function toggleSelectAllOrders() {
    const checkbox = document.getElementById('select-all-orders');
    const checkboxes = document.querySelectorAll('#all-orders-table-body .order-checkbox');
    checkboxes.forEach(cb => cb.checked = checkbox.checked);
    updateBatchDeleteButton('all-orders');
}

// ==================== 切換可見性 ====================
async function toggleVisibility(orderNumber, currentVisibility) {
    const newVisibility = currentVisibility === 'admin_only' ? 'all_sales' : 'admin_only';
    const actionText = newVisibility === 'admin_only' ? '隱藏' : '顯示給業務員';
    
    const confirmed = await showConfirmModal(
        `確定要${actionText}訂單 ${orderNumber} 嗎？`,
        '確認修改可見性',
        '確認',
        '取消',
        true
    );
    
    if (!confirmed) {
        return;
    }
    
    try {
        const response = await fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}/visibility`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ visibility: newVisibility })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`訂單 ${orderNumber} 已${actionText}`, 'success');
            // 刷新当前TAB的数据
            const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
            if (activeTab === 'all-orders') {
                loadAllOrders(allOrdersPage || 1);
            } else if (activeTab === 'unlocked') {
                loadAdminUnlockedOrders(unlockedPage || 1);
            } else if (activeTab === 'locked') {
                loadLockedOrders(lockedPage || 1);
            } else {
                loadAllOrders(1);
            }
        } else {
            showToast(data.error || '修改失敗', 'error');
        }
    } catch (error) {
        console.error('切換可見性失敗:', error);
        showToast('網絡錯誤，請稍後重試', 'error');
    }
}


// ==================== 訂單取消 / 取消已取消 ====================
async function toggleCancelOrder(orderNumber, currentStatus) {
    const isCancelled = currentStatus === 'CANCELLED';
    const actionText = isCancelled ? '取消已取消（恢復訂單）' : '標記為已取消';
    const confirmMsg = isCancelled
        ? `確定要恢復訂單 ${orderNumber} 為正常狀態嗎？`
        : `確定要將訂單 ${orderNumber} 標記為已取消嗎？\n\n取消後主頁將不再顯示此訂單，業務員也看不到。`;

    const confirmed = await showConfirmModal(
        confirmMsg,
        actionText,
        '確認',
        '取消',
        true
    );
    if (!confirmed) return;

    try {
        const response = await fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}/cancel`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();
        if (data.success) {
            showToast(data.message, 'success');
            const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
            if (activeTab === 'all-orders') {
                loadAllOrders(allOrdersPage || 1);
            } else if (activeTab === 'unlocked') {
                loadAdminUnlockedOrders(unlockedPage || 1);
            } else if (activeTab === 'locked') {
                loadLockedOrders(lockedPage || 1);
            } else {
                loadAllOrders(1);
            }
        } else {
            showToast(data.error || '操作失敗', 'error');
        }
    } catch (error) {
        console.error('toggleCancelOrder error:', error);
        showToast('網絡錯誤，請稍後重試', 'error');
    }
}

// ==================== 订单锁定 / 解锁（完成标记） ====================
async function lockCompletedOrder(orderNumber) {
    const confirmed = await showConfirmModal(
        `确定要标记订单 ${orderNumber} 为已完成并锁定吗？\n锁定后业务员将无法继续编辑。`,
        '确认标记完成',
        '确认',
        '取消',
        true
    );
    if (!confirmed) return;

    try {
        const response = await fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}/lock`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();
        if (data.success) {
            showToast('订单已标记完成并锁定', 'success');
            const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
            if (activeTab === 'all-orders') {
                loadAllOrders(allOrdersPage || 1);
            } else if (activeTab === 'unlocked') {
                loadAdminUnlockedOrders(unlockedPage || 1);
            } else if (activeTab === 'locked') {
                loadLockedOrders(lockedPage || 1);
            } else {
                loadAllOrders(1);
            }
        } else {
            showToast(data.error || '操作失败', 'error');
        }
    } catch (error) {
        console.error('锁定订单失败:', error);
        showToast('操作失败', 'error');
    }
}

async function unlockCompletedOrder(orderNumber) {
    const confirmed = await showConfirmModal(
        `确定要解除订单 ${orderNumber} 的锁定吗？\n解除后业务员可以继续编辑。`,
        '确认解除锁定',
        '确认',
        '取消',
        true
    );
    if (!confirmed) return;

    try {
        const response = await fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}/unlock`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();
        if (data.success) {
            showToast('订单锁定已解除', 'success');
            const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
            if (activeTab === 'all-orders') {
                loadAllOrders(allOrdersPage || 1);
            } else if (activeTab === 'unlocked') {
                loadAdminUnlockedOrders(unlockedPage || 1);
            } else if (activeTab === 'locked') {
                loadLockedOrders(lockedPage || 1);
            } else {
                loadAllOrders(1);
            }
        } else {
            showToast(data.error || '操作失败', 'error');
        }
    } catch (error) {
        console.error('解除锁定失败:', error);
        showToast('操作失败', 'error');
    }
}

// ==================== 未解鎖訂單 ====================
let unlockedPage = 1;
let unlockedPageSize = parseInt(localStorage.getItem('unlockedPageSize') || '50', 10);
let unlockedSearchDebounce = null;
let unlockedSortKey = localStorage.getItem('unlockedOrdersSortKey') || 'order_number';
let unlockedSortDir = localStorage.getItem('unlockedOrdersSortDir') || 'desc';

async function loadAdminUnlockedOrders(page = 1) {
    unlockedPage = page;
    const search = document.getElementById('unlocked-search')?.value || '';
    const prefixFilter = document.getElementById('unlocked-prefix-filter')?.value || 'all';
    updateUnlockedSortIndicators();
    
    try {
        // 调用订单号池API，筛选未解锁的订单（status = UNLOCKED）
        const url = `/tracking/api/order-number-pool?page=${page}&page_size=${unlockedPageSize}&status=UNLOCKED&search=${encodeURIComponent(search)}&sort_by=${encodeURIComponent(unlockedSortKey)}&sort_order=${encodeURIComponent(unlockedSortDir)}&prefix=${encodeURIComponent(prefixFilter)}`;
        console.log('[loadAdminUnlockedOrders] 调用API:', url);
        const response = await fetch(url);
        const result = await response.json();
        console.log('[loadAdminUnlockedOrders] API返回结果:', result);
        
        if (result.success) {
            // API返回的数据结构是 { data: { numbers: [...], pagination: {...} } }
            const orders = result.data?.numbers || result.data || [];
            console.log('[loadAdminUnlockedOrders] 解析到的订单数量:', orders.length);
            renderUnlockedOrders(orders);
            if (result.data?.pagination) {
                renderUnlockedPagination(result.data.pagination);
                updateCurrentListTotal(result.data.pagination.total || 0);
            } else {
                updateCurrentListTotal(orders.length);
            }
            updateBatchDeleteButton('unlocked');
        } else {
            console.error('[loadAdminUnlockedOrders] API返回错误:', result.error);
            showToast(result.error || '載入失敗', 'error');
        }
    } catch (error) {
        console.error('[loadAdminUnlockedOrders] 載入未解鎖訂單失敗:', error);
        showToast('載入失敗', 'error');
    }
}

function setupUnlockedSorting() {
    const headers = document.querySelectorAll('#tab-unlocked .admin-orders-table thead th.sortable');
    if (!headers.length) return;
    headers.forEach(header => {
        header.addEventListener('click', () => {
            const key = header.dataset.sort;
            if (!key) return;
            if (unlockedSortKey === key) {
                unlockedSortDir = unlockedSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                unlockedSortKey = key;
                unlockedSortDir = 'asc';
            }
            localStorage.setItem('unlockedOrdersSortKey', unlockedSortKey);
            localStorage.setItem('unlockedOrdersSortDir', unlockedSortDir);
            updateUnlockedSortIndicators();
            loadAdminUnlockedOrders(1);
        });
    });
    updateUnlockedSortIndicators();
}

function updateUnlockedSortIndicators() {
    const headers = document.querySelectorAll('#tab-unlocked .admin-orders-table thead th.sortable');
    headers.forEach(header => {
        const indicator = header.querySelector('.sort-indicator');
        if (!indicator) return;
        if (header.dataset.sort === unlockedSortKey) {
            indicator.textContent = unlockedSortDir === 'asc' ? '▲' : '▼';
        } else {
            indicator.textContent = '';
        }
    });
}

// 为了向后兼容，保留 loadUnlockedOrders 作为别名
const loadUnlockedOrders = loadAdminUnlockedOrders;

function renderUnlockedOrders(orders) {
    const tbody = document.getElementById('unlocked-table-body');
    
    if (orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center">暫無未解鎖訂單</td></tr>';
        return;
    }
    
    // 未解锁订单的状态标签
    const statusLabel = '未解鎖';
    
    tbody.innerHTML = orders.map(order => {
        return `
        <tr class="order-row" 
            style="cursor: pointer;" 
            onclick="openWorkspaceDrawerFromOrder('${order.order_number}')">
            <td onclick="event.stopPropagation();"><input type="checkbox" class="unlocked-checkbox" value="${order.order_number}" onchange="updateBatchDeleteButton('unlocked'); event.stopPropagation();"></td>
            <td><strong>${order.order_number}</strong></td>
            <td>${formatDate(order.created_at)}</td>
            <td onclick="event.stopPropagation();">
                <div class="action-buttons">
                    <button class="btn btn-success btn-sm hover-btn" onclick="openUnlockModal('${order.order_number}'); event.stopPropagation();" title="解鎖訂單">解鎖</button>
                    <button class="btn btn-danger btn-sm hover-btn" onclick="confirmDeleteOrder('${order.order_number}', '${(order.customer_name || '').replace(/'/g, "\\'")}', '${statusLabel}'); event.stopPropagation();" title="刪除訂單">刪除</button>
                </div>
            </td>
        </tr>
    `;
    }).join('');
}

function renderUnlockedPagination(pagination) {
    const container = document.getElementById('unlocked-pagination');
    if (!container) return;
    
    const { page, total_pages, total = 0, page_size = 50 } = pagination;
    const start = total > 0 ? ((page - 1) * page_size + 1) : 0;
    const end = total > 0 ? Math.min(page * page_size, total) : 0;
    let html = '';
    html += `<span class="pagination-summary">显示 ${start} - ${end}，共 ${total} 条（第 ${page} / ${total_pages} 页）</span>`;
    
    html += `<button ${page === 1 ? 'disabled' : ''} onclick="loadAdminUnlockedOrders(${page - 1})">上一頁</button>`;
    
    html += buildCompactPagination(page, total_pages, 'loadAdminUnlockedOrders');
    
    html += `<button ${page === total_pages ? 'disabled' : ''} onclick="loadAdminUnlockedOrders(${page + 1})">下一頁</button>`;
    
    container.innerHTML = html;
}

function setUnlockedPageSize(size) {
    unlockedPageSize = parseInt(size, 10);
    localStorage.setItem('unlockedPageSize', unlockedPageSize);
    loadAdminUnlockedOrders(1);
}

function handleUnlockedSearch() {
    if (unlockedSearchDebounce) clearTimeout(unlockedSearchDebounce);
    unlockedSearchDebounce = setTimeout(() => {
        loadAdminUnlockedOrders(1);
    }, 300);
}

function toggleSelectAllUnlocked() {
    const checkbox = document.getElementById('select-all-unlocked');
    const checkboxes = document.querySelectorAll('#unlocked-table-body .unlocked-checkbox');
    checkboxes.forEach(cb => cb.checked = checkbox.checked);
    updateBatchDeleteButton('unlocked');
}

// ==================== 已解鎖訂單 ====================
let lockedPage = 1;
let lockedPageSize = parseInt(localStorage.getItem('lockedPageSize') || '50', 10);
let lockedSearchDebounce = null;
let lockedSortKey = localStorage.getItem('lockedOrdersSortKey') || 'order_number';
let lockedSortDir = localStorage.getItem('lockedOrdersSortDir') || 'desc';

async function loadLockedOrders(page = 1) {
    lockedPage = page;
    const search = document.getElementById('locked-search')?.value || '';
    const statusFilter = document.getElementById('locked-status-filter')?.value || 'ACTIVE';
    const noProjectsOnly = document.getElementById('locked-project-filter')?.value === '1';
    const prefixFilter = document.getElementById('locked-prefix-filter')?.value || 'all';
    updateLockedSortIndicators();
    
    try {
        // 调用订单号池API，筛选已解锁的订单（status = ACTIVE）
        const url = `/tracking/api/order-number-pool?page=${page}&page_size=${lockedPageSize}&status=${encodeURIComponent(statusFilter || 'ACTIVE')}&search=${encodeURIComponent(search)}&sort_by=${encodeURIComponent(lockedSortKey)}&sort_order=${encodeURIComponent(lockedSortDir)}&include_counts=1&prefix=${encodeURIComponent(prefixFilter)}${noProjectsOnly ? '&project_count=0' : ''}`;
        const response = await fetch(url);
        const result = await response.json();
        
        if (result.success) {
            // API返回的数据结构是 { data: { numbers: [...], pagination: {...} } }
            const orders = result.data?.numbers || result.data || [];
            renderLockedOrders(orders);
            if (result.data?.pagination) {
                renderLockedPagination(result.data.pagination);
                updateCurrentListTotal(result.data.pagination.total || 0);
            } else {
                updateCurrentListTotal(orders.length);
            }
            updateBatchDeleteButton('locked');
        } else {
            showToast(result.error || '載入失敗', 'error');
        }
    } catch (error) {
        console.error('載入已解鎖訂單失敗:', error);
        showToast('載入失敗', 'error');
    }
}

function setupLockedSorting() {
    const headers = document.querySelectorAll('#tab-locked .admin-orders-table thead th.sortable');
    if (!headers.length) return;
    headers.forEach(header => {
        header.addEventListener('click', () => {
            const key = header.dataset.sort;
            if (!key) return;
            if (lockedSortKey === key) {
                lockedSortDir = lockedSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                lockedSortKey = key;
                lockedSortDir = 'asc';
            }
            localStorage.setItem('lockedOrdersSortKey', lockedSortKey);
            localStorage.setItem('lockedOrdersSortDir', lockedSortDir);
            updateLockedSortIndicators();
            loadLockedOrders(1);
        });
    });
    updateLockedSortIndicators();
}

function updateLockedSortIndicators() {
    const headers = document.querySelectorAll('#tab-locked .admin-orders-table thead th.sortable');
    headers.forEach(header => {
        const indicator = header.querySelector('.sort-indicator');
        if (!indicator) return;
        if (header.dataset.sort === lockedSortKey) {
            indicator.textContent = lockedSortDir === 'asc' ? '▲' : '▼';
        } else {
            indicator.textContent = '';
        }
    });
}

function renderLockedOrders(orders) {
    const tbody = document.getElementById('locked-table-body');
    
    if (orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center">暫無已解鎖訂單</td></tr>';
        return;
    }

    tbody.innerHTML = orders.map(order => {
        const status = order.status || 'ACTIVE';
        const isLocked = Boolean(order.is_locked);
        // 状态标签：已锁定的 ACTIVE 订单显示为"已完成"
        let statusLabel, statusClass;
        if (status === 'ACTIVE' && isLocked) {
            statusLabel = '已完成';
            statusClass = 'status-completed';
        } else if (status === 'UNLOCKED') {
            statusLabel = '未解锁';
            statusClass = 'status-reserved';
        } else if (status === 'ACTIVE') {
            statusLabel = '已启用';
            statusClass = 'status-available';
        } else if (status === 'CANCELLED') {
            statusLabel = '已取消';
            statusClass = 'status-cancelled';
        } else if (status === 'SKIPPED') {
            statusLabel = '跳号';
            statusClass = 'status-skip';
        } else {
            statusLabel = status;
            statusClass = '';
        }
        // 可见性显示
        const visibility = order.visibility || 'admin_only';
        const visibilityLabel = visibility === 'admin_only' ? '仅管理员' : '所有业务员';
        const visibilityClass = visibility === 'admin_only' ? 'status-reserved' : 'status-available';
        
        // 备注显示（可编辑）
        const notes = order.notes || '';
        const notesEscaped = escapeHtml(notes);
        const notesDisplay = notes.length > 30 ? notes.substring(0, 30) + '...' : notes;
        const notesDisplayEscaped = escapeHtml(notesDisplay);
        
        const projectCount = typeof order.project_count === 'number' ? order.project_count : 0;
        return `
        <tr class="order-row${isLocked ? ' order-locked' : ''}" 
            style="cursor: pointer;" 
            onclick="openWorkspaceDrawerFromOrder('${order.order_number}')">
            <td onclick="event.stopPropagation();"><input type="checkbox" class="locked-checkbox" value="${order.order_number}" onchange="updateBatchDeleteButton('locked'); event.stopPropagation();"></td>
            <td>${order.order_date || '-'}</td>
            <td><strong>${order.order_number}</strong></td>
            <td class="order-customer" data-order-number="${order.order_number}" onclick="event.stopPropagation();">
                <div class="notes-container">
                    <button class="notes-edit-btn"
                            onclick="toggleAdminCustomerEdit('${order.order_number}', this); event.stopPropagation();"
                            title="编辑客户名称">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                    </button>
                    <div class="customer-display">
                        ${order.customer_name ?
                            `<span class="customer-preview" title="${escapeHtml(order.customer_name)}">${escapeHtml(order.customer_name)}</span>` :
                            '<span class="notes-empty">-</span>'}
                    </div>
                    <div class="customer-edit" style="display: none;">
                        <input class="customer-input" type="text" placeholder="输入客户名称..." value="${escapeHtml(order.customer_name || '')}" onclick="event.stopPropagation();">
                        <div class="notes-edit-actions">
                            <button class="notes-save-btn" onclick="saveAdminCustomerName('${order.order_number}', this); event.stopPropagation();">保存</button>
                            <button class="notes-cancel-btn" onclick="cancelAdminCustomerEdit('${order.order_number}', this); event.stopPropagation();">取消</button>
                        </div>
                    </div>
                </div>
            </td>
            <td><span class="status-badge ${statusClass}">${statusLabel}</span></td>
            <td><span class="status-badge ${visibilityClass}">${visibilityLabel}</span></td>
            <td class="text-muted">${projectCount}</td>
            <td class="order-notes" data-order-number="${order.order_number}" onclick="event.stopPropagation();">
                <div class="notes-container">
                    <button class="notes-edit-btn" 
                            onclick="toggleAdminNotesEdit('${order.order_number}', this); event.stopPropagation();"
                            title="編輯備註">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                    </button>
                    <div class="notes-display">
                        ${notes ? 
                            `<span class="notes-preview" title="${notesEscaped}">${notesDisplayEscaped}${notes.length > 30 ? '...' : ''}</span>` : 
                            '<span class="notes-empty">-</span>'}
                    </div>
                    <div class="notes-edit" style="display: none;">
                        <textarea class="notes-input" rows="2" placeholder="輸入備註..." onclick="event.stopPropagation();">${notesEscaped}</textarea>
                        <div class="notes-edit-actions">
                            <button class="notes-save-btn" onclick="saveAdminNotes('${order.order_number}', this); event.stopPropagation();">保存</button>
                            <button class="notes-cancel-btn" onclick="cancelAdminNotesEdit('${order.order_number}', this); event.stopPropagation();">取消</button>
                        </div>
                    </div>
                </div>
            </td>
            <td onclick="event.stopPropagation();">
                <div class="action-buttons">
                    ${!isLocked ?
                        `<button class="btn btn-primary btn-sm hover-btn" onclick="openNewWorkflowModalWithOrder('${order.order_number}'); event.stopPropagation();" title="快速建立业务流程">建立</button>` :
                        ''}
                    ${isLocked
                        ? `<button class="btn btn-warning btn-sm hover-btn" onclick="unlockCompletedOrder('${order.order_number}'); event.stopPropagation();" title="解除锁定">解除锁定</button>`
                        : `<button class="btn btn-success btn-sm hover-btn" onclick="lockCompletedOrder('${order.order_number}'); event.stopPropagation();" title="标记完成">标记完成</button>`}
                    <button class="btn btn-danger btn-sm hover-btn" onclick="confirmDeleteOrder('${order.order_number}', '${(order.customer_name || '').replace(/'/g, "\\'")}', '${statusLabel}'); event.stopPropagation();" title="删除订单">删除</button>
                    <button class="btn btn-info btn-sm hover-btn" onclick="toggleVisibility('${order.order_number}', '${visibility}'); event.stopPropagation();" title="${visibility === 'admin_only' ? '设为所有业务员可见' : '设为仅管理员可见'}">
                        ${visibility === 'admin_only' ? '显示' : '隐藏'}
                    </button>
                    ${(status === 'ACTIVE' || status === 'CANCELLED') ?
                        `<button class="btn ${status === 'CANCELLED' ? 'btn-warning' : 'btn-danger'} btn-sm hover-btn" onclick="toggleCancelOrder('${order.order_number}', '${status}'); event.stopPropagation();" title="${status === 'CANCELLED' ? '恢復訂單' : '標記取消'}">
                            ${status === 'CANCELLED' ? '解除取消' : '取消'}
                        </button>` :
                        ''}
                </div>
            </td>
        </tr>
    `;
    }).join('');
}

function renderLockedPagination(pagination) {
    const container = document.getElementById('locked-pagination');
    if (!container) return;
    
    const { page, total_pages, total = 0, page_size = 50 } = pagination;
    const start = total > 0 ? ((page - 1) * page_size + 1) : 0;
    const end = total > 0 ? Math.min(page * page_size, total) : 0;
    let html = '';
    html += `<span class="pagination-summary">显示 ${start} - ${end}，共 ${total} 条（第 ${page} / ${total_pages} 页）</span>`;
    
    html += `<button ${page === 1 ? 'disabled' : ''} onclick="loadLockedOrders(${page - 1})">上一頁</button>`;
    
    html += buildCompactPagination(page, total_pages, 'loadLockedOrders');
    
    html += `<button ${page === total_pages ? 'disabled' : ''} onclick="loadLockedOrders(${page + 1})">下一頁</button>`;
    
    container.innerHTML = html;
}

function setLockedPageSize(size) {
    lockedPageSize = parseInt(size, 10);
    localStorage.setItem('lockedPageSize', lockedPageSize);
    loadLockedOrders(1);
}

function handleLockedSearch() {
    if (lockedSearchDebounce) clearTimeout(lockedSearchDebounce);
    lockedSearchDebounce = setTimeout(() => {
        loadLockedOrders(1);
    }, 300);
}

function toggleSelectAllLocked() {
    const checkbox = document.getElementById('select-all-locked');
    const checkboxes = document.querySelectorAll('#locked-table-body .locked-checkbox');
    checkboxes.forEach(cb => cb.checked = checkbox.checked);
    updateBatchDeleteButton('locked');
}

function updateBatchDeleteButton(type) {
    let checkboxes, btn;
    if (type === 'all-orders') {
        checkboxes = document.querySelectorAll('#all-orders-table-body .order-checkbox:checked');
        btn = document.getElementById('batch-delete-btn');
    } else if (type === 'unlocked') {
        checkboxes = document.querySelectorAll('#unlocked-table-body .unlocked-checkbox:checked');
        btn = document.getElementById('batch-delete-unlocked-btn');
    } else {
        checkboxes = document.querySelectorAll('#locked-table-body .locked-checkbox:checked');
        btn = document.getElementById('batch-delete-locked-btn');
    }
    
    if (btn) {
        btn.style.display = checkboxes.length > 0 ? 'inline-flex' : 'none';
    }
}

// ==================== 統計資訊 ====================
async function loadStats() {
    try {
        // 載入號碼池統計
        const poolResponse = await fetch('/tracking/api/order-number-pool?page=1&page_size=1');
        const poolData = await poolResponse.json();
        
        if (poolData.success) {
            const stats = poolData.data.stats;
            const total = Object.values(stats).reduce((a, b) => a + b, 0);
            document.getElementById('total-pool').textContent = total;
            document.getElementById('total-available').textContent = stats.available || 0;
        }
        
        // 載入訂單統計
        const ordersResponse = await fetch('/tracking/api/orders/overview');
        const ordersData = await ordersResponse.json();
        
        if (ordersData.success) {
            // 使用 status 字段：UNLOCKED = 未解锁，ACTIVE = 已解锁
            const orders = ordersData.data?.numbers || ordersData.data || [];
            const unlocked = orders.filter(o => o.status === 'ACTIVE').length;
            const locked = orders.filter(o => o.status === 'UNLOCKED').length;
            if (document.getElementById('total-unlocked')) {
                document.getElementById('total-unlocked').textContent = unlocked;
            }
            if (document.getElementById('total-locked')) {
                document.getElementById('total-locked').textContent = locked;
            }
        }
    } catch (error) {
        console.error('載入統計失敗:', error);
    }
}

// ==================== 缺號檢測 ====================
const MISSING_REMINDER_ACK_STORAGE_KEY = 'orderNumberMissingReminderAck';
let diffRangeOptionsCache = [];
let diffSelectedYearCode = '';

function getMissingReminderTodayKey() {
    const now = new Date();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${now.getFullYear()}-${month}-${day}`;
}

function hasTodayMissingReminderIgnore() {
    try {
        const ack = JSON.parse(localStorage.getItem(MISSING_REMINDER_ACK_STORAGE_KEY) || '{}');
        return ack.date === getMissingReminderTodayKey() && ack.acknowledged === true;
    } catch (e) {
        return false;
    }
}

function updateClearTodayIgnoreButton() {
    const btn = document.getElementById('diffModalClearTodayIgnore');
    if (!btn) return;
    const active = hasTodayMissingReminderIgnore();
    btn.disabled = !active;
    btn.textContent = active ? '取消今日忽略' : '今日未忽略';
    btn.style.opacity = active ? '1' : '0.55';
    btn.style.cursor = active ? 'pointer' : 'default';
}

function clearTodayMissingReminderIgnore() {
    localStorage.removeItem(MISSING_REMINDER_ACK_STORAGE_KEY);
    updateClearTodayIgnoreButton();
    if (typeof showToast === 'function') {
        showToast('已取消今日忽略；重新進入首頁會立即再次檢查缺號', 'success');
    }
}

async function openMissingCheckModal(options = {}) {
    const modal = document.getElementById('diffModal');
    const startInput = document.getElementById('diff-start-number');
    const endInput = document.getElementById('diff-end-number');
    const resultEl = document.getElementById('diff-result');
    if (!modal || !startInput || !endInput || !resultEl) return;

    startInput.value = '';
    endInput.value = '';
    resultEl.style.display = 'none';

    // 清除錯誤提示
    const errorHint = document.getElementById('diff-error-hint');
    if (errorHint) {
        errorHint.style.display = 'none';
        errorHint.textContent = '';
    }

    modal.classList.add('show');
    updateClearTodayIgnoreButton();
    await loadDiffRangeOptions();

    // 從首頁「缺號提醒 → 查看明細」進來時，直接使用提醒的範圍並自動檢測。
    if (options.startNumber) startInput.value = String(options.startNumber);
    if (options.endNumber) endInput.value = String(options.endNumber);

    const rangeHint = document.getElementById('diff-range-hint');
    if (rangeHint && (options.startNumber || options.endNumber)) {
        const startLabel = startInput.value || '-';
        const endLabel = endInput.value || '-';
        rangeHint.style.display = 'block';
        rangeHint.textContent = `提醒檢測範圍：${startLabel} ~ ${endLabel}`;
    }

    if (options.autoRun) {
        await performDiff();
    }
}

async function loadDiffRangeOptions() {
    const prefixGroup = document.getElementById('diff-prefix-group');
    const prefixSelect = document.getElementById('diff-prefix-select');
    const rangeHint = document.getElementById('diff-range-hint');
    const ruleHint = document.getElementById('diff-rule-hint');
    const manualRangeRow = document.getElementById('diff-manual-range-row');
    const yearTabsWrap = document.getElementById('diff-year-tabs-wrap');
    const yearTabs = document.getElementById('diff-year-tabs');
    const startInput = document.getElementById('diff-start-number');
    const endInput = document.getElementById('diff-end-number');

    const optionKey = (opt) => String(opt?.key ?? opt?.prefix ?? '');
    const optionLabel = (opt) => opt?.label || optionKey(opt);

    const clearResultForRangeChange = () => {
        const result = document.getElementById('diff-result');
        if (result) result.style.display = 'none';
        const errorHint = document.getElementById('diff-error-hint');
        if (errorHint) errorHint.style.display = 'none';
    };

    const setYearTabStyle = (button, active) => {
        button.style.cssText = [
            'border:1px solid ' + (active ? '#ff2d55' : '#d1d5db'),
            'background:' + (active ? '#fff1f4' : '#ffffff'),
            'color:' + (active ? '#e11d48' : '#374151'),
            'font-weight:' + (active ? '700' : '600'),
            'border-radius:8px',
            'padding:7px 16px',
            'cursor:pointer',
            'font-size:0.9rem'
        ].join(';');
    };

    const applyYearRange = (opt, yearCode) => {
        const key = optionKey(opt);
        const ranges = Array.isArray(opt?.ranges) ? opt.ranges : [];
        const range = ranges.find(item => String(item.year_code) === String(yearCode));
        diffSelectedYearCode = String(yearCode || '');

        if (startInput) {
            startInput.value = range?.start || `${key}${diffSelectedYearCode}001`;
            startInput.placeholder = `例如：${key}${diffSelectedYearCode}001`;
        }
        if (endInput) {
            endInput.value = range?.end || '';
            endInput.placeholder = range?.end || `例如：${key}${diffSelectedYearCode}999`;
        }
        if (rangeHint) {
            rangeHint.style.display = 'block';
            rangeHint.textContent = range
                ? `${key}${diffSelectedYearCode} 自動範圍：${range.start} ~ ${range.end}`
                : `${key}${diffSelectedYearCode} 暫無現有號碼；可手動輸入要檢測的範圍`;
        }
        if (ruleHint) {
            ruleHint.style.display = 'block';
            ruleHint.textContent = '只檢測目前年份；起始号碼、結束号碼都可以手動修改。';
        }
        if (yearTabs) {
            yearTabs.querySelectorAll('button[data-year]').forEach(btn => {
                setYearTabStyle(btn, btn.dataset.year === diffSelectedYearCode);
            });
        }
        clearResultForRangeChange();
    };

    const renderYearTabs = (opt) => {
        const key = optionKey(opt);
        const grouped = key === 'G' || key === 'KC';
        if (!yearTabsWrap || !yearTabs) return;

        if (!grouped) {
            yearTabsWrap.style.display = 'none';
            yearTabs.innerHTML = '';
            diffSelectedYearCode = '';
            return;
        }

        const years = (Array.isArray(opt?.recent_years) ? opt.recent_years : []).slice().reverse();
        yearTabsWrap.style.display = 'block';
        yearTabs.innerHTML = '';
        years.forEach((yearCode, index) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.dataset.year = String(yearCode);
            btn.textContent = `${yearCode}年`;
            btn.title = `查看 ${key}${yearCode} 年度缺號`;
            setYearTabStyle(btn, index === 0);
            btn.addEventListener('click', () => applyYearRange(opt, String(yearCode)));
            yearTabs.appendChild(btn);
        });

        if (years.length) {
            applyYearRange(opt, String(years[0]));
        }
    };

    const applyOption = (opt) => {
        if (!opt) return;
        const key = optionKey(opt);
        const grouped = key === 'G' || key === 'KC';

        // All three types keep editable start/end inputs. G/KC additionally get year tabs.
        if (manualRangeRow) manualRangeRow.style.display = 'grid';
        renderYearTabs(opt);

        if (grouped) return;

        if (startInput) {
            startInput.value = opt.start || '';
            startInput.placeholder = '例如：1007500';
        }
        if (endInput) {
            endInput.value = opt.end || '';
            endInput.placeholder = '例如：1008225';
        }
        if (rangeHint) {
            rangeHint.style.display = 'block';
            rangeHint.textContent = `自動範圍：${opt.start || '-'} ~ ${opt.end || '-'}`;
        }
        if (ruleHint) {
            ruleHint.style.display = 'block';
            ruleHint.textContent = '國外訂單最低從 1007500 開始；當最大號碼超過 1000 號範圍後，自動改為「最大號碼 - 1000」開始檢測。起訖號碼可手動修改。';
        }
        clearResultForRangeChange();
    };

    try {
        const response = await fetch('/tracking/api/order-number-pool/range');
        const data = await response.json();

        if (!data.success || !data.data) {
            if (rangeHint) {
                rangeHint.style.display = 'block';
                rangeHint.textContent = data.error || '無法取得號碼範圍';
            }
            return;
        }

        const options = data.data.options || [];
        diffRangeOptionsCache = options;
        if (options.length === 0) {
            if (rangeHint) {
                rangeHint.style.display = 'block';
                rangeHint.textContent = '無可用號碼範圍';
            }
            return;
        }

        // User-facing choices are intentionally only: 國外訂單 / G / KC.
        if (prefixGroup && prefixSelect) {
            prefixGroup.style.display = 'block';
            prefixSelect.innerHTML = options.map(opt =>
                `<option value="${optionKey(opt)}">${optionLabel(opt)}</option>`
            ).join('');
        }

        const preferred = String(data.data.preferred_key ?? data.data.preferred_prefix ?? 'NUMERIC');
        const selected = options.find(o => optionKey(o) === preferred) || options[0];
        if (prefixSelect) {
            prefixSelect.value = optionKey(selected);
            prefixSelect.onchange = () => {
                applyOption(options.find(o => optionKey(o) === prefixSelect.value));
            };
        }
        applyOption(selected);
    } catch (error) {
        if (rangeHint) {
            rangeHint.style.display = 'block';
            rangeHint.textContent = '取得範圍失敗，請稍後重試';
        }
    }
}

async function performDiff() {
    const startNumber = document.getElementById('diff-start-number').value.trim();
    const endNumber = document.getElementById('diff-end-number').value.trim();
    const performBtn = document.getElementById('diffModalPerform');
    const originalButtonText = performBtn ? performBtn.textContent : '';
    if (performBtn) {
        performBtn.disabled = true;
        performBtn.textContent = '檢測中...';
    }
    
    // 清除之前的錯誤信息
    const errorHint = document.getElementById('diff-error-hint');
    if (errorHint) {
        errorHint.style.display = 'none';
        errorHint.textContent = '';
    }
    const diffResult = document.getElementById('diff-result');
    if (diffResult) {
        diffResult.style.display = 'none';
    }
    
    try {
        const selectedGroup = document.getElementById('diff-prefix-select')?.value || 'NUMERIC';
        if (!startNumber || !endNumber) {
            displayDiffErrorInline('請輸入起始号碼與結束号碼');
            return;
        }
        const payload = {
            start_number: startNumber,
            end_number: endNumber,
            group: selectedGroup,
            year_code: diffSelectedYearCode || ''
        };

        const response = await fetch('/tracking/api/order-number-pool/diff', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await response.json();
        
        if (data.success) {
            displayDiffResult(data.data);
        } else {
            // 在输入框下方显示错误信息
            displayDiffErrorInline(data.error || '檢測失敗');
        }
    } catch (error) {
        console.error('缺號檢測失敗:', error);
        displayDiffErrorInline('檢測失敗，請重試');
    } finally {
        if (performBtn) {
            performBtn.disabled = false;
            performBtn.textContent = originalButtonText || '開始檢測';
        }
    }
}

function displayDiffErrorInline(message) {
    // 在输入框下方显示错误提示
    let errorHint = document.getElementById('diff-error-hint');
    if (!errorHint) {
        // 如果不存在，创建一个
        const formRow = document.querySelector('#diff-start-number').closest('.form-row');
        if (formRow && formRow.parentNode) {
            errorHint = document.createElement('div');
            errorHint.id = 'diff-error-hint';
            errorHint.style.cssText = 'display: block; color: #ef4444; font-size: 0.875rem; margin-top: 0.5rem; padding: 0.75rem; background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px;';
            formRow.parentNode.insertBefore(errorHint, formRow.nextSibling);
        }
    }
    if (errorHint) {
        errorHint.style.display = 'block';
        errorHint.textContent = message;
    }
    
    // 同时隐藏结果区域
    const diffResult = document.getElementById('diff-result');
    if (diffResult) {
        diffResult.style.display = 'none';
    }
}

function displayDiffError(message) {
    document.getElementById('diff-result').style.display = 'block';
    document.getElementById('diff-missing-list').style.display = 'none';
    document.getElementById('diff-no-missing').style.display = 'none';
    document.getElementById('diff-error').style.display = 'block';
    document.getElementById('diff-error-message').textContent = message;
}

function displayDiffResult(result) {
    // 顯示結果區域
    document.getElementById('diff-result').style.display = 'block';
    document.getElementById('diff-error').style.display = 'none';

    // 缺號 = 真正不存在 + 未解鎖；未解鎖另外保留子清單，方便判斷原因。
    document.getElementById('diff-total').textContent = result.range.total;
    document.getElementById('diff-existing').textContent = result.existing_count;
    document.getElementById('diff-excluded').textContent = result.excluded_count;
    const unlockedCount = result.unlocked_count || 0;
    const unlockedCountEl = document.getElementById('diff-unlocked');
    if (unlockedCountEl) unlockedCountEl.textContent = unlockedCount;
    document.getElementById('diff-missing').textContent = result.missing_count;

    if (result.missing_count > 0) {
        document.getElementById('diff-missing-list').style.display = 'block';
        const numbersContainer = document.getElementById('diff-missing-numbers');
        const unlockedSet = new Set(result.unlocked_numbers || []);
        numbersContainer.innerHTML = (result.missing_numbers || []).map(num => {
            const isUnlocked = unlockedSet.has(num);
            const bg = isUnlocked ? '#fff7ed' : '#fef2f2';
            const border = isUnlocked ? '#fed7aa' : '#fecaca';
            const color = isUnlocked ? '#c2410c' : '#dc2626';
            const title = isUnlocked ? '未解鎖：號碼已建立，但正式訂單尚未回來' : '真正缺號：系統內沒有這個訂單號';
            return `<div title="${title}" style="padding: 0.5rem; background: ${bg}; border: 1px solid ${border}; border-radius: 4px; text-align: center; font-family: monospace; color: ${color};">${num}</div>`;
        }).join('');
    } else {
        document.getElementById('diff-missing-list').style.display = 'none';
    }

    // 未解鎖子清單：在缺號總清單內已計算，這裡再單獨列出方便追單。
    const unlockedList = document.getElementById('diff-unlocked-list');
    const unlockedContainer = document.getElementById('diff-unlocked-numbers');
    if (unlockedList && unlockedContainer) {
        if (unlockedCount > 0) {
            unlockedList.style.display = 'block';
            unlockedContainer.innerHTML = (result.unlocked_numbers || []).map(num =>
                `<div style="padding: 0.5rem; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 4px; text-align: center; font-family: monospace; color: #c2410c;">${num}</div>`
            ).join('');
        } else {
            unlockedList.style.display = 'none';
            unlockedContainer.innerHTML = '';
        }
    }

    document.getElementById('diff-no-missing').style.display =
        result.missing_count === 0 ? 'block' : 'none';
}

// ==================== 工具函數 ====================
function closeAdminModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
    }
}

function closeModalOnBackdrop(event, modalId) {
    try {
        console.log('[closeModalOnBackdrop] 點擊:', event.target.id);
        if (event.target.id === modalId) {
            closeAdminModal(modalId);
        }
    } catch (error) {
        console.error('[closeModalOnBackdrop] 錯誤:', error);
    }
}

function toggleSelectAll() {
    const checked = document.getElementById('select-all').checked;
    document.querySelectorAll('.row-checkbox').forEach(cb => {
        cb.checked = checked;
    });
}

// handleSearch 函数已删除，改用 searchAllOrders


function showToast(message, type = 'info') {
    // 使用与 tracking.js 相同的 Toast 系统
    const toast = document.createElement('div');
    toast.className = 'toast show';
    
    const icon = type === 'success' ? '✓' : type === 'error' ? '✕' : 'ⓘ';
    const bgColor = type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6';
    
    toast.innerHTML = `
        <div style="display: flex; align-items: center; gap: 0.75rem;">
            <div style="width: 32px; height: 32px; border-radius: 50%; background: white; color: ${bgColor}; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 1.2rem;">
                ${icon}
            </div>
            <div>
                <div style="font-weight: 600; margin-bottom: 0.25rem;">${type === 'success' ? '成功' : type === 'error' ? '錯誤' : '提示'}</div>
                <div style="font-size: 0.9rem; opacity: 0.95;">${message}</div>
            </div>
        </div>
    `;
    
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        background: ${bgColor};
        color: white;
        border-radius: 8px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.2);
        z-index: 10000;
        min-width: 320px;
        animation: slideInRight 0.3s ease;
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ==================== Modal 提示函數 ====================
async function showAlertModal(title, message) {
    // 使用全局的 showAlertModal 或 showToast
    if (typeof window.showAlertModal === 'function') {
        await window.showAlertModal(message, title);
    } else if (typeof showToast === 'function') {
        showToast(title, message, 'info');
    } else {
        // 最后的后备方案
        if (typeof showToast === 'function') {
            showToast(title, message, 'info');
        }
    }
}

async function showConfirmModal(
    message,
    title = '确认操作',
    confirmText = '确认',
    cancelText = '取消',
    danger = false,
    options = {}
) {
    // 使用全局的 showConfirmModal（tracking.js）
    if (typeof window.showConfirmModal === 'function') {
        return await window.showConfirmModal(
            message,
            title,
            confirmText,
            cancelText,
            danger,
            options
        );
    }

    // 后备方案：使用原生 confirm
    const promptText = title ? `${title}\n\n${message}` : message;
    return window.confirm(promptText);
}

// 添加動畫樣式
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from { 
            transform: translateX(120%); 
            opacity: 0; 
        }
        to { 
            transform: translateX(0); 
            opacity: 1; 
        }
    }
    @keyframes slideOutRight {
        from { 
            transform: translateX(0); 
            opacity: 1; 
        }
        to { 
            transform: translateX(120%); 
            opacity: 0; 
        }
    }
`;
document.head.appendChild(style);

// ==================== 掛載到全局供 HTML onclick 使用 ====================
console.log('=== 開始掛載全局函數 ===');
window.closeAdminModal = closeAdminModal;
window.openBatchCreateModal = openBatchCreateModal;
window.openMarkSkipModal = openMarkSkipModal;
window.openUnlockModal = openUnlockModal;
window.openMissingCheckModal = openMissingCheckModal;
window.generateNumbers = generateNumbers;
window.markSkipNumbers = markSkipNumbers;
window.unlockOrder = unlockOrder;
window.performDiff = performDiff;
window.toggleSelectAll = toggleSelectAll;
// handleSearch 已删除，改用 searchAllOrders
window.searchAllOrders = searchAllOrders;
window.loadAllOrders = loadAllOrders;
window.loadAdminUnlockedOrders = loadAdminUnlockedOrders;
window.loadUnlockedOrders = loadAdminUnlockedOrders; // 向后兼容
window.loadLockedOrders = loadLockedOrders;
window.setAllOrdersPageSize = setAllOrdersPageSize;
window.setUnlockedPageSize = setUnlockedPageSize;
window.setLockedPageSize = setLockedPageSize;
window.handleAllOrdersSearch = handleAllOrdersSearch;
window.handleUnlockedSearch = handleUnlockedSearch;
window.handleLockedSearch = handleLockedSearch;
window.toggleSelectAllOrders = toggleSelectAllOrders;
window.toggleSelectAllUnlocked = toggleSelectAllUnlocked;
window.toggleSelectAllLocked = toggleSelectAllLocked;
window.confirmDeleteOrder = confirmDeleteOrder;
window.batchDeleteOrders = batchDeleteOrders;
window.batchDeleteUnlockedOrders = batchDeleteUnlockedOrders;
window.batchDeleteLockedOrders = batchDeleteLockedOrders;
window.toggleVisibility = toggleVisibility;
window.handleOrderRowClick = handleOrderRowClick;
window.loadAvailableOrders = loadAvailableOrders;
window.goToAvailableOrdersPage = goToAvailableOrdersPage;
window.handleAvailableSearch = handleAvailableSearch;
window.openNewWorkflowModalWithOrder = openNewWorkflowModalWithOrder;
window.openWorkspaceDrawerFromOrder = openWorkspaceDrawerFromOrder;
window.loadMyProjects = loadMyProjects;
window.handleMyProjectsSearch = handleMyProjectsSearch;
window.openWorkspaceDrawer = openWorkspaceDrawer;
console.log('=== 全局函數掛載完成 ===');
console.log('window.closeAdminModal:', typeof window.closeAdminModal);
console.log('window.openBatchCreateModal:', typeof window.openBatchCreateModal);

// ==================== Modal 事件監聽器設置 ====================
function setupModalEventListeners() {
    console.log('[setupModalEventListeners] 開始設置...');
    
    // generateModal
    setupSingleModal('generateModal', 'generateModalCancel', 'generateModalConfirm', generateNumbers);
    
    // markModal
    setupSingleModal('markModal', 'markModalCancel', 'markModalConfirm', markSkipNumbers);
    
    // addSkipModal
    setupSingleModal('addSkipModal', 'addSkipModalCancel', 'addSkipModalConfirm', addSkipNumbers);
    
    // unlockModal
    setupSingleModal('unlockModal', 'unlockModalCancel', 'unlockModalConfirm', unlockOrder);
    
    // diffModal (使用 diffModalPerform 而不是 Confirm)
    const diffModal = document.getElementById('diffModal');
    const diffModalCancel = document.getElementById('diffModalCancel');
    const diffModalPerform = document.getElementById('diffModalPerform');
    const diffModalClearTodayIgnore = document.getElementById('diffModalClearTodayIgnore');
    const diffModalClose = diffModal?.querySelector('.close-btn');
    
    // 移除 Backdrop 點擊關閉（只允許通過按鈕關閉）
    if (diffModalClose) {
        diffModalClose.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            closeAdminModal('diffModal');
        });
    }
    if (diffModalCancel) {
        diffModalCancel.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            closeAdminModal('diffModal');
        });
    }
    if (diffModalPerform) {
        diffModalPerform.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            performDiff();
        });
    }
    if (diffModalClearTodayIgnore) {
        diffModalClearTodayIgnore.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (!hasTodayMissingReminderIgnore()) return;
            clearTodayMissingReminderIgnore();
        });
    }
    
    console.log('[setupModalEventListeners] 所有 Modal 設置完成');
}

function setupSingleModal(modalId, cancelBtnId, confirmBtnId, confirmAction) {
    const modal = document.getElementById(modalId);
    const cancelBtn = document.getElementById(cancelBtnId);
    const confirmBtn = document.getElementById(confirmBtnId);
    const closeBtn = modal?.querySelector('.close-btn');
    
    if (!modal) {
        console.error(`[setupSingleModal] 找不到 Modal: ${modalId}`);
        return;
    }
    
    // 移除 Backdrop 點擊關閉（只允許通過按鈕關閉）
    
    // Close 按鈕
    if (closeBtn) {
        closeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            console.log(`[${modalId}] Close 按鈕被點擊`);
            closeAdminModal(modalId);
        });
    }
    
    // Cancel 按鈕
    if (cancelBtn) {
        cancelBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            console.log(`[${modalId}] Cancel 按鈕被點擊`);
            closeAdminModal(modalId);
        });
    }
    
    // Confirm 按鈕
    if (confirmBtn && confirmAction) {
        confirmBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            console.log(`[${modalId}] Confirm 按鈕被點擊`);
            const result = confirmAction();
            console.log(`[${modalId}] confirmAction 返回值:`, result);
        });
    }
    
    console.log(`[setupSingleModal] ${modalId} 設置完成`);
}

// ==================== 刪除訂單功能 ====================
async function confirmDeleteOrder(orderNumber, customerName, currentStatus) {
    // 如果没有传递 customerName 和 currentStatus，尝试从 DOM 获取
    if (!customerName || !currentStatus) {
        const row = document.querySelector(`tr[data-order-number="${orderNumber}"]`) || 
                    Array.from(document.querySelectorAll('tr.order-row')).find(tr => {
                        const orderNumCell = tr.querySelector('td:nth-child(2) strong');
                        return orderNumCell && orderNumCell.textContent === orderNumber;
                    });
        
        if (row) {
            const customerCell = row.querySelector('td:nth-child(3)');
            const statusCell = row.querySelector('td:nth-child(5) .status-badge');
            customerName = customerName || (customerCell ? customerCell.textContent.trim() : '未知客户');
            currentStatus = currentStatus || (statusCell ? statusCell.textContent.trim() : '未知状态');
        } else {
            customerName = customerName || '未知客户';
            currentStatus = currentStatus || '未知状态';
        }
    }
    
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
        `确定要继续吗？`,
        '确认删除',
        '确认删除',
        '取消',
        true
    );
    if (!confirmed) {
        return;
    }
    
    try {
        const response = await fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                confirm_order_number: orderNumber,
                reason: '管理員刪除'
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('刪除成功', 'success');
            // 重新載入當前TAB
            const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
            if (activeTab === 'all-orders') {
                loadAllOrders(allOrdersPage);
            } else if (activeTab === 'unlocked') {
                loadAdminUnlockedOrders(unlockedPage);
            } else if (activeTab === 'locked') {
                loadLockedOrders(lockedPage);
            } else if (activeTab === 'skip') {
                loadSkipNumbers();
            }
        } else {
            showToast('刪除失敗: ' + (data.error || '未知錯誤'), 'error');
        }
    } catch (error) {
        console.error('刪除訂單失敗:', error);
        showToast('刪除失敗', 'error');
    }
}

async function batchDeleteOrders() {
    const checkboxes = document.querySelectorAll('#all-orders-table-body .order-checkbox:checked');
    const orderNumbers = Array.from(checkboxes).map(cb => cb.value);
    
    if (orderNumbers.length === 0) {
        showToast('請選擇要刪除的訂單', 'error');
        return;
    }
    
    const confirmed = await showConfirmModal(
        `确定要删除选中的 ${orderNumbers.length} 个订单？\n\n⚠️ 此操作无法复原，关联的流程和文件也将被删除！`,
        '⚠️ 批量删除确认',
        '确认删除',
        '取消',
        true,
        { requireInput: 'DELETE' }
    );
    if (!confirmed) {
        return;
    }
    
    try {
        const response = await fetch('/tracking/api/orders/batch-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                order_numbers: orderNumbers,
                reason: '批量刪除'
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`成功刪除 ${data.data.deleted_count} 個訂單`, 'success');
            const selectAll = document.getElementById('select-all-orders');
            if (selectAll) selectAll.checked = false;
            loadAllOrders(allOrdersPage);
        } else {
            showToast('批量刪除失敗: ' + (data.error || '未知錯誤'), 'error');
        }
    } catch (error) {
        console.error('批量刪除失敗:', error);
        showToast('批量刪除失敗', 'error');
    }
}

async function batchDeleteUnlockedOrders() {
    const checkboxes = document.querySelectorAll('#unlocked-table-body .unlocked-checkbox:checked');
    const orderNumbers = Array.from(checkboxes).map(cb => cb.value);
    
    if (orderNumbers.length === 0) {
        showToast('請選擇要刪除的訂單', 'error');
        return;
    }
    
    const confirmed = await showConfirmModal(
        `确定要删除选中的 ${orderNumbers.length} 个未解锁订单？\n\n⚠️ 此操作无法复原！`,
        '⚠️ 批量删除确认',
        '确认删除',
        '取消',
        true,
        { requireInput: 'DELETE' }
    );
    if (!confirmed) {
        return;
    }
    
    try {
        const response = await fetch('/tracking/api/orders/batch-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                order_numbers: orderNumbers,
                reason: '批量刪除未解鎖訂單'
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`成功刪除 ${data.data.deleted_count} 個訂單`, 'success');
            const selectAll = document.getElementById('select-all-unlocked');
            if (selectAll) selectAll.checked = false;
            loadAdminUnlockedOrders(unlockedPage);
        } else {
            showToast('批量刪除失敗: ' + (data.error || '未知錯誤'), 'error');
        }
    } catch (error) {
        console.error('批量刪除失敗:', error);
        showToast('批量刪除失敗', 'error');
    }
}

async function batchDeleteLockedOrders() {
    const checkboxes = document.querySelectorAll('#locked-table-body .locked-checkbox:checked');
    const orderNumbers = Array.from(checkboxes).map(cb => cb.value);
    
    if (orderNumbers.length === 0) {
        showToast('請選擇要刪除的訂單', 'error');
        return;
    }
    
    const confirmed = await showConfirmModal(
        `确定要删除选中的 ${orderNumbers.length} 个已解锁订单？\n\n⚠️ 此操作无法复原，关联的流程和文件也将被删除！`,
        '⚠️ 批量删除确认',
        '确认删除',
        '取消',
        true,
        { requireInput: 'DELETE' }
    );
    if (!confirmed) {
        return;
    }
    
    try {
        const response = await fetch('/tracking/api/orders/batch-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                order_numbers: orderNumbers,
                reason: '批量刪除已解鎖訂單'
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`成功刪除 ${data.data.deleted_count} 個訂單`, 'success');
            const selectAll = document.getElementById('select-all-locked');
            if (selectAll) selectAll.checked = false;
            loadLockedOrders(lockedPage);
        } else {
            showToast('批量刪除失敗: ' + (data.error || '未知錯誤'), 'error');
        }
    } catch (error) {
        console.error('批量刪除失敗:', error);
        showToast('批量刪除失敗', 'error');
    }
}

// ==================== 業務員：可創建項目 / 我的項目 ====================
let availableOrdersSearchDebounce = null;
let availableOrdersCache = new Map();
let availableOrdersSortKey = 'unlocked_at';
let availableOrdersSortDir = 'desc';
let allAvailableOrders = [];       // 全部可用訂單（前端分頁用）
let availableOrdersPage = 1;
const availableOrdersPageSize = 50;
let myProjectsPage = 1;
let myProjectsSearchDebounce = null;
const myProjectsPageSize = 50;
let myProjectsSortKey = 'created_at';
let myProjectsSortDir = 'desc';

function setAvailableOrdersSort(key, dir) {
    availableOrdersSortKey = key;
    availableOrdersSortDir = dir;
    localStorage.setItem('availableOrdersSortKey', key);
    localStorage.setItem('availableOrdersSortDir', dir);
}

function initAvailableOrdersSortState() {
    const storedKey = localStorage.getItem('availableOrdersSortKey');
    const storedDir = localStorage.getItem('availableOrdersSortDir');
    if (storedKey && storedDir) {
        setAvailableOrdersSort(storedKey, storedDir);
    }
    updateAvailableOrdersSortIndicators();
}

function setupAvailableOrdersSorting() {
    const headers = document.querySelectorAll('#tab-available-orders .admin-orders-table thead th.sortable');
    if (!headers.length) return;
    headers.forEach(header => {
        header.addEventListener('click', () => {
            const key = header.dataset.sort;
            if (!key) return;
            if (availableOrdersSortKey === key) {
                availableOrdersSortDir = availableOrdersSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                availableOrdersSortKey = key;
                availableOrdersSortDir = key === 'unlocked_at' ? 'desc' : 'asc';
            }
            setAvailableOrdersSort(availableOrdersSortKey, availableOrdersSortDir);
            updateAvailableOrdersSortIndicators();
            loadAvailableOrders();
        });
    });
    updateAvailableOrdersSortIndicators();
}

function updateAvailableOrdersSortIndicators() {
    const headers = document.querySelectorAll('#tab-available-orders .admin-orders-table thead th.sortable');
    headers.forEach(header => {
        const indicator = header.querySelector('.sort-indicator');
        if (!indicator) return;
        if (header.dataset.sort === availableOrdersSortKey) {
            indicator.textContent = availableOrdersSortDir === 'asc' ? '▲' : '▼';
        } else {
            indicator.textContent = '';
        }
    });
}

function setMyProjectsSort(key, dir) {
    myProjectsSortKey = key;
    myProjectsSortDir = dir;
    localStorage.setItem('myProjectsSortKey', key);
    localStorage.setItem('myProjectsSortDir', dir);
}

function initMyProjectsSortState() {
    const storedKey = localStorage.getItem('myProjectsSortKey');
    const storedDir = localStorage.getItem('myProjectsSortDir');
    if (storedKey && storedDir) {
        setMyProjectsSort(storedKey, storedDir);
    }
    updateMyProjectsSortIndicators();
}

function setupMyProjectsSorting() {
    const headers = document.querySelectorAll('#tab-my-projects .admin-orders-table thead th.sortable');
    if (!headers.length) return;
    headers.forEach(header => {
        header.addEventListener('click', () => {
            const key = header.dataset.sort;
            if (!key) return;
            if (myProjectsSortKey === key) {
                myProjectsSortDir = myProjectsSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                myProjectsSortKey = key;
                myProjectsSortDir = key === 'created_at' ? 'desc' : 'asc';
            }
            setMyProjectsSort(myProjectsSortKey, myProjectsSortDir);
            updateMyProjectsSortIndicators();
            loadMyProjects(1);
        });
    });
    updateMyProjectsSortIndicators();
}

function updateMyProjectsSortIndicators() {
    const headers = document.querySelectorAll('#tab-my-projects .admin-orders-table thead th.sortable');
    headers.forEach(header => {
        const indicator = header.querySelector('.sort-indicator');
        if (!indicator) return;
        if (header.dataset.sort === myProjectsSortKey) {
            indicator.textContent = myProjectsSortDir === 'asc' ? '▲' : '▼';
        } else {
            indicator.textContent = '';
        }
    });
}

async function loadAvailableOrders() {
    const search = document.getElementById('available-search')?.value || '';
    updateAvailableOrdersSortIndicators();

    try {
        const url = `/tracking/api/orders/unlocked?include_counts=1&search=${encodeURIComponent(search)}&sort_by=${encodeURIComponent(availableOrdersSortKey)}&sort_order=${encodeURIComponent(availableOrdersSortDir)}`;
        const response = await fetch(url);
        const result = await response.json();

        if (result.success) {
            allAvailableOrders = result.data || [];
            availableOrdersPage = 1;
            renderAvailableOrdersPage();
        } else {
            showToast(result.error || '載入失敗', 'error');
        }
    } catch (error) {
        console.error('載入可創建項目的訂單失敗:', error);
        showToast('載入失敗，請重試', 'error');
    }
}

function goToAvailableOrdersPage(page) {
    availableOrdersPage = page;
    renderAvailableOrdersPage();
}

function renderAvailableOrdersPage() {
    const tbody = document.getElementById('available-orders-table-body');
    if (!tbody) return;

    availableOrdersCache = new Map();
    const total = allAvailableOrders.length;

    if (total === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center">暂无可创建项目的订单</td></tr>`;
        renderAvailableOrdersPagination({ page: 1, total_pages: 1, total: 0, page_size: availableOrdersPageSize });
        return;
    }

    const totalPages = Math.ceil(total / availableOrdersPageSize);
    if (availableOrdersPage > totalPages) availableOrdersPage = totalPages;
    if (availableOrdersPage < 1) availableOrdersPage = 1;

    const start = (availableOrdersPage - 1) * availableOrdersPageSize;
    const end = Math.min(start + availableOrdersPageSize, total);
    const pageOrders = allAvailableOrders.slice(start, end);

    tbody.innerHTML = pageOrders.map(order => {
        availableOrdersCache.set(order.order_number, order);
        const count = typeof order.project_count === 'number' ? order.project_count : 0;
        const countLabel = `${count} 个项目`;
        const notesText = order.notes && order.notes.trim() ? escapeHtml(order.notes) : '-';
        return `
            <tr class="order-row" onclick="openWorkspaceDrawerFromOrder('${order.order_number}')">
                <td class="col-create-cell" onclick="event.stopPropagation();">
                    <button class="create-project-btn" onclick="openNewWorkflowModalWithOrder('${order.order_number}')" title="创建新项目">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M12 5v14M5 12h14"></path>
                        </svg>
                    </button>
                </td>
                <td>${escapeHtml(order.order_number)}</td>
                <td>${escapeHtml(order.customer_name || '-')}</td>
                <td class="text-muted">${countLabel}</td>
                <td>${formatDate(order.unlocked_at)}</td>
                <td class="notes-cell" title="${notesText}">${notesText}</td>
            </tr>
        `;
    }).join('');

    renderAvailableOrdersPagination({
        page: availableOrdersPage,
        total_pages: totalPages,
        total: total,
        page_size: availableOrdersPageSize
    });
}

function renderAvailableOrdersPagination(pagination) {
    const container = document.getElementById('available-orders-pagination');
    if (!container) return;

    const { page, total_pages, total = 0, page_size = 50 } = pagination;
    if (total === 0 || total_pages <= 1) {
        container.innerHTML = `<span class="pagination-summary">共 ${total} 条</span>`;
        return;
    }
    const start = (page - 1) * page_size + 1;
    const end = Math.min(page * page_size, total);
    let html = '';
    html += `<span class="pagination-summary">显示 ${start} - ${end}，共 ${total} 条（第 ${page} / ${total_pages} 页）</span>`;
    html += `<button ${page === 1 ? 'disabled' : ''} onclick="goToAvailableOrdersPage(${page - 1})">上一頁</button>`;
    html += buildCompactPagination(page, total_pages, 'goToAvailableOrdersPage');
    html += `<button ${page === total_pages ? 'disabled' : ''} onclick="goToAvailableOrdersPage(${page + 1})">下一頁</button>`;
    container.innerHTML = html;
}

function handleAvailableSearch() {
    if (availableOrdersSearchDebounce) clearTimeout(availableOrdersSearchDebounce);
    availableOrdersSearchDebounce = setTimeout(() => {
        loadAvailableOrders();
    }, 300);
}

function openNewWorkflowModalWithOrder(orderNumber) {
    if (typeof window.openNewWorkflowModal !== 'function') {
        showToast('无法打开创建流程窗口', 'error');
        return;
    }
    window.openNewWorkflowModal();
    setTimeout(() => {
        const orderInput = document.getElementById('newOrderNumber');
        if (orderInput) {
            orderInput.value = orderNumber;
            if (typeof window.validateOrderNumber === 'function') {
                window.validateOrderNumber(orderNumber);
            } else if (typeof window.searchOrderNumber === 'function') {
                window.searchOrderNumber(orderNumber);
            }
        }
    }, 200);
}

function openWorkspaceDrawerFromOrder(orderNumber) {
    if (!orderNumber) return;
    if (window.WorkspaceDrawer && typeof window.WorkspaceDrawer.openFromOrder === 'function') {
        // openFromOrder 內部已有降級處理，catch 這裡只做 log，不開 modal
        window.WorkspaceDrawer.openFromOrder(orderNumber)
            .catch((err) => {
                console.warn('[openWorkspaceDrawerFromOrder] 開啟失敗:', err);
            });
        return;
    }
    openNewWorkflowModalWithOrder(orderNumber);
}

async function loadMyProjects(page = 1) {
    myProjectsPage = page;
    const status = document.getElementById('my-projects-status')?.value || 'all';
    const search = document.getElementById('my-projects-search')?.value || '';
    updateMyProjectsSortIndicators();
    const isAdmin = isAdminRole();

    try {
        const adminFilter = isAdmin ? '&created_by_me=1' : '';
        const url = `/tracking/api/workflows/mine?status=${encodeURIComponent(status)}&sort_by=${encodeURIComponent(myProjectsSortKey)}&sort_order=${encodeURIComponent(myProjectsSortDir)}&search=${encodeURIComponent(search)}&page=${page}&page_size=${myProjectsPageSize}${adminFilter}`;
        const response = await fetch(url);
        const result = await response.json();

        if (result.success) {
            renderMyProjectsTable(result.data || []);
            renderMyProjectsPagination(result.pagination);
        } else {
            showToast(result.error || '載入失敗', 'error');
        }
    } catch (error) {
        console.error('載入我的項目失敗:', error);
        showToast('載入失敗，請重試', 'error');
    }
}

function renderMyProjectsTable(projects) {
    const tbody = document.getElementById('my-projects-table-body');
    if (!tbody) return;

        if (!projects || projects.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center">暂无项目</td></tr>`;
        return;
    }

    tbody.innerHTML = projects.map(project => {
        const light = project.status_light || 'green';
        const lightClass = light === 'red' ? 'red' : light === 'yellow' ? 'yellow' : 'green';
        const lightEmoji = light === 'red' ? '🔴' : light === 'yellow' ? '🟡' : '🟢';
        const statusLabel = escapeHtml(project.status_label || project.current_status || '-');
        return `
            <tr class="${lightClass}" onclick="openWorkspaceDrawer('${project.workflow_number}')">
                <td>${formatDate(project.created_at)}</td>
                <td>${escapeHtml(project.workflow_number)}</td>
                <td>${escapeHtml(project.customer_name || '-')}</td>
                <td><span class="status-pill ${lightClass}">${lightEmoji} ${statusLabel}</span></td>
            </tr>
        `;
    }).join('');
}

function renderMyProjectsPagination(pagination) {
    const container = document.getElementById('my-projects-pagination');
    if (!container || !pagination) return;

    const { page, total_pages } = pagination;
    if (total_pages <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = '';
    html += `<button ${page === 1 ? 'disabled' : ''} onclick="loadMyProjects(${page - 1})">上一頁</button>`;
    for (let i = 1; i <= total_pages; i += 1) {
        html += `<button class="${i === page ? 'active' : ''}" onclick="loadMyProjects(${i})">${i}</button>`;
    }
    html += `<button ${page === total_pages ? 'disabled' : ''} onclick="loadMyProjects(${page + 1})">下一頁</button>`;
    container.innerHTML = html;
}

function handleMyProjectsSearch() {
    if (myProjectsSearchDebounce) clearTimeout(myProjectsSearchDebounce);
    myProjectsSearchDebounce = setTimeout(() => {
        loadMyProjects(1);
    }, 300);
}

function openWorkspaceDrawer(workflowNumber) {
    if (!workflowNumber) return;
    if (window.WorkspaceDrawer && typeof window.WorkspaceDrawer.open === 'function') {
        window.WorkspaceDrawer.open(workflowNumber);
        return;
    }
    const url = `/tracking/?workflow=${encodeURIComponent(workflowNumber)}`;
    window.location.href = url;
}

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', () => {
    console.log('[DOMContentLoaded] 開始初始化...');
    const isAdmin = isAdminRole();

    resetAdminOrdersTableColumns();
    if (isAdmin) {
        setupAllOrdersSorting();
        setupUnlockedSorting();
        setupLockedSorting();
    }
    initAvailableOrdersSortState();
    setupAvailableOrdersSorting();
    initMyProjectsSortState();
    setupMyProjectsSorting();
    
    // 設置 Modal 事件監聽器
    if (isAdmin) {
        setupModalEventListeners();

        // 從首頁缺號提醒的「查看明細」進來：Modal 打開後直接完成檢測，不再要求再按一次。
        const params = new URLSearchParams(window.location.search);
        if (params.get('openMissingCheck') === '1') {
            const startNumber = params.get('missingStart') || '';
            const endNumber = params.get('missingEnd') || '';
            setTimeout(() => {
                openMissingCheckModal({
                    startNumber,
                    endNumber,
                    autoRun: true
                });
            }, 0);

            // 清掉一次性參數，避免重新整理又因 URL 參數重複開啟。
            params.delete('openMissingCheck');
            params.delete('missingStart');
            params.delete('missingEnd');
            const cleanQuery = params.toString();
            const cleanUrl = `${window.location.pathname}${cleanQuery ? `?${cleanQuery}` : ''}${window.location.hash || ''}`;
            window.history.replaceState({}, document.title, cleanUrl);
        }
    }
    
    // 設置抽屜 ESC 鍵監聽
    setupAdminDrawerEscapeKey();
    
    // 設置 TAB 切換
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            
            // 更新按鈕狀態
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // 更新內容顯示
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            const content = document.getElementById(`tab-${tab}`);
            if (content) {
                content.classList.add('active');
            }
            
            // 載入對應數據
            if (tab === 'all-orders') {
                loadAllOrders(1);
            } else if (tab === 'unlocked') {
                loadAdminUnlockedOrders(1);
            } else if (tab === 'locked') {
                loadLockedOrders(1);
            } else if (tab === 'skip') {
                loadSkipNumbers(1);
            } else if (tab === 'available-orders') {
                loadAvailableOrders();
            } else if (tab === 'my-projects') {
                loadMyProjects(1);
            }

            // 控制統計條顯示（只在 admin tab 顯示）
            const sharedStatsBar = document.getElementById('shared-stats-bar');
            if (sharedStatsBar) {
                if (tab === 'all-orders' || tab === 'unlocked' || tab === 'locked') {
                    sharedStatsBar.style.display = '';
                } else {
                    sharedStatsBar.style.display = 'none';
                }
            }
        });
    });

    if (!isAdmin) {
        ['tab-all-orders', 'tab-unlocked', 'tab-locked', 'tab-skip'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.classList.remove('active');
                el.style.display = 'none';
            }
        });
    }

    // 初始化每頁筆數
    if (isAdmin) {
        const allOrdersPageSizeSelect = document.getElementById('page-size-all');
        if (allOrdersPageSizeSelect) {
            allOrdersPageSizeSelect.value = String(allOrdersPageSize);
        }
        const skipPageSizeSelect = document.getElementById('skip-page-size');
        if (skipPageSizeSelect) {
            skipPageSizeSelect.value = String(skipPageSize);
        }
    }
    
    // 初始化統計條顯示狀態（默認顯示，因為初始tab是all-orders）
    const sharedStatsBar = document.getElementById('shared-stats-bar');
    if (sharedStatsBar) {
        sharedStatsBar.style.display = isAdmin ? '' : 'none';
    }
    
    // 載入初始數據
    if (isAdmin) {
        loadAllOrders(1);
    } else {
        loadAvailableOrders();
    }

    // 解鎖訂單：客戶名稱自動完成
    setupUnlockCustomerAutocomplete();
    
    console.log('[DOMContentLoaded] 初始化完成');
});

function resetAdminOrdersTableColumns() {
    const tables = document.querySelectorAll('.admin-orders-page table');
    if (!tables || tables.length === 0) return;
    tables.forEach(table => {
        table.querySelectorAll('thead th, tbody td').forEach(cell => {
            if (cell.style && cell.style.display === 'none') {
                cell.style.display = '';
            }
        });
    });
}

// ==================== 跳號管理 ====================
let skipCurrentPage = 1;

async function loadSkipNumbers(page = 1) {
    skipCurrentPage = page;
    const search = document.getElementById('skip-search-input')?.value || '';
    
    try {
        const response = await fetch(
            `/tracking/api/skip-numbers?page=${page}&page_size=${skipPageSize}&search=${encodeURIComponent(search)}`
        );
        const data = await response.json();
        
        if (data.success) {
            renderSkipTable(data.data.numbers);
            renderSkipPagination(data.data.pagination);
            updateSkipStats(data.data.pagination.total);
        } else {
            showToast(data.error || '載入失敗', 'error');
        }
    } catch (error) {
        console.error('載入跳號失敗:', error);
        showToast('載入失敗，請重試', 'error');
    }
}

function renderSkipTable(numbers) {
    const tbody = document.getElementById('skip-table-body');
    
    if (!tbody) return;
    
    if (numbers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center">暫無跳號</td></tr>';
        return;
    }
    
    tbody.innerHTML = numbers.map(num => `
        <tr class="order-row">
            <td>
                <input type="checkbox" class="skip-checkbox" value="${num.order_number}">
            </td>
            <td><strong>${num.order_number}</strong></td>
            <td>${formatDate(num.created_at)}</td>
            <td>
                <div class="action-buttons">
                    <button class="btn btn-danger btn-sm hover-btn" 
                            onclick="deleteSingleSkip('${num.order_number}')">
                        刪除
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

function renderSkipPagination(pagination) {
    const container = document.getElementById('skip-pagination');
    if (!container) return;
    
    const { page, total_pages } = pagination;

    // 沒有分頁或只有一頁時，不顯示分頁按鈕
    if (!total_pages || total_pages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '';
    
    // 上一頁
    html += `<button ${page === 1 ? 'disabled' : ''} onclick="loadSkipNumbers(${page - 1})">上一頁</button>`;
    
    // 頁碼
    for (let i = Math.max(1, page - 2); i <= Math.min(total_pages, page + 2); i++) {
        html += `<button class="${i === page ? 'active' : ''}" onclick="loadSkipNumbers(${i})">${i}</button>`;
    }
    
    // 下一頁
    html += `<button ${page === total_pages ? 'disabled' : ''} onclick="loadSkipNumbers(${page + 1})">下一頁</button>`;
    
    container.innerHTML = html;
}

function updateSkipStats(total) {
    const element = document.getElementById('skip-total');
    if (element) {
        element.textContent = total || 0;
    }
}

function openAddSkipModal() {
    const modal = document.getElementById('addSkipModal');
    if (modal) {
        const input = document.getElementById('skip-numbers-input');
        if (input) input.value = '';
        modal.classList.add('show');
    }
}

async function addSkipNumbers() {
    const text = document.getElementById('skip-numbers-input')?.value || '';
    
    if (!text.trim()) {
        showToast('請輸入號碼', 'error');
        return;
    }
    
    // 解析號碼
    const numbers = text.split(/[\n,\s]+/).filter(n => n.trim()).map(n => n.trim());
    
    try {
        const response = await fetch('/tracking/api/skip-numbers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ numbers })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(data.message, 'success');
            closeAdminModal('addSkipModal');
            loadSkipNumbers();
        } else {
            showToast(data.error || '新增失敗', 'error');
        }
    } catch (error) {
        console.error('新增失敗:', error);
        showToast('新增失敗', 'error');
    }
}

async function deleteSingleSkip(number) {
    const confirmed = await showConfirmModal(
        `確定要刪除跳號 ${number}？`,
        '確認刪除',
        '確認刪除',
        '取消',
        true
    );
    if (!confirmed) return;
    
    await deleteSkipNumbers([number]);
}

/**
 * 解除跳号（将 SKIPPED 改回 UNLOCKED）
 */
async function removeSkip(orderNumber) {
    const confirmed = await showConfirmModal(
        `確定要解除跳號 ${orderNumber}？\n\n此操作會將訂單號狀態從「跳號」改回「未解鎖」。`,
        '確認解除跳號',
        '確認',
        '取消',
        false
    );
    
    if (!confirmed) {
        return;
    }
    
    try {
        const response = await fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}/remove-skip`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('解除跳號成功', 'success');
            // 重新載入當前TAB
            const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
            if (activeTab === 'all-orders') {
                loadAllOrders(allOrdersPage);
            } else if (activeTab === 'skip') {
                loadSkipNumbers();
            }
        } else {
            showToast('解除跳號失敗: ' + (data.error || '未知錯誤'), 'error');
        }
    } catch (error) {
        console.error('解除跳號失敗:', error);
        showToast('解除跳號失敗', 'error');
    }
}

async function batchDeleteSkip() {
    const checkboxes = document.querySelectorAll('.skip-checkbox:checked');
    
    if (checkboxes.length === 0) {
        showToast('請選擇要刪除的號碼', 'error');
        return;
    }
    
    const numbers = Array.from(checkboxes).map(cb => cb.value);
    
    const confirmed = await showConfirmModal(
        `確定要刪除 ${numbers.length} 個跳號？`,
        '確認批量刪除',
        '確認刪除',
        '取消',
        true
    );
    if (!confirmed) return;
    
    await deleteSkipNumbers(numbers);
}

async function deleteSkipNumbers(numbers) {
    try {
        const response = await fetch('/tracking/api/skip-numbers', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ numbers })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(data.message, 'success');
            loadSkipNumbers();
        } else {
            showToast(data.error || '刪除失敗', 'error');
        }
    } catch (error) {
        console.error('刪除失敗:', error);
        showToast('刪除失敗', 'error');
    }
}

function toggleAllSkip(checkbox) {
    const checkboxes = document.querySelectorAll('.skip-checkbox');
    checkboxes.forEach(cb => cb.checked = checkbox.checked);
}

function handleSkipSearch() {
    // 延遲搜尋（避免頻繁請求）
    clearTimeout(window.skipSearchTimeout);
    window.skipSearchTimeout = setTimeout(() => {
        loadSkipNumbers(1);
    }, 500);
}

// setPoolPageSize 函数已删除，改用 setAllOrdersPageSize

function setSkipPageSize(value) {
    skipPageSize = parseInt(value, 10) || 50;
    localStorage.setItem('skipPageSize', String(skipPageSize));
    loadSkipNumbers(1);
}

// ==================== 右侧抽屉 - 订单详情和文件管理 ====================

let currentAdminDrawerOrderNumber = null;

/**
 * 處理表格行點擊事件
 * 點擊行時打開抽屜,但排除點擊按鈕、複選框等交互元素
 */
function handleOrderRowClick(event, orderNumber, customerName) {
    console.log('[handleOrderRowClick] 被调用:', orderNumber, customerName);
    
    // 檢查點擊的目標元素
    const target = event.target;
    
    // 如果點擊的是可交互元素,不打開抽屜
    if (target.tagName === 'BUTTON' || 
        target.tagName === 'INPUT' || 
        target.tagName === 'TEXTAREA' ||
        target.tagName === 'A' ||
        target.closest('button') ||
        target.closest('input') ||
        target.closest('textarea') ||
        target.closest('.action-buttons') ||
        target.closest('.notes-edit') ||
        target.closest('.order-notes')) {
        console.log('[handleOrderRowClick] 点击了交互元素，不处理');
        return;
    }
    
    // 檢查抽屜是否已經打開
    const drawer = document.getElementById('adminDetailDrawer');
    const isDrawerOpen = drawer && drawer.classList.contains('show');
    
    console.log('[handleOrderRowClick] 抽屉是否打开:', isDrawerOpen);
    
    if (isDrawerOpen) {
        // 如果抽屜已打開,只更新內容,不關閉
        console.log('[handleOrderRowClick] 更新抽屉内容');
        updateAdminDrawerContent(orderNumber, customerName);
    } else {
        // 如果抽屜未打開,正常打開
        console.log('[handleOrderRowClick] 打开抽屉');
        openAdminDetailDrawer(orderNumber, customerName);
    }
}

/**
 * 打开管理员订单详情抽屉
 */
async function openAdminDetailDrawer(orderNumber, customerName) {
    currentAdminDrawerOrderNumber = orderNumber;
    
    // 更新抽屉信息
    document.getElementById('adminDrawerOrderNumber').textContent = orderNumber || '-';
    const customerNameDisplay = document.getElementById('adminDrawerCustomerNameDisplay');
    if (customerNameDisplay) {
        customerNameDisplay.textContent = customerName || '-';
    }
    
    // 显示抽屉（使用 tracking.css 中的样式）
    const overlay = document.getElementById('adminDetailDrawerOverlay');
    const drawer = document.getElementById('adminDetailDrawer');
    if (overlay) overlay.classList.add('show');
    if (drawer) drawer.classList.add('show');
    
    // 使用 requestAnimationFrame 延迟数据加载，让动画先开始
    requestAnimationFrame(() => {
        requestAnimationFrame(async () => {
            // 加载订单详情（包括备注和客户姓名）
            await loadAdminDrawerOrderDetails(orderNumber);
            
            // 加载文件列表
            await loadAdminDrawerFiles(orderNumber);
        });
    });
}

/**
 * 更新抽屜內容(不關閉抽屜)
 */
async function updateAdminDrawerContent(orderNumber, customerName) {
    console.log('[updateAdminDrawerContent] 开始更新:', orderNumber, customerName);
    
    currentAdminDrawerOrderNumber = orderNumber;
    
    // 更新抽屜信息
    const orderNumberEl = document.getElementById('adminDrawerOrderNumber');
    if (orderNumberEl) {
        orderNumberEl.textContent = orderNumber || '-';
        console.log('[updateAdminDrawerContent] 已更新订单号');
    }
    
    const customerNameDisplay = document.getElementById('adminDrawerCustomerNameDisplay');
    if (customerNameDisplay) {
        customerNameDisplay.textContent = customerName || '-';
        console.log('[updateAdminDrawerContent] 已更新客户名称');
    }
    
    // 關閉編輯模式（如果正在編輯）
    const editDiv = document.getElementById('adminDrawerNotesEdit');
    const displayDiv = document.getElementById('adminDrawerNotesDisplay');
    if (editDiv && displayDiv) {
        editDiv.style.display = 'none';
        displayDiv.style.display = 'block';
        console.log('[updateAdminDrawerContent] 已关闭编辑模式');
    }
    
    // 隱藏客戶名稱輸入框
    const customerNameInput = document.getElementById('adminDrawerCustomerNameInput');
    if (customerNameInput && customerNameDisplay) {
        customerNameInput.style.display = 'none';
        customerNameDisplay.style.display = 'inline';
    }
    
    // 重置編輯按鈕文本
    const editBtn = document.getElementById('adminDrawerEditBtn');
    if (editBtn) {
        editBtn.textContent = '编辑';
    }
    
    // 關閉預覽（如果正在預覽圖片）
    closeAdminDrawerPreview();
    
    console.log('[updateAdminDrawerContent] 开始加载订单详情');
    // 加載訂單詳情(包括備註和客戶委名)
    await loadAdminDrawerOrderDetails(orderNumber);
    
    console.log('[updateAdminDrawerContent] 开始加载文件列表');
    // 加載文件列表
    await loadAdminDrawerFiles(orderNumber);
    
    console.log('[updateAdminDrawerContent] 更新完成');
}

/**
 * 加载管理员抽屉订单详情（包括备注）
 */
async function loadAdminDrawerOrderDetails(orderNumber) {
    try {
        const response = await fetch(`/tracking/api/orders/${orderNumber}`);
        const result = await response.json();
        
        if (result.success && result.data) {
            const order = result.data;
            const notesContainer = document.getElementById('adminDrawerNotesContainer');
            const notesText = document.getElementById('adminDrawerNotesText');
            const editBtn = document.getElementById('adminDrawerEditBtn');
            const customerNameDisplay = document.getElementById('adminDrawerCustomerNameDisplay');
            
            if (notesContainer) {
                notesContainer.dataset.orderNumber = orderNumber;
            }
            
            if (notesText) {
                if (order.notes && order.notes.trim()) {
                    notesText.textContent = order.notes;
                } else {
                    notesText.textContent = '-';
                }
            }
            
            // 更新客户姓名显示
            if (customerNameDisplay) {
                customerNameDisplay.textContent = order.customer_name || '-';
            }
            
            // 显示编辑按钮（只有管理员能看到）
            const isAdmin = isAdminRole();
            if (editBtn) {
                editBtn.style.display = isAdmin ? 'flex' : 'none';
            }
        } else {
            // 如果API失败，尝试从当前表格数据中获取备注
            console.warn('加载订单详情失败，尝试从表格数据获取备注');
            const notesText = document.getElementById('adminDrawerNotesText');
            if (notesText) {
                notesText.textContent = '-';
            }
        }
    } catch (error) {
        console.error('加载订单详情失败:', error);
        const notesText = document.getElementById('adminDrawerNotesText');
        if (notesText) {
            notesText.textContent = '-';
        }
    }
}

/**
 * 关闭管理员订单详情抽屉
 */
function closeAdminDetailDrawer() {
    const overlay = document.getElementById('adminDetailDrawerOverlay');
    const drawer = document.getElementById('adminDetailDrawer');
    
    // 关闭预览
    closeAdminDrawerPreview();
    
    // 清空图片列表
    adminDrawerImageFiles = [];
    adminDrawerCurrentImageIndex = -1;
    adminDrawerImageZoom = 1;
    
    if (overlay) overlay.classList.remove('show');
    if (drawer) drawer.classList.remove('show');
    currentAdminDrawerOrderNumber = null;
}

/**
 * 處理抽屜遮罩層點擊事件
 * 修改為：點擊遮罩層不關閉抽屜
 */
function handleAdminDrawerOverlayClick(event) {
    // 不做任何事情 - 點擊遮罩層不關閉抽屜
    // 只有 ESC 鍵才能關閉抽屜
    return;
}

/**
 * 設置 ESC 鍵關閉抽屜
 */
function setupAdminDrawerEscapeKey() {
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const drawer = document.getElementById('adminDetailDrawer');
            const isDrawerOpen = drawer && drawer.classList.contains('show');
            
            if (isDrawerOpen) {
                // 檢查是否在編輯模式
                const editDiv = document.getElementById('adminDrawerNotesEdit');
                const isEditing = editDiv && editDiv.style.display !== 'none';
                
                if (isEditing) {
                    // 如果在編輯模式,先退出編輯
                    cancelAdminDrawerEdit(null);
                } else {
                    // 如果不在編輯模式,關閉抽屜
                    closeAdminDetailDrawer();
                }
                
                e.preventDefault();
                e.stopPropagation();
            }
        }
    });
}

/**
 * 加载管理员抽屉文件列表
 */
async function loadAdminDrawerFiles(orderNumber) {
    currentAdminDrawerOrderNumber = orderNumber;
    
    // 显示/隐藏上传按钮（只有管理员能看到）
    const isAdmin = isAdminRole();
    const uploadBtn = document.getElementById('adminDrawerUploadBtn');
    if (uploadBtn) {
        uploadBtn.style.display = isAdmin ? 'flex' : 'none';
    }
    
    try {
        const response = await fetch(`/tracking/api/orders/${orderNumber}/files`);
        const result = await response.json();
        
        if (result.success) {
            const files = result.data.files;
            renderAdminDrawerFileList(files);
        } else {
            console.error('加载文件列表失败:', result.error);
            renderAdminDrawerFileList([]);
        }
    } catch (error) {
        console.error('加载文件列表失败:', error);
        renderAdminDrawerFileList([]);
    }
}

// 管理员抽屉图片预览状态
let adminDrawerImageFiles = []; // 所有图片文件列表
let adminDrawerCurrentImageIndex = -1; // 当前图片索引
let adminDrawerImageZoom = 1; // 当前缩放级别
let adminDrawerFullscreenMode = false; // 全屏模式状态

/**
 * 渲染管理员抽屉文件列表
 */
function renderAdminDrawerFileList(files) {
    const fileList = document.getElementById('adminDrawerFileList');
    if (!fileList) return;
    
    if (!files || files.length === 0) {
        fileList.innerHTML = `
            <div class="file-list-empty">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                    <polyline points="13 2 13 9 20 9"></polyline>
                </svg>
                <p>暂无文件</p>
            </div>
        `;
        return;
    }
    
    const isAdmin = isAdminRole();
    
    // 判断文件是否为图片
    const isImageFile = (fileName, mimeType) => {
        if (mimeType && mimeType.startsWith('image/')) return true;
        const ext = fileName.toLowerCase().split('.').pop();
        return ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'].includes(ext);
    };
    
    // 筛选出所有图片文件并存储
    adminDrawerImageFiles = files.filter(file => isImageFile(file.file_name, file.mime_type));
    
    const fileListHTML = files.map(file => {
        const isImage = isImageFile(file.file_name, file.mime_type);
        // 找到图片在图片列表中的索引
        const imageIndex = isImage ? adminDrawerImageFiles.findIndex(img => img.id === file.id) : -1;
        const clickAction = isImage ? `onclick="previewAdminDrawerImage(${imageIndex})"` : '';
        const cursorStyle = isImage ? 'cursor: pointer;' : '';
        
        return `
        <div class="file-item" ${clickAction} style="${cursorStyle}">
            <div class="file-info">
                ${isImage ? `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: #3b82f6;">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                        <circle cx="8.5" cy="8.5" r="1.5"></circle>
                        <polyline points="21 15 16 10 5 21"></polyline>
                    </svg>
                ` : `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                        <polyline points="13 2 13 9 20 9"></polyline>
                    </svg>
                `}
                <span class="file-name" title="${escapeHtml(file.file_name)}">${escapeHtml(file.file_name)}</span>
            </div>
            <div class="file-meta">
                <span class="file-size">${formatFileSize(file.file_size)}</span>
                <span class="file-date">${formatDate(file.uploaded_at)}</span>
            </div>
            <div class="file-actions" onclick="event.stopPropagation()">
                <button class="btn-icon" onclick="downloadAdminDrawerFile(${file.id})" title="下载">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                </button>
                ${isAdmin ? `
                <button class="btn-icon btn-danger" onclick="confirmDeleteAdminDrawerFile(${file.id})" title="删除">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
                ` : ''}
            </div>
        </div>
    `;
    }).join('');
    
    fileList.innerHTML = fileListHTML;
}

// 管理员抽屉上传文件列表
let adminDrawerFiles = [];

/**
 * 打开管理员抽屉上传文件 Modal
 */
function openAdminDrawerUploadModal() {
    if (!currentAdminDrawerOrderNumber) {
        if (typeof showToast === 'function') {
            showToast('错误', '请先选择订单', 'error');
        }
        return;
    }
    
    // 清空文件列表
    adminDrawerFiles = [];
    renderAdminDrawerFiles();
    
    const modal = document.getElementById('adminDrawerUploadModal');
    if (modal) {
        modal.style.display = 'flex';
        setupAdminDrawerFileUpload();
    }
}

/**
 * 设置管理员抽屉文件上传功能
 */
function setupAdminDrawerFileUpload() {
    const fileInput = document.getElementById('adminDrawer-file-input');
    const dropzone = document.getElementById('adminDrawer-file-dropzone');
    const fileList = document.getElementById('adminDrawer-file-list');
    
    // 点击选择文件
    if (fileInput) {
        fileInput.onchange = function(e) {
            if (e.target.files && e.target.files.length > 0) {
                handleAdminDrawerFiles(e.target.files);
                // 创建新的input来重置，允许继续添加文件
                const newInput = fileInput.cloneNode(true);
                fileInput.parentNode.replaceChild(newInput, fileInput);
                setupAdminDrawerFileUpload(); // 重新设置事件
            }
        };
    }
    
    // 拖拽事件
    if (dropzone) {
        dropzone.ondragover = function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('drag-over');
        };
        
        dropzone.ondragleave = function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('drag-over');
        };
        
        dropzone.ondrop = function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('drag-over');
            
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                handleAdminDrawerFiles(e.dataTransfer.files);
            }
        };
        
        // 点击dropzone也可以选择文件（但不要阻止按钮点击）
        dropzone.onclick = function(e) {
            if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
                return;
            }
            const fileInput = document.getElementById('adminDrawer-file-input');
            if (fileInput) fileInput.click();
        };
    }
}

/**
 * 处理管理员抽屉文件
 */
function handleAdminDrawerFiles(files) {
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        // 检查文件类型
        if (file.type.startsWith('image/') || 
            file.type === 'application/pdf' ||
            file.name.endsWith('.doc') || file.name.endsWith('.docx') ||
            file.name.endsWith('.xls') || file.name.endsWith('.xlsx')) {
            
            // 检查是否已存在
            if (!adminDrawerFiles.find(f => f.name === file.name && f.size === file.size)) {
                adminDrawerFiles.push(file);
            }
        }
    }
    renderAdminDrawerFiles();
}

/**
 * 渲染管理员抽屉文件列表
 */
function renderAdminDrawerFiles() {
    const fileList = document.getElementById('adminDrawer-file-list');
    const dropzone = document.getElementById('adminDrawer-file-dropzone');
    const fileCount = document.getElementById('adminDrawer-file-count');
    const fileItems = document.getElementById('adminDrawer-file-items');
    
    if (!fileList || !fileItems) return;
    
    if (adminDrawerFiles.length === 0) {
        fileList.style.display = 'none';
        if (dropzone) {
            dropzone.style.display = 'block';
            dropzone.style.minHeight = '200px';
        }
    } else {
        fileList.style.display = 'block';
        // 保持 dropzone 可见但变小，以便继续拖拽
        if (dropzone) {
            dropzone.style.display = 'block';
            dropzone.style.minHeight = '120px';
            dropzone.style.padding = '1rem';
        }
        
        if (fileCount) fileCount.textContent = adminDrawerFiles.length;
        
        fileItems.innerHTML = adminDrawerFiles.map((file, index) => `
            <div class="file-item" style="display: flex; align-items: center; gap: 0.5rem; padding: 0.75rem; background: white; border: 1px solid #e5e7eb; border-radius: 8px;">
                <div class="file-icon" style="flex-shrink: 0;">
                    ${file.type.startsWith('image/') ? `
                        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: #3b82f6;">
                            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                            <circle cx="8.5" cy="8.5" r="1.5"></circle>
                            <polyline points="21 15 16 10 5 21"></polyline>
                        </svg>
                    ` : `
                        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: #6b7280;">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                            <polyline points="14 2 14 8 20 8"></polyline>
                            <line x1="16" y1="13" x2="8" y2="13"></line>
                            <line x1="16" y1="17" x2="8" y2="17"></line>
                            <polyline points="10 9 9 9 8 9"></polyline>
                        </svg>
                    `}
                </div>
                <div class="file-info" style="flex: 1; min-width: 0; overflow: hidden;">
                    <div class="file-name" style="font-size: 0.875rem; font-weight: 500; color: #374151; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%;" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
                    <div class="file-size" style="font-size: 0.75rem; color: #6b7280; margin-top: 0.25rem;">${formatFileSize(file.size)}</div>
                </div>
                <button type="button" class="btn-icon btn-danger" onclick="removeAdminDrawerFile(${index})" title="移除" style="padding: 0.25rem; flex-shrink: 0;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </div>
        `).join('');
    }
}

/**
 * 移除管理员抽屉文件
 */
function removeAdminDrawerFile(index) {
    adminDrawerFiles.splice(index, 1);
    renderAdminDrawerFiles();
}

/**
 * 清空管理员抽屉文件
 */
function clearAdminDrawerFiles() {
    adminDrawerFiles = [];
    renderAdminDrawerFiles();
}

/**
 * 关闭管理员抽屉上传文件 Modal
 */
function closeAdminDrawerUploadModal() {
    const modal = document.getElementById('adminDrawerUploadModal');
    if (modal) modal.style.display = 'none';
}

/**
 * 提交管理员抽屉上传文件
 */
async function submitAdminDrawerUploadFiles() {
    if (!adminDrawerFiles || adminDrawerFiles.length === 0) {
        if (typeof showToast === 'function') {
            showToast('错误', '请选择文件', 'error');
        }
        return;
    }
    
    // 创建 FormData
    const formData = new FormData();
    for (let i = 0; i < adminDrawerFiles.length; i++) {
        formData.append('files', adminDrawerFiles[i]);
    }
    
    try {
        const response = await fetch(`/tracking/api/orders/${currentAdminDrawerOrderNumber}/files/upload`, {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (typeof showToast === 'function') {
                showToast('成功', result.message || '文件上传成功', 'success');
            }
            // 清空文件列表
            adminDrawerFiles = [];
            renderAdminDrawerFiles();
            closeAdminDrawerUploadModal();
            loadAdminDrawerFiles(currentAdminDrawerOrderNumber);  // 重新加载文件列表
        } else {
            if (typeof showToast === 'function') {
                showToast('上传失败', result.error || '未知错误', 'error');
            }
        }
    } catch (error) {
        console.error('上传文件失败:', error);
        if (typeof showToast === 'function') {
            showToast('错误', '网络错误', 'error');
        }
    }
}

/**
 * 预览管理员抽屉图片
 */
function previewAdminDrawerImage(imageIndex) {
    if (imageIndex < 0 || imageIndex >= adminDrawerImageFiles.length) return;
    
    const preview = document.getElementById('adminDrawerPreview');
    const previewImage = document.getElementById('adminDrawerPreviewImage');
    const drawer = document.getElementById('adminDetailDrawer');
    const counter = document.getElementById('adminDrawerPreviewCounter');
    const prevBtn = document.getElementById('adminDrawerPreviewPrev');
    const nextBtn = document.getElementById('adminDrawerPreviewNext');
    
    if (!preview || !previewImage || !drawer) return;
    
    // 设置当前索引
    adminDrawerCurrentImageIndex = imageIndex;
    adminDrawerImageZoom = 1; // 重置缩放
    
    // 获取当前图片
    const currentImage = adminDrawerImageFiles[imageIndex];
    
    // 设置图片源
    previewImage.src = `/tracking/api/orders/files/${currentImage.id}/download`;
    previewImage.alt = currentImage.file_name || '预览图片';
    previewImage.style.transform = `scale(${adminDrawerImageZoom})`;
    
    // 同步全屏模式的图片
    const fullscreenImage = document.getElementById('adminDrawerPreviewFullscreenImage');
    const fullscreenTitle = document.getElementById('adminDrawerPreviewFullscreenTitle');
    if (fullscreenImage) {
        fullscreenImage.src = `/tracking/api/orders/files/${currentImage.id}/download`;
        fullscreenImage.alt = currentImage.file_name || '全屏预览';
    }
    if (fullscreenTitle) {
        fullscreenTitle.textContent = `${currentImage.file_name} (${imageIndex + 1} / ${adminDrawerImageFiles.length})`;
    }
    
    // 更新计数器
    if (counter) {
        counter.textContent = `${imageIndex + 1} / ${adminDrawerImageFiles.length}`;
    }
    
    // 更新导航按钮状态
    if (prevBtn) {
        prevBtn.style.display = adminDrawerImageFiles.length > 1 ? 'flex' : 'none';
    }
    if (nextBtn) {
        nextBtn.style.display = adminDrawerImageFiles.length > 1 ? 'flex' : 'none';
    }
    
    // 显示预览区域
    preview.style.display = 'flex';
    drawer.classList.add('has-preview');
    
    // 添加键盘事件监听
    document.addEventListener('keydown', handleAdminDrawerPreviewKeyboard);
}

/**
 * 处理预览区域的键盘事件
 */
function handleAdminDrawerPreviewKeyboard(e) {
    const preview = document.getElementById('adminDrawerPreview');
    const fullscreen = document.getElementById('adminDrawerPreviewFullscreen');
    
    // 如果预览区域和全屏都关闭，不处理
    if ((!preview || preview.style.display === 'none') && 
        (!fullscreen || fullscreen.style.display === 'none')) {
        return;
    }
    
    // 如果正在输入，不处理
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    
    switch(e.key) {
        case 'ArrowLeft':
            e.preventDefault();
            prevAdminDrawerImage();
            break;
        case 'ArrowRight':
            e.preventDefault();
            nextAdminDrawerImage();
            break;
        case 'Escape':
            e.preventDefault();
            if (adminDrawerFullscreenMode) {
                toggleAdminDrawerFullscreen();
            } else {
                closeAdminDrawerPreview();
            }
            break;
        case 'f':
        case 'F':
            // F键切换全屏
            if (preview && preview.style.display !== 'none') {
                e.preventDefault();
                toggleAdminDrawerFullscreen();
            }
            break;
    }
}

/**
 * 上一张图片
 */
function prevAdminDrawerImage() {
    if (adminDrawerImageFiles.length === 0) return;
    
    let newIndex = adminDrawerCurrentImageIndex - 1;
    if (newIndex < 0) {
        newIndex = adminDrawerImageFiles.length - 1; // 循环到最后一张
    }
    previewAdminDrawerImage(newIndex);
}

/**
 * 下一张图片
 */
function nextAdminDrawerImage() {
    if (adminDrawerImageFiles.length === 0) return;
    
    let newIndex = adminDrawerCurrentImageIndex + 1;
    if (newIndex >= adminDrawerImageFiles.length) {
        newIndex = 0; // 循环到第一张
    }
    previewAdminDrawerImage(newIndex);
}

/**
 * 全屏预览背景点击处理函数（命名函数，避免重复添加）
 */
function handleFullscreenBackgroundClick(e) {
    const fullscreen = document.getElementById('adminDrawerPreviewFullscreen');
    if (fullscreen && e.target === fullscreen) {
        closeAdminDrawerFullscreen();
    }
}

/**
 * 切换全屏预览
 */
function toggleAdminDrawerFullscreen() {
    const fullscreen = document.getElementById('adminDrawerPreviewFullscreen');
    
    if (!fullscreen) return;
    
    // 如果全屏元素在抽屉内，将其移到 body
    const drawer = document.getElementById('adminDetailDrawer');
    if (drawer && drawer.contains(fullscreen)) {
        document.body.appendChild(fullscreen);
    }
    
    adminDrawerFullscreenMode = !adminDrawerFullscreenMode;
    
    if (adminDrawerFullscreenMode) {
        // 进入全屏模式
        fullscreen.style.display = 'flex';
        // 同步当前图片到全屏
        const currentImage = adminDrawerImageFiles[adminDrawerCurrentImageIndex];
        if (currentImage) {
            const fullscreenImage = document.getElementById('adminDrawerPreviewFullscreenImage');
            const fullscreenTitle = document.getElementById('adminDrawerPreviewFullscreenTitle');
            if (fullscreenImage) {
                fullscreenImage.src = `/tracking/api/orders/files/${currentImage.id}/download`;
            }
            if (fullscreenTitle) {
                fullscreenTitle.textContent = `${currentImage.file_name} (${adminDrawerCurrentImageIndex + 1} / ${adminDrawerImageFiles.length})`;
            }
        }
        // 更新全屏导航按钮
        const fullscreenPrev = document.querySelector('.drawer-preview-fullscreen-nav-left');
        const fullscreenNext = document.querySelector('.drawer-preview-fullscreen-nav-right');
        if (fullscreenPrev) {
            fullscreenPrev.style.display = adminDrawerImageFiles.length > 1 ? 'flex' : 'none';
        }
        if (fullscreenNext) {
            fullscreenNext.style.display = adminDrawerImageFiles.length > 1 ? 'flex' : 'none';
        }
        
        // 添加点击背景关闭功能（使用命名函数，先移除再添加，避免重复）
        fullscreen.removeEventListener('click', handleFullscreenBackgroundClick);
        fullscreen.addEventListener('click', handleFullscreenBackgroundClick);
    } else {
        // 退出全屏模式
        closeAdminDrawerFullscreen();
    }
}

/**
 * 关闭全屏预览
 */
function closeAdminDrawerFullscreen() {
    const fullscreen = document.getElementById('adminDrawerPreviewFullscreen');
    if (fullscreen) {
        fullscreen.style.display = 'none';
        adminDrawerFullscreenMode = false;
        // 移除事件监听器
        fullscreen.removeEventListener('click', handleFullscreenBackgroundClick);
    }
}

/**
 * 关闭管理员抽屉图片预览
 */
function closeAdminDrawerPreview() {
    const preview = document.getElementById('adminDrawerPreview');
    const drawer = document.getElementById('adminDetailDrawer');
    
    // 关闭全屏模式
    closeAdminDrawerFullscreen();
    
    if (preview) preview.style.display = 'none';
    if (drawer) drawer.classList.remove('has-preview');
    
    // 重置状态
    adminDrawerCurrentImageIndex = -1;
    adminDrawerImageZoom = 1;
    
    // 移除键盘事件监听
    document.removeEventListener('keydown', handleAdminDrawerPreviewKeyboard);
}

/**
 * 下载管理员抽屉文件
 */
function downloadAdminDrawerFile(fileId) {
    window.open(`/tracking/api/orders/files/${fileId}/download`, '_blank');
}

/**
 * 确认删除管理员抽屉文件
 */
async function confirmDeleteAdminDrawerFile(fileId) {
    if (typeof window.showConfirmModal === 'function') {
        const confirmed = await window.showConfirmModal(
            '确定要删除此文件吗？此操作无法撤销。',
            '确认删除',
            '删除',
            '取消',
            true
        );
        if (confirmed) {
            deleteAdminDrawerFile(fileId);
        }
    } else {
        if (confirm('确定要删除此文件吗？')) {
            deleteAdminDrawerFile(fileId);
        }
    }
}

/**
 * 删除管理员抽屉文件
 */
async function deleteAdminDrawerFile(fileId) {
    try {
        const response = await fetch(`/tracking/api/orders/files/${fileId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (typeof showToast === 'function') {
                showToast('成功', '文件已删除', 'success');
            }
            loadAdminDrawerFiles(currentAdminDrawerOrderNumber);  // 重新加载列表
        } else {
            if (typeof showToast === 'function') {
                showToast('删除失败', result.error, 'error');
            }
        }
    } catch (error) {
        console.error('删除文件失败:', error);
        if (typeof showToast === 'function') {
            showToast('错误', '网络错误', 'error');
        }
    }
}

/**
 * HTML转义
 */
function escapeHtml(text) {
    if (typeof text !== 'string') return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * 格式化文件大小（如果file-management.js中没有定义）
 */
function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/**
 * 格式化日期（如果file-management.js中没有定义）
 */
function formatDate(dateString) {
    if (!dateString) return '';
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// ==================== 备注编辑功能 ====================

/**
 * 表格中备注的内联编辑功能
 */
function toggleAdminNotesEdit(orderNumber, buttonEl) {
    const notesCell = buttonEl.closest('.order-notes');
    if (!notesCell) return;
    
    const displayDiv = notesCell.querySelector('.notes-display');
    const editDiv = notesCell.querySelector('.notes-edit');
    const textarea = editDiv.querySelector('.notes-input');
    
    if (editDiv.style.display === 'none') {
        // 切换到编辑模式
        displayDiv.style.display = 'none';
        editDiv.style.display = 'block';
        
        // 设置初始值
        const preview = displayDiv.querySelector('.notes-preview');
        if (preview && preview.title) {
            textarea.value = preview.title;
        } else {
            textarea.value = '';
        }
        
        // 聚焦并选中
        setTimeout(() => {
            textarea.focus();
            textarea.select();
        }, 10);
        
        // 添加回车键保存（Ctrl+Enter 或 Cmd+Enter）
        textarea.onkeydown = function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                const saveBtn = editDiv.querySelector('.notes-save-btn');
                if (saveBtn && !saveBtn.disabled) {
                    saveAdminNotes(orderNumber, saveBtn);
                }
            }
            // ESC 取消
            if (e.key === 'Escape') {
                e.preventDefault();
                const cancelBtn = editDiv.querySelector('.notes-cancel-btn');
                if (cancelBtn) {
                    cancelAdminNotesEdit(orderNumber, cancelBtn);
                }
            }
        };
    } else {
        // 切换到显示模式
        editDiv.style.display = 'none';
        displayDiv.style.display = 'block';
    }
}

function saveAdminNotes(orderNumber, buttonEl) {
    const notesCell = buttonEl.closest('.order-notes');
    if (!notesCell) return;
    
    const textarea = notesCell.querySelector('.notes-input');
    const notes = textarea.value.trim();
    const displayDiv = notesCell.querySelector('.notes-display');
    const editDiv = notesCell.querySelector('.notes-edit');
    
    // 禁用按钮，显示加载状态
    buttonEl.disabled = true;
    buttonEl.textContent = '保存中...';
    
    // 调用 API 更新备注
    fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            notes: notes
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            // 更新显示内容
            if (notes) {
                const displayText = notes.length > 30 ? notes.substring(0, 30) + '...' : notes;
                const escapedNotes = escapeHtml(notes);
                const escapedDisplay = escapeHtml(displayText);
                displayDiv.innerHTML = `<span class="notes-preview" title="${escapedNotes}">${escapedDisplay}${notes.length > 30 ? '...' : ''}</span>`;
            } else {
                displayDiv.innerHTML = '<span class="notes-empty">-</span>';
            }
            
            // 恢复按钮状态
            buttonEl.disabled = false;
            buttonEl.textContent = '保存';
            
            // 切换回显示模式
            editDiv.style.display = 'none';
            displayDiv.style.display = 'block';
            
            // 同步更新所有表格中的备注显示（全部订单号、未解锁订单、已解锁订单）
            updateAdminTableNotesAfterSave(orderNumber, notes);
            
            // 同步更新右侧抽屉的备注显示（如果抽屉是打开的）
            if (currentAdminDrawerOrderNumber === orderNumber) {
                updateAdminDrawerNotesAfterSave(notes);
            }
            
            showToast('成功', '備註已保存');
        } else {
            showToast('错误', data.error || '保存失敗');
            buttonEl.disabled = false;
            buttonEl.textContent = '保存';
        }
    })
    .catch(err => {
        console.error('Error saving notes:', err);
        showToast('错误', '網絡錯誤');
        buttonEl.disabled = false;
        buttonEl.textContent = '保存';
    });
}

// ==================== 客戶名稱编辑功能（管理员） ====================
function toggleAdminCustomerEdit(orderNumber, buttonEl) {
    const customerCell = buttonEl.closest('.order-customer');
    if (!customerCell) return;

    const displayDiv = customerCell.querySelector('.customer-display');
    const editDiv = customerCell.querySelector('.customer-edit');
    const input = editDiv.querySelector('.customer-input');
    enforceUppercaseInput(input);

    if (editDiv.style.display === 'none') {
        displayDiv.style.display = 'none';
        editDiv.style.display = 'block';
        setTimeout(() => {
            input.focus();
            input.select();
        }, 10);

        input.onkeydown = function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                const saveBtn = editDiv.querySelector('.notes-save-btn');
                if (saveBtn && !saveBtn.disabled) {
                    saveAdminCustomerName(orderNumber, saveBtn);
                }
            }
            if (e.key === 'Escape') {
                e.preventDefault();
                const cancelBtn = editDiv.querySelector('.notes-cancel-btn');
                if (cancelBtn) {
                    cancelAdminCustomerEdit(orderNumber, cancelBtn);
                }
            }
        };
    } else {
        editDiv.style.display = 'none';
        displayDiv.style.display = 'block';
    }
}

function saveAdminCustomerName(orderNumber, buttonEl) {
    const customerCell = buttonEl.closest('.order-customer');
    if (!customerCell) return;

    const input = customerCell.querySelector('.customer-input');
    const customerName = normalizeCustomerName(input.value);
    input.value = customerName;
    const displayDiv = customerCell.querySelector('.customer-display');
    const editDiv = customerCell.querySelector('.customer-edit');

    buttonEl.disabled = true;
    buttonEl.textContent = '保存中...';

    fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            customer_name: customerName
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            const displayHtml = customerName ?
                `<span class="customer-preview" title="${escapeHtml(customerName)}">${escapeHtml(customerName)}</span>` :
                '<span class="notes-empty">-</span>';
            displayDiv.innerHTML = displayHtml;
            editDiv.style.display = 'none';
            displayDiv.style.display = 'block';
            showToast('客戶名稱已更新', 'success');
        } else {
            showToast(data.error || '更新失敗', 'error');
        }
    })
    .catch(error => {
        console.error('更新客戶名稱失敗:', error);
        showToast('更新失敗', 'error');
    })
    .finally(() => {
        buttonEl.disabled = false;
        buttonEl.textContent = '保存';
    });
}

function cancelAdminCustomerEdit(orderNumber, buttonEl) {
    const customerCell = buttonEl.closest('.order-customer');
    if (!customerCell) return;

    const displayDiv = customerCell.querySelector('.customer-display');
    const editDiv = customerCell.querySelector('.customer-edit');
    const preview = displayDiv.querySelector('.customer-preview');
    const input = editDiv.querySelector('.customer-input');

    if (preview && preview.title) {
        input.value = preview.title;
    } else {
        input.value = '';
    }
    editDiv.style.display = 'none';
    displayDiv.style.display = 'block';
}

function cancelAdminNotesEdit(orderNumber, buttonEl) {
    const notesCell = buttonEl.closest('.order-notes');
    if (!notesCell) return;
    
    const displayDiv = notesCell.querySelector('.notes-display');
    const editDiv = notesCell.querySelector('.notes-edit');
    const textarea = editDiv.querySelector('.notes-input');
    const saveBtn = editDiv.querySelector('.notes-save-btn');
    
    // 恢复原始值
    const preview = displayDiv.querySelector('.notes-preview');
    if (preview && preview.title) {
        textarea.value = preview.title;
    } else {
        textarea.value = '';
    }
    
    // 恢复按钮状态
    if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存';
    }
    
    // 切换回显示模式
    editDiv.style.display = 'none';
    displayDiv.style.display = 'block';
}

/**
 * 抽屉编辑模式（同时编辑客户姓名和备注）
 */
function toggleAdminDrawerEditMode(buttonEl) {
    const notesContainer = document.getElementById('adminDrawerNotesContainer');
    if (!notesContainer) return;
    
    const orderNumber = notesContainer.dataset.orderNumber;
    if (!orderNumber) return;
    
    const displayDiv = document.getElementById('adminDrawerNotesDisplay');
    const editDiv = document.getElementById('adminDrawerNotesEdit');
    const textarea = document.getElementById('adminDrawerNotesInput');
    const customerNameDisplay = document.getElementById('adminDrawerCustomerNameDisplay');
    const customerNameInput = document.getElementById('adminDrawerCustomerNameInput');
    enforceUppercaseInput(customerNameInput);
    
    if (editDiv.style.display === 'none') {
        // 切换到编辑模式
        displayDiv.style.display = 'none';
        editDiv.style.display = 'block';
        
        // 显示客户姓名输入框
        if (customerNameDisplay && customerNameInput) {
            customerNameDisplay.style.display = 'none';
            customerNameInput.style.display = 'block';
            customerNameInput.value = customerNameDisplay.textContent === '-' ? '' : customerNameDisplay.textContent;
        }
        
        // 设置备注初始值
        const notesText = document.getElementById('adminDrawerNotesText');
        if (notesText && notesText.textContent !== '-') {
            textarea.value = notesText.textContent;
        } else {
            textarea.value = '';
        }
        
        // 聚焦到客户姓名输入框
        setTimeout(() => {
            if (customerNameInput) {
                customerNameInput.focus();
                customerNameInput.select();
            }
        }, 10);
        
        // 添加回车键保存（Ctrl+Enter 或 Cmd+Enter）
        const handleKeyDown = function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                const saveBtn = editDiv.querySelector('.notes-save-btn');
                if (saveBtn && !saveBtn.disabled) {
                    saveAdminDrawerAll(saveBtn);
                }
            }
            // ESC 取消
            if (e.key === 'Escape') {
                e.preventDefault();
                const cancelBtn = editDiv.querySelector('.notes-cancel-btn');
                if (cancelBtn) {
                    cancelAdminDrawerEdit(cancelBtn);
                }
            }
        };
        
        if (customerNameInput) {
            customerNameInput.onkeydown = handleKeyDown;
        }
        textarea.onkeydown = handleKeyDown;
        
        // 更新按钮文本
        if (buttonEl) {
            buttonEl.textContent = '取消编辑';
        }
    } else {
        // 切换到显示模式
        cancelAdminDrawerEdit(null);
    }
}

/**
 * 抽屉备注内联编辑功能（保留用于兼容）
 */
function toggleAdminDrawerNotesEdit(buttonEl) {
    toggleAdminDrawerEditMode(buttonEl);
}

/**
 * 保存客户姓名和备注
 */
function saveAdminDrawerAll(buttonEl) {
    const notesContainer = document.getElementById('adminDrawerNotesContainer');
    if (!notesContainer) return;
    
    const orderNumber = notesContainer.dataset.orderNumber;
    if (!orderNumber) return;
    
    const textarea = document.getElementById('adminDrawerNotesInput');
    const notes = textarea ? textarea.value.trim() : '';
    const customerNameInput = document.getElementById('adminDrawerCustomerNameInput');
    const customerName = normalizeCustomerName(customerNameInput ? customerNameInput.value : '');
    if (customerNameInput) customerNameInput.value = customerName;
    
    const displayDiv = document.getElementById('adminDrawerNotesDisplay');
    const editDiv = document.getElementById('adminDrawerNotesEdit');
    const notesText = document.getElementById('adminDrawerNotesText');
    const customerNameDisplay = document.getElementById('adminDrawerCustomerNameDisplay');
    const editBtn = document.getElementById('adminDrawerEditBtn');
    
    // 禁用按钮，显示加载状态
    if (buttonEl) {
        buttonEl.disabled = true;
        buttonEl.textContent = '保存中...';
    }
    
    // 调用 API 同时更新客户姓名和备注
    fetch(`/tracking/api/orders/${encodeURIComponent(orderNumber)}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            customer_name: customerName,
            notes: notes
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            // 更新备注显示
            if (notesText) {
                if (notes) {
                    notesText.textContent = notes;
                } else {
                    notesText.textContent = '-';
                }
            }
            
            // 更新客户姓名显示
            if (customerNameDisplay) {
                customerNameDisplay.textContent = customerName || '-';
            }
            
            // 恢复按钮状态
            if (buttonEl) {
                buttonEl.disabled = false;
                buttonEl.textContent = '保存';
            }
            if (editBtn) {
                editBtn.textContent = '编辑';
            }
            
            // 切换回显示模式
            if (editDiv) editDiv.style.display = 'none';
            if (displayDiv) displayDiv.style.display = 'block';
            if (customerNameDisplay) customerNameDisplay.style.display = 'inline';
            if (customerNameInput) customerNameInput.style.display = 'none';
            
            // 同步更新主表格中对应行的备注和客户姓名显示
            updateAdminTableNotesAfterSave(orderNumber, notes);
            updateAdminTableCustomerNameAfterSave(orderNumber, customerName);
            
            showToast('成功', '已保存');
        } else {
            showToast('错误', data.error || '保存失敗');
            if (buttonEl) {
                buttonEl.disabled = false;
                buttonEl.textContent = '保存';
            }
        }
    })
    .catch(err => {
        console.error('Error saving drawer data:', err);
        showToast('错误', '網絡錯誤');
        if (buttonEl) {
            buttonEl.disabled = false;
            buttonEl.textContent = '保存';
        }
    });
}

/**
 * 保存备注（保留用于兼容）
 */
function saveAdminDrawerNotes(buttonEl) {
    saveAdminDrawerAll(buttonEl);
}

/**
 * 取消编辑（客户姓名和备注）
 */
function cancelAdminDrawerEdit(buttonEl) {
    const notesContainer = document.getElementById('adminDrawerNotesContainer');
    if (!notesContainer) return;
    
    const displayDiv = document.getElementById('adminDrawerNotesDisplay');
    const editDiv = document.getElementById('adminDrawerNotesEdit');
    const textarea = document.getElementById('adminDrawerNotesInput');
    const saveBtn = editDiv ? editDiv.querySelector('.notes-save-btn') : null;
    const customerNameDisplay = document.getElementById('adminDrawerCustomerNameDisplay');
    const customerNameInput = document.getElementById('adminDrawerCustomerNameInput');
    const editBtn = document.getElementById('adminDrawerEditBtn');
    
    // 恢复备注原始值
    const notesText = document.getElementById('adminDrawerNotesText');
    if (textarea) {
        if (notesText && notesText.textContent !== '-') {
            textarea.value = notesText.textContent;
        } else {
            textarea.value = '';
        }
    }
    
    // 恢复客户姓名原始值
    if (customerNameInput && customerNameDisplay) {
        customerNameInput.value = customerNameDisplay.textContent === '-' ? '' : customerNameDisplay.textContent;
    }
    
    // 恢复按钮状态
    if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存';
    }
    if (editBtn) {
        editBtn.textContent = '编辑';
    }
    
    // 切换回显示模式
    if (editDiv) editDiv.style.display = 'none';
    if (displayDiv) displayDiv.style.display = 'block';
    if (customerNameDisplay) customerNameDisplay.style.display = 'inline';
    if (customerNameInput) customerNameInput.style.display = 'none';
}

/**
 * 取消备注编辑（保留用于兼容）
 */
function cancelAdminDrawerNotesEdit(buttonEl) {
    cancelAdminDrawerEdit(buttonEl);
}

/**
 * 更新所有表格中对应行的备注显示（同步更新全部订单号、未解锁订单、已解锁订单三个表格）
 */
function updateAdminTableNotesAfterSave(orderNumber, notes) {
    // 更新所有表格中的备注（使用统一的 .order-notes 选择器）
    const allNotesCells = document.querySelectorAll(`.order-notes[data-order-number="${orderNumber}"]`);
    
    allNotesCells.forEach(notesCell => {
        const displayDiv = notesCell.querySelector('.notes-display');
        if (displayDiv) {
            if (notes) {
                const displayText = notes.length > 30 ? notes.substring(0, 30) + '...' : notes;
                const escapedNotes = escapeHtml(notes);
                const escapedDisplay = escapeHtml(displayText);
                displayDiv.innerHTML = `<span class="notes-preview" title="${escapedNotes}">${escapedDisplay}${notes.length > 30 ? '...' : ''}</span>`;
            } else {
                displayDiv.innerHTML = '<span class="notes-empty">-</span>';
            }
        }
    });
}

/**
 * 更新所有表格中对应行的客户姓名显示（同步更新全部订单号、未解锁订单、已解锁订单三个表格）
 */
function updateAdminTableCustomerNameAfterSave(orderNumber, customerName) {
    const customerNameText = customerName || '-';
    
    // 更新全部订单号表格（客户名称在第3列，索引为2）
    const allRows = document.querySelectorAll('#all-orders-table-body tr');
    allRows.forEach(row => {
        const checkbox = row.querySelector('.order-checkbox');
        if (checkbox && checkbox.value === orderNumber) {
            const cells = row.querySelectorAll('td');
            if (cells.length > 2) {
                cells[2].textContent = customerNameText;
            }
        }
    });
    
    // 更新未解锁订单表格（客户名称在第3列，索引为2）
    const unlockedRows = document.querySelectorAll('#unlocked-table-body tr');
    unlockedRows.forEach(row => {
        const checkbox = row.querySelector('.unlocked-checkbox');
        if (checkbox && checkbox.value === orderNumber) {
            const cells = row.querySelectorAll('td');
            if (cells.length > 2) {
                cells[2].textContent = customerNameText;
            }
        }
    });
    
    // 更新已解锁订单表格（客户名称在第3列，索引为2）
    const lockedRows = document.querySelectorAll('#locked-table-body tr');
    lockedRows.forEach(row => {
        const checkbox = row.querySelector('.locked-checkbox');
        if (checkbox && checkbox.value === orderNumber) {
            const cells = row.querySelectorAll('td');
            if (cells.length > 2) {
                cells[2].textContent = customerNameText;
            }
        }
    });
}

/**
 * 更新抽屉中的备注显示（从表格保存后）
 */
function updateAdminDrawerNotesAfterSave(notes) {
    const notesText = document.getElementById('adminDrawerNotesText');
    if (notesText) {
        if (notes) {
            notesText.textContent = notes;
        } else {
            notesText.textContent = '-';
        }
    }
}


// 掛載到全局
window.loadSkipNumbers = loadSkipNumbers;
window.openAddSkipModal = openAddSkipModal;
window.addSkipNumbers = addSkipNumbers;
window.deleteSingleSkip = deleteSingleSkip;
window.batchDeleteSkip = batchDeleteSkip;
window.toggleAllSkip = toggleAllSkip;
window.handleSkipSearch = handleSkipSearch;
window.removeSkip = removeSkip;
// setPoolPageSize 已删除，改用 setAllOrdersPageSize
window.setSkipPageSize = setSkipPageSize;
window.openAdminDetailDrawer = openAdminDetailDrawer;
window.closeAdminDetailDrawer = closeAdminDetailDrawer;
window.updateAdminDrawerContent = updateAdminDrawerContent;
window.handleAdminDrawerOverlayClick = handleAdminDrawerOverlayClick;
window.openAdminDrawerUploadModal = openAdminDrawerUploadModal;
window.closeAdminDrawerUploadModal = closeAdminDrawerUploadModal;
window.submitAdminDrawerUploadFiles = submitAdminDrawerUploadFiles;
window.clearAdminDrawerFiles = clearAdminDrawerFiles;
window.removeAdminDrawerFile = removeAdminDrawerFile;
window.previewAdminDrawerImage = previewAdminDrawerImage;
window.closeAdminDrawerPreview = closeAdminDrawerPreview;
window.prevAdminDrawerImage = prevAdminDrawerImage;
window.nextAdminDrawerImage = nextAdminDrawerImage;
window.toggleAdminDrawerFullscreen = toggleAdminDrawerFullscreen;
window.closeAdminDrawerFullscreen = closeAdminDrawerFullscreen;
window.downloadAdminDrawerFile = downloadAdminDrawerFile;
window.confirmDeleteAdminDrawerFile = confirmDeleteAdminDrawerFile;
