"""
Flask 授權管理系統 - 主應用入口
功能：管理員登入、授權管理、API 查詢
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import hashlib
import sqlite3
from datetime import datetime
from functools import wraps
from utils.time_utils import get_chile_time_naive

# 導入配置和資料庫
from config import config, admin_config, license_config, feature_flags
from database import get_db_connection, init_database, get_lastrowid, get_cursor, get_row_dict, get_row_dict

# 導入 Blueprint
from blueprints.user_auth_bp import user_auth_bp
from blueprints.api_auth_bp import api_auth_bp
from blueprints.monitor_bp import monitor_bp
from blueprints.container_bp import container_bp
from blueprints.b2_test_bp import b2_test_bp
from services.config_service import config_service
from services import container_iti_service

# 導入郵件代理 Blueprint（PythonAnywhere 端使用，可選）
# 如果要在 PythonAnywhere 上使用代理功能，取消下面的註釋
from services.email_proxy import email_proxy_bp


# ========== Flask 應用初始化 ==========
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = config.PERMANENT_SESSION_LIFETIME

# 註冊 Blueprint
app.register_blueprint(user_auth_bp)
app.register_blueprint(api_auth_bp)
app.register_blueprint(monitor_bp)
app.register_blueprint(container_bp)
app.register_blueprint(b2_test_bp)

# 註冊郵件代理 Blueprint（PythonAnywhere 端使用，可選）
# 如果要在 PythonAnywhere 上使用代理功能，取消下面的註釋
app.register_blueprint(email_proxy_bp)

# ========== 自動初始化資料庫 ==========
# 在應用啟動時自動初始化資料庫（適用於 Render 等生產環境）
# 使用 before_request 但只執行一次
_database_initialized = False

@app.before_request
def initialize_database():
    """在首次請求前初始化資料庫"""
    global _database_initialized
    if not _database_initialized:
        try:
            init_database()
            print("✅ 資料庫自動初始化完成")
            _database_initialized = True
        except Exception as e:
            import traceback
            print(f"⚠️  資料庫初始化失敗: {e}")
            print(f"   詳細錯誤: {traceback.format_exc()}")
            # 不阻止應用啟動，讓用戶可以訪問錯誤頁面
            _database_initialized = True  # 標記為已嘗試，避免重複嘗試


# ========== 登入驗證裝飾器 ==========
def login_required(f):
    """登入驗證裝飾器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function






@app.route('/api/debug/metrics', methods=['GET'])
def debug_metrics():
    import json
    import os
    import sys
    import time as _time

    metrics = {}

    # 1) container_iti_cache.payload size
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)
        cursor.execute("SELECT payload FROM container_iti_cache WHERE id = 1")
        row = cursor.fetchone()
        data = get_row_dict(row, cursor) if row else {}
        conn.close()
        payload = data.get('payload') if isinstance(data, dict) else None
        if payload:
            if not isinstance(payload, str):
                payload = json.dumps(payload, ensure_ascii=False)
            payload_bytes = payload.encode('utf-8')
            metrics['payload_size_bytes'] = len(payload_bytes)
            metrics['payload_size_mb'] = round(len(payload_bytes) / 1024 / 1024, 2)
            try:
                parsed = json.loads(payload)
                metrics['payload_keys'] = len(parsed) if isinstance(parsed, dict) else 'N/A'
            except Exception:
                metrics['payload_keys'] = 'N/A'
        else:
            metrics['payload_size_bytes'] = 0
            metrics['payload_size_mb'] = 0
    except Exception as e:
        metrics['payload_error'] = str(e)

    # 2) container_items count
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)
        cursor.execute("SELECT COUNT(*) AS cnt FROM container_items")
        row = cursor.fetchone()
        data = get_row_dict(row, cursor) if row else {}
        conn.close()
        count = 0
        if isinstance(data, dict) and data:
            count = list(data.values())[0]
        elif isinstance(row, (list, tuple)) and row:
            count = row[0]
        elif isinstance(row, int):
            count = row
        metrics['container_items_count'] = count
    except Exception as e:
        metrics['items_error'] = str(e)

    # 3) DB ping latency
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)
        start = _time.time()
        cursor.execute("SELECT 1")
        _ = cursor.fetchone()
        conn.close()
        metrics['db_ping_ms'] = round((_time.time() - start) * 1000, 2)
    except Exception as e:
        metrics['db_error'] = str(e)

    # 4) Render environment info
    try:
        metrics['render_instance_id'] = os.environ.get('RENDER_INSTANCE_ID', 'local')
        metrics['render_service_name'] = os.environ.get('RENDER_SERVICE_NAME', 'local')
        metrics['is_render'] = 'RENDER' in os.environ.get('RENDER_SERVICE_NAME', '')
    except Exception:
        metrics['render_info'] = 'unable to detect'

    # 5) memory cache state
    try:
        cache = getattr(container_iti_service, '_cache', None)
        metrics['memory_cache_exists'] = isinstance(cache, dict)
        if isinstance(cache, dict) and cache:
            metrics['memory_cache_size'] = sys.getsizeof(cache)
            idx = cache.get('index')
            if isinstance(idx, dict):
                metrics['memory_cache_index_size'] = len(idx)
        else:
            metrics['memory_cache_size'] = 0
    except Exception as e:
        metrics['cache_error'] = str(e)

    return jsonify(metrics)

# ========== API 端點：授權檢查 ==========
@app.route('/api/check-license', methods=['POST'])
def api_check_license():
    """API端點：檢查用戶授權狀態"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'success': False, 'error': '請提供郵箱和密碼'})
        
        # 驗證用戶登入
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 優先檢查超級管理員帳號
        if email == admin_config.SUPER_ADMIN_EMAIL:
            if password == admin_config.SUPER_ADMIN_PASSWORD:
                conn.close()
                return jsonify({
                    'success': True, 
                    'message': '超級管理員授權驗證成功',
                    'user_type': admin_config.SUPER_ADMIN_ROLE,
                    'services': [{'name': '超級管理員權限', 'status': 'active', 'end_date': '2099-12-31'}]
                })
            else:
                conn.close()
                return jsonify({'success': False, 'error': '超級管理員密碼錯誤'})
        
        # 檢查普通用戶
        cursor.execute('SELECT id, password_hash, role FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return jsonify({'success': False, 'error': '用戶不存在'})
        
        # 處理返回格式（可能是字典或元組）
        if isinstance(user, dict):
            user_id = user['id']
            stored_password_hash = user['password_hash']
            user_role = user['role']
        else:
            user_id = user[0]
            stored_password_hash = user[1]
            user_role = user[2]
        
        # 驗證密碼
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if stored_password_hash != password_hash:
            conn.close()
            return jsonify({'success': False, 'error': '密碼錯誤'})
        
        # 獲取用戶服務
        cursor.execute('''
            SELECT us.*, s.name as service_name, s.description
            FROM user_services us
            JOIN services s ON us.service_id = s.id
            WHERE us.user_id = ? AND us.status = 'active'
        ''', (user_id,))
        services = cursor.fetchall()
        
        # 檢查服務是否過期
        valid_services = []
        current_date = get_chile_time_naive().date()
        
        for service in services:
            # 處理返回格式（可能是字典或元組）
            if isinstance(service, dict):
                end_date_str = service.get('end_date') or service.get('end_date')
                start_date_str = service.get('start_date') or service.get('start_date')
                service_name = service.get('service_name') or service.get('name')
                description = service.get('description')
            else:
                end_date_str = service[4] if len(service) > 4 else None
                start_date_str = service[3] if len(service) > 3 else None
                service_name = service[6] if len(service) > 6 else None
                description = service[7] if len(service) > 7 else None
            
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                if end_date >= current_date:
                    valid_services.append({
                        'name': service_name,
                        'description': description,
                        'status': 'active',
                        'end_date': end_date_str,
                        'start_date': start_date_str
                    })
        
        conn.close()
        
        if valid_services:
            return jsonify({
                'success': True,
                'message': '授權驗證成功',
                'user_type': 'user',
                'services': valid_services
            })
        else:
            return jsonify({
                'success': False, 
                'error': '沒有有效的服務授權或服務已過期'
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': f'系統錯誤: {str(e)}'})

# ========== 路由：統一登入/登出 ==========
@app.route('/login', methods=['GET', 'POST'])
def login():
    """統一登入入口"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        if not email or not password:
            return render_template('user/login.html', error='請填寫完整信息')
        
        # 優先檢查超級管理員帳號
        from config import admin_config
        print(f"登入嘗試: 郵箱='{email}', 密碼='{password}'")
        print(f"Super Admin配置: 郵箱='{admin_config.SUPER_ADMIN_EMAIL}', 密碼='{admin_config.SUPER_ADMIN_PASSWORD}'")
        
        if email == admin_config.SUPER_ADMIN_EMAIL and password == admin_config.SUPER_ADMIN_PASSWORD:
            print("Super Admin登入成功！")
            session['logged_in'] = True
            # 從數據庫獲取超級管理員的實際 user_id，如果不存在則創建
            conn = None
            try:
                conn = get_db_connection()
                cursor = get_cursor(conn)  # 使用 get_cursor 以支持不同數據庫類型
                cursor.execute('SELECT id, company_name FROM users WHERE email = ?', (admin_config.SUPER_ADMIN_EMAIL,))
                user_row = cursor.fetchone()
                
                if user_row:
                    # 如果數據庫中已有，使用數據庫的ID和公司名稱
                    # 處理不同數據庫返回格式：SQLite 返回元組，MySQL/TiDB 返回字典
                    if isinstance(user_row, dict):
                        session['user_id'] = user_row['id']
                        session['company_name'] = user_row.get('company_name')
                    else:
                        # 處理返回格式（可能是字典或元組）
                        if isinstance(user_row, dict):
                            session['user_id'] = user_row['id']
                            session['company_name'] = user_row.get('company_name')
                        else:
                            session['user_id'] = user_row[0]
                            session['company_name'] = user_row[1] if len(user_row) > 1 and user_row[1] else None
                else:
                    # 如果數據庫中沒有，自動創建超級管理員用戶
                    print("⚠️ 數據庫中沒有超級管理員，正在創建...")
                    from services.user_service import hash_password
                    password_hash = hash_password(admin_config.SUPER_ADMIN_PASSWORD)
                    cursor.execute('''
                        INSERT INTO users (username, email, password_hash, role, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (admin_config.SUPER_ADMIN_USERNAME, admin_config.SUPER_ADMIN_EMAIL, 
                          password_hash, admin_config.SUPER_ADMIN_ROLE, get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')))
                    session['user_id'] = get_lastrowid(cursor, conn)
                    conn.commit()
                    print(f"✅ 超級管理員創建成功，user_id={session['user_id']}")
                    session['company_name'] = None  # 新創建的用戶沒有公司名稱
                
                if conn:
                    conn.close()
            except Exception as e:
                import traceback
                print(f"❌ 數據庫操作失敗: {e}")
                print(f"   詳細錯誤: {traceback.format_exc()}")
                # 如果數據庫操作失敗，仍然允許登入（使用默認值）
                if 'user_id' not in session:
                    session['user_id'] = None  # 臨時設置，後續可能需要處理
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                # 繼續執行，不阻止登入
            session['username'] = admin_config.SUPER_ADMIN_USERNAME
            session['email'] = admin_config.SUPER_ADMIN_EMAIL
            session['role'] = admin_config.SUPER_ADMIN_ROLE
            
            # 創建會話記錄（用於會話監控）
            try:
                from blueprints.api_auth_bp import create_session, generate_session_token, get_device_info
                session_token = generate_session_token()
                device_info = get_device_info(request)
                success = create_session(session['user_id'], session_token, device_info, service_name="Web_Login")
                if success:
                    print(f"✅ 創建超級管理員網頁登入會話記錄成功 - 用戶 {session['user_id']}, service_name=Web_Login")
                else:
                    print(f"❌ 創建超級管理員網頁登入會話記錄失敗 - 用戶 {session['user_id']}, create_session返回False")
            except ImportError as e:
                print(f"❌ 導入會話管理函數失敗: {e}")
            except Exception as e:
                import traceback
                print(f"❌ 創建會話記錄失敗（不影響登入）: {e}")
                print(f"   詳細錯誤: {traceback.format_exc()}")
            
            return redirect(url_for('admin_dashboard'))
        else:
            print("Super Admin登入失敗，嘗試普通用戶驗證")
        
        # 使用用戶服務驗證普通用戶
        from services.user_service import verify_password
        success, result = verify_password(email, password)
        
        if success:
            session['logged_in'] = True
            session['user_id'] = result['id']
            session['username'] = result['username']
            session['email'] = result['email']
            session['role'] = result['role']
            
            # 創建會話記錄（用於會話監控）
            try:
                from blueprints.api_auth_bp import create_session, generate_session_token, get_device_info
                session_token = generate_session_token()
                device_info = get_device_info(request)
                success = create_session(result['id'], session_token, device_info, service_name="Web_Login")
                if success:
                    print(f"✅ 創建網頁登入會話記錄成功 - 用戶 {result['id']}, service_name=Web_Login")
                else:
                    print(f"❌ 創建網頁登入會話記錄失敗 - 用戶 {result['id']}, create_session返回False")
            except ImportError as e:
                print(f"❌ 導入會話管理函數失敗: {e}")
            except Exception as e:
                import traceback
                print(f"❌ 創建會話記錄失敗（不影響登入）: {e}")
                print(f"   詳細錯誤: {traceback.format_exc()}")
            
            # 根據角色重定向到不同頁面
            if result['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_auth.user_portal'))
        else:
            return render_template('user/login.html', error='Correo electrónico o contraseña incorrectos')
    
    return render_template('user/login.html')


@app.route('/logout')
def logout():
    """登出"""
    session.clear()
    return redirect(url_for('login'))


# ========== 路由：管理員儀表板 ==========
@app.route('/admin')
@login_required
def admin_dashboard():
    """管理員儀表板"""
    if session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    try:
        from database import get_db_connection, get_cursor
        conn = get_db_connection()
        
        # 獲取用戶統計（使用 get_cursor 以支持不同數據庫類型）
        cursor = get_cursor(conn)
        cursor.execute('SELECT COUNT(*) as total FROM users')
        result = cursor.fetchone()
        # 處理不同數據庫返回格式
        db_total_users = result['total'] if isinstance(result, dict) else result[0]
        
        cursor.execute('SELECT COUNT(*) as total FROM users WHERE role = ?', ('admin',))
        result = cursor.fetchone()
        db_admin_users = result['total'] if isinstance(result, dict) else result[0]
        
        cursor.execute('SELECT COUNT(*) as total FROM users WHERE role = ?', ('user',))
        result = cursor.fetchone()
        db_regular_users = result['total'] if isinstance(result, dict) else result[0]
        
        # 包含超級管理員的統計
        total_users = db_total_users + 1  # +1 for super admin
        admin_users = db_admin_users + 1  # +1 for super admin
        regular_users = db_regular_users
        
        conn.close()
        
        return render_template('admin/dashboard.html', 
                             total_users=total_users,
                             admin_users=admin_users,
                             regular_users=regular_users)
    except Exception as e:
        import traceback
        print(f"❌ 管理員儀表板錯誤: {e}")
        print(f"   詳細錯誤: {traceback.format_exc()}")
        # 返回錯誤頁面或重定向到登入
        return render_template('admin/dashboard.html', 
                             total_users=0,
                             admin_users=0,
                             regular_users=0,
                             error=f"資料庫錯誤: {str(e)}")

@app.route('/admin/dashboard')
@login_required
def admin_dashboard_redirect():
    """重定向到admin主頁"""
    return redirect(url_for('admin_dashboard'))


# ========== 舊的授權系統已移除，改用 services 和 user_services 系統 ==========


# ========== API：授權查詢（桌面程式用）==========
@app.route('/licenses/check_license', methods=['GET'])
def check_license():
    """
    授權查詢 API
    參數: rut (例: 76315010-0)
    返回: JSON {rut, empresa, estado, fecha_expiracion}
    """
    rut = request.args.get('rut')
    
    if not rut:
        return jsonify({'error': '缺少 RUT 參數'}), 400
    
    try:
        conn = get_db_connection()
        license = conn.execute(
            'SELECT rut, empresa, status, expire_date FROM licenses WHERE rut=?',
            (rut,)
        ).fetchone()
        conn.close()
        
        if license:
            # 檢查是否過期
            if license['expire_date']:
                expire_date = datetime.strptime(license['expire_date'], '%Y-%m-%d')
                is_expired = expire_date < get_chile_time_naive()
                status = license_config.STATUS_EXPIRED if is_expired else license['status']
            else:
                status = license['status']
            
            return jsonify({
                'rut': license['rut'],
                'empresa': license['empresa'],
                'estado': status,
                'fecha_expiracion': license['expire_date']
            })
        else:
            return jsonify({'error': '授權不存在'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ========== 用戶管理 ==========
@app.route('/admin/users')
def admin_users():
    """管理員查看所有用戶"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, role, created_at FROM users ORDER BY created_at DESC')
    users_rows = cursor.fetchall()
    # 將Row對象轉換為字典列表
    users = [dict(row) for row in users_rows]
    
    # 添加超級管理員到列表頂部（從配置文件獲取，不從資料庫）
    super_admin = {
        'id': admin_config.SUPER_ADMIN_USERNAME,
        'username': admin_config.SUPER_ADMIN_USERNAME,
        'email': admin_config.SUPER_ADMIN_EMAIL,
        'role': admin_config.SUPER_ADMIN_ROLE,
        'created_at': '系統創建'
    }
    users.insert(0, super_admin)
    
    conn.close()
    
    return render_template('admin/users.html', users=users, super_admin_role=admin_config.SUPER_ADMIN_ROLE)


@app.route('/admin/monitor-tasks')
def admin_monitor_tasks():
    """Admin page: manage all monitor tasks in one place."""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    return render_template('admin/monitor_tasks.html')

@app.route('/admin/users/<int:user_id>/role', methods=['POST'])
def update_user_role(user_id):
    """更新用戶角色"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'error': '權限不足'}), 403
    new_role = request.form.get('role')
    
    if not user_id or not new_role:
        return jsonify({'error': '參數不完整'}), 400
    
    if new_role not in ['user', 'admin']:
        return jsonify({'error': '無效的角色'}), 400
    
    # 檢查是否為超級管理員（超級管理員不能被修改）
    if str(user_id) == admin_config.SUPER_ADMIN_USERNAME:
        return jsonify({'error': '超級管理員的角色無法修改'}), 400
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 檢查用戶是否存在
    cursor.execute('SELECT id, role FROM users WHERE id=?', (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return jsonify({'error': '用戶不存在'}), 404
    
    # 檢查權限：只有超級管理員可以降級管理員
    current_user_role = session.get('role')
    
    # 如果是要將管理員降級為普通用戶
    if user['role'] == 'admin' and new_role == 'user':
        # 只有超級管理員可以降級管理員
        if current_user_role != admin_config.SUPER_ADMIN_ROLE:
            conn.close()
            return jsonify({
                'error': '權限不足：只有超級管理員可以將管理員降級為普通用戶'
            }), 403
        
        # 超級管理員可以隨意降級管理員，因為超級管理員永遠存在
    
    # 更新角色
    cursor.execute('UPDATE users SET role=? WHERE id=?', (new_role, user_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': '角色更新成功'})

@app.route('/admin/services')
def admin_services():
    """服務管理頁面"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM services ORDER BY created_at DESC')
    services_rows = cursor.fetchall()
    # 將Row對象轉換為字典列表
    services = [dict(row) for row in services_rows]
    conn.close()
    
    return render_template('admin/services.html', services=services)

@app.route('/admin/services', methods=['POST'])
def create_service():
    """創建新服務"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    name = request.form.get('name')
    description = request.form.get('description', '')
    price = request.form.get('price')
    duration_days = request.form.get('duration_days')
    status = request.form.get('status', 'active')
    
    if not all([name, price, duration_days]):
        return jsonify({'success': False, 'error': '請填寫所有必填欄位'})
    
    try:
        price = float(price)
        duration_days = int(duration_days)
    except ValueError:
        return jsonify({'success': False, 'error': '價格和有效期必須為數字'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 獲取配置 JSON（如果有的話）
        config_json = request.form.get('config_json', '')
        
        cursor.execute('''
            INSERT INTO services (name, description, price, duration_days, status, config_json)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, description, price, duration_days, status, config_json))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '服務創建成功'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'創建失敗: {str(e)}'})

@app.route('/admin/services/<int:service_id>', methods=['GET'])
def get_service(service_id):
    """獲取單個服務信息"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM services WHERE id = ?', (service_id,))
    service = cursor.fetchone()
    conn.close()
    
    if service:
        return jsonify({'success': True, 'service': dict(service)})
    else:
        return jsonify({'success': False, 'error': '服務不存在'})

@app.route('/admin/services/<int:service_id>', methods=['PUT'])
def update_service(service_id):
    """更新服務"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    name = request.form.get('name')
    description = request.form.get('description', '')
    price = request.form.get('price')
    duration_days = request.form.get('duration_days')
    status = request.form.get('status', 'active')
    
    if not all([name, price, duration_days]):
        return jsonify({'success': False, 'error': '請填寫所有必填欄位'})
    
    try:
        price = float(price)
        duration_days = int(duration_days)
    except ValueError:
        return jsonify({'success': False, 'error': '價格和有效期必須為數字'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 檢查服務是否存在
        cursor.execute('SELECT id FROM services WHERE id = ?', (service_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': '服務不存在'})
        
        cursor.execute('''
            UPDATE services 
            SET name = ?, description = ?, price = ?, duration_days = ?, status = ?
            WHERE id = ?
        ''', (name, description, price, duration_days, status, service_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '服務更新成功'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'更新失敗: {str(e)}'})

@app.route('/admin/services/<int:service_id>', methods=['DELETE'])
def delete_service(service_id):
    """刪除服務"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 檢查服務是否存在
        cursor.execute('SELECT name FROM services WHERE id = ?', (service_id,))
        service = cursor.fetchone()
        
        if not service:
            return jsonify({'success': False, 'error': '服務不存在'})
        
        # 檢查是否有用戶正在使用此服務
        cursor.execute('SELECT COUNT(*) FROM user_services WHERE service_id = ?', (service_id,))
        user_count_result = cursor.fetchone()
        user_count = user_count_result[0] if isinstance(user_count_result, tuple) else (user_count_result.get('COUNT(*)') or user_count_result.get(list(user_count_result.keys())[0]) if user_count_result else 0)
        
        if user_count > 0:
            return jsonify({'success': False, 'error': f'無法刪除：有 {user_count} 個用戶正在使用此服務'})
        
        # 刪除服務
        cursor.execute('DELETE FROM services WHERE id = ?', (service_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'服務 {service["name"]} 已刪除'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'刪除失敗: {str(e)}'})

@app.route('/admin/user-services')
def admin_user_services():
    """用戶服務管理頁面"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT us.*, u.username, u.email, s.name as service_name, s.description
        FROM user_services us
        JOIN users u ON us.user_id = u.id
        JOIN services s ON us.service_id = s.id
        ORDER BY us.created_at DESC
    ''')
    user_services_rows = cursor.fetchall()
    # 將Row對象轉換為字典列表
    user_services = [dict(row) for row in user_services_rows]
    conn.close()
    
    return render_template('admin/user_services.html', user_services=user_services)

@app.route('/admin/user-services/by-email/<email>')
def get_user_services_by_email(email):
    """根據email查詢用戶服務（API）"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT us.*, u.username, u.email, s.name as service_name, s.description
        FROM user_services us
        JOIN users u ON us.user_id = u.id
        JOIN services s ON us.service_id = s.id
        WHERE u.email = ?
        ORDER BY us.created_at DESC
    ''', (email,))
    
    user_services_rows = cursor.fetchall()
    user_services = [dict(row) for row in user_services_rows]
    conn.close()
    
    return jsonify({'success': True, 'user_services': user_services})

@app.route('/admin/users/<int:user_id>/password')
def get_user_password(user_id):
    """獲取用戶密碼信息"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 獲取用戶信息
    cursor.execute('SELECT username, password_hash FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return jsonify({
            'success': True,
            'username': user['username'],
            'password': '密碼已加密存儲',
            'password_hash': user['password_hash'][:16] + '...',  # 顯示部分hash
            'note': '系統使用SHA256加密存儲密碼，無法查看明文'
        })
    else:
        return jsonify({'success': False, 'error': '用戶不存在'})

@app.route('/admin/users/<int:user_id>/services')
def get_user_services(user_id):
    """獲取用戶的服務列表"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT us.*, s.name as service_name, s.description
        FROM user_services us
        JOIN services s ON us.service_id = s.id
        WHERE us.user_id = ?
        ORDER BY us.created_at DESC
    ''', (user_id,))
    
    services_rows = cursor.fetchall()
    services = [dict(row) for row in services_rows]
    conn.close()
    
    return jsonify({'success': True, 'services': services})

@app.route('/admin/user-services/assign', methods=['POST'])
def assign_user_service():
    """為用戶分配服務"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    user_id = request.form.get('user_id')
    service_id = request.form.get('service_id')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    auto_calculate = request.form.get('auto_calculate', 'true') == 'true'
    
    if not all([user_id, service_id, start_date]):
        return jsonify({'success': False, 'error': '請填寫用戶、服務和開始日期'})
    
    from database import get_db_connection
    from datetime import datetime, timedelta
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 檢查用戶和服務是否存在
        cursor.execute('SELECT id FROM users WHERE id = ?', (user_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': '用戶不存在'})
        
        cursor.execute('SELECT id, duration_days FROM services WHERE id = ?', (service_id,))
        service = cursor.fetchone()
        if not service:
            return jsonify({'success': False, 'error': '服務不存在'})
        
        # 處理結束日期
        if auto_calculate and not end_date:
            # 自動計算結束日期
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = start_dt + timedelta(days=service['duration_days'])
            end_date = end_dt.strftime('%Y-%m-%d')
        elif not end_date:
            return jsonify({'success': False, 'error': '請填寫結束日期或選擇自動計算'})
        
        # 驗證日期合理性
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        if end_dt <= start_dt:
            return jsonify({'success': False, 'error': '結束日期必須晚於開始日期'})
        
        # 檢查是否超過服務標準期限
        actual_days = (end_dt - start_dt).days
        if actual_days > service['duration_days']:
            return jsonify({
                'success': False, 
                'error': f'服務期限不能超過標準期限 {service["duration_days"]} 天'
            })
        
        # 插入用戶服務記錄
        cursor.execute('''
            INSERT INTO user_services (user_id, service_id, start_date, end_date, status)
            VALUES (?, ?, ?, ?, 'active')
        ''', (user_id, service_id, start_date, end_date))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'服務分配成功！有效期：{start_date} 至 {end_date}（{actual_days}天）'
        })
        
    except ValueError as e:
        conn.close()
        return jsonify({'success': False, 'error': 'Formato de fecha incorrecto, use el formato YYYY-MM-DD'})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'分配失敗: {str(e)}'})

@app.route('/admin/user-services/<int:user_service_id>', methods=['DELETE'])
def delete_user_service(user_service_id):
    """刪除用戶服務"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 檢查用戶服務是否存在
        cursor.execute('''
            SELECT us.*, u.username, s.name as service_name
            FROM user_services us
            JOIN users u ON us.user_id = u.id
            JOIN services s ON us.service_id = s.id
            WHERE us.id = ?
        ''', (user_service_id,))
        
        user_service = cursor.fetchone()
        
        if not user_service:
            return jsonify({'success': False, 'error': 'El servicio de usuario no existe'})
        
        # 刪除用戶服務記錄
        cursor.execute('DELETE FROM user_services WHERE id = ?', (user_service_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'用戶 {user_service["username"]} 的服務 {user_service["service_name"]} 已刪除'
        })
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'刪除失敗: {str(e)}'})

@app.route('/admin/user-services/<int:user_service_id>', methods=['GET'])
def get_user_service(user_service_id):
    """獲取單個用戶服務信息"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT us.*, u.username, s.name as service_name
        FROM user_services us
        JOIN users u ON us.user_id = u.id
        JOIN services s ON us.service_id = s.id
        WHERE us.id = ?
    ''', (user_service_id,))
    
    user_service = cursor.fetchone()
    
    if user_service:
        # 轉換為字典
        user_service_dict = dict(user_service)
        
        # 如果有配置，嘗試找到對應的參數配置名稱
        if user_service_dict.get('config_json'):
            cursor.execute('''
                SELECT param_name FROM service_versions 
                WHERE service_name = ? AND param_content = ?
            ''', (user_service_dict['service_name'], user_service_dict['config_json']))
            
            param_result = cursor.fetchone()
            if param_result:
                # 處理返回格式（可能是字典或元組）
                if isinstance(param_result, dict):
                    user_service_dict['param_config'] = param_result.get('param_content') or param_result.get(list(param_result.keys())[0])
                else:
                    user_service_dict['param_config'] = param_result[0]
            else:
                user_service_dict['param_config'] = None
        else:
            user_service_dict['param_config'] = None
        
        conn.close()
        return jsonify({'success': True, 'user_service': user_service_dict})
    else:
        conn.close()
        return jsonify({'success': False, 'error': 'El servicio de usuario no existe'})

@app.route('/admin/user-services/<int:user_service_id>', methods=['PUT'])
def update_user_service(user_service_id):
    """更新用戶服務"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    # 支持 JSON 和 form 數據
    if request.is_json:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        status = data.get('status', 'active')
        param_config = data.get('param_config')
    else:
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        status = request.form.get('status', 'active')
        param_config = None
    
    if not all([start_date, end_date]):
        return jsonify({'success': False, 'error': '請填寫開始日期和結束日期'})
    
    from database import get_db_connection
    from datetime import datetime
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 檢查用戶服務是否存在
        cursor.execute('SELECT id FROM user_services WHERE id = ?', (user_service_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': '用戶服務不存在'})
        
        # 驗證日期格式和合理性
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        if end_dt <= start_dt:
            return jsonify({'success': False, 'error': '結束日期必須晚於開始日期'})
        
        # 如果指定了參數配置，獲取配置內容
        config_json = None
        if param_config:
            cursor.execute('SELECT param_content FROM service_versions WHERE service_name = "Zofri_Compra_Venta" AND param_name = ?', (param_config,))
            config_result = cursor.fetchone()
            if config_result:
                # 處理返回格式（可能是字典或元組）
                if isinstance(config_result, dict):
                    config_json = config_result.get('param_content') or config_result.get(list(config_result.keys())[0])
                else:
                    config_json = config_result[0]  # 這裡保存的是原始參數代碼
        
        # 更新用戶服務
        if config_json:
            cursor.execute('''
                UPDATE user_services 
                SET start_date = ?, end_date = ?, status = ?, config_json = ?
                WHERE id = ?
            ''', (start_date, end_date, status, config_json, user_service_id))
        else:
            cursor.execute('''
                UPDATE user_services 
                SET start_date = ?, end_date = ?, status = ?
                WHERE id = ?
            ''', (start_date, end_date, status, user_service_id))
        
        conn.commit()
        conn.close()
        
        actual_days = (end_dt - start_dt).days
        return jsonify({
            'success': True, 
            'message': f'用戶服務更新成功！有效期: {start_date} 至 {end_date} ({actual_days} 天)'
        })
        
    except ValueError as e:
        conn.close()
        return jsonify({'success': False, 'error': '日期格式不正確，請使用 YYYY-MM-DD 格式'})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'更新失敗: {str(e)}'})

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """刪除用戶"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    # 檢查是否為超級管理員（超級管理員不能被刪除）
    if str(user_id) == admin_config.SUPER_ADMIN_USERNAME:
        return jsonify({'success': False, 'error': '超級管理員無法被刪除'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 檢查用戶是否存在
        cursor.execute('SELECT username, role FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'error': '用戶不存在'})
        
        # 如果要刪除的是管理員，檢查是否會導致沒有管理員
        if user['role'] == 'admin':
            # 檢查當前管理員總數（不包括超級管理員）
            cursor.execute('SELECT COUNT(*) as admin_count FROM users WHERE role="admin"')
            admin_count = cursor.fetchone()['admin_count']
            
            # 如果只有一個管理員，不允許刪除（超級管理員永遠存在）
            if admin_count <= 1:
                conn.close()
                return jsonify({
                    'success': False, 
                    'error': '無法刪除：系統必須至少保留一個普通管理員。超級管理員永遠存在，但建議保留至少一個普通管理員。'
                })
        
        # 刪除用戶的所有相關數據
        cursor.execute('DELETE FROM user_services WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM verification_codes WHERE email = (SELECT email FROM users WHERE id = ?)', (user_id,))
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'用戶 {user["username"]} 已刪除'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'刪除失敗: {str(e)}'})

@app.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
def reset_user_password(user_id):
    """重置用戶密碼"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    new_password = request.form.get('new_password')
    if not new_password:
        return jsonify({'success': False, 'error': '請輸入新密碼'})
    
    from utils.validators import validate_password
    valid, msg = validate_password(new_password)
    if not valid:
        return jsonify({'success': False, 'error': msg})
    
    from database import get_db_connection
    from services.user_service import hash_password
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 檢查用戶是否存在
        cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'error': '用戶不存在'})
        
        # 更新密碼
        password_hash = hash_password(new_password)
        cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, user_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'用戶 {user["username"]} 的密碼已重置',
            'new_password': new_password  # 返回新密碼供管理員告知用戶
        })
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'重置失敗: {str(e)}'})

@app.route('/admin/database')
def admin_database():
    """管理員資料庫瀏覽"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    try:
        from database import get_db_connection, get_cursor, get_table_names
        conn = get_db_connection()
        cursor = get_cursor(conn)  # 使用 get_cursor 以支持不同數據庫類型
        
        # 獲取所有表名（使用統一的函數）
        table_names = get_table_names(cursor)
        tables = [{'name': name} for name in table_names]
        
        # 獲取每個表的數據
        table_data = {}
        for table_name in table_names:
            try:
                cursor.execute(f"SELECT * FROM {table_name}")
                rows = cursor.fetchall()
                # 處理不同數據庫返回格式
                if rows and isinstance(rows[0], dict):
                    table_data[table_name] = rows
                else:
                    # SQLite 返回 Row 對象，需要轉換
                    table_data[table_name] = [dict(row) for row in rows]
            except Exception as e:
                print(f"獲取表 {table_name} 數據失敗: {e}")
                table_data[table_name] = []
        
        conn.close()
        
        return render_template('admin/database.html', tables=tables, table_data=table_data)
        
    except Exception as e:
        import traceback
        print(f"資料庫瀏覽錯誤: {e}")
        print(f"   詳細錯誤: {traceback.format_exc()}")
        return render_template('admin/database.html', tables=[], table_data={}, error=str(e))


# 舊的授權刪除API已移除，改用新的服務系統


# ========== 首頁重定向 ==========
@app.route('/')
def index():
    """首頁重定向到管理員登入"""
    if session.get('logged_in'):
        if session.get('role') in ['admin', admin_config.SUPER_ADMIN_ROLE]:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('user_auth.user_portal'))
    return redirect(url_for('login'))


# ========== 用戶服務相關路由 ==========
@app.route('/user/services')
def user_services():
    """用戶服務頁面"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    return render_template('user/services.html')

@app.route('/user/services/api')
def user_services_api():
    """獲取當前用戶的服務列表（API）"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': '請先登入'})
    
    try:
        from database import get_db_connection
        from datetime import datetime
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 根據用戶ID查詢服務
        cursor.execute('''
            SELECT us.*, s.name as service_name, s.description
            FROM user_services us
            JOIN services s ON us.service_id = s.id
            WHERE us.user_id = ?
            ORDER BY us.created_at DESC
        ''', (session.get('user_id'),))
        
        services_rows = cursor.fetchall()
        services = []
        current_date = get_chile_time_naive().strftime('%Y-%m-%d')
        
        for row in services_rows:
            service = dict(row)
            # 檢查服務是否真的激活（status 為 active 且 end_date 未過期）
            if service.get('status') == 'active' and service.get('end_date'):
                # 比較日期字符串（格式：YYYY-MM-DD）
                if service['end_date'] < current_date:
                    # 如果過期了，將狀態改為 inactive
                    service['status'] = 'inactive'
                    service['is_expired'] = True
            services.append(service)
        
        conn.close()
        
        return jsonify({'success': True, 'services': services})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error al cargar servicios: {str(e)}'})


@app.route('/admin/user-services/<int:user_service_id>/config', methods=['GET'])
def get_user_service_config(user_service_id):
    """獲取用戶服務配置"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取用戶服務配置
        cursor.execute("""
            SELECT us.config_json 
            FROM user_services us
            WHERE us.id = ?
        """, (user_service_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        # 處理返回格式（可能是字典或元組）
        config_str = None
        if result:
            if isinstance(result, dict):
                config_str = result.get('config_json') or result.get(list(result.keys())[0])
            else:
                config_str = result[0] if len(result) > 0 else None
        
        if config_str:
            import json
            config = json.loads(config_str)
            return jsonify({'success': True, 'config': config})
        else:
            # 返回默認配置
            default_config = {
                'max_concurrent_downloads': 5,
                'max_concurrent_procesar_venta': 5,
                'max_concurrent_procesar_compra': 3,
                'max_concurrent_venta': 5,
                'max_concurrent_compra': 25,
                'max_accounts': 5,
                'features': {
                    'batch_download': True,
                    'batch_process': True,
                    'advanced_processing': False,
                    'priority_support': False
                }
            }
            return jsonify({'success': True, 'config': default_config})
            
    except Exception as e:
        return jsonify({'success': False, 'error': f'獲取配置失敗: {str(e)}'})

@app.route('/admin/user-services/<int:user_service_id>/config', methods=['POST'])
def save_user_service_config(user_service_id):
    """保存用戶服務配置"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    try:
        data = request.get_json()
        config = data.get('config', {})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 更新用戶服務配置
        import json
        cursor.execute("""
            UPDATE user_services 
            SET config_json = ?
            WHERE id = ?
        """, (json.dumps(config, ensure_ascii=False), user_service_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '配置保存成功'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'保存配置失敗: {str(e)}'})

@app.route('/admin/services/<int:service_id>/param', methods=['POST'])
def save_service_param(service_id):
    """保存服務參數配置"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    try:
        data = request.get_json()
        param_name = data.get('param_name', '').strip()
        param_content = data.get('param_content', '').strip()
        
        if not param_name:
            return jsonify({'success': False, 'error': '參數名稱不能為空'})
        
        if not param_content:
            return jsonify({'success': False, 'error': '參數內容不能為空'})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取服務名稱
        cursor.execute("SELECT name FROM services WHERE id = ?", (service_id,))
        service = cursor.fetchone()
        if not service:
            conn.close()
            return jsonify({'success': False, 'error': '服務不存在'})
        
        service_name = service[0]
        
        # 檢查參數名稱是否已存在
        cursor.execute("SELECT id FROM service_versions WHERE service_name = ? AND param_name = ?", (service_name, param_name))
        existing = cursor.fetchone()
        
        if existing:
            # 更新現有配置
            cursor.execute("""
                UPDATE service_versions 
                SET param_content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE service_name = ? AND param_name = ?
            """, (param_content, service_name, param_name))
        else:
            # 創建新配置
            cursor.execute("""
                INSERT INTO service_versions (service_name, param_name, param_content)
                VALUES (?, ?, ?)
            """, (service_name, param_name, param_content))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '參數配置保存成功'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'保存參數失敗: {str(e)}'})

@app.route('/admin/services/<int:service_id>/versions', methods=['GET'])
def get_service_versions(service_id):
    """獲取服務的所有參數配置"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取服務名稱
        cursor.execute("SELECT name FROM services WHERE id = ?", (service_id,))
        service = cursor.fetchone()
        if not service:
            conn.close()
            return jsonify({'success': False, 'error': '服務不存在'})
        
        service_name = service[0]
        
        # 獲取所有參數配置
        cursor.execute("""
            SELECT id, param_name, param_content 
            FROM service_versions 
            WHERE service_name = ?
            ORDER BY param_name
        """, (service_name,))
        
        params = cursor.fetchall()
        conn.close()
        
        param_list = []
        for param in params:
            param_list.append({
                'id': param[0],
                'param_name': param[1],
                'param_content': param[2]
            })
        
        return jsonify({'success': True, 'params': param_list})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'獲取參數失敗: {str(e)}'})

@app.route('/admin/services/versions', methods=['GET'])
def get_service_versions_by_name():
    """通過服務名稱獲取參數配置"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    service_name = request.args.get('service_name')
    if not service_name:
        return jsonify({'success': False, 'error': '請提供服務名稱'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取所有參數配置
        cursor.execute("""
            SELECT id, param_name, param_content 
            FROM service_versions 
            WHERE service_name = ?
            ORDER BY param_name
        """, (service_name,))
        
        params = cursor.fetchall()
        conn.close()
        
        versions = []
        for param in params:
            versions.append({
                'id': param[0],
                'param_name': param[1],
                'param_content': param[2]
            })
        
        return jsonify({'success': True, 'versions': versions})
    except Exception as e:
        return jsonify({'success': False, 'error': f'獲取參數配置失敗: {str(e)}'})

@app.route('/admin/services/<int:service_id>/param/<int:param_id>', methods=['DELETE'])
def delete_service_param(service_id, param_id):
    """刪除服務的單個參數配置"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取服務名稱
        cursor.execute("SELECT name FROM services WHERE id = ?", (service_id,))
        service = cursor.fetchone()
        if not service:
            conn.close()
            return jsonify({'success': False, 'error': '服務不存在'})
        
        service_name = service[0]
        
        # 刪除指定的參數配置
        cursor.execute("DELETE FROM service_versions WHERE id = ? AND service_name = ?", (param_id, service_name))
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({'success': False, 'error': '參數配置不存在'})
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '參數配置刪除成功'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'刪除參數失敗: {str(e)}'})

@app.route('/admin/services/<int:service_id>/config', methods=['GET'])
def get_service_config(service_id):
    """獲取服務的 config_json 配置"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT config_json 
            FROM services 
            WHERE id = ?
        """, (service_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        # 處理返回格式（可能是字典或元組）
        config_str = None
        if result:
            if isinstance(result, dict):
                config_str = result.get('config_json') or result.get(list(result.keys())[0])
            else:
                config_str = result[0] if len(result) > 0 else None
        
        if config_str:
            import json
            config = json.loads(config_str)
            return jsonify({'success': True, 'config': config})
        else:
            # 返回默認配置
            default_config = {
                'max_concurrent_downloads': 5,
                'max_concurrent_procesar_venta': 5,
                'max_concurrent_procesar_compra': 3,
                'max_concurrent_venta': 5,
                'max_concurrent_compra': 25,
                'max_accounts': 5,
                'features': {
                    'batch_download': True,
                    'batch_process': True,
                    'advanced_processing': False,
                    'priority_support': False
                }
            }
            return jsonify({'success': True, 'config': default_config})
            
    except Exception as e:
        return jsonify({'success': False, 'error': f'獲取配置失敗: {str(e)}'})

@app.route('/admin/services/<int:service_id>/config', methods=['POST'])
def save_service_config(service_id):
    """保存服務的 config_json 配置"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    try:
        data = request.get_json()
        config = data.get('config', {})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 更新服務配置
        import json
        cursor.execute("""
            UPDATE services 
            SET config_json = ?
            WHERE id = ?
        """, (json.dumps(config, ensure_ascii=False), service_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '服務配置保存成功'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'保存配置失敗: {str(e)}'})

@app.route('/admin/services/templates', methods=['GET'])
def get_config_templates():
    """獲取參數模板列表"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '權限不足'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, version, description 
            FROM services 
            WHERE name = 'Zofri_Compra_Venta' AND version IS NOT NULL AND version != '' AND status = 'active'
            ORDER BY version
        """)
        
        templates = cursor.fetchall()
        conn.close()
        
        template_list = []
        for template in templates:
            template_list.append({
                'id': template[0],
                'name': template[1],  # version 作為模板名稱
                'description': template[2]
            })
        
        return jsonify({'success': True, 'templates': template_list})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'獲取模板失敗: {str(e)}'})

@app.route('/api/user-config', methods=['GET'])
def get_user_config():
    """獲取用戶配置參數（供代碼登入時使用）"""
    try:
        # 從請求頭獲取用戶信息（需要你的代碼在登入時傳遞）
        user_id = request.headers.get('X-User-ID')
        service_name = request.args.get('service_name', 'Zofri_Compra_Venta')
        
        if not user_id:
            return jsonify({'success': False, 'error': '缺少用戶ID'})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取用戶的服務配置
        cursor.execute("""
            SELECT us.config_json 
            FROM user_services us
            JOIN services s ON us.service_id = s.id
            WHERE us.user_id = ? AND s.name = ? AND us.status = 'active'
            ORDER BY us.end_date DESC
            LIMIT 1
        """, (user_id, service_name))
        
        result = cursor.fetchone()
        conn.close()
        
        # 處理返回格式（可能是字典或元組）
        config_params = None
        if result:
            if isinstance(result, dict):
                config_params = result.get('config_params') or result.get(list(result.keys())[0])
            else:
                config_params = result[0] if len(result) > 0 else None
        
        if config_params:
            # 返回原始參數代碼
            return jsonify({
                'success': True,
                'config_params': config_params
            })
        else:
            # 返回默認參數
            default_params = """MAX_CONCURRENT_DOWNLOADS = 5
MAX_CONCURRENT_PROCESAR_VENTA = 5
MAX_CONCURRENT_PROCESAR_COMPRA = 3
MAX_CONCURRENT_VENTA = 5
MAX_CONCURRENT_COMPRA = 25"""
            
            return jsonify({
                'success': True,
                'config_params': default_params
            })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'獲取配置失敗: {str(e)}'})

@app.route('/admin/user-sessions')
def admin_user_sessions():
    """管理員用戶會話監控"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    user_role = session.get('role')
    if user_role not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    return render_template('admin/user_sessions.html')

# ========== 啟動應用 ==========
if __name__ == '__main__':
    # 初始化資料庫
    init_database()
    
    # 開發模式運行（PythonAnywhere 會用 WSGI）
    app.run(debug=True, host='0.0.0.0', port=5000)
