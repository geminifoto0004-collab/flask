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
from blueprints.order_cloud_bp import order_cloud_bp
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
app.register_blueprint(order_cloud_bp)

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
        if password_hash != stored_password_hash:
            conn.close()
            return jsonify({'success': False, 'error': '密碼錯誤'})
        
        # 查詢用戶的服務授權
        cursor.execute('''
            SELECT us.*, s.name as service_name, s.description as service_description
            FROM user_services us
            JOIN services s ON us.service_id = s.id
            WHERE us.user_id = ? AND us.status = 'active'
        ''', (user_id,))
        user_services = cursor.fetchall()
        conn.close()
        
        # 檢查服務授權是否有效
        active_services = []
        for service in user_services:
            # 處理返回格式
            if isinstance(service, dict):
                end_date = service['end_date']
                service_name = service['service_name']
                service_description = service['service_description']
            else:
                end_date = service[5]  # end_date 索引
                service_name = service[-2]  # service_name
                service_description = service[-1]  # service_description
            
            if end_date:
                if isinstance(end_date, str):
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                else:
                    end_date_obj = end_date
                
                if end_date_obj >= get_chile_time_naive().date():
                    active_services.append({
                        'name': service_name,
                        'description': service_description,
                        'end_date': str(end_date)
                    })
            else:
                # 無結束日期，視為永久授權
                active_services.append({
                    'name': service_name,
                    'description': service_description,
                    'end_date': None
                })
        
        if not active_services:
            return jsonify({'success': False, 'error': '沒有有效的服務授權'})
        
        return jsonify({
            'success': True,
            'message': '授權驗證成功',
            'user_type': user_role,
            'services': active_services
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# NOTE: remainder of app.py unchanged in main branch.