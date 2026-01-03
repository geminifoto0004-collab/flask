"""
測試 SMTP 配置
用於驗證 Gmail SMTP 設置是否正確
"""

import smtplib
from email.mime.text import MIMEText
from config import email_config

def test_smtp():
    """測試 SMTP 連接和認證"""
    print("=" * 50)
    print("SMTP 配置測試")
    print("=" * 50)
    
    print(f"\n📧 SMTP 服務器: {email_config.SMTP_SERVER}:{email_config.SMTP_PORT}")
    print(f"📧 發送郵箱: {email_config.SMTP_EMAIL}")
    print(f"🔑 密碼長度: {len(email_config.SMTP_PASSWORD) if email_config.SMTP_PASSWORD else 0} 字符")
    
    if not email_config.SMTP_EMAIL or not email_config.SMTP_PASSWORD:
        print("\n❌ 錯誤：SMTP_EMAIL 或 SMTP_PASSWORD 未設置")
        return False
    
    if email_config.SMTP_EMAIL == 'your@gmail.com' or email_config.SMTP_PASSWORD == 'your-app-password':
        print("\n❌ 錯誤：請在 config.py 中設置真實的 Gmail 地址和應用密碼")
        return False
    
    print("\n🔄 正在測試 SMTP 連接...")
    
    try:
        # 連接 SMTP 服務器
        print("1. 連接 SMTP 服務器...")
        server = smtplib.SMTP(email_config.SMTP_SERVER, email_config.SMTP_PORT)
        server.set_debuglevel(1)  # 顯示詳細調試信息
        
        print("2. 啟動 TLS...")
        server.starttls()
        
        print("3. 嘗試登入...")
        server.login(email_config.SMTP_EMAIL, email_config.SMTP_PASSWORD)
        
        print("\n✅ SMTP 認證成功！")
        
        # 測試發送郵件
        print("\n4. 測試發送郵件...")
        msg = MIMEText("這是一封測試郵件", 'plain', 'utf-8')
        msg['From'] = email_config.SMTP_EMAIL
        msg['To'] = email_config.SMTP_EMAIL  # 發送給自己
        msg['Subject'] = 'SMTP 測試郵件'
        
        server.send_message(msg)
        server.quit()
        
        print("✅ 測試郵件發送成功！")
        print(f"📬 請檢查 {email_config.SMTP_EMAIL} 的收件箱")
        
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"\n❌ SMTP 認證失敗: {e}")
        print("\n💡 解決方法：")
        print("   1. Gmail 必須使用「應用程式密碼」，不是 Gmail 登入密碼！")
        print("   2. 訪問：https://myaccount.google.com/apppasswords")
        print("   3. 選擇「郵件」和「其他（自定義名稱）」")
        print("   4. 輸入名稱（如「Flask App」）")
        print("   5. 複製生成的 16 位密碼")
        print("   6. 將密碼更新到 config.py 的 SMTP_PASSWORD")
        print("\n⚠️  注意：")
        print("   - 必須先啟用 Gmail 的「兩步驟驗證」")
        print("   - 應用密碼通常是 16 位字符（可能包含空格，可以去掉）")
        return False
        
    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        return False

if __name__ == '__main__':
    test_smtp()

