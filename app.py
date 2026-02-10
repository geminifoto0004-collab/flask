"""
Flask ??蝞∠?蝟餌絞 - 銝餅??典??
?嚗恣??餃??甈恣?PI ?亥岷
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import hashlib
import sqlite3
from datetime import datetime
from functools import wraps
from utils.time_utils import get_chile_time_naive

# 撠?蔭???澈
from config import config, admin_config, license_config, feature_flags
from database import get_db_connection, init_database, get_lastrowid, get_cursor, get_row_dict
from services import container_iti_service

# 撠 Blueprint
from blueprints.user_auth_bp import user_auth_bp
from blueprints.api_auth_bp import api_auth_bp
from blueprints.monitor_bp import monitor_bp
from blueprints.container_bp import container_bp
from services.config_service import config_service

# 撠?萎辣隞?? Blueprint嚗ythonAnywhere 蝡臭蝙?剁??舫嚗?
# 憒?閬 PythonAnywhere 銝蝙?其誨???踝???銝?酉??
from services.email_proxy import email_proxy_bp


# ========== Flask ?????==========
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = config.PERMANENT_SESSION_LIFETIME

# 閮餃? Blueprint
app.register_blueprint(user_auth_bp)
app.register_blueprint(api_auth_bp)
app.register_blueprint(monitor_bp)
app.register_blueprint(container_bp)

# 閮餃??萎辣隞?? Blueprint嚗ythonAnywhere 蝡臭蝙?剁??舫嚗?
# 憒?閬 PythonAnywhere 銝蝙?其誨???踝???銝?酉??
app.register_blueprint(email_proxy_bp)

# ========== ?芸??????澈 ==========
# ?冽??典????芸??????澈嚗?冽 Render 蝑??Ｙ憓?
# 雿輻 before_request 雿?瑁?銝甈?
_database_initialized = False

@app.before_request
def initialize_database():
    """?券?甈∟?瘙??????澈"""
    global _database_initialized
    if not _database_initialized:
        try:
            init_database()
            print("??鞈?摨怨??憪?摰?")
            _database_initialized = True
        except Exception as e:
            import traceback
            print(f"??  鞈?摨怠?憪?憭望?: {e}")
            print(f"   閰喟敦?航炊: {traceback.format_exc()}")
            # 銝甇Ｘ??典???霈?嗅隞亥赤?隤日???
            _database_initialized = True  # 璅??箏歇?岫嚗??銴?閰?


# ========== ?餃撽?鋆ˇ??==========
def login_required(f):
    """?餃撽?鋆ˇ??""
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





# ========== API 蝡舫?嚗?甈炎??==========
@app.route('/api/check-license', methods=['POST'])
def api_check_license():
    """API蝡舫?嚗炎?亦?嗆?甈???""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'success': False, 'error': '隢?靘蝞勗?撖Ⅳ'})
        
        # 撽??冽?餃
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?芸?瑼Ｘ頞?蝞∠??∪董??
        if email == admin_config.SUPER_ADMIN_EMAIL:
            if password == admin_config.SUPER_ADMIN_PASSWORD:
                conn.close()
                return jsonify({
                    'success': True, 
                    'message': '頞?蝞∠??⊥?甈?霅???,
                    'user_type': admin_config.SUPER_ADMIN_ROLE,
                    'services': [{'name': '頞?蝞∠??⊥???, 'status': 'active', 'end_date': '2099-12-31'}]
                })
            else:
                conn.close()
                return jsonify({'success': False, 'error': '頞?蝞∠??∪?蝣潮隤?})
        
        # 瑼Ｘ?桅??
        cursor.execute('SELECT id, password_hash, role FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return jsonify({'success': False, 'error': '?冽銝???})
        
        # ??餈??澆?嚗?賣摮??蝯?
        if isinstance(user, dict):
            user_id = user['id']
            stored_password_hash = user['password_hash']
            user_role = user['role']
        else:
            user_id = user[0]
            stored_password_hash = user[1]
            user_role = user[2]
        
        # 撽?撖Ⅳ
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if stored_password_hash != password_hash:
            conn.close()
            return jsonify({'success': False, 'error': '撖Ⅳ?航炊'})
        
        # ?脣??冽??
        cursor.execute('''
            SELECT us.*, s.name as service_name, s.description
            FROM user_services us
            JOIN services s ON us.service_id = s.id
            WHERE us.user_id = ? AND us.status = 'active'
        ''', (user_id,))
        services = cursor.fetchall()
        
        # 瑼Ｘ???臬??
        valid_services = []
        current_date = get_chile_time_naive().date()
        
        for service in services:
            # ??餈??澆?嚗?賣摮??蝯?
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
                'message': '??撽???',
                'user_type': 'user',
                'services': valid_services
            })
        else:
            return jsonify({
                'success': False, 
                'error': '瘝???????甈???撌脤???
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': f'蝟餌絞?航炊: {str(e)}'})

# ========== 頝舐嚗絞銝?餃/?餃 ==========
@app.route('/login', methods=['GET', 'POST'])
def login():
    """蝯曹??餃?亙"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        if not email or not password:
            return render_template('user/login.html', error='隢‵撖怠??港縑??)
        
        # ?芸?瑼Ｘ頞?蝞∠??∪董??
        from config import admin_config
        print(f"?餃?岫: ?萇拳='{email}', 撖Ⅳ='{password}'")
        print(f"Super Admin?蔭: ?萇拳='{admin_config.SUPER_ADMIN_EMAIL}', 撖Ⅳ='{admin_config.SUPER_ADMIN_PASSWORD}'")
        
        if email == admin_config.SUPER_ADMIN_EMAIL and password == admin_config.SUPER_ADMIN_PASSWORD:
            print("Super Admin?餃??嚗?)
            session['logged_in'] = True
            # 敺?澈?脣?頞?蝞∠??∠?撖阡? user_id嚗???摮?撱?
            conn = None
            try:
                conn = get_db_connection()
                cursor = get_cursor(conn)  # 雿輻 get_cursor 隞交????澈憿?
                cursor.execute('SELECT id, company_name FROM users WHERE email = ?', (admin_config.SUPER_ADMIN_EMAIL,))
                user_row = cursor.fetchone()
                
                if user_row:
                    # 憒??豢?摨思葉撌脫?嚗蝙?冽?澈?D??詨?蝔?
                    # ??銝??豢?摨怨??撘?SQLite 餈???嚗ySQL/TiDB 餈?摮
                    if isinstance(user_row, dict):
                        session['user_id'] = user_row['id']
                        session['company_name'] = user_row.get('company_name')
                    else:
                        # ??餈??澆?嚗?賣摮??蝯?
                        if isinstance(user_row, dict):
                            session['user_id'] = user_row['id']
                            session['company_name'] = user_row.get('company_name')
                        else:
                            session['user_id'] = user_row[0]
                            session['company_name'] = user_row[1] if len(user_row) > 1 and user_row[1] else None
                else:
                    # 憒??豢?摨思葉瘝?嚗?撱箄?蝝恣??冽
                    print("?? ?豢?摨思葉瘝?頞?蝞∠??∴?甇??萄遣...")
                    from services.user_service import hash_password
                    password_hash = hash_password(admin_config.SUPER_ADMIN_PASSWORD)
                    cursor.execute('''
                        INSERT INTO users (username, email, password_hash, role, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (admin_config.SUPER_ADMIN_USERNAME, admin_config.SUPER_ADMIN_EMAIL, 
                          password_hash, admin_config.SUPER_ADMIN_ROLE, get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')))
                    session['user_id'] = get_lastrowid(cursor, conn)
                    conn.commit()
                    print(f"??頞?蝞∠??∪撱箸???user_id={session['user_id']}")
                    session['company_name'] = None  # ?啣撱箇??冽瘝??砍?迂
                
                if conn:
                    conn.close()
            except Exception as e:
                import traceback
                print(f"???豢?摨急?雿仃?? {e}")
                print(f"   閰喟敦?航炊: {traceback.format_exc()}")
                # 憒??豢?摨急?雿仃??隞?迂?餃嚗蝙?券?隤潘?
                if 'user_id' not in session:
                    session['user_id'] = None  # ?冽?閮剔蔭嚗?蝥?賡?閬???
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                # 蝜潛??瑁?嚗??餅迫?餃
            session['username'] = admin_config.SUPER_ADMIN_USERNAME
            session['email'] = admin_config.SUPER_ADMIN_EMAIL
            session['role'] = admin_config.SUPER_ADMIN_ROLE
            
            # ?萄遣?店閮?嚗?潭?閰梁?改?
            try:
                from blueprints.api_auth_bp import create_session, generate_session_token, get_device_info
                session_token = generate_session_token()
                device_info = get_device_info(request)
                success = create_session(session['user_id'], session_token, device_info, service_name="Web_Login")
                if success:
                    print(f"???萄遣頞?蝞∠??∠雯??交?閰梯?????- ?冽 {session['user_id']}, service_name=Web_Login")
                else:
                    print(f"???萄遣頞?蝞∠??∠雯??交?閰梯??仃??- ?冽 {session['user_id']}, create_session餈?False")
            except ImportError as e:
                print(f"??撠?店蝞∠??賣憭望?: {e}")
            except Exception as e:
                import traceback
                print(f"???萄遣?店閮?憭望?嚗?敶梢?餃嚗? {e}")
                print(f"   閰喟敦?航炊: {traceback.format_exc()}")
            
            return redirect(url_for('admin_dashboard'))
        else:
            print("Super Admin?餃憭望?嚗?閰行??園?霅?)
        
        # 雿輻?冽??撽??桅??
        from services.user_service import verify_password
        success, result = verify_password(email, password)
        
        if success:
            session['logged_in'] = True
            session['user_id'] = result['id']
            session['username'] = result['username']
            session['email'] = result['email']
            session['role'] = result['role']
            
            # ?萄遣?店閮?嚗?潭?閰梁?改?
            try:
                from blueprints.api_auth_bp import create_session, generate_session_token, get_device_info
                session_token = generate_session_token()
                device_info = get_device_info(request)
                success = create_session(result['id'], session_token, device_info, service_name="Web_Login")
                if success:
                    print(f"???萄遣蝬脤??餃?店閮??? - ?冽 {result['id']}, service_name=Web_Login")
                else:
                    print(f"???萄遣蝬脤??餃?店閮?憭望? - ?冽 {result['id']}, create_session餈?False")
            except ImportError as e:
                print(f"??撠?店蝞∠??賣憭望?: {e}")
            except Exception as e:
                import traceback
                print(f"???萄遣?店閮?憭望?嚗?敶梢?餃嚗? {e}")
                print(f"   閰喟敦?航炊: {traceback.format_exc()}")
            
            # ?寞?閫???銝??
            if result['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_auth.user_portal'))
        else:
            return render_template('user/login.html', error='Correo electr籀nico o contrase簽a incorrectos')
    
    return render_template('user/login.html')


@app.route('/logout')
def logout():
    """?餃"""
    session.clear()
    return redirect(url_for('login'))


# ========== 頝舐嚗恣??銵冽 ==========
@app.route('/admin')
@login_required
def admin_dashboard():
    """蝞∠??∪?銵冽"""
    if session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    try:
        from database import get_db_connection, get_cursor
        conn = get_db_connection()
        
        # ?脣??冽蝯梯?嚗蝙??get_cursor 隞交????澈憿?嚗?
        cursor = get_cursor(conn)
        cursor.execute('SELECT COUNT(*) as total FROM users')
        result = cursor.fetchone()
        # ??銝??豢?摨怨??撘?
        db_total_users = result['total'] if isinstance(result, dict) else result[0]
        
        cursor.execute('SELECT COUNT(*) as total FROM users WHERE role = ?', ('admin',))
        result = cursor.fetchone()
        db_admin_users = result['total'] if isinstance(result, dict) else result[0]
        
        cursor.execute('SELECT COUNT(*) as total FROM users WHERE role = ?', ('user',))
        result = cursor.fetchone()
        db_regular_users = result['total'] if isinstance(result, dict) else result[0]
        
        # ?頞?蝞∠??∠?蝯梯?
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
        print(f"??蝞∠??∪?銵冽?航炊: {e}")
        print(f"   閰喟敦?航炊: {traceback.format_exc()}")
        # 餈??航炊???摰??啁??
        return render_template('admin/dashboard.html', 
                             total_users=0,
                             admin_users=0,
                             regular_users=0,
                             error=f"鞈?摨恍隤? {str(e)}")

@app.route('/admin/dashboard')
@login_required
def admin_dashboard_redirect():
    """???admin銝駁?"""
    return redirect(url_for('admin_dashboard'))


# ========== ????蝟餌絞撌脩宏?歹??寧 services ??user_services 蝟餌絞 ==========


# ========== API嚗?甈閰ｇ?獢蝔??剁?==========
@app.route('/licenses/check_license', methods=['GET'])
def check_license():
    """
    ???亥岷 API
    ?: rut (靘? 76315010-0)
    餈?: JSON {rut, empresa, estado, fecha_expiracion}
    """
    rut = request.args.get('rut')
    
    if not rut:
        return jsonify({'error': '蝻箏? RUT ?'}), 400
    
    try:
        conn = get_db_connection()
        license = conn.execute(
            'SELECT rut, empresa, status, expire_date FROM licenses WHERE rut=?',
            (rut,)
        ).fetchone()
        conn.close()
        
        if license:
            # 瑼Ｘ?臬??
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
            return jsonify({'error': '??銝???}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ========== ?冽蝞∠? ==========
@app.route('/admin/users')
def admin_users():
    """蝞∠??⊥?????""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, role, created_at FROM users ORDER BY created_at DESC')
    users_rows = cursor.fetchall()
    # 撠ow撠情頧??箏??詨?銵?
    users = [dict(row) for row in users_rows]
    
    # 瘛餃?頞?蝞∠??∪?”?嚗??蔭?辣?脣?嚗?敺??澈嚗?
    super_admin = {
        'id': admin_config.SUPER_ADMIN_USERNAME,
        'username': admin_config.SUPER_ADMIN_USERNAME,
        'email': admin_config.SUPER_ADMIN_EMAIL,
        'role': admin_config.SUPER_ADMIN_ROLE,
        'created_at': '蝟餌絞?萄遣'
    }
    users.insert(0, super_admin)
    
    conn.close()
    
    return render_template('admin/users.html', users=users, super_admin_role=admin_config.SUPER_ADMIN_ROLE)

@app.route('/admin/users/<int:user_id>/role', methods=['POST'])
def update_user_role(user_id):
    """?湔?冽閫"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'error': '甈?銝雲'}), 403
    new_role = request.form.get('role')
    
    if not user_id or not new_role:
        return jsonify({'error': '?銝???}), 400
    
    if new_role not in ['user', 'admin']:
        return jsonify({'error': '?⊥?????}), 400
    
    # 瑼Ｘ?臬?箄?蝝恣?嚗?蝝恣?銝鋡思耨?對?
    if str(user_id) == admin_config.SUPER_ADMIN_USERNAME:
        return jsonify({'error': '頞?蝞∠??∠?閫?⊥?靽格'}), 400
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 瑼Ｘ?冽?臬摮
    cursor.execute('SELECT id, role FROM users WHERE id=?', (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return jsonify({'error': '?冽銝???}), 404
    
    # 瑼Ｘ甈?嚗??蝝恣??臭誑??蝞∠???
    current_user_role = session.get('role')
    
    # 憒??航?撠恣????箸???
    if user['role'] == 'admin' and new_role == 'user':
        # ?芣?頞?蝞∠??∪隞仿?蝝恣?
        if current_user_role != admin_config.SUPER_ADMIN_ROLE:
            conn.close()
            return jsonify({
                'error': '甈?銝雲嚗??蝝恣??臭誑撠恣????箸???
            }), 403
        
        # 頞?蝞∠??∪隞仿??蝝恣?嚗??箄?蝝恣?瘞賊?摮
    
    # ?湔閫
    cursor.execute('UPDATE users SET role=? WHERE id=?', (new_role, user_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': '閫?湔??'})

@app.route('/admin/services')
def admin_services():
    """??蝞∠??"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM services ORDER BY created_at DESC')
    services_rows = cursor.fetchall()
    # 撠ow撠情頧??箏??詨?銵?
    services = [dict(row) for row in services_rows]
    conn.close()
    
    return render_template('admin/services.html', services=services)

@app.route('/admin/services', methods=['POST'])
def create_service():
    """?萄遣?唳???""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    name = request.form.get('name')
    description = request.form.get('description', '')
    price = request.form.get('price')
    duration_days = request.form.get('duration_days')
    status = request.form.get('status', 'active')
    
    if not all([name, price, duration_days]):
        return jsonify({'success': False, 'error': '隢‵撖急???憛急?雿?})
    
    try:
        price = float(price)
        duration_days = int(duration_days)
    except ValueError:
        return jsonify({'success': False, 'error': '?寞????敹??箸摮?})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # ?脣??蔭 JSON嚗????店嚗?
        config_json = request.form.get('config_json', '')
        
        cursor.execute('''
            INSERT INTO services (name, description, price, duration_days, status, config_json)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, description, price, duration_days, status, config_json))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '???萄遣??'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?萄遣憭望?: {str(e)}'})

@app.route('/admin/services/<int:service_id>', methods=['GET'])
def get_service(service_id):
    """?脣??桀??縑??""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM services WHERE id = ?', (service_id,))
    service = cursor.fetchone()
    conn.close()
    
    if service:
        return jsonify({'success': True, 'service': dict(service)})
    else:
        return jsonify({'success': False, 'error': '??銝???})

@app.route('/admin/services/<int:service_id>', methods=['PUT'])
def update_service(service_id):
    """?湔??"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    name = request.form.get('name')
    description = request.form.get('description', '')
    price = request.form.get('price')
    duration_days = request.form.get('duration_days')
    status = request.form.get('status', 'active')
    
    if not all([name, price, duration_days]):
        return jsonify({'success': False, 'error': '隢‵撖急???憛急?雿?})
    
    try:
        price = float(price)
        duration_days = int(duration_days)
    except ValueError:
        return jsonify({'success': False, 'error': '?寞????敹??箸摮?})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 瑼Ｘ???臬摮
        cursor.execute('SELECT id FROM services WHERE id = ?', (service_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': '??銝???})
        
        cursor.execute('''
            UPDATE services 
            SET name = ?, description = ?, price = ?, duration_days = ?, status = ?
            WHERE id = ?
        ''', (name, description, price, duration_days, status, service_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '???湔??'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?湔憭望?: {str(e)}'})

@app.route('/admin/services/<int:service_id>', methods=['DELETE'])
def delete_service(service_id):
    """?芷??"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 瑼Ｘ???臬摮
        cursor.execute('SELECT name FROM services WHERE id = ?', (service_id,))
        service = cursor.fetchone()
        
        if not service:
            return jsonify({'success': False, 'error': '??銝???})
        
        # 瑼Ｘ?臬??嗆迤?其蝙?冽迨??
        cursor.execute('SELECT COUNT(*) FROM user_services WHERE service_id = ?', (service_id,))
        user_count_result = cursor.fetchone()
        user_count = user_count_result[0] if isinstance(user_count_result, tuple) else (user_count_result.get('COUNT(*)') or user_count_result.get(list(user_count_result.keys())[0]) if user_count_result else 0)
        
        if user_count > 0:
            return jsonify({'success': False, 'error': f'?⊥??芷嚗? {user_count} ??嗆迤?其蝙?冽迨??'})
        
        # ?芷??
        cursor.execute('DELETE FROM services WHERE id = ?', (service_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'?? {service["name"]} 撌脣??})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?芷憭望?: {str(e)}'})

@app.route('/admin/user-services')
def admin_user_services():
    """?冽??蝞∠??"""
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
    # 撠ow撠情頧??箏??詨?銵?
    user_services = [dict(row) for row in user_services_rows]
    conn.close()
    
    return render_template('admin/user_services.html', user_services=user_services)

@app.route('/admin/user-services/by-email/<email>')
def get_user_services_by_email(email):
    """?寞?email?亥岷?冽??嚗PI嚗?""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
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
    """?脣??冽撖Ⅳ靽⊥"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # ?脣??冽靽⊥
    cursor.execute('SELECT username, password_hash FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return jsonify({
            'success': True,
            'username': user['username'],
            'password': '撖Ⅳ撌脣?撖???,
            'password_hash': user['password_hash'][:16] + '...',  # 憿舐內?典?hash
            'note': '蝟餌絞雿輻SHA256??摮撖Ⅳ嚗瘜????
        })
    else:
        return jsonify({'success': False, 'error': '?冽銝???})

@app.route('/admin/users/<int:user_id>/services')
def get_user_services(user_id):
    """?脣??冽????銵?""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
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
    """?箇?嗅?????""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    user_id = request.form.get('user_id')
    service_id = request.form.get('service_id')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    auto_calculate = request.form.get('auto_calculate', 'true') == 'true'
    
    if not all([user_id, service_id, start_date]):
        return jsonify({'success': False, 'error': '隢‵撖怎?嗚??????交?'})
    
    from database import get_db_connection
    from datetime import datetime, timedelta
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 瑼Ｘ?冽????血???
        cursor.execute('SELECT id FROM users WHERE id = ?', (user_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': '?冽銝???})
        
        cursor.execute('SELECT id, duration_days FROM services WHERE id = ?', (service_id,))
        service = cursor.fetchone()
        if not service:
            return jsonify({'success': False, 'error': '??銝???})
        
        # ??蝯??交?
        if auto_calculate and not end_date:
            # ?芸?閮?蝯??交?
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = start_dt + timedelta(days=service['duration_days'])
            end_date = end_dt.strftime('%Y-%m-%d')
        elif not end_date:
            return jsonify({'success': False, 'error': '隢‵撖怎?????豢??芸?閮?'})
        
        # 撽??交?????
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        if end_dt <= start_dt:
            return jsonify({'success': False, 'error': '蝯??交?敹?????交?'})
        
        # 瑼Ｘ?臬頞???璅???
        actual_days = (end_dt - start_dt).days
        if actual_days > service['duration_days']:
            return jsonify({
                'success': False, 
                'error': f'????銝頞?璅??? {service["duration_days"]} 憭?
            })
        
        # ??冽??閮?
        cursor.execute('''
            INSERT INTO user_services (user_id, service_id, start_date, end_date, status)
            VALUES (?, ?, ?, ?, 'active')
        ''', (user_id, service_id, start_date, end_date))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'??????嚗???嚗start_date} ??{end_date}嚗actual_days}憭抬?'
        })
        
    except ValueError as e:
        conn.close()
        return jsonify({'success': False, 'error': 'Formato de fecha incorrecto, use el formato YYYY-MM-DD'})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'??憭望?: {str(e)}'})

@app.route('/admin/user-services/<int:user_service_id>', methods=['DELETE'])
def delete_user_service(user_service_id):
    """?芷?冽??"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 瑼Ｘ?冽???臬摮
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
        
        # ?芷?冽??閮?
        cursor.execute('DELETE FROM user_services WHERE id = ?', (user_service_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'?冽 {user_service["username"]} ????{user_service["service_name"]} 撌脣??
        })
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?芷憭望?: {str(e)}'})

@app.route('/admin/user-services/<int:user_service_id>', methods=['GET'])
def get_user_service(user_service_id):
    """?脣??桀?嗆??縑??""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
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
        # 頧??箏???
        user_service_dict = dict(user_service)
        
        # 憒???蝵殷??岫?曉撠????賊?蝵桀?蝔?
        if user_service_dict.get('config_json'):
            cursor.execute('''
                SELECT param_name FROM service_versions 
                WHERE service_name = ? AND param_content = ?
            ''', (user_service_dict['service_name'], user_service_dict['config_json']))
            
            param_result = cursor.fetchone()
            if param_result:
                # ??餈??澆?嚗?賣摮??蝯?
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
    """?湔?冽??"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    # ?舀? JSON ??form ?豢?
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
        return jsonify({'success': False, 'error': '隢‵撖恍?憪??蝯??交?'})
    
    from database import get_db_connection
    from datetime import datetime
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 瑼Ｘ?冽???臬摮
        cursor.execute('SELECT id FROM user_services WHERE id = ?', (user_service_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': '?冽??銝???})
        
        # 撽??交??澆?????
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        if end_dt <= start_dt:
            return jsonify({'success': False, 'error': '蝯??交?敹?????交?'})
        
        # 憒???鈭??賊?蝵殷??脣??蔭?批捆
        config_json = None
        if param_config:
            cursor.execute('SELECT param_content FROM service_versions WHERE service_name = "Zofri_Compra_Venta" AND param_name = ?', (param_config,))
            config_result = cursor.fetchone()
            if config_result:
                # ??餈??澆?嚗?賣摮??蝯?
                if isinstance(config_result, dict):
                    config_json = config_result.get('param_content') or config_result.get(list(config_result.keys())[0])
                else:
                    config_json = config_result[0]  # ?ㄐ靽?????隞?Ⅳ
        
        # ?湔?冽??
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
            'message': f'?冽???湔??嚗???: {start_date} ??{end_date} ({actual_days} 憭?'
        })
        
    except ValueError as e:
        conn.close()
        return jsonify({'success': False, 'error': '?交??澆?銝迤蝣綽?隢蝙??YYYY-MM-DD ?澆?'})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?湔憭望?: {str(e)}'})

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """?芷?冽"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    # 瑼Ｘ?臬?箄?蝝恣?嚗?蝝恣?銝鋡怠?歹?
    if str(user_id) == admin_config.SUPER_ADMIN_USERNAME:
        return jsonify({'success': False, 'error': '頞?蝞∠??∠瘜◤?芷'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 瑼Ｘ?冽?臬摮
        cursor.execute('SELECT username, role FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'error': '?冽銝???})
        
        # 憒?閬?斤??舐恣?嚗炎?交?行?撠瘝?蝞∠???
        if user['role'] == 'admin':
            # 瑼Ｘ?嗅?蝞∠??∠蜇?賂?銝??祈?蝝恣?嚗?
            cursor.execute('SELECT COUNT(*) as admin_count FROM users WHERE role="admin"')
            admin_count = cursor.fetchone()['admin_count']
            
            # 憒??芣?銝?恣?嚗??迂?芷嚗?蝝恣?瘞賊?摮嚗?
            if admin_count <= 1:
                conn.close()
                return jsonify({
                    'success': False, 
                    'error': '?⊥??芷嚗頂蝯勗??撠?????恣???蝝恣?瘞賊?摮嚗?撱箄降靽??喳?銝??恣???
                })
        
        # ?芷?冽??????
        cursor.execute('DELETE FROM user_services WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM verification_codes WHERE email = (SELECT email FROM users WHERE id = ?)', (user_id,))
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'?冽 {user["username"]} 撌脣??})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?芷憭望?: {str(e)}'})

@app.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
def reset_user_password(user_id):
    """?蔭?冽撖Ⅳ"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    new_password = request.form.get('new_password')
    if not new_password:
        return jsonify({'success': False, 'error': '隢撓?交撖Ⅳ'})
    
    from utils.validators import validate_password
    valid, msg = validate_password(new_password)
    if not valid:
        return jsonify({'success': False, 'error': msg})
    
    from database import get_db_connection
    from services.user_service import hash_password
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 瑼Ｘ?冽?臬摮
        cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'error': '?冽銝???})
        
        # ?湔撖Ⅳ
        password_hash = hash_password(new_password)
        cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, user_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'?冽 {user["username"]} ??蝣澆歇?蔭',
            'new_password': new_password  # 餈??啣?蝣潔?蝞∠??∪??亦??
        })
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?蔭憭望?: {str(e)}'})

@app.route('/admin/database')
def admin_database():
    """蝞∠??∟??澈?汗"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    try:
        from database import get_db_connection, get_cursor, get_table_names
        conn = get_db_connection()
        cursor = get_cursor(conn)  # 雿輻 get_cursor 隞交????澈憿?
        
        # ?脣???”??雿輻蝯曹???賂?
        table_names = get_table_names(cursor)
        tables = [{'name': name} for name in table_names]
        
        # ?脣?瘥”???
        table_data = {}
        for table_name in table_names:
            try:
                cursor.execute(f"SELECT * FROM {table_name}")
                rows = cursor.fetchall()
                # ??銝??豢?摨怨??撘?
                if rows and isinstance(rows[0], dict):
                    table_data[table_name] = rows
                else:
                    # SQLite 餈? Row 撠情嚗?閬???
                    table_data[table_name] = [dict(row) for row in rows]
            except Exception as e:
                print(f"?脣?銵?{table_name} ?豢?憭望?: {e}")
                table_data[table_name] = []
        
        conn.close()
        
        return render_template('admin/database.html', tables=tables, table_data=table_data)
        
    except Exception as e:
        import traceback
        print(f"鞈?摨怎汗?航炊: {e}")
        print(f"   閰喟敦?航炊: {traceback.format_exc()}")
        return render_template('admin/database.html', tables=[], table_data={}, error=str(e))


# ?????芷API撌脩宏?歹??寧?啁???蝟餌絞


# ========== 擐?????==========
@app.route('/')
def index():
    """擐????蝞∠??∠??""
    if session.get('logged_in'):
        if session.get('role') in ['admin', admin_config.SUPER_ADMIN_ROLE]:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('user_auth.user_portal'))
    return redirect(url_for('login'))


# ========== ?冽???賊?頝舐 ==========
@app.route('/user/services')
def user_services():
    """?冽???"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    return render_template('user/services.html')

@app.route('/user/services/api')
def user_services_api():
    """?脣??嗅??冽????銵剁?API嚗?""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': '隢??餃'})
    
    try:
        from database import get_db_connection
        from datetime import datetime
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?寞??冽ID?亥岷??
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
            # 瑼Ｘ???臬??瞈瘣鳴?status ??active 銝?end_date ?芷???
            if service.get('status') == 'active' and service.get('end_date'):
                # 瘥??交?摮泵銝莎??澆?嚗YYY-MM-DD嚗?
                if service['end_date'] < current_date:
                    # 憒???鈭?撠????inactive
                    service['status'] = 'inactive'
                    service['is_expired'] = True
            services.append(service)
        
        conn.close()
        
        return jsonify({'success': True, 'services': services})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error al cargar servicios: {str(e)}'})


@app.route('/admin/user-services/<int:user_service_id>/config', methods=['GET'])
def get_user_service_config(user_service_id):
    """?脣??冽???蔭"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?脣??冽???蔭
        cursor.execute("""
            SELECT us.config_json 
            FROM user_services us
            WHERE us.id = ?
        """, (user_service_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        # ??餈??澆?嚗?賣摮??蝯?
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
            # 餈?暺??蔭
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
        return jsonify({'success': False, 'error': f'?脣??蔭憭望?: {str(e)}'})

@app.route('/admin/user-services/<int:user_service_id>/config', methods=['POST'])
def save_user_service_config(user_service_id):
    """靽??冽???蔭"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    try:
        data = request.get_json()
        config = data.get('config', {})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?湔?冽???蔭
        import json
        cursor.execute("""
            UPDATE user_services 
            SET config_json = ?
            WHERE id = ?
        """, (json.dumps(config, ensure_ascii=False), user_service_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '?蔭靽???'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'靽??蔭憭望?: {str(e)}'})

@app.route('/admin/services/<int:service_id>/param', methods=['POST'])
def save_service_param(service_id):
    """靽?????蔭"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    try:
        data = request.get_json()
        param_name = data.get('param_name', '').strip()
        param_content = data.get('param_content', '').strip()
        
        if not param_name:
            return jsonify({'success': False, 'error': '??迂銝?箇征'})
        
        if not param_content:
            return jsonify({'success': False, 'error': '??批捆銝?箇征'})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?脣????迂
        cursor.execute("SELECT name FROM services WHERE id = ?", (service_id,))
        service = cursor.fetchone()
        if not service:
            conn.close()
            return jsonify({'success': False, 'error': '??銝???})
        
        service_name = service[0]
        
        # 瑼Ｘ??迂?臬撌脣???
        cursor.execute("SELECT id FROM service_versions WHERE service_name = ? AND param_name = ?", (service_name, param_name))
        existing = cursor.fetchone()
        
        if existing:
            # ?湔?暹??蔭
            cursor.execute("""
                UPDATE service_versions 
                SET param_content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE service_name = ? AND param_name = ?
            """, (param_content, service_name, param_name))
        else:
            # ?萄遣?圈?蝵?
            cursor.execute("""
                INSERT INTO service_versions (service_name, param_name, param_content)
                VALUES (?, ?, ?)
            """, (service_name, param_name, param_content))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '??蔭靽???'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'靽??憭望?: {str(e)}'})

@app.route('/admin/services/<int:service_id>/versions', methods=['GET'])
def get_service_versions(service_id):
    """?脣????????賊?蝵?""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?脣????迂
        cursor.execute("SELECT name FROM services WHERE id = ?", (service_id,))
        service = cursor.fetchone()
        if not service:
            conn.close()
            return jsonify({'success': False, 'error': '??銝???})
        
        service_name = service[0]
        
        # ?脣?????賊?蝵?
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
        return jsonify({'success': False, 'error': f'?脣??憭望?: {str(e)}'})

@app.route('/admin/services/versions', methods=['GET'])
def get_service_versions_by_name():
    """?????迂?脣???蔭"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    service_name = request.args.get('service_name')
    if not service_name:
        return jsonify({'success': False, 'error': '隢?靘???蝔?})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?脣?????賊?蝵?
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
        return jsonify({'success': False, 'error': f'?脣???蔭憭望?: {str(e)}'})

@app.route('/admin/services/<int:service_id>/param/<int:param_id>', methods=['DELETE'])
def delete_service_param(service_id, param_id):
    """?芷??????賊?蝵?""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?脣????迂
        cursor.execute("SELECT name FROM services WHERE id = ?", (service_id,))
        service = cursor.fetchone()
        if not service:
            conn.close()
            return jsonify({'success': False, 'error': '??銝???})
        
        service_name = service[0]
        
        # ?芷?????賊?蝵?
        cursor.execute("DELETE FROM service_versions WHERE id = ? AND service_name = ?", (param_id, service_name))
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({'success': False, 'error': '??蔭銝???})
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '??蔭?芷??'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'?芷?憭望?: {str(e)}'})

@app.route('/admin/services/<int:service_id>/config', methods=['GET'])
def get_service_config(service_id):
    """?脣?????config_json ?蔭"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
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
        
        # ??餈??澆?嚗?賣摮??蝯?
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
            # 餈?暺??蔭
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
        return jsonify({'success': False, 'error': f'?脣??蔭憭望?: {str(e)}'})

@app.route('/admin/services/<int:service_id>/config', methods=['POST'])
def save_service_config(service_id):
    """靽?????config_json ?蔭"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
    try:
        data = request.get_json()
        config = data.get('config', {})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?湔???蔭
        import json
        cursor.execute("""
            UPDATE services 
            SET config_json = ?
            WHERE id = ?
        """, (json.dumps(config, ensure_ascii=False), service_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '???蔭靽???'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'靽??蔭憭望?: {str(e)}'})

@app.route('/admin/services/templates', methods=['GET'])
def get_config_templates():
    """?脣??璅⊥?”"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': '甈?銝雲'})
    
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
                'name': template[1],  # version 雿璅⊥?迂
                'description': template[2]
            })
        
        return jsonify({'success': True, 'templates': template_list})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'?脣?璅⊥憭望?: {str(e)}'})

@app.route('/api/user-config', methods=['GET'])
def get_user_config():
    """?脣??冽?蔭?嚗?隞?Ⅳ?餃?蝙?剁?"""
    try:
        # 敺?瘙?脣??冽靽⊥嚗?閬??誨蝣澆?餃???
        user_id = request.headers.get('X-User-ID')
        service_name = request.args.get('service_name', 'Zofri_Compra_Venta')
        
        if not user_id:
            return jsonify({'success': False, 'error': '蝻箏??冽ID'})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?脣??冽????蝵?
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
        
        # ??餈??澆?嚗?賣摮??蝯?
        config_params = None
        if result:
            if isinstance(result, dict):
                config_params = result.get('config_params') or result.get(list(result.keys())[0])
            else:
                config_params = result[0] if len(result) > 0 else None
        
        if config_params:
            # 餈????隞?Ⅳ
            return jsonify({
                'success': True,
                'config_params': config_params
            })
        else:
            # 餈?暺??
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
        return jsonify({'success': False, 'error': f'?脣??蔭憭望?: {str(e)}'})

@app.route('/admin/user-sessions')
def admin_user_sessions():
    """蝞∠??∠?嗆?閰梁??""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    user_role = session.get('role')
    if user_role not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    return render_template('admin/user_sessions.html')

# ========== ??? ==========
if __name__ == '__main__':
    # ?????澈
    init_database()
    
    # ?璅∪???嚗ythonAnywhere ? WSGI嚗?
    app.run(debug=True, host='0.0.0.0', port=5000)

