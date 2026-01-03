# 🚀 Render + TiDB Cloud 完整設置指南

## 📋 為什麼使用 TiDB Cloud？

**Render 免費版 PostgreSQL 的限制**：
- ⚠️ 90 天後會自動刪除未使用的資料庫
- ⚠️ 免費版有資源限制

**TiDB Cloud 的優勢**：
- ✅ 免費版永久免費（有使用限制但不會自動刪除）
- ✅ 兼容 MySQL 協議，穩定可靠
- ✅ 適合長期使用

---

## 🔧 步驟 1：創建 TiDB Cloud 帳號和集群

### 1.1 註冊 TiDB Cloud

1. 訪問 https://tidbcloud.com
2. 點擊 "Sign Up" 註冊帳號
3. 登入控制台

### 1.2 創建免費集群

1. 在 TiDB Cloud 控制台點擊 **"Create Cluster"**
2. 選擇 **"Developer Tier"**（免費版）
3. 選擇區域（建議選擇離 Render 服務器近的區域）
4. 設置集群名稱
5. 點擊 **"Create"** 創建集群

**注意**：免費版可能需要等待幾分鐘才能創建完成。

### 1.3 獲取連接信息

1. 等待集群創建完成（狀態變為 "Available"）
2. 點擊集群進入詳情頁
3. 點擊 **"Connect"** 按鈕
4. 記下以下信息：
   - **Host（主機）**：例如 `gateway01.ap-northeast-1.prod.aws.tidbcloud.com`
   - **Port（端口）**：通常是 `4000`
   - **User（用戶名）**：通常是 `root` 或你創建的用戶名
   - **Password（密碼）**：你設置的密碼
   - **Database（數據庫名）**：例如 `test` 或你創建的數據庫名

### 1.4 創建數據庫（如果需要）

1. 在 TiDB Cloud 控制台，點擊 **"Chat2Query"** 或使用 SQL 客戶端
2. 執行以下 SQL 創建數據庫：
   ```sql
   CREATE DATABASE IF NOT EXISTS your_database_name;
   ```
3. 記下數據庫名稱

---

## 🔧 步驟 2：在 Render 設置環境變數

### 2.1 登入 Render Dashboard

1. 訪問 https://render.com
2. 登入你的帳號
3. 找到你的 Web Service（應該已經從 GitHub 連接）

### 2.2 設置環境變數

1. 點擊你的 Web Service
2. 點擊左側 **"Environment"** 標籤
3. 點擊 **"Add Environment Variable"** 按鈕
4. 添加以下環境變數：

#### 必須設置的環境變數：

```bash
# Flask 密鑰（必須設置，用於 session 加密）
SECRET_KEY=your-secret-key-here
# 生成方法：python -c "import secrets; print(secrets.token_hex(32))"

# 資料庫類型（必須設置為 mysql）
DATABASE_TYPE=mysql

# TiDB Cloud 連接字符串（方法 A：推薦）
DATABASE_URL=mysql://用戶名:密碼@主機:4000/數據庫名
```

**示例**：
```bash
SECRET_KEY=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6
DATABASE_TYPE=mysql
DATABASE_URL=mysql://root:your_password@gateway01.ap-northeast-1.prod.aws.tidbcloud.com:4000/test
```

#### 或者使用單獨的環境變數（方法 B）：

如果 TiDB Cloud 提供的連接字符串不方便使用，可以分別設置：

```bash
DATABASE_TYPE=mysql
MYSQL_HOST=gateway01.ap-northeast-1.prod.aws.tidbcloud.com
MYSQL_PORT=4000
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=test
```

#### 測試帳號（可選）：

```bash
# 超級管理員帳號（可選，如果不設置會使用默認值）
SUPER_ADMIN_EMAIL=test@example.com
SUPER_ADMIN_PASSWORD=your_test_password
```

#### 郵件配置（如果需要發送郵件）：

```bash
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

### 2.3 生成 SECRET_KEY

**重要**：`SECRET_KEY` 必須是一個隨機字符串。

**生成方法**：

**方法 1：使用 Python**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**方法 2：使用在線工具**
- 訪問 https://randomkeygen.com/
- 選擇 "CodeIgniter Encryption Keys"
- 複製生成的密鑰

### 2.4 保存環境變數

1. 點擊 **"Save Changes"**
2. Render 會自動重新部署你的應用
3. 等待部署完成（通常需要 1-2 分鐘）

---

## 🔍 步驟 3：驗證連接

### 3.1 查看部署日誌

1. 在 Render Dashboard 點擊你的 Web Service
2. 點擊 **"Logs"** 標籤
3. 查看日誌，確認：
   - ✅ 沒有資料庫連接錯誤
   - ✅ 看到 "資料庫連接成功" 或類似的消息
   - ✅ 看到 "users 表已就緒" 等表創建消息

### 3.2 測試登入

1. 訪問你的應用 URL（例如：`https://your-app.onrender.com`）
2. 點擊登入
3. 使用以下帳號登入：
   - 如果設置了環境變數：使用 `SUPER_ADMIN_EMAIL` 和 `SUPER_ADMIN_PASSWORD`
   - 如果沒有設置：使用默認值
     - 郵箱：`admin@xingwang.com`
     - 密碼：`12345678`

---

## ✅ 檢查清單

在開始測試前，確認以下項目：

- [ ] TiDB Cloud 集群已創建並運行
- [ ] 已獲取 TiDB Cloud 連接信息（Host, Port, User, Password, Database）
- [ ] `SECRET_KEY` 已設置（必須）
- [ ] `DATABASE_TYPE=mysql` 已設置（必須）
- [ ] `DATABASE_URL` 或 `MYSQL_*` 環境變數已設置（必須）
- [ ] `SUPER_ADMIN_EMAIL` 和 `SUPER_ADMIN_PASSWORD` 已設置（可選，建議設置）
- [ ] `SMTP_EMAIL` 和 `SMTP_PASSWORD` 已設置（如果需要發送郵件）
- [ ] Render 已重新部署
- [ ] 部署日誌沒有錯誤

---

## 🔍 故障排除

### 問題 1：資料庫連接失敗

**錯誤信息**：
```
資料庫連接失敗: ...
```

**可能原因**：
- `DATABASE_URL` 格式錯誤
- 用戶名或密碼錯誤
- 主機地址錯誤
- 端口錯誤
- 數據庫名稱錯誤
- TiDB Cloud 集群未運行

**解決方法**：
1. 檢查 `DATABASE_URL` 格式：
   ```
   mysql://用戶名:密碼@主機:端口/數據庫名
   ```
   **注意**：如果密碼包含特殊字符，需要 URL 編碼
   - `@` → `%40`
   - `#` → `%23`
   - `$` → `%24`
   - `%` → `%25`
   - `&` → `%26`
   - `+` → `%2B`
   - `=` → `%3D`

2. 確認 TiDB Cloud 集群狀態為 "Available"
3. 檢查用戶名和密碼是否正確
4. 確認數據庫名稱已創建
5. 查看 Render 部署日誌獲取詳細錯誤信息

### 問題 2：表創建失敗

**錯誤信息**：
```
CREATE TABLE 失敗: ...
```

**可能原因**：
- 數據庫用戶沒有 CREATE TABLE 權限
- 數據庫名稱不存在

**解決方法**：
1. 確認數據庫已創建：
   ```sql
   CREATE DATABASE IF NOT EXISTS your_database_name;
   ```
2. 確認用戶有足夠權限（TiDB Cloud 默認用戶通常有所有權限）
3. 查看應用日誌獲取詳細錯誤信息

### 問題 3：環境變數沒有生效

**可能原因**：
- 環境變數設置後沒有重新部署
- 環境變數名稱拼寫錯誤

**解決方法**：
1. 確認環境變數名稱拼寫正確（區分大小寫）
2. 點擊 "Save Changes" 後等待重新部署
3. 查看部署日誌確認環境變數已加載

### 問題 4：無法登入

**可能原因**：
- 環境變數沒有正確設置
- 應用沒有重新部署

**解決方法**：
1. 檢查環境變數是否正確設置
2. 確認 Render 已經重新部署
3. 查看部署日誌確認沒有錯誤
4. 嘗試使用默認帳號：`admin@xingwang.com` / `12345678`

---

## 📝 快速參考

### 最小配置（可以測試登入）

```bash
SECRET_KEY=your-secret-key-here
DATABASE_TYPE=mysql
DATABASE_URL=mysql://root:password@gateway01.ap-northeast-1.prod.aws.tidbcloud.com:4000/test
```

使用默認帳號登入：
- 郵箱：`admin@xingwang.com`
- 密碼：`12345678`

### 完整配置（生產環境）

```bash
SECRET_KEY=your-very-secure-random-key-here
DATABASE_TYPE=mysql
DATABASE_URL=mysql://root:password@gateway01.ap-northeast-1.prod.aws.tidbcloud.com:4000/your_database
SUPER_ADMIN_EMAIL=your-admin@example.com
SUPER_ADMIN_PASSWORD=your-secure-password
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

---

## 🎉 完成！

設置完成後，你就可以：
- ✅ 使用 TiDB Cloud 作為資料庫（不會自動刪除）
- ✅ 訪問應用
- ✅ 使用設置的帳號密碼登入
- ✅ 測試所有功能

**默認測試帳號**（如果沒有設置環境變數）：
- 郵箱：`admin@xingwang.com`
- 密碼：`12345678`

---

## 📚 相關文檔

- [TiDB Cloud 配置指南](./TIDB_CLOUD_SETUP.md)
- [三個環境配置說明](./三個環境配置說明.md)
- [如何修改管理員密碼](./HOW_TO_CHANGE_ADMIN_PASSWORD.md)

---

## 💡 提示

1. **TiDB Cloud 免費版限制**：
   - 有存儲和計算資源限制
   - 適合開發和測試使用
   - 如果需要更多資源，可以升級到付費版

2. **安全性**：
   - 不要在代碼中硬編碼密碼
   - 使用環境變數存儲敏感信息
   - 定期更換密碼

3. **備份**：
   - 定期備份重要數據
   - TiDB Cloud 提供自動備份功能（付費版）

