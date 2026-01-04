"""
郵件代理服務
功能：Render 通過 PythonAnywhere 的 SMTP 發送郵件（臨時方案）
適用於：Render 無法使用 SMTP，但 PythonAnywhere 可以使用的情況
"""

import requests
import json
from flask import Blueprint, request, jsonify
from typing import Tuple, Optional

# ========== Render 端：發送郵件到 PythonAnywhere 代理 ==========
def send_email_via_proxy(proxy_url: str, to_email: str, subject: str, html_content: str) -> Tuple[bool, str]:
    """
    通過 PythonAnywhere 代理發送郵件（Render 端使用）
    
    參數：
        proxy_url - PythonAnywhere 的代理 API URL
        to_email - 收件人郵箱（可以是字符串或列表）
        subject - 郵件主題
        html_content - HTML 內容
    
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
    try:
        # 準備 JSON 數據
        payload = {
            'to': to_email,
            'subject': subject,
            'html': html_content
        }
        
        # 發送 POST 請求到 PythonAnywhere
        print(f"[Email Proxy] 通過代理發送郵件到: {proxy_url}")
        print(f"[Email Proxy] 收件人: {to_email}")
        
        response = requests.post(
            proxy_url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30  # 30 秒超時
        )
        
        # 檢查響應
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print(f"[Email Proxy] 郵件發送成功（通過代理）")
                return True, ""
            else:
                error_msg = result.get('error', '未知錯誤')
                print(f"[Email Proxy] 郵件發送失敗（代理返回錯誤）: {error_msg}")
                return False, f"代理返回錯誤: {error_msg}"
        else:
            error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
            print(f"[Email Proxy] 郵件發送失敗（HTTP 錯誤）: {error_msg}")
            return False, f"HTTP {response.status_code}: {error_msg}"
            
    except requests.exceptions.Timeout:
        error_msg = "代理請求超時（30秒）"
        print(f"[Email Proxy] {error_msg}")
        return False, error_msg
    except requests.exceptions.ConnectionError:
        error_msg = "無法連接到代理服務器"
        print(f"[Email Proxy] {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"代理請求失敗: {str(e)}"
        print(f"[Email Proxy] {error_msg}")
        import traceback
        traceback.print_exc()
        return False, error_msg


# ========== PythonAnywhere 端：接收代理請求並發送郵件 ==========
# 創建 Blueprint（PythonAnywhere 端使用）
email_proxy_bp = Blueprint('email_proxy', __name__, url_prefix='/api/email')


@email_proxy_bp.route('/proxy', methods=['POST'])
def email_proxy():
    """
    郵件代理 API 端點（PythonAnywhere 端使用）
    接收 JSON 請求，使用本地 SMTP 發送郵件
    
    請求格式：
        {
            "to": "email@example.com" 或 ["email1@example.com", "email2@example.com"],
            "subject": "郵件主題",
            "html": "<html>...</html>"
        }
    
    返回：
        {
            "success": true/false,
            "error": "錯誤信息（如果失敗）"
        }
    """
    try:
        # 檢查請求格式
        if not request.is_json:
            return jsonify({
                'success': False,
                'error': '請求必須是 JSON 格式'
            }), 400
        
        data = request.get_json()
        
        # 驗證必要字段
        if 'to' not in data:
            return jsonify({
                'success': False,
                'error': '缺少必要字段: to'
            }), 400
        
        if 'subject' not in data:
            return jsonify({
                'success': False,
                'error': '缺少必要字段: subject'
            }), 400
        
        if 'html' not in data:
            return jsonify({
                'success': False,
                'error': '缺少必要字段: html'
            }), 400
        
        to_email = data['to']
        subject = data['subject']
        html_content = data['html']
        
        print(f"[Email Proxy API] 接收到郵件代理請求")
        print(f"[Email Proxy API] 收件人: {to_email}")
        print(f"[Email Proxy API] 主題: {subject}")
        
        # 導入郵件發送函數（避免循環導入）
        from services.email_service import _send_email_via_smtp
        
        # 發送郵件（使用本地 SMTP）
        success, error = _send_email_via_smtp(to_email, subject, html_content)
        
        if success:
            print(f"[Email Proxy API] 郵件發送成功（通過 SMTP）")
            return jsonify({
                'success': True
            }), 200
        else:
            print(f"[Email Proxy API] 郵件發送失敗: {error}")
            return jsonify({
                'success': False,
                'error': error
            }), 500
            
    except Exception as e:
        error_msg = f"處理代理請求時發生錯誤: {str(e)}"
        print(f"[Email Proxy API] {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': error_msg
        }), 500

