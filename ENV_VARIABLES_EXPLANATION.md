# 環境變數（Environment Variables）說明

## 📖 什麼是環境變數？

**環境變數**是操作系統（Windows/Linux/Mac）提供的一種存儲配置信息的方式，類似於"系統設置"。

### 簡單比喻：
- **硬編碼在代碼中** = 把密碼直接寫在紙上，放在桌子上（不安全）
- **環境變數** = 把密碼放在保險箱裡，只有系統知道密碼（安全）

## 🔍 代碼中的使用方式

### 當前代碼（config.py）：
```python
# 方式1：從環境變數讀取，如果沒有就用默認值
SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', '12345678')
#                                 ↑ 環境變數名稱        ↑ 備案默認值

# 這行代碼的意思是：
# 1. 先檢查系統環境變數中是否有 'SUPER_ADMIN_PASSWORD'
# 2. 如果有，就用環境變數的值
# 3. 如果沒有，就用備案默認值 '12345678'
```

## 🆚 環境變數 vs SQL 數據庫

### ❌ 不是 SQL！
- **環境變數**：存儲在**操作系統**中，不是數據庫
- **SQL 數據庫**：存儲在 `app.db` 文件中，用於存儲用戶數據、服務數據等

### 兩者的區別：

| 特性 | 環境變數 | SQL 數據庫 |
|------|---------|-----------|
| **存儲位置** | 操作系統內存/配置文件 | `databases/app.db` 文件 |
| **用途** | 存儲敏感配置（密碼、API密鑰） | 存儲業務數據（用戶、服務、會話） |
| **讀取方式** | `os.environ.get('變數名')` | `cursor.execute('SELECT ...')` |
| **安全性** | 不寫在代碼中，更安全 | 數據庫文件，需要保護 |
| **例子** | `SUPER_ADMIN_PASSWORD` | `users` 表、`services` 表 |

## 📝 實際例子

### 當前系統中的環境變數使用：

```python
# config.py 中的環境變數讀取：

# 1. Flask 密鑰
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
# 如果設置了環境變數 SECRET_KEY，就用環境變數的值
# 如果沒設置，就用 'dev-secret-key-change-in-production'

# 2. 資料庫路徑
DATABASE_PATH = os.environ.get('DATABASE_PATH', 'databases/app.db')
# 如果設置了環境變數 DATABASE_PATH，就用環境變數的值
# 如果沒設置，就用 'databases/app.db'

# 3. 超級管理員密碼
SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', '12345678')
# 如果設置了環境變數 SUPER_ADMIN_PASSWORD，就用環境變數的值
# 如果沒設置，就用 '12345678'（備案默認值）

# 4. SMTP 郵件配置
SMTP_EMAIL = os.environ.get('SMTP_EMAIL', 'geminifoto0004@gmail.com')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', 'pczr wlzh uxxl ozot')
```

## 🛠️ 如何設置環境變數？

### Windows 系統：
```cmd
# 臨時設置（關閉命令行窗口後失效）
set SUPER_ADMIN_PASSWORD=my_secure_password

# 永久設置（需要通過系統設置）
# 1. 右鍵"此電腦" → 屬性
# 2. 高級系統設置 → 環境變數
# 3. 新建系統變數
```

### Linux/Mac 系統：
```bash
# 臨時設置（關閉終端後失效）
export SUPER_ADMIN_PASSWORD="my_secure_password"

# 永久設置（添加到 ~/.bashrc 或 ~/.zshrc）
echo 'export SUPER_ADMIN_PASSWORD="my_secure_password"' >> ~/.bashrc
source ~/.bashrc
```

### PythonAnywhere（生產環境）：
1. 登入 PythonAnywhere
2. 進入 **Web** 標籤
3. 找到 **Environment variables** 區塊
4. 添加：
   - `SUPER_ADMIN_PASSWORD` = `your_secure_password`
   - `SUPER_ADMIN_EMAIL` = `admin@xingwang.com`

## ✅ 為什麼要用環境變數？

### 安全性優勢：
1. **密碼不寫在代碼中**：即使代碼泄露，密碼也不會泄露
2. **不同環境不同配置**：開發環境和生產環境可以用不同的密碼
3. **方便管理**：不需要修改代碼，只需要設置環境變數

### 實際場景：
```python
# ❌ 不安全的方式（硬編碼）
SUPER_ADMIN_PASSWORD = '12345678'  # 密碼直接寫在代碼裡

# ✅ 安全的方式（環境變數）
SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', '12345678')
# 生產環境：設置環境變數 = 'my_production_password_123'
# 開發環境：不設置環境變數 = 使用默認值 '12345678'
```

## 🔍 如何檢查環境變數是否設置？

### Python 代碼中：
```python
import os

# 檢查環境變數是否存在
if 'SUPER_ADMIN_PASSWORD' in os.environ:
    print("✅ 環境變數已設置")
    print(f"值: {os.environ['SUPER_ADMIN_PASSWORD']}")
else:
    print("⚠️ 環境變數未設置，使用默認值")
```

### 命令行中：
```bash
# Windows
echo %SUPER_ADMIN_PASSWORD%

# Linux/Mac
echo $SUPER_ADMIN_PASSWORD
```

## 📋 總結

1. **環境變數** = 操作系統的配置存儲，不是 SQL 數據庫
2. **用途** = 存儲敏感信息（密碼、API密鑰），避免寫在代碼中
3. **讀取方式** = `os.environ.get('變數名', '默認值')`
4. **設置方式** = 通過操作系統設置或 PythonAnywhere Web 界面
5. **優勢** = 更安全，不同環境可以不同配置

---

**當前系統狀態**：
- 如果**沒有設置**環境變數 → 使用 `config.py` 中的備案默認值
- 如果**設置了**環境變數 → 優先使用環境變數的值（更安全）

