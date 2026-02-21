"""
監控服務模組
功能：ITI/ZOFRI 監控檢查、任務管理、郵件通知
"""

import json
import hashlib
import uuid
import io
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from database import get_db_connection, get_lastrowid
from services.email_service import send_email
from services.telegram_service import send_telegram_message, send_telegram_photo
from services.zofri_iti_service import (
    iti_data, process_data
)
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
        
        iti_results = iti_data()
        
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
                            'fecha': fecha
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


def _split_telegram_rows(containers: List[Dict], include_matched: bool, include_unmatched: bool, max_rows: int) -> Tuple[List[Dict], int]:
    rows = []
    for container in containers:
        is_matched = bool(container.get('matched', False))
        if is_matched and not include_matched:
            continue
        if (not is_matched) and not include_unmatched:
            continue
        rows.append({
            'matched': is_matched,
            'descripcion': _truncate_text(container.get('glosa_descripcion'), 48),
            'estado': _truncate_text(container.get('estado'), 28),
            'codigo': _truncate_text(container.get('glosa_codigo') or container.get('codigo'), 20),
            'fecha': _truncate_text(container.get('fecha') if is_matched else '-', 20)
        })

    total_rows = len(rows)
    max_rows = normalize_telegram_max_rows(max_rows)
    return rows[:max_rows], max(0, total_rows - max_rows)


def _build_telegram_text_message(company_name: str, containers: List[Dict], include_matched: bool, include_unmatched: bool, max_rows: int) -> str:
    matched = [c for c in containers if c.get('matched', False)]
    unmatched = [c for c in containers if not c.get('matched', False)]
    rows, hidden_count = _split_telegram_rows(containers, include_matched, include_unmatched, max_rows)
    now_text = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')

    lines = [
        f"🚢 {company_name} Monitor",
        f"Time: {now_text} (Chile)",
        f"Total: {len(containers)} | Matched: {len(matched)} | Unmatched: {len(unmatched)}",
        "----"
    ]

    if not rows:
        lines.append("No rows selected by current telegram filters.")
    else:
        for idx, row in enumerate(rows, 1):
            flag = "M" if row['matched'] else "U"
            lines.append(f"{idx}. [{flag}] {row['codigo']} | {row['estado']} | {row['fecha']} | {row['descripcion']}")

    if hidden_count > 0:
        lines.append(f"... {hidden_count} more rows hidden by telegram_max_rows")

    return "\n".join(lines)


def _build_telegram_image_caption(company_name: str, containers: List[Dict]) -> str:
    matched_count = sum(1 for item in containers if item.get('matched', False))
    unmatched_count = len(containers) - matched_count
    now_text = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
    return f"{company_name} | {now_text} | Total {len(containers)} / M {matched_count} / U {unmatched_count}"


def _render_telegram_table_image(containers: List[Dict], company_name: str, include_matched: bool, include_unmatched: bool, max_rows: int) -> Tuple[Optional[bytes], str]:
    if Image is None or ImageDraw is None or ImageFont is None:
        return None, "Pillow is not available for telegram image rendering"

    rows, hidden_count = _split_telegram_rows(containers, include_matched, include_unmatched, max_rows)
    matched_count = sum(1 for item in containers if item.get('matched', False))
    unmatched_count = len(containers) - matched_count

    margin = 28
    summary_h = 110
    header_h = 42
    row_h = 34
    footer_h = 36
    columns = [330, 180, 210, 170]
    table_w = sum(columns)
    width = margin * 2 + table_w
    height = margin * 2 + summary_h + header_h + max(1, len(rows)) * row_h + footer_h

    image = Image.new("RGB", (width, height), "#f4f6fb")
    draw = ImageDraw.Draw(image)
    font_title = ImageFont.load_default()
    font_body = ImageFont.load_default()

    y = margin
    draw.rectangle([margin, y, width - margin, y + summary_h], fill="#ffffff", outline="#dbe2ef", width=1)
    draw.text((margin + 12, y + 10), f"Monitor Report - {company_name}", fill="#111827", font=font_title)
    draw.text((margin + 12, y + 34), f"Time (Chile): {get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')}", fill="#374151", font=font_body)
    draw.text((margin + 12, y + 56), f"Total: {len(containers)}  Matched: {matched_count}  Unmatched: {unmatched_count}", fill="#1f2937", font=font_body)
    if hidden_count > 0:
        draw.text((margin + 12, y + 78), f"Rows hidden by limit: {hidden_count}", fill="#b45309", font=font_body)
    y += summary_h + 10

    draw.rectangle([margin, y, width - margin, y + header_h], fill="#1f2937")
    headers = ["Description", "Status", "Container", "ETA"]
    x = margin
    for idx, title in enumerate(headers):
        draw.text((x + 8, y + 12), title, fill="#ffffff", font=font_body)
        x += columns[idx]
    y += header_h

    if not rows:
        draw.rectangle([margin, y, width - margin, y + row_h], fill="#ffffff", outline="#d1d5db", width=1)
        draw.text((margin + 8, y + 10), "No rows selected by current telegram filters", fill="#6b7280", font=font_body)
        y += row_h
    else:
        for row in rows:
            base_color = "#ecfdf5" if row['matched'] else "#fef2f2"
            draw.rectangle([margin, y, width - margin, y + row_h], fill=base_color, outline="#d1d5db", width=1)

            values = [row['descripcion'], row['estado'], row['codigo'], row['fecha']]
            x = margin
            for idx, value in enumerate(values):
                draw.text((x + 8, y + 10), value, fill="#111827", font=font_body)
                x += columns[idx]
            y += row_h

    y += 8
    draw.text((margin + 4, y), "Generated by monitor service", fill="#6b7280", font=font_body)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), ""


# ========== 發送 Telegram 通知 ==========
def send_notification_telegram(bot_token: str, chat_id: str, containers: List[Dict], task_config: Dict = None) -> Tuple[bool, str]:
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

    text_ok = None
    image_ok = None
    error_messages = []

    if telegram_mode in ("text", "both"):
        text_ok, text_err = send_telegram_message(bot_token, chat_id, text_message)
        if not text_ok:
            error_messages.append(f"text failed: {text_err}")

    if telegram_mode in ("image", "both"):
        image_bytes, render_err = _render_telegram_table_image(
            containers=containers,
            company_name=company_name,
            include_matched=include_matched,
            include_unmatched=include_unmatched,
            max_rows=max_rows
        )
        if image_bytes is None:
            image_ok = False
            error_messages.append(f"image render failed: {render_err}")
        else:
            image_ok, image_err = send_telegram_photo(bot_token, chat_id, image_bytes, caption=caption)
            if not image_ok:
                error_messages.append(f"image send failed: {image_err}")

    if telegram_mode == "text":
        if text_ok:
            return True, "Telegram text sent"
        return False, "; ".join(error_messages) if error_messages else "Telegram text failed"

    if telegram_mode == "image":
        if image_ok:
            return True, "Telegram image sent"
        # fallback to text to avoid total loss
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

