"""
Flask ?ˆæ?ç®¡ç?ç³»çµ± - ä¸»æ??¨å…¥??
?Ÿèƒ½ï¼šç®¡?†å“¡?»å…¥?æ?æ¬Šç®¡?†ã€API ?¥è©¢
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import hashlib
import sqlite3
from datetime import datetime
from functools import wraps
from utils.time_utils import get_chile_time_naive

# å°å…¥?ç½®?Œè??™åº«
from config import config, admin_config, license_config, feature_flags
from database import get_db_connection, init_database, get_lastrowid, get_cursor, get_row_dict
from services import container_iti_service

# å°å…¥ Blueprint
from blueprints.user_auth_bp import user_auth_bp
from blueprints.api_auth_bp import api_auth_bp
from blueprints.monitor_bp import monitor_bp
from blueprints.container_bp import container_bp
from services.config_service import config_service

# å°å…¥?µä»¶ä»?? Blueprintï¼ˆPythonAnywhere ç«¯ä½¿?¨ï??¯é¸ï¼?
# å¦‚æ?è¦åœ¨ PythonAnywhere ä¸Šä½¿?¨ä»£?†å??½ï??–æ?ä¸‹é¢?„è¨»??
from services.email_proxy import email_proxy_bp


# ========== Flask ?‰ç”¨?å???==========
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = config.PERMANENT_SESSION_LIFETIME

# è¨»å? Blueprint
app.register_blueprint(user_auth_bp)
app.register_blueprint(api_auth_bp)
app.register_blueprint(monitor_bp)
app.register_blueprint(container_bp)

# è¨»å??µä»¶ä»?? Blueprintï¼ˆPythonAnywhere ç«¯ä½¿?¨ï??¯é¸ï¼?
# å¦‚æ?è¦åœ¨ PythonAnywhere ä¸Šä½¿?¨ä»£?†å??½ï??–æ?ä¸‹é¢?„è¨»??
app.register_blueprint(email_proxy_bp)

# ========== ?ªå??å??–è??™åº« ==========
# ?¨æ??¨å??•æ??ªå??å??–è??™åº«ï¼ˆé©?¨æ–¼ Render ç­‰ç??¢ç’°å¢ƒï?
# ä½¿ç”¨ before_request ä½†åª?·è?ä¸€æ¬?
_database_initialized = False

@app.before_request
def initialize_database():
    """?¨é?æ¬¡è?æ±‚å??å??–è??™åº«"""
    global _database_initialized
    if not _database_initialized:
        try:
            init_database()
            print("??è³‡æ?åº«è‡ª?•å?å§‹å?å®Œæ?")
            _database_initialized = True
        except Exception as e:
            import traceback
            print(f"? ï?  è³‡æ?åº«å?å§‹å?å¤±æ?: {e}")
            print(f"   è©³ç´°?¯èª¤: {traceback.format_exc()}")
            # ä¸é˜»æ­¢æ??¨å??•ï?è®“ç”¨?¶å¯ä»¥è¨ª?éŒ¯èª¤é???
            _database_initialized = True  # æ¨™è??ºå·²?—è©¦ï¼Œé¿?é?è¤‡å?è©?


# ========== ?»å…¥é©—è?è£é£¾??==========
def login_required(f):
    """?»å…¥é©—è?è£é£¾??""
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





# ========== API ç«¯é?ï¼šæ?æ¬Šæª¢??==========
@app.route('/api/check-license', methods=['POST'])
def api_check_license():
    """APIç«¯é?ï¼šæª¢?¥ç”¨?¶æ?æ¬Šç???""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'success': False, 'error': 'è«‹æ?ä¾›éƒµç®±å?å¯†ç¢¼'})
        
        # é©—è??¨æˆ¶?»å…¥
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?ªå?æª¢æŸ¥è¶…ç?ç®¡ç??¡å¸³??
        if email == admin_config.SUPER_ADMIN_EMAIL:
            if password == admin_config.SUPER_ADMIN_PASSWORD:
                conn.close()
                return jsonify({
                    'success': True, 
                    'message': 'è¶…ç?ç®¡ç??¡æ?æ¬Šé?è­‰æ???,
                    'user_type': admin_config.SUPER_ADMIN_ROLE,
                    'services': [{'name': 'è¶…ç?ç®¡ç??¡æ???, 'status': 'active', 'end_date': '2099-12-31'}]
                })
            else:
                conn.close()
                return jsonify({'success': False, 'error': 'è¶…ç?ç®¡ç??¡å?ç¢¼éŒ¯èª?})
        
        # æª¢æŸ¥?®é€šç”¨??
        cursor.execute('SELECT id, password_hash, role FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return jsonify({'success': False, 'error': '?¨æˆ¶ä¸å???})
        
        # ?•ç?è¿”å??¼å?ï¼ˆå¯?½æ˜¯å­—å…¸?–å?çµ„ï?
        if isinstance(user, dict):
            user_id = user['id']
            stored_password_hash = user['password_hash']
            user_role = user['role']
        else:
            user_id = user[0]
            stored_password_hash = user[1]
            user_role = user[2]
        
        # é©—è?å¯†ç¢¼
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if stored_password_hash != password_hash:
            conn.close()
            return jsonify({'success': False, 'error': 'å¯†ç¢¼?¯èª¤'})
        
        # ?²å??¨æˆ¶?å?
        cursor.execute('''
            SELECT us.*, s.name as service_name, s.description
            FROM user_services us
            JOIN services s ON us.service_id = s.id
            WHERE us.user_id = ? AND us.status = 'active'
        ''', (user_id,))
        services = cursor.fetchall()
        
        # æª¢æŸ¥?å??¯å¦?æ?
        valid_services = []
        current_date = get_chile_time_naive().date()
        
        for service in services:
            # ?•ç?è¿”å??¼å?ï¼ˆå¯?½æ˜¯å­—å…¸?–å?çµ„ï?
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
                'message': '?ˆæ?é©—è??å?',
                'user_type': 'user',
                'services': valid_services
            })
        else:
            return jsonify({
                'success': False, 
                'error': 'æ²’æ??‰æ??„æ??™æ?æ¬Šæ??å?å·²é???
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': f'ç³»çµ±?¯èª¤: {str(e)}'})

# ========== è·¯ç”±ï¼šçµ±ä¸€?»å…¥/?»å‡º ==========
@app.route('/login', methods=['GET', 'POST'])
def login():
    """çµ±ä??»å…¥?¥å£"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        if not email or not password:
            return render_template('user/login.html', error='è«‹å¡«å¯«å??´ä¿¡??)
        
        # ?ªå?æª¢æŸ¥è¶…ç?ç®¡ç??¡å¸³??
        from config import admin_config
        print(f"?»å…¥?—è©¦: ?µç®±='{email}', å¯†ç¢¼='{password}'")
        print(f"Super Admin?ç½®: ?µç®±='{admin_config.SUPER_ADMIN_EMAIL}', å¯†ç¢¼='{admin_config.SUPER_ADMIN_PASSWORD}'")
        
        if email == admin_config.SUPER_ADMIN_EMAIL and password == admin_config.SUPER_ADMIN_PASSWORD:
            print("Super Admin?»å…¥?å?ï¼?)
            session['logged_in'] = True
            # å¾æ•¸?šåº«?²å?è¶…ç?ç®¡ç??¡ç?å¯¦é? user_idï¼Œå??œä?å­˜åœ¨?‡å‰µå»?
            conn = None
            try:
                conn = get_db_connection()
                cursor = get_cursor(conn)  # ä½¿ç”¨ get_cursor ä»¥æ”¯?ä??Œæ•¸?šåº«é¡å?
                cursor.execute('SELECT id, company_name FROM users WHERE email = ?', (admin_config.SUPER_ADMIN_EMAIL,))
                user_row = cursor.fetchone()
                
                if user_row:
                    # å¦‚æ??¸æ?åº«ä¸­å·²æ?ï¼Œä½¿?¨æ•¸?šåº«?„ID?Œå…¬?¸å?ç¨?
                    # ?•ç?ä¸å??¸æ?åº«è??æ ¼å¼ï?SQLite è¿”å??ƒç?ï¼ŒMySQL/TiDB è¿”å?å­—å…¸
                    if isinstance(user_row, dict):
                        session['user_id'] = user_row['id']
                        session['company_name'] = user_row.get('company_name')
                    else:
                        # ?•ç?è¿”å??¼å?ï¼ˆå¯?½æ˜¯å­—å…¸?–å?çµ„ï?
                        if isinstance(user_row, dict):
                            session['user_id'] = user_row['id']
                            session['company_name'] = user_row.get('company_name')
                        else:
                            session['user_id'] = user_row[0]
                            session['company_name'] = user_row[1] if len(user_row) > 1 and user_row[1] else None
                else:
                    # å¦‚æ??¸æ?åº«ä¸­æ²’æ?ï¼Œè‡ª?•å‰µå»ºè?ç´šç®¡?†å“¡?¨æˆ¶
                    print("? ï? ?¸æ?åº«ä¸­æ²’æ?è¶…ç?ç®¡ç??¡ï?æ­?œ¨?µå»º...")
                    from services.user_service import hash_password
                    password_hash = hash_password(admin_config.SUPER_ADMIN_PASSWORD)
                    cursor.execute('''
                        INSERT INTO users (username, email, password_hash, role, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (admin_config.SUPER_ADMIN_USERNAME, admin_config.SUPER_ADMIN_EMAIL, 
                          password_hash, admin_config.SUPER_ADMIN_ROLE, get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')))
                    session['user_id'] = get_lastrowid(cursor, conn)
                    conn.commit()
                    print(f"??è¶…ç?ç®¡ç??¡å‰µå»ºæ??Ÿï?user_id={session['user_id']}")
                    session['company_name'] = None  # ?°å‰µå»ºç??¨æˆ¶æ²’æ??¬å¸?ç¨±
                
                if conn:
                    conn.close()
            except Exception as e:
                import traceback
                print(f"???¸æ?åº«æ?ä½œå¤±?? {e}")
                print(f"   è©³ç´°?¯èª¤: {traceback.format_exc()}")
                # å¦‚æ??¸æ?åº«æ?ä½œå¤±?—ï?ä»ç„¶?è¨±?»å…¥ï¼ˆä½¿?¨é?èªå€¼ï?
                if 'user_id' not in session:
                    session['user_id'] = None  # ?¨æ?è¨­ç½®ï¼Œå?çºŒå¯?½é?è¦è???
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                # ç¹¼ç??·è?ï¼Œä??»æ­¢?»å…¥
            session['username'] = admin_config.SUPER_ADMIN_USERNAME
            session['email'] = admin_config.SUPER_ADMIN_EMAIL
            session['role'] = admin_config.SUPER_ADMIN_ROLE
            
            # ?µå»º?ƒè©±è¨˜é?ï¼ˆç”¨?¼æ?è©±ç›£?§ï?
            try:
                from blueprints.api_auth_bp import create_session, generate_session_token, get_device_info
                session_token = generate_session_token()
                device_info = get_device_info(request)
                success = create_session(session['user_id'], session_token, device_info, service_name="Web_Login")
                if success:
                    print(f"???µå»ºè¶…ç?ç®¡ç??¡ç¶²?ç™»?¥æ?è©±è??„æ???- ?¨æˆ¶ {session['user_id']}, service_name=Web_Login")
                else:
                    print(f"???µå»ºè¶…ç?ç®¡ç??¡ç¶²?ç™»?¥æ?è©±è??„å¤±??- ?¨æˆ¶ {session['user_id']}, create_sessionè¿”å?False")
            except ImportError as e:
                print(f"??å°å…¥?ƒè©±ç®¡ç??½æ•¸å¤±æ?: {e}")
            except Exception as e:
                import traceback
                print(f"???µå»º?ƒè©±è¨˜é?å¤±æ?ï¼ˆä?å½±éŸ¿?»å…¥ï¼? {e}")
                print(f"   è©³ç´°?¯èª¤: {traceback.format_exc()}")
            
            return redirect(url_for('admin_dashboard'))
        else:
            print("Super Admin?»å…¥å¤±æ?ï¼Œå?è©¦æ™®?šç”¨?¶é?è­?)
        
        # ä½¿ç”¨?¨æˆ¶?å?é©—è??®é€šç”¨??
        from services.user_service import verify_password
        success, result = verify_password(email, password)
        
        if success:
            session['logged_in'] = True
            session['user_id'] = result['id']
            session['username'] = result['username']
            session['email'] = result['email']
            session['role'] = result['role']
            
            # ?µå»º?ƒè©±è¨˜é?ï¼ˆç”¨?¼æ?è©±ç›£?§ï?
            try:
                from blueprints.api_auth_bp import create_session, generate_session_token, get_device_info
                session_token = generate_session_token()
                device_info = get_device_info(request)
                success = create_session(result['id'], session_token, device_info, service_name="Web_Login")
                if success:
                    print(f"???µå»ºç¶²é??»å…¥?ƒè©±è¨˜é??å? - ?¨æˆ¶ {result['id']}, service_name=Web_Login")
                else:
                    print(f"???µå»ºç¶²é??»å…¥?ƒè©±è¨˜é?å¤±æ? - ?¨æˆ¶ {result['id']}, create_sessionè¿”å?False")
            except ImportError as e:
                print(f"??å°å…¥?ƒè©±ç®¡ç??½æ•¸å¤±æ?: {e}")
            except Exception as e:
                import traceback
                print(f"???µå»º?ƒè©±è¨˜é?å¤±æ?ï¼ˆä?å½±éŸ¿?»å…¥ï¼? {e}")
                print(f"   è©³ç´°?¯èª¤: {traceback.format_exc()}")
            
            # ?¹æ?è§’è‰²?å??‘åˆ°ä¸å??é¢
            if result['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_auth.user_portal'))
        else:
            return render_template('user/login.html', error='Correo electrÃ³nico o contraseÃ±a incorrectos')
    
    return render_template('user/login.html')


@app.route('/logout')
def logout():
    """?»å‡º"""
    session.clear()
    return redirect(url_for('login'))


# ========== è·¯ç”±ï¼šç®¡?†å“¡?€è¡¨æ¿ ==========
@app.route('/admin')
@login_required
def admin_dashboard():
    """ç®¡ç??¡å?è¡¨æ¿"""
    if session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    try:
        from database import get_db_connection, get_cursor
        conn = get_db_connection()
        
        # ?²å??¨æˆ¶çµ±è?ï¼ˆä½¿??get_cursor ä»¥æ”¯?ä??Œæ•¸?šåº«é¡å?ï¼?
        cursor = get_cursor(conn)
        cursor.execute('SELECT COUNT(*) as total FROM users')
        result = cursor.fetchone()
        # ?•ç?ä¸å??¸æ?åº«è??æ ¼å¼?
        db_total_users = result['total'] if isinstance(result, dict) else result[0]
        
        cursor.execute('SELECT COUNT(*) as total FROM users WHERE role = ?', ('admin',))
        result = cursor.fetchone()
        db_admin_users = result['total'] if isinstance(result, dict) else result[0]
        
        cursor.execute('SELECT COUNT(*) as total FROM users WHERE role = ?', ('user',))
        result = cursor.fetchone()
        db_regular_users = result['total'] if isinstance(result, dict) else result[0]
        
        # ?…å«è¶…ç?ç®¡ç??¡ç?çµ±è?
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
        print(f"??ç®¡ç??¡å?è¡¨æ¿?¯èª¤: {e}")
        print(f"   è©³ç´°?¯èª¤: {traceback.format_exc()}")
        # è¿”å??¯èª¤?é¢?–é?å®šå??°ç™»??
        return render_template('admin/dashboard.html', 
                             total_users=0,
                             admin_users=0,
                             regular_users=0,
                             error=f"è³‡æ?åº«éŒ¯èª? {str(e)}")

@app.route('/admin/dashboard')
@login_required
def admin_dashboard_redirect():
    """?å??‘åˆ°adminä¸»é?"""
    return redirect(url_for('admin_dashboard'))


# ========== ?Šç??ˆæ?ç³»çµ±å·²ç§»?¤ï??¹ç”¨ services ??user_services ç³»çµ± ==========


# ========== APIï¼šæ?æ¬ŠæŸ¥è©¢ï?æ¡Œé¢ç¨‹å??¨ï?==========
@app.route('/licenses/check_license', methods=['GET'])
def check_license():
    """
    ?ˆæ??¥è©¢ API
    ?ƒæ•¸: rut (ä¾? 76315010-0)
    è¿”å?: JSON {rut, empresa, estado, fecha_expiracion}
    """
    rut = request.args.get('rut')
    
    if not rut:
        return jsonify({'error': 'ç¼ºå? RUT ?ƒæ•¸'}), 400
    
    try:
        conn = get_db_connection()
        license = conn.execute(
            'SELECT rut, empresa, status, expire_date FROM licenses WHERE rut=?',
            (rut,)
        ).fetchone()
        conn.close()
        
        if license:
            # æª¢æŸ¥?¯å¦?æ?
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
            return jsonify({'error': '?ˆæ?ä¸å???}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ========== ?¨æˆ¶ç®¡ç? ==========
@app.route('/admin/users')
def admin_users():
    """ç®¡ç??¡æŸ¥?‹æ??‰ç”¨??""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, role, created_at FROM users ORDER BY created_at DESC')
    users_rows = cursor.fetchall()
    # å°‡Rowå°è±¡è½‰æ??ºå??¸å?è¡?
    users = [dict(row) for row in users_rows]
    
    # æ·»å?è¶…ç?ç®¡ç??¡åˆ°?—è¡¨?‚éƒ¨ï¼ˆå??ç½®?‡ä»¶?²å?ï¼Œä?å¾è??™åº«ï¼?
    super_admin = {
        'id': admin_config.SUPER_ADMIN_USERNAME,
        'username': admin_config.SUPER_ADMIN_USERNAME,
        'email': admin_config.SUPER_ADMIN_EMAIL,
        'role': admin_config.SUPER_ADMIN_ROLE,
        'created_at': 'ç³»çµ±?µå»º'
    }
    users.insert(0, super_admin)
    
    conn.close()
    
    return render_template('admin/users.html', users=users, super_admin_role=admin_config.SUPER_ADMIN_ROLE)

@app.route('/admin/users/<int:user_id>/role', methods=['POST'])
def update_user_role(user_id):
    """?´æ–°?¨æˆ¶è§’è‰²"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'error': 'æ¬Šé?ä¸è¶³'}), 403
    new_role = request.form.get('role')
    
    if not user_id or not new_role:
        return jsonify({'error': '?ƒæ•¸ä¸å???}), 400
    
    if new_role not in ['user', 'admin']:
        return jsonify({'error': '?¡æ??„è???}), 400
    
    # æª¢æŸ¥?¯å¦?ºè?ç´šç®¡?†å“¡ï¼ˆè?ç´šç®¡?†å“¡ä¸èƒ½è¢«ä¿®?¹ï?
    if str(user_id) == admin_config.SUPER_ADMIN_USERNAME:
        return jsonify({'error': 'è¶…ç?ç®¡ç??¡ç?è§’è‰²?¡æ?ä¿®æ”¹'}), 400
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # æª¢æŸ¥?¨æˆ¶?¯å¦å­˜åœ¨
    cursor.execute('SELECT id, role FROM users WHERE id=?', (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return jsonify({'error': '?¨æˆ¶ä¸å???}), 404
    
    # æª¢æŸ¥æ¬Šé?ï¼šåª?‰è?ç´šç®¡?†å“¡?¯ä»¥?ç?ç®¡ç???
    current_user_role = session.get('role')
    
    # å¦‚æ??¯è?å°‡ç®¡?†å“¡?ç??ºæ™®?šç”¨??
    if user['role'] == 'admin' and new_role == 'user':
        # ?ªæ?è¶…ç?ç®¡ç??¡å¯ä»¥é?ç´šç®¡?†å“¡
        if current_user_role != admin_config.SUPER_ADMIN_ROLE:
            conn.close()
            return jsonify({
                'error': 'æ¬Šé?ä¸è¶³ï¼šåª?‰è?ç´šç®¡?†å“¡?¯ä»¥å°‡ç®¡?†å“¡?ç??ºæ™®?šç”¨??
            }), 403
        
        # è¶…ç?ç®¡ç??¡å¯ä»¥éš¨?é?ç´šç®¡?†å“¡ï¼Œå??ºè?ç´šç®¡?†å“¡æ°¸é?å­˜åœ¨
    
    # ?´æ–°è§’è‰²
    cursor.execute('UPDATE users SET role=? WHERE id=?', (new_role, user_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'è§’è‰²?´æ–°?å?'})

@app.route('/admin/services')
def admin_services():
    """?å?ç®¡ç??é¢"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM services ORDER BY created_at DESC')
    services_rows = cursor.fetchall()
    # å°‡Rowå°è±¡è½‰æ??ºå??¸å?è¡?
    services = [dict(row) for row in services_rows]
    conn.close()
    
    return render_template('admin/services.html', services=services)

@app.route('/admin/services', methods=['POST'])
def create_service():
    """?µå»º?°æ???""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    name = request.form.get('name')
    description = request.form.get('description', '')
    price = request.form.get('price')
    duration_days = request.form.get('duration_days')
    status = request.form.get('status', 'active')
    
    if not all([name, price, duration_days]):
        return jsonify({'success': False, 'error': 'è«‹å¡«å¯«æ??‰å?å¡«æ?ä½?})
    
    try:
        price = float(price)
        duration_days = int(duration_days)
    except ValueError:
        return jsonify({'success': False, 'error': '?¹æ ¼?Œæ??ˆæ?å¿…é??ºæ•¸å­?})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # ?²å??ç½® JSONï¼ˆå??œæ??„è©±ï¼?
        config_json = request.form.get('config_json', '')
        
        cursor.execute('''
            INSERT INTO services (name, description, price, duration_days, status, config_json)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, description, price, duration_days, status, config_json))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '?å??µå»º?å?'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?µå»ºå¤±æ?: {str(e)}'})

@app.route('/admin/services/<int:service_id>', methods=['GET'])
def get_service(service_id):
    """?²å??®å€‹æ??™ä¿¡??""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM services WHERE id = ?', (service_id,))
    service = cursor.fetchone()
    conn.close()
    
    if service:
        return jsonify({'success': True, 'service': dict(service)})
    else:
        return jsonify({'success': False, 'error': '?å?ä¸å???})

@app.route('/admin/services/<int:service_id>', methods=['PUT'])
def update_service(service_id):
    """?´æ–°?å?"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    name = request.form.get('name')
    description = request.form.get('description', '')
    price = request.form.get('price')
    duration_days = request.form.get('duration_days')
    status = request.form.get('status', 'active')
    
    if not all([name, price, duration_days]):
        return jsonify({'success': False, 'error': 'è«‹å¡«å¯«æ??‰å?å¡«æ?ä½?})
    
    try:
        price = float(price)
        duration_days = int(duration_days)
    except ValueError:
        return jsonify({'success': False, 'error': '?¹æ ¼?Œæ??ˆæ?å¿…é??ºæ•¸å­?})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # æª¢æŸ¥?å??¯å¦å­˜åœ¨
        cursor.execute('SELECT id FROM services WHERE id = ?', (service_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': '?å?ä¸å???})
        
        cursor.execute('''
            UPDATE services 
            SET name = ?, description = ?, price = ?, duration_days = ?, status = ?
            WHERE id = ?
        ''', (name, description, price, duration_days, status, service_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '?å??´æ–°?å?'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?´æ–°å¤±æ?: {str(e)}'})

@app.route('/admin/services/<int:service_id>', methods=['DELETE'])
def delete_service(service_id):
    """?ªé™¤?å?"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # æª¢æŸ¥?å??¯å¦å­˜åœ¨
        cursor.execute('SELECT name FROM services WHERE id = ?', (service_id,))
        service = cursor.fetchone()
        
        if not service:
            return jsonify({'success': False, 'error': '?å?ä¸å???})
        
        # æª¢æŸ¥?¯å¦?‰ç”¨?¶æ­£?¨ä½¿?¨æ­¤?å?
        cursor.execute('SELECT COUNT(*) FROM user_services WHERE service_id = ?', (service_id,))
        user_count_result = cursor.fetchone()
        user_count = user_count_result[0] if isinstance(user_count_result, tuple) else (user_count_result.get('COUNT(*)') or user_count_result.get(list(user_count_result.keys())[0]) if user_count_result else 0)
        
        if user_count > 0:
            return jsonify({'success': False, 'error': f'?¡æ??ªé™¤ï¼šæ? {user_count} ?‹ç”¨?¶æ­£?¨ä½¿?¨æ­¤?å?'})
        
        # ?ªé™¤?å?
        cursor.execute('DELETE FROM services WHERE id = ?', (service_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'?å? {service["name"]} å·²åˆª??})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?ªé™¤å¤±æ?: {str(e)}'})

@app.route('/admin/user-services')
def admin_user_services():
    """?¨æˆ¶?å?ç®¡ç??é¢"""
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
    # å°‡Rowå°è±¡è½‰æ??ºå??¸å?è¡?
    user_services = [dict(row) for row in user_services_rows]
    conn.close()
    
    return render_template('admin/user_services.html', user_services=user_services)

@app.route('/admin/user-services/by-email/<email>')
def get_user_services_by_email(email):
    """?¹æ?email?¥è©¢?¨æˆ¶?å?ï¼ˆAPIï¼?""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
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
    """?²å??¨æˆ¶å¯†ç¢¼ä¿¡æ¯"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # ?²å??¨æˆ¶ä¿¡æ¯
    cursor.execute('SELECT username, password_hash FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return jsonify({
            'success': True,
            'username': user['username'],
            'password': 'å¯†ç¢¼å·²å?å¯†å???,
            'password_hash': user['password_hash'][:16] + '...',  # é¡¯ç¤º?¨å?hash
            'note': 'ç³»çµ±ä½¿ç”¨SHA256? å?å­˜å„²å¯†ç¢¼ï¼Œç„¡æ³•æŸ¥?‹æ???
        })
    else:
        return jsonify({'success': False, 'error': '?¨æˆ¶ä¸å???})

@app.route('/admin/users/<int:user_id>/services')
def get_user_services(user_id):
    """?²å??¨æˆ¶?„æ??™å?è¡?""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
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
    """?ºç”¨?¶å??æ???""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    user_id = request.form.get('user_id')
    service_id = request.form.get('service_id')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    auto_calculate = request.form.get('auto_calculate', 'true') == 'true'
    
    if not all([user_id, service_id, start_date]):
        return jsonify({'success': False, 'error': 'è«‹å¡«å¯«ç”¨?¶ã€æ??™å??‹å??¥æ?'})
    
    from database import get_db_connection
    from datetime import datetime, timedelta
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # æª¢æŸ¥?¨æˆ¶?Œæ??™æ˜¯?¦å???
        cursor.execute('SELECT id FROM users WHERE id = ?', (user_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': '?¨æˆ¶ä¸å???})
        
        cursor.execute('SELECT id, duration_days FROM services WHERE id = ?', (service_id,))
        service = cursor.fetchone()
        if not service:
            return jsonify({'success': False, 'error': '?å?ä¸å???})
        
        # ?•ç?çµæ??¥æ?
        if auto_calculate and not end_date:
            # ?ªå?è¨ˆç?çµæ??¥æ?
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = start_dt + timedelta(days=service['duration_days'])
            end_date = end_dt.strftime('%Y-%m-%d')
        elif not end_date:
            return jsonify({'success': False, 'error': 'è«‹å¡«å¯«ç??Ÿæ—¥?Ÿæ??¸æ??ªå?è¨ˆç?'})
        
        # é©—è??¥æ??ˆç???
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        if end_dt <= start_dt:
            return jsonify({'success': False, 'error': 'çµæ??¥æ?å¿…é??šæ–¼?‹å??¥æ?'})
        
        # æª¢æŸ¥?¯å¦è¶…é??å?æ¨™æ??Ÿé?
        actual_days = (end_dt - start_dt).days
        if actual_days > service['duration_days']:
            return jsonify({
                'success': False, 
                'error': f'?å??Ÿé?ä¸èƒ½è¶…é?æ¨™æ??Ÿé? {service["duration_days"]} å¤?
            })
        
        # ?’å…¥?¨æˆ¶?å?è¨˜é?
        cursor.execute('''
            INSERT INTO user_services (user_id, service_id, start_date, end_date, status)
            VALUES (?, ?, ?, ?, 'active')
        ''', (user_id, service_id, start_date, end_date))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'?å??†é??å?ï¼æ??ˆæ?ï¼š{start_date} ??{end_date}ï¼ˆ{actual_days}å¤©ï?'
        })
        
    except ValueError as e:
        conn.close()
        return jsonify({'success': False, 'error': 'Formato de fecha incorrecto, use el formato YYYY-MM-DD'})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?†é?å¤±æ?: {str(e)}'})

@app.route('/admin/user-services/<int:user_service_id>', methods=['DELETE'])
def delete_user_service(user_service_id):
    """?ªé™¤?¨æˆ¶?å?"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # æª¢æŸ¥?¨æˆ¶?å??¯å¦å­˜åœ¨
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
        
        # ?ªé™¤?¨æˆ¶?å?è¨˜é?
        cursor.execute('DELETE FROM user_services WHERE id = ?', (user_service_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'?¨æˆ¶ {user_service["username"]} ?„æ???{user_service["service_name"]} å·²åˆª??
        })
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?ªé™¤å¤±æ?: {str(e)}'})

@app.route('/admin/user-services/<int:user_service_id>', methods=['GET'])
def get_user_service(user_service_id):
    """?²å??®å€‹ç”¨?¶æ??™ä¿¡??""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
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
        # è½‰æ??ºå???
        user_service_dict = dict(user_service)
        
        # å¦‚æ??‰é?ç½®ï??—è©¦?¾åˆ°å°æ??„å??¸é?ç½®å?ç¨?
        if user_service_dict.get('config_json'):
            cursor.execute('''
                SELECT param_name FROM service_versions 
                WHERE service_name = ? AND param_content = ?
            ''', (user_service_dict['service_name'], user_service_dict['config_json']))
            
            param_result = cursor.fetchone()
            if param_result:
                # ?•ç?è¿”å??¼å?ï¼ˆå¯?½æ˜¯å­—å…¸?–å?çµ„ï?
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
    """?´æ–°?¨æˆ¶?å?"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    # ?¯æ? JSON ??form ?¸æ?
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
        return jsonify({'success': False, 'error': 'è«‹å¡«å¯«é?å§‹æ—¥?Ÿå?çµæ??¥æ?'})
    
    from database import get_db_connection
    from datetime import datetime
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # æª¢æŸ¥?¨æˆ¶?å??¯å¦å­˜åœ¨
        cursor.execute('SELECT id FROM user_services WHERE id = ?', (user_service_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': '?¨æˆ¶?å?ä¸å???})
        
        # é©—è??¥æ??¼å??Œå??†æ€?
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        if end_dt <= start_dt:
            return jsonify({'success': False, 'error': 'çµæ??¥æ?å¿…é??šæ–¼?‹å??¥æ?'})
        
        # å¦‚æ??‡å?äº†å??¸é?ç½®ï??²å??ç½®?§å®¹
        config_json = None
        if param_config:
            cursor.execute('SELECT param_content FROM service_versions WHERE service_name = "Zofri_Compra_Venta" AND param_name = ?', (param_config,))
            config_result = cursor.fetchone()
            if config_result:
                # ?•ç?è¿”å??¼å?ï¼ˆå¯?½æ˜¯å­—å…¸?–å?çµ„ï?
                if isinstance(config_result, dict):
                    config_json = config_result.get('param_content') or config_result.get(list(config_result.keys())[0])
                else:
                    config_json = config_result[0]  # ?™è£¡ä¿å??„æ˜¯?Ÿå??ƒæ•¸ä»?¢¼
        
        # ?´æ–°?¨æˆ¶?å?
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
            'message': f'?¨æˆ¶?å??´æ–°?å?ï¼æ??ˆæ?: {start_date} ??{end_date} ({actual_days} å¤?'
        })
        
    except ValueError as e:
        conn.close()
        return jsonify({'success': False, 'error': '?¥æ??¼å?ä¸æ­£ç¢ºï?è«‹ä½¿??YYYY-MM-DD ?¼å?'})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?´æ–°å¤±æ?: {str(e)}'})

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """?ªé™¤?¨æˆ¶"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    # æª¢æŸ¥?¯å¦?ºè?ç´šç®¡?†å“¡ï¼ˆè?ç´šç®¡?†å“¡ä¸èƒ½è¢«åˆª?¤ï?
    if str(user_id) == admin_config.SUPER_ADMIN_USERNAME:
        return jsonify({'success': False, 'error': 'è¶…ç?ç®¡ç??¡ç„¡æ³•è¢«?ªé™¤'})
    
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # æª¢æŸ¥?¨æˆ¶?¯å¦å­˜åœ¨
        cursor.execute('SELECT username, role FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'error': '?¨æˆ¶ä¸å???})
        
        # å¦‚æ?è¦åˆª?¤ç??¯ç®¡?†å“¡ï¼Œæª¢?¥æ˜¯?¦æ?å°è‡´æ²’æ?ç®¡ç???
        if user['role'] == 'admin':
            # æª¢æŸ¥?¶å?ç®¡ç??¡ç¸½?¸ï?ä¸å??¬è?ç´šç®¡?†å“¡ï¼?
            cursor.execute('SELECT COUNT(*) as admin_count FROM users WHERE role="admin"')
            admin_count = cursor.fetchone()['admin_count']
            
            # å¦‚æ??ªæ?ä¸€?‹ç®¡?†å“¡ï¼Œä??è¨±?ªé™¤ï¼ˆè?ç´šç®¡?†å“¡æ°¸é?å­˜åœ¨ï¼?
            if admin_count <= 1:
                conn.close()
                return jsonify({
                    'success': False, 
                    'error': '?¡æ??ªé™¤ï¼šç³»çµ±å??ˆè‡³å°‘ä??™ä??‹æ™®?šç®¡?†å“¡?‚è?ç´šç®¡?†å“¡æ°¸é?å­˜åœ¨ï¼Œä?å»ºè­°ä¿ç??³å?ä¸€?‹æ™®?šç®¡?†å“¡??
                })
        
        # ?ªé™¤?¨æˆ¶?„æ??‰ç›¸?œæ•¸??
        cursor.execute('DELETE FROM user_services WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM verification_codes WHERE email = (SELECT email FROM users WHERE id = ?)', (user_id,))
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'?¨æˆ¶ {user["username"]} å·²åˆª??})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?ªé™¤å¤±æ?: {str(e)}'})

@app.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
def reset_user_password(user_id):
    """?ç½®?¨æˆ¶å¯†ç¢¼"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    new_password = request.form.get('new_password')
    if not new_password:
        return jsonify({'success': False, 'error': 'è«‹è¼¸?¥æ–°å¯†ç¢¼'})
    
    from utils.validators import validate_password
    valid, msg = validate_password(new_password)
    if not valid:
        return jsonify({'success': False, 'error': msg})
    
    from database import get_db_connection
    from services.user_service import hash_password
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # æª¢æŸ¥?¨æˆ¶?¯å¦å­˜åœ¨
        cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'error': '?¨æˆ¶ä¸å???})
        
        # ?´æ–°å¯†ç¢¼
        password_hash = hash_password(new_password)
        cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, user_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'?¨æˆ¶ {user["username"]} ?„å?ç¢¼å·²?ç½®',
            'new_password': new_password  # è¿”å??°å?ç¢¼ä?ç®¡ç??¡å??¥ç”¨??
        })
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'?ç½®å¤±æ?: {str(e)}'})

@app.route('/admin/database')
def admin_database():
    """ç®¡ç??¡è??™åº«?è¦½"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    try:
        from database import get_db_connection, get_cursor, get_table_names
        conn = get_db_connection()
        cursor = get_cursor(conn)  # ä½¿ç”¨ get_cursor ä»¥æ”¯?ä??Œæ•¸?šåº«é¡å?
        
        # ?²å??€?‰è¡¨?ï?ä½¿ç”¨çµ±ä??„å‡½?¸ï?
        table_names = get_table_names(cursor)
        tables = [{'name': name} for name in table_names]
        
        # ?²å?æ¯å€‹è¡¨?„æ•¸??
        table_data = {}
        for table_name in table_names:
            try:
                cursor.execute(f"SELECT * FROM {table_name}")
                rows = cursor.fetchall()
                # ?•ç?ä¸å??¸æ?åº«è??æ ¼å¼?
                if rows and isinstance(rows[0], dict):
                    table_data[table_name] = rows
                else:
                    # SQLite è¿”å? Row å°è±¡ï¼Œé?è¦è???
                    table_data[table_name] = [dict(row) for row in rows]
            except Exception as e:
                print(f"?²å?è¡?{table_name} ?¸æ?å¤±æ?: {e}")
                table_data[table_name] = []
        
        conn.close()
        
        return render_template('admin/database.html', tables=tables, table_data=table_data)
        
    except Exception as e:
        import traceback
        print(f"è³‡æ?åº«ç€è¦½?¯èª¤: {e}")
        print(f"   è©³ç´°?¯èª¤: {traceback.format_exc()}")
        return render_template('admin/database.html', tables=[], table_data={}, error=str(e))


# ?Šç??ˆæ??ªé™¤APIå·²ç§»?¤ï??¹ç”¨?°ç??å?ç³»çµ±


# ========== é¦–é??å???==========
@app.route('/')
def index():
    """é¦–é??å??‘åˆ°ç®¡ç??¡ç™»??""
    if session.get('logged_in'):
        if session.get('role') in ['admin', admin_config.SUPER_ADMIN_ROLE]:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('user_auth.user_portal'))
    return redirect(url_for('login'))


# ========== ?¨æˆ¶?å??¸é?è·¯ç”± ==========
@app.route('/user/services')
def user_services():
    """?¨æˆ¶?å??é¢"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    return render_template('user/services.html')

@app.route('/user/services/api')
def user_services_api():
    """?²å??¶å??¨æˆ¶?„æ??™å?è¡¨ï?APIï¼?""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'è«‹å??»å…¥'})
    
    try:
        from database import get_db_connection
        from datetime import datetime
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?¹æ??¨æˆ¶ID?¥è©¢?å?
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
            # æª¢æŸ¥?å??¯å¦?Ÿç?æ¿€æ´»ï?status ??active ä¸?end_date ?ªé??Ÿï?
            if service.get('status') == 'active' and service.get('end_date'):
                # æ¯”è??¥æ?å­—ç¬¦ä¸²ï??¼å?ï¼šYYYY-MM-DDï¼?
                if service['end_date'] < current_date:
                    # å¦‚æ??æ?äº†ï?å°‡ç??‹æ”¹??inactive
                    service['status'] = 'inactive'
                    service['is_expired'] = True
            services.append(service)
        
        conn.close()
        
        return jsonify({'success': True, 'services': services})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error al cargar servicios: {str(e)}'})


@app.route('/admin/user-services/<int:user_service_id>/config', methods=['GET'])
def get_user_service_config(user_service_id):
    """?²å??¨æˆ¶?å??ç½®"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?²å??¨æˆ¶?å??ç½®
        cursor.execute("""
            SELECT us.config_json 
            FROM user_services us
            WHERE us.id = ?
        """, (user_service_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        # ?•ç?è¿”å??¼å?ï¼ˆå¯?½æ˜¯å­—å…¸?–å?çµ„ï?
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
            # è¿”å?é»˜è??ç½®
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
        return jsonify({'success': False, 'error': f'?²å??ç½®å¤±æ?: {str(e)}'})

@app.route('/admin/user-services/<int:user_service_id>/config', methods=['POST'])
def save_user_service_config(user_service_id):
    """ä¿å??¨æˆ¶?å??ç½®"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    try:
        data = request.get_json()
        config = data.get('config', {})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?´æ–°?¨æˆ¶?å??ç½®
        import json
        cursor.execute("""
            UPDATE user_services 
            SET config_json = ?
            WHERE id = ?
        """, (json.dumps(config, ensure_ascii=False), user_service_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '?ç½®ä¿å??å?'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'ä¿å??ç½®å¤±æ?: {str(e)}'})

@app.route('/admin/services/<int:service_id>/param', methods=['POST'])
def save_service_param(service_id):
    """ä¿å??å??ƒæ•¸?ç½®"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    try:
        data = request.get_json()
        param_name = data.get('param_name', '').strip()
        param_content = data.get('param_content', '').strip()
        
        if not param_name:
            return jsonify({'success': False, 'error': '?ƒæ•¸?ç¨±ä¸èƒ½?ºç©º'})
        
        if not param_content:
            return jsonify({'success': False, 'error': '?ƒæ•¸?§å®¹ä¸èƒ½?ºç©º'})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?²å??å??ç¨±
        cursor.execute("SELECT name FROM services WHERE id = ?", (service_id,))
        service = cursor.fetchone()
        if not service:
            conn.close()
            return jsonify({'success': False, 'error': '?å?ä¸å???})
        
        service_name = service[0]
        
        # æª¢æŸ¥?ƒæ•¸?ç¨±?¯å¦å·²å???
        cursor.execute("SELECT id FROM service_versions WHERE service_name = ? AND param_name = ?", (service_name, param_name))
        existing = cursor.fetchone()
        
        if existing:
            # ?´æ–°?¾æ??ç½®
            cursor.execute("""
                UPDATE service_versions 
                SET param_content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE service_name = ? AND param_name = ?
            """, (param_content, service_name, param_name))
        else:
            # ?µå»º?°é?ç½?
            cursor.execute("""
                INSERT INTO service_versions (service_name, param_name, param_content)
                VALUES (?, ?, ?)
            """, (service_name, param_name, param_content))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '?ƒæ•¸?ç½®ä¿å??å?'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'ä¿å??ƒæ•¸å¤±æ?: {str(e)}'})

@app.route('/admin/services/<int:service_id>/versions', methods=['GET'])
def get_service_versions(service_id):
    """?²å??å??„æ??‰å??¸é?ç½?""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?²å??å??ç¨±
        cursor.execute("SELECT name FROM services WHERE id = ?", (service_id,))
        service = cursor.fetchone()
        if not service:
            conn.close()
            return jsonify({'success': False, 'error': '?å?ä¸å???})
        
        service_name = service[0]
        
        # ?²å??€?‰å??¸é?ç½?
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
        return jsonify({'success': False, 'error': f'?²å??ƒæ•¸å¤±æ?: {str(e)}'})

@app.route('/admin/services/versions', methods=['GET'])
def get_service_versions_by_name():
    """?šé??å??ç¨±?²å??ƒæ•¸?ç½®"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    service_name = request.args.get('service_name')
    if not service_name:
        return jsonify({'success': False, 'error': 'è«‹æ?ä¾›æ??™å?ç¨?})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?²å??€?‰å??¸é?ç½?
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
        return jsonify({'success': False, 'error': f'?²å??ƒæ•¸?ç½®å¤±æ?: {str(e)}'})

@app.route('/admin/services/<int:service_id>/param/<int:param_id>', methods=['DELETE'])
def delete_service_param(service_id, param_id):
    """?ªé™¤?å??„å–®?‹å??¸é?ç½?""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?²å??å??ç¨±
        cursor.execute("SELECT name FROM services WHERE id = ?", (service_id,))
        service = cursor.fetchone()
        if not service:
            conn.close()
            return jsonify({'success': False, 'error': '?å?ä¸å???})
        
        service_name = service[0]
        
        # ?ªé™¤?‡å??„å??¸é?ç½?
        cursor.execute("DELETE FROM service_versions WHERE id = ? AND service_name = ?", (param_id, service_name))
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({'success': False, 'error': '?ƒæ•¸?ç½®ä¸å???})
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '?ƒæ•¸?ç½®?ªé™¤?å?'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'?ªé™¤?ƒæ•¸å¤±æ?: {str(e)}'})

@app.route('/admin/services/<int:service_id>/config', methods=['GET'])
def get_service_config(service_id):
    """?²å??å???config_json ?ç½®"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
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
        
        # ?•ç?è¿”å??¼å?ï¼ˆå¯?½æ˜¯å­—å…¸?–å?çµ„ï?
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
            # è¿”å?é»˜è??ç½®
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
        return jsonify({'success': False, 'error': f'?²å??ç½®å¤±æ?: {str(e)}'})

@app.route('/admin/services/<int:service_id>/config', methods=['POST'])
def save_service_config(service_id):
    """ä¿å??å???config_json ?ç½®"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
    try:
        data = request.get_json()
        config = data.get('config', {})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?´æ–°?å??ç½®
        import json
        cursor.execute("""
            UPDATE services 
            SET config_json = ?
            WHERE id = ?
        """, (json.dumps(config, ensure_ascii=False), service_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '?å??ç½®ä¿å??å?'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'ä¿å??ç½®å¤±æ?: {str(e)}'})

@app.route('/admin/services/templates', methods=['GET'])
def get_config_templates():
    """?²å??ƒæ•¸æ¨¡æ¿?—è¡¨"""
    if not session.get('logged_in') or session.get('role') not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return jsonify({'success': False, 'error': 'æ¬Šé?ä¸è¶³'})
    
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
                'name': template[1],  # version ä½œç‚ºæ¨¡æ¿?ç¨±
                'description': template[2]
            })
        
        return jsonify({'success': True, 'templates': template_list})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'?²å?æ¨¡æ¿å¤±æ?: {str(e)}'})

@app.route('/api/user-config', methods=['GET'])
def get_user_config():
    """?²å??¨æˆ¶?ç½®?ƒæ•¸ï¼ˆä?ä»?¢¼?»å…¥?‚ä½¿?¨ï?"""
    try:
        # å¾è?æ±‚é ­?²å??¨æˆ¶ä¿¡æ¯ï¼ˆé?è¦ä??„ä»£ç¢¼åœ¨?»å…¥?‚å‚³?ï?
        user_id = request.headers.get('X-User-ID')
        service_name = request.args.get('service_name', 'Zofri_Compra_Venta')
        
        if not user_id:
            return jsonify({'success': False, 'error': 'ç¼ºå??¨æˆ¶ID'})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?²å??¨æˆ¶?„æ??™é?ç½?
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
        
        # ?•ç?è¿”å??¼å?ï¼ˆå¯?½æ˜¯å­—å…¸?–å?çµ„ï?
        config_params = None
        if result:
            if isinstance(result, dict):
                config_params = result.get('config_params') or result.get(list(result.keys())[0])
            else:
                config_params = result[0] if len(result) > 0 else None
        
        if config_params:
            # è¿”å??Ÿå??ƒæ•¸ä»?¢¼
            return jsonify({
                'success': True,
                'config_params': config_params
            })
        else:
            # è¿”å?é»˜è??ƒæ•¸
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
        return jsonify({'success': False, 'error': f'?²å??ç½®å¤±æ?: {str(e)}'})

@app.route('/admin/user-sessions')
def admin_user_sessions():
    """ç®¡ç??¡ç”¨?¶æ?è©±ç›£??""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    user_role = session.get('role')
    if user_role not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
        return redirect(url_for('login'))
    
    return render_template('admin/user_sessions.html')

# ========== ?Ÿå??‰ç”¨ ==========
if __name__ == '__main__':
    # ?å??–è??™åº«
    init_database()
    
    # ?‹ç™¼æ¨¡å??‹è?ï¼ˆPythonAnywhere ?ƒç”¨ WSGIï¼?
    app.run(debug=True, host='0.0.0.0', port=5000)
