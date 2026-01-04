"""
郵件代理功能測試腳本
用於測試 PythonAnywhere 的郵件代理 API 是否正常工作
"""

import requests
import json
import sys
import os
from datetime import datetime

# 設置 Windows 控制台編碼（避免 emoji 顯示問題）
if sys.platform == 'win32':
    try:
        os.system('chcp 65001 >nul 2>&1')  # 設置為 UTF-8
    except:
        pass

# 配置
PYANYWHERE_URL = "https://xingwangtextil.pythonanywhere.com"
PROXY_ENDPOINT = f"{PYANYWHERE_URL}/api/email/proxy"

# 測試郵箱（請修改為您的測試郵箱）
TEST_EMAIL = "geminifoto0004@gmail.com"  # 👈 請修改為您的測試郵箱


def test_proxy_endpoint():
    """測試代理端點是否存在"""
    print("=" * 60)
    print("測試 1: 檢查代理端點是否存在")
    print("=" * 60)
    
    try:
        # 發送一個空的請求，應該返回錯誤（但能證明端點存在）
        response = requests.post(
            PROXY_ENDPOINT,
            json={},
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        print(f"狀態碼: {response.status_code}")
        print(f"響應: {response.json()}")
        
        if response.status_code == 400:
            print("[成功] 端點存在！返回了預期的錯誤（缺少參數）")
            return True
        else:
            print(f"[警告] 端點返回了意外的狀態碼: {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("[錯誤] 無法連接到服務器，請檢查 URL 是否正確")
        return False
    except requests.exceptions.Timeout:
        print("[錯誤] 請求超時，請檢查服務器是否正常運行")
        return False
    except Exception as e:
        print(f"[錯誤] 測試失敗: {e}")
        return False


def test_send_email():
    """測試發送郵件"""
    print("\n" + "=" * 60)
    print("測試 2: 測試發送郵件")
    print("=" * 60)
    
    # 準備郵件數據
    payload = {
        "to": TEST_EMAIL,
        "subject": f"郵件代理測試 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "html": f"""
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
                    color: #667eea;
                    margin-bottom: 30px;
                }}
                .success {{
                    background-color: #d4edda;
                    color: #155724;
                    padding: 15px;
                    border-radius: 5px;
                    margin: 20px 0;
                }}
                .info {{
                    background-color: #d1ecf1;
                    color: #0c5460;
                    padding: 15px;
                    border-radius: 5px;
                    margin: 20px 0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>✅ 郵件代理測試成功！</h1>
                </div>
                
                <div class="success">
                    <strong>恭喜！</strong> 如果您收到這封郵件，說明 PythonAnywhere 的郵件代理功能正常工作。
                </div>
                
                <div class="info">
                    <h3>測試信息：</h3>
                    <ul>
                        <li><strong>測試時間：</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</li>
                        <li><strong>代理端點：</strong> {PROXY_ENDPOINT}</li>
                        <li><strong>發送方式：</strong> PythonAnywhere SMTP</li>
                    </ul>
                </div>
                
                <p>這是一封測試郵件，用於驗證郵件代理功能是否正常工作。</p>
                
                <p style="color: #999; font-size: 12px; margin-top: 30px;">
                    此郵件由系統自動發送，請勿回復
                </p>
            </div>
        </body>
        </html>
        """
    }
    
    print(f"發送到: {TEST_EMAIL}")
    print(f"主題: {payload['subject']}")
    print(f"端點: {PROXY_ENDPOINT}")
    print("\n正在發送...")
    
    try:
        response = requests.post(
            PROXY_ENDPOINT,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        print(f"\n狀態碼: {response.status_code}")
        
        try:
            result = response.json()
            print(f"響應: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            if result.get('success'):
                print("\n[成功] 郵件發送成功！")
                print(f"       請檢查郵箱: {TEST_EMAIL}")
                return True
            else:
                print(f"\n[錯誤] 郵件發送失敗: {result.get('error', '未知錯誤')}")
                return False
                
        except json.JSONDecodeError:
            print(f"[錯誤] 響應不是有效的 JSON: {response.text[:200]}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("[錯誤] 無法連接到服務器")
        return False
    except requests.exceptions.Timeout:
        print("[錯誤] 請求超時（30秒）")
        return False
    except Exception as e:
        print(f"[錯誤] 測試失敗: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函數"""
    global TEST_EMAIL
    
    # 如果提供了命令行參數，使用它作為測試郵箱
    if len(sys.argv) > 1:
        TEST_EMAIL = sys.argv[1]
    
    print("\n" + "=" * 60)
    print("郵件代理功能測試")
    print("=" * 60)
    print(f"PythonAnywhere URL: {PYANYWHERE_URL}")
    print(f"測試郵箱: {TEST_EMAIL}")
    print(f"代理端點: {PROXY_ENDPOINT}")
    print("\n" + "=" * 60)
    
    # 檢查是否提供了測試郵箱
    if TEST_EMAIL == "geminifoto0004@gmail.com":
        print("[!] 請在腳本中修改 TEST_EMAIL 為您的測試郵箱")
        print("    或者通過命令行參數提供: python test_email_proxy.py your_email@example.com")
        print()
    
    if len(sys.argv) > 1:
        print(f"使用命令行參數中的郵箱: {TEST_EMAIL}\n")
    
    # 執行測試
    test1_passed = test_proxy_endpoint()
    
    if test1_passed:
        print("\n" + "-" * 60)
        input("按 Enter 繼續測試發送郵件（或 Ctrl+C 取消）...")
        test2_passed = test_send_email()
        
        print("\n" + "=" * 60)
        print("測試結果總結")
        print("=" * 60)
        print(f"端點測試: {'[通過]' if test1_passed else '[失敗]'}")
        print(f"發送測試: {'[通過]' if test2_passed else '[失敗]'}")
        
        if test1_passed and test2_passed:
            print("\n[成功] 所有測試通過！郵件代理功能正常工作。")
        else:
            print("\n[警告] 部分測試失敗，請檢查 PythonAnywhere 的配置和日誌。")
    else:
        print("\n[錯誤] 端點測試失敗，請先確保代理端點已正確啟用。")
        print("       檢查 app.py 中是否已取消註釋 email_proxy_bp 的註冊")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n測試已取消")
    except Exception as e:
        print(f"\n[錯誤] 發生錯誤: {e}")
        import traceback
        traceback.print_exc()

