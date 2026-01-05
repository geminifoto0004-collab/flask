# 📋 星旺授權管理系統

完整的用戶服務管理平台，支援管理員CRUD操作、郵件驗證、用戶自助註冊、服務分配與管理

## ✅ 最新更新 (2026-01-01)

- 實現完整的用戶服務管理系統
- 統一管理員與用戶登入入口
- 新增服務管理與用戶服務分配功能
- 改進UI/UX設計，響應式布局
- **🆕 超級管理員系統**：實現不可修改的超級管理員機制
- **🆕 權限分級管理**：超級管理員可隨心所欲，普通管理員只能提升用戶
- **🆕 ITI/ZOFRI 監控系統**：實現多用戶監控任務管理，支持外部 cron job 觸發
- **🆕 國際化支持**：用戶界面支持西班牙語
- **🆕 統一時區系統**：全站統一使用智利時區 (America/Santiago)

---

## 🚀 快速開始

### 本地開發

```bash
cd FLASKPYTHONANYWHERE
pip install -r requirements.txt
python app.py
```

訪問：http://localhost:5000/login

**默認管理員帳號**：
- 郵箱：`admin@xingwang.com`
- 密碼：`12345678`

> 📄 **修改管理員密碼**：直接修改 `config.py` 第 44-45 行

---

## 🗂️ 項目結構

```
FLASKPYTHONANYWHERE/
├── app.py                    # 主應用入口，路由定義
├── config.py                 # 配置管理（SMTP、密碼規則、管理員帳號）
├── database.py               # 資料庫管理與初始化
├── requirements.txt          # Python依賴包清單
├── blueprints/               # 模組化路由
│   ├── user_auth_bp.py       # 用戶認證Blueprint
│   ├── api_auth_bp.py        # API認證Blueprint（JWT token）
│   └── monitor_bp.py         # 監控任務Blueprint
├── services/                 # 業務邏輯服務層
│   ├── email_service.py      # 郵件服務
│   ├── user_service.py       # 用戶服務
│   └── monitor_service.py    # 監控服務
├── utils/                    # 工具函數
│   ├── validators.py         # 驗證工具
│   └── time_utils.py         # 時間工具（智利時區）
├── templates/                # HTML模板
│   ├── admin/                # 管理員頁面
│   └── user/                 # 用戶頁面
└── static/                   # 靜態資源
    ├── css/                  # 樣式文件
    └── js/                   # JavaScript文件
```

---

## 🔑 核心功能

### 🔐 認證系統

- 統一登入入口（管理員+用戶）
- 超級管理員帳號（不可修改、不可刪除）
- 權限分級（super_admin、admin、user）
- 用戶註冊（郵件驗證）
- 密碼重設與修改
- Session 管理與權限控制

### 👥 用戶管理

- 用戶註冊與驗證
- 用戶列表查看
- 權限分級管理
- 用戶角色管理（user/admin/super_admin）
- 用戶密碼重置
- 用戶服務分配
- 用戶刪除

### 🛍️ 服務管理

- 服務產品CRUD操作
- 服務狀態管理（active/inactive）
- 服務有效期設定
- 用戶服務分配
- 服務歷史記錄

### 📊 管理員儀表板

- 用戶統計
- 服務統計
- 資料庫瀏覽
- 系統狀態監控

### 📧 郵件系統

- Gmail SMTP 整合
- Resend API 支持
- 驗證碼發送
- HTML 郵件模板

### 🔌 API 系統

- JWT Token 認證
- RESTful API
- 用戶信息查詢
- 服務權限檢查
- 外部APP集成支持

---

## 🚀 部署指南

系統支持多種部署方式，可根據需求選擇最適合的環境。

### 📋 支持的部署平台

| 平台 | 資料庫 | 推薦場景 |
|------|--------|----------|
| **本地開發** | SQLite | 開發和測試 |
| **PythonAnywhere** | SQLite | 簡單部署，免費方案 |
| **Render** | PostgreSQL | 現代化部署，免費方案 |
| **Render + TiDB Cloud** | TiDB/MySQL | 長期穩定運行 |

---

### 🖥️ 本地開發環境

#### 配置方式

**方法 1：使用 .env 文件（推薦）**

在項目根目錄創建 `.env` 文件：

```env
DATABASE_TYPE=sqlite
DATABASE_PATH=./databases/app.db
SECRET_KEY=your-secret-key-here
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

然後安裝 `python-dotenv`：
```bash
pip install python-dotenv
```

在 `app.py` 開頭添加：
```python
from dotenv import load_dotenv
load_dotenv()
```

**方法 2：設置環境變數**

Windows (PowerShell)：
```powershell
$env:DATABASE_TYPE="sqlite"
$env:DATABASE_PATH="C:\path\to\databases\app.db"
python app.py
```

Linux/Mac：
```bash
export DATABASE_TYPE=sqlite
export DATABASE_PATH=./databases/app.db
python app.py
```

---

### 🌐 PythonAnywhere 部署

1. **上傳文件** - 將所有文件上傳到 PythonAnywhere

2. **安裝依賴**
```bash
pip3.10 install --user -r requirements.txt
```

3. **設置 WSGI 文件**
```python
# /var/www/yourusername_pythonanywhere_com_wsgi.py
import sys
path = '/home/yourusername/path/to/your/app'
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application
```

4. **設置靜態文件** - Static files: `/static/` → `/home/yourusername/path/to/your/app/static/`

5. **配置環境變數** - 在 PythonAnywhere Dashboard → Web → Environment variables：
```bash
   DATABASE_TYPE=sqlite
   DATABASE_PATH=/home/yourusername/path/to/databases/app.db
   SECRET_KEY=your-secret-key-here
   SMTP_EMAIL=your@gmail.com
   SMTP_PASSWORD=your-app-password
   SUPER_ADMIN_EMAIL=admin@xingwang.com
   SUPER_ADMIN_PASSWORD=your_secure_password
   ```

6. **初始化資料庫**
```bash
   python3.10 -c "from database import init_database; init_database(); print('Database initialized')"
   ```

7. **重新載入** - 點擊 "Reload" 重新載入 Web app

---

### ☁️ Render 部署（PostgreSQL）

1. **創建 Render 帳號** - 訪問 https://render.com

2. **創建 PostgreSQL 資料庫**
   - 在 Render Dashboard 點擊 "New +" → "PostgreSQL"
   - 選擇免費方案（Free）
   - Render 會自動提供 `DATABASE_URL` 環境變數

3. **創建 Web Service**
   - 點擊 "New +" → "Web Service"
   - 連接你的 Git 倉庫
   - 選擇分支（通常是 `main` 或 `master`）

4. **配置構建設置**
   ```
   Build Command: pip install -r requirements.txt
   Start Command: gunicorn app:app
   ```

5. **設置環境變數** - 在 Render Dashboard → 你的 Web Service → "Environment" 標籤：
   ```bash
   SECRET_KEY=your-secret-key-here
   DATABASE_TYPE=postgresql
   # DATABASE_URL 由 Render 自動提供
   
   SUPER_ADMIN_EMAIL=admin@xingwang.com
   SUPER_ADMIN_PASSWORD=your_secure_password
   SMTP_EMAIL=your@gmail.com
   SMTP_PASSWORD=your-app-password
   ```

6. **生成 SECRET_KEY**
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

7. **部署和測試** - 點擊 "Save Changes"，Render 會自動部署

**注意**：Render 免費方案會在 15 分鐘無活動後休眠

---

### 🗄️ Render + TiDB Cloud 部署

TiDB Cloud 免費版永久免費，適合長期使用。

#### 步驟 1：創建 TiDB Cloud 集群

1. 訪問 https://tidbcloud.com 註冊帳號
2. 創建免費集群（Developer Tier）
3. 等待集群創建完成（狀態變為 "Available"）
4. 點擊 "Connect" 獲取連接信息（Host、Port、User、Password、Database）

#### 步驟 2：在 Render 設置環境變數

```bash
SECRET_KEY=your-secret-key-here
DATABASE_TYPE=mysql

# 方法 A：使用 DATABASE_URL（推薦）
DATABASE_URL=mysql://用戶名:密碼@主機:4000/數據庫名

# 方法 B：使用單獨的環境變數
MYSQL_HOST=gateway01.ap-northeast-1.prod.aws.tidbcloud.com
MYSQL_PORT=4000
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=test

SUPER_ADMIN_EMAIL=admin@xingwang.com
SUPER_ADMIN_PASSWORD=your_secure_password
```

**注意**：如果密碼包含特殊字符，需要 URL 編碼

#### 步驟 3：部署和驗證

1. 點擊 "Save Changes"，Render 會自動部署
2. 查看部署日誌，確認資料庫連接成功
3. 訪問應用測試登入

---

### 📧 郵件服務配置

#### Gmail SMTP（本地開發 / PythonAnywhere）

```bash
   SMTP_EMAIL=your@gmail.com
   SMTP_PASSWORD=your-app-password
   ```
   
**設置步驟**：
1. 登入 Google 帳號
2. 啟用兩步驟驗證
3. 生成應用程式密碼（16位）
4. 使用生成的密碼作為 `SMTP_PASSWORD`

#### Resend API（Render 推薦）

Resend 不受 Render 網絡限制，免費 3000 封/月。

1. **註冊 Resend** - 訪問 https://resend.com
2. **創建 API Key** - Dashboard → "API Keys" → "Create API Key"
3. **設置環境變數**：
     ```bash
   EMAIL_PROVIDER=resend
   RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   RESEND_FROM_EMAIL=onboarding@resend.dev
   ```

**注意**：測試域名 `onboarding@resend.dev` 只能發送到驗證過的郵箱

#### 其他 SMTP 服務

- **Mailgun**：免費 5000 封/月
- **Brevo (Sendinblue)**：免費 300 封/天
- **AWS SES**：按使用量付費，前 62,000 封免費

---

## 🗄️ 資料庫配置

系統支持三種資料庫類型，可根據部署環境選擇最適合的資料庫。

### 📋 支持的資料庫類型

| 資料庫類型 | DATABASE_TYPE | 使用場景 |
|-----------|--------------|----------|
| **SQLite** | `sqlite` | 本地開發、PythonAnywhere |
| **PostgreSQL** | `postgresql` | Render 部署 |
| **MySQL/TiDB** | `mysql` | Render + TiDB Cloud |

### 🔧 配置方式

#### SQLite 配置

```bash
DATABASE_TYPE=sqlite
DATABASE_PATH=./databases/app.db
```

#### PostgreSQL 配置

```bash
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql://user:password@host:port/database
```

#### MySQL/TiDB 配置

```bash
DATABASE_TYPE=mysql
DATABASE_URL=mysql://user:password@host:4000/database
```

或者使用單獨的環境變數：

```bash
DATABASE_TYPE=mysql
MYSQL_HOST=gateway01.ap-northeast-1.prod.aws.tidbcloud.com
MYSQL_PORT=4000
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=test
```

### ✅ 資料庫初始化

系統會在首次啟動時自動初始化資料庫：
1. 自動檢測資料庫類型
2. 自動創建所有表
3. 自動添加新列（向後兼容）
4. 初始化默認數據

手動初始化：
```bash
python database.py
```

### 🔍 檢查資料庫配置

運行檢查腳本：
```bash
python check_db_config.py
```

### 🔧 SQL 參數占位符適配

系統自動處理 SQLite 和 PostgreSQL/MySQL 的參數占位符差異：
- **SQLite**：使用 `?` 作為參數占位符
- **PostgreSQL/MySQL**：使用 `%s` 作為參數占位符

系統會自動適配，無需修改 SQL 語句。

---

## 👤 管理員配置

### 🔐 超級管理員系統

系統實現了分級權限管理系統，支持三種角色：
- **super_admin**：超級管理員（最高權限）
- **admin**：普通管理員
- **user**：普通用戶

### 🔑 修改超級管理員帳號和密碼

**最簡單的方法：直接修改 config.py**

1. 打開文件：`config.py`
2. 找到第 44-45 行：
```python
   SUPER_ADMIN_EMAIL = 'admin@xingwang.com'  # 修改這裡改帳號
   SUPER_ADMIN_PASSWORD = '12345678'  # 修改這裡改密碼
   ```
3. 修改後保存文件並重啟應用

### 🛠️ 使用環境變數（可選，更安全）

如果使用環境變數，系統會優先使用環境變數的值。

**Windows 系統**：
```cmd
set SUPER_ADMIN_PASSWORD=你的密碼
```

**Linux/Mac 系統**：
```bash
export SUPER_ADMIN_PASSWORD="你的密碼"
```

**PythonAnywhere**：
1. 登入 PythonAnywhere
2. 點擊頂部的 **Web** 標籤
3. 找到 **Environment variables** 區塊
4. 添加環境變數

**Render**：
1. 登入 Render Dashboard
2. 選擇你的 Web Service
3. 點擊左側 **"Environment"** 標籤
4. 添加環境變數

### 📋 認證機制說明

超級管理員的密碼驗證是通過 **代碼配置**（config.py 或環境變數）來完成的，**不是**通過數據庫。

**登入流程**：
```
用戶輸入帳號密碼 → 檢查是否為超級管理員郵箱 → 比較密碼與 config.py 或環境變數的值 → 登入成功/失敗 → 從數據庫獲取或創建用戶記錄
```

**優先級**：
1. **環境變數**（如果設置了）
2. **config.py 默認值**（如果環境變數未設置）

### 🔒 權限分級管理

**超級管理員（super_admin）**：
- ✅ 可以執行所有操作
- ✅ 可以降級任何管理員
- ✅ 可以修改任何用戶
- ✅ 不可修改、不可刪除自己

**普通管理員（admin）**：
- ✅ 可以查看和修改用戶
- ✅ 可以提升用戶為管理員
- ❌ **不能降級管理員**（只能超級管理員操作）
- ❌ 不能修改或刪除超級管理員

**普通用戶（user）**：
- ✅ 只能管理自己的資料
- ✅ 可以修改自己的密碼
- ✅ 可以查看自己的服務

### 🔍 檢查當前配置

運行檢查工具：
```bash
python check_admin_credentials.py
```

---

## 🔐 安全配置

### ⚠️ 重要安全提示

**請務必通過環境變數設置敏感信息，不要將密碼硬編碼在代碼中！**

### 🔒 必須設置的環境變數

#### 1. Flask 密鑰（SECRET_KEY）

**生成方法**：
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**設置環境變數**：
```bash
SECRET_KEY=生成的隨機字符串
```

#### 2. 超級管理員配置

```bash
SUPER_ADMIN_EMAIL=admin@xingwang.com
SUPER_ADMIN_PASSWORD=你的安全密碼
```

**注意**：
- 生產環境建議設置環境變數
- 使用強密碼（至少12位，包含大小寫字母、數字和特殊字符）
- 不要使用默認密碼 `12345678`（僅用於開發環境）

#### 3. SMTP 郵件配置（如果需要發送郵件）

```bash
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

或使用 Resend API：
```bash
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
RESEND_FROM_EMAIL=onboarding@resend.dev
```

### ✅ 安全檢查清單

部署前請確認：
- [ ] `SECRET_KEY` 已設置為隨機字符串（不是默認值）
- [ ] `SUPER_ADMIN_EMAIL` 已設置
- [ ] `SUPER_ADMIN_PASSWORD` 已設置（不是默認值 `12345678`）
- [ ] `SMTP_EMAIL` 和 `SMTP_PASSWORD` 已設置（如果需要郵件功能）
- [ ] 資料庫配置已正確設置
- [ ] `.env` 文件已添加到 `.gitignore`
- [ ] 沒有將敏感信息提交到 GitHub

### 🔍 環境變數說明

**環境變數**是操作系統提供的配置存儲方式，類似於"系統設置"。

**簡單比喻**：
- **硬編碼在代碼中** = 把密碼直接寫在紙上，放在桌子上（不安全）
- **環境變數** = 把密碼放在保險箱裡，只有系統知道密碼（安全）

**代碼中的使用方式**：
```python
# ❌ 不安全的方式（硬編碼）
SUPER_ADMIN_PASSWORD = '12345678'

# ✅ 安全的方式（環境變數）
SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', '12345678')
```

---

## ⚙️ 完整環境變數列表

### 必須設置（生產環境）

```bash
SECRET_KEY=your-secret-key-here
SUPER_ADMIN_EMAIL=admin@xingwang.com
SUPER_ADMIN_PASSWORD=your_secure_password
```

### 資料庫配置（必須設置一個）

```bash
# SQLite
DATABASE_TYPE=sqlite
DATABASE_PATH=./databases/app.db

# PostgreSQL
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql://user:password@host:port/database

# MySQL/TiDB
DATABASE_TYPE=mysql
DATABASE_URL=mysql://user:password@host:4000/database
```

### 郵件配置（可選）

```bash
# Gmail SMTP
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password

# 或使用 Resend API
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
RESEND_FROM_EMAIL=onboarding@resend.dev
```

---

## 📋 API 文檔

### 認證系統

#### 用戶登入
```http
POST /api/login
Content-Type: application/json

{
    "email": "user@example.com",
    "password": "12345678"
}
```

#### 驗證Token
```http
POST /api/verify
Authorization: Bearer <token>
```

#### 獲取用戶信息
```http
GET /api/user/info
Authorization: Bearer <token>
```

#### 獲取用戶服務
```http
GET /api/user/services
Authorization: Bearer <token>
```

#### 檢查服務權限
```http
POST /api/check-service
Authorization: Bearer <token>
Content-Type: application/json

{
    "service_name": "基礎服務"
}
```

---

## 🎯 主要路由

### 管理員路由
- `/login` - 統一登入頁面
- `/admin` - 管理員儀表板
- `/admin/users` - 用戶管理
- `/admin/services` - 服務管理
- `/admin/user-services` - 用戶服務管理
- `/admin/database` - 資料庫瀏覽

### 用戶路由
- `/user/register` - 用戶註冊
- `/user/portal` - 用戶門戶
- `/user/services` - 我的服務
- `/user/change-password` - 修改密碼
- `/user/forgot-password` - 忘記密碼

### API 路由
- `/api/login` - API登入（返回JWT token）
- `/api/verify` - 驗證JWT token
- `/api/user/info` - 獲取用戶詳細信息
- `/api/user/services` - 獲取用戶服務列表
- `/api/check-service` - 檢查特定服務訪問權限

---

## 📝 開發說明

### 代碼風格

- 中文註釋
- 錯誤處理 (try-except)
- 參數化 SQL 查詢 (防注入)
- 密碼 SHA256 加密
- 簡潔函數命名

### 時區配置

所有模組統一使用智利時區 (America/Santiago)：
- 時間工具函數：`utils/time_utils.py`
- 所有時間相關操作均使用 `get_chile_time()` 等函數

---

## ✅ 測試狀態

- ✅ 應用程式啟動成功
- ✅ 資料庫初始化完成
- ✅ 統一登入功能正常
- ✅ 管理員功能完整
- ✅ 用戶註冊與驗證正常
- ✅ 服務管理功能正常
- ✅ 用戶服務分配正常
- ✅ 郵件驗證功能正常
- ✅ API 認證系統正常

---

## 🔍 故障排除

### 問題 1：資料庫連接失敗

**可能原因**：
- `DATABASE_TYPE` 設置錯誤
- `DATABASE_URL` 格式錯誤
- 資料庫服務未啟動
- 用戶名或密碼錯誤

**解決方法**：
1. 檢查環境變數是否正確設置
2. 確認 `DATABASE_URL` 格式正確
3. 確認資料庫服務正在運行
4. 查看應用日誌獲取詳細錯誤信息

### 問題 2：無法登入

**可能原因**：
- 環境變數沒有正確設置
- 應用沒有重新部署

**解決方法**：
1. 運行 `python check_admin_credentials.py` 查看當前使用的值
2. 確認應用已重啟
3. 檢查環境變數是否正確設置
4. 嘗試使用默認帳號：`admin@xingwang.com` / `12345678`

### 問題 3：郵件發送失敗

**Render 上使用 Gmail SMTP**：
- Render 網絡環境可能無法訪問 Gmail SMTP
- 解決方法：使用 Resend API 或其他 SMTP 服務

**其他問題**：
1. 檢查 SMTP 配置是否正確
2. 確認 API Key 或密碼正確
3. 查看應用日誌獲取詳細錯誤信息

---

## 🎉 項目特色

- 完整的用戶服務管理系統
- 現代化響應式UI設計
- 統一的登入入口
- 完善的權限控制
- 安全的密碼管理
- 郵件驗證系統
- 模組化架構設計
- JWT API認證系統（外部APP集成）

---

## 📚 相關信息

- **部署環境**：本地開發 / PythonAnywhere / Render
- **資料庫**：SQLite / PostgreSQL / MySQL (TiDB)
- **Python**：3.8+
- **前端**：HTML5, CSS3, JavaScript (ES6+)
- **時區**：智利時區 (America/Santiago)
