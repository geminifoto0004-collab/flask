# 🔐 超級管理員備案登入信息

> 💡 **提示**: 修改密碼最簡單的方法：直接修改 `config.py` 第 48 行  
> 詳見: `HOW_TO_CHANGE_ADMIN_PASSWORD.md`

## ⚠️ 緊急備案：如果環境變數設置出問題，使用此備案信息

### 📍 備案位置
**文件**: `config.py`  
**類別**: `AdminConfig`  
**行數**: 第 39-40 行

### 🔑 備案登入信息

```
郵箱: admin@xingwang.com
密碼: 12345678
用戶名: super_admin
```

### 📝 如何查看備案信息

1. **打開文件**: `config.py`
2. **找到第 30-42 行**的 `AdminConfig` 類
3. **查看以下行**:
   ```python
   SUPER_ADMIN_EMAIL = os.environ.get('SUPER_ADMIN_EMAIL', 'admin@xingwang.com')
   SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', '12345678')
   ```
   - 如果環境變數未設置，會使用 `'admin@xingwang.com'` 和 `'12345678'`（備案值）

### 🔄 工作原理

```python
# config.py 中的邏輯：
SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', '12345678')
#                                 ↑ 先檢查環境變數    ↑ 如果沒有，用這個備案值
```

**優先級**：
1. **第一優先**：環境變數 `SUPER_ADMIN_PASSWORD`（如果設置了）
2. **備案**：`config.py` 中的 `'12345678'`（如果環境變數未設置）

### ⚠️ 重要：環境變數和備案值不一致的情況

**如果環境變數設置了，但與備案值不同**：
- 系統會使用**環境變數的值**（優先級更高）
- 備案值 `12345678` **不會生效**
- 如果忘記環境變數的密碼，無法用備案值登入

**解決方案**：
1. **查看當前使用的密碼**：
   ```bash
   python check_admin_credentials.py
   ```
   這個工具會顯示當前實際使用的登入信息

2. **刪除環境變數，使用備案值**：
   - 在 PythonAnywhere：刪除 Web 設置中的 `SUPER_ADMIN_PASSWORD` 環境變數
   - 系統會自動使用備案值 `12345678`

3. **更新備案值**：
   - 如果環境變數的密碼是正確的，可以更新 `config.py` 第 40 行的備案值
   - 這樣即使環境變數出問題，備案值也能使用

### ✅ 使用場景

- ✅ **開發環境**：直接使用備案值，無需設置環境變數
- ✅ **緊急情況**：環境變數設置出問題時，備案值自動生效
- ✅ **忘記密碼**：如果忘記了環境變數的密碼，可以查看此備案

### 🛡️ 安全說明

- **備案值**：`12345678` 僅用於開發環境和緊急備案
- **生產環境**：建議設置環境變數使用更強的密碼
- **備案位置**：永遠在 `config.py` 第 40 行，不會改變

### 📞 如何修改備案值（如果需要）

1. 打開 `config.py`
2. 找到第 40 行：
   ```python
   SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', '12345678')
   ```
3. 修改 `'12345678'` 為你想要的備案密碼：
   ```python
   SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', 'your_backup_password')
   ```

---

**最後更新**: 2026-01-01  
**備案狀態**: ✅ 可用  
**備案位置**: `config.py` 第 40 行

