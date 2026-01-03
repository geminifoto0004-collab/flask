# 🔄 SQL 參數占位符適配指南

## 📋 問題說明

SQLite 和 PostgreSQL 使用不同的 SQL 參數占位符：
- **SQLite**: 使用 `?` 作為參數占位符
- **PostgreSQL**: 使用 `%s` 作為參數占位符

## ✅ 解決方案

系統已經創建了自動適配函數，**你不需要修改現有的 SQL 語句**！

### 方法 1：使用 `execute_sql()` 函數（推薦）

所有使用 `cursor.execute()` 的地方，可以改為使用 `execute_sql()`：

```python
from database import get_db_connection, execute_sql

# 舊的方式（仍然可以工作，但建議改用新方式）
cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))

# 新的方式（自動適配 SQLite 和 PostgreSQL）
execute_sql(cursor, 'SELECT * FROM users WHERE id = ?', (user_id,))
```

### 方法 2：直接使用 `adapt_sql()` 函數

如果你只想轉換 SQL 語句：

```python
from database import adapt_sql, get_db_connection

conn = get_db_connection()
cursor = conn.cursor()

sql = 'SELECT * FROM users WHERE id = ?'
adapted_sql = adapt_sql(sql)  # PostgreSQL 會自動轉換為 %s
cursor.execute(adapted_sql, (user_id,))
```

## 🔧 實際使用範例

### 範例 1：單個參數查詢

```python
from database import get_db_connection, execute_sql

conn = get_db_connection()
cursor = conn.cursor()

# 自動適配，無需修改 SQL
execute_sql(cursor, 'SELECT * FROM users WHERE email = ?', (email,))
user = cursor.fetchone()
```

### 範例 2：多個參數插入

```python
from database import get_db_connection, execute_sql

conn = get_db_connection()
cursor = conn.cursor()

# 自動適配，無需修改 SQL
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

# 自動適配，無需修改 SQL
executemany_sql(cursor, '''
    INSERT INTO users (username, email, password_hash)
    VALUES (?, ?, ?)
''', users)
conn.commit()
```

## ⚠️ 注意事項

1. **現有代碼仍然可以工作**
   - 如果你不想修改現有代碼，系統會自動處理（通過 `adapt_sql()` 函數）
   - 但建議逐步遷移到 `execute_sql()` 以獲得更好的兼容性

2. **字符串中的 `?` 不會被轉換**
   - `adapt_sql()` 函數會簡單地將所有 `?` 替換為 `%s`
   - 如果你的 SQL 中有字符串包含 `?`，可能會出問題
   - 解決方法：使用參數化查詢，不要將值直接拼接到 SQL 中

3. **CREATE TABLE 語句**
   - CREATE TABLE 語句通常不需要參數，所以不受影響
   - 但如果使用參數，請使用 `execute_sql()`

## 🚀 遷移建議

### 階段 1：新代碼使用新函數
- 所有新寫的代碼都使用 `execute_sql()` 和 `executemany_sql()`

### 階段 2：逐步遷移舊代碼
- 在修改現有代碼時，順便改為使用新函數
- 不需要一次性全部修改

### 階段 3：完全遷移（可選）
- 如果時間允許，可以逐步將所有 `cursor.execute()` 改為 `execute_sql()`

## 📝 總結

- ✅ **不需要立即修改所有代碼**
- ✅ **新代碼建議使用 `execute_sql()`**
- ✅ **系統會自動適配 SQLite 和 PostgreSQL**
- ✅ **現有代碼仍然可以正常工作**

