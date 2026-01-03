# 🔧 資料庫類型配置指南

## 📋 概述

系統支持兩種資料庫類型：
- **SQLite**：用於本地開發和 PythonAnywhere
- **PostgreSQL**：用於 Render

通過設置 `DATABASE_TYPE` 環境變數來切換模式。

---

## 🖥️ 環境 1：本地 Flask 開發

### 方法 A：使用環境變數（推薦）

#### Windows (PowerShell)
```powershell
# 設置 SQLite（默認，開發用）
$env:DATABASE_TYPE="sqlite"
$env:DATABASE_PATH="C:\Users\PC\Desktop\FLASKPYTHONANYWHERE\databases\app.db"

# 或者設置 PostgreSQL（如果有本地 PostgreSQL）
$env:DATABASE_TYPE="postgresql"
$env:DATABASE_URL="postgresql://user:password@localhost:5432/database"

# 運行 Flask
python app.py
```

#### Windows (CMD)
```cmd
# 設置 SQLite
set DATABASE_TYPE=sqlite
set DATABASE_PATH=C:\Users\PC\Desktop\FLASKPYTHONANYWHERE\databases\app.db

# 運行 Flask
python app.py
```

#### Linux/Mac
```bash
# 設置 SQLite（默認）
export DATABASE_TYPE=sqlite
export DATABASE_PATH=./databases/app.db

# 或者設置 PostgreSQL
export DATABASE_TYPE=postgresql
export DATABASE_URL=postgresql://user:password@localhost:5432/database

# 運行 Flask
python app.py
```

### 方法 B：使用 .env 文件（推薦，更方便）

在項目根目錄創建 `.env` 文件：

**SQLite 配置（本地開發）**：
```env
DATABASE_TYPE=sqlite
DATABASE_PATH=./databases/app.db
SECRET_KEY=your-secret-key-here
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

**PostgreSQL 配置（如果有本地 PostgreSQL）**：
```env
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql://user:password@localhost:5432/database
SECRET_KEY=your-secret-key-here
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

然後安裝 `python-dotenv` 並在 `app.py` 開頭加載：
```bash
pip install python-dotenv
```

```python
# app.py 開頭
from dotenv import load_dotenv
load_dotenv()  # 自動加載 .env 文件
```

### 方法 C：直接修改 config.py（不推薦，但可行）

如果不想使用環境變數，可以直接修改 `config.py`：

```python
# config.py 第 17-21 行
DATABASE_TYPE = 'sqlite'  # 或 'postgresql'
DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'databases', 'app.db')
DATABASE_URL = ''  # PostgreSQL 連接字符串（如果使用 PostgreSQL）
```

---

## 🌐 環境 2：PythonAnywhere

### 設置步驟

1. **登入 PythonAnywhere Dashboard**

2. **進入 Web 設置頁面**
   - 點擊 "Web" 標籤
   - 點擊你的 Web app

3. **設置環境變數**
   - 向下滾動找到 "Environment variables" 部分
   - 點擊 "Add a new environment variable"

4. **添加環境變數**

   **SQLite 配置（PythonAnywhere 推薦）**：
   ```
   DATABASE_TYPE = sqlite
   DATABASE_PATH = /home/yourusername/path/to/databases/app.db
   ```

   **或者使用 PostgreSQL（如果訂閱了 PostgreSQL 服務）**：
   ```
   DATABASE_TYPE = postgresql
   DATABASE_URL = postgresql://user:password@host:port/database
   ```

5. **保存並重新載入**
   - 點擊 "Save"
   - 點擊 "Reload" 重新載入 Web app

### 完整環境變數列表（PythonAnywhere）

```bash
DATABASE_TYPE=sqlite
DATABASE_PATH=/home/yourusername/path/to/databases/app.db
SECRET_KEY=your-secret-key-here
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

---

## ☁️ 環境 3：Render

### 設置步驟

1. **登入 Render Dashboard**
   - 訪問 https://render.com
   - 登入你的帳號

2. **進入你的 Web Service**
   - 點擊你的 Web Service

3. **進入環境變數設置**
   - 點擊左側 "Environment" 標籤

4. **添加環境變數**

   **PostgreSQL 配置（Render 推薦）**：
   ```
   DATABASE_TYPE = postgresql
   DATABASE_URL = postgresql://user:password@host:port/database
   ```
   
   **注意**：如果你在 Render 創建了 PostgreSQL 資料庫，`DATABASE_URL` 會自動提供，你只需要添加：
   ```
   DATABASE_TYPE = postgresql
   ```

5. **保存更改**
   - 點擊 "Save Changes"
   - Render 會自動重新部署

### 完整環境變數列表（Render）

```bash
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql://user:password@host:port/database
SECRET_KEY=your-secret-key-here
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

**注意**：`DATABASE_URL` 通常會由 Render 自動提供（如果你在 Render 創建了 PostgreSQL 資料庫）。

---

## 📝 快速參考表

| 環境 | DATABASE_TYPE | DATABASE_PATH / DATABASE_URL | 設置位置 |
|------|--------------|------------------------------|----------|
| **本地 Flask** | `sqlite` | `./databases/app.db` | `.env` 文件或環境變數 |
| **PythonAnywhere** | `sqlite` | `/home/username/.../app.db` | Web 設置 → Environment variables |
| **Render** | `postgresql` | `postgresql://...` | Dashboard → Environment |

---

## 🔍 如何檢查當前配置

### 方法 1：查看環境變數

**Windows (PowerShell)**：
```powershell
echo $env:DATABASE_TYPE
echo $env:DATABASE_PATH
```

**Linux/Mac**：
```bash
echo $DATABASE_TYPE
echo $DATABASE_PATH
```

### 方法 2：在 Python 中檢查

創建一個測試腳本 `check_db_config.py`：

```python
from config import config
import os

print("=" * 50)
print("資料庫配置檢查")
print("=" * 50)
print(f"DATABASE_TYPE (環境變數): {os.environ.get('DATABASE_TYPE', 'Not set')}")
print(f"DATABASE_TYPE (config.py): {config.DATABASE_TYPE}")
print(f"DATABASE_PATH: {config.DATABASE_PATH}")
print(f"DATABASE_URL: {config.DATABASE_URL[:30] + '...' if config.DATABASE_URL else 'Not set'}")
print("=" * 50)

if config.DATABASE_TYPE == 'sqlite':
    print("✅ 當前使用 SQLite 資料庫")
    print(f"   資料庫路徑: {config.DATABASE_PATH}")
elif config.DATABASE_TYPE == 'postgresql':
    print("✅ 當前使用 PostgreSQL 資料庫")
    print(f"   連接字符串: {config.DATABASE_URL[:50]}...")
else:
    print("⚠️  未設置 DATABASE_TYPE，使用默認值（sqlite）")
```

運行：
```bash
python check_db_config.py
```

---

## 🚀 切換模式示例

### 從 SQLite 切換到 PostgreSQL（本地開發）

1. **安裝 PostgreSQL 和 psycopg2**：
   ```bash
   pip install psycopg2-binary
   ```

2. **設置環境變數**：
   ```bash
   # Windows
   set DATABASE_TYPE=postgresql
   set DATABASE_URL=postgresql://user:password@localhost:5432/database
   
   # Linux/Mac
   export DATABASE_TYPE=postgresql
   export DATABASE_URL=postgresql://user:password@localhost:5432/database
   ```

3. **初始化資料庫**：
   ```bash
   python database.py
   ```

4. **運行應用**：
   ```bash
   python app.py
   ```

### 從 PostgreSQL 切換回 SQLite

1. **設置環境變數**：
   ```bash
   # Windows
   set DATABASE_TYPE=sqlite
   set DATABASE_PATH=./databases/app.db
   
   # Linux/Mac
   export DATABASE_TYPE=sqlite
   export DATABASE_PATH=./databases/app.db
   ```

2. **運行應用**：
   ```bash
   python app.py
   ```

---

## ⚠️ 注意事項

1. **環境變數優先級**：
   - 環境變數 > config.py 默認值
   - 如果設置了環境變數，會覆蓋 config.py 中的值

2. **資料庫遷移**：
   - SQLite 和 PostgreSQL 的資料庫結構相同
   - 但數據不會自動遷移
   - 如果需要遷移數據，需要手動導出/導入

3. **開發建議**：
   - 本地開發：使用 SQLite（簡單快速）
   - PythonAnywhere：使用 SQLite（免費方案）
   - Render：使用 PostgreSQL（推薦，免費方案也支持）

4. **配置文件不要提交**：
   - `.env` 文件應該加入 `.gitignore`
   - 不要將敏感信息（如密碼）提交到 Git

---

## 🎯 總結

### 三個環境的配置位置：

1. **本地 Flask**：`.env` 文件或環境變數
2. **PythonAnywhere**：Web 設置 → Environment variables
3. **Render**：Dashboard → Environment

### 切換方式：

只需要設置 `DATABASE_TYPE` 環境變數即可：
- `sqlite` → 使用 SQLite
- `postgresql` → 使用 PostgreSQL

**就是這麼簡單！** 🎉

