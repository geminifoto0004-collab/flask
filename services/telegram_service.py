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


def send_telegram_photo(bot_token: str, chat_id: str, photo_bytes: bytes, caption: str = "") -> tuple[bool, str]:
    """
    使用 Telegram Bot API 發送圖片
    參數：
        bot_token - Bot Token
        chat_id - Chat ID 或 @channelusername
        photo_bytes - 圖片二進位資料
        caption - 圖片說明文字（可選）
    回傳：(是否成功, 錯誤信息)
    """
    if not bot_token:
        return False, "Telegram Bot Token 未設置"
    if not chat_id:
        return False, "Telegram Chat ID 未設置"
    if not photo_bytes:
        return False, "Telegram 圖片內容為空"

    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    data = {
        "chat_id": chat_id,
        "caption": caption or ""
    }
    files = {
        "photo": ("monitor_report.png", photo_bytes, "image/png")
    }

    try:
        response = requests.post(url, data=data, files=files, timeout=20)
        if response.status_code == 200:
            resp_data = response.json()
            if resp_data.get("ok"):
                return True, ""
            return False, resp_data.get("description", "Telegram 圖片發送失敗")
        return False, f"HTTP {response.status_code}: {response.text[:200]}"
    except requests.exceptions.Timeout:
        return False, "Telegram 圖片請求超時"
    except requests.exceptions.ConnectionError:
        return False, "Telegram 圖片連線失敗"
    except Exception as e:
        return False, f"Telegram 圖片發送異常: {str(e)}"
