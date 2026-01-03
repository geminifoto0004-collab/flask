/**
 * 管理員頁面 JavaScript
 * 功能：Modal 管理、AJAX 編輯、表單驗證
 */

// ========== 新增授權 Modal ==========
function showAddForm() {
    document.getElementById('addModal').classList.add('show');
}

function closeAddForm() {
    document.getElementById('addModal').classList.remove('show');
}

// ========== 編輯授權 Modal ==========
function openEditModal(id, rut, empresa, status, expireDate) {
    document.getElementById('edit_id').value = id;
    document.getElementById('edit_rut').value = rut;
    document.getElementById('edit_empresa').value = empresa || '';
    document.getElementById('edit_status').value = status;
    document.getElementById('edit_expire_date').value = expireDate || '';
    document.getElementById('editModal').classList.add('show');
}

function closeEditModal() {
    document.getElementById('editModal').classList.remove('show');
}

// ========== 保存編輯（AJAX）==========
function saveEdit() {
    const id = document.getElementById('edit_id').value;
    const data = {
        empresa: document.getElementById('edit_empresa').value,
        status: document.getElementById('edit_status').value,
        expire_date: document.getElementById('edit_expire_date').value
    };

    fetch(`/licenses/update/${id}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            alert('✅ 更新成功！');
            location.reload();
        } else {
            alert('❌ 更新失敗: ' + (result.error || '未知錯誤'));
        }
    })
    .catch(error => {
        alert('❌ 網絡錯誤: ' + error);
    });
}

// ========== 點擊 Modal 外部關閉 ==========
window.onclick = function(event) {
    const addModal = document.getElementById('addModal');
    const editModal = document.getElementById('editModal');
    
    if (event.target === addModal) {
        closeAddForm();
    }
    if (event.target === editModal) {
        closeEditModal();
    }
}

// ========== ESC 鍵關閉 Modal ==========
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeAddForm();
        closeEditModal();
    }
});

// ========== 表單驗證 ==========
document.addEventListener('DOMContentLoaded', function() {
    // RUT 格式驗證（智利 RUT 格式）
    const rutInputs = document.querySelectorAll('input[name="rut"]');
    rutInputs.forEach(input => {
        input.addEventListener('blur', function() {
            const rut = this.value.trim();
            if (rut && !isValidRUT(rut)) {
                alert('⚠️ RUT 格式不正確（例: 12345678-9）');
            }
        });
    });

    // 到期日驗證（不能早於今天）
    const dateInputs = document.querySelectorAll('input[type="date"]');
    dateInputs.forEach(input => {
        input.addEventListener('change', function() {
            const selectedDate = new Date(this.value);
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            
            if (selectedDate < today) {
                if (confirm('⚠️ 到期日早於今天，確定要設置嗎？')) {
                    // 用戶確認
                } else {
                    this.value = '';
                }
            }
        });
    });
});

// ========== RUT 驗證函數 ==========
function isValidRUT(rut) {
    // 基本格式驗證：xxxxxxxx-x 或 xx.xxx.xxx-x
    const rutPattern = /^(\d{1,2}\.?\d{3}\.?\d{3}|\d{7,8})-[\dkK]$/;
    return rutPattern.test(rut);
}

// ========== 搜索過濾（可選功能）==========
function filterTable() {
    const input = document.getElementById('searchInput');
    if (!input) return;
    
    const filter = input.value.toUpperCase();
    const table = document.querySelector('table');
    const rows = table.getElementsByTagName('tr');

    for (let i = 1; i < rows.length; i++) {
        const cells = rows[i].getElementsByTagName('td');
        let found = false;

        for (let j = 0; j < cells.length; j++) {
            const cell = cells[j];
            if (cell) {
                const textValue = cell.textContent || cell.innerText;
                if (textValue.toUpperCase().indexOf(filter) > -1) {
                    found = true;
                    break;
                }
            }
        }

        rows[i].style.display = found ? '' : 'none';
    }
}

// ========== 刪除確認（增強版）==========
function confirmDelete(rut, empresa) {
    const message = `確定要刪除此授權嗎？\n\nRUT: ${rut}\n企業: ${empresa || '未設定'}`;
    return confirm(message);
}

// ========== 導出數據為 CSV（可選功能）==========
function exportToCSV() {
    const table = document.querySelector('table');
    const rows = table.querySelectorAll('tr');
    let csv = [];

    for (let i = 0; i < rows.length - 1; i++) { // 排除最後一行（操作列）
        const row = rows[i];
        const cols = row.querySelectorAll('td, th');
        let csvRow = [];

        for (let j = 0; j < cols.length - 1; j++) { // 排除操作欄
            csvRow.push(cols[j].innerText);
        }

        csv.push(csvRow.join(','));
    }

    // 下載 CSV
    const csvContent = '\uFEFF' + csv.join('\n'); // \uFEFF 為 UTF-8 BOM
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    
    link.setAttribute('href', url);
    link.setAttribute('download', `licenses_${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ========== 自動刷新統計數據（可選）==========
function updateStats() {
    fetch('/api/stats')
        .then(response => response.json())
        .then(data => {
            // 更新統計卡片
            console.log('統計數據已更新', data);
        })
        .catch(error => {
            console.error('統計更新失敗:', error);
        });
}

// 每 30 秒自動刷新統計（可選功能，需要後端 API）
// setInterval(updateStats, 30000);

// ========== 用戶管理功能 ==========
function showUserManagement() {
    // 跳轉到用戶管理頁面
    window.location.href = '/admin/users';
}

// ========== 資料庫瀏覽功能 ==========
function showDatabaseBrowser() {
    // 跳轉到資料庫瀏覽頁面
    window.location.href = '/admin/database';
}