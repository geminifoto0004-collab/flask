"""
用戶認證 Blueprint
功能：用戶註冊、登入、忘記密碼、修改密碼
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from services.email_service import send_verification_code, verify_code
from services.user_service import (
    create_user, verify_password, reset_password, 
    change_password, email_exists, username_exists
)
from utils.validators import (
    validate_email, validate_password, validate_username,
    validate_verification_code
)
from config import feature_flags


# 創建 Blueprint
user_auth_bp = Blueprint('user_auth', __name__, url_prefix='/user')


# ========== 用戶註冊頁面 ==========
@user_auth_bp.route('/register', methods=['GET'])
def register_page():
    """用戶註冊頁面"""
    if not feature_flags.ENABLE_USER_REGISTRATION:
        return "用戶註冊功能未開啟", 403
    
    return render_template('user/register.html')


# ========== 步驟 1：發送註冊驗證碼 ==========
@user_auth_bp.route('/register/send-code', methods=['POST'])
def send_register_code():
    """
    發送註冊驗證碼（API）
    請求：JSON {email}
    返回：JSON {success, message}
    """
    if not feature_flags.ENABLE_USER_REGISTRATION:
        return jsonify({'success': False, 'message': '用戶註冊功能未開啟'}), 403
    
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        
        # 驗證郵箱格式
        valid, msg = validate_email(email)
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        # 檢查是否為超級管理員保留郵箱
        from config import admin_config
        if email.lower() == admin_config.SUPER_ADMIN_EMAIL.lower():
            return jsonify({'success': False, 'message': f'{admin_config.SUPER_ADMIN_EMAIL} es un correo reservado para el super administrador, no se puede registrar'})
        
        # 檢查郵箱是否已註冊
        if email_exists(email):
            return jsonify({'success': False, 'message': '該郵箱已被註冊'})
        
        # 發送驗證碼
        success, error = send_verification_code(email, purpose='registration')
        
        if success:
            return jsonify({'success': True, 'message': 'El código de verificación ha sido enviado a su correo electrónico'})
        else:
            return jsonify({'success': False, 'message': f'發送失敗: {error}'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error del sistema: {str(e)}'}), 500


# ========== 步驟 2：提交註冊（驗證碼 + 創建用戶）==========
@user_auth_bp.route('/register/submit', methods=['POST'])
def submit_registration():
    """
    提交註冊信息
    請求：JSON {username, email, password, code}
    返回：JSON {success, message}
    """
    if not feature_flags.ENABLE_USER_REGISTRATION:
        return jsonify({'success': False, 'message': '用戶註冊功能未開啟'}), 403
    
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        code = data.get('code', '').strip()
        
        # 驗證用戶名
        valid, msg = validate_username(username)
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        # 驗證郵箱
        valid, msg = validate_email(email)
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        # 驗證密碼
        valid, msg = validate_password(password)
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        # 驗證驗證碼
        valid, msg = validate_verification_code(code)
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        # 驗證驗證碼是否正確
        valid, msg = verify_code(email, code, purpose='registration')
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        # 檢查是否為超級管理員保留郵箱
        from config import admin_config
        if email.lower() == admin_config.SUPER_ADMIN_EMAIL.lower():
            return jsonify({'success': False, 'message': f'{admin_config.SUPER_ADMIN_EMAIL} es un correo reservado para el super administrador, no se puede registrar'})
        
        # 檢查用戶名是否已存在
        if username_exists(username):
            return jsonify({'success': False, 'message': 'Este nombre de usuario ya está en uso'})
        
        # 檢查郵箱是否已註冊
        if email_exists(email):
            return jsonify({'success': False, 'message': 'Este correo electrónico ya está registrado'})
        
        # 創建用戶
        success, result = create_user(username, email, password)
        
        if success:
            # 註冊成功後直接登入用戶
            from services.user_service import verify_password
            login_success, login_result = verify_password(email, password)
            
            if login_success:
                # 設置 session
                session['logged_in'] = True
                session['user_id'] = login_result['id']
                session['username'] = login_result['username']
                session['email'] = login_result['email']
                session['role'] = login_result['role']
                
                # 創建會話記錄（用於會話監控）
                try:
                    from blueprints.api_auth_bp import create_session, generate_session_token, get_device_info
                    session_token = generate_session_token()
                    device_info = get_device_info(request)
                    success = create_session(login_result['id'], session_token, device_info, service_name="Web_Login")
                    if success:
                        print(f"✅ 創建註冊後登入會話記錄成功 - 用戶 {login_result['id']}, service_name=Web_Login")
                    else:
                        print(f"❌ 創建註冊後登入會話記錄失敗 - 用戶 {login_result['id']}, create_session返回False")
                except ImportError as e:
                    print(f"❌ 導入會話管理函數失敗: {e}")
                except Exception as e:
                    import traceback
                    print(f"❌ 創建會話記錄失敗（不影響登入）: {e}")
                    print(f"   詳細錯誤: {traceback.format_exc()}")
                
                return jsonify({
                    'success': True, 
                    'message': '¡Registro exitoso! Redirigiendo al portal de usuario...',
                    'user_id': result,
                    'auto_login': True
                })
            else:
                return jsonify({
                    'success': True, 
                    'message': '¡Registro exitoso! Por favor inicie sesión',
                    'user_id': result,
                    'auto_login': False
                })
        else:
            return jsonify({'success': False, 'message': result})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error del sistema: {str(e)}'}), 500


# ========== 用戶登入頁面 ==========
@user_auth_bp.route('/login', methods=['GET'])
def login_page():
    """用戶登入頁面"""
    return render_template('user/login.html')


# ========== 用戶登入提交 ==========
@user_auth_bp.route('/login', methods=['POST'])
def login_submit():
    """
    用戶登入
    表單：email, password
    """
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    
    # 驗證輸入
    if not email or not password:
        return render_template('user/login.html', error='Por favor complete toda la información')
    
    # 驗證密碼
    success, result = verify_password(email, password)
    
    if success:
        # 設置 session
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
        
        # 根據角色重定向
        from config import admin_config
        if result['role'] in ['admin', admin_config.SUPER_ADMIN_ROLE]:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('user_auth.user_portal'))
    else:
        return render_template('user/login.html', error=result)


# ========== 用戶門戶（登入後）==========
@user_auth_bp.route('/portal')
def user_portal():
    """用戶門戶頁面（需要登入）"""
    if not session.get('logged_in'):
        return redirect(url_for('user_auth.login_page'))
    
    return render_template('user/portal.html')


# ========== 忘記密碼頁面 ==========
@user_auth_bp.route('/forgot-password', methods=['GET'])
def forgot_password_page():
    """忘記密碼頁面"""
    return render_template('user/forgot_password.html')


# ========== 步驟 1：發送重置密碼驗證碼 ==========
@user_auth_bp.route('/forgot-password/send-code', methods=['POST'])
def send_reset_code():
    """
    發送重置密碼驗證碼（API）
    請求：JSON {email}
    返回：JSON {success, message}
    """
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        
        # 驗證郵箱格式
        valid, msg = validate_email(email)
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        # 檢查是否為超級管理員保留郵箱
        from config import admin_config
        if email.lower() == admin_config.SUPER_ADMIN_EMAIL.lower():
            return jsonify({'success': False, 'message': f'{admin_config.SUPER_ADMIN_EMAIL} 是超級管理員保留郵箱，不能重置密碼'})
        
        # 檢查郵箱是否已註冊
        if not email_exists(email):
            return jsonify({'success': False, 'message': '該郵箱未註冊'})
        
        # 發送驗證碼
        success, error = send_verification_code(email, purpose='reset_password')
        
        if success:
            return jsonify({'success': True, 'message': 'El código de verificación ha sido enviado a su correo electrónico'})
        else:
            return jsonify({'success': False, 'message': f'發送失敗: {error}'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error del sistema: {str(e)}'}), 500


# ========== 步驟 2：提交新密碼 ==========
@user_auth_bp.route('/forgot-password/reset', methods=['POST'])
def reset_password_submit():
    """
    重置密碼
    請求：JSON {email, code, new_password}
    返回：JSON {success, message}
    """
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        code = data.get('code', '').strip()
        new_password = data.get('new_password', '')
        
        # 驗證輸入
        valid, msg = validate_email(email)
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        valid, msg = validate_verification_code(code)
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        valid, msg = validate_password(new_password)
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        # 驗證驗證碼
        valid, msg = verify_code(email, code, purpose='reset_password')
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        # 重置密碼
        success, error = reset_password(email, new_password)
        
        if success:
            return jsonify({'success': True, 'message': '密碼重置成功！請使用新密碼登入'})
        else:
            return jsonify({'success': False, 'message': error})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error del sistema: {str(e)}'}), 500


# ========== 修改密碼頁面（需登入）==========
@user_auth_bp.route('/change-password', methods=['GET'])
def change_password_page():
    """修改密碼頁面"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    return render_template('user/change_password.html')


# ========== 提交修改密碼 ==========
@user_auth_bp.route('/change-password', methods=['POST'])
def change_password_submit():
    """
    修改密碼（需要驗證舊密碼）
    請求：JSON {old_password, new_password}
    返回：JSON {success, message}
    """
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': '請先登入'}), 401
    
    try:
        data = request.get_json()
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')
        
        email = session.get('email')
        
        # 驗證新密碼
        valid, msg = validate_password(new_password)
        if not valid:
            return jsonify({'success': False, 'message': msg})
        
        # 修改密碼
        success, error = change_password(email, old_password, new_password)
        
        if success:
            return jsonify({'success': True, 'message': '¡Contraseña modificada exitosamente!'})
        else:
            return jsonify({'success': False, 'message': error})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error del sistema: {str(e)}'}), 500


# ========== 檢查郵箱是否可用（API）==========
@user_auth_bp.route('/check-email', methods=['POST'])
def check_email_availability():
    """
    檢查郵箱是否可用
    請求：JSON {email}
    返回：JSON {available, message}
    """
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        
        # 驗證格式
        valid, msg = validate_email(email)
        if not valid:
            return jsonify({'available': False, 'message': msg})
        
        # 檢查是否為超級管理員保留郵箱
        from config import admin_config
        if email.lower() == admin_config.SUPER_ADMIN_EMAIL.lower():
            return jsonify({'available': False, 'message': f'{admin_config.SUPER_ADMIN_EMAIL} es un correo reservado para el super administrador, no se puede registrar'})
        
        # 檢查是否已存在
        exists = email_exists(email)
        
        if exists:
            return jsonify({'available': False, 'message': 'Este correo electrónico ya está registrado'})
        else:
            return jsonify({'available': True, 'message': 'Correo electrónico disponible'})
            
    except Exception as e:
        return jsonify({'available': False, 'message': f'Error del sistema: {str(e)}'}), 500


# ========== 檢查用戶名是否可用（API）==========
@user_auth_bp.route('/check-username', methods=['POST'])
def check_username_availability():
    """
    檢查用戶名是否可用
    請求：JSON {username}
    返回：JSON {available, message}
    """
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        
        # 驗證格式
        valid, msg = validate_username(username)
        if not valid:
            return jsonify({'available': False, 'message': msg})
        
        # 檢查是否已存在
        exists = username_exists(username)
        
        if exists:
            return jsonify({'available': False, 'message': 'Este nombre de usuario ya está en uso'})
        else:
            return jsonify({'available': True, 'message': 'Nombre de usuario disponible'})
            
    except Exception as e:
        return jsonify({'available': False, 'message': f'Error del sistema: {str(e)}'}), 500