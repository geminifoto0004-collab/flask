"""
初始化數據庫數據腳本
用於首次部署時創建初始數據（超級管理員、默認服務等）
"""
import os
import sys
from datetime import datetime
from config import config, admin_config
from database import get_db_connection, get_cursor, init_database, get_lastrowid, get_placeholder
from utils.time_utils import get_chile_time_naive
from services.user_service import hash_password

def create_super_admin(cursor, conn):
    """創建超級管理員用戶（如果不存在）"""
    print("\n" + "=" * 50)
    print("檢查超級管理員用戶")
    print("=" * 50)
    
    # 檢查是否已存在
    cursor.execute('SELECT id, username, email, role FROM users WHERE email = ?', (admin_config.SUPER_ADMIN_EMAIL,))
    user_row = cursor.fetchone()
    
    if user_row:
        # 處理不同數據庫返回格式
        if isinstance(user_row, dict):
            user_id = user_row['id']
            username = user_row['username']
            email = user_row['email']
            role = user_row['role']
        else:
            user_id = user_row[0]
            username = user_row[1]
            email = user_row[2]
            role = user_row[3]
        
        print(f"✅ 超級管理員已存在:")
        print(f"   ID: {user_id}")
        print(f"   用戶名: {username}")
        print(f"   郵箱: {email}")
        print(f"   角色: {role}")
        return user_id
    else:
        # 創建超級管理員
        print(f"⚠️  超級管理員不存在，正在創建...")
        password_hash = hash_password(admin_config.SUPER_ADMIN_PASSWORD)
        created_at = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
        
        placeholder = get_placeholder()
        cursor.execute(f'''
            INSERT INTO users (username, email, password_hash, role, created_at)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
        ''', (admin_config.SUPER_ADMIN_USERNAME, admin_config.SUPER_ADMIN_EMAIL, 
              password_hash, admin_config.SUPER_ADMIN_ROLE, created_at))
        
        user_id = get_lastrowid(cursor, conn)
        conn.commit()
        
        print(f"✅ 超級管理員創建成功:")
        print(f"   ID: {user_id}")
        print(f"   用戶名: {admin_config.SUPER_ADMIN_USERNAME}")
        print(f"   郵箱: {admin_config.SUPER_ADMIN_EMAIL}")
        print(f"   密碼: {admin_config.SUPER_ADMIN_PASSWORD}")
        print(f"   角色: {admin_config.SUPER_ADMIN_ROLE}")
        return user_id

def check_default_services(cursor):
    """檢查默認服務是否已創建"""
    print("\n" + "=" * 50)
    print("檢查默認服務")
    print("=" * 50)
    
    cursor.execute('SELECT COUNT(*) as count FROM services')
    result = cursor.fetchone()
    count = result['count'] if isinstance(result, dict) else result[0]
    
    if count > 0:
        print(f"✅ 已找到 {count} 個服務")
        cursor.execute('SELECT id, name, description, price FROM services LIMIT 5')
        services = cursor.fetchall()
        print("   服務列表:")
        for service in services:
            if isinstance(service, dict):
                print(f"     - {service.get('name')} (ID: {service.get('id')}, 價格: ${service.get('price')})")
            else:
                print(f"     - {service[1]} (ID: {service[0]}, 價格: ${service[3]})")
    else:
        print("⚠️  沒有找到服務，請檢查 init_database() 是否正確執行了 init_default_services()")

def show_database_summary(cursor):
    """顯示數據庫摘要"""
    print("\n" + "=" * 50)
    print("數據庫摘要")
    print("=" * 50)
    
    tables = ['users', 'services', 'user_services', 'user_monitor_configs']
    
    for table_name in tables:
        try:
            cursor.execute(f'SELECT COUNT(*) as count FROM {table_name}')
            result = cursor.fetchone()
            count = result['count'] if isinstance(result, dict) else result[0]
            print(f"  {table_name}: {count} 條記錄")
        except Exception as e:
            print(f"  {table_name}: 查詢失敗 - {e}")

def main():
    """主函數"""
    print("=" * 50)
    print("數據庫初始化腳本")
    print("=" * 50)
    print(f"\n資料庫類型: {config.DATABASE_TYPE}")
    
    if config.DATABASE_TYPE == 'sqlite':
        print(f"資料庫路徑: {config.DATABASE_PATH}")
    elif config.DATABASE_TYPE in ('mysql', 'tidb'):
        print(f"資料庫主機: {getattr(config, 'DB_HOST', config.MYSQL_HOST)}")
        print(f"資料庫名稱: {getattr(config, 'DB_NAME', config.MYSQL_DATABASE)}")
    elif config.DATABASE_TYPE == 'postgresql':
        print(f"資料庫 URL: {config.DATABASE_URL[:50]}..." if config.DATABASE_URL else "未設置")
    
    print(f"\n超級管理員配置:")
    print(f"  郵箱: {admin_config.SUPER_ADMIN_EMAIL}")
    print(f"  密碼: {admin_config.SUPER_ADMIN_PASSWORD}")
    print(f"  用戶名: {admin_config.SUPER_ADMIN_USERNAME}")
    
    try:
        # 1. 初始化數據庫表結構
        print("\n" + "=" * 50)
        print("步驟 1: 初始化數據庫表結構")
        print("=" * 50)
        init_database()
        print("✅ 數據庫表結構初始化完成")
        
        # 2. 創建超級管理員
        conn = get_db_connection()
        cursor = get_cursor(conn)
        
        try:
            create_super_admin(cursor, conn)
            check_default_services(cursor)
            show_database_summary(cursor)
            
            print("\n" + "=" * 50)
            print("✅ 數據庫初始化完成！")
            print("=" * 50)
            print("\n現在可以使用以下帳號登入:")
            print(f"  郵箱: {admin_config.SUPER_ADMIN_EMAIL}")
            print(f"  密碼: {admin_config.SUPER_ADMIN_PASSWORD}")
            print("\n💡 提示:")
            print("   - 可以在 config.py 或環境變數中修改超級管理員帳號和密碼")
            print("   - 首次登入後，建議在用戶設置中設置公司名稱（company_name）")
            
        finally:
            conn.close()
            
    except Exception as e:
        print(f"\n❌ 初始化失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()

