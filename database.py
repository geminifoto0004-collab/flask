"""
Flask 授權管理系統 - 資料庫管理
功能：初始化表、提供連接、數據遷移
支持：SQLite (PythonAnywhere)、PostgreSQL (Render) 和 MySQL/TiDB (TiDB Cloud)
"""

import os
from datetime import datetime
from config import config
from utils.time_utils import get_chile_time_naive

# 根據資料庫類型導入相應模組
POSTGRESQL_AVAILABLE = None
MYSQL_AVAILABLE = None

# 嘗試導入 PostgreSQL 模組（如果需要的話）
try:
    import psycopg2  # type: ignore
    from psycopg2.extras import RealDictCursor  # type: ignore
    POSTGRESQL_AVAILABLE = True
except ImportError:
    POSTGRESQL_AVAILABLE = False
    # 只在需要時才顯示警告
    if config.DATABASE_TYPE == 'postgresql':
        print("⚠️  PostgreSQL 模組未安裝，請運行: pip install psycopg2-binary")

# 嘗試導入 MySQL/TiDB 模組（如果需要的話）
try:
    import pymysql  # noqa: F401
    pymysql.install_as_MySQLdb()  # 使 pymysql 兼容 MySQLdb
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    # 只在需要時才顯示警告
    if config.DATABASE_TYPE in ('mysql', 'tidb'):
        print("⚠️  MySQL/TiDB 模組未安裝，請運行: pip install PyMySQL")

# SQLite 是 Python 標準庫，總是可用
import sqlite3  # noqa: F401


# ========== SQL 參數占位符適配 ==========
def adapt_sql(sql):
    """
    適配 SQL 語句的參數占位符
    SQLite 使用 ?，PostgreSQL/MySQL/TiDB 使用 %s
    為了兼容性，所有 SQL 語句都使用 ?，此函數會自動轉換為 %s（PostgreSQL/MySQL/TiDB）
    """
    if config.DATABASE_TYPE in ('postgresql', 'mysql', 'tidb'):
        # 將 ? 轉換為 %s（但要注意不要替換字符串中的 ?）
        # 簡單的替換：將所有 ? 替換為 %s
        # 注意：這可能在某些複雜 SQL 中出問題，但對於大多數情況都適用
        return sql.replace('?', '%s')
    else:
        return sql


def execute_sql(cursor, sql, params=None):
    """
    執行 SQL 語句的統一接口，自動處理參數占位符轉換
    參數：
        cursor - 資料庫游標
        sql - SQL 語句（可以使用 ? 占位符，會自動轉換為 %s 如果是 PostgreSQL）
        params - 參數元組或列表（可選）
    返回：cursor.execute() 的結果
    使用範例：
        execute_sql(cursor, 'SELECT * FROM users WHERE id = ?', (user_id,))
    """
    # 如果是 PostgreSQL，自動轉換 ? 為 %s
    adapted_sql = adapt_sql(sql)
    
    if params:
        return cursor.execute(adapted_sql, params)
    else:
        return cursor.execute(adapted_sql)


def executemany_sql(cursor, sql, params_list):
    """
    批量執行 SQL 語句的統一接口，自動處理參數占位符轉換
    參數：
        cursor - 資料庫游標
        sql - SQL 語句（可以使用 ? 占位符，會自動轉換為 %s 如果是 PostgreSQL）
        params_list - 參數列表
    返回：cursor.executemany() 的結果
    使用範例：
        executemany_sql(cursor, 'INSERT INTO users (name) VALUES (?)', [('Alice',), ('Bob',)])
    """
    # 如果是 PostgreSQL，自動轉換 ? 為 %s
    adapted_sql = adapt_sql(sql)
    return cursor.executemany(adapted_sql, params_list)


# ========== 資料庫連接 ==========
def get_db_connection():
    """
    獲取資料庫連接
    返回：資料庫連接對象（SQLite、PostgreSQL 或 MySQL/TiDB）
    """
    try:
        if config.DATABASE_TYPE == 'postgresql':
            if not POSTGRESQL_AVAILABLE:
                raise ImportError("PostgreSQL 模組未安裝，請運行: pip install psycopg2-binary")
            
            if not config.DATABASE_URL:
                raise ValueError("DATABASE_URL 環境變數未設置（Render 會自動提供）")
            
            # PostgreSQL 連接
            conn = psycopg2.connect(config.DATABASE_URL)
            # 設置自動提交為 False（與 SQLite 行為一致）
            conn.autocommit = False
            # 包裝連接以自動適配 cursor
            return AdaptedConnection(conn)
        elif config.DATABASE_TYPE in ('mysql', 'tidb'):
            if not MYSQL_AVAILABLE:
                raise ImportError("MySQL/TiDB 模組未安裝，請運行: pip install PyMySQL")
            
            import pymysql
            
            # 優先使用 DATABASE_URL，如果沒有則使用單獨的配置
            if config.DATABASE_URL:
                # 解析 MySQL URL 格式：mysql://user:password@host:port/database
                # 或者 TiDB URL 格式類似
                import urllib.parse
                parsed = urllib.parse.urlparse(config.DATABASE_URL)
                db_config = {
                    'host': parsed.hostname or config.MYSQL_HOST,
                    'port': parsed.port or config.MYSQL_PORT,
                    'user': parsed.username or config.MYSQL_USER,
                    'password': parsed.password or config.MYSQL_PASSWORD,
                    'database': parsed.path.lstrip('/') if parsed.path else config.MYSQL_DATABASE,
                    'charset': 'utf8mb4',
                    'autocommit': False
                }
                # 檢查 URL 參數中是否有 SSL 設置
                if parsed.query:
                    query_params = urllib.parse.parse_qs(parsed.query)
                    if query_params.get('ssl_mode') == ['REQUIRED']:
                        # TiDB Cloud 要求 SSL 連接
                        db_config['ssl'] = {'check_hostname': False}
            else:
                if not config.MYSQL_HOST or not config.MYSQL_USER or not config.MYSQL_DATABASE:
                    raise ValueError("MySQL/TiDB 連接配置未設置，請設置 DATABASE_URL 或 MYSQL_HOST/MYSQL_USER/MYSQL_DATABASE")
                db_config = {
                    'host': config.MYSQL_HOST,
                    'port': config.MYSQL_PORT,
                    'user': config.MYSQL_USER,
                    'password': config.MYSQL_PASSWORD,
                    'database': config.MYSQL_DATABASE,
                    'charset': 'utf8mb4',
                    'autocommit': False
                }
            
            # TiDB Cloud 要求 SSL 連接，自動啟用 SSL
            # 如果 host 包含 tidbcloud.com，自動啟用 SSL
            if 'tidbcloud.com' in db_config.get('host', '').lower():
                db_config['ssl'] = {'check_hostname': False}
            
            # MySQL/TiDB 連接
            conn = pymysql.connect(**db_config)
            # 包裝連接以自動適配 cursor
            return AdaptedConnection(conn)
        else:
            # SQLite 連接
            # 確保資料庫目錄存在
            db_dir = os.path.dirname(config.DATABASE_PATH)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
            
            conn = sqlite3.connect(config.DATABASE_PATH)
            conn.row_factory = sqlite3.Row  # 使查詢結果可以像字典一樣訪問
            # 包裝連接以自動適配 cursor（即使 SQLite 不需要轉換，也保持一致性）
            return AdaptedConnection(conn)
    except Exception as e:
        print(f"資料庫連接失敗: {e}")
        raise


# ========== 資料庫特定的 SQL 語法 ==========
def get_id_type():
    """獲取主鍵 ID 類型"""
    if config.DATABASE_TYPE == 'postgresql':
        return 'SERIAL PRIMARY KEY'
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        return 'INT AUTO_INCREMENT PRIMARY KEY'
    else:
        return 'INTEGER PRIMARY KEY AUTOINCREMENT'


def get_boolean_type():
    """獲取布林類型"""
    if config.DATABASE_TYPE == 'postgresql':
        return 'BOOLEAN'
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        return 'BOOLEAN'  # MySQL 5.7.8+ 和 TiDB 支持 BOOLEAN
    else:
        return 'INTEGER'


def get_text_type():
    """獲取文本類型（SQLite 用 TEXT，PostgreSQL 用 TEXT 或 VARCHAR）"""
    if config.DATABASE_TYPE == 'postgresql':
        return 'TEXT'
    else:
        return 'TEXT'


def get_timestamp_default():
    """獲取時間戳默認值"""
    # 所有資料庫都支持 CURRENT_TIMESTAMP
    return "DEFAULT CURRENT_TIMESTAMP"


class AdaptedCursor:
    """
    包裝的 Cursor 類，自動處理 SQL 參數占位符轉換
    這樣就不需要修改現有代碼，所有 cursor.execute() 都會自動適配
    """
    def __init__(self, cursor):
        self._cursor = cursor
    
    def __getattr__(self, name):
        # 將所有其他屬性和方法委託給原始 cursor
        return getattr(self._cursor, name)
    
    def execute(self, sql, params=None):
        """執行 SQL，自動適配參數占位符"""
        adapted_sql = adapt_sql(sql)
        if params:
            return self._cursor.execute(adapted_sql, params)
        else:
            return self._cursor.execute(adapted_sql)
    
    def executemany(self, sql, params_list):
        """批量執行 SQL，自動適配參數占位符"""
        adapted_sql = adapt_sql(sql)
        return self._cursor.executemany(adapted_sql, params_list)


class AdaptedConnection:
    """
    包裝的 Connection 類，自動處理所有 cursor 的 SQL 參數占位符轉換
    這樣就不需要修改現有代碼，所有 conn.cursor() 都會自動返回適配的 cursor
    """
    def __init__(self, conn):
        self._conn = conn
    
    def __getattr__(self, name):
        # 將所有其他屬性和方法委託給原始連接
        return getattr(self._conn, name)
    
    def cursor(self, *args, **kwargs):
        """創建 cursor，自動包裝為 AdaptedCursor"""
        if config.DATABASE_TYPE == 'postgresql':
            from psycopg2.extras import RealDictCursor  # type: ignore
            cursor = self._conn.cursor(cursor_factory=RealDictCursor, *args, **kwargs)
        elif config.DATABASE_TYPE in ('mysql', 'tidb'):
            # PyMySQL 使用 pymysql.cursors.DictCursor 來返回字典
            import pymysql.cursors
            # PyMySQL 需要使用 cursorclass 關鍵字參數
            if 'cursorclass' not in kwargs:
                kwargs['cursorclass'] = pymysql.cursors.DictCursor
            cursor = self._conn.cursor(*args, **kwargs)
        else:
            cursor = self._conn.cursor(*args, **kwargs)
        return AdaptedCursor(cursor)


def get_cursor(conn, use_adapter=True):
    """
    獲取游標（PostgreSQL 使用 RealDictCursor，MySQL/TiDB 使用 DictCursor，SQLite 使用普通游標）
    參數：
        conn - 資料庫連接
        use_adapter - 是否使用適配器（默認 True，自動處理 SQL 占位符轉換）
    返回：cursor 對象（如果 use_adapter=True，返回 AdaptedCursor）
    """
    if config.DATABASE_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor  # type: ignore
        cursor = conn.cursor(cursor_factory=RealDictCursor)
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        import pymysql.cursors
        # PyMySQL 需要使用 cursorclass 關鍵字參數
        cursor = conn.cursor(cursorclass=pymysql.cursors.DictCursor)
    else:
        cursor = conn.cursor()
    
    # 如果啟用適配器，包裝 cursor 以自動處理 SQL 占位符轉換
    if use_adapter:
        return AdaptedCursor(cursor)
    else:
        return cursor


def get_row_dict(row, cursor):
    """將查詢結果轉換為字典"""
    if config.DATABASE_TYPE == 'postgresql':
        return dict(row) if row else None
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        # PyMySQL DictCursor 已經返回字典
        return dict(row) if row else None
    else:
        # SQLite Row 需要轉換
        if row:
            return {key: row[key] for key in row.keys()}
        return None


def get_lastrowid(cursor, conn):
    """獲取最後插入的 ID"""
    if config.DATABASE_TYPE == 'postgresql':
        # PostgreSQL 使用 LASTVAL()
        cursor.execute("SELECT LASTVAL()")
        result = cursor.fetchone()
        # 處理不同的返回格式
        if isinstance(result, (list, tuple)):
            return result[0]
        elif isinstance(result, dict):
            return result['lastval']
        else:
            return result
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        # MySQL/TiDB 使用 LAST_INSERT_ID()
        cursor.execute("SELECT LAST_INSERT_ID()")
        result = cursor.fetchone()
        if isinstance(result, (list, tuple)):
            return result[0]
        elif isinstance(result, dict):
            return result['LAST_INSERT_ID()']
        else:
            return result
    else:
        # SQLite 使用 cursor.lastrowid
        return cursor.lastrowid


def check_column_exists(cursor, table_name, column_name):
    """檢查列是否存在"""
    if config.DATABASE_TYPE == 'postgresql':
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s AND column_name = %s
        """, (table_name, column_name))
        return cursor.fetchone() is not None
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        # MySQL/TiDB 使用 information_schema（類似 PostgreSQL）
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s AND column_name = %s
        """, (table_name, column_name))
        return cursor.fetchone() is not None
    else:
        # SQLite 使用 PRAGMA
        cursor.execute("PRAGMA table_info({})".format(table_name))
        columns = [column[1] for column in cursor.fetchall()]
        return column_name in columns


def get_table_names(cursor):
    """獲取所有表名"""
    if config.DATABASE_TYPE == 'postgresql':
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        return [row[0] if isinstance(row, tuple) else row['table_name'] for row in cursor.fetchall()]
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        # MySQL/TiDB 使用 information_schema（類似 PostgreSQL，但使用 database() 函數）
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = DATABASE()
        """)
        return [row[0] if isinstance(row, tuple) else row['table_name'] for row in cursor.fetchall()]
    else:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return [row[0] if isinstance(row, tuple) else row['name'] for row in cursor.fetchall()]


def get_placeholder():
    """獲取 SQL 參數占位符（SQLite 用 ?，PostgreSQL/MySQL/TiDB 用 %s）"""
    if config.DATABASE_TYPE in ('postgresql', 'mysql', 'tidb'):
        return '%s'
    else:
        return '?'


# ========== 資料庫初始化 ==========
def init_database():
    """
    初始化所有資料庫表
    如果表已存在則跳過
    """
    conn = get_db_connection()
    cursor = get_cursor(conn)
    
    try:
        # 創建 users 表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id {id_type},
                username {text_type} UNIQUE NOT NULL,
                email {text_type} UNIQUE NOT NULL,
                password_hash {text_type} NOT NULL,
                role {text_type} DEFAULT 'user',
                created_at TIMESTAMP {timestamp_default}
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            timestamp_default=get_timestamp_default()
        ))
        print("users 表已就緒")
        
        # 檢查是否需要添加 company_name 列（向後兼容）
        if not check_column_exists(cursor, 'users', 'company_name'):
            cursor.execute('ALTER TABLE users ADD COLUMN company_name {text_type}'.format(
                text_type=get_text_type()
            ))
            print("已添加 company_name 列到 users 表")
        
        # 創建 services 表（服務產品）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS services (
                id {id_type},
                name {text_type} NOT NULL,
                description {text_type},
                price DECIMAL(10,2),
                duration_days INTEGER,
                version {text_type} DEFAULT 'FREE',
                config_json {text_type},
                status {text_type} DEFAULT 'active',
                created_at TIMESTAMP {timestamp_default}
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            timestamp_default=get_timestamp_default()
        ))
        print("services 表已就緒")
        
        # 檢查是否需要添加新列（向後兼容）
        if not check_column_exists(cursor, 'services', 'version'):
            cursor.execute('ALTER TABLE services ADD COLUMN version {text_type} DEFAULT \'FREE\''.format(
                text_type=get_text_type()
            ))
            print("已添加 version 列到 services 表")
        
        if not check_column_exists(cursor, 'services', 'config_json'):
            cursor.execute('ALTER TABLE services ADD COLUMN config_json {text_type}'.format(
                text_type=get_text_type()
            ))
            print("已添加 config_json 列到 services 表")
        
        # 創建 user_services 表（用戶購買的服務）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_services (
                id {id_type},
                user_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                status {text_type} DEFAULT 'active',
                start_date DATE,
                end_date DATE,
                config_json {text_type},
                created_at TIMESTAMP {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            timestamp_default=get_timestamp_default()
        ))
        print("user_services 表已就緒")
        
        # 檢查是否需要添加 config_json 列（向後兼容）
        if not check_column_exists(cursor, 'user_services', 'config_json'):
            cursor.execute('ALTER TABLE user_services ADD COLUMN config_json {text_type}'.format(
                text_type=get_text_type()
            ))
            print("已添加 config_json 列到 user_services 表")
        
        # 創建服務版本表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS service_versions (
                id {id_type},
                service_name {text_type} NOT NULL,
                param_name {text_type} NOT NULL,
                param_content {text_type} NOT NULL,
                created_at TIMESTAMP {timestamp_default},
                updated_at TIMESTAMP {timestamp_default}
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            timestamp_default=get_timestamp_default()
        ))
        print("service_versions 表已就緒")
        
        # 創建用戶會話表（用於記錄用戶上線狀態）
        boolean_type = get_boolean_type()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id {id_type},
                user_id INTEGER NOT NULL,
                service_name {text_type} NOT NULL,
                session_start TIMESTAMP {timestamp_default},
                last_activity TIMESTAMP {timestamp_default},
                is_online {boolean_type} DEFAULT 1,
                session_data {text_type},
                session_token VARCHAR(255) UNIQUE,
                device_info {text_type},
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            boolean_type=boolean_type,
            timestamp_default=get_timestamp_default()
        ))
        print("user_sessions 表已就緒")
        
        # 檢查並添加新字段（向後兼容）
        if not check_column_exists(cursor, 'user_sessions', 'session_token'):
            cursor.execute('ALTER TABLE user_sessions ADD COLUMN session_token VARCHAR(255)')
            print("已添加 session_token 列到 user_sessions 表")
        
        if not check_column_exists(cursor, 'user_sessions', 'device_info'):
            cursor.execute('ALTER TABLE user_sessions ADD COLUMN device_info {text_type}'.format(
                text_type=get_text_type()
            ))
            print("已添加 device_info 列到 user_sessions 表")
            
        
        # 創建 verification_codes 表（郵件驗證用）
        boolean_type = get_boolean_type()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS verification_codes (
                id {id_type},
                email {text_type} NOT NULL,
                code {text_type} NOT NULL,
                purpose {text_type} NOT NULL,
                expire_time TIMESTAMP NOT NULL,
                used {boolean_type} DEFAULT 0,
                created_at TIMESTAMP {timestamp_default}
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            boolean_type=boolean_type,
            timestamp_default=get_timestamp_default()
        ))
        print("verification_codes 表已就緒")
        
        # 創建 user_monitor_configs 表（用戶監控任務配置）
        boolean_type = get_boolean_type()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_monitor_configs (
                id {id_type},
                user_id INTEGER NOT NULL,
                api_key {text_type} UNIQUE NOT NULL,
                zofri_username {text_type} NOT NULL,
                zofri_password {text_type} NOT NULL,
                zofri_rut_entidad {text_type} NOT NULL,
                zofri_rut_representante {text_type},
                notification_emails {text_type} NOT NULL,
                last_check_time TIMESTAMP,
                last_check_result {text_type},
                is_active {boolean_type} DEFAULT 1,
                created_at TIMESTAMP {timestamp_default},
                updated_at TIMESTAMP {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            boolean_type=boolean_type,
            timestamp_default=get_timestamp_default()
        ))
        print("user_monitor_configs 表已就緒")
        
        # 檢查是否需要添加新列（向後兼容）
        if not check_column_exists(cursor, 'user_monitor_configs', 'company_name'):
            cursor.execute('ALTER TABLE user_monitor_configs ADD COLUMN company_name {text_type}'.format(
                text_type=get_text_type()
            ))
            print("已添加 company_name 列到 user_monitor_configs 表")
        
        if not check_column_exists(cursor, 'user_monitor_configs', 'email_subject'):
            cursor.execute('ALTER TABLE user_monitor_configs ADD COLUMN email_subject {text_type}'.format(
                text_type=get_text_type()
            ))
            print("已添加 email_subject 列到 user_monitor_configs 表")
        
        # 初始化默認服務
        init_default_services(cursor)
        
        conn.commit()
        print("資料庫初始化完成")
        
    except Exception as e:
        print(f"資料庫初始化失敗: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def init_default_services(cursor):
    """初始化默認服務"""
    # 檢查是否已有服務
    cursor.execute('SELECT COUNT(*) FROM services')
    result = cursor.fetchone()
    # 處理不同資料庫類型的返回結果
    if result is None:
        count = 0
    elif isinstance(result, (int, tuple)):
        count = result[0]
    elif isinstance(result, dict):
        # PostgreSQL RealDictCursor 返回字典
        count = result.get('count', result.get(list(result.keys())[0], 0))
    else:
        # SQLite Row 或 PostgreSQL 普通 cursor 返回 tuple-like 對象
        count = result[0]
    
    if count > 0:
        return
    
    # 插入默認服務
    default_services = [
        ('基礎授權', '基礎軟體授權服務', 100.00, 365),
        ('專業授權', '專業軟體授權服務', 300.00, 365),
        ('企業授權', '企業級軟體授權服務', 800.00, 365),
        ('月度授權', '月度軟體授權服務', 50.00, 30),
        ('年度授權', '年度軟體授權服務', 500.00, 365)
    ]
    
    # 根據資料庫類型使用不同的參數占位符
    placeholder = get_placeholder()
    
    cursor.executemany('''
        INSERT INTO services (name, description, price, duration_days)
        VALUES ({}, {}, {}, {})
    '''.format(placeholder, placeholder, placeholder, placeholder), default_services)
    
    print("默認服務已初始化")


# ========== 資料庫檢查 ==========
def check_database():
    """
    檢查資料庫和表是否存在
    返回：(bool, list) - (是否正常, 錯誤信息列表)
    """
    errors = []
    
    # 檢查資料庫連接
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)
    except Exception as e:
        errors.append(f"資料庫連接失敗: {e}")
        return False, errors
    
    # 檢查表是否存在
    try:
        # 獲取所有表名
        tables = get_table_names(cursor)
        
        required_tables = ['users', 'verification_codes', 'services', 'user_services']
        missing_tables = [t for t in required_tables if t not in tables]
        
        if missing_tables:
            errors.append(f"缺少表: {', '.join(missing_tables)}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        errors.append(f"資料庫檢查失敗: {e}")
        return False, errors
    
    if errors:
        return False, errors
    return True, []


# ========== 資料庫統計 ==========
def get_database_stats():
    """
    獲取資料庫統計信息
    返回：dict - 包含各表的記錄數
    """
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)
        
        stats = {}
        
        # 輔助函數：獲取 COUNT(*) 查詢結果
        def get_count(result):
            """從 COUNT(*) 查詢結果中提取計數"""
            if result is None:
                return 0
            elif isinstance(result, (int, tuple)):
                return result[0]
            elif isinstance(result, dict):
                # PostgreSQL RealDictCursor 返回字典
                return result.get('count', result.get(list(result.keys())[0], 0))
            else:
                # SQLite Row 或 PostgreSQL 普通 cursor 返回 tuple-like 對象
                return result[0]
        
        # 統計 users
        cursor.execute("SELECT COUNT(*) FROM users")
        result = cursor.fetchone()
        stats['users'] = get_count(result)
        
        # 統計 services
        cursor.execute("SELECT COUNT(*) FROM services")
        result = cursor.fetchone()
        stats['services'] = get_count(result)
        
        # 統計 user_services
        cursor.execute("SELECT COUNT(*) FROM user_services")
        result = cursor.fetchone()
        stats['user_services'] = get_count(result)
        
        # 統計 active user_services
        cursor.execute("SELECT COUNT(*) FROM user_services WHERE status='active'")
        result = cursor.fetchone()
        stats['active_user_services'] = get_count(result)
        
        # 統計 verification_codes
        cursor.execute("SELECT COUNT(*) FROM verification_codes")
        result = cursor.fetchone()
        stats['verification_codes'] = get_count(result)
        
        cursor.close()
        conn.close()
        return stats
        
    except Exception as e:
        print(f"❌ 統計失敗: {e}")
        return {}


# ========== 測試程式 ==========
if __name__ == '__main__':
    print("=" * 50)
    print("資料庫管理工具")
    print("=" * 50)
    
    print(f"\n資料庫類型: {config.DATABASE_TYPE}")
    if config.DATABASE_TYPE == 'sqlite':
        print(f"資料庫路徑: {config.DATABASE_PATH}")
        # 檢查資料庫目錄
        db_dir = os.path.dirname(config.DATABASE_PATH)
        if not os.path.exists(db_dir):
            print(f"⚠️  創建資料庫目錄: {db_dir}")
            os.makedirs(db_dir, exist_ok=True)
    else:
        print(f"資料庫 URL: {config.DATABASE_URL[:20]}..." if config.DATABASE_URL else "未設置")
    
    # 初始化資料庫
    print("\n[1] 初始化資料庫...")
    init_database()
    
    # 檢查資料庫
    print("\n[2] 檢查資料庫...")
    ok, errors = check_database()
    if ok:
        print("✅ 資料庫檢查通過")
    else:
        print("❌ 資料庫檢查失敗:")
        for error in errors:
            print(f"  - {error}")
    
    # 顯示統計
    print("\n[3] 資料庫統計:")
    stats = get_database_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 50)
