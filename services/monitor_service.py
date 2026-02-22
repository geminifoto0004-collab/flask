"""
監控服務模組
功能：ITI/ZOFRI 監控檢查、任務管理、郵件通知
"""

import json
import hashlib
import uuid
import io
import re
import os
from pathlib import Path
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from jinja2 import Environment, FileSystemLoader, select_autoescape
from urllib.parse import quote

from database import get_db_connection, get_lastrowid
from services.email_service import send_email
from services.telegram_service import send_telegram_message, send_telegram_photo
from services.zofri_iti_service import (
    process_data
)
from services.unified_iti_service import get_unified_iti_legacy_rows_fresh
from utils.time_utils import get_chile_time_naive

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


ALLOWED_TELEGRAM_MODES = {"text", "image", "both"}


# ========== 生成 API Key ==========
def generate_api_key() -> str:
    """生成唯一的 API Key"""
    return str(uuid.uuid4()).replace('-', '')


# ========== 加密密碼 ==========
def hash_password(password: str) -> str:
    """使用 SHA256 加密密碼"""
    return hashlib.sha256(password.encode()).hexdigest()


def compute_result_hash(result: Dict) -> str:
    """計算監控結果的穩定 Hash"""
    try:
        payload = json.dumps(result, sort_keys=True, default=str)
    except Exception:
        payload = str(result)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def normalize_telegram_mode(mode: Optional[str]) -> str:
    """Normalize telegram mode to text/image/both."""
    if not mode:
        return "text"
    normalized = str(mode).strip().lower()
    if normalized not in ALLOWED_TELEGRAM_MODES:
        return "text"
    return normalized


def normalize_telegram_max_rows(value, default: int = 200) -> int:
    """Clamp telegram rows to a safe range."""
    try:
        rows = int(value)
    except Exception:
        rows = default
    return max(10, min(rows, 1000))


def resolve_public_base_url(explicit_base_url: Optional[str] = None) -> str:
    """Resolve public base URL for external links."""
    candidates = [
        explicit_base_url,
        os.environ.get("PUBLIC_BASE_URL"),
        os.environ.get("APP_BASE_URL"),
        os.environ.get("RENDER_EXTERNAL_URL"),
    ]
    for candidate in candidates:
        if candidate:
            return str(candidate).strip().rstrip("/")
    return ""


def build_monitor_report_url(api_key: str, base_url: Optional[str] = None) -> str:
    """Build public monitor report URL bound to monitor api_key."""
    base = resolve_public_base_url(base_url)
    key = (api_key or "").strip()
    if not base or not key:
        return ""
    return f"{base}/monitor/report?api_key={quote(key)}"


# ========== 創建監控任務 ==========
def create_monitor_task(
    user_id: int,
    zofri_username: str,
    zofri_password: str,
    zofri_rut_entidad: str,
    zofri_rut_representante: str = '',
    notification_emails: List[str] = None,
    company_name: str = None,
    email_subject: str = None,
    notify_email: bool = True,
    notify_telegram: bool = False,
    telegram_bot_token: str = None,
    telegram_chat_id: str = None,
    telegram_mode: str = "text",
    telegram_include_matched: bool = True,
    telegram_include_unmatched: bool = True,
    telegram_max_rows: int = 200
) -> Tuple[bool, str]:
    """
    創建監控任務
    返回：(是否成功, 錯誤信息或任務ID)
    """
    if not company_name:
        return False, "請設置公司名稱（company_name）"
    
    if not notify_email and not notify_telegram:
        return False, "至少需要選擇一種通知方式"
    
    if notify_email and not notification_emails:
        return False, "至少需要一個通知郵箱"
    
    if notify_telegram and (not telegram_bot_token or not telegram_chat_id):
        return False, "Telegram Bot Token 或 Chat ID 未設置"

    telegram_mode = normalize_telegram_mode(telegram_mode)
    telegram_max_rows = normalize_telegram_max_rows(telegram_max_rows)
    if notify_telegram and not telegram_include_matched and not telegram_include_unmatched:
        return False, "Telegram 至少要選擇顯示匹配或未匹配"
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 生成 API Key
        api_key = generate_api_key()
        
        # 注意：密碼暫時不加密存儲（因為 ZOFRI 登錄需要原始密碼）
        # TODO: 後續改為使用 AES 可逆加密
        
        # 將郵箱列表轉為 JSON
        emails_json = json.dumps(notification_emails or [])
        
        cursor.execute('''
            INSERT INTO user_monitor_configs 
            (user_id, api_key, zofri_username, zofri_password, zofri_rut_entidad, 
             zofri_rut_representante, notification_emails, company_name, email_subject, 
             notify_email, notify_telegram, telegram_bot_token, telegram_chat_id,
             telegram_mode, telegram_include_matched, telegram_include_unmatched, telegram_max_rows, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (user_id, api_key, zofri_username, zofri_password, zofri_rut_entidad,
              zofri_rut_representante, emails_json, company_name, email_subject,
              1 if notify_email else 0, 1 if notify_telegram else 0, telegram_bot_token, telegram_chat_id,
              telegram_mode, 1 if telegram_include_matched else 0, 1 if telegram_include_unmatched else 0, telegram_max_rows))
        
        task_id = get_lastrowid(cursor, conn)
        conn.commit()
        conn.close()
        
        return True, str(task_id)
        
    except Exception as e:
        return False, f"創建失敗: {str(e)}"


# ========== 獲取用戶的監控任務 ==========
def get_user_monitor_tasks(user_id: int) -> List[Dict]:
    """獲取用戶的所有監控任務"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, api_key, zofri_username, zofri_rut_entidad, 
                   notification_emails, last_check_time, is_active, created_at,
                   notify_email, notify_telegram, telegram_chat_id,
                   telegram_mode, telegram_include_matched, telegram_include_unmatched, telegram_max_rows
            FROM user_monitor_configs
            WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (user_id,))
        
        tasks = []
        for row in cursor.fetchall():
            task = dict(row)
            # 解析郵箱列表
            task['notification_emails'] = json.loads(task['notification_emails'] or '[]')
            task['notify_email'] = True if task.get('notify_email') is None else bool(task.get('notify_email'))
            task['notify_telegram'] = bool(task.get('notify_telegram'))
            task['telegram_mode'] = normalize_telegram_mode(task.get('telegram_mode'))
            task['telegram_include_matched'] = True if task.get('telegram_include_matched') is None else bool(task.get('telegram_include_matched'))
            task['telegram_include_unmatched'] = True if task.get('telegram_include_unmatched') is None else bool(task.get('telegram_include_unmatched'))
            task['telegram_max_rows'] = normalize_telegram_max_rows(task.get('telegram_max_rows', 200))
            tasks.append(task)
        
        conn.close()
        return tasks
        
    except Exception as e:
        print(f"獲取任務失敗: {e}")
        return []


# ========== 獲取單個任務 ==========
def get_all_monitor_tasks_admin(
    keyword: str = "",
    status: str = "all",
    user_id: Optional[int] = None,
    limit: int = 500,
) -> List[Dict]:
    """
    Admin view: list monitor tasks across all users.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        where = []
        params: List[Any] = []

        if user_id is not None:
            where.append("umc.user_id = ?")
            params.append(int(user_id))

        normalized_status = (status or "all").strip().lower()
        if normalized_status == "active":
            where.append("umc.is_active = 1")
        elif normalized_status == "inactive":
            where.append("umc.is_active = 0")

        keyword = (keyword or "").strip()
        if keyword:
            where.append(
                "(u.username LIKE ? OR u.email LIKE ? OR umc.company_name LIKE ? OR umc.zofri_username LIKE ? OR umc.zofri_rut_entidad LIKE ?)"
            )
            like = f"%{keyword}%"
            params.extend([like, like, like, like, like])

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        limit = max(1, min(int(limit or 500), 2000))

        query = f"""
            SELECT
                umc.*,
                u.username AS user_username,
                u.email AS user_email
            FROM user_monitor_configs umc
            LEFT JOIN users u ON umc.user_id = u.id
            {where_sql}
            ORDER BY umc.updated_at DESC, umc.id DESC
            LIMIT ?
        """
        cursor.execute(query, (*params, limit))

        rows = cursor.fetchall() or []
        conn.close()

        tasks: List[Dict] = []
        for row in rows:
            task = dict(row)
            task['notification_emails'] = json.loads(task.get('notification_emails') or '[]')
            task['notify_email'] = True if task.get('notify_email') is None else bool(task.get('notify_email'))
            task['notify_telegram'] = bool(task.get('notify_telegram'))
            task['telegram_mode'] = normalize_telegram_mode(task.get('telegram_mode'))
            task['telegram_include_matched'] = True if task.get('telegram_include_matched') is None else bool(task.get('telegram_include_matched'))
            task['telegram_include_unmatched'] = True if task.get('telegram_include_unmatched') is None else bool(task.get('telegram_include_unmatched'))
            task['telegram_max_rows'] = normalize_telegram_max_rows(task.get('telegram_max_rows', 200))
            task.pop('zofri_password', None)
            task.pop('telegram_bot_token', None)
            tasks.append(task)

        return tasks
    except Exception as e:
        print(f"[monitor] get_all_monitor_tasks_admin failed: {e}")
        return []


def get_monitor_task(task_id: int, user_id: int = None) -> Optional[Dict]:
    """獲取單個監控任務（可選用戶ID驗證）"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if user_id:
            cursor.execute('''
                SELECT * FROM user_monitor_configs
                WHERE id = ? AND user_id = ?
            ''', (task_id, user_id))
        else:
            cursor.execute('''
                SELECT * FROM user_monitor_configs
                WHERE id = ?
            ''', (task_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            task = dict(row)
            task['notification_emails'] = json.loads(task['notification_emails'] or '[]')
            task['notify_email'] = True if task.get('notify_email') is None else bool(task.get('notify_email'))
            task['notify_telegram'] = bool(task.get('notify_telegram'))
            task['telegram_mode'] = normalize_telegram_mode(task.get('telegram_mode'))
            task['telegram_include_matched'] = True if task.get('telegram_include_matched') is None else bool(task.get('telegram_include_matched'))
            task['telegram_include_unmatched'] = True if task.get('telegram_include_unmatched') is None else bool(task.get('telegram_include_unmatched'))
            task['telegram_max_rows'] = normalize_telegram_max_rows(task.get('telegram_max_rows', 200))
            return task
        return None
        
    except Exception as e:
        print(f"獲取任務失敗: {e}")
        return None


# ========== 更新監控任務 ==========
def update_monitor_task(
    task_id: int,
    user_id: int,
    zofri_username: str = None,
    zofri_password: str = None,
    zofri_rut_entidad: str = None,
    zofri_rut_representante: str = None,
    notification_emails: List[str] = None,
    company_name: str = None,
    email_subject: str = None,
    notify_email: bool = None,
    notify_telegram: bool = None,
    telegram_bot_token: str = None,
    telegram_chat_id: str = None,
    telegram_mode: str = None,
    telegram_include_matched: bool = None,
    telegram_include_unmatched: bool = None,
    telegram_max_rows: int = None,
    is_active: bool = None
) -> Tuple[bool, str]:
    """更新監控任務"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 檢查任務是否存在且屬於該用戶
        cursor.execute('''
            SELECT id, notification_emails, notify_email, notify_telegram, telegram_bot_token, telegram_chat_id,
                   telegram_mode, telegram_include_matched, telegram_include_unmatched, telegram_max_rows
            FROM user_monitor_configs
            WHERE id = ? AND user_id = ?
        ''', (task_id, user_id))
        existing = cursor.fetchone()
        if not existing:
            conn.close()
            return False, "任務不存在或無權限"
        
        if isinstance(existing, dict):
            existing_emails = json.loads(existing.get('notification_emails') or '[]')
            existing_notify_email = True if existing.get('notify_email') is None else bool(existing.get('notify_email'))
            existing_notify_telegram = bool(existing.get('notify_telegram'))
            existing_token = existing.get('telegram_bot_token')
            existing_chat_id = existing.get('telegram_chat_id')
            existing_mode = normalize_telegram_mode(existing.get('telegram_mode'))
            existing_include_matched = True if existing.get('telegram_include_matched') is None else bool(existing.get('telegram_include_matched'))
            existing_include_unmatched = True if existing.get('telegram_include_unmatched') is None else bool(existing.get('telegram_include_unmatched'))
            existing_max_rows = normalize_telegram_max_rows(existing.get('telegram_max_rows', 200))
        else:
            existing_emails = json.loads(existing[1] or '[]')
            existing_notify_email = True if existing[2] is None else bool(existing[2])
            existing_notify_telegram = bool(existing[3])
            existing_token = existing[4]
            existing_chat_id = existing[5]
            existing_mode = normalize_telegram_mode(existing[6] if len(existing) > 6 else 'text')
            existing_include_matched = True if (len(existing) <= 7 or existing[7] is None) else bool(existing[7])
            existing_include_unmatched = True if (len(existing) <= 8 or existing[8] is None) else bool(existing[8])
            existing_max_rows = normalize_telegram_max_rows(existing[9] if len(existing) > 9 else 200)
        
        # 構建更新語句
        updates = []
        params = []
        
        if zofri_username:
            updates.append('zofri_username = ?')
            params.append(zofri_username)
        
        if zofri_password:
            updates.append('zofri_password = ?')
            params.append(zofri_password)  # 暫時不加密
        
        if zofri_rut_entidad:
            updates.append('zofri_rut_entidad = ?')
            params.append(zofri_rut_entidad)
        
        if zofri_rut_representante is not None:
            updates.append('zofri_rut_representante = ?')
            params.append(zofri_rut_representante)
        
        if notification_emails is not None:
            updates.append('notification_emails = ?')
            params.append(json.dumps(notification_emails))
        
        if company_name is not None:
            updates.append('company_name = ?')
            params.append(company_name)
        
        if email_subject is not None:
            updates.append('email_subject = ?')
            params.append(email_subject)
        
        if notify_email is not None:
            updates.append('notify_email = ?')
            params.append(1 if notify_email else 0)
        
        if notify_telegram is not None:
            updates.append('notify_telegram = ?')
            params.append(1 if notify_telegram else 0)
        
        if telegram_bot_token:
            updates.append('telegram_bot_token = ?')
            params.append(telegram_bot_token)
        
        if telegram_chat_id:
            updates.append('telegram_chat_id = ?')
            params.append(telegram_chat_id)

        if telegram_mode is not None:
            updates.append('telegram_mode = ?')
            params.append(normalize_telegram_mode(telegram_mode))

        if telegram_include_matched is not None:
            updates.append('telegram_include_matched = ?')
            params.append(1 if telegram_include_matched else 0)

        if telegram_include_unmatched is not None:
            updates.append('telegram_include_unmatched = ?')
            params.append(1 if telegram_include_unmatched else 0)

        if telegram_max_rows is not None:
            updates.append('telegram_max_rows = ?')
            params.append(normalize_telegram_max_rows(telegram_max_rows))
        
        if is_active is not None:
            updates.append('is_active = ?')
            params.append(1 if is_active else 0)
        
        # 驗證通知配置
        final_notify_email = existing_notify_email if notify_email is None else notify_email
        final_notify_telegram = existing_notify_telegram if notify_telegram is None else notify_telegram
        final_emails = existing_emails if notification_emails is None else notification_emails
        final_token = telegram_bot_token if telegram_bot_token else existing_token
        final_chat_id = telegram_chat_id if telegram_chat_id else existing_chat_id
        final_mode = existing_mode if telegram_mode is None else normalize_telegram_mode(telegram_mode)
        final_include_matched = existing_include_matched if telegram_include_matched is None else bool(telegram_include_matched)
        final_include_unmatched = existing_include_unmatched if telegram_include_unmatched is None else bool(telegram_include_unmatched)
        final_max_rows = existing_max_rows if telegram_max_rows is None else normalize_telegram_max_rows(telegram_max_rows)
        
        if not final_notify_email and not final_notify_telegram:
            conn.close()
            return False, "至少需要選擇一種通知方式"
        
        if final_notify_email and not final_emails:
            conn.close()
            return False, "至少需要一個通知郵箱"
        
        if final_notify_telegram and (not final_token or not final_chat_id):
            conn.close()
            return False, "Telegram Bot Token 或 Chat ID 未設置"

        if final_notify_telegram and final_mode not in ALLOWED_TELEGRAM_MODES:
            conn.close()
            return False, "Telegram 模式不正確"

        if final_notify_telegram and not final_include_matched and not final_include_unmatched:
            conn.close()
            return False, "Telegram 至少要選擇顯示匹配或未匹配"

        if final_notify_telegram and final_max_rows < 10:
            conn.close()
            return False, "Telegram 顯示筆數至少為 10"
        
        if not updates:
            conn.close()
            return False, "沒有需要更新的字段"
        
        # 若切換通知方式或變更通知目標，重置對應的發送記錄
        if (notify_email is not None and notify_email and not existing_notify_email) or (notification_emails is not None):
            updates.append('last_email_result_hash = NULL')

        reset_telegram_hash = False
        if (notify_telegram is not None and notify_telegram and not existing_notify_telegram) or (telegram_bot_token or telegram_chat_id):
            reset_telegram_hash = True
        if telegram_mode is not None or telegram_include_matched is not None or telegram_include_unmatched is not None or telegram_max_rows is not None:
            reset_telegram_hash = True
        if reset_telegram_hash:
            updates.append('last_telegram_result_hash = NULL')
        
        updates.append('updated_at = ?')
        params.append(get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S'))
        params.append(task_id)
        
        cursor.execute(f'''
            UPDATE user_monitor_configs
            SET {', '.join(updates)}
            WHERE id = ?
        ''', params)
        
        conn.commit()
        conn.close()
        
        return True, "更新成功"
        
    except Exception as e:
        return False, f"更新失敗: {str(e)}"


# ========== 刪除監控任務 ==========
def delete_monitor_task(task_id: int, user_id: int) -> Tuple[bool, str]:
    """刪除監控任務"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 檢查任務是否存在且屬於該用戶
        cursor.execute('SELECT id FROM user_monitor_configs WHERE id = ? AND user_id = ?', 
                      (task_id, user_id))
        if not cursor.fetchone():
            conn.close()
            return False, "任務不存在或無權限"
        
        cursor.execute('DELETE FROM user_monitor_configs WHERE id = ?', (task_id,))
        conn.commit()
        conn.close()
        
        return True, "刪除成功"
        
    except Exception as e:
        return False, f"刪除失敗: {str(e)}"


# ========== 清空任務的檢查歷史 ==========
def clear_check_history(task_id: int, user_id: int = None) -> Tuple[bool, str]:
    """
    清空任務的檢查歷史（將 last_check_result 設為 NULL）
    返回：(是否成功, 錯誤信息)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if user_id:
            # 檢查任務是否存在且屬於該用戶
            cursor.execute('SELECT id FROM user_monitor_configs WHERE id = ? AND user_id = ?', 
                          (task_id, user_id))
            if not cursor.fetchone():
                conn.close()
                return False, "任務不存在或無權限"
            
            cursor.execute('''
                UPDATE user_monitor_configs
                SET last_check_result = NULL,
                    last_check_time = NULL,
                    last_email_result_hash = NULL,
                    last_telegram_result_hash = NULL
                WHERE id = ? AND user_id = ?
            ''', (task_id, user_id))
        else:
            cursor.execute('''
                UPDATE user_monitor_configs
                SET last_check_result = NULL,
                    last_check_time = NULL,
                    last_email_result_hash = NULL,
                    last_telegram_result_hash = NULL
                WHERE id = ?
            ''', (task_id,))
        
        conn.commit()
        conn.close()
        return True, "檢查歷史已清空"
        
    except Exception as e:
        return False, f"清空失敗: {str(e)}"


# ========== 根據 API Key 獲取任務 ==========
def get_task_by_api_key(api_key: str) -> Optional[Dict]:
    """根據 API Key 獲取任務配置"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM user_monitor_configs
            WHERE api_key = ? AND is_active = 1
        ''', (api_key,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            task = dict(row)
            task['notification_emails'] = json.loads(task['notification_emails'] or '[]')
            task['notify_email'] = True if task.get('notify_email') is None else bool(task.get('notify_email'))
            task['notify_telegram'] = bool(task.get('notify_telegram'))
            task['telegram_mode'] = normalize_telegram_mode(task.get('telegram_mode'))
            task['telegram_include_matched'] = True if task.get('telegram_include_matched') is None else bool(task.get('telegram_include_matched'))
            task['telegram_include_unmatched'] = True if task.get('telegram_include_unmatched') is None else bool(task.get('telegram_include_unmatched'))
            task['telegram_max_rows'] = normalize_telegram_max_rows(task.get('telegram_max_rows', 200))
            return task
        return None
        
    except Exception as e:
        print(f"獲取任務失敗: {e}")
        return None


# ========== 使用任務配置登錄 ZOFRI ==========
def get_all_active_monitor_tasks(limit: Optional[int] = None) -> List[Dict]:
    """
    Get all active monitor tasks for centralized check-all cron flow.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if limit and int(limit) > 0:
            cursor.execute(
                """
                SELECT * FROM user_monitor_configs
                WHERE is_active = 1
                ORDER BY id ASC
                LIMIT ?
                """,
                (int(limit),)
            )
        else:
            cursor.execute(
                """
                SELECT * FROM user_monitor_configs
                WHERE is_active = 1
                ORDER BY id ASC
                """
            )

        rows = cursor.fetchall() or []
        conn.close()

        tasks: List[Dict] = []
        for row in rows:
            task = dict(row)
            task['notification_emails'] = json.loads(task.get('notification_emails') or '[]')
            task['notify_email'] = True if task.get('notify_email') is None else bool(task.get('notify_email'))
            task['notify_telegram'] = bool(task.get('notify_telegram'))
            task['telegram_mode'] = normalize_telegram_mode(task.get('telegram_mode'))
            task['telegram_include_matched'] = True if task.get('telegram_include_matched') is None else bool(task.get('telegram_include_matched'))
            task['telegram_include_unmatched'] = True if task.get('telegram_include_unmatched') is None else bool(task.get('telegram_include_unmatched'))
            task['telegram_max_rows'] = normalize_telegram_max_rows(task.get('telegram_max_rows', 200))
            tasks.append(task)

        return tasks
    except Exception as e:
        print(f"[monitor] get_all_active_monitor_tasks failed: {e}")
        return []


def login_zofri_with_config(task_config: Dict) -> Tuple[bool, Dict, str]:
    """
    使用任務配置登錄 ZOFRI
    返回：(是否成功, cookies字典, 錯誤信息)
    注意：這裡假設密碼在數據庫中是加密的，需要解密
    但為了簡化，暫時先從數據庫讀取時不解密（後續需要實現）
    """
    try:
        session = requests.Session()
        login_url = 'https://zvirtual.zofri.cl/controller?accion=login'
        
        # 注意：這裡需要從數據庫讀取原始密碼或解密
        # 目前先假設 task_config 中已經有正確的密碼
        login_data = {
            'usuario': task_config['zofri_username'],
            'clave': task_config['zofri_password'],  # 使用用戶輸入的密碼（從數據庫讀取）
            'rutEntidad': task_config['zofri_rut_entidad'],
            'rutRepresentante': '',  # 不使用 RUT 代表
            'identificador': 'zsve',
            'tipoUsuario': 'TUSU3'
        }
        
        response = session.post(login_url, data=login_data, verify=False, timeout=10)
        if response.status_code != 200 or 'success' not in response.text:
            return False, {}, "ZOFRI 登錄失敗，請檢查賬號密碼"
        
        cookies_dict = {cookie.name: cookie.value for cookie in session.cookies}
        return True, cookies_dict, ""
        
    except Exception as e:
        return False, {}, f"登錄失敗: {str(e)}"


# ========== 執行監控檢查 ==========
def check_monitor_task(task_config: Dict) -> Tuple[bool, Dict, str]:
    """
    執行監控檢查
    返回：(是否成功, 檢查結果, 錯誤信息)
    """
    import uuid
    execution_id = str(uuid.uuid4())[:8]  # 生成唯一執行ID用於追蹤
    print(f"[監控檢查-{execution_id}] 開始執行監控檢查，任務ID: {task_config.get('id', 'N/A')}")
    
    try:
        # 1. 使用任務配置登錄 ZOFRI
        login_success, cookies_dict, error = login_zofri_with_config(task_config)
        if not login_success:
            return False, {}, error
        
        # 2. 獲取 ZOFRI 數據（28天內）
        
        today = get_chile_time_naive()
        end_date = today.strftime('%Y-%m-%d')
        start_date = (today - timedelta(days=28)).strftime('%Y-%m-%d')
        
        # 手動實現 fetch_tickets 邏輯（使用傳入的 cookies）
        busqueda_url = "https://zvirtual.zofri.cl/controller?accion=busquedaDocumentosSolicitar"
        data_busqueda = {
            "rutEmpresa": task_config['zofri_rut_entidad'],
            "formato": "json",
            "fechaDesde": start_date,
            "fechaHasta": end_date
        }
        
        time.sleep(3)  # ZOFRI 需要時間準備
        
        try:
            r = requests.post(busqueda_url, json=data_busqueda, cookies=cookies_dict, verify=False, timeout=10)
            r.raise_for_status()
            j = r.json()
            ticket = j.get("data", {}).get("entity", {}).get("ticket")
        except:
            ticket = None
        
        # 輪詢獲取 ticket
        if not ticket:
            for i in range(12):
                time.sleep(2)
                try:
                    r = requests.post(busqueda_url, json=data_busqueda, cookies=cookies_dict, verify=False, timeout=10)
                    j = r.json()
                    ticket = j.get("data", {}).get("entity", {}).get("ticket")
                    if ticket:
                        break
                except:
                    pass
        
        if not ticket:
            return False, {}, "無法獲取 ZOFRI ticket"
        
        # 3. 獲取文檔數據（手動實現，使用傳入的 cookies）
        url = f"https://zvirtual.zofri.cl/controller?accion=busquedaDocumentosObtener&idSolicitud={ticket}&"
        
        for attempt in range(12):
            time.sleep(2)
            try:
                r = requests.get(url, cookies=cookies_dict, verify=False, timeout=10)
                if not r.text.strip().startswith("{"):
                    continue
                
                j = r.json()
                if j.get("status") == "fail":
                    continue
                
                # 處理數據（需要傳遞 cookies_dict）
                df_zofri = process_data(j, cookies_dict)
                if df_zofri is not None and not df_zofri.empty:
                    break
            except:
                continue
        else:
            return True, {
                'containers': [],
                'matched_count': 0,
                'unmatched_count': 0
            }, ""
        
        if df_zofri is None or df_zofri.empty:
            return True, {
                'containers': [],
                'matched_count': 0,
                'unmatched_count': 0
            }, ""
        
        # 4. 獲取 ITI 數據並匹配
        print(f"[監控檢查-{execution_id}] ZOFRI 容器總數: {len(df_zofri)}")
        
        iti_max_age_seconds = int(os.environ.get("MONITOR_ITI_MAX_AGE_SECONDS", "300"))
        iti_results, iti_cache_meta = get_unified_iti_legacy_rows_fresh(
            max_age_seconds=iti_max_age_seconds
        )
        print(
            f"[監控檢查-{execution_id}] ITI cache age={iti_cache_meta.get('age_seconds')}s, "
            f"refreshed={iti_cache_meta.get('refreshed')}"
        )
        
        matched_data = pd.DataFrame()
        matched_indices = pd.Series([False] * len(df_zofri), index=df_zofri.index)
        iti_info_map = {}  # 存儲匹配的 ITI 信息：{index: {iti_item, vessel_name, fecha}}
        
        for iti_item in iti_results:
            if len(iti_item) == 7:
                iti_codigo = (iti_item[2] + iti_item[3] + iti_item[4]).strip()
                # 使用 _container_number 進行匹配
                if '_container_number' not in df_zofri.columns:
                    # 如果沒有 _container_number，回退到使用 glosa_codigo
                    df_zofri['_container_number'] = df_zofri['glosa_codigo']
                df_zofri['_container_number'] = df_zofri['_container_number'].astype(str).str.strip()
                match = df_zofri[df_zofri['_container_number'] == iti_codigo]
                
                if not match.empty:
                    match = match.copy()
                    # 保存 ITI 信息
                    for match_idx in match.index:
                        # 提取日期（iti_item[5] 是日期字符串，格式：05/01/2026 10:24）
                        fecha = iti_item[5] if len(iti_item) > 5 else ''
                        vessel_name = iti_item[0] if len(iti_item) > 0 else ''
                        iti_info_map[match_idx] = {
                            'iti_item': str(iti_item),
                            'vessel_name': vessel_name,
                            'fecha': fecha,
                            'folio': iti_item[1] if len(iti_item) > 1 else '',
                            'sigla': iti_item[2] if len(iti_item) > 2 else '',
                            'numero': iti_item[3] if len(iti_item) > 3 else '',
                            'digito': iti_item[4] if len(iti_item) > 4 else '',
                            'pies': iti_item[6] if len(iti_item) > 6 else ''
                        }
                    matched_data = pd.concat([matched_data, match])
                    matched_indices[match.index] = True
        
        unmatched_data = df_zofri[~matched_indices]
        
        # 打印 ZOFRI 容器匹配結果
        matched_count = int(matched_indices.sum())
        unmatched_count = len(unmatched_data)
        print(f"[監控檢查-{execution_id}] ZOFRI 容器匹配結果: 總數={len(df_zofri)}, 已匹配(VISADO)={matched_count}, 未匹配={unmatched_count}")
        
        # 打印已匹配的 ZOFRI 容器
        if matched_count > 0:
            print(f"[監控檢查-{execution_id}] ========== 已匹配(VISADO)的 ZOFRI 容器 (共 {matched_count} 個) ==========")
            for idx, row in df_zofri[matched_indices].iterrows():
                codigo = row.get('codigo', 'N/A')
                glosa_codigo = row.get('glosa_codigo', 'N/A')
                glosa_descripcion = row.get('glosa_descripcion', 'N/A')
                estado = row.get('nombre', 'N/A')
                print(f"[監控檢查-{execution_id}] ✅ VISADO: codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
            print(f"[監控檢查-{execution_id}] ========== 已匹配容器列表結束 ==========")
        
        # 打印未匹配的 ZOFRI 容器
        if unmatched_count > 0:
            print(f"[監控檢查-{execution_id}] ========== 未匹配的 ZOFRI 容器 (共 {unmatched_count} 個) ==========")
            for idx, row in unmatched_data.iterrows():
                codigo = row.get('codigo', 'N/A')
                glosa_codigo = row.get('glosa_codigo', 'N/A')
                glosa_descripcion = row.get('glosa_descripcion', 'N/A')
                estado = row.get('nombre', 'N/A')
                print(f"[監控檢查-{execution_id}] ❌ 未匹配: codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
            print(f"[監控檢查-{execution_id}] ========== 未匹配容器列表結束 ==========")
        else:
            print(f"[監控檢查-{execution_id}] ✅ 所有 ZOFRI 容器都已匹配(VISADO)，沒有未匹配的容器")
        
        # 5. 轉換為字典列表（參考 iti.py 的邏輯）
        all_containers = []
        for idx, row in df_zofri.iterrows():
            # 使用 matched_indices 來判斷是否匹配（與 iti.py 邏輯一致）
            # matched_indices 的 index 與 df_zofri 的 index 一致，可以直接訪問
            try:
                is_matched = bool(matched_indices.loc[idx])
            except (KeyError, IndexError):
                # 如果索引不存在，默認為未匹配
                is_matched = False
            
            codigo = row.get('codigo', '')
            glosa_codigo = row.get('glosa_codigo', '')
            container = {
                'codigo': codigo,
                'glosa_codigo': glosa_codigo,
                'glosa_descripcion': row.get('glosa_descripcion', ''),
                'estado': row.get('nombre', ''),
                'matched': is_matched
            }
            
            # 如果是已匹配的，添加 ITI 信息
            if idx in iti_info_map:
                container['iti_item'] = iti_info_map[idx]['iti_item']
                container['vessel_name'] = iti_info_map[idx]['vessel_name']
                container['fecha'] = iti_info_map[idx]['fecha']
                container['iti_folio'] = iti_info_map[idx].get('folio', '')
                container['iti_sigla'] = iti_info_map[idx].get('sigla', '')
                container['iti_numero'] = iti_info_map[idx].get('numero', '')
                container['iti_digito'] = iti_info_map[idx].get('digito', '')
                container['iti_pies'] = iti_info_map[idx].get('pies', '')
            all_containers.append(container)
        
        # 調試：打印匹配統計（與 iti.py 的打印邏輯一致）
        matched_count = int(matched_indices.sum())
        unmatched_count = len(unmatched_data)  # 使用 unmatched_data 的長度（與 iti.py 一致）
        print(f"[監控檢查-{execution_id}] 容器統計: 總數={len(all_containers)}, 已匹配={matched_count}, 未匹配={unmatched_count}")
        
        # 額外調試：打印未匹配容器的詳細信息（與 iti.py 的打印邏輯一致）
        if not unmatched_data.empty:
            print(f"[監控檢查-{execution_id}] ========== 未匹配容器列表 (共 {len(unmatched_data)} 個) ==========")
            for idx, row in unmatched_data.iterrows():
                codigo = row.get('codigo', 'N/A')
                glosa_codigo = row.get('glosa_codigo', 'N/A')
                glosa_descripcion = row.get('glosa_descripcion', 'N/A')
                estado = row.get('nombre', 'N/A')
                print(f"[監控檢查-{execution_id}] ❌ 未匹配: codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
            print(f"[監控檢查-{execution_id}] ========== 未匹配容器列表結束 ==========")
        else:
            print(f"[監控檢查-{execution_id}] ✅ 所有容器都已匹配，沒有未匹配的容器")
        
        result = {
            'containers': all_containers,
            'matched_count': len(matched_data),
            'unmatched_count': len(unmatched_data)
        }
        
        print(f"[監控檢查-{execution_id}] 監控檢查完成")
        return True, result, ""
        
    except Exception as e:
        print(f"[監控檢查-{execution_id}] 監控檢查失敗: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, {}, f"檢查失敗: {str(e)}"


# ========== 對比上次結果，判斷是否有變化 ==========
def has_result_changed(last_result: Optional[str], current_result: Dict) -> bool:
    """
    對比上次和本次結果，判斷是否有變化需要發送郵件
    返回：True 表示有變化需要發送，False 表示沒有變化
    
    邏輯：
    1. 第一次檢查（last_result 為空）：如果有數據，返回 True（發送所有容器，包括匹配和未匹配的）
    2. 後續檢查：
       - 如果有容器從 unmatched → matched，返回 True（發送所有容器）
       - 如果有新增的容器（無論匹配與否），返回 True（發送所有容器）
       - 如果容器數量有變化，返回 True（發送所有容器）
       - 否則返回 False（不發送）
    """
    if not last_result:
        # 第一次檢查：如果有容器數據，就發送（包括匹配和未匹配的）
        containers = current_result.get('containers', [])
        return len(containers) > 0
    
    try:
        # 對比上次和本次結果
        last_data = json.loads(last_result)
        
        # 獲取容器列表
        last_containers = last_data.get('containers', [])
        current_containers = current_result.get('containers', [])
        
        # 如果容器數量有變化，發送
        if len(last_containers) != len(current_containers):
            return True
        
        # 創建容器狀態映射：{codigo: matched}
        def create_status_map(data):
            containers = data.get('containers', [])
            status_map = {}
            for c in containers:
                codigo = c.get('codigo', '')
                if codigo:  # 確保 codigo 不為空
                    matched = c.get('matched', False)
                    status_map[codigo] = matched
            return status_map
        
        last_map = create_status_map(last_data)
        current_map = create_status_map(current_result)
        
        # 找出共同存在的容器（兩次檢查都存在的容器）
        common_codes = set(last_map.keys()) & set(current_map.keys())
        
        # 如果有新增的容器（不在上次結果中的），發送
        new_codes = set(current_map.keys()) - set(last_map.keys())
        if new_codes:
            return True
        
        # 檢查共同存在的容器，是否有從 unmatched → matched 的變化
        for codigo in common_codes:
            last_matched = last_map.get(codigo)
            current_matched = current_map.get(codigo)
            
            # 如果上次未匹配，本次匹配了 → 需要發送
            if last_matched is False and current_matched is True:
                return True
        
        # 沒有變化（容器數量相同，沒有新增，沒有 unmatched → matched 的變化）
        return False
        
    except Exception as e:
        print(f"對比失敗: {e}")
        import traceback
        traceback.print_exc()
        # 對比失敗時，為了安全起見，認為有變化（發送所有容器）
        return True


# ========== 發送通知郵件 ==========
def send_notification_email(emails: List[str], containers: List[Dict], task_config: Dict = None) -> Tuple[bool, str]:
    """
    發送監控通知郵件
    參數：
        emails - 收件人郵箱列表
        containers - 容器數據列表
        task_config - 監控任務配置（可選，包含 company_name 和 email_subject）
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
    print(f"[監控郵件] 準備發送郵件，收件人: {emails}, 容器數量: {len(containers)}")
    
    if not containers:
        print("[監控郵件] 沒有容器數據，跳過發送")
        return True, "沒有新匹配的容器"
    
    if not emails:
        print("[監控郵件] 沒有收件人郵箱，跳過發送")
        return False, "沒有收件人郵箱"
    
    # 統計匹配和未匹配的容器數量（用於調試）
    matched_count = sum(1 for c in containers if c.get('matched', False))
    unmatched_count = len(containers) - matched_count
    print(f"[監控郵件] 容器統計: 總數={len(containers)}, 已匹配={matched_count}, 未匹配={unmatched_count}")
    
    # 從任務配置獲取公司名稱（必填）
    if not task_config:
        return False, "缺少任務配置信息"
    
    company_name = task_config.get('company_name')
    if not company_name:
        return False, "請在監控任務配置中設置公司名稱（company_name）"
    
    # 獲取郵件主題（優先從任務配置，如果沒有就使用默認格式）
    email_subject = None
    if task_config:
        email_subject = task_config.get('email_subject')
    
    # 如果沒有自定義主題，使用默認格式（包含公司名稱）
    if not email_subject:
        email_subject = f"🚢 {company_name} 櫃子通知🚢"
    
    # 生成郵件內容
    matched_list = []
    unmatched_list = []
    
    print(f"[監控郵件] 開始處理 {len(containers)} 個容器...")
    for container in containers:
        is_matched = container.get('matched', False)
        status_class = "status-matched" if is_matched else "status-unmatched"
        status_text = "已匹配" if is_matched else "未匹配"
        
        # 顯示：描述、狀態、集裝箱號碼、交貨日期（4列，已對調）
        if is_matched:
            fecha = container.get('fecha', '')
            item = f"""
        <tr>
            <td style="border: 1px solid #000000; padding: 12px 10px; font-size: 14px; color: #000000; vertical-align: top;">{container.get('glosa_descripcion', '') or '-'}</td>
            <td style="border: 1px solid #000000; padding: 12px 10px; font-size: 14px; color: #000000; vertical-align: top;">{container.get('estado', '') or '-'}</td>
            <td style="border: 1px solid #000000; padding: 12px 10px; font-size: 14px; color: #000000; vertical-align: top; font-family: 'Courier New', 'Consolas', monospace; font-weight: 600; white-space: nowrap;">{container.get('glosa_codigo', '') or '-'}</td>
            <td style="border: 1px solid #000000; padding: 12px 10px; font-size: 14px; color: #1976d2; font-weight: 500; vertical-align: top; white-space: nowrap; min-width: 120px;">{fecha or '-'}</td>
        </tr>
        """
            matched_list.append(item)
            print(f"[監控郵件] 已匹配容器: {container.get('glosa_codigo', 'N/A')}")
        else:
            item = f"""
        <tr>
            <td style="border: 1px solid #000000; padding: 12px 10px; font-size: 14px; color: #000000; vertical-align: top;">{container.get('glosa_descripcion', '') or '-'}</td>
            <td style="border: 1px solid #000000; padding: 12px 10px; font-size: 14px; color: #000000; vertical-align: top;">{container.get('estado', '') or '-'}</td>
            <td style="border: 1px solid #000000; padding: 12px 10px; font-size: 14px; color: #000000; vertical-align: top; font-family: 'Courier New', 'Consolas', monospace; font-weight: 600; white-space: nowrap;">{container.get('glosa_codigo', '') or '-'}</td>
            <td style="border: 1px solid #000000; padding: 12px 10px; font-size: 14px; color: #9ca3af; vertical-align: top; white-space: nowrap; min-width: 120px;">-</td>
        </tr>
        """
            unmatched_list.append(item)
            codigo = container.get('codigo', 'N/A')
            glosa_codigo = container.get('glosa_codigo', 'N/A')
            glosa_descripcion = container.get('glosa_descripcion', 'N/A')
            estado = container.get('estado', 'N/A')
            print(f"[監控郵件] ❌ 未匹配容器: codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
    
    print(f"[監控郵件] 郵件內容生成: 已匹配={len(matched_list)}, 未匹配={len(unmatched_list)}")
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, "Microsoft YaHei", sans-serif;
                font-size: 14px;
                line-height: 1.6;
                margin: 0;
                padding: 0;
                background-color: #f5f5f5;
            }}
            .email-wrapper {{
                max-width: 900px;
                margin: 0 auto;
                background-color: #ffffff;
                padding: 0;
            }}
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px 25px;
                text-align: center;
            }}
            .header h1 {{
                font-size: 24px;
                font-weight: 600;
                margin: 0 0 8px 0;
                color: #000000 !important;
            }}
            .header p {{
                font-size: 14px;
                margin: 0;
                opacity: 0.95;
            }}
            .content {{
                padding: 30px 25px;
            }}
            .stats {{
                display: table;
                width: 100%;
                margin-bottom: 30px;
                border-collapse: separate;
                border-spacing: 12px;
            }}
            .stat-box {{
                display: table-cell;
                background: #f8f9fa;
                padding: 20px;
                text-align: center;
                border-radius: 8px;
                border-left: 4px solid #667eea;
            }}
            .stat-box.matched {{
                border-left-color: #10b981;
                background: #f0fdf4;
            }}
            .stat-box.unmatched {{
                border-left-color: #ef4444;
                background: #fef2f2;
            }}
            .stat-number {{
                font-size: 32px;
                font-weight: 700;
                color: #1f2937;
                display: block;
                margin-bottom: 5px;
            }}
            .stat-box.matched .stat-number {{
                color: #10b981;
            }}
            .stat-box.unmatched .stat-number {{
                color: #ef4444;
            }}
            .stat-label {{
                font-size: 13px;
                color: #6b7280;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .section {{
                margin-bottom: 35px;
            }}
            .section-header {{
                font-size: 18px;
                font-weight: 600;
                margin-bottom: 15px;
                padding-bottom: 10px;
                border-bottom: 2px solid #e5e7eb;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            .section-header.matched {{
                color: #10b981;
                border-bottom-color: #10b981;
            }}
            .section-header.unmatched {{
                color: #ef4444;
                border-bottom-color: #ef4444;
            }}
            .table-container {{
                overflow-x: auto;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: white;
                border: 2px solid #000000;
            }}
            thead {{
                background: #e5e7eb;
            }}
            th {{
                padding: 14px 16px;
                text-align: left;
                font-weight: 700;
                font-size: 13px;
                color: #000000;
                border: 1px solid #000000;
                border-bottom: 2px solid #000000;
            }}
            tbody tr {{
                border-bottom: 1px solid #000000;
            }}
            tbody tr:hover {{
                background-color: #f9fafb;
            }}
            tbody tr:last-child {{
                border-bottom: 1px solid #000000;
            }}
            td {{
                padding: 14px 16px;
                font-size: 14px;
                color: #000000;
                border-right: 1px solid #000000;
                vertical-align: top;
            }}
            td:last-child {{
                border-right: 1px solid #000000;
            }}
            .code {{
                font-family: "Courier New", "Consolas", monospace;
                font-weight: 600;
                color: #667eea;
                font-size: 12px;
            }}
            .date {{
                color: #1976d2;
                font-weight: 500;
            }}
            .vessel {{
                color: #7c3aed;
                font-weight: 500;
            }}
            .status-badge {{
                display: inline-block;
                padding: 4px 10px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
            }}
            .status-matched {{
                background: #d1fae5;
                color: #065f46;
            }}
            .status-unmatched {{
                background: #fee2e2;
                color: #991b1b;
            }}
            .empty-message {{
                padding: 40px;
                text-align: center;
                color: #9ca3af;
                font-size: 14px;
            }}
            .footer {{
                background: #f9fafb;
                padding: 20px 25px;
                text-align: center;
                border-top: 1px solid #e5e7eb;
                color: #6b7280;
                font-size: 12px;
            }}
            @media only screen and (max-width: 600px) {{
                .stats {{
                    display: block;
                }}
                .stat-box {{
                    display: block;
                    margin-bottom: 12px;
                }}
                .content {{
                    padding: 20px 15px;
                }}
                .table-container {{
                    overflow-x: auto;
                    -webkit-overflow-scrolling: touch;
                }}
                table {{
                    font-size: 12px !important;
                    min-width: 100%;
                }}
                th, td {{
                    padding: 10px 8px !important;
                    font-size: 12px !important;
                }}
                th:last-child, td:last-child {{
                    min-width: 110px !important;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="email-wrapper">
            <div class="header">
                <h1 style="color: #000000 !important; margin: 0 0 8px 0; font-size: 24px; font-weight: 600;">🚢 {company_name} 櫃子通知🚢</h1>
                <p>容器匹配狀態更新</p>
            </div>
            
            <div class="content">
                <div class="stats">
                    <div class="stat-box">
                        <span class="stat-number">{len(containers)}</span>
                        <span class="stat-label">總數</span>
                    </div>
                    <div class="stat-box matched">
                        <span class="stat-number">{len(matched_list)}</span>
                        <span class="stat-label">已匹配</span>
                    </div>
                    <div class="stat-box unmatched">
                        <span class="stat-number">{len(unmatched_list)}</span>
                        <span class="stat-label">未匹配</span>
                    </div>
                </div>
                
                <div class="section">
                    <div class="section-header matched">
                        <span>✅</span>
                        <span>已匹配到 ITI ({len(matched_list)} 個)</span>
                    </div>
                    {f'<div class="table-container"><table cellpadding="0" cellspacing="0" style="width: 100%; border-collapse: collapse; background: white; border: 2px solid #000000;"><thead><tr><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">描述</th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">狀態</th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap;">集裝箱號碼</th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap; min-width: 120px;">交貨日期</th></tr></thead><tbody>{"".join(matched_list)}</tbody></table></div>' if matched_list else '<div class="empty-message">暫無已匹配的容器</div>'}
                </div>
                
                {f'<div class="section"><div class="section-header unmatched"><span>❌</span><span>未匹配到 ITI ({len(unmatched_list)} 個)</span></div><div class="table-container"><table cellpadding="0" cellspacing="0" style="width: 100%; border-collapse: collapse; background: white; border: 2px solid #000000;"><thead><tr><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">描述</th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">狀態</th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap;">集裝箱號碼</th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap; min-width: 120px;">交貨日期</th></tr></thead><tbody>{"".join(unmatched_list)}</tbody></table></div></div>' if unmatched_list else ''}
            </div>
            
            <div class="footer">
                <div>檢查時間：{get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')}</div>
                <div style="margin-top: 5px;">總計：{len(containers)} 個容器</div>
            </div>
        </div>
    </body>
    </html>
    """
    
    # 發送到所有郵箱
    success_count = 0
    error_messages = []
    
    # 清理和驗證郵件地址
    from services.email_service import clean_email_address, validate_email_format
    cleaned_emails = []
    for email in emails:
        cleaned = clean_email_address(str(email))
        if cleaned and validate_email_format(cleaned):
            cleaned_emails.append(cleaned)
        else:
            print(f"[監控郵件] 跳過無效的郵件地址: {email}")
    
    if not cleaned_emails:
        return False, "沒有有效的郵件地址"
    
    for email in cleaned_emails:
        print(f"[監控郵件] 正在發送郵件到: {email}")
        success, error = send_email(
            email,
            email_subject,  # 使用動態獲取的郵件主題
            html_content
        )
        if success:
            success_count += 1
            print(f"[監控郵件] ✅ 郵件已成功發送到: {email}")
        else:
            error_messages.append(f"{email}: {error}")
            print(f"[監控郵件] ❌ 郵件發送失敗到 {email}: {error}")
    
    if success_count > 0:
        result_msg = f"已發送到 {success_count}/{len(emails)} 個郵箱"
        print(f"[監控郵件] ✅ {result_msg}")
        return True, result_msg
    else:
        result_msg = "; ".join(error_messages)
        print(f"[監控郵件] ❌ 所有郵件發送失敗: {result_msg}")
        return False, result_msg


def _safe_text(value, default='-') -> str:
    if value is None:
        return default
    text = str(value).replace('\n', ' ').replace('\r', ' ').strip()
    return text if text else default


def _truncate_text(value: str, limit: int = 40) -> str:
    value = _safe_text(value)
    if len(value) <= limit:
        return value
    return value[:limit - 3] + "..."


def _parse_telegram_fecha(value) -> Optional[datetime]:
    text = _safe_text(value, '').strip()
    if not text or text == '-':
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _split_container_code(code_text: str) -> Tuple[str, str, str]:
    cleaned = re.sub(r'[^A-Za-z0-9]', '', _safe_text(code_text, '')).upper()
    match = re.match(r'^([A-Z]{4})(\d{6,7})(\d)$', cleaned)
    if match:
        return match.group(1), match.group(2), match.group(3)
    if len(cleaned) >= 5:
        return cleaned[:4], cleaned[4:-1] or '-', cleaned[-1]
    return '-', '-', '-'


def _prepare_telegram_row(container: Dict) -> Dict:
    is_matched = bool(container.get('matched', False))
    code = _safe_text(container.get('glosa_codigo') or container.get('codigo'))
    sigla_auto, numero_auto, digito_auto = _split_container_code(code)

    row = {
        'matched': is_matched,
        'codigo': code,
        'buque': _safe_text(container.get('vessel_name') if is_matched else container.get('glosa_descripcion')),
        'estado': _safe_text(container.get('estado')),
        'descripcion': _safe_text(container.get('glosa_descripcion')),
        'folio': _safe_text(container.get('iti_folio'), '-') if is_matched else '-',
        'sigla': _safe_text(container.get('iti_sigla'), sigla_auto) if is_matched else sigla_auto,
        'numero': _safe_text(container.get('iti_numero'), numero_auto) if is_matched else numero_auto,
        'digito': _safe_text(container.get('iti_digito'), digito_auto) if is_matched else digito_auto,
        'fecha': _safe_text(container.get('fecha'), '-') if is_matched else '-',
        'pies': _safe_text(container.get('iti_pies'), '-') if is_matched else '-',
        '_fecha_dt': _parse_telegram_fecha(container.get('fecha') if is_matched else None)
    }
    return row


def _collect_telegram_rows(
    containers: List[Dict],
    include_matched: bool,
    include_unmatched: bool
) -> Tuple[List[Dict], List[Dict]]:
    matched_rows = []
    unmatched_rows = []

    for container in containers:
        row = _prepare_telegram_row(container)
        if row['matched'] and not include_matched:
            continue
        if (not row['matched']) and not include_unmatched:
            continue
        if row['matched']:
            matched_rows.append(row)
        else:
            unmatched_rows.append(row)

    # matched: group by ship, then date old -> new
    matched_rows.sort(key=lambda r: (r['buque'], r['_fecha_dt'] is None, r['_fecha_dt'] or datetime.max, r['codigo']))
    # unmatched: keep stable and easy scan
    unmatched_rows.sort(key=lambda r: (r['buque'], r['codigo']))

    return matched_rows, unmatched_rows


def _build_telegram_sections(
    containers: List[Dict],
    include_matched: bool,
    include_unmatched: bool,
    max_rows: int
) -> Tuple[List[Dict], List[Dict], int, int]:
    matched_rows, unmatched_rows = _collect_telegram_rows(
        containers=containers,
        include_matched=include_matched,
        include_unmatched=include_unmatched
    )

    max_rows = normalize_telegram_max_rows(max_rows)
    total_rows = len(matched_rows) + len(unmatched_rows)
    shown_matched = []
    shown_unmatched = []

    if total_rows <= max_rows:
        shown_matched = matched_rows
        shown_unmatched = unmatched_rows
    else:
        if include_matched and include_unmatched:
            matched_quota = min(len(matched_rows), max(1, max_rows // 2))
            unmatched_quota = min(len(unmatched_rows), max(1, max_rows - matched_quota))
            remain = max_rows - matched_quota - unmatched_quota
            if remain > 0:
                add_m = min(remain, len(matched_rows) - matched_quota)
                matched_quota += add_m
                remain -= add_m
            if remain > 0:
                add_u = min(remain, len(unmatched_rows) - unmatched_quota)
                unmatched_quota += add_u
            shown_matched = matched_rows[:matched_quota]
            shown_unmatched = unmatched_rows[:unmatched_quota]
        elif include_matched:
            shown_matched = matched_rows[:max_rows]
        else:
            shown_unmatched = unmatched_rows[:max_rows]

    hidden_matched = len(matched_rows) - len(shown_matched)
    hidden_unmatched = len(unmatched_rows) - len(shown_unmatched)

    for row in shown_matched:
        row.pop('_fecha_dt', None)
    for row in shown_unmatched:
        row.pop('_fecha_dt', None)

    return shown_matched, shown_unmatched, hidden_matched, hidden_unmatched


def _group_rows_by_buque(rows: List[Dict]) -> List[Tuple[str, List[Dict]]]:
    grouped: Dict[str, List[Dict]] = {}
    for row in rows:
        ship = _safe_text(row.get('buque'), 'UNKNOWN')
        grouped.setdefault(ship, []).append(row)
    return list(grouped.items())


def _build_telegram_text_message(company_name: str, containers: List[Dict], include_matched: bool, include_unmatched: bool, max_rows: int) -> str:
    max_text_len = 3900
    matched = [c for c in containers if c.get('matched', False)]
    unmatched = [c for c in containers if not c.get('matched', False)]
    shown_matched, shown_unmatched, hidden_matched, hidden_unmatched = _build_telegram_sections(
        containers, include_matched, include_unmatched, max_rows
    )
    grouped_matched = _group_rows_by_buque(shown_matched)
    grouped_unmatched = _group_rows_by_buque(shown_unmatched)
    now_text = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')

    lines = [
        f"🚢 {company_name} 監控通知",
        f"時間: {now_text} (Chile)",
        f"總數: {len(containers)} | 匹配: {len(matched)} | 未匹配: {len(unmatched)}",
        "====================",
        f"✅ 已匹配 ({len(matched)})"
    ]

    def try_add_line(line: str) -> bool:
        projected = len("\n".join(lines + [line]))
        if projected > max_text_len:
            return False
        lines.append(line)
        return True

    extra_hidden_matched = 0
    if not grouped_matched:
        lines.append("- 無")
    else:
        printed = 0
        for ship, rows in grouped_matched:
            if not try_add_line(f"【{_truncate_text(ship, 48)}】"):
                extra_hidden_matched = len(shown_matched) - printed
                break
            for idx, row in enumerate(rows, 1):
                folio_text = row['folio'] if row.get('folio') and row['folio'] != '-' else '-'
                line_a = f"{idx}. F{folio_text} |"
                line_b = f"   {row['codigo']} | {row['fecha']}"
                if not try_add_line(line_a) or not try_add_line(line_b):
                    extra_hidden_matched = len(shown_matched) - printed
                    break
                printed += 1
            if extra_hidden_matched > 0:
                break

    if hidden_matched > 0:
        lines.append(f"... 已匹配尚有 {hidden_matched} 筆未顯示")
    if extra_hidden_matched > 0:
        lines.append(f"... 已匹配尚有 {extra_hidden_matched} 筆因訊息長度未顯示")

    lines.append("--------------------")
    lines.append(f"❌ 未匹配 ({len(unmatched)})")
    extra_hidden_unmatched = 0
    if not grouped_unmatched:
        lines.append("- 無")
    else:
        printed = 0
        for ship, rows in grouped_unmatched:
            if not try_add_line(f"【{_truncate_text(ship, 48)}】"):
                extra_hidden_unmatched = len(shown_unmatched) - printed
                break
            for idx, row in enumerate(rows, 1):
                line = f"{idx}. {row['codigo']} | {row['estado']}"
                if not try_add_line(line):
                    extra_hidden_unmatched = len(shown_unmatched) - printed
                    break
                printed += 1
            if extra_hidden_unmatched > 0:
                break

    if hidden_unmatched > 0:
        lines.append(f"... 未匹配尚有 {hidden_unmatched} 筆未顯示")
    if extra_hidden_unmatched > 0:
        lines.append(f"... 未匹配尚有 {extra_hidden_unmatched} 筆因訊息長度未顯示")

    return "\n".join(lines)


def _build_telegram_image_caption(company_name: str, containers: List[Dict]) -> str:
    matched_count = sum(1 for item in containers if item.get('matched', False))
    unmatched_count = len(containers) - matched_count
    now_text = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
    return f"{company_name} | {now_text} | Total {len(containers)} / Coincidentes {matched_count} / Pendientes {unmatched_count}"


def _format_telegram_fecha_for_image(row: Dict) -> str:
    dt_value = row.get('_fecha_dt')
    if dt_value:
        return dt_value.strftime('%d/%m/%Y · %H:%M')
    fallback = _safe_text(row.get('fecha'), '-')
    if fallback in ('', '-'):
        return '-'
    parsed = _parse_telegram_fecha(fallback)
    if parsed:
        return parsed.strftime('%d/%m/%Y · %H:%M')
    return fallback


def _build_telegram_html_context(
    containers: List[Dict],
    include_matched: bool,
    include_unmatched: bool
) -> Dict[str, Any]:
    matched_rows, unmatched_rows = _collect_telegram_rows(
        containers=containers,
        include_matched=include_matched,
        include_unmatched=include_unmatched
    )
    grouped_matched = _group_rows_by_buque(matched_rows)
    grouped_unmatched = _group_rows_by_buque(unmatched_rows)

    matched_groups = []
    for ship_name, rows in grouped_matched:
        matched_groups.append({
            'nave': ship_name,
            'count': len(rows),
            'contenedores': [
                {
                    'folio': _safe_text(r.get('folio'), '-'),
                    'contenedor': _safe_text(r.get('codigo'), '-'),
                    'fecha_entrega': _format_telegram_fecha_for_image(r),
                    'estado': _safe_text(r.get('estado'), '-')
                }
                for r in rows
            ]
        })

    unmatched_groups = []
    for ship_name, rows in grouped_unmatched:
        unmatched_groups.append({
            'nave': ship_name,
            'count': len(rows),
            'contenedores': [
                {
                    'contenedor': _safe_text(r.get('codigo'), '-'),
                    'estado': _safe_text(r.get('estado'), '-')
                }
                for r in rows
            ]
        })

    now_local = get_chile_time_naive()
    return {
        'total_count': len(matched_rows) + len(unmatched_rows),
        'matched_count': len(matched_rows),
        'unmatched_count': len(unmatched_rows),
        'matched_groups': matched_groups,
        'unmatched_groups': unmatched_groups,
        'show_matched': include_matched,
        'show_unmatched': include_unmatched,
        'generated_date': now_local.strftime('%d/%m/%Y'),
        'generated_time': now_local.strftime('%H:%M')
    }


def get_monitor_report_context_by_api_key(api_key: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Load last monitor result by api_key and build HTML context for report page."""
    task_config = get_task_by_api_key(api_key)
    if not task_config:
        return None, "Invalid api_key"

    raw_result = task_config.get('last_check_result')
    parsed_result: Dict[str, Any] = {}
    if raw_result:
        try:
            if isinstance(raw_result, str):
                parsed_result = json.loads(raw_result)
            elif isinstance(raw_result, dict):
                parsed_result = raw_result
        except Exception as exc:
            return None, f"Failed to parse last_check_result: {exc}"

    result_hash = compute_result_hash(parsed_result if parsed_result else {'containers': []})
    containers = parsed_result.get('containers', []) if isinstance(parsed_result, dict) else []
    include_matched = True if task_config.get('telegram_include_matched') is None else bool(task_config.get('telegram_include_matched'))
    include_unmatched = True if task_config.get('telegram_include_unmatched') is None else bool(task_config.get('telegram_include_unmatched'))
    context = _build_telegram_html_context(
        containers=containers,
        include_matched=include_matched,
        include_unmatched=include_unmatched
    )
    context['company_name'] = _safe_text(task_config.get('company_name'), 'NICO').upper()
    context['task_id'] = task_config.get('id')
    context['api_key'] = task_config.get('api_key')
    context['result_hash'] = result_hash
    return context, ""


def get_monitor_report_status_by_api_key(api_key: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return lightweight report status for polling without triggering crawlers."""
    task_config = get_task_by_api_key(api_key)
    if not task_config:
        return None, "Invalid api_key"

    raw_result = task_config.get('last_check_result')
    parsed_result: Dict[str, Any] = {}
    if raw_result:
        try:
            if isinstance(raw_result, str):
                parsed_result = json.loads(raw_result)
            elif isinstance(raw_result, dict):
                parsed_result = raw_result
        except Exception as exc:
            return None, f"Failed to parse last_check_result: {exc}"

    result_hash = compute_result_hash(parsed_result if parsed_result else {'containers': []})
    return {
        'result_hash': result_hash,
        'last_check_time': task_config.get('last_check_time'),
        'task_id': task_config.get('id')
    }, ""


def _render_telegram_html_image(
    company_name: str,
    containers: List[Dict],
    include_matched: bool,
    include_unmatched: bool
) -> Tuple[Optional[bytes], str]:
    template_dir = Path(__file__).resolve().parent.parent / "templates" / "reports"
    template_path = template_dir / "iti_telegram_report.html"
    if not template_path.exists():
        return None, f"template not found: {template_path}"

    try:
        env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"])
        )
        template = env.get_template("iti_telegram_report.html")
        context = _build_telegram_html_context(
            containers=containers,
            include_matched=include_matched,
            include_unmatched=include_unmatched
        )
        context['company_name'] = _safe_text(company_name, 'NICO').upper()
        html_content = template.render(**context)
    except Exception as exc:
        return None, f"template render failed: {exc}"

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return None, f"playwright import failed: {exc}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(
                viewport={"width": 520, "height": 900},
                device_scale_factor=4
            )
            page.set_content(html_content, wait_until="networkidle")
            page.wait_for_timeout(2000)
            content_height = int(page.evaluate("Math.ceil(document.documentElement.scrollHeight || document.body.scrollHeight || 900)"))
            content_width = int(page.evaluate("Math.ceil(document.documentElement.scrollWidth || document.body.scrollWidth || 520)"))
            target_width = max(520, content_width)

            if content_height <= 860:
                # Short report: tighten bottom spacing to avoid visible blank area.
                page.evaluate("""
                    (() => {
                      const styleId = 'iti-short-report-compact-style';
                      if (!document.getElementById(styleId)) {
                        const st = document.createElement('style');
                        st.id = styleId;
                        st.textContent = 'body{padding-bottom:12px !important;} .footer{margin-top:8px !important;}';
                        document.head.appendChild(st);
                      }
                    })();
                """)
                page.wait_for_timeout(80)
                content_height = int(page.evaluate("Math.ceil(document.documentElement.scrollHeight || document.body.scrollHeight || 900)"))
                target_height = max(280, content_height + 4)
                page.set_viewport_size({"width": target_width, "height": target_height})
                png_bytes = page.screenshot(full_page=False, type="png")
            else:
                page.set_viewport_size({"width": target_width, "height": 900})
                png_bytes = page.screenshot(full_page=True, type="png")
            browser.close()
            return png_bytes, ""
    except Exception as exc:
        return None, f"playwright screenshot failed: {exc}"


def _load_telegram_font(size: int, bold: bool = False):
    if ImageFont is None:
        return None
    if bold:
        candidates = ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"]
    else:
        candidates = ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_text(draw, text: str, font, max_width: int) -> str:
    text = _safe_text(text)
    if not text:
        return '-'
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    low = 0
    high = len(text)
    while low < high:
        mid = (low + high) // 2
        probe = text[:mid] + ellipsis
        if draw.textlength(probe, font=font) <= max_width:
            low = mid + 1
        else:
            high = mid
    cut = max(1, low - 1)
    return text[:cut] + ellipsis


def _draw_grid_table(
    draw,
    x0: int,
    y0: int,
    col_widths: List[int],
    header_h: int,
    row_h: int,
    headers: List[str],
    rows: List[List[str]],
    fonts: Dict[str, Any],
    style: Optional[Dict[str, str]] = None
) -> int:
    style = style or {}
    header_bg = style.get('header_bg', "#d1d5db")
    line_color = style.get('line_color', "#9ca3af")
    body_bg = style.get('body_bg', "#ffffff")
    row_alt_bg = style.get('row_alt_bg', body_bg)
    text_color = style.get('text_color', "#111827")
    header_text_color = style.get('header_text_color', "#111827")
    header_font = fonts['header']
    body_font = fonts['body']
    table_w = sum(col_widths)
    x1 = x0 + table_w
    y = y0

    draw.rectangle([x0, y, x1, y + header_h], fill=header_bg, outline=line_color, width=2)
    x = x0
    for idx, h in enumerate(headers):
        w = col_widths[idx]
        draw.text((x + 10, y + (header_h - 20) // 2), _fit_text(draw, h, header_font, w - 16), fill=header_text_color, font=header_font)
        x += w
        if idx < len(headers) - 1:
            draw.line([x, y, x, y + header_h], fill=line_color, width=2)
    y += header_h

    if not rows:
        rows = [["-"] + [""] * (len(headers) - 1)]

    for ridx, row in enumerate(rows):
        row_bg = body_bg if ridx % 2 == 0 else row_alt_bg
        draw.rectangle([x0, y, x1, y + row_h], fill=row_bg, outline=line_color, width=1)
        x = x0
        for idx, cell in enumerate(row):
            w = col_widths[idx]
            draw.text((x + 10, y + (row_h - 18) // 2), _fit_text(draw, cell, body_font, w - 16), fill=text_color, font=body_font)
            x += w
            if idx < len(row) - 1:
                draw.line([x, y, x, y + row_h], fill=line_color, width=1)
        y += row_h

    draw.rectangle([x0, y0, x1, y], outline=line_color, width=2)
    return y


def _render_telegram_table_image_pillow(containers: List[Dict], company_name: str, include_matched: bool, include_unmatched: bool, max_rows: int) -> Tuple[List[bytes], str]:
    if Image is None or ImageDraw is None or ImageFont is None:
        return [], "Pillow is not available for telegram image rendering"

    # Image mode should be complete: do not trim by telegram_max_rows.
    full_matched, full_unmatched = _collect_telegram_rows(
        containers=containers,
        include_matched=include_matched,
        include_unmatched=include_unmatched
    )
    grouped_matched = _group_rows_by_buque(full_matched)
    grouped_unmatched = _group_rows_by_buque(full_unmatched)
    matched_count = sum(1 for item in containers if item.get('matched', False))
    unmatched_count = len(containers) - matched_count

    scale = 2.2
    margin = int(20 * scale)
    summary_h = int(74 * scale)
    header_h = int(22 * scale)
    row_h = int(20 * scale)
    section_gap = int(14 * scale)
    footer_h = int(24 * scale)
    ship_h = int(20 * scale)
    matched_cols = [int(110 * scale), int(220 * scale), int(200 * scale), int(180 * scale)]
    unmatched_cols = [int(300 * scale), int(200 * scale)]
    table_w = max(sum(matched_cols), sum(unmatched_cols))

    font_title = _load_telegram_font(int(17 * scale), bold=True)
    font_summary = _load_telegram_font(int(12 * scale), bold=False)
    font_header = _load_telegram_font(int(11 * scale), bold=True)
    font_body = _load_telegram_font(int(10 * scale), bold=False)
    fonts = {'header': font_header, 'body': font_body}

    def section_height(grouped: List[Tuple[str, List[Dict]]]) -> int:
        if not grouped:
            return ship_h + header_h + row_h + section_gap
        h = 0
        for _, rows in grouped:
            h += ship_h + header_h + max(1, len(rows)) * row_h + 6
        return h + section_gap

    section_count = (1 if include_matched else 0) + (1 if include_unmatched else 0)
    content_h = 0
    if include_matched:
        content_h += header_h + section_height(grouped_matched)
    if include_unmatched:
        content_h += header_h + section_height(grouped_unmatched)
    height = margin * 2 + summary_h + section_gap + content_h + footer_h
    width = margin * 2 + table_w

    # Telegram image constraints guard: keep a single long image but shrink layout if needed.
    while height > 9200 and scale > 1.3:
        scale -= 0.2
        margin = int(20 * scale)
        summary_h = int(74 * scale)
        header_h = int(22 * scale)
        row_h = int(20 * scale)
        section_gap = int(14 * scale)
        footer_h = int(24 * scale)
        ship_h = int(20 * scale)
        matched_cols = [int(110 * scale), int(220 * scale), int(200 * scale), int(180 * scale)]
        unmatched_cols = [int(300 * scale), int(200 * scale)]
        table_w = max(sum(matched_cols), sum(unmatched_cols))
        font_title = _load_telegram_font(int(17 * scale), bold=True)
        font_summary = _load_telegram_font(int(12 * scale), bold=False)
        font_header = _load_telegram_font(int(11 * scale), bold=True)
        font_body = _load_telegram_font(int(10 * scale), bold=False)
        fonts = {'header': font_header, 'body': font_body}
        content_h = 0
        if include_matched:
            content_h += header_h + section_height(grouped_matched)
        if include_unmatched:
            content_h += header_h + section_height(grouped_unmatched)
        height = margin * 2 + summary_h + section_gap + content_h + footer_h
        width = margin * 2 + table_w

    image = Image.new("RGB", (width, height), "#f0f9ff")
    draw = ImageDraw.Draw(image)
    y = margin

    # Brighter, premium header card
    draw.rounded_rectangle([margin, y, width - margin, y + summary_h], radius=max(12, int(10 * scale)), fill="#ffffff", outline="#93c5fd", width=2)
    draw.rectangle([margin, y, width - margin, y + max(6, int(5 * scale))], fill="#2563eb")
    draw.text((margin + 14, y + int(16 * scale)), f"{company_name} • ITI Monitor", fill="#0f172a", font=font_title)
    draw.text((margin + 14, y + int(40 * scale)), f"Tiempo (Chile): {get_chile_time_naive().strftime('%d/%m/%Y %H:%M')}", fill="#334155", font=font_summary)
    draw.text((margin + 14, y + int(58 * scale)), f"Total: {len(containers)} | Coincidentes: {matched_count} | Pendientes: {unmatched_count}", fill="#334155", font=font_summary)
    y += summary_h + section_gap

    def draw_section_title(text: str, bg: str, border: str, fg: str):
        nonlocal y
        draw.rounded_rectangle([margin, y, width - margin, y + header_h], radius=max(8, int(7 * scale)), fill=bg, outline=border, width=2)
        draw.text((margin + 10, y + int(8 * scale)), text, fill=fg, font=font_header)
        y += header_h

    def draw_ship_title(text: str):
        nonlocal y
        draw.rounded_rectangle([margin, y, width - margin, y + ship_h], radius=max(6, int(5 * scale)), fill="#f8fafc", outline="#cbd5e1", width=1)
        draw.text((margin + 10, y + int(7 * scale)), _fit_text(draw, text, font_header, width - margin * 2 - 20), fill="#334155", font=font_header)
        y += ship_h

    if include_matched:
        draw_section_title(f"✓ Matched ({matched_count})", bg="#dcfce7", border="#22c55e", fg="#166534")
        if not grouped_matched:
            draw_ship_title("No matched data")
            y = _draw_grid_table(
                draw=draw,
                x0=margin,
                y0=y,
                col_widths=matched_cols,
                header_h=header_h,
                row_h=row_h,
                headers=["Folio", "Contenedor", "Entrega", "Estado"],
                rows=[],
                fonts=fonts,
                style={
                    'header_bg': "#bbf7d0",
                    'line_color': "#86efac",
                    'body_bg': "#ffffff",
                    'row_alt_bg': "#f0fdf4",
                    'text_color': "#14532d",
                    'header_text_color': "#14532d"
                }
            )
        else:
            for ship, rows in grouped_matched:
                draw_ship_title(ship)
                table_rows = []
                for row in rows:
                    folio = row['folio'] if row.get('folio') and row['folio'] != '-' else '-'
                    table_rows.append([folio, row['codigo'], row['fecha'], row['estado']])
                y = _draw_grid_table(
                    draw=draw,
                    x0=margin,
                    y0=y,
                    col_widths=matched_cols,
                    header_h=header_h,
                    row_h=row_h,
                    headers=["Folio", "Contenedor", "Entrega", "Estado"],
                    rows=table_rows,
                    fonts=fonts,
                    style={
                        'header_bg': "#bbf7d0",
                        'line_color': "#86efac",
                        'body_bg': "#ffffff",
                        'row_alt_bg': "#f0fdf4",
                        'text_color': "#14532d",
                        'header_text_color': "#14532d"
                    }
                )
                y += 6
        y += section_gap

    if include_unmatched:
        draw_section_title(f"✕ Unmatched ({unmatched_count})", bg="#fee2e2", border="#f87171", fg="#991b1b")
        if not grouped_unmatched:
            draw_ship_title("No unmatched data")
            y = _draw_grid_table(
                draw=draw,
                x0=margin,
                y0=y,
                col_widths=unmatched_cols,
                header_h=header_h,
                row_h=row_h,
                headers=["Contenedor", "Estado"],
                rows=[],
                fonts=fonts,
                style={
                    'header_bg': "#fecaca",
                    'line_color': "#fca5a5",
                    'body_bg': "#ffffff",
                    'row_alt_bg': "#fff1f2",
                    'text_color': "#7f1d1d",
                    'header_text_color': "#7f1d1d"
                }
            )
        else:
            for ship, rows in grouped_unmatched:
                draw_ship_title(ship)
                table_rows = [[row['codigo'], row['estado']] for row in rows]
                y = _draw_grid_table(
                    draw=draw,
                    x0=margin,
                    y0=y,
                    col_widths=unmatched_cols,
                    header_h=header_h,
                    row_h=row_h,
                    headers=["Contenedor", "Estado"],
                    rows=table_rows,
                    fonts=fonts,
                    style={
                        'header_bg': "#fecaca",
                        'line_color': "#fca5a5",
                        'body_bg': "#ffffff",
                        'row_alt_bg': "#fff1f2",
                        'text_color': "#7f1d1d",
                        'header_text_color': "#7f1d1d"
                    }
                )
                y += 6
        y += section_gap

    draw.text((margin + 4, y), f"NICO ITI · Generated {get_chile_time_naive().strftime('%d/%m/%Y · %H:%M')}", fill="#64748b", font=font_summary)
    # Keep one long image while staying inside Telegram limits.
    max_dimension = 9800
    if (image.width + image.height) > max_dimension:
        ratio = max_dimension / float(image.width + image.height)
        new_w = max(640, int(image.width * ratio))
        new_h = max(900, int(image.height * ratio))
        resample_method = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        image = image.resize((new_w, new_h), resample_method)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return [buffer.getvalue()], ""


# ========== 發送 Telegram 通知 ==========

def _render_telegram_table_image(containers: List[Dict], company_name: str, include_matched: bool, include_unmatched: bool, max_rows: int) -> Tuple[List[bytes], str]:
    html_png, html_err = _render_telegram_html_image(
        company_name=company_name,
        containers=containers,
        include_matched=include_matched,
        include_unmatched=include_unmatched
    )
    if html_png:
        return [html_png], ""
    return [], f"html render failed: {html_err}"


def send_notification_telegram(
    bot_token: str,
    chat_id: str,
    containers: List[Dict],
    task_config: Dict = None,
    report_url: Optional[str] = None
) -> Tuple[bool, str]:
    """
    發送監控通知到 Telegram
    參數：
        bot_token - Telegram Bot Token
        chat_id - Chat ID 或 @channelusername
        containers - 容器數據列表
        task_config - 監控任務配置（包含 company_name）
    返回：(bool, str) - (是否成功, 錯誤信息)
    """
    if not task_config:
        return False, "缺少任務配置信息"

    company_name = task_config.get('company_name')
    if not company_name:
        return False, "請在監控任務配置中設置公司名稱（company_name）"

    if not containers:
        return True, "沒有新匹配的容器"

    telegram_mode = normalize_telegram_mode(task_config.get('telegram_mode'))
    include_matched = True if task_config.get('telegram_include_matched') is None else bool(task_config.get('telegram_include_matched'))
    include_unmatched = True if task_config.get('telegram_include_unmatched') is None else bool(task_config.get('telegram_include_unmatched'))
    max_rows = normalize_telegram_max_rows(task_config.get('telegram_max_rows', 200))

    if not include_matched and not include_unmatched:
        return False, "Telegram 至少要顯示匹配或未匹配其中一種"

    text_message = _build_telegram_text_message(
        company_name=company_name,
        containers=containers,
        include_matched=include_matched,
        include_unmatched=include_unmatched,
        max_rows=max_rows
    )
    caption = _build_telegram_image_caption(company_name, containers)
    report_url = (report_url or "").strip()

    text_ok = None
    image_ok = None
    error_messages = []

    def build_photo_caption(base_caption: str) -> str:
        if not report_url:
            return base_caption
        suffix = f"\n🔗 {report_url}"
        max_len = 1024
        if len(base_caption) + len(suffix) <= max_len:
            return base_caption + suffix
        allowed = max_len - len(suffix)
        if allowed <= 0:
            return report_url[:max_len]
        trimmed = base_caption
        if len(trimmed) > allowed:
            trimmed = trimmed[:max(0, allowed - 3)] + "..."
        return trimmed + suffix

    if telegram_mode == "text" and report_url:
        text_message = f"{text_message}\n\n🔗 Ver reporte web:\n{report_url}"

    if telegram_mode in ("text", "both"):
        text_ok, text_err = send_telegram_message(bot_token, chat_id, text_message)
        if not text_ok:
            error_messages.append(f"text failed: {text_err}")

    if telegram_mode in ("image", "both"):
        image_pages, render_err = _render_telegram_table_image(
            containers=containers,
            company_name=company_name,
            include_matched=include_matched,
            include_unmatched=include_unmatched,
            max_rows=max_rows
        )
        if not image_pages:
            image_ok = False
            error_messages.append(f"image render failed: {render_err}")
        else:
            page_errors = []
            sent_count = 0
            total_pages = len(image_pages)
            for page_idx, image_bytes in enumerate(image_pages, 1):
                if page_idx == 1:
                    page_caption = build_photo_caption(caption)
                else:
                    page_caption = f"{company_name} | page {page_idx}/{total_pages}"
                ok, err = send_telegram_photo(bot_token, chat_id, image_bytes, caption=page_caption)
                if ok:
                    sent_count += 1
                else:
                    page_errors.append(f"page {page_idx}: {err}")

            image_ok = sent_count > 0
            if page_errors:
                error_messages.append("image send partial failed: " + "; ".join(page_errors))

    if telegram_mode == "text":
        if text_ok:
            return True, "Telegram text sent"
        return False, "; ".join(error_messages) if error_messages else "Telegram text failed"

    if telegram_mode == "image":
        if image_ok:
            return True, "Telegram image sent"
        # fallback to text to avoid total loss
        if report_url:
            text_message = f"{text_message}\n\n🔗 Ver reporte web:\n{report_url}"
        fallback_ok, fallback_err = send_telegram_message(bot_token, chat_id, text_message)
        if fallback_ok:
            return True, "Telegram image failed, fallback text sent"
        error_messages.append(f"fallback text failed: {fallback_err}")
        return False, "; ".join(error_messages)

    # both mode: allow partial success to prevent repeated duplicates
    if text_ok or image_ok:
        if text_ok and image_ok:
            return True, "Telegram text+image sent"
        return True, "Telegram partial success: " + "; ".join(error_messages)

    return False, "; ".join(error_messages) if error_messages else "Telegram send failed"

