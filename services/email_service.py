"""
郵件服務模組
功能：發送驗證碼、生成驗證碼、驗證驗證碼
"""

import smtplib
import random
import string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import os

from config import email_config
from database import get_db_connection, get_cursor
from utils.time_utils import get_chile_time_naive

# ========== SMTP 失敗緩存 ==========
# 用於記住 SMTP 是否可用，避免重複嘗試
# 優先檢查環境變數（持久化，適用於 Render），其次檢查文件緩存（適用於本地）
_SMTP_FAILED_CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', '.smtp_failed_cache')
_SMTP_FAILED = None  # None=未知, True=已失敗, False=可用

def _load_smtp_cache():
    """
    加載 SMTP 失敗緩存
    優先檢查環境變數 SMTP_FAILED（持久化，適用於 Render）
    其次檢查文件緩存（適用於本地開發）
    """
    global _SMTP_FAILED
    if _SMTP_FAILED is not None:
        return _SMTP_FAILED
    
    # 1. 優先檢查環境變數（持久化，適用於 Render）
    smtp_failed_env = os.environ.get('SMTP_FAILED', '').lower()
    if smtp_failed_env in ('1', 'true', 'yes', 'on'):
        _SMTP_FAILED = True
        print("[Email Cache] 從環境變數讀取: SMTP 已失敗（永久記錄）")
        return _SMTP_FAILED
    
    # 2. 檢查文件緩存（適用於本地開發）
    try:
        if os.path.exists(_SMTP_FAILED_CACHE_FILE):
            with open(_SMTP_FAILED_CACHE_FILE, 'r') as f:
                content = f.read().strip()
                _SMTP_FAILED = (content == '1')
                print(f"[Email Cache] 從文件緩存讀取: SMTP {'已失敗' if _SMTP_FAILED else '可用'}")
        else:
            _SMTP_FAILED = None
            print("[Email Cache] 緩存不存在，將嘗試 SMTP")
    except Exception as e:
        print(f"[Email Cache] 讀取緩存失敗: {e}")
        _SMTP_FAILED = None
    
    return _SMTP_FAILED

def _save_smtp_cache(failed=True):
    """
    保存 SMTP 失敗狀態
    同時保存到文件緩存（本地）和提示用戶設置環境變數（Render）
    """
    global _SMTP_FAILED
    _SMTP_FAILED = failed
    
    # 保存到文件緩存（適用於本地開發）
    try:
        with open(_SMTP_FAILED_CACHE_FILE, 'w') as f:
            f.write('1' if failed else '0')
        print(f"[Email Cache] 已保存到文件: SMTP {'已失敗' if failed else '可用'}")
    except Exception as e:
        print(f"[Email Cache] 保存文件緩存失敗: {e}")
    
    # 如果是失敗狀態，提示用戶設置環境變數（適用於 Render）
    if failed:
        print("\n" + "="*60)
        print("⚠️  SMTP 已失敗，已記錄到緩存")
        print("="*60)
        print("💡 為了避免每次重啟都嘗試 SMTP，建議在 Render 上設置環境變數：")
        print("   SMTP_FAILED=1")
        print("   這樣會永久跳過 SMTP，直接使用 Resend API")
        print("="*60 + "\n")

def _clear_smtp_cache():
    """清除 SMTP 失敗緩存（用於測試或重置）"""
    global _SMTP_FAILED
    _SMTP_FAILED = None
    try:
        if os.path.exists(_SMTP_FAILED_CACHE_FILE):
            os.remove(_SMTP_FAILED_CACHE_FILE)
            print("[Email Cache] 已清除文件緩存")
        print("💡 如果設置了環境變數 SMTP_FAILED=1，請在 Render 上刪除該環境變數")
    except Exception as e:
        print(f"[Email Cache] 清除緩存失敗: {e}")


# ========== 生成驗證碼 ==========
def generate_verification_code(length=6):
    """
    生成隨機數字驗證碼
    參數：length - 驗證碼長度（默認 6）
    返回：str - 驗證碼
    """
    return ''.join(random.choices(string.digits, k=length))


# ========== 保存驗證碼到資料庫 ==========
def save_verification_code(email, code, purpose='registration'):
    """
    保存驗證碼到資料庫
    參數：
        email - 郵箱地址
        code - 驗證碼
        purpose - 用途（registration/reset_password）
    返回：bool - 是否保存成功
    """
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)  # 使用 get_cursor 以支持自動 SQL 適配和 DictCursor
        
        # 計算過期時間
        expire_time = get_chile_time_naive() + timedelta(minutes=email_config.CODE_EXPIRE_MINUTES)
        
        # 檢查是否已有有效的驗證碼（未使用且未過期）
        current_time = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            SELECT id FROM verification_codes 
            WHERE email=? AND purpose=? AND used=0 AND expire_time > ?
            ORDER BY created_at DESC LIMIT 1
        ''', (email, purpose, current_time))
        
        existing_code = cursor.fetchone()
        
        if existing_code:
            # 如果已有有效驗證碼，不發送新驗證碼，直接返回成功
            conn.close()
            return True
        else:
            # 將舊的驗證碼標記為已使用
            cursor.execute(
                'UPDATE verification_codes SET used=1 WHERE email=? AND purpose=? AND used=0',
                (email, purpose)
            )
            
            # 插入新驗證碼
            cursor.execute('''
                INSERT INTO verification_codes (email, code, purpose, expire_time, used)
                VALUES (?, ?, ?, ?, 0)
            ''', (email, code, purpose, expire_time.strftime('%Y-%m-%d %H:%M:%S')))
        
        conn.commit()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"保存驗證碼失敗: {e}")
        import traceback
        traceback.print_exc()
        return False


# ========== 驗證驗證碼 ==========
def verify_code(email, code, purpose='registration'):
    """
    驗證驗證碼是否正確
    參數：
        email - 郵箱地址
        code - 驗證碼
        purpose - 用途
    返回：(bool, str) - (是否有效, 錯誤信息)
    """
    try:
        conn = get_db_connection()
        cursor = get_cursor(conn)  # 使用 get_cursor 以支持自動 SQL 適配和 DictCursor
        
        # 查詢驗證碼
        cursor.execute('''
            SELECT id, expire_time, used FROM verification_codes
            WHERE email=? AND code=? AND purpose=?
            ORDER BY created_at DESC LIMIT 1
        ''', (email, code, purpose))
        
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            print(f"[Verify Code] 未找到驗證碼: email={email}, code={code}, purpose={purpose}")
            return False, "驗證碼不正確"
        
        # 處理返回格式（可能是字典或元組）
        if isinstance(result, dict):
            result_id = result['id']
            result_used = result['used']
            result_expire_time = result['expire_time']
        else:
            # 如果是元組，按順序解包
            result_id = result[0]
            result_expire_time = result[1]
            result_used = result[2]
        
        # 檢查是否已使用
        if result_used:
            conn.close()
            print(f"[Verify Code] 驗證碼已被使用: email={email}, code={code}")
            return False, "驗證碼已被使用"
        
        # 檢查是否過期
        if isinstance(result_expire_time, str):
            expire_time = datetime.strptime(result_expire_time, '%Y-%m-%d %H:%M:%S')
        else:
            expire_time = result_expire_time
        
        current_time = get_chile_time_naive()
        if current_time > expire_time:
            conn.close()
            print(f"[Verify Code] 驗證碼已過期: email={email}, code={code}, expire_time={expire_time}, current_time={current_time}")
            return False, "驗證碼已過期"
        
        # 標記為已使用
        cursor.execute('UPDATE verification_codes SET used=1 WHERE id=?', (result_id,))
        conn.commit()
        conn.close()
        
        print(f"[Verify Code] 驗證成功: email={email}, code={code}")
        return True, ""
        
    except Exception as e:
        print(f"驗證碼驗證失敗: {e}")
        import traceback
        traceback.print_exc()
        return False, f"系統錯誤: {str(e)}"


# ========== 使用 Resend API 發送郵件 ==========
def send_email_via_resend(to_email, subject, html_content):
    """
    使用 Resend API 發送郵件（不受 Render 網絡限制）
    參數：
        to_email - 收件人郵箱
        subject - 郵件主題
        html_content - HTML 內容
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
    try:
        import resend  # type: ignore
        
        if not email_config.RESEND_API_KEY:
            return False, "RESEND_API_KEY 未設置"
        
        if not email_config.RESEND_FROM_EMAIL:
            return False, "RESEND_FROM_EMAIL 未設置（需要在 Resend 驗證發送域名）"
        
        resend.api_key = email_config.RESEND_API_KEY
        
        print(f"[Resend API] 嘗試發送郵件到: {to_email}")
        
        r = resend.Emails.send({
            "from": email_config.RESEND_FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": html_content
        })
        
        print(f"[Resend API] 郵件發送成功: {r}")
        return True, ""
        
    except ImportError:
        return False, "Resend 模組未安裝，請運行: pip install resend"
    except Exception as e:
        error_msg = str(e)
        print(f"[Resend API] 發送失敗: {error_msg}")
        return False, f"Resend API 發送失敗: {error_msg}"


# ========== 清理和驗證郵件地址 ==========
def clean_email_address(email: str) -> str:
    """
    清理郵件地址（去除空格、分號等）
    參數：
        email - 原始郵件地址
    返回：清理後的郵件地址
    """
    if not email:
        return ""
    # 去除首尾空格
    email = email.strip()
    # 去除分號（如果用戶誤輸入）
    email = email.rstrip(';')
    # 去除多餘空格
    email = email.strip()
    return email


def validate_email_format(email: str) -> bool:
    """
    驗證郵件地址格式
    參數：
        email - 郵件地址
    返回：是否有效
    """
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


# ========== 發送郵件 ==========
def send_email(to_email, subject, html_content):
    """
    發送 HTML 郵件
    根據 EMAIL_PROVIDER 配置選擇服務：
    - 'auto': 自動檢測，優先 SMTP，失敗後自動切換到 Resend API（並記住）
    - 'smtp': 只使用 SMTP
    - 'resend': 只使用 Resend API
    
    如果設置了 PYANYWHERE_EMAIL_PROXY_URL，優先使用 PythonAnywhere 代理（臨時方案）
    
    參數：
        to_email - 收件人郵箱（字符串或列表）
        subject - 郵件主題
        html_content - HTML 內容
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
    # 清理和驗證郵件地址
    if isinstance(to_email, str):
        to_email = clean_email_address(to_email)
        if not validate_email_format(to_email):
            return False, f"無效的郵件地址格式: {to_email}"
    elif isinstance(to_email, list):
        # 清理列表中的每個郵件地址
        cleaned_emails = []
        for email in to_email:
            cleaned = clean_email_address(email)
            if cleaned and validate_email_format(cleaned):
                cleaned_emails.append(cleaned)
            else:
                print(f"[Email] 跳過無效的郵件地址: {email}")
        if not cleaned_emails:
            return False, "沒有有效的郵件地址"
        # Resend API 支持列表，SMTP 需要逐個發送
        to_email = cleaned_emails
    # 優先檢查 PythonAnywhere 代理（如果設置了）
    if email_config.PYANYWHERE_EMAIL_PROXY_URL:
        from services.email_proxy import send_email_via_proxy
        print("[Email] 使用 PythonAnywhere 代理發送郵件")
        success, error = send_email_via_proxy(
            email_config.PYANYWHERE_EMAIL_PROXY_URL,
            to_email,
            subject,
            html_content
        )
        if success:
            return True, ""
        else:
            # 代理失敗，回退到原有邏輯
            print(f"[Email] 代理失敗，回退到原有邏輯: {error}")
            # 繼續執行下面的邏輯
    
    provider = email_config.EMAIL_PROVIDER.lower()
    print(f"[Email] 郵件服務提供商: {provider}")
    print(f"[Email Debug] EMAIL_PROVIDER 環境變數: {os.environ.get('EMAIL_PROVIDER', '未設置')}")
    print(f"[Email Debug] email_config.EMAIL_PROVIDER: {email_config.EMAIL_PROVIDER}")
    
    # 如果是 'auto' 模式，先檢查緩存
    if provider == 'auto':
        smtp_failed = _load_smtp_cache()
        if smtp_failed:
            print("[Email] 檢測到 SMTP 已失敗（從緩存），直接使用 Resend API")
            provider = 'resend'
        else:
            print("[Email] 自動模式：優先嘗試 SMTP")
            provider = 'smtp'
    
    # 根據配置選擇服務
    if provider == 'resend':
        # 只使用 Resend API
        if not email_config.RESEND_API_KEY or not email_config.RESEND_FROM_EMAIL:
            return False, "Resend API 配置未設置（需要 RESEND_API_KEY 和 RESEND_FROM_EMAIL）"
        
        print("[Email] 使用 Resend API 發送郵件")
        success, error = send_email_via_resend(to_email, subject, html_content)
        if success:
            # Resend 成功，清除 SMTP 失敗緩存（可能 SMTP 現在可用了）
            _clear_smtp_cache()
        return success, error
    
    elif provider == 'smtp':
        # 只使用 SMTP
        return _send_email_via_smtp(to_email, subject, html_content)
    
    else:
        # 'auto' 模式：先嘗試 SMTP，失敗後切換到 Resend API
        print("[Email] 自動模式：先嘗試 SMTP")
        
        # 檢查 SMTP 配置
        if not email_config.SMTP_EMAIL or not email_config.SMTP_PASSWORD:
            print("[Email] SMTP 配置未設置，切換到 Resend API")
            if not email_config.RESEND_API_KEY or not email_config.RESEND_FROM_EMAIL:
                return False, "SMTP 和 Resend API 都未配置"
            return send_email_via_resend(to_email, subject, html_content)
        
        # 嘗試 SMTP
        success, error = _send_email_via_smtp(to_email, subject, html_content)
        if success:
            # SMTP 成功，清除失敗緩存
            _clear_smtp_cache()
            return True, ""
        
        # SMTP 失敗，記錄並切換到 Resend API
        print(f"[Email] SMTP 失敗: {error}")
        print("[Email] 自動切換到 Resend API")
        _save_smtp_cache(failed=True)
        
        if not email_config.RESEND_API_KEY or not email_config.RESEND_FROM_EMAIL:
            return False, f"SMTP 失敗: {error}，且 Resend API 未配置"
        
        return send_email_via_resend(to_email, subject, html_content)


def _send_email_via_smtp(to_email, subject, html_content):
    """
    通過 SMTP 發送郵件（內部函數）
    參數：
        to_email - 收件人郵箱
        subject - 郵件主題
        html_content - HTML 內容
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
    print("[Email] 使用 SMTP 發送郵件")
    
    # 檢查 SMTP 配置
    if not email_config.SMTP_EMAIL or not email_config.SMTP_PASSWORD:
        return False, "SMTP 配置未設置"
    
    try:
        # 創建郵件
        msg = MIMEMultipart('alternative')
        msg['From'] = email_config.SMTP_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # 添加 HTML 內容
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        # 連接 SMTP 服務器（設置超時，避免在 Render 上卡住）
        # 超時設置：10 秒（適用於所有 SMTP 操作）
        # 根據端口選擇連接方式：465 使用 SSL，587 使用 STARTTLS
        print(f"[SMTP] 嘗試連接到 {email_config.SMTP_SERVER}:{email_config.SMTP_PORT}")
        
        if email_config.SMTP_PORT == 465:
            # 使用 SSL 連接（端口 465）
            print("[SMTP] 使用 SSL 連接（端口 465）")
            server = smtplib.SMTP_SSL(email_config.SMTP_SERVER, email_config.SMTP_PORT, timeout=10)
            server.set_debuglevel(0)  # 關閉調試輸出
        else:
            # 使用普通連接然後啟動 TLS（端口 587）
            print("[SMTP] 使用 STARTTLS 連接（端口 587）")
            server = smtplib.SMTP(email_config.SMTP_SERVER, email_config.SMTP_PORT, timeout=10)
            server.set_debuglevel(0)  # 關閉調試輸出
            # 啟動 TLS
            server.starttls()
        
        print(f"[SMTP] 連接成功，嘗試登入: {email_config.SMTP_EMAIL}")
        
        # 登入（自動嘗試兩種密碼格式：去掉空格和保留空格）
        password_original = email_config.SMTP_PASSWORD
        login_success = False
        last_error = None
        
        # 準備兩種密碼格式
        if ' ' in password_original:
            # 如果密碼包含空格，準備兩種格式
            password_no_space = password_original.replace(' ', '')
            passwords_to_try = [
                (password_no_space, f"去掉空格（長度: {len(password_no_space)}）"),
                (password_original, f"保留空格（長度: {len(password_original)}）")
            ]
        else:
            # 如果密碼沒有空格，也嘗試添加空格（如果長度是 16，可能是 Gmail 應用密碼）
            if len(password_original) == 16:
                # 嘗試添加空格：每 4 個字符加一個空格
                password_with_space = ' '.join([password_original[i:i+4] for i in range(0, len(password_original), 4)])
                passwords_to_try = [
                    (password_original, f"原始格式（長度: {len(password_original)}）"),
                    (password_with_space, f"添加空格（長度: {len(password_with_space)}）")
                ]
            else:
                # 長度不是 16，直接使用原始密碼
                passwords_to_try = [(password_original, f"原始格式（長度: {len(password_original)}）")]
        
        # 嘗試每種密碼格式
        for password, description in passwords_to_try:
            try:
                print(f"[SMTP] 嘗試登入 - {description}")
                server.login(email_config.SMTP_EMAIL, password)
                login_success = True
                print(f"[SMTP] 登入成功 - {description}")
                break
            except smtplib.SMTPAuthenticationError as e:
                last_error = e
                print(f"[SMTP] 登入失敗 - {description}: {str(e)}")
                # 繼續嘗試下一種格式
                continue
        
        if not login_success:
            # 所有格式都失敗，拋出最後的錯誤
            raise last_error or smtplib.SMTPAuthenticationError("所有密碼格式都失敗")
        
        # 發送郵件
        server.send_message(msg)
        server.quit()
        
        print(f"郵件已發送到: {to_email}")
        return True, ""
        
    except smtplib.SMTPAuthenticationError as e:
        error_msg = f"SMTP 認證失敗: {str(e)}"
        # 如果是 Gmail，提供更詳細的提示
        if 'gmail.com' in email_config.SMTP_EMAIL.lower():
            error_msg += "\n💡 Gmail 提示：請使用「應用程式密碼」，不是 Gmail 登入密碼！\n獲取方法：https://myaccount.google.com/apppasswords"
        return False, error_msg
    except (TimeoutError, OSError) as e:
        # 捕獲超時和網絡錯誤
        error_str = str(e).lower()
        error_code = str(e)
        
        # 判斷是否為網絡不可達錯誤（Render 上常見）
        if 'network is unreachable' in error_str or '101' in error_code:
            return False, f"SMTP 網絡不可達: {str(e)}"
        elif 'timeout' in error_str or 'timed out' in error_str:
            return False, f"SMTP 連接超時: {str(e)}"
        elif 'connection refused' in error_str or '111' in error_code:
            return False, f"SMTP 連接被拒絕: {str(e)}"
        else:
            return False, f"SMTP 連接錯誤: {str(e)}"
    except smtplib.SMTPException as e:
        return False, f"郵件發送失敗: {str(e)}"
    except Exception as e:
        # 捕獲所有其他異常，包括 socket 超時
        error_str = str(e).lower()
        error_type = type(e).__name__
        if 'timeout' in error_str or 'timed out' in error_str:
            return False, "SMTP 連接超時: 請檢查網絡連接或稍後再試"
        return False, f"郵件發送失敗: {error_type} - {str(e)}"


# ========== 發送驗證碼 ==========
def send_verification_code(email, purpose='registration'):
    """
    生成並發送驗證碼
    參數：
        email - 郵箱地址
        purpose - 用途（registration/reset_password）
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
    # 生成驗證碼
    code = generate_verification_code(email_config.CODE_LENGTH)
    
    # 保存到資料庫
    if not save_verification_code(email, code, purpose):
        return False, "驗證碼保存失敗"
    
    # 獲取郵件模板
    if purpose not in email_config.EMAIL_TEMPLATES:
        return False, f"未知的郵件類型: {purpose}"
    
    template = email_config.EMAIL_TEMPLATES[purpose]
    
    # 生成郵件內容
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: Arial, sans-serif;
                background-color: #f5f5f5;
                padding: 20px;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
            }}
            .code {{
                text-align: center;
                font-size: 32px;
                font-weight: bold;
                color: #667eea;
                letter-spacing: 5px;
                padding: 20px;
                background: #f0f4ff;
                border-radius: 8px;
                margin: 20px 0;
            }}
            .footer {{
                text-align: center;
                margin-top: 30px;
                color: #999;
                font-size: 12px;
            }}
            .warning {{
                color: #e74c3c;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>🔐 {template['subject']}</h2>
            </div>
            
            <p>您好，</p>
            <p>您的驗證碼為：</p>
            
            <div class="code">{code}</div>
            
            <p>此驗證碼有效期為 <strong>{email_config.CODE_EXPIRE_MINUTES} 分鐘</strong>。</p>
            
            {('<p class="warning">⚠️ 如非本人操作，請立即聯繫管理員！</p>' if purpose == 'reset_password' else '')}
            
            <p>請勿將驗證碼告訴他人。</p>
            
            <div class="footer">
                <p>此郵件由系統自動發送，請勿回復</p>
                <p>© 2025 授權管理系統</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    # 發送郵件
    success, error = send_email(email, template['subject'], html_content)
    
    if success:
        print(f"驗證碼已發送到: {email} (代碼: {code})")  # 開發環境顯示，生產環境移除
    
    return success, error


# ========== 清理過期驗證碼 ==========
def cleanup_expired_codes():
    """
    清理過期的驗證碼（定期任務）
    返回：int - 清理數量
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 刪除過期的驗證碼
        current_time = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            DELETE FROM verification_codes
            WHERE expire_time < ?
        ''', (current_time,))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        print(f"已清理 {deleted_count} 條過期驗證碼")
        return deleted_count
        
    except Exception as e:
        print(f"清理失敗: {e}")
        return 0


# ========== 測試程式 ==========
if __name__ == '__main__':
    print("=" * 50)
    print("郵件服務測試")
    print("=" * 50)
    
    # 測試生成驗證碼
    print("\n【生成驗證碼測試】")
    for i in range(5):
        code = generate_verification_code()
        print(f"驗證碼 {i+1}: {code}")
    
    # 測試保存驗證碼
    print("\n【保存驗證碼測試】")
    test_email = "test@example.com"
    test_code = generate_verification_code()
    
    if save_verification_code(test_email, test_code, 'registration'):
        print(f"✅ 驗證碼已保存: {test_code}")
        
        # 測試驗證
        print("\n【驗證驗證碼測試】")
        valid, msg = verify_code(test_email, test_code, 'registration')
        if valid:
            print(f"✅ 驗證成功")
        else:
            print(f"❌ 驗證失敗: {msg}")
        
        # 測試重複驗證（應該失敗）
        valid, msg = verify_code(test_email, test_code, 'registration')
        if not valid:
            print(f"✅ 重複驗證正確阻止: {msg}")
    
    # 測試清理過期驗證碼
    print("\n【清理過期驗證碼測試】")
    count = cleanup_expired_codes()
    
    print("\n⚠️  注意：實際發送郵件需要設置 SMTP 環境變數")
    print("   SMTP_EMAIL=your@gmail.com")
    print("   SMTP_PASSWORD=your-app-password")
    print("\n" + "=" * 50)