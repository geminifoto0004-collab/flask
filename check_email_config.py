"""
檢查郵件配置腳本
用於驗證 EMAIL_PROVIDER 和 Resend API 配置是否正確
"""

import os
from config import email_config

print("=" * 60)
print("郵件配置檢查")
print("=" * 60)

# 檢查環境變數
print("\n[1] 環境變數檢查：")
email_provider_env = os.environ.get('EMAIL_PROVIDER', '未設置')
print(f"   EMAIL_PROVIDER (環境變數): {email_provider_env}")

resend_api_key_env = os.environ.get('RESEND_API_KEY', '未設置')
resend_from_email_env = os.environ.get('RESEND_FROM_EMAIL', '未設置')
print(f"   RESEND_API_KEY (環境變數): {'已設置' if resend_api_key_env != '未設置' else '未設置'}")
print(f"   RESEND_FROM_EMAIL (環境變數): {resend_from_email_env}")

# 檢查配置類
print("\n[2] 配置類檢查：")
print(f"   email_config.EMAIL_PROVIDER: {email_config.EMAIL_PROVIDER}")
print(f"   email_config.RESEND_API_KEY: {'已設置' if email_config.RESEND_API_KEY else '未設置'}")
print(f"   email_config.RESEND_FROM_EMAIL: {email_config.RESEND_FROM_EMAIL}")

# 判斷配置狀態
print("\n[3] 配置狀態：")
if email_config.EMAIL_PROVIDER.lower() == 'resend':
    print("   [OK] EMAIL_PROVIDER 設置為 'resend'，應該使用 Resend API")
    if email_config.RESEND_API_KEY and email_config.RESEND_FROM_EMAIL:
        print("   [OK] Resend API 配置完整")
    else:
        print("   [ERROR] Resend API 配置不完整")
        if not email_config.RESEND_API_KEY:
            print("      - RESEND_API_KEY 未設置")
        if not email_config.RESEND_FROM_EMAIL:
            print("      - RESEND_FROM_EMAIL 未設置")
elif email_config.EMAIL_PROVIDER.lower() == 'smtp':
    print("   [WARN] EMAIL_PROVIDER 設置為 'smtp'，將使用 SMTP")
elif email_config.EMAIL_PROVIDER.lower() == 'auto':
    print("   [WARN] EMAIL_PROVIDER 設置為 'auto'，將自動檢測（優先 SMTP）")
else:
    print(f"   [ERROR] EMAIL_PROVIDER 設置為未知值: {email_config.EMAIL_PROVIDER}")

# 建議
print("\n[4] 建議：")
if email_config.EMAIL_PROVIDER.lower() != 'resend':
    print("   如果要在 Render 上使用 Resend API，請設置：")
    print("      EMAIL_PROVIDER=resend")
    print("      RESEND_API_KEY=你的_API_Key")
    print("      RESEND_FROM_EMAIL=onboarding@resend.dev")
    print("   然後重新部署應用")

print("\n" + "=" * 60)

