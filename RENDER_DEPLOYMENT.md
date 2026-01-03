# 🚀 Render 部署指南

## 📋 概述

本系統現在支持兩種部署方式：
- **PythonAnywhere** - 使用 SQLite 資料庫（本地文件）
- **Render** - 使用 PostgreSQL 資料庫（雲端資料庫）

系統會根據 `DATABASE_TYPE` 環境變數自動選擇資料庫類型。

---

## ✅ 部署前準備

### 1. 創建 Render 帳號
- 訪問 https://render.com
- 註冊並登入帳號

### 2. 創建 PostgreSQL 資料庫
- 在 Render Dashboard 點擊 "New +" → "PostgreSQL"
- 選擇免費方案（Free）或付費方案
- 記下資料庫連接資訊（Render 會自動提供 `DATABASE_URL` 環境變數）

### 3. 準備代碼倉庫
- 將代碼推送到 GitHub/GitLab/Bitbucket
- 確保 `requirements.txt` 包含 `psycopg2-binary==2.9.9`

---

## 🔧 部署步驟

### 1. 創建 Web Service
- 在 Render Dashboard 點擊 "New +" → "Web Service"
- 連接你的 Git 倉庫
- 選擇分支（通常是 `main` 或 `master`）

### 2. 配置構建設置
```
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
```

### 3. 設置環境變數
在 Render Dashboard 的 Environment 部分添加：

```
SECRET_KEY=your-secret-key-here
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql://user:password@host:port/database
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

**重要說明**：
- `DATABASE_URL` 會由 Render 自動提供（如果你在 Render 創建了 PostgreSQL 資料庫）
- 如果手動設置，格式為：`postgresql://user:password@host:port/database`
- **`DATABASE_TYPE=postgresql` 必須設置**，否則系統會使用 SQLite

### 4. 初始化資料庫
- 部署完成後，訪問你的應用 URL
- 系統會自動初始化資料庫表（首次訪問時）
- 或者手動運行：在 Render Shell 中執行：
  ```bash
  python database.py
  ```

### 5. 驗證部署
- 訪問應用首頁
- 使用超級管理員帳號登入（`config.py` 中配置的帳號密碼）
- 檢查資料庫是否正常連接

---

## ⚠️ 部署注意事項

### 1. 資料庫連接
- Render 會自動提供 `DATABASE_URL` 環境變數
- 確保 `DATABASE_TYPE=postgresql` 已設置
- 系統會自動使用 PostgreSQL 連接

### 2. 時區設置
- Render 服務器可能在不同時區，但系統已統一使用智利時區
- 所有時間操作都使用 `utils/time_utils.py` 提供的函數

### 3. 靜態文件
- Render 會自動處理靜態文件
- 確保 `static/` 目錄結構正確

### 4. 環境變數管理
- 所有敏感資訊（如 SMTP 密碼）都應通過環境變數設置
- 超級管理員帳號密碼在 `config.py` 中直接配置（可選，也可通過環境變數）

### 5. 免費方案限制
- Render 免費方案會在 15 分鐘無活動後休眠
- 首次訪問可能需要等待幾秒鐘喚醒服務

---

## 🔄 資料庫類型切換

系統支持在 SQLite 和 PostgreSQL 之間切換，只需設置環境變數：

**PythonAnywhere (SQLite)**:
```bash
DATABASE_TYPE=sqlite
DATABASE_PATH=/path/to/databases/app.db
```

**Render (PostgreSQL)**:
```bash
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql://user:password@host:port/database
```

系統會根據 `DATABASE_TYPE` 自動選擇正確的資料庫連接方式。

---

## 🎉 部署完成後

**訪問地址**: https://your-app-name.onrender.com

**測試功能**:
- ✅ 登入頁面
- ✅ 用戶註冊
- ✅ 管理員儀表板
- ✅ 資料庫連接

**狀態**: ✅ 準備就緒，可以部署

---

## 📝 技術細節

### SQL 參數占位符
- SQLite 使用 `?` 作為參數占位符
- PostgreSQL 使用 `%s` 作為參數占位符
- 系統會自動適配，無需修改 SQL 語句

### 資料庫初始化
- 系統會自動檢測資料庫類型
- 根據類型創建相應的表結構
- 支持自動遷移和向後兼容

### 連接管理
- SQLite: 使用 `sqlite3` 模組
- PostgreSQL: 使用 `psycopg2` 模組
- 兩種方式都支持事務和連接池

