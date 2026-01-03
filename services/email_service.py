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

from config import email_config
from database import get_db_connection
from utils.time_utils import get_chile_time_naive


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
        cursor = conn.cursor()
        
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
        cursor = conn.cursor()
        
        # 查詢驗證碼
        cursor.execute('''
            SELECT id, expire_time, used FROM verification_codes
            WHERE email=? AND code=? AND purpose=?
            ORDER BY created_at DESC LIMIT 1
        ''', (email, code, purpose))
        
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return False, "驗證碼不正確"
        
        # 檢查是否已使用
        if result['used']:
            conn.close()
            return False, "驗證碼已被使用"
        
        # 檢查是否過期
        expire_time = datetime.strptime(result['expire_time'], '%Y-%m-%d %H:%M:%S')
        if get_chile_time_naive() > expire_time:
            conn.close()
            return False, "驗證碼已過期"
        
        # 標記為已使用
        cursor.execute('UPDATE verification_codes SET used=1 WHERE id=?', (result['id'],))
        conn.commit()
        conn.close()
        
        return True, ""
        
    except Exception as e:
        print(f"驗證碼驗證失敗: {e}")
        return False, "系統錯誤"


# ========== 發送郵件 ==========
def send_email(to_email, subject, html_content):
    """
    發送 HTML 郵件
    參數：
        to_email - 收件人郵箱
        subject - 郵件主題
        html_content - HTML 內容
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
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
        
        if 'timeout' in error_str or 'timed out' in error_str:
            return False, "SMTP 連接超時: 請檢查網絡連接或稍後再試"
        elif 'network is unreachable' in error_str or '101' in error_code:
            # 網絡不可達錯誤，可能是 DNS 解析或網絡配置問題
            # 這是 Render 網絡環境的限制，Gmail SMTP 可能無法訪問
            return False, (
                f"SMTP 網絡不可達: {str(e)}\n\n"
                f"⚠️ 這是 Render 網絡環境的限制，無法訪問 Gmail SMTP 服務器。\n\n"
                f"💡 解決方案：\n"
                f"1. 在 Render 環境變數中設置 SMTP_SERVER 和 SMTP_PORT，嘗試不同的配置\n"
                f"2. 使用其他 SMTP 服務（推薦）：\n"
                f"   - SendGrid（免費 100 封/天）: SMTP_SERVER=smtp.sendgrid.net, SMTP_PORT=587\n"
                f"   - Mailgun（免費 5000 封/月）: SMTP_SERVER=smtp.mailgun.org, SMTP_PORT=587\n"
                f"3. 或暫時禁用郵件功能，使用其他驗證方式\n\n"
                f"當前配置：\n"
                f"- SMTP 服務器: {email_config.SMTP_SERVER}\n"
                f"- 端口: {email_config.SMTP_PORT}\n"
                f"- 郵箱: {email_config.SMTP_EMAIL}"
            )
        elif 'connection refused' in error_str or '111' in error_code:
            return False, "SMTP 連接被拒絕: 請檢查 SMTP 服務器地址和端口是否正確"
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