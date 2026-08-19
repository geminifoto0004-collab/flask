// 用户管理模块 - v3.0 改进版
// 更新：移除负责产品栏位、改用 Modal 替代 alert、使用 SVG 图标

console.log('用户管理模块已载入 - 版本 3.0');
console.log('更新時間: 2025-01-18');

let allUsers = [];
let editingUserId = null;
let approvingUserId = null;
let currentActionUserId = null; // 用於 Modal 操作

const ROLE_LABELS = {
    admin: 'ADMIN',
    sales: 'SALES',
    viewer: 'VIEWER'
};

function getRoleOptionsHtml(currentRole) {
    const roleOptions = Array.isArray(window.USER_ROLE_OPTIONS) && window.USER_ROLE_OPTIONS.length
        ? window.USER_ROLE_OPTIONS
        : ['admin', 'sales', 'viewer'];
    return roleOptions.map(role => {
        const label = ROLE_LABELS[role] || role.toUpperCase();
        const selected = role === currentRole ? 'selected' : '';
        return `<option value="${role}" ${selected}>${label}</option>`;
    }).join('');
}

// ==================== 载入用户 ====================

async function loadUsers() {
    console.log('🔄 开始载入用户列表...');
    try {
        const response = await fetch('/tracking/api/users');
        console.log('📡 API 響應狀態:', response.status);
        
        if (!response.ok) {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                const errorData = await response.json();
                throw new Error(errorData.error || `HTTP ${response.status}`);
            } else {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
        }
        
        const data = await response.json();
        console.log('API 返回數據:', data);
        
        if (data.success) {
            allUsers = data.data;
            console.log('用户数据载入成功，共', allUsers.length, '个用户');
            updateTotalCount();
            renderUsers();
        } else {
            showToast('错误', data.error || '未知错误', 'error');
        }
    } catch (error) {
        console.error('载入用户列表错误：', error);
        showToast('错误', '载入用户列表失败：' + error.message, 'error');
    }
}

// ==================== 渲染用户表格 ====================

function renderUsers() {
    console.log('开始渲染用户表格...');
    const tbody = document.getElementById('users-table-body');
    if (!tbody) {
        console.error('找不到表格 tbody 元素！');
        return;
    }
    
    const filtered = getFilteredUsers();
    console.log('筛选后的用户数量:', filtered.length);
    
    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--text-2);">没有找到匹配的用户</td></tr>';
        return;
    }
    
    tbody.innerHTML = filtered.map(user => {
        const employeeId = user.employee_id || `EMP${String(user.user_id).padStart(3, '0')}`;
        const userStatus = user.status || 'active';
        const statusBadge = getStatusBadge(userStatus);
        
        return `
            <tr class="user-row" data-status="${userStatus}" data-user-id="${user.user_id}">
                <td style="color: var(--text-2); font-size: 0.875rem;">${user.user_id}</td>
                <td><code style="background: var(--gray-bg); padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.875rem; font-weight: 600;">${employeeId}</code></td>
                <td><strong>${escapeHtml(user.username)}</strong></td>
                <td>
                    <input type="text" 
                           class="inline-edit" 
                           value="${escapeHtml(user.real_name || user.display_name)}" 
                           data-field="real_name"
                           data-user-id="${user.user_id}"
                           onblur="saveInlineEdit(this)"
                           style="width: 100%; border: 1px solid transparent; background: transparent; padding: 0.25rem; border-radius: 4px; font-size: 0.9375rem;">
                </td>
                <td>
                    <select class="inline-edit-select" 
                            data-field="role"
                            data-user-id="${user.user_id}"
                            onchange="saveInlineEdit(this)"
                            style="width: 100%; border: 1px solid var(--border); background: white; padding: 0.375rem; border-radius: 4px; font-size: 0.875rem; cursor: pointer;">
                        ${getRoleOptionsHtml(user.role)}
                    </select>
                </td>
                <td class="status-cell">${statusBadge}</td>
                <td style="color: var(--text-2); font-size: 0.875rem;">${formatDate(user.created_at)}</td>
                <td class="actions-cell">
                    <div class="action-buttons">
                        ${getActionButtons(user)}
                    </div>
                </td>
            </tr>
        `;
    }).join('');
    
    // 修復隱藏欄位
    setTimeout(() => {
        const table = document.querySelector('.users-table');
        if (table) {
            let fixedCount = 0;
            table.querySelectorAll('th, td').forEach(cell => {
                if (cell.style.display === 'none') {
                    cell.style.display = '';
                    fixedCount++;
                }
            });
            if (fixedCount > 0) {
                console.log(`已修復 ${fixedCount} 個隱藏的欄位`);
            }
        }
    }, 50);
}

// ==================== 狀態徽章 ====================

function getStatusBadge(status) {
    const badges = {
        'pending': '<span class="status-badge status-pending">待审核</span>',
        'active': '<span class="status-badge status-active">已审核</span>',
        'rejected': '<span class="status-badge status-rejected">已拒绝</span>',
        'suspended': '<span class="status-badge status-suspended">已停权</span>' // ⭐ 新增
    };
    return badges[status] || badges['active'];
}

// ==================== 動態操作按鈕 ====================

function getActionButtons(user) {
    const status = user.status || 'active';
    const buttons = [];
    
    // 根據狀態顯示對應按鈕
    if (status === 'pending') {
        // 待审核：通过 + 拒绝
        buttons.push(`
            <button class="action-btn approve" onclick="openApproveModal(${user.user_id})" title="通过审核">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                通过
            </button>
        `);
        buttons.push(`
            <button class="action-btn reject" onclick="quickReject(${user.user_id})" title="拒绝">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
                拒绝
            </button>
        `);
    } else if (status === 'active') {
        // 已审核：停权
        buttons.push(`
            <button class="action-btn suspend" onclick="openSuspendModal(${user.user_id}, '${escapeHtml(user.username)}')" title="停权">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="15" y1="9" x2="9" y2="15"></line>
                    <line x1="9" y1="9" x2="15" y2="15"></line>
                </svg>
                停权
            </button>
        `);
    } else if (status === 'rejected') {
        // 已拒绝：恢复
        buttons.push(`
            <button class="action-btn restore" onclick="openRestoreModal(${user.user_id}, '${escapeHtml(user.username)}')" title="恢复">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 12a9 9 0 11-6.219-8.56"></path>
                </svg>
                恢复
            </button>
        `);
    
    } else if (status === 'suspended') {  
        buttons.push(`
            <button class="action-btn restore" onclick="openRestoreModal(${user.user_id}, '${escapeHtml(user.username)}')" title="恢復">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 12a9 9 0 11-6.219-8.56"></path>
                </svg>
                恢复
            </button>
        `);
    }
    
    // 所有状态都有：重置密码
    buttons.push(`
        <button class="action-btn reset" onclick="openResetPasswordModal(${user.user_id}, '${escapeHtml(user.username)}', '${escapeHtml(user.real_name || user.display_name)}')" title="重置密码">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
            </svg>
            重置密码
        </button>
    `);

    buttons.push(`
        <button class="action-btn delete" onclick="openDeleteUserModal(${user.user_id}, '${escapeHtml(user.username)}')" title="删除用户">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
                <path d="M10 11v6"></path>
                <path d="M14 11v6"></path>
                <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>
            </svg>
            删除
        </button>
    `);
    
    return buttons.join('');
}

// ==================== Modal 操作函數 ====================

// 停权 Modal
function openSuspendModal(userId, username) {
    currentActionUserId = userId;
    document.getElementById('suspend-username').textContent = username;
    document.getElementById('suspendConfirmModal').classList.add('show');
}

function closeSuspendConfirmModal() {
    document.getElementById('suspendConfirmModal').classList.remove('show');
    currentActionUserId = null;
}

async function confirmSuspendUser() {
    if (!currentActionUserId) return;
    
    try {
        const response = await fetch(`/tracking/api//users/${currentActionUserId}/suspend`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('成功', '用户已停权', 'success');
            closeSuspendConfirmModal();
            loadUsers();
        } else {
            showToast('错误', data.error || '停权失败', 'error');
        }
    } catch (error) {
        console.error('停权用户失败：', error);
        showToast('错误', '停权失败：' + error.message, 'error');
    }
}

// 恢复 Modal
function openRestoreModal(userId, username) {
    currentActionUserId = userId;
    document.getElementById('restore-username').textContent = username;
    document.getElementById('restoreConfirmModal').classList.add('show');
}

function closeRestoreConfirmModal() {
    document.getElementById('restoreConfirmModal').classList.remove('show');
    currentActionUserId = null;
}

async function confirmRestoreUser() {
    if (!currentActionUserId) return;
    
    try {
        const response = await fetch(`/tracking/api//users/${currentActionUserId}/restore`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('成功', '用户已恢复', 'success');
            closeRestoreConfirmModal();
            loadUsers();
        } else {
            showToast('错误', data.error || '恢复失败', 'error');
        }
    } catch (error) {
        console.error('恢复用户失败：', error);
        showToast('错误', '恢复失败：' + error.message, 'error');
    }
}

// 重置密码 Modal
function openResetPasswordModal(userId, username, realName) {
    currentActionUserId = userId;
    document.getElementById('reset-username').textContent = username;
    document.getElementById('reset-real-name').textContent = realName;
    document.getElementById('reset-new-password').value = '';
    document.getElementById('reset-require-change').checked = true;
    document.getElementById('resetPasswordModal').classList.add('show');
}

function closeResetPasswordModal() {
    document.getElementById('resetPasswordModal').classList.remove('show');
    currentActionUserId = null;
}

// 删除用户 Modal
function openDeleteUserModal(userId, username) {
    currentActionUserId = userId;
    document.getElementById('delete-username').textContent = username;
    document.getElementById('deleteUserModal').classList.add('show');
}

function closeDeleteUserModal() {
    document.getElementById('deleteUserModal').classList.remove('show');
    currentActionUserId = null;
}

async function confirmDeleteUser() {
    if (!currentActionUserId) return;

    const confirmBtn = document.getElementById('deleteConfirmBtn');
    if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.textContent = '删除中...';
    }

    try {
        const response = await fetch(`/tracking/api/users/${currentActionUserId}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();
        if (data.success) {
            showToast('成功', '用户已删除', 'success');
            closeDeleteUserModal();
            loadUsers();
        } else {
            showToast('错误', data.error || '删除失败', 'error');
        }
    } catch (error) {
        console.error('删除用户失败：', error);
        showToast('错误', '删除失败：' + error.message, 'error');
    } finally {
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = '确认删除';
        }
    }
}

async function confirmResetPassword() {
    if (!currentActionUserId) return;
    
    const newPassword = document.getElementById('reset-new-password').value.trim();
    const requireChange = document.getElementById('reset-require-change').checked;
    
    if (newPassword && newPassword.length < 6) {
        showToast('错误', '密码至少需要 6 个字符', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/tracking/api//users/${currentActionUserId}/reset-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                new_password: newPassword || null,
                require_change: requireChange
            })
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('成功', data.message || '密码已重置', 'success');
            closeResetPasswordModal();
            loadUsers();
        } else {
            showToast('错误', data.error || '重置失败', 'error');
        }
    } catch (error) {
        console.error('重置密码失败：', error);
        showToast('错误', '重置失败：' + error.message, 'error');
    }
}

// ==================== 快速操作（保留原有功能）====================

async function quickReject(userId) {
    try {
        const response = await fetch(`/tracking/api//users/${userId}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('成功', '用户已拒绝', 'success');
            loadUsers();
        } else {
            showToast('錯誤', data.error || '拒絕失敗', 'error');
        }
    } catch (error) {
        console.error('拒絕用戶失敗：', error);
        showToast('錯誤', '拒絕失敗：' + error.message, 'error');
    }
}

// ==================== 審核 Modal（保留原有）====================

function openApproveModal(userId) {
    const user = allUsers.find(u => u.user_id === userId);
    if (!user) return;
    
    approvingUserId = userId;
    document.getElementById('approve-username').textContent = user.username;
    document.getElementById('approve-real-name').textContent = user.real_name || user.display_name || '-';
    document.getElementById('approve-created-at').textContent = formatDate(user.created_at);
    document.getElementById('approve-role').value = user.role || 'sales';
    document.getElementById('approveUserModal').classList.add('show');
}

function closeApproveModal() {
    document.getElementById('approveUserModal').classList.remove('show');
    approvingUserId = null;
}

async function confirmApproveUser() {
    if (!approvingUserId) return;
    
    const role = document.getElementById('approve-role').value;
    
    try {
        const response = await fetch(`/tracking/api//users/${approvingUserId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role })
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('成功', '用户已通过审核', 'success');
            closeApproveModal();
            loadUsers();
        } else {
            showToast('错误', data.error || '审核失败', 'error');
        }
    } catch (error) {
        console.error('审核用户失败：', error);
        showToast('错误', '审核失败：' + error.message, 'error');
    }
}

async function confirmRejectUser() {
    if (!approvingUserId) return;
    
    try {
        const response = await fetch(`/tracking/api//users/${approvingUserId}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('成功', '用户已拒绝', 'success');
            closeApproveModal();
            loadUsers();
        } else {
            showToast('錯誤', data.error || '拒絕失敗', 'error');
        }
    } catch (error) {
        console.error('拒絕用戶失敗：', error);
        showToast('錯誤', '拒絕失敗：' + error.message, 'error');
    }
}

// ==================== 内联编辑 ====================

async function saveInlineEdit(element) {
    const userId = element.dataset.userId;
    const field = element.dataset.field;
    const value = element.value.trim();
    
    if (!value) {
        showToast('错误', '值不能为空', 'error');
        loadUsers();
        return;
    }
    
    try {
        const response = await fetch(`/tracking/api//users/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: value })
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('成功', '更新成功', 'success');
            loadUsers();
        } else {
            showToast('错误', data.error || '更新失败', 'error');
            loadUsers();
        }
    } catch (error) {
        console.error('更新失败：', error);
        showToast('错误', '更新失败：' + error.message, 'error');
        loadUsers();
    }
}

// ==================== 工具函數 ====================

function getFilteredUsers() {
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    const statusFilter = document.getElementById('status-filter').value;
    const roleFilter = document.getElementById('role-filter').value;
    
    return allUsers.filter(user => {
        const matchSearch = !searchTerm || 
            user.username.toLowerCase().includes(searchTerm) ||
            (user.real_name && user.real_name.toLowerCase().includes(searchTerm)) ||
            (user.display_name && user.display_name.toLowerCase().includes(searchTerm));
        
        const matchStatus = !statusFilter || (user.status || 'active') === statusFilter;
        const matchRole = !roleFilter || user.role === roleFilter;
        
        return matchSearch && matchStatus && matchRole;
    });
}

function filterUsers() {
    renderUsers();
}

function updateTotalCount() {
    document.getElementById('total-count').textContent = allUsers.length;
}

function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleString('zh-TW', { 
        year: 'numeric', 
        month: '2-digit', 
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function showToast(title, message, type = 'success') {
    if (typeof window.showToast === 'function') {
        window.showToast(title, message, type);
    } else if (typeof showToast === 'function') {
        showToast(title, message, type);
    } else {
        // 最后的后备方案：使用 console
        console.log(`[${type.toUpperCase()}] ${title}: ${message}`);
    }
}

// ==================== 新增用户 Modal（保留原有）====================

function openNewUserModal() {
    editingUserId = null;
    document.getElementById('userModalTitle').textContent = '新增用户';
    document.getElementById('submitUserBtn').textContent = '创建';
    document.getElementById('passwordField').style.display = 'block';
    document.getElementById('newUserForm').reset();
    document.getElementById('newUserModal').classList.add('show');
}

function closeModal() {
    document.getElementById('newUserModal').classList.remove('show');
    editingUserId = null;
}

async function submitUserForm() {
    const form = document.getElementById('newUserForm');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    
    if (!data.username || !data.password || !data.real_name) {
        showToast('错误', '请填写所有必填栏位', 'error');
        return;
    }
    
    try {
        const response = await fetch('/tracking/api//users', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        if (result.success) {
            showToast('成功', '用户创建成功', 'success');
            closeModal();
            loadUsers();
        } else {
            showToast('错误', result.error || '创建失败', 'error');
        }
    } catch (error) {
        console.error('创建用户失败：', error);
        showToast('错误', '创建失败：' + error.message, 'error');
    }
}

// ==================== 初始化 ====================

document.addEventListener('DOMContentLoaded', () => {
    console.log('📋 DOM 已载入，开始初始化用户管理模块...');
    loadUsers();
});