# TiDB Cloud 配置指南

## 概述

系統現在支持 TiDB Cloud 作為外接數據庫。TiDB 兼容 MySQL 協議，可以使用 MySQL 客戶端連接。

---

## 在 Render 上配置 TiDB Cloud

### 步驟 1：獲取 TiDB Cloud 連接信息

1. 登錄 TiDB Cloud 控制台
2. 創建或選擇一個 TiDB 集群
3. 獲取連接信息：
   - **Host（主機）**：例如 `gateway01.ap-northeast-1.prod.aws.tidbcloud.com`
   - **Port（端口）**：通常是 `4000`
   - **User（用戶名）**：你的數據庫用戶名
   - **Password（密碼）**：你的數據庫密碼
   - **Database（數據庫名）**：你的數據庫名稱

### 步驟 2：在 Render 設置環境變數

在 Render 的 Web Service 設置頁面，添加以下環境變數：

#### 方法 A：使用 DATABASE_URL（推薦）

```
DATABASE_TYPE=mysql
DATABASE_URL=mysql://用戶名:密碼@主機:端口/數據庫名
```

**示例**：
```
DATABASE_TYPE=mysql
DATABASE_URL=mysql://root:your_password@gateway01.ap-northeast-1.prod.aws.tidbcloud.com:4000/your_database
```

#### 方法 B：使用單獨的環境變數

如果 TiDB Cloud 提供的連接字符串不方便使用，可以分別設置：

```
DATABASE_TYPE=mysql
MYSQL_HOST=gateway01.ap-northeast-1.prod.aws.tidbcloud.com
MYSQL_PORT=4000
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database
```

### 步驟 3：確保依賴已安裝

`requirements.txt` 中已包含 `PyMySQL==1.1.0`，Render 會自動安裝。

### 步驟 4：部署和測試

1. 推送代碼到 Git 倉庫
2. Render 會自動部署
3. 查看部署日誌確認數據庫連接成功
4. 訪問應用測試功能

---

## 注意事項

### SSL/TLS 連接（可選）

如果 TiDB Cloud 要求 SSL 連接，可以在連接字符串中添加參數：

```
DATABASE_URL=mysql://user:password@host:port/database?ssl_mode=REQUIRED
```

或者使用環境變數配置（需要在代碼中進一步配置）。

### 數據庫初始化

首次連接 TiDB Cloud 時，系統會自動創建所需的表結構。確保數據庫用戶有創建表的權限。

### 兼容性

- TiDB 兼容 MySQL 5.7 協議
- 使用 `mysql` 作為 `DATABASE_TYPE`（`tidb` 也支持，效果相同）
- 所有 SQL 語句使用 `?` 占位符，系統會自動轉換為 `%s`

---

## 與其他數據庫類型的區別

| 特性 | SQLite | PostgreSQL | MySQL/TiDB |
|------|--------|------------|------------|
| DATABASE_TYPE | `sqlite` | `postgresql` | `mysql` 或 `tidb` |
| 連接方式 | 文件路徑 | DATABASE_URL | DATABASE_URL 或單獨配置 |
| 參數占位符 | `?` | `%s`（自動轉換） | `%s`（自動轉換） |
| ID 類型 | INTEGER AUTOINCREMENT | SERIAL | INT AUTO_INCREMENT |
| 布林類型 | INTEGER | BOOLEAN | BOOLEAN |
| 獲取最後ID | cursor.lastrowid | LASTVAL() | LAST_INSERT_ID() |

---

## 故障排除

### 連接失敗

1. 檢查環境變數是否正確設置
2. 確認 TiDB Cloud 集群正在運行
3. 檢查網絡連接和防火牆設置
4. 驗證用戶名和密碼是否正確

### 表創建失敗

1. 確認數據庫用戶有 CREATE TABLE 權限
2. 檢查數據庫名稱是否正確
3. 查看應用日誌獲取詳細錯誤信息

### 查詢錯誤

1. 確認 SQL 語法正確
2. 檢查表是否已創建
3. 查看數據庫日誌

---

## 參考資料

- [TiDB Cloud 文檔](https://docs.pingcap.com/tidbcloud/)
- [PyMySQL 文檔](https://pymysql.readthedocs.io/)

