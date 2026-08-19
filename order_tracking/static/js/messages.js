/* ===== 报价邮箱 JS ===== */
'use strict';

let _allMessages  = [];
let _currentView  = 'all';
let _currentMsgId = null;
let _currentMsg   = null;
let _quill        = null;
let _pendingFiles = [];
let _isAdmin      = false;
let _filterMode   = '';       // ''|'unread'|'hasatt'|'sent'
let _currentPage  = 1;
let _hasMore      = false;
let _sortBy       = 'date';   // 'date'|'sender'|'subject'|'order'
let _sortOrder    = 'desc';   // 'desc'|'asc'

// ── 初始化 ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const role = document.body.dataset.rawRole || '';
    _isAdmin = ['admin','administrator','root','superuser','管理员','主管']
                .includes(role.toLowerCase());

    if (_isAdmin) {
        const el = document.getElementById('siUnread');
        if (el) el.style.display = '';
        ['siToday','siBatchDivider','siBatchPrint'].forEach(id => {
            const e = document.getElementById(id);
            if (e) e.style.display = '';
        });
    } else {
        // 業務員：預設切到「已發送」視圖，隱藏收件箱和未讀
        switchView('sent', document.querySelector('.msg-si[data-view="sent"]'));
        // 隱藏主管才需要的側邊欄項目
        const allItem = document.querySelector('.msg-si[data-view="all"]');
        if (allItem) allItem.style.display = 'none';
        // 隱藏篩選工具列的未讀選項
        document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'none');
    }

    initQuill();
    initResizers();
    _loadPresetRecipients().then(() => {
        _renderComposePrsetBtns();
    });
    loadMessages();
});

// ── Quill 初始化 ─────────────────────────────────────────
function initQuill() {
    if (typeof Quill === 'undefined') return;

    const Size = Quill.import('attributors/style/size');
    Size.whitelist = ['12px','14px','16px','18px','20px','24px','28px','32px'];
    Quill.register(Size, true);

    _quill = new Quill('#cEditor', {
        theme: 'snow',
        placeholder: '輸入报价内容...',
        modules: {
            toolbar: {
                container: [
                    ['bold', 'italic', 'underline', 'strike'],
                    [{ color: [] }, { background: [] }],
                    [{ size: ['12px','14px','16px','18px','20px','24px','28px','32px'] }],
                    [{ list: 'ordered' }, { list: 'bullet' }],
                    ['image', 'clean']
                ],
                handlers: { image: _imageHandler }
            }
        }
    });

    // 預設字體大小 20px（或上次記住的設定）
    const savedSize = localStorage.getItem('msg_quill_size') || '20px';
    _quill.format('size', savedSize);

    // 記住每次選擇的字體大小
    _quill.on('selection-change', (range) => {
        if (range) {
            const format = _quill.getFormat(range);
            if (format.size) localStorage.setItem('msg_quill_size', format.size);
        }
    });
}

function _imageHandler() {
    const input = document.createElement('input');
    input.type   = 'file';
    input.accept = 'image/*';
    input.click();
    input.onchange = () => {
        const file = input.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = e => {
            const range = _quill.getSelection(true);
            _quill.insertEmbed(range.index, 'image', e.target.result);
        };
        reader.readAsDataURL(file);
    };
}

// ── 載入报价列表 ──────────────────────────────────────────
async function loadMessages(reset = true) {
    if (reset) { _currentPage = 1; _allMessages = []; }
    showLoading(true);
    try {
        const url = `/tracking/api/messages/inbox?page=${_currentPage}&per_page=50`;
        const res  = await fetch(url);
        if (!res.ok) throw new Error('加载失败');
        const data = await res.json();
        if (!data.success) throw new Error(data.error || '加载失败');
        if (reset) {
            _allMessages = data.messages || [];
        } else {
            _allMessages = [..._allMessages, ...(data.messages || [])];
        }
        _hasMore = data.has_more || false;
        updateBadges(data.unread_count || 0);
        _buildDateFilter();
        _buildSenderFilter();
        renderList();
    } catch (e) {
        console.error('[messages]', e);
        showLoading(false);
    }
}

async function loadMore() {
    if (!_hasMore) return;
    _currentPage++;
    await loadMessages(false);
}

// 從郵件列表提取所有日期，填充下拉選單
function _buildDateFilter() {
    const sel = document.getElementById('msgDateFilter');
    if (!sel) return;
    const todayObj = new Date();
    const todayStr = `${todayObj.getFullYear()}-${String(todayObj.getMonth()+1).padStart(2,'0')}-${String(todayObj.getDate()).padStart(2,'0')}`;
    const dateCounts = {};
    _allMessages.forEach(m => {
        const d  = new Date(m.created_at.replace(' ','T'));
        const ds = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
        dateCounts[ds] = (dateCounts[ds]||0) + 1;
    });
    const currentVal = sel.value;
    const dates = Object.keys(dateCounts).sort((a,b) => b.localeCompare(a));
    sel.innerHTML = '<option value="">全部日期</option>' +
        dates.map(ds => {
            const label = ds === todayStr ? `今天（${dateCounts[ds]}封）` : `${ds}（${dateCounts[ds]}封）`;
            return `<option value="${ds}">${label}</option>`;
        }).join('');
    if (currentVal) sel.value = currentVal;
}

function showLoading(show) {
    const el = document.getElementById('msgListLoading');
    if (el) el.style.display = show ? 'flex' : 'none';
}

function updateBadges(n) {
    ['siBadgeAll','siBadgeUnread'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent   = n;
        el.style.display = n > 0 ? '' : 'none';
    });
}

// ── 切換視圖 ──────────────────────────────────────────────
function switchView(view, el) {
    _currentView = view;
    document.querySelectorAll('.msg-si').forEach(s => s.classList.remove('active'));
    if (el) el.classList.add('active');
    const titles = { all:'收件箱', sent:'已发送', unread:'未读' };
    const t = document.getElementById('msgListTitle');
    if (t) t.textContent = titles[view] || '报价';
    renderList();
}

function filterList() { renderList(); }

function getFiltered() {
    const q = (document.getElementById('msgSearch')?.value || '').toLowerCase();

    let msgs = _allMessages.filter(m => {
        // 側邊欄視圖
        if (_currentView === 'sent'   && !m.is_own)  return false;
        if (_currentView === 'unread' && m.is_read)  return false;
        if (_currentView === 'today') {
            const d  = new Date(m.created_at.replace(' ','T'));
            const ds = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
            const t  = new Date();
            const ts = `${t.getFullYear()}-${String(t.getMonth()+1).padStart(2,'0')}-${String(t.getDate()).padStart(2,'0')}`;
            if (ds !== ts) return false;
        }
        // 工具列篩選
        if (_filterMode === 'unread'  && m.is_read)          return false;
        if (_filterMode === 'hasatt'  && !m.has_attachments)  return false;
        if (_filterMode === 'flagged' && !m.is_flagged)        return false;
        if (_filterMode === 'pinned'  && !m.is_pinned)         return false;
        if (_filterMode.startsWith('sender:')) {
            const name = _filterMode.replace('sender:','');
            if (m.sender_name !== name) return false;
        }
        // 搜索
        if (q) {
            const hay = [m.sender_name, m.subject, m.body_preview,
                         m.order_number, m.customer_name].join(' ').toLowerCase();
            if (!hay.includes(q)) return false;
        }
        return true;
    });

    // 排序
    msgs.sort((a, b) => {
        // 置頂永遠排最前（每個用戶自己的置頂）
        if (a.is_pinned !== b.is_pinned) return b.is_pinned - a.is_pinned;

        let va, vb;
        switch (_sortBy) {
            case 'sender':  va = (a.sender_name||'').toLowerCase(); vb = (b.sender_name||'').toLowerCase(); break;
            case 'subject': va = (a.subject||'').toLowerCase();     vb = (b.subject||'').toLowerCase();     break;
            case 'order':   va = (a.order_number||'').toLowerCase(); vb = (b.order_number||'').toLowerCase(); break;
            default:        va = a.created_at; vb = b.created_at; break;
        }
        const cmp = va < vb ? -1 : va > vb ? 1 : 0;
        return _sortOrder === 'asc' ? cmp : -cmp;
    });

    return msgs;
}

// ── 篩選/排序菜單 ─────────────────────────────────────────
function toggleFilterMenu(e) {
    e.stopPropagation();
    const m = document.getElementById('msgFilterMenu');
    const s = document.getElementById('msgSortMenu');
    s.style.display = 'none';
    m.style.display = m.style.display === 'none' ? '' : 'none';
}
function toggleSortMenu(e) {
    e.stopPropagation();
    const m = document.getElementById('msgSortMenu');
    const f = document.getElementById('msgFilterMenu');
    f.style.display = 'none';
    m.style.display = m.style.display === 'none' ? '' : 'none';
}
document.addEventListener('click', () => {
    document.getElementById('msgFilterMenu')?.style && (document.getElementById('msgFilterMenu').style.display = 'none');
    document.getElementById('msgSortMenu')?.style   && (document.getElementById('msgSortMenu').style.display   = 'none');
});

function setFilter(val, el) {
    _filterMode = val;
    document.querySelectorAll('#msgFilterMenu .msg-dropdown-item[data-filter]').forEach(i => i.classList.remove('active'));
    if (el) el.classList.add('active');
    const labels = {''        : '筛选器',
                    'unread'  : '未读',
                    'hasatt'  : '带附件',
                    'flagged' : '已标记',
                    'pinned'  : '已置顶'};
    // 如果是發件人篩選
    if (val.startsWith('sender:')) {
        const name = val.replace('sender:','');
        document.getElementById('msgFilterLabel').textContent = name;
    } else {
        document.getElementById('msgFilterLabel').textContent = labels[val] || '筛选器';
    }
    document.getElementById('msgFilterMenu').style.display = 'none';
    renderList();
}

// 主管專用：建立發件人篩選列表
function _buildSenderFilter() {
    if (!_isAdmin) return;
    const section = document.getElementById('filterSenderSection');
    const list    = document.getElementById('filterSenderList');
    if (!section || !list) return;

    // 取所有發件人（去重）
    const senders = {};
    _allMessages.forEach(m => {
        if (m.sender_name) senders[m.sender_name] = (senders[m.sender_name]||0) + 1;
    });
    const names = Object.keys(senders).sort();
    if (!names.length) return;

    section.style.display = '';
    list.style.display    = '';
    list.innerHTML = names.map(name =>
        `<div class="msg-dropdown-item" data-filter="sender:${name}"
              onclick="setFilter('sender:${name.replace(/'/g,"\\'")}',this)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            ${name}
            <span style="margin-left:auto;font-size:.68rem;color:#aaa;">${senders[name]}</span>
        </div>`
    ).join('');

    // 顯示主管專用項目
    document.querySelectorAll('.admin-only').forEach(el => el.style.display = '');
}

function setSort(val, el) {
    _sortBy = val;
    document.querySelectorAll('#msgSortMenu .msg-dropdown-item[data-sort]').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
    _updateSortLabel();
    renderList();
}

function setSortOrder(val, el) {
    _sortOrder = val;
    document.querySelectorAll('#msgSortMenu .msg-dropdown-item[data-order]').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
    _updateSortLabel();
    document.getElementById('msgSortMenu').style.display = 'none';
    renderList();
}

function _updateSortLabel() {
    const sortLabels = {date:'日期', sender:'发件人', subject:'主题', order:'订单'};
    const orderLabel = _sortOrder === 'asc' ? '↑' : '↓';
    document.getElementById('msgSortLabel').textContent =
        `${sortLabels[_sortBy]||'日期'} ${orderLabel}`;
}

// ── 渲染列表 ──────────────────────────────────────────────
function renderList() {
    showLoading(false);
    const body  = document.getElementById('msgListBody');
    const empty = document.getElementById('msgListEmpty');
    if (!body || !empty) return;
    const msgs = getFiltered();

    if (!msgs.length) {
        body.innerHTML = '';
        body.appendChild(empty);
        empty.style.display = '';
        return;
    }
    empty.style.display = 'none';
    [...body.children].forEach(c => { if (c !== empty) c.remove(); });

    msgs.forEach(m => {
        const el = document.createElement('div');
        el.className = 'msg-item'
            + (!m.is_read && !m.is_own ? ' unread' : '')
            + (m.id === _currentMsgId ? ' active' : '')
            + (m.is_flagged ? ' flagged-item' : '')
            + (m.is_pinned  ? ' pinned-item'  : '');        el.dataset.id = m.id;
        const t = formatTime(m.created_at);
        const orderChip = m.customer_name
            ? `<div class="msg-item-chip">
                 <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
                 ${_e(m.customer_name)}
               </div>`
            : (m.order_number
                ? `<div class="msg-item-chip"><svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg> ${_e(m.order_number)}</div>`
                : `<div class="msg-item-chip msg-item-chip-free">自由报价</div>`);
        // 用函數生成 HTML，避免嵌套 template literal
        function _buildMiRow(m, t, isAdmin) {
            const clip = m.has_attachments
                ? '<svg class="mi-ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#bbb" stroke-width="2" title="有附件"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>'
                : '<span style="width:12px;display:inline-block;"></span>';
            const flag = '<button class="mi-btn mi-flag ' + (m.is_flagged?'on':'') + '" title="' + (m.is_flagged?'取消标记':'标记') + '" onclick="event.stopPropagation();toggleFlag(' + m.id + ')">'
                + '<svg width="15" height="15" viewBox="0 0 24 24" fill="' + (m.is_flagged?'#ff2442':'none') + '" stroke="' + (m.is_flagged?'#ff2442':'#ccc') + '" stroke-width="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg></button>';
            const pin = '<button class="mi-btn mi-pin ' + (m.is_pinned?'on':'') + '" title="' + (m.is_pinned?'取消置顶':'置顶') + '" onclick="event.stopPropagation();togglePin(' + m.id + ')">'
                + '<svg width="15" height="15" viewBox="0 0 24 24" fill="' + (m.is_pinned?'#ff2442':'none') + '" stroke="' + (m.is_pinned?'#ff2442':'#ccc') + '" stroke-width="2"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 00-1.11-1.79l-1.78-.9A2 2 0 0115 10.76V6h1a2 2 0 000-4H8a2 2 0 000 4h1v4.76a2 2 0 01-1.11 1.79l-1.78.9A2 2 0 005 15.24V17z"/></svg></button>';
            const readBtn = '<button class="mi-btn mi-read" title="' + (m.is_read?'标记为未读':'标记为已读') + '" onclick="event.stopPropagation();' + (m.is_read?'markUnread':'markRead') + '(' + m.id + ')">'
                + '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="' + (m.is_read?'#bbb':'#ff2442') + '" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg></button>';
            return '<div class="mi-row">' + clip + flag + pin + readBtn + '<span class="msg-item-time">' + t + '</span></div>';
        }

        el.innerHTML =
            '<div class="msg-item-row1">'
            +   (!m.is_read && !m.is_own ? '<div class="msg-item-unread-dot"></div>' : '')
            +   '<span class="msg-item-sender">' + _e(m.sender_name) + '</span>'
            +   _buildMiRow(m, t, _isAdmin)
            + '</div>'
            + '<div class="msg-item-subject">' + _e(m.subject || '（无主题）') + '</div>'
            + '<div class="msg-item-preview">' + _e(m.body_preview) + '</div>'
            + orderChip;
        el.addEventListener('click', () => selectMessage(m));
        body.appendChild(el);
    });

    // 顯示/隱藏「加載更多」
    const loadMoreBtn = document.getElementById('msgLoadMore');
    if (loadMoreBtn) loadMoreBtn.style.display = _hasMore ? '' : 'none';
}

// ── 選擇並顯示报价（閱讀模式） ───────────────────────────
async function selectMessage(m) {
    _currentMsgId = m.id;
    _currentMsg   = m;

    document.querySelectorAll('.msg-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.id) === m.id);
    });

    // 點開自動標記已讀（每個用戶獨立，用 user_prefs）
    if (!m.is_read) {
        fetch(`/tracking/api/messages/${m.id}/read`, { method:'POST' }).catch(()=>{});
        m.is_read = true;
        document.querySelector(`.msg-item[data-id="${m.id}"] .msg-item-unread-dot`)?.remove();
        _refreshNavBadge();
    }

    showPanel('read');

    // 取完整报价（含附件）
    try {
        // 用單筆 API 取完整資料（含附件）
        const res  = await fetch(`/tracking/api/messages/${m.id}/detail`);
        if (res.ok) {
            const data = await res.json();
            if (data.success && data.message) {
                renderReadView(data.message);
                return;
            }
        }
        // fallback：從订单列表取
        if (m.order_number) {
            const res2  = await fetch(`/tracking/api/orders/${m.order_number}/messages`);
            const data2 = await res2.json();
            const full  = (data2.messages || []).find(x => x.id === m.id) || m;
            renderReadView(full);
        } else {
            renderReadView(m);
        }
    } catch (e) {
        renderReadView(m);
    }
}

function renderReadView(m) {
    _set('rdSubject', m.subject || '（無主题）');
    _set('rdAvatar',  (m.sender_name||'?')[0].toUpperCase());
    document.getElementById('rdFrom').innerHTML = `<strong>${_e(m.sender_name)}</strong>`;
    _set('rdTime', formatDateTime(m.created_at));
    // 收件人：顯示已發送對象，未發送則隱藏
    const toValEl = document.getElementById('rdToVal');
    const toRowEl = toValEl ? toValEl.closest('.msg-read-to-row') : null;
    if (toValEl) {
        if (m.smtp_sent_to) {
            toValEl.textContent = m.smtp_sent_to;
            if (toRowEl) toRowEl.style.display = '';
        } else {
            toValEl.textContent = '';
            if (toRowEl) toRowEl.style.display = 'none';
        }
    }

    // 订单標籤
    const chip = document.getElementById('rdOrderChip');
    if (m.order_number) {
        document.getElementById('rdOrderNum').textContent = m.order_number;
        document.getElementById('rdCustomer').textContent = m.customer_name ? '· '+m.customer_name : '';
        chip.dataset.orderNum = m.order_number;
        chip.style.display = '';
    } else {
        chip.style.display = 'none';
    }

    document.getElementById('rdBody').innerHTML = m.body || '';

    // 附件
    // 附件 - Outlook 风格（正文上方）
    const attsBox  = document.getElementById('rdAtts');
    const attsList = document.getElementById('rdAttList');
    const attCount = document.getElementById('rdAttCount');
    if (m.attachments?.length) {
        const totalSize = m.attachments.reduce((s,a) => s+(a.size||0), 0);
        if (attCount) attCount.textContent = `${m.attachments.length} 个附件（${fmtSize(totalSize)}）`;
        attsList.innerHTML = '<div class="msg-att-list">' + m.attachments.map(a => {
            const isImg = (a.mime||'').startsWith('image/');
            const url   = `/tracking/api/messages/files/${a.id}/download`;
            if (isImg) {
                return `<a class="msg-att-img-card" href="${url}" target="_blank">
                    <img src="${url}" alt="${_e(a.filename)}" loading="lazy">
                    <div class="att-img-name">${_e(a.filename)}</div>
                </a>`;
            }
            const ext = (a.filename||'').split('.').pop().toLowerCase();
            const iconColor = ext==='pdf' ? '#e53e3e'
                : (ext==='xlsx'||ext==='xls') ? '#38a169'
                : (ext==='docx'||ext==='doc') ? '#3182ce'
                : '#718096';
            return `<a class="msg-att-file-card" href="${url}" target="_blank">
                <div class="att-file-icon">
                    <svg width="28" height="32" viewBox="0 0 24 28" xmlns="http://www.w3.org/2000/svg">
                        <rect width="24" height="28" rx="3" fill="${iconColor}" opacity=".15"/>
                        <text x="12" y="19" text-anchor="middle" font-size="8" font-weight="700" fill="${iconColor}">${ext.toUpperCase()}</text>
                    </svg>
                </div>
                <div class="att-file-info">
                    <div class="att-file-name">${_e(a.filename)}</div>
                    <div class="att-file-size">${fmtSize(a.size)}</div>
                </div>
                <div class="att-file-dl">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                </div>
            </a>`;
        }).join('') + '</div>';
        attsBox.style.display = '';
    } else {
        attsBox.style.display = 'none';
    }

    // 删除按鈕
    const delBtn  = document.getElementById('rdDelBtn');
    const delHint = document.getElementById('rdDelHint');
    if (m.can_delete) {
        delBtn.style.display = '';
        delHint.textContent  = _isAdmin
            ? '主管可永久删除（需輸入 DELETE 確認）'
            : `可在 ${formatDateTime(m.delete_deadline)} 前删除（发送後5分鐘內）`;
        delHint.style.display = '';
    } else {
        delBtn.style.display  = 'none';
        delHint.style.display = 'none';
    }
}

// ── 面板切換 ─────────────────────────────────────────────
function showPanel(mode) {
    // mode: 'empty' | 'read' | 'compose'
    document.getElementById('msgMainEmpty').style.display   = mode === 'empty'   ? '' : 'none';
    document.getElementById('msgReadView').style.display    = mode === 'read'    ? 'flex' : 'none';
    document.getElementById('msgComposeView').style.display = mode === 'compose' ? 'flex' : 'none';
}

// ── 撰寫模式 ─────────────────────────────────────────────
function switchToCompose(orderNumber, customerName) {
    showPanel('compose');

    // 重置欄位
    if (_quill) {
        _quill.setContents([]);
        // 套用上次記住的字體大小
        const savedSize = localStorage.getItem('msg_quill_size') || '20px';
        _quill.format('size', savedSize);
    }
    _pendingFiles = [];
    renderFilePrev();

    const orderInput = document.getElementById('cOrderInput');
    const orderNum   = document.getElementById('cOrderNum');
    const subject    = document.getElementById('cSubject');
    const chip       = document.getElementById('cOrderChip');
    const chipText   = document.getElementById('cOrderChipText');
    const drop       = document.getElementById('cOrderDrop');

    if (orderNumber) {
        orderInput.value = `${orderNumber}${customerName ? ' - '+customerName : ''}`;
        orderNum.value   = orderNumber;
        subject.value    = `訂${orderNumber}${customerName ? ' - '+customerName : ''} 报价`;
        chipText.textContent = `${orderNumber}${customerName ? ' · '+customerName : ''}`;
        chip.style.display   = '';
    } else {
        orderInput.value   = '';
        orderNum.value     = '';
        subject.value      = '';
        chip.style.display = 'none';
    }
    if (drop) drop.style.display = 'none';

    // 初始化收件人欄
    const toInput = document.getElementById('cToInput');
    if (toInput) {
        if (_autoApplyPreset && _presetRecipients.length > 0) {
            toInput.value = _presetRecipients.map(r => r.email).join(', ');
        } else {
            toInput.value = '';
        }
    }
    _renderComposePrsetBtns();
    // 同步開關狀態
    const cToggle = document.getElementById('cAutoApplyToggle');
    if (cToggle) cToggle.checked = _autoApplyPreset;

    setTimeout(() => orderInput.focus(), 80);
}

// 渲染撰寫介面的快速收件人按鈕
function _renderComposePrsetBtns() {
    const container = document.getElementById('cPresetBtns');
    if (!container) return;
    const list = _presetRecipients;
    container.innerHTML = '';
    // 同步開關 UI
    const cToggle = document.getElementById('cAutoApplyToggle');
    if (cToggle) cToggle.checked = _autoApplyPreset;
    if (list.length === 0) {
        container.innerHTML = '<span style="font-size:.73rem;color:#bbb;">尚無固定收件人</span>';
        return;
    }
    list.forEach(r => {
        const btn = document.createElement('button');
        btn.textContent = r.name || r.email;
        btn.title = r.email;
        btn.setAttribute('data-email', r.email);
        // 如果自動套用，預設高亮
        const preSelected = _autoApplyPreset;
        btn.setAttribute('data-selected', preSelected ? '1' : '0');
        btn.style.cssText = `border:1.5px solid ${preSelected ? '#ff2442' : '#e0e0e0'};border-radius:20px;padding:.2rem .65rem;font-size:.76rem;cursor:pointer;font-family:inherit;background:${preSelected ? '#ff2442' : 'white'};color:${preSelected ? 'white' : '#333'};transition:all .15s;white-space:nowrap;`;
        btn.onclick = () => {
            const sel = btn.getAttribute('data-selected') === '1';
            btn.setAttribute('data-selected', sel ? '0' : '1');
            btn.style.background  = sel ? 'white'   : '#ff2442';
            btn.style.color       = sel ? '#333'    : 'white';
            btn.style.borderColor = sel ? '#e0e0e0' : '#ff2442';
            const picked = Array.from(container.querySelectorAll('button[data-selected="1"]')).map(b => b.getAttribute('data-email'));
            document.getElementById('cToInput').value = picked.join(', ');
        };
        container.appendChild(btn);
    });
}

function closeCompose() {
    if (_currentMsg) {
        showPanel('read');
    } else {
        showPanel('empty');
    }
}

// ── 订单搜索 ─────────────────────────────────────────────
let _searchTimer = null;
async function searchOrders(q) {
    const drop = document.getElementById('cOrderDrop');
    if (!drop) return;
    if (!q) { drop.style.display = 'none'; return; }
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(async () => {
        try {
            const res = await fetch(`/tracking/api/messages/search-orders?q=${encodeURIComponent(q)}`);
            if (!res.ok || !res.headers.get('content-type')?.includes('json')) {
                drop.style.display = 'none'; return;
            }
            const data   = await res.json();
            const orders = data.orders || [];
            if (!orders.length) { drop.style.display = 'none'; return; }
            drop.innerHTML = orders.map(o =>
                `<div class="msg-order-drop-item" onclick="selectOrder('${_e(o.order_number)}','${_e(o.customer_name||'')}')">
                   <span class="drop-num">${_e(o.order_number)}</span>
                   <span class="drop-name">${_e(o.customer_name||'')}</span>
                 </div>`).join('');
            drop.style.display = '';
        } catch(e) { drop.style.display = 'none'; }
    }, 280);
}

function selectOrder(num, name) {
    document.getElementById('cOrderNum').value   = num;
    document.getElementById('cOrderInput').value = `${num}${name?' - '+name:''}`;
    document.getElementById('cOrderDrop').style.display = 'none';
    document.getElementById('cOrderChipText').textContent = `${num}${name?' · '+name:''}`;
    document.getElementById('cOrderChip').style.display   = '';
    const s = document.getElementById('cSubject');
    if (!s.value) s.value = `訂${num}${name?' - '+name:''} 报价`;
}

function clearOrder() {
    document.getElementById('cOrderNum').value   = '';
    document.getElementById('cOrderInput').value = '';
    document.getElementById('cOrderChip').style.display = 'none';
}

// ── 附件 ─────────────────────────────────────────────────
function previewFiles(files) {
    for (const f of files) _pendingFiles.push(f);
    renderFilePrev();
}

function renderFilePrev() {
    const box = document.getElementById('cFilePrev');
    if (!box) return;
    if (!_pendingFiles.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
    box.style.display = 'flex';
    box.innerHTML = _pendingFiles.map((f,i) => {
        const isImg = f.type.startsWith('image/');
        if (isImg) {
            // 圖片顯示縮圖
            const url = URL.createObjectURL(f);
            return `<div class="msg-att-chip-img">
                <img src="${url}" alt="${_e(f.name)}">
                <span class="msg-att-chip-name" style="max-width:48px">${_e(f.name.length>8?f.name.substring(0,8)+'...':f.name)}</span>
                <span class="msg-att-chip-rm" onclick="removeFile(${i})">✕</span>
            </div>`;
        }
        // 非圖片顯示圖示
        const ext = f.name.split('.').pop().toLowerCase();
        const iconColor = ext==='pdf'?'#e53e3e':ext.includes('xl')?'#38a169':ext.includes('doc')?'#3182ce':'#718096';
        return `<div class="msg-att-chip">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="${iconColor}" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span class="msg-att-chip-name">${_e(f.name)}</span>
            <span class="msg-att-chip-rm" onclick="removeFile(${i})">✕</span>
        </div>`;
    }).join('');
}

function removeFile(i) {
    _pendingFiles.splice(i,1);
    renderFilePrev();
}

// ── 发送报价 ─────────────────────────────────────────────
async function submitCompose() {
    const orderNum = document.getElementById('cOrderNum').value.trim();
    const subject  = document.getElementById('cSubject').value.trim();
    const body     = _quill ? _quill.root.innerHTML.trim() : '';
    const toRaw    = (document.getElementById('cToInput') || {}).value || '';
    const toEmails = toRaw.split(/[,;]/).map(e => e.trim()).filter(Boolean);

    if (!body || body === '<p><br></p>') { alert('請填寫报价内容'); return; }

    const btn = document.getElementById('cSendBtn');
    btn.disabled   = true;
    btn.textContent = '发送中...';

    try {
        // 1. 有订单 → POST 到 order，沒订单 → POST 到 free
        const apiUrl = orderNum
            ? `/tracking/api/orders/${orderNum}/messages`
            : `/tracking/api/messages/free`;

        const res  = await fetch(apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subject, body })
        });
        if (!res.ok) throw new Error('发送失敗');
        const data = await res.json();
        if (!data.success) throw new Error(data.error || '发送失敗');

        const msgId = data.message_id;
        console.log('[送出] message_id:', msgId, '附件數:', _pendingFiles.length);

        // 3. 若有填收件人，自動寄 email
        if (toEmails.length) {
            try {
                const mailRes  = await fetch(`/tracking/api/messages/${msgId}/send-email`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ to: toEmails })
                });
                const mailData = await mailRes.json();
                if (!mailData.success) console.warn('[Email寄送失敗]', mailData.error);
            } catch(e) {
                console.warn('[Email寄送錯誤]', e.message);
            }
        }

        // 2. 上傳附件
        if (_pendingFiles.length) {
            const fd = new FormData();
            fd.append('message_id', msgId);
            _pendingFiles.forEach(f => {
                fd.append('files', f);
                console.log('[附件]', f.name, f.type, f.size);
            });
            const uploadUrl = orderNum
                ? `/tracking/api/orders/${orderNum}/messages/upload`
                : `/tracking/api/messages/upload/${msgId}`;
            console.log('[上傳URL]', uploadUrl);
            const upRes  = await fetch(uploadUrl, { method: 'POST', body: fd });
            const upData = await upRes.json();
            console.log('[上傳結果]', upData);
            if (!upData.success) {
                console.error('[上傳失敗]', upData.error);
            }
        }

        await loadMessages();
        // 发送後自動選中剛發的报价
        const newMsg = _allMessages.find(m => m.id === msgId);
        if (newMsg) selectMessage(newMsg);
        else showPanel('empty');
    } catch (e) {
        alert(e.message || '发送失敗，請稍後再試');
    } finally {
        btn.disabled    = false;
        btn.innerHTML   = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> 发送报价`;
    }
}

// ── 删除 ─────────────────────────────────────────────────
function deleteMsg() {
    if (!_currentMsg) return;
    if (_isAdmin) {
        showConfirmModal(
            '確定要永久删除這封报价嗎？此操作無法撤銷。',
            '確認删除报价', '確認删除', '取消', true,
            { requireInput: 'DELETE', orderNumber: _currentMsg.order_number }
        ).then(ok => { if (ok) doDelete(_currentMsg.id, 'DELETE'); });
    } else {
        showConfirmModal(
            '確定要删除這封报价嗎？此操作無法撤銷。',
            '確認删除', '確認删除', '取消', true
        ).then(ok => { if (ok) doDelete(_currentMsg.id, ''); });
    }
}

async function doDelete(msgId, confirm) {
    try {
        const res  = await fetch(`/tracking/api/messages/${msgId}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm })
        });
        const data = await res.json();
        if (!data.success) { alert(data.error||'删除失敗'); return; }
        _allMessages = _allMessages.filter(m => m.id !== msgId);
        _currentMsgId = null;
        _currentMsg   = null;
        showPanel('empty');
        renderList();
    } catch(e) { alert('删除失敗'); }
}

// ── 打印 ─────────────────────────────────────────────────
function printMsg() {
    if (!_currentMsg) return;
    fetch(`/tracking/api/messages/${_currentMsg.id}/detail`)
        .then(r => r.json())
        .then(d => _openPrintWindow([(d.success && d.message) ? d.message : _currentMsg]))
        .catch(() => _openPrintWindow([_currentMsg]));
}

function _openPrintWindow(msgs) {
    const area = document.getElementById('globalPrintArea');
    if (!area) { alert('列印區域未找到'); return; }

    area.innerHTML = msgs.map((m, i) => `
        <div>
            <div class="pa-subject">${m.subject||'（无主题）'}</div>
            <div class="pa-meta">
                <strong>发件人：</strong>${m.sender_name||''}&emsp;
                <strong>时间：</strong>${m.created_at||''}
                ${m.order_number ? '&emsp;<strong>订单：</strong>' + m.order_number + (m.customer_name?' · '+m.customer_name:'') : ''}
            </div>
            <div class="pa-body">${m.body||''}</div>
            ${i < msgs.length - 1 ? '<hr class="pa-sep">' : ''}
        </div>
    `).join('');

    const cleanup = () => { area.innerHTML = ''; window.removeEventListener('afterprint', cleanup); };
    window.addEventListener('afterprint', cleanup);
    setTimeout(() => window.print(), 100);
}
// ── 跳到订单 ─────────────────────────────────────────────
function goToOrder(e) {
    e.preventDefault();
    const num = e.currentTarget.dataset.orderNum;
    if (!num) return false;
    // 新分頁打開主頁，自動開啟該訂單的 Drawer
    window.open(`/tracking/?open=${encodeURIComponent(num)}`, '_blank');
    return false;
}

// ── 拖動條 ────────────────────────────────────────────────
function initResizers() {
    makeResizer('rz1', 'msgSidebar',   130, 240);
    makeResizer('rz2', 'msgListPanel', 200, 440);
}

function makeResizer(rzId, leftId, mn, mx) {
    const rz = document.getElementById(rzId);
    const lp = document.getElementById(leftId);
    if (!rz || !lp) return;
    let sx, sw;
    rz.addEventListener('mousedown', e => {
        sx = e.clientX; sw = lp.offsetWidth;
        rz.classList.add('dragging');
        document.body.style.cssText = 'cursor:col-resize;user-select:none;';
        const mv = e2 => lp.style.width = Math.max(mn, Math.min(mx, sw+(e2.clientX-sx)))+'px';
        const up = () => {
            rz.classList.remove('dragging');
            document.body.style.cssText = '';
            document.removeEventListener('mousemove', mv);
            document.removeEventListener('mouseup', up);
        };
        document.addEventListener('mousemove', mv);
        document.addEventListener('mouseup', up);
        e.preventDefault();
    });
}

// ── 工具 ─────────────────────────────────────────────────
function _refreshNavBadge() {
    const unread = _allMessages.filter(m => !m.is_read && !m.is_own).length;
    // 更新導航欄 badge
    const navBadge = document.getElementById('msgNavBadge');
    if (navBadge) {
        navBadge.textContent = unread > 99 ? '99+' : unread;
        navBadge.style.display = unread > 0 ? '' : 'none';
    }
    // 更新信箱內 badge
    updateBadges(unread);
}
function _e(s) {
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function _set(id, txt) {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
}
function formatTime(ts) {
    if (!ts) return '';
    const d = new Date(ts.replace(' ','T'));
    const diff = Math.floor((Date.now()-d)/86400000);
    if (diff === 0) return d.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'});
    if (diff === 1) return '昨天';
    if (diff < 7)  return diff+'天前';
    return `${(d.getMonth()+1).toString().padStart(2,'0')}-${d.getDate().toString().padStart(2,'0')}`;
}
function formatDateTime(ts) {
    if (!ts) return '';
    return new Date(ts.replace(' ','T')).toLocaleString('zh-TW',{
        year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'
    });
}
function fmtSize(b) {
    if (!b) return '';
    if (b<1024) return b+'B';
    if (b<1048576) return (b/1024).toFixed(1)+'KB';
    return (b/1048576).toFixed(1)+'MB';
}

// ── 批量打印 ──────────────────────────────────────────────
function openBatchPrint() {
    const today = new Date().toLocaleDateString('zh-TW', {year:'numeric',month:'2-digit',day:'2-digit'});
    const todayMsgs = _allMessages.filter(m => {
        const d  = new Date(m.created_at.replace(' ','T'));
        const ds = d.toLocaleDateString('zh-TW', {year:'numeric',month:'2-digit',day:'2-digit'});
        return ds === today;
    });

    // 偵測重複：同一個業務員 + 同一個訂單 → 重複
    // key = sender_id + order_number，出現超過1次就標記
    const dupKey = m => `${m.sender_id||m.sender_name}__${m.order_number||'FREE'}`;
    const keyCount = {};
    todayMsgs.forEach(m => {
        const k = dupKey(m);
        keyCount[k] = (keyCount[k] || 0) + 1;
    });

    const modal = document.getElementById('batchPrintModal');
    const list  = document.getElementById('batchPrintList');
    const count = document.getElementById('batchSelectedCount');
    document.getElementById('batchSelectAll').checked = false;
    count.textContent = '已选 0 封';

    const hasDup = Object.values(keyCount).some(v => v > 1);

    if (!todayMsgs.length) {
        list.innerHTML = '<div style="text-align:center;padding:2rem;color:#aaa;font-size:.85rem;">今日暂无报价</div>';
    } else {
        // 有重複時顯示提示
        const dupHint = hasDup
            ? `<div style="background:#fff8e8;border:1px solid #ffe0a0;border-radius:8px;padding:.5rem .75rem;margin-bottom:.5rem;font-size:.78rem;color:#b86000;display:flex;align-items:center;gap:.4rem;">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                检测到重复报价（同一业务员对同一订单），已用 <span style="background:#fff0c0;padding:0 .3rem;border-radius:3px;">⚠️</span> 标记，请确认后再打印
               </div>`
            : '';

        list.innerHTML = dupHint + todayMsgs.map((m, idx) => {
            const isDup = keyCount[dupKey(m)] > 1;
            // 找出同組中最新的一筆（時間最晚）
            const groupMsgs = todayMsgs.filter(x => dupKey(x) === dupKey(m));
            const isLatest  = isDup && m.id === Math.max(...groupMsgs.map(x => x.id));
            // 重複組：預設只勾選最新一筆，其他取消
            const defaultChecked = !isDup || isLatest;

            const dupBadge = isDup
                ? `<span style="background:#fff0c0;border:1px solid #ffe066;color:#b86000;font-size:.65rem;font-weight:700;padding:.08rem .3rem;border-radius:4px;white-space:nowrap;">
                    ⚠️ 重复${isLatest?' (最新)':' (旧)'}
                   </span>`
                : '';

            const rowBg = isDup && !isLatest
                ? 'background:#fffdf0;'
                : '';

            return `<div style="display:flex;align-items:center;gap:.75rem;padding:.55rem .3rem;border-bottom:1px solid #f5f5f5;${rowBg}">
                <input type="checkbox" class="batch-chk" data-id="${m.id}"
                    ${defaultChecked ? 'checked' : ''}
                    onchange="updateBatchCount()"
                    style="flex-shrink:0;width:15px;height:15px;cursor:pointer;">
                <div style="flex:1;min-width:0;">
                    <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;">
                        <span style="font-size:.82rem;font-weight:${isDup&&!isLatest?'400':'600'};color:${isDup&&!isLatest?'#999':'#111'};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:260px;">${_e(m.subject||'（无主题）')}</span>
                        ${dupBadge}
                    </div>
                    <div style="font-size:.74rem;color:#999;margin-top:.15rem;">
                        ${_e(m.sender_name)} · ${formatTime(m.created_at)}
                        ${m.order_number?` · <span style="font-family:monospace;color:#666;">${_e(m.order_number)}</span>`:''}
                    </div>
                </div>
                ${m.has_attachments?'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#aaa" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>':''}
            </div>`;
        }).join('');

        // 更新已選數
        updateBatchCount();
    }

    modal.style.display = 'flex';
}

function closeBatchPrint() {
    document.getElementById('batchPrintModal').style.display = 'none';
}

function batchToggleAll(checked) {
    document.querySelectorAll('.batch-chk').forEach(c => c.checked = checked);
    updateBatchCount();
}

function updateBatchCount() {
    const n = document.querySelectorAll('.batch-chk:checked').length;
    document.getElementById('batchSelectedCount').textContent = `已选 ${n} 封`;
    document.getElementById('batchSelectAll').indeterminate =
        n > 0 && n < document.querySelectorAll('.batch-chk').length;
}

async function doBatchPrint() {
    const ids = [...document.querySelectorAll('.batch-chk:checked')].map(c => parseInt(c.dataset.id));
    if (!ids.length) { alert('请先选择要打印的报价'); return; }

    closeBatchPrint();

    // 逐一取完整報價，組成打印頁面
    const btn = document.getElementById('batchPrintBtn');
    if (btn) { btn.disabled = true; btn.textContent = '准备中...'; }

    try {
        const msgs = await Promise.all(ids.map(async id => {
            const res = await fetch(`/tracking/api/messages/${id}/detail`);
            const d   = await res.json();
            return d.success ? d.message : null;
        }));

        const valid = msgs.filter(Boolean);
        if (!valid.length) { alert('加载失败'); return; }

        // 用統一的打印視窗
        _openPrintWindow(valid);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '打印选中'; }
    }
}

// ── 标记操作 ──────────────────────────────────────────────
async function markUnread(msgId) {
    await fetch(`/tracking/api/messages/${msgId}/unread`, { method: 'POST' });
    const m = _allMessages.find(x => x.id === msgId);
    if (m) { m.is_read = false; renderList(); _refreshNavBadge(); }
}

async function markRead(msgId) {
    await fetch(`/tracking/api/messages/${msgId}/read`, { method: 'POST' });
    const m = _allMessages.find(x => x.id === msgId);
    if (m) { m.is_read = true; renderList(); _refreshNavBadge(); }
}

async function toggleFlag(msgId) {
    const res  = await fetch(`/tracking/api/messages/${msgId}/flag`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
        const m = _allMessages.find(x => x.id === msgId);
        if (m) { m.is_flagged = data.is_flagged; renderList(); }
    }
}

async function togglePin(msgId) {
    const res  = await fetch(`/tracking/api/messages/${msgId}/pin`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
        const m = _allMessages.find(x => x.id === msgId);
        if (m) {
            m.is_pinned = data.is_pinned;
            // 置頂的排最前，同為置頂按日期倒序，其餘也按日期倒序
            _allMessages.sort((a, b) => {
                if (a.is_pinned !== b.is_pinned) return b.is_pinned - a.is_pinned;
                return new Date(b.created_at) - new Date(a.created_at);
            });
            renderList();
        }
    }
}

// ── 發送郵件 ──────────────────────────────────────────────

// 固定收件人：存在資料庫，與帳號綁定
let _presetRecipients = [];   // [{id, name, email}]
let _autoApplyPreset  = true; // 是否自動套用

async function _loadPresetRecipients() {
    try {
        const res  = await fetch('/tracking/api/user/preset-recipients');
        const data = await res.json();
        if (data.success) {
            _presetRecipients = data.recipients || [];
            _autoApplyPreset  = data.auto_apply !== false;
        }
    } catch(e) { /* 網路錯誤保持預設值 */ }
}

async function _savePresetRecipientsToServer() {
    try {
        await fetch('/tracking/api/user/preset-recipients', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recipients: _presetRecipients, auto_apply: _autoApplyPreset })
        });
    } catch(e) { /* 靜默失敗 */ }
}

function _getPresetRecipients() { return _presetRecipients; }

// 渲染快速選擇按鈕（發送框）
function _renderPresetBtns() {
    const list = _presetRecipients;
    const container = document.getElementById('presetRecipients');
    if (!container) return;
    container.innerHTML = '';
    if (list.length === 0) {
        container.innerHTML = '<span style="font-size:.75rem;color:#bbb;">尚無固定收件人，請點下方「管理」新增</span>';
        return;
    }
    list.forEach(r => {
        const btn = document.createElement('button');
        btn.textContent = r.name || r.email;
        btn.title = r.email;
        btn.style.cssText = 'border:1.5px solid #e0e0e0;border-radius:20px;padding:.25rem .75rem;font-size:.78rem;cursor:pointer;font-family:inherit;background:white;color:#333;transition:all .15s;';
        btn.setAttribute('data-email', r.email);
        btn.setAttribute('data-selected', '0');
        btn.onclick = () => _togglePresetBtn(btn, r.email);
        container.appendChild(btn);
    });
}

// 點選/取消收件人按鈕，更新輸入框
function _togglePresetBtn(btn, email) {
    const selected = btn.getAttribute('data-selected') === '1';
    if (selected) {
        btn.setAttribute('data-selected', '0');
        btn.style.background = 'white';
        btn.style.color = '#333';
        btn.style.borderColor = '#e0e0e0';
    } else {
        btn.setAttribute('data-selected', '1');
        btn.style.background = '#ff2442';
        btn.style.color = 'white';
        btn.style.borderColor = '#ff2442';
    }
    const allBtns = document.querySelectorAll('#presetRecipients button[data-selected="1"]');
    const emails = Array.from(allBtns).map(b => b.getAttribute('data-email'));
    document.getElementById('sendEmailTo').value = emails.join(', ');
}

// 渲染管理列表
function _renderRecipientEditor() {
    const list = _presetRecipients;
    const el = document.getElementById('recipientListEditor');
    if (!el) return;
    if (list.length === 0) {
        el.innerHTML = '<div style="font-size:.75rem;color:#bbb;margin-bottom:.3rem;">尚無固定收件人</div>';
        return;
    }
    el.innerHTML = list.map((r, i) => `
        <div style="display:flex;align-items:center;gap:.4rem;margin-bottom:.3rem;font-size:.78rem;">
            <span style="flex:1;color:#333;">${r.name || ''} <span style="color:#999;">${r.email}</span></span>
            <button onclick="removePresetRecipient(${i})" style="background:none;border:none;color:#e53e3e;cursor:pointer;font-size:.8rem;padding:.1rem .3rem;">✕</button>
        </div>
    `).join('');
}

function toggleManageRecipients() {
    const panel = document.getElementById('manageRecipientsPanel');
    if (panel.style.display === 'none') {
        panel.style.display = 'block';
        _renderRecipientEditor();
    } else {
        panel.style.display = 'none';
    }
}

function addPresetRecipient() {
    const name  = (document.getElementById('newRecipientName').value  || '').trim();
    const email = (document.getElementById('newRecipientEmail').value || '').trim();
    if (!email) return;
    _presetRecipients.push({ name, email });
    _savePresetRecipientsToServer();
    document.getElementById('newRecipientName').value  = '';
    document.getElementById('newRecipientEmail').value = '';
    _renderRecipientEditor();
    _renderPresetBtns();
    _renderComposePrsetBtns();
}

function removePresetRecipient(idx) {
    _presetRecipients.splice(idx, 1);
    _savePresetRecipientsToServer();
    _renderRecipientEditor();
    _renderPresetBtns();
    _renderComposePrsetBtns();
}

function _getAutoApplyPreset()      { return _autoApplyPreset; }
function _setAutoApplyPreset(val)   {
    _autoApplyPreset = !!val;
    _savePresetRecipientsToServer();
}

function openSendEmail() {
    if (!_currentMsg) return;
    document.getElementById('sendEmailMsg').style.display = 'none';
    document.getElementById('sendEmailBtn').disabled = false;
    document.getElementById('sendEmailBtn').textContent = '发送';
    document.getElementById('manageRecipientsPanel').style.display = 'none';

    // 重置按鈕狀態
    document.querySelectorAll('#presetRecipients button').forEach(b => {
        b.setAttribute('data-selected', '0');
        b.style.background = 'white';
        b.style.color = '#333';
        b.style.borderColor = '#e0e0e0';
    });

    // 更新自動套用開關 UI
    const autoToggle = document.getElementById('autoApplyToggle');
    if (autoToggle) autoToggle.checked = _autoApplyPreset;

    // 自動套用固定收件人
    if (_autoApplyPreset) {
        const emails = _presetRecipients.map(r => r.email);
        document.getElementById('sendEmailTo').value = emails.join(', ');
        document.querySelectorAll('#presetRecipients button[data-email]').forEach(b => {
            b.setAttribute('data-selected', '1');
            b.style.background = '#ff2442';
            b.style.color = 'white';
            b.style.borderColor = '#ff2442';
        });
    } else {
        document.getElementById('sendEmailTo').value = '';
    }

    _renderPresetBtns();
    document.getElementById('sendEmailModal').style.display = 'flex';
    setTimeout(() => document.getElementById('sendEmailTo').focus(), 100);
}

function closeSendEmail() {
    document.getElementById('sendEmailModal').style.display = 'none';
}

async function doSendEmail() {
    if (!_currentMsg) return;
    const toVal = document.getElementById('sendEmailTo').value.trim();
    if (!toVal) { _showSendMsg('请填写收件人邮箱', true); return; }

    const btn = document.getElementById('sendEmailBtn');
    btn.disabled = true;
    btn.textContent = '发送中...';

    try {
        const res  = await fetch(`/tracking/api/messages/${_currentMsg.id}/send-email`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to: toVal })
        });
        const data = await res.json();
        if (data.success) {
            _showSendMsg('✅ 发送成功！邮件已发出', false);
            setTimeout(() => closeSendEmail(), 1800);
        } else {
            _showSendMsg('❌ ' + (data.error || '发送失败'), true);
            btn.disabled = false;
            btn.textContent = '发送';
        }
    } catch(e) {
        _showSendMsg('❌ 网络错误：' + e.message, true);
        btn.disabled = false;
        btn.textContent = '发送';
    }
}

function _showSendMsg(msg, isError) {
    const el = document.getElementById('sendEmailMsg');
    if (!el) return;
    el.textContent = msg;
    el.style.display = '';
    el.style.background = isError ? '#fff0f0' : '#f0fff4';
    el.style.color      = isError ? '#c53030' : '#276749';
    el.style.border     = `1px solid ${isError ? '#fed7d7' : '#c6f6d5'}`;
}
