"""
用戶服務模組
功能：用戶註冊、登入驗證、密碼管理
"""

import hashlib
import sqlite3
from datetime import datetime

from database import get_db_connection, get_lastrowid, get_cursor, get_row_dict
from utils.validators import validate_username, validate_email, validate_password
from utils.time_utils import get_chile_time_naive


# ========== 密碼加密 ==========
def hash_password(password):
    """
    使用 SHA256 加密密碼
    參數：password - 明文密碼
    返回：str - 密碼 hash
    """
    return hashlib.sha256(password.encode()).hexdigest()


# ========== 創建用戶 ==========
def create_user(username, email, password, role='user'):
    """
    創建新用戶
    參數：
        username - 用戶名
        email - 郵箱
        password - 密碼（明文）
        role - 角色（user/admin）
    返回：(bool, str) - (是否成功, 錯誤信息/用戶ID)
    """
    # 檢查是否為保留的超級管理員郵箱
    from config import admin_config
    if email.lower() == admin_config.SUPER_ADMIN_EMAIL.lower():
        return False, f"{admin_config.SUPER_ADMIN_EMAIL} 是超級管理員保留郵箱，不能註冊"
    
    # 驗證輸入
    valid, msg = validate_username(username)
    if not valid:
        return False, msg
    
    valid, msg = validate_email(email)
    if not valid:
        return False, msg
    
    valid, msg = validate_password(password)
    if not valid:
        return False, msg
    
    # 加密密碼
    password_hash = hash_password(password)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 檢查用戶名是否已存在
        cursor.execute('SELECT id FROM users WHERE username=?', (username,))
        if cursor.fetchone():
            conn.close()
            return False, "用戶名已被使用"
        
        # 檢查郵箱是否已存在
        cursor.execute('SELECT id FROM users WHERE email=?', (email,))
        if cursor.fetchone():
            conn.close()
            return False, "郵箱已被註冊"
        
        # 插入用戶
        cursor.execute('''
            INSERT INTO users (username, email, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, email, password_hash, role, get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')))
        
        user_id = get_lastrowid(cursor, conn)
        conn.commit()
        conn.close()
        
        print(f"用戶創建成功: {username} (ID: {user_id})")
        return True, str(user_id)
        
    except sqlite3.IntegrityError as e:
        return False, f"數據庫錯誤: {str(e)}"
    except Exception as e:
        return False, f"創建用戶失敗: {str(e)}"


# ========== 驗證用戶密碼 ==========
def verify_password(email, password):
    """
    驗證用戶密碼
    參數：
        email - 郵箱
        password - 密碼（明文）
    返回：(bool, dict/str) - (是否成功, 用戶信息/錯誤信息)
    """
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)  # 使用 get_cursor 以支持自動 SQL 適配和 DictCursor
        
        # 查詢用戶
        cursor.execute('''
            SELECT id, username, email, password_hash, role, company_name 
            FROM users WHERE email=?
        ''', (email,))
        
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            print(f"[Verify Password] 用戶不存在: email={email}")
            return False, "郵箱或密碼錯誤"
        
        # 處理返回格式（可能是字典或元組）
        if isinstance(user, dict):
            user_id = user['id']
            username = user['username']
            user_email = user['email']
            stored_password_hash = user['password_hash']
            user_role = user['role']
            company_name = user.get('company_name')
        else:
            # 如果是元組，按順序解包
            user_id = user[0]
            username = user[1]
            user_email = user[2]
            stored_password_hash = user[3]
            user_role = user[4]
            company_name = user[5] if len(user) > 5 else None
        
        # 驗證密碼
        password_hash = hash_password(password)
        print(f"[Verify Password] 輸入密碼 hash: {password_hash[:16]}...")
        print(f"[Verify Password] 存儲密碼 hash: {stored_password_hash[:16] if stored_password_hash else 'None'}...")
        
        if password_hash != stored_password_hash:
            print(f"[Verify Password] 密碼不匹配: email={email}")
            return False, "郵箱或密碼錯誤"
        
        # 返回用戶信息（不包含密碼）
        user_info = {
            'id': user_id,
            'username': username,
            'email': user_email,
            'role': user_role,
            'company_name': company_name
        }
        
        print(f"[Verify Password] 驗證成功: email={email}, user_id={user_id}")
        return True, user_info
        
    except Exception as e:
        print(f"[Verify Password] 驗證失敗: {e}")
        import traceback
        traceback.print_exc()
        return False, f"驗證失敗: {str(e)}"


# ========== 通過用戶名驗證密碼 ==========
def verify_password_by_username(username, password):
    """
    通過用戶名驗證密碼
    參數：
        username - 用戶名
        password - 密碼（明文）
    返回：(bool, dict/str) - (是否成功, 用戶信息/錯誤信息)
    """
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)  # 使用 get_cursor 以支持自動 SQL 適配和 DictCursor
        
        # 查詢用戶
        cursor.execute('''
            SELECT id, username, email, password_hash, role 
            FROM users WHERE username=?
        ''', (username,))
        
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return False, "用戶名或密碼錯誤"
        
        # 處理返回格式（可能是字典或元組）
        if isinstance(user, dict):
            stored_password_hash = user['password_hash']
            user_id = user['id']
            user_username = user['username']
            user_email = user['email']
            user_role = user['role']
        else:
            # 如果是元組，按順序解包
            user_id = user[0]
            user_username = user[1]
            user_email = user[2]
            stored_password_hash = user[3]
            user_role = user[4]
        
        # 驗證密碼
        password_hash = hash_password(password)
        if password_hash != stored_password_hash:
            return False, "用戶名或密碼錯誤"
        
        # 返回用戶信息
        user_info = {
            'id': user_id,
            'username': user_username,
            'email': user_email,
            'role': user_role
        }
        
        return True, user_info
        
    except Exception as e:
        return False, f"驗證失敗: {str(e)}"


# ========== 重置密碼 ==========
def reset_password(email, new_password):
    """
    重置用戶密碼
    參數：
        email - 郵箱
        new_password - 新密碼（明文）
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
    # 驗證新密碼
    valid, msg = validate_password(new_password)
    if not valid:
        return False, msg
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 檢查用戶是否存在
        cursor.execute('SELECT id FROM users WHERE email=?', (email,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return False, "用戶不存在"
        
        # 更新密碼
        new_password_hash = hash_password(new_password)
        cursor.execute(
            'UPDATE users SET password_hash=? WHERE email=?',
            (new_password_hash, email)
        )
        
        conn.commit()
        conn.close()
        
        print(f"密碼重置成功: {email}")
        return True, ""
        
    except Exception as e:
        return False, f"密碼重置失敗: {str(e)}"


# ========== 修改密碼 ==========
def change_password(email, old_password, new_password):
    """
    修改密碼（需要驗證舊密碼）
    參數：
        email - 郵箱
        old_password - 舊密碼（明文）
        new_password - 新密碼（明文）
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
    # 驗證舊密碼
    valid, result = verify_password(email, old_password)
    if not valid:
        return False, "舊密碼不正確"
    
    # 檢查新舊密碼是否相同
    if old_password == new_password:
        return False, "新密碼不能與舊密碼相同"
    
    # 重置密碼
    return reset_password(email, new_password)


# ========== 獲取用戶信息 ==========
def get_user_by_email(email):
    """
    通過郵箱獲取用戶信息
    參數：email - 郵箱
    返回：dict/None - 用戶信息
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, username, email, role, created_at 
            FROM users WHERE email=?
        ''', (email,))
        
        user = cursor.fetchone()
        conn.close()
        
        if user:
            # 兼容字典和元组格式
            if isinstance(user, dict):
                return user
            else:
                return {
                    'id': user[0],
                    'username': user[1],
                    'email': user[2],
                    'role': user[3],
                    'created_at': user[4] if len(user) > 4 else None
                }
        return None
        
    except Exception as e:
        print(f"❌ 查詢用戶失敗: {e}")
        return None


def get_user_by_id(user_id):
    """
    通過 ID 獲取用戶信息
    參數：user_id - 用戶 ID
    返回：dict/None - 用戶信息
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, username, email, role, created_at 
            FROM users WHERE id=?
        ''', (user_id,))
        
        user = cursor.fetchone()
        conn.close()
        
        if user:
            # 兼容字典和元组格式
            if isinstance(user, dict):
                return user
            else:
                return {
                    'id': user[0],
                    'username': user[1],
                    'email': user[2],
                    'role': user[3],
                    'created_at': user[4] if len(user) > 4 else None
                }
        return None
        
    except Exception as e:
        print(f"❌ 查詢用戶失敗: {e}")
        return None


# ========== 檢查郵箱是否已註冊 ==========
def email_exists(email):
    """
    檢查郵箱是否已被註冊
    參數：email - 郵箱
    返回：bool - 是否存在
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM users WHERE email=?', (email,))
        result = cursor.fetchone()
        conn.close()
        
        return result is not None
        
    except Exception as e:
        print(f"❌ 查詢失敗: {e}")
        return False


# ========== 檢查用戶名是否已存在 ==========
def username_exists(username):
    """
    檢查用戶名是否已被使用
    參數：username - 用戶名
    返回：bool - 是否存在
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM users WHERE username=?', (username,))
        result = cursor.fetchone()
        conn.close()
        
        return result is not None
        
    except Exception as e:
        print(f"❌ 查詢失敗: {e}")
        return False


# ========== 獲取所有用戶 ==========
def get_all_users():
    """
    獲取所有用戶列表
    返回：list - 用戶列表
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, username, email, role, created_at 
            FROM users 
            ORDER BY created_at DESC
        ''')
        
        users = cursor.fetchall()
        conn.close()
        
        # 兼容字典和元组格式
        result = []
        for user in users:
            if isinstance(user, dict):
                result.append(user)
            else:
                result.append({
                    'id': user[0],
                    'username': user[1],
                    'email': user[2],
                    'role': user[3],
                    'created_at': user[4] if len(user) > 4 else None
                })
        return result
        
    except Exception as e:
        print(f"❌ 查詢用戶列表失敗: {e}")
        return []


# ========== 刪除用戶 ==========
def delete_user(user_id):
    """
    刪除用戶
    參數：user_id - 用戶 ID
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 檢查用戶是否存在
        cursor.execute('SELECT id FROM users WHERE id=?', (user_id,))
        if not cursor.fetchone():
            conn.close()
            return False, "用戶不存在"
        
        # 刪除用戶
        cursor.execute('DELETE FROM users WHERE id=?', (user_id,))
        conn.commit()
        conn.close()
        
        print(f"用戶已刪除: ID {user_id}")
        return True, ""
        
    except Exception as e:
        return False, f"刪除用戶失敗: {str(e)}"


# ========== 測試程式 ==========
if __name__ == '__main__':
    print("=" * 50)
    print("用戶服務測試")
    print("=" * 50)
    
    # 測試創建用戶
    print("\n【創建用戶測試】")
    test_users = [
        ("testuser1", "test1@example.com", "Test1234"),
        ("testuser2", "test2@example.com", "Test5678"),
    ]
    
    for username, email, password in test_users:
        success, result = create_user(username, email, password)
        if success:
            print(f"✅ 用戶創建成功: {username} (ID: {result})")
        else:
            print(f"❌ 用戶創建失敗: {username} - {result}")
    
    # 測試密碼驗證
    print("\n【密碼驗證測試】")
    success, result = verify_password("test1@example.com", "Test1234")
    if success:
        print(f"✅ 密碼驗證成功: {result['username']}")
    else:
        print(f"❌ 密碼驗證失敗: {result}")
    
    # 測試錯誤密碼
    success, result = verify_password("test1@example.com", "WrongPassword")
    if not success:
        print(f"✅ 錯誤密碼正確拒絕: {result}")
    
    # 測試重置密碼
    print("\n【重置密碼測試】")
    success, msg = reset_password("test1@example.com", "NewPass1234")
    if success:
        print(f"✅ 密碼重置成功")
        
        # 驗證新密碼
        success, result = verify_password("test1@example.com", "NewPass1234")
        if success:
            print(f"✅ 新密碼驗證成功")
    
    # 測試獲取用戶信息
    print("\n【獲取用戶信息測試】")
    user = get_user_by_email("test1@example.com")
    if user:
        print(f"✅ 用戶信息: {user['username']} ({user['email']})")
    
    # 測試檢查郵箱
    print("\n【郵箱檢查測試】")
    print(f"test1@example.com 存在: {email_exists('test1@example.com')}")
    print(f"notexist@example.com 存在: {email_exists('notexist@example.com')}")
    
    # 測試獲取所有用戶
    print("\n【所有用戶列表】")
    all_users = get_all_users()
    for user in all_users:
        print(f"  - {user['username']} ({user['email']}) - {user['role']}")
    
    print("\n" + "=" * 50)