"""
檢查 TiDB 數據庫中的數據
"""
import os
import sys
from config import config
from database import get_db_connection, get_cursor, get_table_names

def check_tidb_data():
    """檢查 TiDB 數據庫中的數據"""
    print("=" * 50)
    print("檢查 TiDB 數據庫數據")
    print("=" * 50)
    
    print(f"\n資料庫類型: {config.DATABASE_TYPE}")
    print(f"資料庫主機: {getattr(config, 'DB_HOST', 'N/A')}")
    print(f"資料庫名稱: {getattr(config, 'DB_NAME', 'N/A')}")
    
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)
        
        # 獲取所有表名
        table_names = get_table_names(cursor)
        print(f"\n✅ 找到 {len(table_names)} 個表: {', '.join(table_names)}")
        
        # 檢查每個表的數據
        for table_name in table_names:
            try:
                cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
                result = cursor.fetchone()
                count = result['count'] if isinstance(result, dict) else result[0]
                print(f"  - {table_name}: {count} 條記錄")
                
                # 如果是 users 表，顯示用戶列表
                if table_name == 'users' and count > 0:
                    cursor.execute("SELECT id, username, email, role, company_name FROM users LIMIT 10")
                    users = cursor.fetchall()
                    print(f"    用戶列表:")
                    for user in users:
                        if isinstance(user, dict):
                            print(f"      - ID: {user.get('id')}, 用戶名: {user.get('username')}, 郵箱: {user.get('email')}, 角色: {user.get('role')}, 公司: {user.get('company_name', 'N/A')}")
                        else:
                            print(f"      - ID: {user[0]}, 用戶名: {user[1]}, 郵箱: {user[2]}, 角色: {user[3]}, 公司: {user[4] if len(user) > 4 else 'N/A'}")
                
                # 如果是 services 表，顯示服務列表
                if table_name == 'services' and count > 0:
                    cursor.execute("SELECT id, name, description, price FROM services LIMIT 10")
                    services = cursor.fetchall()
                    print(f"    服務列表:")
                    for service in services:
                        if isinstance(service, dict):
                            print(f"      - ID: {service.get('id')}, 名稱: {service.get('name')}, 描述: {service.get('description')}, 價格: {service.get('price')}")
                        else:
                            print(f"      - ID: {service[0]}, 名稱: {service[1]}, 描述: {service[2]}, 價格: {service[3]}")
                            
            except Exception as e:
                print(f"  - {table_name}: 查詢失敗 - {e}")
        
        conn.close()
        print("\n✅ 數據檢查完成")
        
    except Exception as e:
        print(f"\n❌ 數據檢查失敗: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == '__main__':
    check_tidb_data()

