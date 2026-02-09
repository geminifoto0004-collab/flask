"""
Flask ?æ?ç®¡ç?ç³»çµ± - è³æ?åº«ç®¡??
?è½ï¼å?å§å?è¡¨ãæ?ä¾é?¥?æ¸?é·ç§?
?¯æ?ï¼SQLite (PythonAnywhere)?PostgreSQL (Render) ??MySQL/TiDB (TiDB Cloud)
"""

import os
from datetime import datetime
from config import config
from utils.time_utils import get_chile_time_naive

# ?¹æ?è³æ?åº«é??å??¥ç¸?æ¨¡çµ?
POSTGRESQL_AVAILABLE = None
MYSQL_AVAILABLE = None

# ?è©¦å°å
# ¥ PostgreSQL æ¨¡ç?ï¼å??é?è¦ç?è©±ï?
try:
    import psycopg2  # type: ignore
    from psycopg2.extras import RealDictCursor  # type: ignore
    POSTGRESQL_AVAILABLE = True
except ImportError:
    POSTGRESQL_AVAILABLE = False

# ?ªå¨?è¦æ??é¡¯ç¤ºè­¦??
if not POSTGRESQL_AVAILABLE and config.DATABASE_TYPE == 'postgresql':
    print("? ï?  PostgreSQL æ¨¡ç??ªå?è£ï?è«é?è¡? pip install psycopg2-binary")

# ?è©¦å°å
# ¥ MySQL/TiDB æ¨¡ç?ï¼å??é?è¦ç?è©±ï?
try:
    import pymysql  # noqa: F401
    pymysql.install_as_MySQLdb()  # ä½?pymysql ?¼å®¹ MySQLdb
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# ?ªå¨?è¦æ??é¡¯ç¤ºè­¦??
if not MYSQL_AVAILABLE and config.DATABASE_TYPE in ('mysql', 'tidb'):
    print("? ï?  MySQL/TiDB æ¨¡ç??ªå?è£ï?è«é?è¡? pip install PyMySQL")

# SQLite ??Python æ¨æ?åº«ï?ç¸½æ¯?¯ç¨
# DBUtils connection pool (for MySQL/TiDB)
try:
    from DBUtils.PooledDB import PooledDB  # type: ignore
    POOLEDDB_AVAILABLE = True
except ImportError:
    POOLEDDB_AVAILABLE = False

_MYSQL_POOL = None

import sqlite3  # noqa: F401


# ========== SQL ?æ¸? ä?ç¬¦é©??==========
def adapt_sql(sql):
    """
    ?©é? SQL èªå¥?å??¸å?ä½ç¬¦
    SQLite ä½¿ç¨ ?ï¼PostgreSQL/MySQL/TiDB ä½¿ç¨ %s
    ?ºä??¼å®¹?§ï????SQL èªå¥?½ä½¿???ï¼æ­¤?½æ¸?èª?è??çº %sï¼PostgreSQL/MySQL/TiDBï¼?
    """
    if config.DATABASE_TYPE in ('postgresql', 'mysql', 'tidb'):
        # å°?? è½æ???%sï¼ä?è¦æ³¨?ä?è¦æ¿?å?ç¬¦ä¸²ä¸­ç? ?ï¼?
        # ç°¡å®?æ¿?ï?å°æ???? ?¿æ???%s
        # æ³¨æ?ï¼éå¯?½å¨?ä?è¤é? SQL ä¸­åº?é?ï¼ä?å°æ¼å¤§å??¸æ?æ³é½?©ç¨
        return sql.replace('?', '%s')
    else:
        return sql


def execute_sql(cursor, sql, params=None):
    """
    ?·è? SQL èªå¥?çµ±ä¸?¥å£ï¼èª?è??å??¸å?ä½ç¬¦è½æ?
    ?æ¸ï¼?
        cursor - è³æ?åº«æ¸¸æ¨?
        sql - SQL èªå¥ï¼å¯ä»¥ä½¿??? ? ä?ç¬¦ï??èª?è??çº %s å¦æ???PostgreSQLï¼?
        params - ?æ¸?ç??å?è¡¨ï??¯é¸ï¼?
    è¿å?ï¼cursor.execute() ?ç???
    ä½¿ç¨ç¯ä?ï¼?
        execute_sql(cursor, 'SELECT * FROM users WHERE id = ?', (user_id,))
    """
    # å¦æ???PostgreSQLï¼èª?è???? ??%s
    adapted_sql = adapt_sql(sql)
    
    if params:
        return cursor.execute(adapted_sql, params)
    else:
        return cursor.execute(adapted_sql)


def executemany_sql(cursor, sql, params_list):
    """
    ?¹é??·è? SQL èªå¥?çµ±ä¸?¥å£ï¼èª?è??å??¸å?ä½ç¬¦è½æ?
    ?æ¸ï¼?
        cursor - è³æ?åº«æ¸¸æ¨?
        sql - SQL èªå¥ï¼å¯ä»¥ä½¿??? ? ä?ç¬¦ï??èª?è??çº %s å¦æ???PostgreSQLï¼?
        params_list - ?æ¸?è¡¨
    è¿å?ï¼cursor.executemany() ?ç???
    ä½¿ç¨ç¯ä?ï¼?
        executemany_sql(cursor, 'INSERT INTO users (name) VALUES (?)', [('Alice',), ('Bob',)])
    """
    # å¦æ???PostgreSQLï¼èª?è???? ??%s
    adapted_sql = adapt_sql(sql)
    return cursor.executemany(adapted_sql, params_list)


# ========== è³æ?åº«é?¥ ==========
def get_db_connection():
    """
    ?²å?è³æ?åº«é?¥
    è¿å?ï¼è??åº«??¥å°è±¡ï¼SQLite?PostgreSQL ??MySQL/TiDBï¼?
    """
    try:
        if config.DATABASE_TYPE == 'postgresql':
            if not POSTGRESQL_AVAILABLE:
                raise ImportError("PostgreSQL æ¨¡ç??ªå?è£ï?è«é?è¡? pip install psycopg2-binary")
            
            if not config.DATABASE_URL:
                raise ValueError("DATABASE_URL ?°å?è®æ¸?ªè¨­ç½®ï?Render ?èª?æ?ä¾ï?")
            
            # PostgreSQL ??¥
            conn = psycopg2.connect(config.DATABASE_URL)
            # è¨­ç½®?ªå??äº¤??Falseï¼è? SQLite è¡çºä¸?´ï?
            conn.autocommit = False
            # ?
# è???¥ä»¥èª?é©??cursor
            return AdaptedConnection(conn)
        elif config.DATABASE_TYPE in ('mysql', 'tidb'):
            if not MYSQL_AVAILABLE:
                raise ImportError("MySQL/TiDB æ¨¡ç??ªå?è£ï?è«é?è¡? pip install PyMySQL")
            
            import pymysql
            
            # ?ªå?ä½¿ç¨ DATABASE_URLï¼å??æ??å?ä½¿ç¨?®ç¨?é?ç½?
            if config.DATABASE_URL:
                # è§?? MySQL URL ?¼å?ï¼mysql://user:password@host:port/database
                # ?è?TiDB URL ?¼å?é¡ä¼¼
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
                # æª¢æ¥ URL ?æ¸ä¸­æ¯?¦æ? SSL è¨­ç½®
                if parsed.query:
                    query_params = urllib.parse.parse_qs(parsed.query)
                    if query_params.get('ssl_mode') == ['REQUIRED']:
                        # TiDB Cloud è¦æ? SSL ??¥
                        db_config['ssl'] = {'check_hostname': False}
            else:
                if not config.MYSQL_HOST or not config.MYSQL_USER or not config.MYSQL_DATABASE:
                    raise ValueError("MySQL/TiDB ??¥?ç½®?ªè¨­ç½®ï?è«è¨­ç½?DATABASE_URL ??MYSQL_HOST/MYSQL_USER/MYSQL_DATABASE")
                db_config = {
                    'host': config.MYSQL_HOST,
                    'port': config.MYSQL_PORT,
                    'user': config.MYSQL_USER,
                    'password': config.MYSQL_PASSWORD,
                    'database': config.MYSQL_DATABASE,
                    'charset': 'utf8mb4',
                    'autocommit': False
                }
            
            # TiDB Cloud è¦æ? SSL ??¥ï¼èª?å???SSL
            # å¦æ? host ?
# å« tidbcloud.comï¼èª?å???SSL
            if 'tidbcloud.com' in db_config.get('host', '').lower():
                db_config['ssl'] = {'check_hostname': False}
            
            # è¨­ç½®é»è?ä½¿ç¨ DictCursorï¼è??å??¸æ ¼å¼ï?
            import pymysql.cursors
            db_config['cursorclass'] = pymysql.cursors.DictCursor
            
            # æ·»å?è¶
# æ?è¨­ç½®ï¼é¿?å¨ Render ä¸å¡ä½ï?
            # connect_timeout: ??¥è¶
# æ?ï¼ç?ï¼?
            # read_timeout: è®?è??ï?ç§ï?
            # write_timeout: å¯«å
# ¥è¶
# æ?ï¼ç?ï¼?
            db_config['connect_timeout'] = 10  # 10 ç§é?¥è¶
# æ?
            db_config['read_timeout'] = 10     # 10 ç§è??è???
            db_config['write_timeout'] = 10    # 10 ç§å¯«?¥è???
            
            # MySQL/TiDB ??¥
            global _MYSQL_POOL
            if POOLEDDB_AVAILABLE:
                if _MYSQL_POOL is None:
                    _MYSQL_POOL = PooledDB(
                        creator=pymysql,
                        mincached=1,
                        maxcached=5,
                        maxconnections=10,
                        blocking=True,
                        ping=1,
                        **db_config,
                    )
                conn = _MYSQL_POOL.connection()
            else:
                conn = pymysql.connect(**db_config)
            # ?
# è???¥ä»¥èª?é©??cursor
            return AdaptedConnection(conn)
        else:
            # SQLite ??¥
            # ç¢ºä?è³æ?åº«ç®?å???
            db_dir = os.path.dirname(config.DATABASE_PATH)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
            
            # SQLite ??¥?ç½®ï¼åª?ä¸¦?¼æ§è½ï¼é¿?å¨ Render ä¸å¡ä½ï?
            # timeout: 20 ç§ï?ç­å??å??è??æ??ï??¿å??¡æ­»ï¼?
            # check_same_thread: Falseï¼å?è¨±å?ç·ç?è¨ªå?ï¼Flask ?¯å?ç·ç??ï?
            conn = sqlite3.connect(
                config.DATABASE_PATH,
                timeout=20.0,  # 20 ç§è??ï??¿å??·æ??ç?å¾
# é?å®?
                check_same_thread=False  # ?è¨±å¤ç?ç¨è¨ª??
            )
            conn.row_factory = sqlite3.Row  # ä½¿æ¥è©¢ç??å¯ä»¥å?å­å
# ¸ä¸æ¨?¨ª??
            
            # ?ç¨ WAL æ¨¡å?ï¼Write-Ahead Loggingï¼æ?é«ä¸¦?¼æ§è½
            # WAL æ¨¡å??è¨±å¤åè??å?ä¸?å¯«?¥å??é²è?ï¼æ?å°é?å®?
            try:
                conn.execute('PRAGMA journal_mode=WAL')
            except Exception:
                # å¦æ??ç¨ WAL å¤±æ?ï¼ä?å¦æ?äºåªè®?ä»¶ç³»çµ±ï¼ï?å¿½ç¥?¯èª¤
                pass
            
            # ?
# è???¥ä»¥èª?é©??cursorï¼å³ä½?SQLite ä¸é?è¦è??ï?ä¹ä??ä??´æ§ï?
            return AdaptedConnection(conn)
    except Exception as e:
        print(f"è³æ?åº«é?¥å¤±æ?: {e}")
        raise


# ========== è³æ?åº«ç¹å®ç? SQL èªæ? ==========
def get_id_type():
    """?²å?ä¸»éµ ID é¡å?"""
    if config.DATABASE_TYPE == 'postgresql':
        return 'SERIAL PRIMARY KEY'
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        return 'INT AUTO_INCREMENT PRIMARY KEY'
    else:
        return 'INTEGER PRIMARY KEY AUTOINCREMENT'


def get_boolean_type():
    """?²å?å¸æ?é¡å?"""
    if config.DATABASE_TYPE == 'postgresql':
        return 'BOOLEAN'
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        return 'BOOLEAN'  # MySQL 5.7.8+ ??TiDB ?¯æ? BOOLEAN
    else:
        return 'INTEGER'


def get_text_type():
    """?²å??æ¬é¡å?ï¼SQLite ??TEXTï¼PostgreSQL ??TEXTï¼MySQL/TiDB ??TEXTï¼?"""
    if config.DATABASE_TYPE == 'postgresql':
        return 'TEXT'
    else:
        return 'TEXT'

def get_text_type_with_default():
    """
    ?²å?å¸¶é?èªå¼ç??æ¬é¡å?
    MySQL/TiDB ??TEXT é¡å?ä¸æ¯??DEFAULTï¼æ?ä»¥ä½¿??VARCHAR(255)
    SQLite ??PostgreSQL ä½¿ç¨ TEXT
    """
    if config.DATABASE_TYPE in ('mysql', 'tidb'):
        return 'VARCHAR(255)'  # MySQL/TiDB ä½¿ç¨ VARCHAR ä»¥æ¯??DEFAULT
    else:
        return 'TEXT'  # SQLite ??PostgreSQL ä½¿ç¨ TEXT

def get_text_type_unique():
    """
    ?²å??¨æ¼ UNIQUE ç´æ??æ??¬é???
    MySQL/TiDB ??TEXT é¡å?ä¸è½?´æ¥?¨æ¼ UNIQUE ç´æ?ï¼æ?ä»¥ä½¿??VARCHAR(255)
    SQLite ??PostgreSQL ä½¿ç¨ TEXT
    """
    if config.DATABASE_TYPE in ('mysql', 'tidb'):
        return 'VARCHAR(255)'  # MySQL/TiDB ä½¿ç¨ VARCHAR ä»¥æ¯??UNIQUE ç´æ?
    else:
        return 'TEXT'  # SQLite ??PostgreSQL ä½¿ç¨ TEXT


def get_text_type_uuid():
    """UUID 欄位型別（MySQL/TiDB 用 VARCHAR 方便索引）"""
    if config.DATABASE_TYPE in ('mysql', 'tidb'):
        return 'VARCHAR(36)'
    else:
        return 'TEXT'


def get_timestamp_default():
    """?²å??é??³é?èªå?"""
    # ??è??åº«?½æ¯??CURRENT_TIMESTAMP
    return "DEFAULT CURRENT_TIMESTAMP"


class AdaptedCursor:
    """
    ?
è???Cursor é¡ï??ªå??ç? SQL ?æ¸? ä?ç¬¦è???
    ?æ¨£å°±ä??è¦ä¿®?¹ç¾?ä»£ç¢¼ï????cursor.execute() ?½æ??ªå??©é?
    """
    def __init__(self, cursor):
        self._cursor = cursor
    
    def __getattr__(self, name):
        # å°æ??å
# ¶ä»å±¬?§å??¹æ?å§è?çµ¦å?å§?cursor
        return getattr(self._cursor, name)
    
    def execute(self, sql, params=None):
        """?·è? SQLï¼èª?é©?å??¸å?ä½ç¬¦"""
        adapted_sql = adapt_sql(sql)
        if params:
            return self._cursor.execute(adapted_sql, params)
        else:
            return self._cursor.execute(adapted_sql)
    
    def executemany(self, sql, params_list):
        """?¹é??·è? SQLï¼èª?é©?å??¸å?ä½ç¬¦"""
        adapted_sql = adapt_sql(sql)
        return self._cursor.executemany(adapted_sql, params_list)


class AdaptedConnection:
    """
    ?
è???Connection é¡ï??ªå??ç????cursor ??SQL ?æ¸? ä?ç¬¦è???
    ?æ¨£å°±ä??è¦ä¿®?¹ç¾?ä»£ç¢¼ï????conn.cursor() ?½æ??ªå?è¿å??©é???cursor
    """
    def __init__(self, conn):
        self._conn = conn
    
    def __getattr__(self, name):
        # å°æ??å
# ¶ä»å±¬?§å??¹æ?å§è?çµ¦å?å§é?¥
        return getattr(self._conn, name)
    
    def cursor(self, *args, **kwargs):
        """?µå»º cursorï¼èª?å?è£çº AdaptedCursor"""
        if config.DATABASE_TYPE == 'postgresql':
            from psycopg2.extras import RealDictCursor  # type: ignore
            cursor = self._conn.cursor(cursor_factory=RealDictCursor, *args, **kwargs)
        elif config.DATABASE_TYPE in ('mysql', 'tidb'):
            # PyMySQL ??¥?å·²ç¶è¨­ç½®ä? cursorclass=DictCursor
            # ?´æ¥?µå»º cursor ?³å¯ï¼æ??ªå?ä½¿ç¨ DictCursor
            # ç§»é¤ä»»ä??¯è½?³é???cursorclass ??cursor ?æ¸ï¼PyMySQL ä¸æ¥?ï?
            kwargs_clean = {k: v for k, v in kwargs.items() if k not in ('cursorclass', 'cursor', 'cursor_factory')}
            cursor = self._conn.cursor(*args, **kwargs_clean)
        else:
            cursor = self._conn.cursor(*args, **kwargs)
        return AdaptedCursor(cursor)


def get_cursor(conn, use_adapter=True):
    """
    ?²å?æ¸¸æ?ï¼PostgreSQL ä½¿ç¨ RealDictCursorï¼MySQL/TiDB ä½¿ç¨ DictCursorï¼SQLite ä½¿ç¨?®éæ¸¸æ¨ï?
    ?æ¸ï¼?
        conn - è³æ?åº«é?¥
        use_adapter - ?¯å¦ä½¿ç¨?©é??¨ï?é»è? Trueï¼èª?è???SQL ? ä?ç¬¦è??ï?
    è¿å?ï¼cursor å°è±¡ï¼å???use_adapter=Trueï¼è???AdaptedCursorï¼?
    """
    if config.DATABASE_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor  # type: ignore
        cursor = conn.cursor(cursor_factory=RealDictCursor)
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        # PyMySQL ??¥?å·²ç¶è¨­ç½®ä? cursorclass=DictCursor
        # ?´æ¥?µå»º cursor ?³å¯ï¼æ??ªå?ä½¿ç¨ DictCursor
        cursor = conn.cursor()
    else:
        cursor = conn.cursor()
    
    # å¦æ??ç¨?©é??¨ï??
# è? cursor ä»¥èª?è???SQL ? ä?ç¬¦è???
    if use_adapter:
        return AdaptedCursor(cursor)
    else:
        return cursor


def get_row_dict(row, cursor):
    """å°æ¥è©¢ç??è??çºå­å
¸"""
    if config.DATABASE_TYPE == 'postgresql':
        return dict(row) if row else None
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        # PyMySQL DictCursor å·²ç?è¿å?å­å
# ¸
        return dict(row) if row else None
    else:
        # SQLite Row ?è¦è???
        if row:
            return {key: row[key] for key in row.keys()}
        return None


def get_lastrowid(cursor, conn):
    """?²å??å¾æ??¥ç? ID"""
    if config.DATABASE_TYPE == 'postgresql':
        # PostgreSQL ä½¿ç¨ LASTVAL()
        cursor.execute("SELECT LASTVAL()")
        result = cursor.fetchone()
        # ?ç?ä¸å??è??æ ¼å¼?
        if isinstance(result, (list, tuple)):
            return result[0]
        elif isinstance(result, dict):
            return result['lastval']
        else:
            return result
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        # MySQL/TiDB ä½¿ç¨ LAST_INSERT_ID()
        cursor.execute("SELECT LAST_INSERT_ID()")
        result = cursor.fetchone()
        if isinstance(result, (list, tuple)):
            return result[0]
        elif isinstance(result, dict):
            return result['LAST_INSERT_ID()']
        else:
            return result
    else:
        # SQLite ä½¿ç¨ cursor.lastrowid
        return cursor.lastrowid


def check_column_exists(cursor, table_name, column_name):
    """æª¢æ¥?æ¯?¦å???"""
    if config.DATABASE_TYPE == 'postgresql':
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s AND column_name = %s
        """, (table_name, column_name))
        return cursor.fetchone() is not None
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        # MySQL/TiDB ä½¿ç¨ information_schemaï¼é?ä¼?PostgreSQLï¼?
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s AND column_name = %s
        """, (table_name, column_name))
        return cursor.fetchone() is not None
    else:
        # SQLite ä½¿ç¨ PRAGMA
        cursor.execute("PRAGMA table_info({})".format(table_name))
        columns = [column[1] for column in cursor.fetchall()]
        return column_name in columns


def check_index_exists(cursor, table_name, index_name):
    """檢查索引是否存在"""
    if config.DATABASE_TYPE == 'postgresql':
        cursor.execute(
            """
            SELECT 1
            FROM pg_indexes
            WHERE tablename = %s AND indexname = %s
            """,
            (table_name, index_name),
        )
        return cursor.fetchone() is not None
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = %s
              AND index_name = %s
            """,
            (table_name, index_name),
        )
        return cursor.fetchone() is not None
    else:
        cursor.execute("PRAGMA index_list({})".format(table_name))
        rows = cursor.fetchall()
        names = []
        for row in rows:
            if isinstance(row, dict):
                names.append(row.get('name'))
            elif hasattr(row, 'keys'):
                names.append(row['name'])
            elif isinstance(row, (list, tuple)) and len(row) > 1:
                names.append(row[1])
        return index_name in names


def get_table_names(cursor):
    """?²å???è¡¨??"""
    if config.DATABASE_TYPE == 'postgresql':
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        return [row[0] if isinstance(row, tuple) else row['table_name'] for row in cursor.fetchall()]
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        # MySQL/TiDB ä½¿ç¨ information_schemaï¼é?ä¼?PostgreSQLï¼ä?ä½¿ç¨ database() ?½æ¸ï¼?
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
    """?²å? SQL ?æ¸? ä?ç¬¦ï?SQLite ???ï¼PostgreSQL/MySQL/TiDB ??%sï¼?"""
    if config.DATABASE_TYPE in ('postgresql', 'mysql', 'tidb'):
        return '%s'
    else:
        return '?'


# ========== è³æ?åº«å?å§å? ==========
def init_database():
    """
    ?å??æ??è??åº«è¡?
    å¦æ?è¡¨å·²å­å¨?è·³??
    """
    conn = get_db_connection()
    cursor = get_cursor(conn)
    
    try:
        # ?µå»º users è¡?
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id {id_type},
                username {text_type_unique} UNIQUE NOT NULL,
                email {text_type_unique} UNIQUE NOT NULL,
                password_hash {text_type} NOT NULL,
                role {text_type_with_default} DEFAULT 'user',
                created_at TIMESTAMP {timestamp_default}
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            text_type_unique=get_text_type_unique(),
            text_type_with_default=get_text_type_with_default(),
            timestamp_default=get_timestamp_default()
        ))
        print("users è¡¨å·²å°±ç?")
        
        # æª¢æ¥?¯å¦?è¦æ·»??company_name ?ï??å??¼å®¹ï¼?
        if not check_column_exists(cursor, 'users', 'company_name'):
            cursor.execute('ALTER TABLE users ADD COLUMN company_name {text_type}'.format(
                text_type=get_text_type()
            ))
            print("Added company_name column to users")
        
        # ?µå»º services è¡¨ï??å??¢å?ï¼?
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS services (
                id {id_type},
                name {text_type} NOT NULL,
                description {text_type},
                price DECIMAL(10,2),
                duration_days INTEGER,
                version {text_type_with_default} DEFAULT 'FREE',
                config_json {text_type},
                status {text_type_with_default} DEFAULT 'active',
                created_at TIMESTAMP {timestamp_default}
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            text_type_with_default=get_text_type_with_default(),
            timestamp_default=get_timestamp_default()
        ))
        print("services è¡¨å·²å°±ç?")
        
        # æª¢æ¥?¯å¦?è¦æ·»? æ°?ï??å??¼å®¹ï¼?
        if not check_column_exists(cursor, 'services', 'version'):
            cursor.execute('ALTER TABLE services ADD COLUMN version {text_type_with_default} DEFAULT \'FREE\''.format(
                text_type_with_default=get_text_type_with_default()
            ))
            print("Added version column to services")
        
        if not check_column_exists(cursor, 'services', 'config_json'):
            cursor.execute('ALTER TABLE services ADD COLUMN config_json {text_type}'.format(
                text_type=get_text_type()
            ))
            print("Added config_json column to services")
        
        # ?µå»º user_services è¡¨ï??¨æ¶è³¼è²·?æ??ï?
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_services (
                id {id_type},
                user_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                status {text_type_with_default} DEFAULT 'active',
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
            text_type_with_default=get_text_type_with_default(),
            timestamp_default=get_timestamp_default()
        ))
        print("user_services è¡¨å·²å°±ç?")
        
        # æª¢æ¥?¯å¦?è¦æ·»??config_json ?ï??å??¼å®¹ï¼?
        if not check_column_exists(cursor, 'user_services', 'config_json'):
            cursor.execute('ALTER TABLE user_services ADD COLUMN config_json {text_type}'.format(
                text_type=get_text_type()
            ))
            print("Added config_json column to user_services")
        
        # ?µå»º?å??æ¬è¡?
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
        print("service_versions è¡¨å·²å°±ç?")
        
        # ?µå»º?¨æ¶?è©±è¡¨ï??¨æ¼è¨é??¨æ¶ä¸ç???ï?
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
        print("user_sessions è¡¨å·²å°±ç?")
        
        # æª¢æ¥ä¸¦æ·»? æ°å­æ®µï¼å?å¾å
# ¼å®¹ï?
        if not check_column_exists(cursor, 'user_sessions', 'session_token'):
            cursor.execute('ALTER TABLE user_sessions ADD COLUMN session_token VARCHAR(255)')
            print("Added session_token column to user_sessions")
        
        if not check_column_exists(cursor, 'user_sessions', 'device_info'):
            cursor.execute('ALTER TABLE user_sessions ADD COLUMN device_info {text_type}'.format(
                text_type=get_text_type()
            ))
            print("Added device_info column to user_sessions")
            
        
        # ?µå»º verification_codes è¡¨ï??µä»¶é©è??¨ï?
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
        print("verification_codes è¡¨å·²å°±ç?")
        
        # ?µå»º user_monitor_configs è¡¨ï??¨æ¶??§ä»»å??ç½®ï¼?
        boolean_type = get_boolean_type()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_monitor_configs (
                id {id_type},
                user_id INTEGER NOT NULL,
                api_key {text_type_unique} UNIQUE NOT NULL,
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
            text_type_unique=get_text_type_unique(),
            boolean_type=boolean_type,
            timestamp_default=get_timestamp_default()
        ))
        print("user_monitor_configs è¡¨å·²å°±ç?")
        
        # æª¢æ¥?¯å¦?è¦æ·»? æ°?ï??å??¼å®¹ï¼?
        if not check_column_exists(cursor, 'user_monitor_configs', 'company_name'):
            cursor.execute('ALTER TABLE user_monitor_configs ADD COLUMN company_name {text_type}'.format(
                text_type=get_text_type()
            ))
            print("Added company_name column to user_monitor_configs")
        
        if not check_column_exists(cursor, 'user_monitor_configs', 'email_subject'):
            cursor.execute('ALTER TABLE user_monitor_configs ADD COLUMN email_subject {text_type}'.format(
                text_type=get_text_type()
            ))
            print("Added email_subject column to user_monitor_configs")
        
        # ?µå»º async_tasks è¡¨ï??¨æ¼?°æ­¥ä»»å?ï¼?
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS async_tasks (
                id {id_type},
                task_id {text_type_unique} UNIQUE NOT NULL,
                task_type {text_type} NOT NULL,
                status {text_type_with_default} DEFAULT 'pending',
                task_config {text_type},
                task_data {text_type},
                result {text_type},
                error {text_type},
                created_at TIMESTAMP {timestamp_default},
                updated_at TIMESTAMP
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            text_type_unique=get_text_type_unique(),
            text_type_with_default=get_text_type_with_default(),
            timestamp_default=get_timestamp_default()
        ))
        print("async_tasks è¡¨å·²å°±ç?")

        # container access admin
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS container_access_admin (
                id {id_type},
                password {text_type} NOT NULL,
                session_timeout_minutes INTEGER,
                updated_at TIMESTAMP {timestamp_default}
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            timestamp_default=get_timestamp_default()
        ))
        print("container_access_admin table ready")

        # container access tokens
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS container_access_tokens (
                id {id_type},
                token {text_type_unique} UNIQUE NOT NULL,
                latest_save_id {save_id_type},
                note {text_type},
                status {text_type_with_default} DEFAULT 'active',
                expires_at TIMESTAMP,
                blocked_until TIMESTAMP,
                max_concurrent INTEGER,
                created_at TIMESTAMP {timestamp_default},
                last_used_at TIMESTAMP
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            text_type_unique=get_text_type_unique(),
            text_type_with_default=get_text_type_with_default(),
            timestamp_default=get_timestamp_default()
        ))
        print("container_access_tokens table ready")
        if not check_column_exists(cursor, 'container_access_tokens', 'blocked_until'):
            cursor.execute("ALTER TABLE container_access_tokens ADD COLUMN blocked_until TIMESTAMP")
            print("Added blocked_until column to container_access_tokens")
        if not check_column_exists(cursor, 'container_access_tokens', 'latest_save_id'):
            cursor.execute(
                'ALTER TABLE container_access_tokens ADD COLUMN latest_save_id {text_type}'.format(
                    text_type=get_text_type_uuid()
                )
            )
            print("Added latest_save_id column to container_access_tokens")

        # container access sessions
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS container_access_sessions (
                id {id_type},
                token {text_type} NOT NULL,
                session_id {text_type_unique} UNIQUE NOT NULL,
                last_heartbeat TIMESTAMP,
                ip {text_type},
                user_agent {text_type},
                created_at TIMESTAMP {timestamp_default}
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            text_type_unique=get_text_type_unique(),
            timestamp_default=get_timestamp_default()
        ))
        print("container_access_sessions table ready")

        # container items
        boolean_type = get_boolean_type()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS container_items (
                id {id_type},
                access_token {text_type},
                company {text_type},
                container_no {text_type},
                vessel {text_type},
                eta {text_type},
                status {text_type},
                folio {text_type},
                sigla {text_type},
                numero {text_type},
                digito {text_type},
                fecha_entrega {text_type},
                pies {text_type},
                save_id {save_id_type},
                saved_at TIMESTAMP,
                has_data {boolean_type} DEFAULT 0,
                last_notified_at TIMESTAMP
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type(),
            save_id_type=get_text_type_uuid(),
            save_id_type=get_text_type_uuid(),
            boolean_type=boolean_type
        ))
        print("container_items table ready")

        if not check_column_exists(cursor, 'container_items', 'access_token'):
            cursor.execute('ALTER TABLE container_items ADD COLUMN access_token {text_type}'.format(
                text_type=get_text_type()
            ))
            print("container_items access_token column added")
        if not check_column_exists(cursor, 'container_items', 'save_id'):
            cursor.execute('ALTER TABLE container_items ADD COLUMN save_id {text_type}'.format(
                text_type=get_text_type_uuid()
            ))
            print("container_items save_id column added")
        if not check_column_exists(cursor, 'container_items', 'saved_at'):
            cursor.execute("ALTER TABLE container_items ADD COLUMN saved_at TIMESTAMP")
            print("container_items saved_at column added")

        # container_items indexes for latest-save lookups
        if not check_index_exists(cursor, 'container_items', 'idx_container_items_token_save'):
            if config.DATABASE_TYPE in ('mysql', 'tidb'):
                cursor.execute(
                    "CREATE INDEX idx_container_items_token_save "
                    "ON container_items (access_token(128), save_id)"
                )
            else:
                cursor.execute(
                    "CREATE INDEX idx_container_items_token_save "
                    "ON container_items (access_token, save_id)"
                )
            print("container_items idx_container_items_token_save index added")

        if not check_index_exists(cursor, 'container_items', 'idx_container_items_token_savedat'):
            if config.DATABASE_TYPE in ('mysql', 'tidb'):
                cursor.execute(
                    "CREATE INDEX idx_container_items_token_savedat "
                    "ON container_items (access_token(128), saved_at)"
                )
            else:
                cursor.execute(
                    "CREATE INDEX idx_container_items_token_savedat "
                    "ON container_items (access_token, saved_at)"
                )
            print("container_items idx_container_items_token_savedat index added")
        # container ITI cache
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS container_iti_cache (
                id {id_type},
                payload {text_type},
                updated_at TIMESTAMP,
                lock_until TIMESTAMP
            )
        '''.format(
            id_type=get_id_type(),
            text_type=get_text_type()
        ))
        print("container_iti_cache table ready")
        
        # ?å??é?èªæ???
        init_default_services(cursor)
        
        # ?ªå??µå»ºè¶
# ç?ç®¡ç??¡ï?å¦æ?ä¸å??¨ï?
        init_super_admin(cursor)
        
        conn.commit()
        print("è³æ?åº«å?å§å?å®æ?")
        
    except Exception as e:
        print(f"è³æ?åº«å?å§å?å¤±æ?: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def init_default_services(cursor):
    """?å??é?èªæ???"""
    # æª¢æ¥?¯å¦å·²æ??å?
    cursor.execute('SELECT COUNT(*) FROM services')
    result = cursor.fetchone()
    # ?ç?ä¸å?è³æ?åº«é??ç?è¿å?çµæ?
    if result is None:
        count = 0
    elif isinstance(result, (int, tuple)):
        count = result[0]
    elif isinstance(result, dict):
        # PostgreSQL RealDictCursor è¿å?å­å
# ¸
        count = result.get('count', result.get(list(result.keys())[0], 0))
    else:
        # SQLite Row ??PostgreSQL ?®é?cursor è¿å? tuple-like å°è±¡
        count = result[0]
    
    if count > 0:
        return
    
    # ?å
# ¥é»è??å?
    default_services = [
        ("Basic Plan", "Basic service plan", 100.00, 365),
        ("Pro Plan", "Professional service plan", 300.00, 365),
        ("Enterprise Plan", "Enterprise service plan", 800.00, 365),
        ("Monthly Plan", "Monthly service plan", 50.00, 30),
        ("Annual Plan", "Annual service plan", 500.00, 365)
    ]
    
    # ?¹æ?è³æ?åº«é??ä½¿?¨ä??ç??æ¸? ä?ç¬?
    placeholder = get_placeholder()
    
    cursor.executemany('''
        INSERT INTO services (name, description, price, duration_days)
        VALUES ({}, {}, {}, {})
    '''.format(placeholder, placeholder, placeholder, placeholder), default_services)
    
    print("é»è??å?å·²å?å§å?")


def init_super_admin(cursor):
    """?ªå??µå»ºè¶
ç?ç®¡ç??¡ç¨?¶ï?å¦æ?ä¸å??¨ï?"""
    try:
        from config import admin_config
        from utils.time_utils import get_chile_time_naive
        
        # æª¢æ¥?¯å¦å·²å???
        cursor.execute('SELECT id FROM users WHERE email = ?', (admin_config.SUPER_ADMIN_EMAIL,))
        user_row = cursor.fetchone()
        
        if user_row:
            # è¶
# ç?ç®¡ç??¡å·²å­å¨ï¼è·³??
            return
        
        # ?µå»ºè¶
# ç?ç®¡ç???
        from services.user_service import hash_password
        password_hash = hash_password(admin_config.SUPER_ADMIN_PASSWORD)
        created_at = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
        
        placeholder = get_placeholder()
        cursor.execute(f'''
            INSERT INTO users (username, email, password_hash, role, created_at)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
        ''', (admin_config.SUPER_ADMIN_USERNAME, admin_config.SUPER_ADMIN_EMAIL, 
              password_hash, admin_config.SUPER_ADMIN_ROLE, created_at))
        
        print("Super admin user created:")

        print(f"   ?µç®±: {admin_config.SUPER_ADMIN_EMAIL}")
        print(f"   å¯ç¢¼: {admin_config.SUPER_ADMIN_PASSWORD}")
        print(f"   ?¨æ¶?? {admin_config.SUPER_ADMIN_USERNAME}")
        print(f"   è§è²: {admin_config.SUPER_ADMIN_ROLE}")
        
    except Exception as e:
        print(f"Super admin user creation failed: {e}")

        # ä¸æ??ºç°å¸¸ï??¿å??»æ­¢?¸æ?åº«å?å§å?
        import traceback
        traceback.print_exc()


# ========== è³æ?åº«æª¢??==========
def check_database():
    """
    æª¢æ¥è³æ?åº«å?è¡¨æ¯?¦å???
    è¿å?ï¼?bool, list) - (?¯å¦æ­?¸¸, ?¯èª¤ä¿¡æ¯?è¡¨)
    """
    errors = []
    
    # æª¢æ¥è³æ?åº«é?¥
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)
    except Exception as e:
        errors.append(f"è³æ?åº«é?¥å¤±æ?: {e}")
        return False, errors
    
    # æª¢æ¥è¡¨æ¯?¦å???
    try:
        # ?²å???è¡¨??
        tables = get_table_names(cursor)
        
        required_tables = ['users', 'verification_codes', 'services', 'user_services']
        missing_tables = [t for t in required_tables if t not in tables]
        
        if missing_tables:
            errors.append(f"ç¼ºå?è¡? {', '.join(missing_tables)}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        errors.append(f"è³æ?åº«æª¢?¥å¤±?? {e}")
        return False, errors
    
    if errors:
        return False, errors
    return True, []


# ========== è³æ?åº«çµ±è¨?==========
def get_database_stats():
    """
    ?²å?è³æ?åº«çµ±è¨ä¿¡??
    è¿å?ï¼dict - ?
å«?è¡¨?è??æ¸
    """
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)
        
        stats = {}
        
        # è¼å©?½æ¸ï¼ç²??COUNT(*) ?¥è©¢çµæ?
        def get_count(result):
            """å¾?COUNT(*) ?¥è©¢çµæ?ä¸­æ??è???"""
            if result is None:
                return 0
            elif isinstance(result, (int, tuple)):
                return result[0]
            elif isinstance(result, dict):
                # PostgreSQL RealDictCursor è¿å?å­å
# ¸
                return result.get('count', result.get(list(result.keys())[0], 0))
            else:
                # SQLite Row ??PostgreSQL ?®é?cursor è¿å? tuple-like å°è±¡
                return result[0]
        
        # çµ±è? users
        cursor.execute("SELECT COUNT(*) FROM users")
        result = cursor.fetchone()
        stats['users'] = get_count(result)
        
        # çµ±è? services
        cursor.execute("SELECT COUNT(*) FROM services")
        result = cursor.fetchone()
        stats['services'] = get_count(result)
        
        # çµ±è? user_services
        cursor.execute("SELECT COUNT(*) FROM user_services")
        result = cursor.fetchone()
        stats['user_services'] = get_count(result)
        
        # çµ±è? active user_services
        cursor.execute("SELECT COUNT(*) FROM user_services WHERE status='active'")
        result = cursor.fetchone()
        stats['active_user_services'] = get_count(result)
        
        # çµ±è? verification_codes
        cursor.execute("SELECT COUNT(*) FROM verification_codes")
        result = cursor.fetchone()
        stats['verification_codes'] = get_count(result)
        
        cursor.close()
        conn.close()
        return stats
        
    except Exception as e:
        print(f"??çµ±è?å¤±æ?: {e}")
        return {}


# ========== æ¸¬è©¦ç¨å? ==========
if __name__ == '__main__':
    print("=" * 50)
    print("Database Management Tool")
    print("=" * 50)
    
    print(f"\nè³æ?åº«é??? {config.DATABASE_TYPE}")
    if config.DATABASE_TYPE == 'sqlite':
        print(f"è³æ?åº«è·¯å¾? {config.DATABASE_PATH}")
        # æª¢æ¥è³æ?åº«ç®??
        db_dir = os.path.dirname(config.DATABASE_PATH)
        if not os.path.exists(db_dir):
            print(f"? ï?  ?µå»ºè³æ?åº«ç®?? {db_dir}")
            os.makedirs(db_dir, exist_ok=True)
    else:
        print(f"Database URL: {config.DATABASE_URL[:20]}..." if config.DATABASE_URL else "Database URL: (not set)")
    
    # ?å??è??åº«
    print("\n[1] ?å??è??åº«...")
    init_database()
    
    # æª¢æ¥è³æ?åº?
    print("\n[2] æª¢æ¥è³æ?åº?..")
    ok, errors = check_database()
    if ok:
        print("??è³æ?åº«æª¢?¥éé?")
    else:
        print("??è³æ?åº«æª¢?¥å¤±??")
        for error in errors:
            print(f"  - {error}")
    
    # é¡¯ç¤ºçµ±è?
    print("\n[3] è³æ?åº«çµ±è¨?")
    stats = get_database_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 50)
