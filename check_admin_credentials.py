#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
檢查當前超級管理員登入信息
用於確認環境變數和備案值是否一致
"""

import os
import sys

# 添加項目路徑
sys.path.insert(0, os.path.dirname(__file__))

from config import admin_config

def check_admin_credentials():
    """檢查並顯示當前使用的超級管理員登入信息"""
    print("=" * 60)
    print("[ADMIN] Super Admin Login Credentials Check")
    print("=" * 60)
    print()
    
    # 檢查環境變數
    env_email = os.environ.get('SUPER_ADMIN_EMAIL')
    env_password = os.environ.get('SUPER_ADMIN_PASSWORD')
    env_username = os.environ.get('SUPER_ADMIN_USERNAME')
    
    # 備案值
    backup_email = 'admin@xingwang.com'
    backup_password = '12345678'
    backup_username = 'super_admin'
    
    # 當前實際使用的值
    current_email = admin_config.SUPER_ADMIN_EMAIL
    current_password = admin_config.SUPER_ADMIN_PASSWORD
    current_username = admin_config.SUPER_ADMIN_USERNAME
    
    print("[1] Environment Variables Status:")
    print(f"   SUPER_ADMIN_EMAIL:     {env_email if env_email else '[NOT SET] Using backup value'}")
    print(f"   SUPER_ADMIN_PASSWORD:  {'[SET] Hidden' if env_password else '[NOT SET] Using backup value'}")
    print(f"   SUPER_ADMIN_USERNAME:  {env_username if env_username else '[NOT SET] Using backup value'}")
    print()
    
    print("[2] Backup Values (config.py line 40):")
    print(f"   Email: {backup_email}")
    print(f"   Password: {backup_password}")
    print(f"   Username: {backup_username}")
    print()
    
    print("[3] Current Active Login Credentials:")
    print(f"   Email: {current_email}")
    print(f"   Password: {current_password}")
    print(f"   Username: {current_username}")
    print()
    
    # 檢查是否一致
    print("[4] Consistency Check:")
    email_match = (env_email is None and current_email == backup_email) or (env_email == current_email)
    password_match = (env_password is None and current_password == backup_password) or (env_password == current_password)
    username_match = (env_username is None and current_username == backup_username) or (env_username == current_username)
    
    if email_match and password_match and username_match:
        print("   [OK] Environment variables and backup values are consistent, or using backup values")
    else:
        print("   [WARNING] Environment variables and backup values are INCONSISTENT!")
        if not email_match:
            print(f"      - Email mismatch: ENV={env_email}, Backup={backup_email}, Current={current_email}")
        if not password_match:
            print(f"      - Password mismatch: ENV is set but different from backup, currently using ENV value")
        if not username_match:
            print(f"      - Username mismatch: ENV={env_username}, Backup={backup_username}, Current={current_username}")
    print()
    
    print("[5] Login Instructions:")
    print(f"   Use the following credentials to login:")
    print(f"   Email: {current_email}")
    print(f"   Password: {current_password}")
    print()
    
    print("[6] Backup Location:")
    print("   File: config.py")
    print("   Line: 40")
    print("   Documentation: ADMIN_BACKUP_CREDENTIALS.md")
    print()
    
    print("=" * 60)
    
    return {
        'email': current_email,
        'password': current_password,
        'username': current_username,
        'using_env': env_password is not None,
        'matches_backup': password_match
    }

if __name__ == '__main__':
    try:
        result = check_admin_credentials()
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] Check failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

