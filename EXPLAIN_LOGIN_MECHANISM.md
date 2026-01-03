# 🔐 超級管理員登入機制說明

## 📋 工作原理

### 登入驗證流程

當你登入時，系統會：

1. **檢查 config.py 中的值**（第 44-45 行）
   - 比較你輸入的郵箱是否等於 `SUPER_ADMIN_EMAIL`
   - 比較你輸入的密碼是否等於 `SUPER_ADMIN_PASSWORD`
   - 如果都匹配 → 登入成功 ✅

2. **處理數據庫記錄**
   - 如果數據庫中**已有**這個郵箱的記錄 → 使用數據庫中的 user_id
   - 如果數據庫中**沒有**這個郵箱的記錄 → 自動創建新記錄

## ✅ 回答你的問題

### 問題1：在 config.py 中修改，是否等於下次登入就能用新的？

**答案：是的，但要重啟應用！**

- ✅ 修改 `config.py` 第 44-45 行的值
- ✅ 保存文件
- ✅ **重啟應用**（必須！）
- ✅ 下次登入時，使用新的帳號和密碼即可

**注意**：
- 如果只改了密碼，舊密碼立即失效，新密碼立即生效
- 如果改了郵箱，舊郵箱立即失效，新郵箱立即生效
- 但**必須重啟應用**才能生效（因為 Python 代碼已經載入到內存中）

### 問題2：剛剛因為出錯，數據庫裡已經有帳號密碼了？

**答案：沒問題，系統會自動處理！**

**情況分析**：

#### 情況A：只改密碼，不改郵箱
```
config.py: SUPER_ADMIN_EMAIL = 'admin@xingwang.com'
config.py: SUPER_ADMIN_PASSWORD = 'new_password'  ← 改成新密碼

數據庫: 已有 admin@xingwang.com 的記錄（舊密碼的hash）
```

**結果**：
- ✅ 登入時，系統會用 `config.py` 中的新密碼驗證
- ✅ 驗證通過後，系統會使用數據庫中已有的 user_id
- ✅ 數據庫中的 password_hash 不會更新（因為超級管理員驗證不查數據庫的hash）
- ✅ **可以正常登入，使用新密碼**

#### 情況B：改了郵箱
```
config.py: SUPER_ADMIN_EMAIL = 'new_admin@example.com'  ← 改成新郵箱
config.py: SUPER_ADMIN_PASSWORD = '12345678'

數據庫: 只有舊的 admin@xingwang.com 的記錄
```

**結果**：
- ✅ 登入時，系統會用 `config.py` 中的新郵箱驗證
- ✅ 如果數據庫中沒有 `new_admin@example.com`，系統會**自動創建**新記錄
- ✅ **可以正常登入，使用新郵箱**
- ⚠️ 舊的 `admin@xingwang.com` 記錄會保留在數據庫中（但不影響，因為驗證邏輯只看 config.py）

#### 情況C：既改郵箱又改密碼
```
config.py: SUPER_ADMIN_EMAIL = 'new_admin@example.com'
config.py: SUPER_ADMIN_PASSWORD = 'new_password'

數據庫: 只有舊的 admin@xingwang.com 的記錄
```

**結果**：
- ✅ 登入時，系統會用 `config.py` 中的新郵箱和新密碼驗證
- ✅ 如果數據庫中沒有 `new_admin@example.com`，系統會**自動創建**新記錄
- ✅ **可以正常登入，使用新的郵箱和密碼**

## 🔍 代碼邏輯（app.py 第 150 行）

```python
# 登入驗證（只檢查 config.py 中的值）
if email == admin_config.SUPER_ADMIN_EMAIL and password == admin_config.SUPER_ADMIN_PASSWORD:
    # 登入成功！
    # 然後檢查數據庫中是否有這個郵箱的記錄
    cursor.execute('SELECT id FROM users WHERE email = ?', (admin_config.SUPER_ADMIN_EMAIL,))
    user_row = cursor.fetchone()
    
    if user_row:
        # 如果有，使用數據庫中的 user_id
        session['user_id'] = user_row[0]
    else:
        # 如果沒有，自動創建（使用 config.py 中的值）
        cursor.execute('INSERT INTO users ...', (admin_config.SUPER_ADMIN_USERNAME, 
                                                  admin_config.SUPER_ADMIN_EMAIL, 
                                                  password_hash, ...))
```

## 📝 總結

### ✅ 修改 config.py 後：

1. **必須重啟應用**才能生效
2. **下次登入**時，使用 config.py 中的新值登入
3. **數據庫會自動處理**：
   - 如果郵箱不變 → 使用數據庫中已有的記錄
   - 如果郵箱改變 → 自動創建新記錄

### ✅ 數據庫中的舊記錄：

- **不會影響**登入（因為驗證邏輯只看 config.py）
- 如果郵箱改了，舊記錄會保留在數據庫中（但不影響使用）
- 如果想清理舊記錄，可以手動刪除（可選）

---

**重要**：
- 🔑 **登入驗證**：只看 `config.py` 中的值
- 💾 **數據庫記錄**：只影響 user_id 的分配，不影響驗證
- 🔄 **修改後**：必須重啟應用才能生效

