# 🚀 Render 部署和測試帳號設置指南

## 📋 概述

本指南將幫助你在 Render 上設置環境變數，以便可以測試登入功能。

---

## 🔧 步驟 1：在 Render 設置環境變數

### 1.1 登入 Render Dashboard

1. 訪問 https://render.com
2. 登入你的帳號
3. 找到你的 Web Service（應該已經從 GitHub 連接）

### 1.2 設置環境變數

1. 點擊你的 Web Service
2. 點擊左側 **"Environment"** 標籤
3. 點擊 **"Add Environment Variable"** 按鈕
4. 添加以下環境變數：

#### 必須設置的環境變數：

```bash
# 資料庫配置（如果使用 PostgreSQL）
DATABASE_TYPE=postgresql
# 注意：DATABASE_URL 會由 Render 自動提供（如果你在 Render 創建了 PostgreSQL 資料庫）

# 或者使用 TiDB Cloud（如果使用 MySQL/TiDB）
DATABASE_TYPE=mysql
DATABASE_URL=mysql://用戶名:密碼@主機:端口/數據庫名

# Flask 密鑰（必須設置）
SECRET_KEY=your-secret-key-change-this-to-random-string

# 超級管理員帳號（可選，如果不設置會使用 config.py 中的默認值）
SUPER_ADMIN_EMAIL=admin@xingwang.com

# 超級管理員密碼（可選，如果不設置會使用 config.py 中的默認值）
SUPER_ADMIN_PASSWORD=12345678

# SMTP 郵件配置（如果需要發送郵件）
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

### 1.3 生成 SECRET_KEY

**重要**：`SECRET_KEY` 必須是一個隨機字符串，用於 Flask session 加密。

你可以使用以下方法生成：

**方法 1：使用 Python**
```python
import secrets
print(secrets.token_hex(32))
```

**方法 2：使用在線工具**
- 訪問 https://randomkeygen.com/
- 選擇 "CodeIgniter Encryption Keys"
- 複製生成的密鑰

**方法 3：使用命令行**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 🗄️ 步驟 2：設置資料庫

### 選項 A：使用 Render PostgreSQL（推薦）

1. 在 Render Dashboard 點擊 **"New +"** → **"PostgreSQL"**
2. 選擇免費方案（Free）或付費方案
3. 創建資料庫
4. Render 會自動提供 `DATABASE_URL` 環境變數
5. 你只需要在 Web Service 的環境變數中設置：
   ```
   DATABASE_TYPE=postgresql
   ```
6. Render 會自動將 `DATABASE_URL` 連接到你的 Web Service

### 選項 B：使用 TiDB Cloud

1. 登入 TiDB Cloud 控制台
2. 創建或選擇一個 TiDB 集群
3. 獲取連接信息
4. 在 Render 的環境變數中設置：
   ```
   DATABASE_TYPE=mysql
   DATABASE_URL=mysql://用戶名:密碼@主機:4000/數據庫名
   ```

---

## 🔐 步驟 3：設置測試帳號

### 方法 1：使用環境變數（推薦，更安全）

在 Render 的環境變數中設置：

```
SUPER_ADMIN_EMAIL=test@example.com
SUPER_ADMIN_PASSWORD=your_test_password
```

### 方法 2：使用 config.py 中的默認值

如果不設置環境變數，系統會使用 `config.py` 中的默認值：
- **郵箱**：`admin@xingwang.com`
- **密碼**：`12345678`

**注意**：如果代碼已經推送到 GitHub，這些默認值會公開，建議使用環境變數。

---

## 🚀 步驟 4：部署和測試

### 4.1 保存環境變數

1. 在 Render 環境變數頁面點擊 **"Save Changes"**
2. Render 會自動重新部署你的應用

### 4.2 等待部署完成

1. 查看部署日誌，確認沒有錯誤
2. 等待部署完成（通常需要 1-2 分鐘）

### 4.3 測試登入

1. 訪問你的應用 URL（例如：`https://your-app.onrender.com`）
2. 點擊登入
3. 使用你設置的帳號和密碼登入：
   - 如果設置了環境變數：使用環境變數中的值
   - 如果沒有設置：使用 `admin@xingwang.com` / `12345678`

---

## ✅ 檢查清單

在開始測試前，確認以下項目：

- [ ] `SECRET_KEY` 已設置（必須）
- [ ] `DATABASE_TYPE` 已設置（必須）
- [ ] `DATABASE_URL` 已設置或由 Render 自動提供（必須）
- [ ] `SUPER_ADMIN_EMAIL` 已設置（可選，建議設置）
- [ ] `SUPER_ADMIN_PASSWORD` 已設置（可選，建議設置）
- [ ] `SMTP_EMAIL` 和 `SMTP_PASSWORD` 已設置（如果需要發送郵件）

---

## 🔍 故障排除

### 問題 1：無法登入

**可能原因**：
- 環境變數沒有正確設置
- 應用沒有重新部署

**解決方法**：
1. 檢查環境變數是否正確設置
2. 確認 Render 已經重新部署
3. 查看部署日誌確認沒有錯誤
4. 嘗試使用默認帳號：`admin@xingwang.com` / `12345678`

### 問題 2：資料庫連接失敗

**可能原因**：
- `DATABASE_TYPE` 設置錯誤
- `DATABASE_URL` 格式錯誤
- 資料庫服務未啟動

**解決方法**：
1. 確認 `DATABASE_TYPE` 設置為 `postgresql` 或 `mysql`
2. 檢查 `DATABASE_URL` 格式是否正確
3. 確認資料庫服務正在運行
4. 查看應用日誌獲取詳細錯誤信息

### 問題 3：環境變數沒有生效

**可能原因**：
- 環境變數設置後沒有重新部署
- 環境變數名稱拼寫錯誤

**解決方法**：
1. 確認環境變數名稱拼寫正確（區分大小寫）
2. 點擊 "Save Changes" 後等待重新部署
3. 查看部署日誌確認環境變數已加載

---

## 📝 快速參考

### 最小配置（可以測試登入）

```bash
SECRET_KEY=your-secret-key-here
DATABASE_TYPE=postgresql
# DATABASE_URL 由 Render 自動提供
```

使用默認帳號登入：
- 郵箱：`admin@xingwang.com`
- 密碼：`12345678`

### 完整配置（生產環境）

```bash
SECRET_KEY=your-very-secure-random-key-here
DATABASE_TYPE=postgresql
SUPER_ADMIN_EMAIL=your-admin@example.com
SUPER_ADMIN_PASSWORD=your-secure-password
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

---

## 🎉 完成！

設置完成後，你就可以：
- ✅ 訪問應用
- ✅ 使用設置的帳號密碼登入
- ✅ 測試所有功能

**默認測試帳號**（如果沒有設置環境變數）：
- 郵箱：`admin@xingwang.com`
- 密碼：`12345678`

---

## 📚 相關文檔

- [Render 部署指南](./RENDER_DEPLOYMENT.md)
- [TiDB Cloud 設置指南](./TIDB_CLOUD_SETUP.md)
- [三個環境配置說明](./三個環境配置說明.md)
- [如何修改管理員密碼](./HOW_TO_CHANGE_ADMIN_PASSWORD.md)

