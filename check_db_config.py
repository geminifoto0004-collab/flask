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
    
    # 檢查環境變數
    env_db_type = os.environ.get('DATABASE_TYPE', 'Not set')
    env_db_path = os.environ.get('DATABASE_PATH', 'Not set')
    env_db_url = os.environ.get('DATABASE_URL', 'Not set')
    
    print("\n[1] 環境變數:")
    print(f"   DATABASE_TYPE: {env_db_type}")
    if env_db_path != 'Not set':
        print(f"   DATABASE_PATH: {env_db_path}")
    if env_db_url != 'Not set':
        print(f"   DATABASE_URL: {env_db_url[:50]}..." if len(env_db_url) > 50 else f"   DATABASE_URL: {env_db_url}")
    
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

