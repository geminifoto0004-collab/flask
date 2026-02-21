"""
Telegram 通知服務
"""

import requests


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """
    使用 Telegram Bot API 發送訊息
    參數：
        bot_token - Bot Token
        chat_id - Chat ID 或 @channelusername
        text - 訊息內容
    回傳：(是否成功, 錯誤信息)
    """
    if not bot_token:
        return False, "Telegram Bot Token 未設置"
    if not chat_id:
        return False, "Telegram Chat ID 未設置"
    if not text:
        return False, "Telegram 訊息內容為空"
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                return True, ""
            return False, data.get("description", "Telegram 發送失敗")
        return False, f"HTTP {response.status_code}: {response.text[:200]}"
    except requests.exceptions.Timeout:
        return False, "Telegram 請求超時"
    except requests.exceptions.ConnectionError:
        return False, "Telegram 連線失敗"
    except Exception as e:
        return False, f"Telegram 發送異常: {str(e)}"
