# 🗄️ TiDB 初始化指南

## ✅ 好消息：代碼已經自動處理！

**你的代碼已經幫你處理好了 TiDB 初始化！** 🎉

當應用啟動時，會自動：
1. ✅ 連接 TiDB 數據庫
2. ✅ 自動創建所有需要的表
3. ✅ 自動添加新列（向後兼容）
4. ✅ 初始化默認數據

---

## 🚀 自動初始化（推薦）

### 在 Render 上（自動）

當你的應用在 Render 上部署後：

1. **首次訪問應用**時，系統會自動：
   - 連接 TiDB 數據庫
   - 創建所有表（users, services, user_services, 等）
   - 初始化默認配置

2. **查看日誌**確認初始化成功：
   - 在 Render Dashboard → 你的 Web Service → Logs
   - 應該看到類似這樣的輸出：
     ```
     ✅ 資料庫自動初始化完成
     users 表已就緒
     services 表已就緒
     ...
     ```

3. **如果看到錯誤**：
   - 檢查環境變數是否正確設置
   - 確認 TiDB 連接信息正確
   - 確認數據庫用戶有 CREATE TABLE 權限

---

## 🔧 手動初始化（可選）

如果你想在部署前手動初始化，可以使用以下方法：

### 方法 1：使用 database.py（推薦）

在本地運行（需要設置環境變數）：

```bash
# 設置環境變數
export DB_TYPE=tidb
export DB_HOST=gateway01.ap-northeast-1.prod.aws.tidbcloud.com
export DB_PORT=4000
export DB_USER=root
export DB_PASSWORD=your_password
export DB_NAME=test

# 運行初始化
python database.py
```

**輸出示例**：
```
==================================================
資料庫管理工具
==================================================

資料庫類型: tidb
資料庫 URL: mysql://root:***@gateway01...

[1] 初始化資料庫...
users 表已就緒
services 表已就緒
user_services 表已就緒
...
✅ 資料庫檢查通過

[3] 資料庫統計:
  users: 0
  services: 3
  ...
```

### 方法 2：使用 init_config.py（完整初始化）

這會初始化資料庫和默認配置：

```bash
# 設置環境變數（同上）
python init_config.py
```

---

## 📋 創建的表

系統會自動創建以下表：

1. **users** - 用戶表
   - id, username, email, password_hash, role, company_name, created_at

2. **services** - 服務產品表
   - id, name, description, price, duration_days, version, config_json, status, created_at

3. **user_services** - 用戶購買的服務表
   - id, user_id, service_id, status, start_date, end_date, config_json, created_at

4. **verification_codes** - 郵件驗證碼表
   - id, email, code, purpose, expire_time, used, created_at

5. **user_sessions** - 用戶會話表
   - id, user_id, session_token, device_info, service_name, session_start, last_activity, is_online

6. **user_monitor_configs** - 監控任務配置表
   - id, user_id, api_key, zofri_username, zofri_password, zofri_rut_entidad, 
     notification_emails, company_name, email_subject, last_check_time, is_active, created_at

7. **service_versions** - 服務版本表
   - id, service_name, param_name, param_content, created_at, updated_at

---

## ✅ 驗證初始化

### 方法 1：查看 Render 日誌

在 Render Dashboard → Logs，應該看到：
```
✅ 資料庫自動初始化完成
users 表已就緒
services 表已就緒
...
```

### 方法 2：訪問應用

1. 訪問你的應用 URL
2. 嘗試登入（使用你設置的帳號密碼）
3. 如果登入成功，說明資料庫已正確初始化

### 方法 3：使用檢查工具

在本地運行（需要設置環境變數）：
```bash
python check_db_config.py
```

---

## 🔍 故障排除

### 問題 1：初始化失敗

**錯誤信息**：
```
資料庫連接失敗: ...
```

**解決方法**：
1. 檢查環境變數是否正確設置
2. 確認 TiDB 連接信息正確
3. 確認數據庫用戶有 CREATE TABLE 權限
4. 查看 Render 日誌獲取詳細錯誤信息

### 問題 2：表已存在錯誤

**錯誤信息**：
```
Table 'xxx' already exists
```

**解決方法**：
- 這是正常的！`CREATE TABLE IF NOT EXISTS` 會跳過已存在的表
- 如果表結構需要更新，系統會自動添加新列

### 問題 3：權限不足

**錯誤信息**：
```
Access denied for user 'xxx'@'xxx'
```

**解決方法**：
1. 確認數據庫用戶有足夠權限：
   ```sql
   GRANT ALL PRIVILEGES ON database_name.* TO 'user'@'%';
   FLUSH PRIVILEGES;
   ```
2. 或者使用 root 用戶（開發環境）

---

## 📝 總結

### ✅ 自動初始化（推薦）

**在 Render 上**：
- 應用啟動時自動初始化
- 首次訪問時自動創建表
- 無需手動操作

**你只需要**：
1. ✅ 設置環境變數（DB_TYPE, DB_HOST, 等）
2. ✅ 部署應用
3. ✅ 訪問應用（自動初始化）

### 🔧 手動初始化（可選）

如果你想在部署前測試：
```bash
# 設置環境變數
export DB_TYPE=tidb
export DB_HOST=...
export DB_PORT=4000
export DB_USER=...
export DB_PASSWORD=...
export DB_NAME=...

# 運行初始化
python database.py
```

---

## 🎉 完成！

設置完成後，你的 TiDB 數據庫會：
- ✅ 自動初始化（首次訪問時）
- ✅ 自動創建所有表
- ✅ 自動添加新列（向後兼容）
- ✅ 準備好使用！

**不需要手動操作，代碼已經幫你處理好了！** 🚀

