
📋 項目概述
星旺授權管理系統 - 完整的用戶服務管理平台，支援管理員CRUD操作、郵件驗證、用戶自助註冊、服務分配與管理

✅ **最新更新 (2026-01-01)**
- 實現完整的用戶服務管理系統
- 統一管理員與用戶登入入口
- 新增服務管理與用戶服務分配功能
- 改進UI/UX設計，響應式布局
- 修復日期顯示時區問題
- 移除無效的個人資料連結
- 完善修改密碼功能
- **🆕 超級管理員系統**：實現不可修改的超級管理員機制
- **🆕 權限分級管理**：超級管理員可隨心所欲，普通管理員只能提升用戶
- **🆕 統計數據統一**：儀表板與用戶管理頁面統計邏輯一致
- **🆕 防呆機制**：防止註冊超級管理員郵箱，防止權限衝突
- **🆕 配置集中化**：所有超級管理員設定統一在 config.py 管理
- **🆕 統一時區系統**：全站統一使用智利時區 (America/Santiago)，所有時間相關操作均使用 `utils/time_utils.py` 提供的時間函數
- **🆕 ITI/ZOFRI 監控系統**：實現多用戶監控任務管理，支持外部 cron job 觸發
- **🆕 國際化支持**：用戶界面支持西班牙語

🗂️ 完整文件結構

FLASKPYTHONANYWHERE/
├── app.py                           # 主應用入口，路由定義
├── config.py                        # 配置管理（SMTP、密碼規則、管理員帳號）
├── database.py                      # 資料庫管理與初始化
├── requirements.txt                 # Python依賴包清單
├── blueprints/                      # 模組化路由
│   ├── __init__.py                  # Blueprint包初始化
│   ├── user_auth_bp.py              # 用戶認證Blueprint（註冊、登入、密碼管理）
│   └── api_auth_bp.py               # API認證Blueprint（JWT token、外部APP集成）
├── services/                        # 業務邏輯服務層
│   ├── __init__.py                  # Services包初始化
│   ├── email_service.py             # 郵件服務（驗證碼發送、驗證）
│   └── user_service.py              # 用戶服務（CRUD、密碼管理、驗證）
├── utils/                           # 工具函數
│   ├── __init__.py                  # Utils包初始化
│   ├── validators.py                # 驗證工具（郵箱、密碼、用戶名等）
│   └── time_utils.py                # 時間工具（智利時區時間函數）
├── databases/                       # 資料庫文件
│   └── app.db                       # SQLite主資料庫
├── templates/                       # HTML模板
│   ├── admin/                       # 管理員頁面模板
│   │   ├── base.html                # 管理員基礎模板
│   │   ├── sidebar.html             # 管理員側邊欄
│   │   ├── dashboard.html           # 管理員儀表板
│   │   ├── users.html               # 用戶管理頁面
│   │   ├── services.html            # 服務管理頁面
│   │   ├── user_services.html       # 用戶服務管理頁面
│   │   └── database.html            # 資料庫瀏覽頁面
│   └── user/                        # 用戶頁面模板
│       ├── base.html                # 用戶基礎模板
│       ├── sidebar.html             # 用戶側邊欄
│       ├── login.html               # 統一登入頁面
│       ├── register.html            # 用戶註冊頁面
│       ├── portal.html              # 用戶門戶頁面
│       ├── services.html            # 我的服務頁面
│       ├── change_password.html     # 修改密碼頁面
│       └── forgot_password.html     # 忘記密碼頁面
├── static/                          # 靜態資源
│   ├── css/                         # 樣式文件
│   │   ├── style.css                # 通用樣式
│   │   ├── admin.css                # 管理員頁面樣式
│   │   └── user.css                 # 用戶頁面樣式
│   └── js/                          # JavaScript文件
│       ├── admin.js                 # 管理員頁面腳本
│       └── user.js                  # 用戶頁面腳本
└── __pycache__/                     # Python緩存目錄（自動生成）
🗄️ 資料庫設計 (app.db)

**users 表** - 用戶基本資料
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**services 表** - 服務產品目錄
```sql
CREATE TABLE services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    duration_days INTEGER NOT NULL,
    price DECIMAL(10,2),
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**user_services 表** - 用戶服務分配記錄
```sql
CREATE TABLE user_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    service_id INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (service_id) REFERENCES services(id)
);
```

**verification_codes 表** - 郵件驗證碼記錄
```sql
CREATE TABLE verification_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    code TEXT NOT NULL,
    purpose TEXT NOT NULL,
    expire_time TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**已移除的舊表**
- `licenses` 表 - 已被 `services` 和 `user_services` 表取代
📝 核心模組說明

**config.py** - 配置管理中心
* 環境變數管理（SECRET_KEY、SMTP設定、超級管理員密碼）
* Gmail SMTP 設定（smtp.gmail.com:587）
* 功能開關（用戶註冊、郵件驗證）
* 密碼規則配置（8位數字，必須包含數字）
* **🆕 超級管理員配置**（admin@xingwang.com / 12345678 / super_admin）
  - 支持從環境變數讀取密碼（生產環境強烈推薦）
  - 備案默認值僅用於開發環境
  - 設置方式：`export SUPER_ADMIN_PASSWORD="your_secure_password"`
* **🆕 權限角色定義**（user、admin、super_admin）
* ✅ 支援跨平台路徑配置
* ✅ 集中化配置管理，避免硬編碼
* ✅ 安全配置驗證（啟動時檢查環境變數）

**database.py** - 資料庫管理
* 初始化所有表（users、services、user_services、verification_codes）
* 提供 get_db_connection() 函數
* 預設服務數據初始化
* ✅ 自動創建資料庫目錄
* ✅ 移除舊 licenses 表

**services/email_service.py** - 郵件服務
* send_verification_code(email, purpose) - 發送驗證碼
* verify_code(email, code, purpose) - 驗證驗證碼
* save_verification_code() - 保存驗證碼到資料庫
* 使用 Gmail SMTP (smtp.gmail.com:587)
* HTML 郵件模板（註冊、密碼重設）

**services/user_service.py** - 用戶服務
* create_user(username, email, password) - 創建用戶 (SHA256 加密)
* verify_password(email, password) - 驗證密碼
* change_password(email, old_password, new_password) - 修改密碼
* reset_password(email, new_password) - 重置密碼
* email_exists(email) - 檢查郵箱是否存在
* username_exists(username) - 檢查用戶名是否存在
* get_user_by_email() - 獲取用戶信息
* delete_user() - 刪除用戶
* **🆕 超級管理員保護**：防止註冊超級管理員郵箱

**utils/validators.py** - 驗證工具
* validate_email(email) - 郵箱格式驗證
* validate_password(password) - 密碼強度驗證（8位數字+數字）
* validate_username(username) - 用戶名驗證
* validate_verification_code(code) - 驗證碼驗證

**blueprints/user_auth_bp.py** - 用戶認證模組
* /user/register - 用戶註冊頁面與API
* /user/login - 用戶登入（已統一到主登入頁面）
* /user/portal - 用戶門戶頁面
* /user/forgot-password - 忘記密碼頁面與API
* /user/change-password - 修改密碼頁面與API
* /user/check-email - 郵箱可用性檢查API
* **🆕 超級管理員保護**：防止註冊、驗證碼發送、郵箱檢查等操作使用超級管理員郵箱

**blueprints/api_auth_bp.py** - API認證模組（外部APP集成）
* /api/login - API登入（返回JWT token）
* /api/verify - 驗證JWT token有效性
* /api/user/info - 獲取用戶詳細信息
* /api/user/services - 獲取用戶服務列表
* /api/user/services/active - 獲取用戶活躍服務
* /api/check-service - 檢查特定服務訪問權限
* /api/refresh-token - 刷新JWT token

**app.py** - 主應用路由
* / - 首頁重定向
* /login - 統一登入頁面（管理員+用戶）
* /logout - 登出
* /admin - 管理員儀表板
* /admin/users - 用戶管理
* /admin/services - 服務管理
* /admin/user-services - 用戶服務管理
* /admin/database - 資料庫瀏覽
* /user/services - 用戶服務頁面
* /user/services/api - 用戶服務API
* **🆕 超級管理員優先登入**：優先檢查超級管理員憑證
* **🆕 權限分級控制**：超級管理員可降級管理員，普通管理員不能
* **🆕 統計數據統一**：儀表板包含超級管理員統計
* **🆕 超級管理員保護**：防止修改、刪除超級管理員
🔑 完整功能列表

**🔐 認證系統**
* 統一登入入口（管理員+用戶）
* **🆕 超級管理員帳號**：admin@xingwang.com / 12345678（不可修改、不可刪除）
* **🆕 權限分級**：super_admin（超級管理員）、admin（普通管理員）、user（普通用戶）
* 用戶註冊（郵箱驗證）
* 密碼重設（郵件驗證）
* 密碼修改（需驗證舊密碼）
* Session 管理與權限控制
* **🆕 防呆機制**：防止註冊超級管理員郵箱

**👥 用戶管理**
* 用戶註冊與驗證
* 用戶列表查看
* **🆕 權限分級管理**：
  - 超級管理員：可隨心所欲，降級任何管理員
  - 普通管理員：可提升用戶為管理員，不能降級管理員
  - 普通用戶：只能管理自己的資料
* 用戶角色管理（user/admin/super_admin）
* 用戶密碼重置
* 用戶服務分配
* 用戶刪除
* **🆕 超級管理員保護**：超級管理員不可修改、不可刪除

**🛍️ 服務管理**
* 服務產品CRUD操作
* 服務狀態管理（active/inactive）
* 服務有效期設定
* 預設服務初始化

**📋 用戶服務管理**
* 為用戶分配服務
* 服務有效期管理
* 服務狀態控制
* 批量服務操作
* 服務歷史記錄

**📊 管理員儀表板**
* **🆕 統一統計邏輯**：儀表板與用戶管理頁面統計數據一致
* 用戶統計（總數、管理員數、普通用戶數、超級管理員數）
* 服務統計（總數、啟用數）
* 資料庫瀏覽
* 系統狀態監控
* **🆕 超級管理員統計**：包含超級管理員在內的完整統計

**👤 用戶門戶**
* 個人服務查看
* 密碼修改
* 帳號概覽
* 響應式設計

**📧 郵件系統**
* Gmail SMTP 整合
* 驗證碼發送
* HTML 郵件模板
* 郵件驗證流程

**🎨 前端特性**
* 響應式設計（手機/平板/桌面）
* 現代化UI/UX
* Modal 編輯彈窗
* AJAX 數據交互
* 實時表單驗證
* 側邊欄導航
⚙️ 配置需求

**環境變數 (可選)**
```bash
SECRET_KEY=your-secret-key-here
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password

# 資料庫配置（三選一）
# 本地開發 / PythonAnywhere (SQLite)
DATABASE_TYPE=sqlite
DATABASE_PATH=/path/to/databases/app.db

# Render (PostgreSQL)
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql://user:password@host:port/database
```

**詳細配置說明**: 見 `DATABASE_TYPE_CONFIG.md`

**Gmail SMTP 設定**
* SMTP Server: smtp.gmail.com
* Port: 587 (TLS)
* 需要應用程式密碼（16位）
* 必須開啟兩步驟驗證

**密碼規則**
* 最少8位字符
* 必須包含數字
* 不區分大小寫
* **🆕 超級管理員密碼**：12345678（不可修改）
* **🆕 普通管理員密碼**：可通過重置功能修改

**✅ 已修復的問題**
* 資料庫路徑自動配置 (支援 Windows/Linux)
* Blueprint 導入路徑問題
* Unicode 編碼問題
* 日期顯示時區問題
* 修改密碼500錯誤
* 無效連結清理
* **🆕 權限邏輯錯誤**：修復普通管理員無法降級管理員的權限問題
* **🆕 統計數據不一致**：修復儀表板與用戶管理頁面統計數據不匹配
* **🆕 硬編碼問題**：移除所有硬編碼，統一使用 config.py 配置
* **🆕 登入衝突**：修復超級管理員郵箱重複導致的登入混亂
* **🆕 權限檢查錯誤**：修復超級管理員無法訪問管理頁面的問題
* **🆕 代碼清理**：移除不必要的 ESLint 配置文件

🚀 部署環境
* **平台**: PythonAnywhere / Windows 本地開發
* **資料庫**: SQLite (app.db)
* **Python**: 3.8+
* **依賴**: Flask 2.3.3, Werkzeug 2.3.7
* **前端**: HTML5, CSS3, JavaScript (ES6+)
* **郵件**: Gmail SMTP
* **時區**: 智利時區 (America/Santiago)

⏰ **時區配置說明**
* **統一使用智利時區** (America/Santiago):
  - 所有模組統一使用智利時區，確保時間一致性
  - 時間工具函數：`utils/time_utils.py`
    - `get_chile_time()`: 獲取智利當前時間（帶時區信息）
    - `get_chile_time_naive()`: 獲取智利當前時間（無時區信息，用於與資料庫記錄比較）
* **使用智利時區的模組**:
  - `app.py`: 服務過期檢查、日期比較
  - `blueprints/api_auth_bp.py`: 會話記錄、JWT token 過期時間、用戶活動時間
  - `blueprints/monitor_bp.py`: 監控任務時間記錄
  - `services/monitor_service.py`: 監控檢查時間、郵件通知時間
  - `services/email_service.py`: 驗證碼過期時間
  - `services/user_service.py`: 用戶創建時間
  - `database.py`: 資料庫記錄時間
* **前端顯示** (`templates/admin/user_sessions.html`):
  - 使用 JavaScript `timeZone: 'America/Santiago'` 顯示智利時間
  - 所有時間相關顯示均轉換為智利時區
📋 代碼生成要求
優先級
1. 高: config.py, database.py, admin_bp.py (重構), app.py
2. 中: email_service.py, user_service.py, validators.py
3. 低: decorators.py, user_auth_bp.py (預留)
代碼風格
* 中文註釋
* 錯誤處理 (try-except)
* 參數化 SQL 查詢 (防注入)
* 密碼 SHA256 加密
* 簡潔函數命名
兼容性
* 保持現有路由不變
* 支援舊 licenses.db 遷移
* 前端 HTML/JS 盡量不改
🎯 核心流程
管理員登入流程

用戶訪問 /login 
→ 輸入密碼 
→ 驗證 hash 
→ 設置 session['logged_in'] 
→ 重定向到 /admin
授權查詢 API

GET /licenses/check_license?rut=76315010-0
→ 查詢 licenses 表
→ 返回 JSON: {rut, empresa, estado, fecha_expiracion}
郵件驗證流程 (預留)

用戶註冊 
→ 生成 6 位驗證碼 
→ 存入 verification_codes 表 
→ 發送郵件 
→ 用戶輸入驗證碼 
→ 驗證通過創建用戶
🚀 快速啟動

**本地開發**
```bash
cd FLASKPYTHONANYWHERE
pip install -r requirements.txt
python app.py
```

**訪問地址**
* **統一登入**: http://localhost:5000/login
* **管理員帳號**: admin@xingwang.com / 12345678
  - 🔐 **修改帳號和密碼**: 直接修改 `config.py` 第 44-45 行即可（最簡單！）
  - 📄 **修改說明**: 詳見 `HOW_TO_CHANGE_ADMIN_PASSWORD.md`
  - 🔍 **檢查工具**: 運行 `python check_admin_credentials.py` 查看當前使用的登入信息
* **管理員儀表板**: http://localhost:5000/admin
* **用戶註冊**: http://localhost:5000/user/register
* **用戶門戶**: http://localhost:5000/user/portal

**主要功能頁面**
* 用戶管理: http://localhost:5000/admin/users
* 服務管理: http://localhost:5000/admin/services
* 用戶服務: http://localhost:5000/admin/user-services
* 資料庫瀏覽: http://localhost:5000/admin/database
* 我的服務: http://localhost:5000/user/services

**✅ 測試狀態**
* ✅ 應用程式啟動成功
* ✅ 資料庫初始化完成
* ✅ 統一登入功能正常
* ✅ 管理員功能完整
* ✅ 用戶註冊與驗證正常
* ✅ 服務管理功能正常
* ✅ 用戶服務分配正常
* ✅ 郵件驗證功能正常
* ✅ 修改密碼功能正常

---

## 🚀 部署指南

### 📋 支持的部署平台

本系統支持兩種部署方式：

1. **PythonAnywhere** - 使用 SQLite 資料庫（本地文件）
2. **Render** - 使用 PostgreSQL 資料庫（雲端資料庫）

兩種方式都完全支持，系統會根據配置自動選擇資料庫類型。

---

## 🚀 PythonAnywhere 部署指南（SQLite）

### ✅ 部署前檢查項目

#### 1. 依賴包檢查
- [x] Flask==2.3.3
- [x] Werkzeug==2.3.7
- [x] PyJWT==2.8.0
- [x] pytz==2023.3 (智利時區支持)
- [x] pandas==2.1.3 (監控服務需要)
- [x] requests==2.31.0 (ZOFRI/ITI 爬蟲需要)

#### 2. 功能模組檢查
- [x] 用戶認證系統 (登入/註冊/密碼管理)
- [x] 管理員系統 (超級管理員/普通管理員)
- [x] 服務管理系統 (服務 CRUD/用戶服務分配)
- [x] ITI/ZOFRI 監控系統 (多用戶監控任務)
- [x] 會話管理系統 (用戶會話追蹤)
- [x] 郵件服務 (驗證碼發送)

#### 3. 資料庫檢查
- [x] SQLite 資料庫路徑配置正確
- [x] 資料庫初始化腳本正常
- [x] 所有表結構已定義

#### 4. 配置檢查
- [x] `config.py` 配置完整
- [x] 郵件 SMTP 配置 (email_config)
- [x] 管理員配置 (admin_config)
- [x] SECRET_KEY 配置

### 🔧 部署步驟

#### 1. 上傳文件
上傳所有文件到 PythonAnywhere，確保文件結構完整

#### 2. 安裝依賴
```bash
pip3.10 install --user -r requirements.txt
```

#### 3. 設置 WSGI 文件
```python
# /var/www/yourusername_pythonanywhere_com_wsgi.py
import sys
path = '/home/yourusername/path/to/your/app'
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application
```

#### 4. 設置靜態文件
- Static files: `/static/` → `/home/yourusername/path/to/your/app/static/`

#### 5. 資料庫初始化
```bash
python3.10 -c "from database import init_database; init_database(); print('Database initialized')"
```

#### 6. 環境變數（可選，強烈建議生產環境設置）
```bash
# 在 Web 設置中配置環境變數（PythonAnywhere）
# 或在 .env 文件中設置（本地開發）

# 資料庫路徑（可選）
DATABASE_PATH=/path/to/database

# Flask 密鑰（生產環境必須更改）
SECRET_KEY=your-secret-key-change-in-production

# 超級管理員配置（強烈建議生產環境設置，避免密碼泄露）
SUPER_ADMIN_EMAIL=admin@xingwang.com
SUPER_ADMIN_PASSWORD=your_secure_password_here
SUPER_ADMIN_USERNAME=super_admin

# SMTP 郵件配置（如果使用郵件功能）
SMTP_EMAIL=your-email@gmail.com
SMTP_PASSWORD=your-app-password
```

**⚠️ 安全提示**：
- 生產環境務必設置 `SUPER_ADMIN_PASSWORD` 環境變數，避免密碼硬編碼在代碼中
- 如果未設置環境變數，系統會使用 `config.py` 中的備案默認值（僅用於開發環境）
- 建議使用強密碼（至少12位，包含大小寫字母、數字和特殊字符）

#### 7. 測試檢查清單
- [ ] 訪問首頁，確認重定向正常
- [ ] 測試管理員登入
- [ ] 測試用戶註冊/登入
- [ ] 測試服務管理功能
- [ ] 測試監控任務管理
- [ ] 測試郵件發送功能

### ⚠️ 部署注意事項

1. **時區設置**：PythonAnywhere 服務器可能在不同時區，但系統已統一使用智利時區，無需額外配置

2. **資料庫權限**：確保 SQLite 資料庫文件有讀寫權限

3. **郵件配置**：確認 SMTP 配置在生產環境中正確設置

4. **SSL/HTTPS**：生產環境建議啟用 HTTPS

5. **SECRET_KEY**：生產環境務必更改 SECRET_KEY

6. **Cron Job 設置**：如果使用外部 cron job 觸發監控 API，確保 URL 正確配置

### 🎉 部署完成後

- [ ] 確認所有功能正常運作
- [ ] 測試監控 API 端點
- [ ] 確認郵件發送正常
- [ ] 檢查日誌無錯誤
- [ ] 設置定時任務（如需要）

**狀態**: ✅ 準備就緒，可以部署

---

## 🚀 Render 部署指南（PostgreSQL）

### ✅ 部署前準備

1. **創建 Render 帳號**
   - 訪問 https://render.com
   - 註冊並登入帳號

2. **創建 PostgreSQL 資料庫**
   - 在 Render Dashboard 點擊 "New +" → "PostgreSQL"
   - 選擇免費方案（Free）或付費方案
   - 記下資料庫連接資訊（Render 會自動提供 `DATABASE_URL` 環境變數）

3. **準備代碼倉庫**
   - 將代碼推送到 GitHub/GitLab/Bitbucket
   - 確保 `requirements.txt` 包含 `psycopg2-binary==2.9.9`

### 🔧 部署步驟

1. **創建 Web Service**
   - 在 Render Dashboard 點擊 "New +" → "Web Service"
   - 連接你的 Git 倉庫
   - 選擇分支（通常是 `main` 或 `master`）

2. **配置構建設置**
   ```
   Build Command: pip install -r requirements.txt
   Start Command: gunicorn app:app
   ```

3. **設置環境變數**
   在 Render Dashboard 的 Environment 部分添加：
   ```
   SECRET_KEY=your-secret-key-here
   DATABASE_TYPE=postgresql
   DATABASE_URL=postgresql://user:password@host:port/database
   SMTP_EMAIL=your@gmail.com
   SMTP_PASSWORD=your-app-password
   ```
   
   **注意**：
   - `DATABASE_URL` 會由 Render 自動提供（如果你在 Render 創建了 PostgreSQL 資料庫）
   - 如果手動設置，格式為：`postgresql://user:password@host:port/database`
   - `DATABASE_TYPE=postgresql` 必須設置，否則系統會使用 SQLite

4. **初始化資料庫**
   - 部署完成後，訪問你的應用 URL
   - 系統會自動初始化資料庫表（首次訪問時）
   - 或者手動運行：在 Render Shell 中執行：
     ```bash
     python database.py
     ```

5. **驗證部署**
   - 訪問應用首頁
   - 使用超級管理員帳號登入（`config.py` 中配置的帳號密碼）
   - 檢查資料庫是否正常連接

### ⚠️ Render 部署注意事項

1. **資料庫連接**
   - Render 會自動提供 `DATABASE_URL` 環境變數
   - 確保 `DATABASE_TYPE=postgresql` 已設置
   - 系統會自動使用 PostgreSQL 連接

2. **時區設置**
   - Render 服務器可能在不同時區，但系統已統一使用智利時區
   - 所有時間操作都使用 `utils/time_utils.py` 提供的函數

3. **靜態文件**
   - Render 會自動處理靜態文件
   - 確保 `static/` 目錄結構正確

4. **環境變數管理**
   - 所有敏感資訊（如 SMTP 密碼）都應通過環境變數設置
   - 超級管理員帳號密碼在 `config.py` 中直接配置（可選，也可通過環境變數）

5. **免費方案限制**
   - Render 免費方案會在 15 分鐘無活動後休眠
   - 首次訪問可能需要等待幾秒鐘喚醒服務

### 🎉 Render 部署完成後

**訪問地址**: https://your-app-name.onrender.com

**測試功能**:
- ✅ 登入頁面
- ✅ 用戶註冊
- ✅ 管理員儀表板
- ✅ 資料庫連接

**狀態**: ✅ 準備就緒，可以部署

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

## ⚙️ 動態配置管理系統

### 🎯 系統概述

這是一個混合配置管理系統，支持硬編碼默認值 + 遠程動態配置，為應用提供靈活的參數管理。

### ✨ 主要特性

- **混合配置**：硬編碼默認值 + 遠程動態配置
- **版本控制**：支持 FREE/PRO/ULTRA 不同版本參數
- **自動降級**：遠程配置失敗時自動使用硬編碼默認值
- **緩存機制**：5分鐘配置緩存，減少 API 調用
- **管理界面**：Web 界面管理不同版本的配置參數
- **API 支持**：RESTful API 獲取和更新配置

### 🚀 快速開始

#### 1. 初始化配置
```bash
python init_config.py
```

#### 2. 在 Python 應用中使用
```python
from utils.remote_config_manager import RemoteConfigManager

# 創建配置管理器
config_manager = RemoteConfigManager(
    api_base_url="http://localhost:5000",
    api_token="your_jwt_token_here"
)

# 獲取配置
config = config_manager.get_config("Zofri_Compra_Venta", "PRO")

# 使用配置參數
max_downloads = config['max_concurrent_downloads']
batch_enabled = config['features']['batch_download']
```

#### 3. 使用裝飾器
```python
from utils.remote_config_manager import with_remote_config

@with_remote_config("Zofri_Compra_Venta", "PRO")
def process_data(self, config, *args, **kwargs):
    max_downloads = config['max_concurrent_downloads']
    # 使用配置處理數據
```

### 🌐 API 端點

#### 獲取配置
```http
GET /api/config?service_name=Zofri_Compra_Venta&version=PRO
Authorization: Bearer <token>
```

#### 更新配置（管理員）
```http
POST /api/config/update
Authorization: Bearer <token>
Content-Type: application/json

{
  "service_name": "Zofri_Compra_Venta",
  "version": "PRO",
  "config": {
    "max_concurrent_downloads": 8,
    "features": {
      "batch_download": true
    }
  }
}
```

### 🎛️ 管理界面

訪問 `http://localhost:5000/admin/config` 可以：
- 切換不同版本（FREE/PRO/ULTRA）
- 調整並行處理參數
- 開關功能選項
- 保存和重置配置

### 🛡️ 錯誤處理

系統具有完善的錯誤處理機制：
1. **遠程配置失敗**：自動使用硬編碼默認值
2. **API 超時**：5秒超時，自動降級
3. **配置解析錯誤**：使用默認配置
4. **網絡問題**：緩存機制減少影響
* ✅ 響應式設計正常

**📁 未使用的文件**
* `static/css/user.css` - 用戶頁面樣式（已整合到各模板中）
* `requirements.txt` - 依賴包清單（保留用於部署）

**🎯 項目特色**
* 完整的用戶服務管理系統
* 現代化響應式UI設計
* 統一的登入入口
* 完善的權限控制
* 安全的密碼管理
* 郵件驗證系統
* 模組化架構設計
* JWT API認證系統（外部APP集成）

## 🔌 API 文檔

### 認證系統

#### 1. 用戶登入
```http
POST /api/login
Content-Type: application/json

{
    "email": "user@example.com",
    "password": "12345678"
}
```

**成功響應：**
```json
{
    "success": true,
    "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "user_info": {
        "id": 1,
        "username": "testuser",
        "email": "user@example.com",
        "role": "user",
        "created_at": "2025-01-01 00:00:00"
    },
    "expires_in": 86400
}
```

#### 2. 驗證Token
```http
POST /api/verify
Authorization: Bearer <token>
```

**成功響應：**
```json
{
    "success": true,
    "user_info": {
        "id": 1,
        "username": "testuser",
        "email": "user@example.com",
        "role": "user"
    }
}
```

#### 3. 獲取用戶詳細信息
```http
GET /api/user/info
Authorization: Bearer <token>
```

#### 4. 刷新Token
```http
POST /api/refresh-token
Authorization: Bearer <token>
```

### 服務管理

#### 5. 獲取用戶所有服務
```http
GET /api/user/services
Authorization: Bearer <token>
```

**響應：**
```json
{
    "success": true,
    "services": [
        {
            "id": 1,
            "name": "基礎服務",
            "description": "基礎功能服務",
            "duration_days": 30,
            "price": 99.99,
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "status": "active",
            "created_at": "2025-01-01 00:00:00"
        }
    ],
    "count": 1
}
```

#### 6. 獲取用戶活躍服務
```http
GET /api/user/services/active
Authorization: Bearer <token>
```

#### 7. 檢查特定服務權限
```http
POST /api/check-service
Authorization: Bearer <token>
Content-Type: application/json

{
    "service_name": "基礎服務"
}
```

**響應：**
```json
{
    "success": true,
    "has_access": true,
    "service_info": {
        "id": 1,
        "name": "基礎服務",
        "description": "基礎功能服務",
        "start_date": "2025-01-01",
        "end_date": "2025-01-31",
        "status": "active"
    }
}
```

### 錯誤處理

所有API都返回統一的錯誤格式：
```json
{
    "success": false,
    "error": "錯誤描述"
}
```

**常見HTTP狀態碼：**
- `200` - 成功
- `400` - 請求參數錯誤
- `401` - 認證失敗（無效token或憑證錯誤）
- `404` - 資源不存在
- `500` - 服務器內部錯誤

### 使用示例

#### Python 客戶端示例
```python
import requests

# 登入獲取token
login_data = {
    "email": "user@example.com",
    "password": "12345678"
}
response = requests.post("http://localhost:5000/api/login", json=login_data)
token = response.json()["token"]

# 使用token訪問受保護的API
headers = {"Authorization": f"Bearer {token}"}
response = requests.get("http://localhost:5000/api/user/info", headers=headers)
user_info = response.json()
```

#### JavaScript 客戶端示例
```javascript
// 登入獲取token
const loginData = {
    email: "user@example.com",
    password: "12345678"
};

fetch("http://localhost:5000/api/login", {
    method: "POST",
    headers: {
        "Content-Type": "application/json"
    },
    body: JSON.stringify(loginData)
})
.then(response => response.json())
.then(data => {
    const token = data.token;
    
    // 使用token訪問受保護的API
    return fetch("http://localhost:5000/api/user/info", {
        headers: {
            "Authorization": `Bearer ${token}`
        }
    });
})
.then(response => response.json())
.then(userInfo => console.log(userInfo));
```

## 📋 API 使用規則與最佳實踐

### 🔐 認證規則

#### **JWT Token 管理**
- **Token 有效期**: 24小時（86400秒）
- **刷新機制**: 使用 `/api/refresh-token` 延長有效期
- **存儲建議**: 將token存儲在安全的地方（如HttpOnly Cookie或安全存儲）
- **傳遞方式**: 在 `Authorization` header中使用 `Bearer <token>` 格式

#### **密碼規則**
- **最小長度**: 8位字符
- **必須包含**: 至少一個數字
- **格式要求**: 不區分大小寫
- **管理員密碼**: `12345678`（預設）

### 🚀 使用流程規則

#### **1. 標準登入流程**
```python
# 步驟1: 登入獲取token
login_response = requests.post("http://localhost:5000/api/login", json={
    "email": "admin@xingwang.com",
    "password": "12345678"
})

if login_response.status_code == 200:
    token = login_response.json()["token"]
    # 步驟2: 使用token訪問API
    headers = {"Authorization": f"Bearer {token}"}
```

#### **2. Token 驗證流程**
```python
# 在每次API調用前驗證token
verify_response = requests.post("http://localhost:5000/api/verify", 
                               headers=headers)
if verify_response.status_code != 200:
    # Token無效，需要重新登入
    pass
```

#### **3. 服務權限檢查流程**
```python
# 檢查用戶是否有特定服務權限
service_check = requests.post("http://localhost:5000/api/check-service", 
                             json={"service_name": "基礎服務"}, 
                             headers=headers)
has_access = service_check.json()["has_access"]
```

### ⚠️ 錯誤處理規則

#### **HTTP 狀態碼對應**
- **200**: 請求成功
- **400**: 請求參數錯誤（如缺少必要字段）
- **401**: 認證失敗（無效token或憑證錯誤）
- **404**: 資源不存在
- **500**: 服務器內部錯誤

#### **錯誤響應格式**
```json
{
    "success": false,
    "error": "具體錯誤描述"
}
```

#### **常見錯誤處理**
```python
def handle_api_response(response):
    if response.status_code == 200:
        data = response.json()
        if data.get("success"):
            return data
        else:
            raise Exception(f"API錯誤: {data.get('error')}")
    elif response.status_code == 401:
        raise Exception("認證失敗，請重新登入")
    elif response.status_code == 400:
        raise Exception("請求參數錯誤")
    else:
        raise Exception(f"服務器錯誤: {response.status_code}")
```

### 🔒 安全規則

#### **Token 安全**
- **不要**在URL中傳遞token
- **不要**在日誌中記錄token
- **定期刷新**token（建議每12小時）
- **及時清理**過期的token

#### **請求安全**
- **始終使用HTTPS**（生產環境）
- **驗證所有輸入**參數
- **限制請求頻率**（防止濫用）
- **記錄敏感操作**日誌

### 📊 服務管理規則

#### **服務狀態定義**
- **active**: 服務正常運行
- **inactive**: 服務已停用
- **expired**: 服務已過期

#### **服務權限檢查**
```python
# 檢查特定服務權限
def check_service_access(token, service_name):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post("http://localhost:5000/api/check-service", 
                           json={"service_name": service_name}, 
                           headers=headers)
    return response.json().get("has_access", False)
```

#### **活躍服務查詢**
```python
# 獲取用戶所有活躍服務
def get_active_services(token):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get("http://localhost:5000/api/user/services/active", 
                          headers=headers)
    return response.json().get("services", [])
```

### 🛠️ 開發規則

#### **API 調用封裝**
```python
class AuthAPI:
    def __init__(self, base_url="http://localhost:5000"):
        self.base_url = base_url
        self.token = None
    
    def login(self, email, password):
        response = requests.post(f"{self.base_url}/api/login", json={
            "email": email, "password": password
        })
        if response.status_code == 200:
            data = response.json()
            self.token = data["token"]
            return True
        return False
    
    def get_headers(self):
        if not self.token:
            raise Exception("未登入，請先調用login方法")
        return {"Authorization": f"Bearer {self.token}"}
    
    def get_user_info(self):
        response = requests.get(f"{self.base_url}/api/user/info", 
                              headers=self.get_headers())
        return response.json()
```

#### **重試機制**
```python
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_session_with_retries():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
```

### 📝 日誌記錄規則

#### **API 調用日誌**
```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log_api_call(method, url, status_code, response_time):
    logger.info(f"API調用: {method} {url} - 狀態: {status_code} - 耗時: {response_time}ms")
```

#### **錯誤日誌**
```python
def log_api_error(error, context=""):
    logger.error(f"API錯誤: {error} - 上下文: {context}")
```

### 🔄 版本控制規則

#### **API 版本管理**
- 當前版本: v1
- 向後兼容: 保持現有端點不變
- 新功能: 通過新端點添加
- 棄用通知: 提前3個月通知

#### **端點命名規範**
- 認證相關: `/api/auth/*`
- 用戶相關: `/api/user/*`
- 服務相關: `/api/services/*`
- 管理相關: `/api/admin/*`

### 📈 性能優化規則

#### **緩存策略**
- Token緩存: 24小時
- 用戶信息緩存: 1小時
- 服務列表緩存: 30分鐘

#### **請求優化**
- 批量查詢: 避免多次單個請求
- 分頁查詢: 大量數據使用分頁
- 字段選擇: 只請求需要的字段

### 🧪 測試規則

#### **單元測試**
```python
import unittest
from unittest.mock import patch, Mock

class TestAuthAPI(unittest.TestCase):
    def setUp(self):
        self.api = AuthAPI()
    
    @patch('requests.post')
    def test_login_success(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "token": "test_token"
        }
        mock_post.return_value = mock_response
        
        result = self.api.login("test@example.com", "password")
        self.assertTrue(result)
        self.assertEqual(self.api.token, "test_token")
```

#### **集成測試**
```python
def test_full_auth_flow():
    # 1. 登入
    login_response = requests.post("http://localhost:5000/api/login", json={
        "email": "admin@xingwang.com",
        "password": "12345678"
    })
    assert login_response.status_code == 200
    
    # 2. 使用token
    token = login_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3. 獲取用戶信息
    user_response = requests.get("http://localhost:5000/api/user/info", 
                               headers=headers)
    assert user_response.status_code == 200
```

### 🚨 故障排除規則

#### **常見問題**
1. **Token過期**: 使用refresh-token或重新登入
2. **網絡錯誤**: 檢查網絡連接和服務器狀態
3. **參數錯誤**: 檢查請求格式和必要字段
4. **權限不足**: 檢查用戶角色和服務權限

#### **調試步驟**
1. 檢查HTTP狀態碼
2. 查看錯誤響應內容
3. 驗證token有效性
4. 檢查服務器日誌
5. 測試網絡連接

### 📞 支持與維護

#### **監控指標**
- API響應時間
- 錯誤率
- Token使用率
- 服務可用性

#### **維護窗口**
- 定期維護: 每月第一個週日 2:00-4:00
- 緊急維護: 提前24小時通知
- 版本更新: 提前1週通知

---

**📌 重要提醒**
- 請定期更新API客戶端以獲得最新功能
- 遇到問題請先查看本文檔的故障排除部分
- 生產環境請使用HTTPS和安全的token存儲方式
- 建議實施適當的日誌記錄和監控機制 