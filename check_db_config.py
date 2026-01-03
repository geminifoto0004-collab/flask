"""
資料庫配置檢查工具
用於檢查當前環境的資料庫配置
"""

from config import config
import os

def check_database_config():
    """檢查資料庫配置"""
    print("=" * 60)
    print("資料庫配置檢查")
    print("=" * 60)
    
    # 檢查環境變數（支持兩種命名方式）
    env_db_type = os.environ.get('DATABASE_TYPE') or os.environ.get('DB_TYPE', 'Not set')
    env_db_path = os.environ.get('DATABASE_PATH', 'Not set')
    env_db_url = os.environ.get('DATABASE_URL', 'Not set')
    
    # 檢查 MySQL/TiDB 相關環境變數
    env_mysql_host = os.environ.get('MYSQL_HOST') or os.environ.get('DB_HOST', 'Not set')
    env_mysql_port = os.environ.get('MYSQL_PORT') or os.environ.get('DB_PORT', 'Not set')
    env_mysql_user = os.environ.get('MYSQL_USER') or os.environ.get('DB_USER', 'Not set')
    env_mysql_password = os.environ.get('MYSQL_PASSWORD') or os.environ.get('DB_PASSWORD', 'Not set')
    env_mysql_database = os.environ.get('MYSQL_DATABASE') or os.environ.get('DB_NAME', 'Not set')
    
    print("\n[1] 環境變數:")
    print(f"   DATABASE_TYPE / DB_TYPE: {env_db_type}")
    if env_db_path != 'Not set':
        print(f"   DATABASE_PATH: {env_db_path}")
    if env_db_url != 'Not set':
        print(f"   DATABASE_URL: {env_db_url[:50]}..." if len(env_db_url) > 50 else f"   DATABASE_URL: {env_db_url}")
    if env_db_type.lower() in ('mysql', 'tidb'):
        if env_mysql_host != 'Not set':
            print(f"   MYSQL_HOST / DB_HOST: {env_mysql_host}")
        if env_mysql_port != 'Not set':
            print(f"   MYSQL_PORT / DB_PORT: {env_mysql_port}")
        if env_mysql_user != 'Not set':
            print(f"   MYSQL_USER / DB_USER: {env_mysql_user}")
        if env_mysql_password != 'Not set':
            print(f"   MYSQL_PASSWORD / DB_PASSWORD: {'*' * len(env_mysql_password)}")
        if env_mysql_database != 'Not set':
            print(f"   MYSQL_DATABASE / DB_NAME: {env_mysql_database}")
    
    # 檢查 config.py 中的配置
    print("\n[2] config.py 配置:")
    print(f"   DATABASE_TYPE: {config.DATABASE_TYPE}")
    print(f"   DATABASE_PATH: {config.DATABASE_PATH}")
    if config.DATABASE_URL:
        print(f"   DATABASE_URL: {config.DATABASE_URL[:50]}..." if len(config.DATABASE_URL) > 50 else f"   DATABASE_URL: {config.DATABASE_URL}")
    else:
        print(f"   DATABASE_URL: Not set")
    
    # 判斷當前使用的配置
    print("\n[3] 當前使用的配置:")
    if config.DATABASE_TYPE == 'sqlite':
        print("   [OK] 資料庫類型: SQLite")
        print(f"   [PATH] 資料庫路徑: {config.DATABASE_PATH}")
        print("   [INFO] 適用於: 本地開發、PythonAnywhere")
    elif config.DATABASE_TYPE == 'postgresql':
        print("   [OK] 資料庫類型: PostgreSQL")
        if config.DATABASE_URL:
            print(f"   [URL] 連接字符串: {config.DATABASE_URL[:50]}..." if len(config.DATABASE_URL) > 50 else f"   [URL] 連接字符串: {config.DATABASE_URL}")
        else:
            print("   [WARN] 警告: DATABASE_URL 未設置")
        print("   [INFO] 適用於: Render")
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        db_type_name = 'TiDB' if config.DATABASE_TYPE == 'tidb' else 'MySQL'
        print(f"   [OK] 資料庫類型: {db_type_name}")
        if config.DATABASE_URL:
            print(f"   [URL] 連接字符串: {config.DATABASE_URL[:50]}..." if len(config.DATABASE_URL) > 50 else f"   [URL] 連接字符串: {config.DATABASE_URL}")
        else:
            if config.MYSQL_HOST and config.MYSQL_HOST != 'localhost':
                print(f"   [HOST] 主機: {config.MYSQL_HOST}")
            if config.MYSQL_PORT and config.MYSQL_PORT != 4000:
                print(f"   [PORT] 端口: {config.MYSQL_PORT}")
            if config.MYSQL_USER:
                print(f"   [USER] 用戶名: {config.MYSQL_USER}")
            if config.MYSQL_PASSWORD:
                print(f"   [PASSWORD] 密碼: {'*' * len(config.MYSQL_PASSWORD)}")
            if config.MYSQL_DATABASE:
                print(f"   [DATABASE] 數據庫名: {config.MYSQL_DATABASE}")
            if not (config.MYSQL_HOST and config.MYSQL_USER and config.MYSQL_DATABASE):
                print("   [WARN] 警告: MySQL/TiDB 連接配置不完整")
                print("   [TIP] 請設置 DATABASE_URL 或 MYSQL_HOST/MYSQL_USER/MYSQL_DATABASE")
        print("   [INFO] 適用於: TiDB Cloud, MySQL")
    else:
        print(f"   [WARN] 未知的資料庫類型: {config.DATABASE_TYPE}")
        print("   [INFO] 使用默認值: sqlite")
    
    # 檢查環境變數是否設置
    print("\n[4] 配置來源:")
    if env_db_type != 'Not set':
        print("   [OK] 使用環境變數配置 (環境變數優先)")
    else:
        print("   [INFO] 使用 config.py 默認配置 (環境變數未設置)")
    
    # 建議
    print("\n[5] 建議:")
    if config.DATABASE_TYPE == 'sqlite':
        print("   [OK] SQLite 配置正確，適合本地開發和 PythonAnywhere")
    elif config.DATABASE_TYPE == 'postgresql':
        if config.DATABASE_URL:
            print("   [OK] PostgreSQL 配置正確，適合 Render")
        else:
            print("   [WARN] PostgreSQL 類型已設置，但 DATABASE_URL 未設置")
            print("   [TIP] 請設置 DATABASE_URL 環境變數")
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        db_type_name = 'TiDB' if config.DATABASE_TYPE == 'tidb' else 'MySQL'
        if config.DATABASE_URL or (config.MYSQL_HOST and config.MYSQL_USER and config.MYSQL_DATABASE):
            print(f"   [OK] {db_type_name} 配置正確，適合 TiDB Cloud 或 MySQL")
        else:
            print(f"   [WARN] {db_type_name} 類型已設置，但連接配置不完整")
            print("   [TIP] 請設置 DATABASE_URL 或 DB_HOST/DB_USER/DB_NAME 環境變數")
    
    print("\n" + "=" * 60)
    
    # 返回配置信息
    return {
        'database_type': config.DATABASE_TYPE,
        'database_path': config.DATABASE_PATH,
        'database_url': config.DATABASE_URL,
        'using_env_vars': env_db_type != 'Not set'
    }


if __name__ == '__main__':
    check_database_config()

