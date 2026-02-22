"""
API 認證 Blueprint
功能：為其他APP提供登入驗證、JWT token管理、用戶服務查詢API
"""

from flask import Blueprint, request, jsonify, session as flask_session
import hashlib
import jwt
import sqlite3
import secrets
import json
from datetime import datetime, timedelta
from functools import wraps
import pytz

from database import get_db_connection
from services.user_service import verify_password, get_user_by_email
from services.config_service import config_service
from config import config, admin_config
from utils.time_utils import get_chile_time, get_chile_time_naive

# ========== 會話管理工具函數 ==========

def generate_session_token():
    """生成唯一的會話令牌"""
    return secrets.token_urlsafe(32)

def get_client_ip(request):
    """獲取客戶端真實IP地址（支持反向代理）"""
    # 優先檢查 X-Forwarded-For（可能包含多個IP，取第一個）
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    
    # 檢查 X-Real-IP
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    
    # 檢查 CF-Connecting-IP（Cloudflare）
    if request.headers.get('CF-Connecting-IP'):
        return request.headers.get('CF-Connecting-IP')
    
    # 最後使用直接連接的IP
    return request.remote_addr

def get_device_info(request):
    """獲取設備信息"""
    user_agent = request.headers.get('User-Agent', 'Unknown')
    return {
        'user_agent': user_agent,
        'ip_address': get_client_ip(request),
        'timestamp': get_chile_time().isoformat()
    }

def create_session(user_id, session_token, device_info, service_name="Zofri_Compra_Venta"):
    """創建會話記錄"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        current_time = get_chile_time().replace(tzinfo=None)
        
        # 創建會話記錄
        cursor.execute("""
            INSERT INTO user_sessions (
                user_id, service_name, session_start, last_activity, 
                is_online, session_token, device_info
            ) VALUES (?, ?, ?, ?, 1, ?, ?)
        """, (user_id, service_name, current_time, current_time, 
              session_token, json.dumps(device_info)))
        
        conn.commit()
        conn.close()
        
        print(f"✅ 創建會話記錄成功 - 用戶 {user_id}, service_name={service_name}, session_token={session_token[:16]}...")
        return True
        
    except sqlite3.IntegrityError as e:
        # 可能是 session_token 重複
        print(f"❌ 創建會話失敗（完整性錯誤）: {e}, user_id={user_id}, service_name={service_name}")
        try:
            conn.close()
        except:
            pass
        return False
    except Exception as e:
        import traceback
        print(f"❌ 創建會話失敗: {e}, user_id={user_id}, service_name={service_name}")
        print(f"   詳細錯誤: {traceback.format_exc()}")
        try:
            conn.close()
        except:
            pass
        return False

def get_user_id_from_session_token(session_token):
    """從會話令牌獲取用戶ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT user_id FROM user_sessions 
            WHERE session_token = ?
        """, (session_token,))
        
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else None
        
    except Exception as e:
        print(f"❌ 獲取用戶ID失敗: {e}")
        return None

def update_user_heartbeat(user_id, service_name="Zofri_Compra_Venta", session_token=None):
    """更新用戶心跳檢測"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        current_time = get_chile_time().replace(tzinfo=None)
        
        # 更新或創建活動狀態記錄
        if session_token:
            # 使用會話令牌更新
            cursor.execute("""
                UPDATE user_sessions 
                SET last_activity = ?, is_online = 1
                WHERE user_id = ? AND service_name = ? AND session_token = ?
            """, (current_time, user_id, service_name, session_token))
            
            # 檢查是否成功更新
            if cursor.rowcount == 0:
                print(f"❌ 用戶 {user_id} 會話令牌無效或已失效")
                conn.close()
                return False
        else:
            # 傳統方式更新
            cursor.execute("""
                SELECT id FROM user_sessions 
                WHERE user_id = ? AND service_name = ?
            """, (user_id, service_name))
            
            existing_activity = cursor.fetchone()
            
            if existing_activity:
                cursor.execute("""
                    UPDATE user_sessions 
                    SET last_activity = ?, is_online = 1
                    WHERE user_id = ? AND service_name = ?
                """, (current_time, user_id, service_name))
            else:
                cursor.execute("""
                    INSERT INTO user_sessions (user_id, service_name, session_start, last_activity, is_online)
                    VALUES (?, ?, ?, ?, 1)
                """, (user_id, service_name, current_time, current_time))
        
        print(f"💓 用戶 {user_id} 心跳更新 - {current_time.strftime('%H:%M:%S')}")
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 心跳更新失敗: {e}")
        return False

def mark_user_offline(user_id, service_name="Zofri_Compra_Venta"):
    """標記用戶為離線狀態"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        current_time = get_chile_time().replace(tzinfo=None)
        
        # 更新活動狀態為離線
        cursor.execute("""
            UPDATE user_sessions 
            SET is_online = 0, last_activity = ?
            WHERE user_id = ? AND service_name = ?
        """, (current_time, user_id, service_name))
        
        print(f"📴 用戶 {user_id} 離線 - {current_time.strftime('%H:%M:%S')}")
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 離線標記失敗: {e}")
        return False


# 創建 Blueprint
api_auth_bp = Blueprint('api_auth', __name__, url_prefix='/api')


# ========== JWT 配置 ==========
JWT_SECRET_KEY = config.SECRET_KEY
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24  # Token 24小時過期


# ========== JWT Token 工具函數 ==========
def generate_jwt_token(user_data):
    """
    生成 JWT token
    參數：user_data - 用戶數據字典
    返回：str - JWT token
    """
    payload = {
        'user_id': user_data['id'],
        'username': user_data['username'],
        'email': user_data['email'],
        'role': user_data['role'],
        'exp': get_chile_time() + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': get_chile_time()
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_jwt_token(token):
    """
    驗證 JWT token
    參數：token - JWT token字符串
    返回：(bool, dict) - (是否有效, 用戶數據/錯誤信息)
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return True, payload
    except jwt.ExpiredSignatureError:
        return False, {'error': 'Token已過期'}
    except jwt.InvalidTokenError:
        return False, {'error': '無效的Token'}


def token_required(f):
    """
    JWT token 驗證裝飾器
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # 從 Authorization header 獲取 token
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'success': False, 'error': 'Token格式錯誤'}), 401
        
        if not token:
            return jsonify({'success': False, 'error': '缺少認證Token'}), 401
        
        valid, data = verify_jwt_token(token)
        if not valid:
            return jsonify({'success': False, 'error': data['error']}), 401
        
        # 將用戶數據添加到請求上下文
        request.current_user = data
        return f(*args, **kwargs)
    
    return decorated


# ========== API 路由 ==========

@api_auth_bp.route('/login', methods=['POST'])
def api_login():
    """
    API登入端點
    請求：JSON {email, password}
    返回：JSON {success, token, user_info}
    """
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({
                'success': False, 
                'error': '請提供郵箱和密碼'
            }), 400
        
        # 驗證用戶憑證
        success, user_data = verify_password(email, password)
        if not success:
            return jsonify({
                'success': False, 
                'error': user_data  # user_data 在這裡是錯誤信息
            }), 401
        
        # 生成新的會話令牌
        session_token = generate_session_token()
        device_info = get_device_info(request)
        
        # 創建會話記錄
        if not create_session(user_data['id'], session_token, device_info):
            return jsonify({
                'success': False,
                'error': '創建會話失敗'
            }), 500
        
        # 生成 JWT token
        token = generate_jwt_token(user_data)
        
        return jsonify({
            'success': True,
            'token': token,
            'session_token': session_token,
            'user_info': {
                'id': user_data['id'],
                'username': user_data['username'],
                'email': user_data['email'],
                'role': user_data['role']
            },
            'expires_in': JWT_EXPIRATION_HOURS * 3600,  # 秒數
            'message': '登入成功'
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'登入失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/verify', methods=['POST'])
@token_required
def api_verify():
    """
    驗證Token有效性
    請求：Authorization: Bearer <token>
    返回：JSON {success, user_info}
    """
    try:
        return jsonify({
            'success': True,
            'user_info': {
                'id': request.current_user['user_id'],
                'username': request.current_user['username'],
                'email': request.current_user['email'],
                'role': request.current_user['role']
            }
        })
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'驗證失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/user/info', methods=['GET'])
@token_required
def api_user_info():
    """
    獲取用戶詳細信息
    請求：Authorization: Bearer <token>
    返回：JSON {success, user_info}
    """
    try:
        user_id = request.current_user['user_id']
        
        # 從資料庫獲取完整用戶信息
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, username, email, role, created_at 
            FROM users 
            WHERE id = ?
        """, (user_id,))
        
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return jsonify({
                'success': False, 
                'error': '用戶不存在'
            }), 404
        
        # 處理返回格式（可能是字典或元組）
        if isinstance(user, dict):
            user_info = {
                'id': user.get('id'),
                'username': user.get('username'),
                'email': user.get('email'),
                'role': user.get('role'),
                'created_at': user.get('created_at')
            }
        else:
            user_info = {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'role': user[3],
                'created_at': user[4] if len(user) > 4 else None
            }
        
        return jsonify({
            'success': True,
            'user_info': user_info
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'獲取用戶信息失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/user/services', methods=['GET'])
@token_required
def api_user_services():
    """
    獲取用戶服務列表
    請求：Authorization: Bearer <token>
    返回：JSON {success, services}
    """
    try:
        user_id = request.current_user['user_id']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查詢用戶的服務
        cursor.execute("""
            SELECT 
                us.id,
                s.name,
                s.description,
                s.duration_days,
                s.price,
                us.start_date,
                us.end_date,
                us.status,
                us.created_at
            FROM user_services us
            JOIN services s ON us.service_id = s.id
            WHERE us.user_id = ?
            ORDER BY us.created_at DESC
        """, (user_id,))
        
        services = cursor.fetchall()
        conn.close()
        
        service_list = []
        for service in services:
            # 處理返回格式（可能是字典或元組）
            if isinstance(service, dict):
                service_list.append({
                    'id': service.get('id'),
                    'name': service.get('name'),
                    'description': service.get('description'),
                    'duration_days': service.get('duration_days'),
                    'price': float(service.get('price')) if service.get('price') else None,
                    'start_date': service.get('start_date'),
                    'end_date': service.get('end_date'),
                    'status': service.get('status'),
                    'created_at': service.get('created_at')
                })
            else:
                service_list.append({
                    'id': service[0],
                    'name': service[1],
                    'description': service[2],
                    'duration_days': service[3],
                    'price': float(service[4]) if service[4] else None,
                    'start_date': service[5],
                    'end_date': service[6],
                    'status': service[7],
                    'created_at': service[8] if len(service) > 8 else None
                })
        
        return jsonify({
            'success': True,
            'services': service_list,
            'count': len(service_list)
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'獲取服務列表失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/user/services/active', methods=['GET'])
@token_required
def api_user_active_services():
    """
    獲取用戶活躍服務列表
    請求：Authorization: Bearer <token>
    返回：JSON {success, services}
    """
    try:
        user_id = request.current_user['user_id']
        current_date = get_chile_time_naive().strftime('%Y-%m-%d')
        
        # 更新用戶心跳檢測
        session_token = request.headers.get('X-Session-Token')
        update_user_heartbeat(user_id, session_token=session_token)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查詢用戶的活躍服務（未過期且狀態為active）
        cursor.execute("""
            SELECT 
                us.id,
                s.name,
                s.description,
                s.duration_days,
                s.price,
                us.start_date,
                us.end_date,
                us.status,
                us.created_at
            FROM user_services us
            JOIN services s ON us.service_id = s.id
            WHERE us.user_id = ? 
            AND us.status = 'active'
            AND us.end_date >= ?
            ORDER BY us.end_date ASC
        """, (user_id, current_date))
        
        services = cursor.fetchall()
        conn.close()
        
        service_list = []
        for service in services:
            # 處理返回格式（可能是字典或元組）
            if isinstance(service, dict):
                service_list.append({
                    'id': service.get('id'),
                    'name': service.get('name'),
                    'description': service.get('description'),
                    'duration_days': service.get('duration_days'),
                    'price': float(service.get('price')) if service.get('price') else None,
                    'start_date': service.get('start_date'),
                    'end_date': service.get('end_date'),
                    'status': service.get('status'),
                    'created_at': service.get('created_at')
                })
            else:
                service_list.append({
                    'id': service[0],
                    'name': service[1],
                    'description': service[2],
                    'duration_days': service[3],
                    'price': float(service[4]) if service[4] else None,
                    'start_date': service[5],
                    'end_date': service[6],
                    'status': service[7],
                    'created_at': service[8] if len(service) > 8 else None
                })
        
        return jsonify({
            'success': True,
            'services': service_list,
            'count': len(service_list)
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'獲取活躍服務失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/check-service', methods=['POST'])
@token_required
def api_check_service():
    """
    檢查特定服務狀態
    請求：Authorization: Bearer <token>
    請求體：JSON {service_name}
    返回：JSON {success, has_access, service_info}
    """
    try:
        data = request.get_json()
        service_name = data.get('service_name', '').strip()
        
        if not service_name:
            return jsonify({
                'success': False, 
                'error': '請提供服務名稱'
            }), 400
        
        user_id = request.current_user['user_id']
        current_date = get_chile_time_naive().strftime('%Y-%m-%d')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查詢用戶是否有該服務的訪問權限
        cursor.execute("""
            SELECT 
                us.id,
                s.name,
                s.description,
                us.start_date,
                us.end_date,
                us.status
            FROM user_services us
            JOIN services s ON us.service_id = s.id
            WHERE us.user_id = ? 
            AND s.name = ?
            AND us.status = 'active'
            AND us.end_date >= ?
            ORDER BY us.end_date DESC
            LIMIT 1
        """, (user_id, service_name, current_date))
        
        service = cursor.fetchone()
        conn.close()
        
        if service:
            return jsonify({
                'success': True,
                'has_access': True,
                'service_info': {
                    'id': service[0],
                    'name': service[1],
                    'description': service[2],
                    'start_date': service[3],
                    'end_date': service[4],
                    'status': service[5]
                }
            })
        else:
            return jsonify({
                'success': True,
                'has_access': False,
                'service_info': None
            })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'檢查服務失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/refresh-token', methods=['POST'])
@token_required
def api_refresh_token():
    """
    刷新Token
    請求：Authorization: Bearer <token>
    返回：JSON {success, token}
    """
    try:
        # 使用當前用戶數據生成新token
        user_data = {
            'id': request.current_user['user_id'],
            'username': request.current_user['username'],
            'email': request.current_user['email'],
            'role': request.current_user['role']
        }
        
        new_token = generate_jwt_token(user_data)
        
        return jsonify({
            'success': True,
            'token': new_token,
            'expires_in': JWT_EXPIRATION_HOURS * 3600
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'刷新Token失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/user/sessions', methods=['GET'])
@token_required
def api_get_current_user_sessions():
    """
    獲取當前用戶的會話列表
    請求：Authorization: Bearer <token>
    返回：JSON {success, sessions}
    """
    try:
        user_id = request.current_user['user_id']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取用戶的所有會話
        cursor.execute("""
            SELECT 
                id, session_token, device_info, session_start, 
                last_activity, is_online
            FROM user_sessions 
            WHERE user_id = ? 
            ORDER BY last_activity DESC
        """, (user_id,))
        
        sessions = cursor.fetchall()
        conn.close()
        
        session_list = []
        for session in sessions:
            # 處理返回格式（可能是字典或元組）
            if isinstance(session, dict):
                device_info_str = session.get('device_info') or ''
                device_info = json.loads(device_info_str) if device_info_str else {}
                session_list.append({
                    'id': session.get('id'),
                    'session_token': session.get('session_token'),
                    'device_info': device_info,
                    'session_start': session.get('session_start'),
                    'last_activity': session.get('last_activity'),
                    'is_online': bool(session.get('is_online')),
                    'is_current': session.get('session_token') == request.headers.get('X-Session-Token')
                })
            else:
                device_info = json.loads(session[2]) if len(session) > 2 and session[2] else {}
                session_list.append({
                    'id': session[0],
                    'session_token': session[1],
                    'device_info': device_info,
                    'session_start': session[3] if len(session) > 3 else None,
                    'last_activity': session[4] if len(session) > 4 else None,
                    'is_online': bool(session[5]) if len(session) > 5 else False,
                    'is_current': session[1] == request.headers.get('X-Session-Token') if len(session) > 1 else False
                })
        
        return jsonify({
            'success': True,
            'sessions': session_list,
            'count': len(session_list)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'獲取會話失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/admin/user-sessions', methods=['GET'])
def api_get_user_sessions():
    """
    獲取用戶會話狀態（管理員用）
    請求：Authorization: Bearer <token> 或 session 認證
    返回：JSON {success, sessions}
    """
    try:
        # 檢查認證方式
        user_id = None
        user_role = None
        
        # 嘗試從 JWT token 獲取用戶信息
        try:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                valid, payload = verify_jwt_token(token)
                if valid and payload:
                    user_id = payload['user_id']
                    user_role = payload['role']
                    print(f"🔑 JWT認證成功: user_id={user_id}, role={user_role}")
        except Exception as e:
            print(f"❌ JWT認證失敗: {e}")
            pass
        
        # 如果 JWT 認證失敗，嘗試 session 認證
        if not user_id:
            if flask_session.get('logged_in'):
                user_id = flask_session.get('user_id')
                user_role = flask_session.get('role')
                print(f"🔑 Session認證成功: user_id={user_id}, role={user_role}")
                
                # 如果 user_id 是 None 但 role 是 super_admin，允許訪問（super admin 可能沒有數據庫記錄）
                if user_id is None and user_role == admin_config.SUPER_ADMIN_ROLE:
                    print("⚠️ Super Admin user_id 為 None，但允許訪問（使用特殊處理）")
                    user_id = 0  # 使用特殊值標記 super admin
        
        # 檢查是否已認證
        if user_id is None:
            return jsonify({
                'success': False, 
                'error': '缺少認證Token'
            }), 401
        
        # 檢查管理員權限
        if user_role not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
            return jsonify({
                'success': False, 
                'error': '權限不足'
            }), 403
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取每個用戶的最新會話狀態（最近24小時）
        cutoff_time = get_chile_time_naive() - timedelta(hours=24)
        cursor.execute("""
            SELECT 
                us.id,
                us.user_id,
                u.username,
                u.email,
                us.service_name,
                us.session_start,
                us.last_activity,
                us.is_online
            FROM user_sessions us
            JOIN users u ON us.user_id = u.id
            WHERE us.last_activity > ?
            AND us.id IN (
                SELECT MAX(id) 
                FROM user_sessions 
                WHERE last_activity > ?
                GROUP BY user_id
            )
            ORDER BY us.last_activity DESC
        """, (cutoff_time, cutoff_time))
        
        sessions = cursor.fetchall()
        
        
        conn.close()
        
        # 使用 Python 計算狀態，避免時區問題
        current_time = get_chile_time_naive()
        session_list = []
        
        for session in sessions:
            # 解析最後活動時間
            try:
                if isinstance(session[6], str):
                    last_activity = datetime.strptime(session[6], '%Y-%m-%d %H:%M:%S.%f')
                else:
                    last_activity = session[6]
            except:
                try:
                    last_activity = datetime.strptime(session[6], '%Y-%m-%d %H:%M:%S')
                except:
                    last_activity = current_time
            
            # 計算時間差（分鐘）
            time_diff = (current_time - last_activity).total_seconds() / 60
            
            # 判定狀態 - WhatsApp 風格
            if time_diff <= 1:  # 1分鐘內 - 在線
                status = 'online'
            elif time_diff <= 5:  # 1-5分鐘 - 離開
                status = 'away'
            else:  # 超過5分鐘 - 離線
                status = 'offline'
            
            # 處理返回格式（可能是字典或元組）
            if isinstance(session, dict):
                session_list.append({
                    'id': session.get('id'),
                    'user_id': session.get('user_id'),
                    'username': session.get('username'),
                    'email': session.get('email'),
                    'service_name': session.get('service_name'),
                    'session_start': session.get('session_start'),
                    'last_activity': session.get('last_activity'),
                    'is_online': bool(session.get('is_online')),
                    'status': status
                })
            else:
                session_list.append({
                    'id': session[0],
                    'user_id': session[1],
                    'username': session[2],
                    'email': session[3],
                    'service_name': session[4],
                    'session_start': session[5],
                    'last_activity': session[6],
                    'is_online': bool(session[7]) if len(session) > 7 else False,
                    'status': status
                })
        
        return jsonify({
            'success': True,
            'sessions': session_list,
            'count': len(session_list)
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'獲取會話狀態失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/admin/user-sessions/<int:user_id>', methods=['GET'])
def api_get_user_session_details(user_id):
    """
    獲取特定用戶的會話詳情（管理員用）
    請求：GET /api/admin/user-sessions/{user_id}
    返回：JSON {success, sessions}
    """
    try:
        # 檢查認證方式
        current_user_id = None
        user_role = None
        
        # 嘗試從 JWT token 獲取用戶信息
        try:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                valid, payload = verify_jwt_token(token)
                if valid and payload:
                    current_user_id = payload['user_id']
                    user_role = payload['role']
        except Exception as e:
            print(f"❌ JWT認證失敗: {e}")
            pass
        
        # 如果 JWT 認證失敗，嘗試 session 認證
        if not current_user_id:
            if flask_session.get('logged_in'):
                current_user_id = flask_session.get('user_id')
                user_role = flask_session.get('role')
                
                # 如果 user_id 是 None 但 role 是 super_admin，允許訪問
                if current_user_id is None and user_role == admin_config.SUPER_ADMIN_ROLE:
                    print("⚠️ Super Admin user_id 為 None，但允許訪問（使用特殊處理）")
                    current_user_id = 0  # 使用特殊值標記 super admin
        
        # 檢查是否已認證
        if current_user_id is None:
            return jsonify({
                'success': False, 
                'error': '缺少認證Token'
            }), 401
        
        # 檢查管理員權限
        if user_role not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
            return jsonify({
                'success': False, 
                'error': '權限不足'
            }), 403
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取指定用戶的會話記錄（分頁）
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        # 限制每頁數量
        per_page = min(per_page, 50)  # 最多50條
        
        offset = (page - 1) * per_page
        
        # 獲取總數
        cursor.execute("SELECT COUNT(*) FROM user_sessions WHERE user_id = ?", (user_id,))
        total_count_result = cursor.fetchone()
        total_count = total_count_result[0] if isinstance(total_count_result, tuple) else (total_count_result.get('COUNT(*)') or total_count_result.get(list(total_count_result.keys())[0]) if total_count_result else 0)
        
        # 獲取分頁數據
        cursor.execute("""
            SELECT 
                us.id,
                us.user_id,
                u.username,
                u.email,
                us.service_name,
                us.session_start,
                us.last_activity,
                us.is_online,
                us.session_token,
                us.device_info
            FROM user_sessions us
            JOIN users u ON us.user_id = u.id
            WHERE us.user_id = ?
            ORDER BY us.session_start DESC
            LIMIT ? OFFSET ?
        """, (user_id, per_page, offset))
        
        sessions = cursor.fetchall()
        conn.close()
        
        # 使用 Python 計算狀態，避免時區問題
        current_time = get_chile_time_naive()
        session_list = []
        
        for session in sessions:
            # 解析最後活動時間
            try:
                if isinstance(session[6], str):
                    last_activity = datetime.strptime(session[6], '%Y-%m-%d %H:%M:%S.%f')
                else:
                    last_activity = session[6]
            except:
                try:
                    last_activity = datetime.strptime(session[6], '%Y-%m-%d %H:%M:%S')
                except:
                    last_activity = current_time
            
            # 計算時間差（分鐘）
            time_diff = (current_time - last_activity).total_seconds() / 60
            
            # 判定狀態
            if time_diff <= 1:
                status = 'online'
            elif time_diff <= 5:
                status = 'away'
            else:
                status = 'offline'
            
            # 解析設備信息
            device_info = {}
            if session[9]:  # device_info
                try:
                    device_info = json.loads(session[9])
                except:
                    device_info = {}
            
            # 處理返回格式（可能是字典或元組）
            if isinstance(session, dict):
                session_token = session.get('session_token') or ''
                session_list.append({
                    'id': session.get('id'),
                    'user_id': session.get('user_id'),
                    'username': session.get('username'),
                    'email': session.get('email'),
                    'service_name': session.get('service_name'),
                    'session_start': session.get('session_start'),
                    'last_activity': session.get('last_activity'),
                    'is_online': bool(session.get('is_online')),
                    'session_token': session_token[:20] + '...' if session_token else None,
                    'device_info': device_info,
                    'status': status
                })
            else:
                session_list.append({
                    'id': session[0],
                    'user_id': session[1],
                    'username': session[2],
                    'email': session[3],
                    'service_name': session[4],
                    'session_start': session[5],
                    'last_activity': session[6],
                    'is_online': bool(session[7]) if len(session) > 7 else False,
                    'session_token': session[8][:20] + '...' if len(session) > 8 and session[8] else None,
                    'device_info': device_info,
                    'status': status
                })
        
        return jsonify({
            'success': True,
            'sessions': session_list,
            'count': len(session_list),
            'total_count': total_count,
            'page': page,
            'per_page': per_page,
            'has_more': offset + per_page < total_count
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'獲取用戶會話詳情失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/admin/clear-all-sessions', methods=['DELETE'])
def api_clear_all_sessions():
    """
    清除所有用戶的會話記錄（管理員用）
    請求：DELETE /api/admin/clear-all-sessions
    返回：JSON {success, message, deleted_count}
    """
    try:
        # 檢查認證方式
        current_user_id = None
        user_role = None
        
        # 嘗試從 JWT token 獲取用戶信息
        try:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                valid, payload = verify_jwt_token(token)
                if valid and payload:
                    current_user_id = payload['user_id']
                    user_role = payload['role']
        except Exception as e:
            print(f"❌ JWT認證失敗: {e}")
            pass
        
        # 如果 JWT 認證失敗，嘗試 session 認證
        if not current_user_id:
            if flask_session.get('logged_in'):
                current_user_id = flask_session.get('user_id')
                user_role = flask_session.get('role')
                
                # 如果 user_id 是 None 但 role 是 super_admin，允許訪問
                if current_user_id is None and user_role == admin_config.SUPER_ADMIN_ROLE:
                    print("⚠️ Super Admin user_id 為 None，但允許訪問（使用特殊處理）")
                    current_user_id = 0  # 使用特殊值標記 super admin
        
        # 檢查是否已認證
        if current_user_id is None:
            return jsonify({
                'success': False, 
                'error': '缺少認證Token'
            }), 401
        
        # 檢查管理員權限
        if user_role not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
            return jsonify({
                'success': False, 
                'error': '權限不足'
            }), 403
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取將要刪除的會話數量
        cursor.execute("SELECT COUNT(*) FROM user_sessions")
        count_before_result = cursor.fetchone()
        count_before = count_before_result[0] if isinstance(count_before_result, tuple) else (count_before_result.get('COUNT(*)') or count_before_result.get(list(count_before_result.keys())[0]) if count_before_result else 0)
        
        if count_before == 0:
            conn.close()
            return jsonify({
                'success': True,
                'message': '沒有會話記錄需要清除',
                'deleted_count': 0
            })
        
        # 刪除所有會話記錄
        cursor.execute("DELETE FROM user_sessions")
        conn.commit()
        
        # 獲取實際刪除的數量
        cursor.execute("SELECT changes()")
        deleted_count_result = cursor.fetchone()
        deleted_count = deleted_count_result[0] if isinstance(deleted_count_result, tuple) else (deleted_count_result.get('COUNT(*)') or deleted_count_result.get(list(deleted_count_result.keys())[0]) if deleted_count_result else 0)
        
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'成功清除 {deleted_count} 條會話記錄',
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'清除會話記錄失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/admin/delete-user-sessions/<int:user_id>', methods=['DELETE'])
def api_delete_user_sessions(user_id):
    """
    刪除指定用戶的所有會話記錄（管理員用）
    請求：DELETE /api/admin/delete-user-sessions/{user_id}
    返回：JSON {success, message, deleted_count}
    """
    try:
        # 檢查認證方式
        current_user_id = None
        user_role = None
        
        # 嘗試從 JWT token 獲取用戶信息
        try:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                valid, payload = verify_jwt_token(token)
                if valid and payload:
                    current_user_id = payload['user_id']
                    user_role = payload['role']
        except Exception as e:
            print(f"❌ JWT認證失敗: {e}")
            pass
        
        # 如果 JWT 認證失敗，嘗試 session 認證
        if not current_user_id:
            if flask_session.get('logged_in'):
                current_user_id = flask_session.get('user_id')
                user_role = flask_session.get('role')
                
                # 如果 user_id 是 None 但 role 是 super_admin，允許訪問
                if current_user_id is None and user_role == admin_config.SUPER_ADMIN_ROLE:
                    print("⚠️ Super Admin user_id 為 None，但允許訪問（使用特殊處理）")
                    current_user_id = 0  # 使用特殊值標記 super admin
        
        # 檢查是否已認證
        if current_user_id is None:
            return jsonify({
                'success': False, 
                'error': '缺少認證Token'
            }), 401
        
        # 檢查管理員權限
        if user_role not in ['admin', admin_config.SUPER_ADMIN_ROLE]:
            return jsonify({
                'success': False, 
                'error': '權限不足'
            }), 403
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 獲取將要刪除的會話數量
        cursor.execute("SELECT COUNT(*) FROM user_sessions WHERE user_id = ?", (user_id,))
        count_before_result = cursor.fetchone()
        count_before = count_before_result[0] if isinstance(count_before_result, tuple) else (count_before_result.get('COUNT(*)') or count_before_result.get(list(count_before_result.keys())[0]) if count_before_result else 0)
        
        if count_before == 0:
            conn.close()
            return jsonify({
                'success': True,
                'message': '該用戶沒有會話記錄',
                'deleted_count': 0
            })
        
        # 刪除會話記錄
        cursor.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        
        # 獲取實際刪除的數量
        cursor.execute("SELECT changes()")
        deleted_count_result = cursor.fetchone()
        deleted_count = deleted_count_result[0] if isinstance(deleted_count_result, tuple) else (deleted_count_result.get('COUNT(*)') or deleted_count_result.get(list(deleted_count_result.keys())[0]) if deleted_count_result else 0)
        
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'成功刪除 {deleted_count} 條會話記錄',
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'刪除會話記錄失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/config', methods=['GET'])
@token_required
def api_get_config():
    """
    獲取用戶服務配置參數
    請求：Authorization: Bearer <token>
    請求參數：?service_name=xxx&version=xxx
    返回：JSON {success, config}
    """
    try:
        service_name = request.args.get('service_name', 'Zofri_Compra_Venta')
        version = request.args.get('version', None)
        
        # 獲取用戶的參數配置
        if not version:
            user_id = request.current_user['user_id']
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 查詢用戶服務的參數配置
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
            
            if result and result[0]:
                # 從 service_versions 表獲取參數名稱
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT param_name, param_content 
                    FROM service_versions 
                    WHERE service_name = ? AND param_content = ?
                    LIMIT 1
                """, (service_name, result[0]))
                
                param_result = cursor.fetchone()
                conn.close()
                
                if param_result:
                    version = param_result[0]  # 使用參數名稱（如 FREE、PRO、ULTRA）
                else:
                    version = 'FREE'  # 默認版本
            else:
                version = 'FREE'  # 默認版本
        
        # 獲取配置
        config_data = config_service.get_config_for_service(service_name, version)
        
        return jsonify({
            'success': True,
            'config': config_data,
            'service_name': service_name,
            'version': version
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'獲取配置失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/config/all', methods=['GET'])
@token_required
def api_get_all_configs():
    """
    獲取所有服務配置（管理員用）
    請求：Authorization: Bearer <token>
    返回：JSON {success, configs}
    """
    try:
        # 檢查管理員權限
        user_role = request.current_user.get('role', 'user')
        if user_role not in ['admin', 'super_admin']:
            return jsonify({
                'success': False, 
                'error': '權限不足'
            }), 403
        
        configs = config_service.get_all_service_configs()
        
        return jsonify({
            'success': True,
            'configs': configs
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'獲取所有配置失敗：{str(e)}'
        }), 500


@api_auth_bp.route('/config/update', methods=['POST'])
@token_required
def api_update_config():
    """
    更新服務配置（管理員用）
    請求：Authorization: Bearer <token>
    請求體：JSON {service_name, version, config}
    返回：JSON {success, message}
    """
    try:
        # 檢查管理員權限
        user_role = request.current_user.get('role', 'user')
        if user_role not in ['admin', 'super_admin']:
            return jsonify({
                'success': False, 
                'error': '權限不足'
            }), 403
        
        data = request.get_json()
        service_name = data.get('service_name', '').strip()
        version = data.get('version', '').strip()
        config_data = data.get('config', {})
        
        if not service_name or not version:
            return jsonify({
                'success': False, 
                'error': '請提供服務名稱和版本'
            }), 400
        
        success = config_service.update_service_config(service_name, version, config_data)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'{service_name} {version} 配置更新成功'
            })
        else:
            return jsonify({
                'success': False,
                'error': '配置更新失敗'
            }), 500
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'更新配置失敗：{str(e)}'
        }), 500


# ========== 錯誤處理 ==========
@api_auth_bp.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'API端點不存在'}), 404


@api_auth_bp.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'success': False, 'error': '不支援的HTTP方法'}), 405


@api_auth_bp.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': '內部服務器錯誤'}), 500
