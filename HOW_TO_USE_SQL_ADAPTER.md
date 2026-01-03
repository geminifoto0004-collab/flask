# 🔄 如何使用 SQL 適配函數

## 📋 問題

你的代碼中大量使用了 `cursor.execute()` 和 `?` 占位符（SQLite 格式），但 PostgreSQL 需要使用 `%s`。

## ✅ 解決方案

**好消息**：我已經創建了**自動適配包裝類**，**你完全不需要修改任何現有代碼**！

### 🎉 自動適配（推薦，無需修改代碼）

所有通過 `get_cursor()` 獲取的 cursor 都會自動適配 SQL 占位符：

```python
from database import get_db_connection, get_cursor

conn = get_db_connection()
cursor = get_cursor(conn)  # 自動包裝，無需修改

# 直接使用，系統會自動處理 ? 轉換為 %s（如果是 PostgreSQL）
cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
```

**就是這麼簡單！** 你不需要修改任何現有代碼，系統會自動處理。

### 方法 1：使用新的 `execute_sql()` 函數（推薦用於新代碼）

```python
from database import get_db_connection, execute_sql

conn = get_db_connection()
cursor = conn.cursor()

# 舊的方式（仍然可以工作）
cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))

# 新的方式（自動適配 SQLite 和 PostgreSQL）
execute_sql(cursor, 'SELECT * FROM users WHERE id = ?', (user_id,))
```

### 方法 2：現有代碼自動適配（無需修改）

**好消息**：由於 `adapt_sql()` 函數已經創建，你可以在需要的地方手動調用它：

```python
from database import get_db_connection, adapt_sql

conn = get_db_connection()
cursor = conn.cursor()

sql = 'SELECT * FROM users WHERE id = ?'
adapted_sql = adapt_sql(sql)  # 如果是 PostgreSQL，會自動轉換 ? 為 %s
cursor.execute(adapted_sql, (user_id,))
```

## 🚀 實際範例

### 範例 1：查詢用戶

```python
from database import get_db_connection, execute_sql

conn = get_db_connection()
cursor = conn.cursor()

# 使用新的 execute_sql 函數（自動適配）
execute_sql(cursor, 'SELECT * FROM users WHERE email = ?', (email,))
user = cursor.fetchone()
```

### 範例 2：插入數據

```python
from database import get_db_connection, execute_sql

conn = get_db_connection()
cursor = conn.cursor()

# 使用新的 execute_sql 函數（自動適配）
execute_sql(cursor, '''
    INSERT INTO users (username, email, password_hash)
    VALUES (?, ?, ?)
''', (username, email, password_hash))
conn.commit()
```

### 範例 3：批量插入

```python
from database import get_db_connection, executemany_sql

conn = get_db_connection()
cursor = conn.cursor()

users = [
    ('Alice', 'alice@example.com', 'hash1'),
    ('Bob', 'bob@example.com', 'hash2'),
]

# 使用新的 executemany_sql 函數（自動適配）
executemany_sql(cursor, '''
    INSERT INTO users (username, email, password_hash)
    VALUES (?, ?, ?)
''', users)
conn.commit()
```

## ⚠️ 重要說明

### 現有代碼怎麼辦？

**✅ 答案：什麼都不需要做！**

系統已經創建了 `AdaptedCursor` 包裝類，所有通過 `get_cursor()` 獲取的 cursor 都會自動適配。

**你只需要確保使用 `get_cursor()` 獲取 cursor**：

```python
# ✅ 正確：使用 get_cursor()（自動適配）
from database import get_db_connection, get_cursor
conn = get_db_connection()
cursor = get_cursor(conn)  # 自動適配，無需修改代碼

# ❌ 錯誤：直接使用 conn.cursor()（不會適配）
cursor = conn.cursor()  # 不會自動適配
```

### 檢查你的代碼

確保所有地方都使用 `get_cursor()`：

```python
# ✅ 正確
from database import get_db_connection, get_cursor
conn = get_db_connection()
cursor = get_cursor(conn)

# ❌ 需要修改
cursor = conn.cursor()  # 改為 get_cursor(conn)
```

## 🔧 在 Render 上部署

當你在 Render 上部署時：

1. **設置環境變數**：
   ```
   DATABASE_TYPE=postgresql
   DATABASE_URL=postgresql://user:password@host:port/database
   ```

2. **系統會自動**：
   - 檢測到 `DATABASE_TYPE=postgresql`
   - 所有使用 `execute_sql()` 的地方會自動將 `?` 轉換為 `%s`
   - 現有代碼如果使用 `cursor.execute()`，需要手動調用 `adapt_sql()` 或改用 `execute_sql()`

## 📝 總結

- ✅ **完全自動**：使用 `get_cursor()` 獲取的 cursor 會自動適配
- ✅ **無需修改代碼**：現有代碼完全不需要改動
- ✅ **自動適配**：系統會根據 `DATABASE_TYPE` 自動處理 `?` 轉換為 `%s`
- ✅ **無需本地 PostgreSQL**：可以在 Render 上直接測試
- ✅ **向後兼容**：SQLite 仍然正常工作，不受影響

## 🎯 下一步

1. 在 Render 上部署
2. 設置 `DATABASE_TYPE=postgresql`
3. 測試應用是否正常工作
4. 如果有 SQL 錯誤，檢查是否使用了 `execute_sql()`

