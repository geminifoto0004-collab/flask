"""
??§?å?æ¨¡ç?
?Ÿèƒ½ï¼šITI/ZOFRI ??§æª¢æŸ¥?ä»»?™ç®¡?†ã€éƒµä»¶é€šçŸ¥
"""

import json
import hashlib
import uuid
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from database import get_db_connection, get_lastrowid
from services.email_service import send_email
from services.telegram_service import send_telegram_message
from services.zofri_iti_service import (
    iti_data, process_data
)
from utils.time_utils import get_chile_time_naive


# ========== ?Ÿæ? API Key ==========
def generate_api_key() -> str:
    """?Ÿæ??¯ä???API Key"""
    return str(uuid.uuid4()).replace('-', '')


# ========== ? å?å¯†ç¢¼ ==========
def hash_password(password: str) -> str:
    """ä½¿ç”¨ SHA256 ? å?å¯†ç¢¼"""
    return hashlib.sha256(password.encode()).hexdigest()


def compute_result_hash(result: Dict) -> str:
    """è¨ˆç???§çµæ??„ç©©å®?Hash"""
    try:
        payload = json.dumps(result, sort_keys=True, default=str)
    except Exception:
        payload = str(result)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


# ========== ?µå»º??§ä»»å? ==========
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
    telegram_chat_id: str = None
) -> Tuple[bool, str]:
    """
    ?µå»º??§ä»»å?
    è¿”å?ï¼??¯å¦?å?, ?¯èª¤ä¿¡æ¯?–ä»»?™ID)
    """
    if not company_name:
        return False, "è«‹è¨­ç½®å…¬?¸å?ç¨±ï?company_nameï¼?
    
    if not notify_email and not notify_telegram:
        return False, "?³å??€è¦é¸?‡ä?ç¨®é€šçŸ¥?¹å?"
    
    if notify_email and not notification_emails:
        return False, "?³å??€è¦ä??‹é€šçŸ¥?µç®±"
    
    if notify_telegram and (not telegram_bot_token or not telegram_chat_id):
        return False, "Telegram Bot Token ??Chat ID ?ªè¨­ç½?
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?Ÿæ? API Key
        api_key = generate_api_key()
        
        # æ³¨æ?ï¼šå?ç¢¼æš«?‚ä?? å?å­˜å„²ï¼ˆå???ZOFRI ?»é??€è¦å?å§‹å?ç¢¼ï?
        # TODO: å¾Œç??¹ç‚ºä½¿ç”¨ AES ?¯é€†å?å¯?
        
        # å°‡éƒµç®±å?è¡¨è???JSON
        emails_json = json.dumps(notification_emails or [])
        
        cursor.execute('''
            INSERT INTO user_monitor_configs 
            (user_id, api_key, zofri_username, zofri_password, zofri_rut_entidad, 
             zofri_rut_representante, notification_emails, company_name, email_subject, 
             notify_email, notify_telegram, telegram_bot_token, telegram_chat_id, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (user_id, api_key, zofri_username, zofri_password, zofri_rut_entidad,
              zofri_rut_representante, emails_json, company_name, email_subject,
              1 if notify_email else 0, 1 if notify_telegram else 0, telegram_bot_token, telegram_chat_id))
        
        task_id = get_lastrowid(cursor, conn)
        conn.commit()
        conn.close()
        
        return True, str(task_id)
        
    except Exception as e:
        return False, f"?µå»ºå¤±æ?: {str(e)}"


# ========== ?²å??¨æˆ¶?„ç›£?§ä»»??==========
def get_user_monitor_tasks(user_id: int) -> List[Dict]:
    """?²å??¨æˆ¶?„æ??‰ç›£?§ä»»??""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, api_key, zofri_username, zofri_rut_entidad, 
                   notification_emails, last_check_time, is_active, created_at,
                   notify_email, notify_telegram, telegram_chat_id
            FROM user_monitor_configs
            WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (user_id,))
        
        tasks = []
        for row in cursor.fetchall():
            task = dict(row)
            # è§???µç®±?—è¡¨
            task['notification_emails'] = json.loads(task['notification_emails'] or '[]')
            task['notify_email'] = True if task.get('notify_email') is None else bool(task.get('notify_email'))
            task['notify_telegram'] = bool(task.get('notify_telegram'))
            tasks.append(task)
        
        conn.close()
        return tasks
        
    except Exception as e:
        print(f"?²å?ä»»å?å¤±æ?: {e}")
        return []


# ========== ?²å??®å€‹ä»»??==========
def get_monitor_task(task_id: int, user_id: int = None) -> Optional[Dict]:
    """?²å??®å€‹ç›£?§ä»»?™ï??¯é¸?¨æˆ¶IDé©—è?ï¼?""
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
            return task
        return None
        
    except Exception as e:
        print(f"?²å?ä»»å?å¤±æ?: {e}")
        return None


# ========== ?´æ–°??§ä»»å? ==========
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
    is_active: bool = None
) -> Tuple[bool, str]:
    """?´æ–°??§ä»»å?"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # æª¢æŸ¥ä»»å??¯å¦å­˜åœ¨ä¸”å±¬?¼è©²?¨æˆ¶
        cursor.execute('''
            SELECT id, notification_emails, notify_email, notify_telegram, telegram_bot_token, telegram_chat_id
            FROM user_monitor_configs
            WHERE id = ? AND user_id = ?
        ''', (task_id, user_id))
        existing = cursor.fetchone()
        if not existing:
            conn.close()
            return False, "ä»»å?ä¸å??¨æ??¡æ???
        
        if isinstance(existing, dict):
            existing_emails = json.loads(existing.get('notification_emails') or '[]')
            existing_notify_email = True if existing.get('notify_email') is None else bool(existing.get('notify_email'))
            existing_notify_telegram = bool(existing.get('notify_telegram'))
            existing_token = existing.get('telegram_bot_token')
            existing_chat_id = existing.get('telegram_chat_id')
        else:
            existing_emails = json.loads(existing[1] or '[]')
            existing_notify_email = True if existing[2] is None else bool(existing[2])
            existing_notify_telegram = bool(existing[3])
            existing_token = existing[4]
            existing_chat_id = existing[5]
        
        # æ§‹å»º?´æ–°èªå¥
        updates = []
        params = []
        
        if zofri_username:
            updates.append('zofri_username = ?')
            params.append(zofri_username)
        
        if zofri_password:
            updates.append('zofri_password = ?')
            params.append(zofri_password)  # ?«æ?ä¸å?å¯?
        
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
        
        if is_active is not None:
            updates.append('is_active = ?')
            params.append(1 if is_active else 0)
        
        # é©—è??šçŸ¥?ç½®
        final_notify_email = existing_notify_email if notify_email is None else notify_email
        final_notify_telegram = existing_notify_telegram if notify_telegram is None else notify_telegram
        final_emails = existing_emails if notification_emails is None else notification_emails
        final_token = telegram_bot_token if telegram_bot_token else existing_token
        final_chat_id = telegram_chat_id if telegram_chat_id else existing_chat_id
        
        if not final_notify_email and not final_notify_telegram:
            conn.close()
            return False, "?³å??€è¦é¸?‡ä?ç¨®é€šçŸ¥?¹å?"
        
        if final_notify_email and not final_emails:
            conn.close()
            return False, "?³å??€è¦ä??‹é€šçŸ¥?µç®±"
        
        if final_notify_telegram and (not final_token or not final_chat_id):
            conn.close()
            return False, "Telegram Bot Token ??Chat ID ?ªè¨­ç½?
        
        if not updates:
            conn.close()
            return False, "æ²’æ??€è¦æ›´?°ç?å­—æ®µ"
        
        # ?¥å??›é€šçŸ¥?¹å??–è??´é€šçŸ¥?®æ?ï¼Œé?ç½®å??‰ç??¼é€è???        if (notify_email is not None and notify_email and not existing_notify_email) or (notification_emails is not None):
            updates.append('last_email_result_hash = NULL')
        if (notify_telegram is not None and notify_telegram and not existing_notify_telegram) or (telegram_bot_token or telegram_chat_id):
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
        
        return True, "?´æ–°?å?"
        
    except Exception as e:
        return False, f"?´æ–°å¤±æ?: {str(e)}"


# ========== ?ªé™¤??§ä»»å? ==========
def delete_monitor_task(task_id: int, user_id: int) -> Tuple[bool, str]:
    """?ªé™¤??§ä»»å?"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # æª¢æŸ¥ä»»å??¯å¦å­˜åœ¨ä¸”å±¬?¼è©²?¨æˆ¶
        cursor.execute('SELECT id FROM user_monitor_configs WHERE id = ? AND user_id = ?', 
                      (task_id, user_id))
        if not cursor.fetchone():
            conn.close()
            return False, "ä»»å?ä¸å??¨æ??¡æ???
        
        cursor.execute('DELETE FROM user_monitor_configs WHERE id = ?', (task_id,))
        conn.commit()
        conn.close()
        
        return True, "?ªé™¤?å?"
        
    except Exception as e:
        return False, f"?ªé™¤å¤±æ?: {str(e)}"


# ========== æ¸…ç©ºä»»å??„æª¢?¥æ­·??==========
def clear_check_history(task_id: int, user_id: int = None) -> Tuple[bool, str]:
    """
    æ¸…ç©ºä»»å??„æª¢?¥æ­·?²ï?å°?last_check_result è¨­ç‚º NULLï¼?
    è¿”å?ï¼??¯å¦?å?, ?¯èª¤ä¿¡æ¯)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if user_id:
            # æª¢æŸ¥ä»»å??¯å¦å­˜åœ¨ä¸”å±¬?¼è©²?¨æˆ¶
            cursor.execute('SELECT id FROM user_monitor_configs WHERE id = ? AND user_id = ?', 
                          (task_id, user_id))
            if not cursor.fetchone():
                conn.close()
                return False, "ä»»å?ä¸å??¨æ??¡æ???
            
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
        return True, "æª¢æŸ¥æ­·å²å·²æ?ç©?
        
    except Exception as e:
        return False, f"æ¸…ç©ºå¤±æ?: {str(e)}"


# ========== ?¹æ? API Key ?²å?ä»»å? ==========
def get_task_by_api_key(api_key: str) -> Optional[Dict]:
    """?¹æ? API Key ?²å?ä»»å??ç½®"""
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
            return task
        return None
        
    except Exception as e:
        print(f"?²å?ä»»å?å¤±æ?: {e}")
        return None


# ========== ä½¿ç”¨ä»»å??ç½®?»é? ZOFRI ==========
def login_zofri_with_config(task_config: Dict) -> Tuple[bool, Dict, str]:
    """
    ä½¿ç”¨ä»»å??ç½®?»é? ZOFRI
    è¿”å?ï¼??¯å¦?å?, cookieså­—å…¸, ?¯èª¤ä¿¡æ¯)
    æ³¨æ?ï¼šé€™è£¡?‡è¨­å¯†ç¢¼?¨æ•¸?šåº«ä¸­æ˜¯? å??„ï??€è¦è§£å¯?
    ä½†ç‚ºäº†ç°¡?–ï??«æ??ˆå??¸æ?åº«è??–æ?ä¸è§£å¯†ï?å¾Œç??€è¦å¯¦?¾ï?
    """
    try:
        session = requests.Session()
        login_url = 'https://zvirtual.zofri.cl/controller?accion=login'
        
        # æ³¨æ?ï¼šé€™è£¡?€è¦å??¸æ?åº«è??–å?å§‹å?ç¢¼æ?è§??
        # ?®å??ˆå?è¨?task_config ä¸­å·²ç¶“æ?æ­?¢º?„å?ç¢?
        login_data = {
            'usuario': task_config['zofri_username'],
            'clave': task_config['zofri_password'],  # ä½¿ç”¨?¨æˆ¶è¼¸å…¥?„å?ç¢¼ï?å¾æ•¸?šåº«è®€?–ï?
            'rutEntidad': task_config['zofri_rut_entidad'],
            'rutRepresentante': '',  # ä¸ä½¿??RUT ä»?¡¨
            'identificador': 'zsve',
            'tipoUsuario': 'TUSU3'
        }
        
        response = session.post(login_url, data=login_data, verify=False, timeout=10)
        if response.status_code != 200 or 'success' not in response.text:
            return False, {}, "ZOFRI ?»é?å¤±æ?ï¼Œè?æª¢æŸ¥è³¬è?å¯†ç¢¼"
        
        cookies_dict = {cookie.name: cookie.value for cookie in session.cookies}
        return True, cookies_dict, ""
        
    except Exception as e:
        return False, {}, f"?»é?å¤±æ?: {str(e)}"


# ========== ?·è???§æª¢æŸ¥ ==========
def check_monitor_task(task_config: Dict) -> Tuple[bool, Dict, str]:
    """
    ?·è???§æª¢æŸ¥
    è¿”å?ï¼??¯å¦?å?, æª¢æŸ¥çµæ?, ?¯èª¤ä¿¡æ¯)
    """
    import uuid
    execution_id = str(uuid.uuid4())[:8]  # ?Ÿæ??¯ä??·è?ID?¨æ–¼è¿½è¹¤
    print(f"[??§æª¢æŸ¥-{execution_id}] ?‹å??·è???§æª¢æŸ¥ï¼Œä»»?™ID: {task_config.get('id', 'N/A')}")
    
    try:
        # 1. ä½¿ç”¨ä»»å??ç½®?»é? ZOFRI
        login_success, cookies_dict, error = login_zofri_with_config(task_config)
        if not login_success:
            return False, {}, error
        
        # 2. ?²å? ZOFRI ?¸æ?ï¼?8å¤©å…§ï¼?
        
        today = get_chile_time_naive()
        end_date = today.strftime('%Y-%m-%d')
        start_date = (today - timedelta(days=28)).strftime('%Y-%m-%d')
        
        # ?‹å?å¯¦ç¾ fetch_tickets ?è¼¯ï¼ˆä½¿?¨å‚³?¥ç? cookiesï¼?
        busqueda_url = "https://zvirtual.zofri.cl/controller?accion=busquedaDocumentosSolicitar"
        data_busqueda = {
            "rutEmpresa": task_config['zofri_rut_entidad'],
            "formato": "json",
            "fechaDesde": start_date,
            "fechaHasta": end_date
        }
        
        time.sleep(3)  # ZOFRI ?€è¦æ??“æ???
        
        try:
            r = requests.post(busqueda_url, json=data_busqueda, cookies=cookies_dict, verify=False, timeout=10)
            r.raise_for_status()
            j = r.json()
            ticket = j.get("data", {}).get("entity", {}).get("ticket")
        except:
            ticket = None
        
        # è¼ªè©¢?²å? ticket
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
            return False, {}, "?¡æ??²å? ZOFRI ticket"
        
        # 3. ?²å??‡æ??¸æ?ï¼ˆæ??•å¯¦?¾ï?ä½¿ç”¨?³å…¥??cookiesï¼?
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
                
                # ?•ç??¸æ?ï¼ˆé?è¦å‚³??cookies_dictï¼?
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
        
        # 4. ?²å? ITI ?¸æ?ä¸¦åŒ¹??
        print(f"[??§æª¢æŸ¥-{execution_id}] ZOFRI å®¹å™¨ç¸½æ•¸: {len(df_zofri)}")
        
        iti_results = iti_data()
        
        matched_data = pd.DataFrame()
        matched_indices = pd.Series([False] * len(df_zofri), index=df_zofri.index)
        iti_info_map = {}  # å­˜å„²?¹é???ITI ä¿¡æ¯ï¼š{index: {iti_item, vessel_name, fecha}}
        
        for iti_item in iti_results:
            if len(iti_item) == 7:
                iti_codigo = (iti_item[2] + iti_item[3] + iti_item[4]).strip()
                # ä½¿ç”¨ _container_number ?²è??¹é?
                if '_container_number' not in df_zofri.columns:
                    # å¦‚æ?æ²’æ? _container_numberï¼Œå??€?°ä½¿??glosa_codigo
                    df_zofri['_container_number'] = df_zofri['glosa_codigo']
                df_zofri['_container_number'] = df_zofri['_container_number'].astype(str).str.strip()
                match = df_zofri[df_zofri['_container_number'] == iti_codigo]
                
                if not match.empty:
                    match = match.copy()
                    # ä¿å? ITI ä¿¡æ¯
                    for match_idx in match.index:
                        # ?å??¥æ?ï¼ˆiti_item[5] ?¯æ—¥?Ÿå?ç¬¦ä¸²ï¼Œæ ¼å¼ï?05/01/2026 10:24ï¼?
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
        
        # ?“å° ZOFRI å®¹å™¨?¹é?çµæ?
        matched_count = int(matched_indices.sum())
        unmatched_count = len(unmatched_data)
        print(f"[??§æª¢æŸ¥-{execution_id}] ZOFRI å®¹å™¨?¹é?çµæ?: ç¸½æ•¸={len(df_zofri)}, å·²åŒ¹??VISADO)={matched_count}, ?ªåŒ¹??{unmatched_count}")
        
        # ?“å°å·²åŒ¹?ç? ZOFRI å®¹å™¨
        if matched_count > 0:
            print(f"[??§æª¢æŸ¥-{execution_id}] ========== å·²åŒ¹??VISADO)??ZOFRI å®¹å™¨ (??{matched_count} ?? ==========")
            for idx, row in df_zofri[matched_indices].iterrows():
                codigo = row.get('codigo', 'N/A')
                glosa_codigo = row.get('glosa_codigo', 'N/A')
                glosa_descripcion = row.get('glosa_descripcion', 'N/A')
                estado = row.get('nombre', 'N/A')
                print(f"[??§æª¢æŸ¥-{execution_id}] ??VISADO: codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
            print(f"[??§æª¢æŸ¥-{execution_id}] ========== å·²åŒ¹?å®¹?¨å?è¡¨ç???==========")
        
        # ?“å°?ªåŒ¹?ç? ZOFRI å®¹å™¨
        if unmatched_count > 0:
            print(f"[??§æª¢æŸ¥-{execution_id}] ========== ?ªåŒ¹?ç? ZOFRI å®¹å™¨ (??{unmatched_count} ?? ==========")
            for idx, row in unmatched_data.iterrows():
                codigo = row.get('codigo', 'N/A')
                glosa_codigo = row.get('glosa_codigo', 'N/A')
                glosa_descripcion = row.get('glosa_descripcion', 'N/A')
                estado = row.get('nombre', 'N/A')
                print(f"[??§æª¢æŸ¥-{execution_id}] ???ªåŒ¹?? codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
            print(f"[??§æª¢æŸ¥-{execution_id}] ========== ?ªåŒ¹?å®¹?¨å?è¡¨ç???==========")
        else:
            print(f"[??§æª¢æŸ¥-{execution_id}] ???€??ZOFRI å®¹å™¨?½å·²?¹é?(VISADO)ï¼Œæ??‰æœª?¹é??„å®¹??)
        
        # 5. è½‰æ??ºå??¸å?è¡¨ï??ƒè€?iti.py ?„é?è¼¯ï?
        all_containers = []
        for idx, row in df_zofri.iterrows():
            # ä½¿ç”¨ matched_indices ä¾†åˆ¤?·æ˜¯?¦åŒ¹?ï???iti.py ?è¼¯ä¸€?´ï?
            # matched_indices ??index ??df_zofri ??index ä¸€?´ï??¯ä»¥?´æ¥è¨ªå?
            try:
                is_matched = bool(matched_indices.loc[idx])
            except (KeyError, IndexError):
                # å¦‚æ?ç´¢å?ä¸å??¨ï?é»˜è??ºæœª?¹é?
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
            
            # å¦‚æ??¯å·²?¹é??„ï?æ·»å? ITI ä¿¡æ¯
            if idx in iti_info_map:
                container['iti_item'] = iti_info_map[idx]['iti_item']
                container['vessel_name'] = iti_info_map[idx]['vessel_name']
                container['fecha'] = iti_info_map[idx]['fecha']
            all_containers.append(container)
        
        # èª¿è©¦ï¼šæ??°åŒ¹?çµ±è¨ˆï???iti.py ?„æ??°é?è¼¯ä??´ï?
        matched_count = int(matched_indices.sum())
        unmatched_count = len(unmatched_data)  # ä½¿ç”¨ unmatched_data ?„é•·åº¦ï???iti.py ä¸€?´ï?
        print(f"[??§æª¢æŸ¥-{execution_id}] å®¹å™¨çµ±è?: ç¸½æ•¸={len(all_containers)}, å·²åŒ¹??{matched_count}, ?ªåŒ¹??{unmatched_count}")
        
        # é¡å?èª¿è©¦ï¼šæ??°æœª?¹é?å®¹å™¨?„è©³ç´°ä¿¡?¯ï???iti.py ?„æ??°é?è¼¯ä??´ï?
        if not unmatched_data.empty:
            print(f"[??§æª¢æŸ¥-{execution_id}] ========== ?ªåŒ¹?å®¹?¨å?è¡?(??{len(unmatched_data)} ?? ==========")
            for idx, row in unmatched_data.iterrows():
                codigo = row.get('codigo', 'N/A')
                glosa_codigo = row.get('glosa_codigo', 'N/A')
                glosa_descripcion = row.get('glosa_descripcion', 'N/A')
                estado = row.get('nombre', 'N/A')
                print(f"[??§æª¢æŸ¥-{execution_id}] ???ªåŒ¹?? codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
            print(f"[??§æª¢æŸ¥-{execution_id}] ========== ?ªåŒ¹?å®¹?¨å?è¡¨ç???==========")
        else:
            print(f"[??§æª¢æŸ¥-{execution_id}] ???€?‰å®¹?¨éƒ½å·²åŒ¹?ï?æ²’æ??ªåŒ¹?ç?å®¹å™¨")
        
        result = {
            'containers': all_containers,
            'matched_count': len(matched_data),
            'unmatched_count': len(unmatched_data)
        }
        
        print(f"[??§æª¢æŸ¥-{execution_id}] ??§æª¢æŸ¥å®Œæ?")
        return True, result, ""
        
    except Exception as e:
        print(f"[??§æª¢æŸ¥-{execution_id}] ??§æª¢æŸ¥å¤±æ?: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, {}, f"æª¢æŸ¥å¤±æ?: {str(e)}"


# ========== å°æ?ä¸Šæ¬¡çµæ?ï¼Œåˆ¤?·æ˜¯?¦æ?è®Šå? ==========
def has_result_changed(last_result: Optional[str], current_result: Dict) -> bool:
    """
    å°æ?ä¸Šæ¬¡?Œæœ¬æ¬¡ç??œï??¤æ–·?¯å¦?‰è??–é?è¦ç™¼?éƒµä»?
    è¿”å?ï¼šTrue è¡¨ç¤º?‰è??–é?è¦ç™¼?ï?False è¡¨ç¤ºæ²’æ?è®Šå?
    
    ?è¼¯ï¼?
    1. ç¬¬ä?æ¬¡æª¢?¥ï?last_result ?ºç©ºï¼‰ï?å¦‚æ??‰æ•¸?šï?è¿”å? Trueï¼ˆç™¼?æ??‰å®¹?¨ï??…æ‹¬?¹é??Œæœª?¹é??„ï?
    2. å¾Œç?æª¢æŸ¥ï¼?
       - å¦‚æ??‰å®¹?¨å? unmatched ??matchedï¼Œè???Trueï¼ˆç™¼?æ??‰å®¹?¨ï?
       - å¦‚æ??‰æ–°å¢ç?å®¹å™¨ï¼ˆç„¡è«–åŒ¹?è??¦ï?ï¼Œè???Trueï¼ˆç™¼?æ??‰å®¹?¨ï?
       - å¦‚æ?å®¹å™¨?¸é??‰è??–ï?è¿”å? Trueï¼ˆç™¼?æ??‰å®¹?¨ï?
       - ?¦å?è¿”å? Falseï¼ˆä??¼é€ï?
    """
    if not last_result:
        # ç¬¬ä?æ¬¡æª¢?¥ï?å¦‚æ??‰å®¹?¨æ•¸?šï?å°±ç™¼?ï??…æ‹¬?¹é??Œæœª?¹é??„ï?
        containers = current_result.get('containers', [])
        return len(containers) > 0
    
    try:
        # å°æ?ä¸Šæ¬¡?Œæœ¬æ¬¡ç???
        last_data = json.loads(last_result)
        
        # ?²å?å®¹å™¨?—è¡¨
        last_containers = last_data.get('containers', [])
        current_containers = current_result.get('containers', [])
        
        # å¦‚æ?å®¹å™¨?¸é??‰è??–ï??¼é€?
        if len(last_containers) != len(current_containers):
            return True
        
        # ?µå»ºå®¹å™¨?€?‹æ?å°„ï?{codigo: matched}
        def create_status_map(data):
            containers = data.get('containers', [])
            status_map = {}
            for c in containers:
                codigo = c.get('codigo', '')
                if codigo:  # ç¢ºä? codigo ä¸ç‚ºç©?
                    matched = c.get('matched', False)
                    status_map[codigo] = matched
            return status_map
        
        last_map = create_status_map(last_data)
        current_map = create_status_map(current_result)
        
        # ?¾å‡º?±å?å­˜åœ¨?„å®¹?¨ï??©æ¬¡æª¢æŸ¥?½å??¨ç?å®¹å™¨ï¼?
        common_codes = set(last_map.keys()) & set(current_map.keys())
        
        # å¦‚æ??‰æ–°å¢ç?å®¹å™¨ï¼ˆä??¨ä?æ¬¡ç??œä¸­?„ï?ï¼Œç™¼??
        new_codes = set(current_map.keys()) - set(last_map.keys())
        if new_codes:
            return True
        
        # æª¢æŸ¥?±å?å­˜åœ¨?„å®¹?¨ï??¯å¦?‰å? unmatched ??matched ?„è???
        for codigo in common_codes:
            last_matched = last_map.get(codigo)
            current_matched = current_map.get(codigo)
            
            # å¦‚æ?ä¸Šæ¬¡?ªåŒ¹?ï??¬æ¬¡?¹é?äº????€è¦ç™¼??
            if last_matched is False and current_matched is True:
                return True
        
        # æ²’æ?è®Šå?ï¼ˆå®¹?¨æ•¸?ç›¸?Œï?æ²’æ??°å?ï¼Œæ???unmatched ??matched ?„è??–ï?
        return False
        
    except Exception as e:
        print(f"å°æ?å¤±æ?: {e}")
        import traceback
        traceback.print_exc()
        # å°æ?å¤±æ??‚ï??ºä?å®‰å…¨èµ·è?ï¼Œè??ºæ?è®Šå?ï¼ˆç™¼?æ??‰å®¹?¨ï?
        return True


# ========== ?¼é€é€šçŸ¥?µä»¶ ==========
def send_notification_email(emails: List[str], containers: List[Dict], task_config: Dict = None) -> Tuple[bool, str]:
    """
    ?¼é€ç›£?§é€šçŸ¥?µä»¶
    ?ƒæ•¸ï¼?
        emails - ?¶ä»¶äººéƒµç®±å?è¡?
        containers - å®¹å™¨?¸æ??—è¡¨
        task_config - ??§ä»»å??ç½®ï¼ˆå¯?¸ï??…å« company_name ??email_subjectï¼?
    è¿”å?ï¼?bool, str) - (?¯å¦?å?, ?¯èª¤ä¿¡æ¯)
    """
    print(f"[??§?µä»¶] æº–å??¼é€éƒµä»¶ï??¶ä»¶äº? {emails}, å®¹å™¨?¸é?: {len(containers)}")
    
    if not containers:
        print("[??§?µä»¶] æ²’æ?å®¹å™¨?¸æ?ï¼Œè·³?ç™¼??)
        return True, "æ²’æ??°åŒ¹?ç?å®¹å™¨"
    
    if not emails:
        print("[??§?µä»¶] æ²’æ??¶ä»¶äººéƒµç®±ï?è·³é??¼é€?)
        return False, "æ²’æ??¶ä»¶äººéƒµç®?
    
    # çµ±è??¹é??Œæœª?¹é??„å®¹?¨æ•¸?ï??¨æ–¼èª¿è©¦ï¼?
    matched_count = sum(1 for c in containers if c.get('matched', False))
    unmatched_count = len(containers) - matched_count
    print(f"[??§?µä»¶] å®¹å™¨çµ±è?: ç¸½æ•¸={len(containers)}, å·²åŒ¹??{matched_count}, ?ªåŒ¹??{unmatched_count}")
    
    # å¾ä»»?™é?ç½®ç²?–å…¬?¸å?ç¨±ï?å¿…å¡«ï¼?
    if not task_config:
        return False, "ç¼ºå?ä»»å??ç½®ä¿¡æ¯"
    
    company_name = task_config.get('company_name')
    if not company_name:
        return False, "è«‹åœ¨??§ä»»å??ç½®ä¸­è¨­ç½®å…¬?¸å?ç¨±ï?company_nameï¼?
    
    # ?²å??µä»¶ä¸»é?ï¼ˆå„ª?ˆå?ä»»å??ç½®ï¼Œå??œæ??‰å°±ä½¿ç”¨é»˜è??¼å?ï¼?
    email_subject = None
    if task_config:
        email_subject = task_config.get('email_subject')
    
    # å¦‚æ?æ²’æ??ªå?ç¾©ä¸»é¡Œï?ä½¿ç”¨é»˜è??¼å?ï¼ˆå??«å…¬?¸å?ç¨±ï?
    if not email_subject:
        email_subject = f"?š¢ {company_name} æ«ƒå??šçŸ¥?š¢"
    
    # ?Ÿæ??µä»¶?§å®¹
    matched_list = []
    unmatched_list = []
    
    print(f"[??§?µä»¶] ?‹å??•ç? {len(containers)} ?‹å®¹??..")
    for container in containers:
        is_matched = container.get('matched', False)
        status_class = "status-matched" if is_matched else "status-unmatched"
        status_text = "å·²åŒ¹?? if is_matched else "?ªåŒ¹??
        
        # é¡¯ç¤ºï¼šæ?è¿°ã€ç??‹ã€é?è£ç®±?Ÿç¢¼?äº¤è²¨æ—¥?Ÿï?4?—ï?å·²å?èª¿ï?
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
            print(f"[??§?µä»¶] å·²åŒ¹?å®¹?? {container.get('glosa_codigo', 'N/A')}")
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
            print(f"[??§?µä»¶] ???ªåŒ¹?å®¹?? codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
    
    print(f"[??§?µä»¶] ?µä»¶?§å®¹?Ÿæ?: å·²åŒ¹??{len(matched_list)}, ?ªåŒ¹??{len(unmatched_list)}")
    
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
                <h1 style="color: #000000 !important; margin: 0 0 8px 0; font-size: 24px; font-weight: 600;">?š¢ {company_name} æ«ƒå??šçŸ¥?š¢</h1>
                <p>å®¹å™¨?¹é??€?‹æ›´??/p>
            </div>
            
            <div class="content">
                <div class="stats">
                    <div class="stat-box">
                        <span class="stat-number">{len(containers)}</span>
                        <span class="stat-label">ç¸½æ•¸</span>
                    </div>
                    <div class="stat-box matched">
                        <span class="stat-number">{len(matched_list)}</span>
                        <span class="stat-label">å·²åŒ¹??/span>
                    </div>
                    <div class="stat-box unmatched">
                        <span class="stat-number">{len(unmatched_list)}</span>
                        <span class="stat-label">?ªåŒ¹??/span>
                    </div>
                </div>
                
                <div class="section">
                    <div class="section-header matched">
                        <span>??/span>
                        <span>å·²åŒ¹?åˆ° ITI ({len(matched_list)} ??</span>
                    </div>
                    {f'<div class="table-container"><table cellpadding="0" cellspacing="0" style="width: 100%; border-collapse: collapse; background: white; border: 2px solid #000000;"><thead><tr><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">?è¿°</th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">?€??/th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap;">?†è?ç®±è?ç¢?/th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap; min-width: 120px;">äº¤è²¨?¥æ?</th></tr></thead><tbody>{"".join(matched_list)}</tbody></table></div>' if matched_list else '<div class="empty-message">?«ç„¡å·²åŒ¹?ç?å®¹å™¨</div>'}
                </div>
                
                {f'<div class="section"><div class="section-header unmatched"><span>??/span><span>?ªåŒ¹?åˆ° ITI ({len(unmatched_list)} ??</span></div><div class="table-container"><table cellpadding="0" cellspacing="0" style="width: 100%; border-collapse: collapse; background: white; border: 2px solid #000000;"><thead><tr><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">?è¿°</th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">?€??/th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap;">?†è?ç®±è?ç¢?/th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap; min-width: 120px;">äº¤è²¨?¥æ?</th></tr></thead><tbody>{"".join(unmatched_list)}</tbody></table></div></div>' if unmatched_list else ''}
            </div>
            
            <div class="footer">
                <div>æª¢æŸ¥?‚é?ï¼š{get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')}</div>
                <div style="margin-top: 5px;">ç¸½è?ï¼š{len(containers)} ?‹å®¹??/div>
            </div>
        </div>
    </body>
    </html>
    """
    
    # ?¼é€åˆ°?€?‰éƒµç®?
    success_count = 0
    error_messages = []
    
    # æ¸…ç??Œé?è­‰éƒµä»¶åœ°?€
    from services.email_service import clean_email_address, validate_email_format
    cleaned_emails = []
    for email in emails:
        cleaned = clean_email_address(str(email))
        if cleaned and validate_email_format(cleaned):
            cleaned_emails.append(cleaned)
        else:
            print(f"[??§?µä»¶] è·³é??¡æ??„éƒµä»¶åœ°?€: {email}")
    
    if not cleaned_emails:
        return False, "æ²’æ??‰æ??„éƒµä»¶åœ°?€"
    
    for email in cleaned_emails:
        print(f"[??§?µä»¶] æ­?œ¨?¼é€éƒµä»¶åˆ°: {email}")
        success, error = send_email(
            email,
            email_subject,  # ä½¿ç”¨?•æ??²å??„éƒµä»¶ä¸»é¡?
            html_content
        )
        if success:
            success_count += 1
            print(f"[??§?µä»¶] ???µä»¶å·²æ??Ÿç™¼?åˆ°: {email}")
        else:
            error_messages.append(f"{email}: {error}")
            print(f"[??§?µä»¶] ???µä»¶?¼é€å¤±?—åˆ° {email}: {error}")
    
    if success_count > 0:
        result_msg = f"å·²ç™¼?åˆ° {success_count}/{len(emails)} ?‹éƒµç®?
        print(f"[??§?µä»¶] ??{result_msg}")
        return True, result_msg
    else:
        result_msg = "; ".join(error_messages)
        print(f"[??§?µä»¶] ???€?‰éƒµä»¶ç™¼?å¤±?? {result_msg}")
        return False, result_msg


# ========== ?¼é€?Telegram ?šçŸ¥ ==========
def send_notification_telegram(bot_token: str, chat_id: str, containers: List[Dict], task_config: Dict = None) -> Tuple[bool, str]:
    """
    ?¼é€ç›£?§é€šçŸ¥??Telegram
    ?ƒæ•¸ï¼?        bot_token - Telegram Bot Token
        chat_id - Chat ID ??@channelusername
        containers - å®¹å™¨?¸æ??—è¡¨
        task_config - ??§ä»»å??ç½®ï¼ˆå???company_nameï¼?    è¿”å?ï¼?bool, str) - (?¯å¦?å?, ?¯èª¤ä¿¡æ¯)
    """
    if not task_config:
        return False, "ç¼ºå?ä»»å??ç½®ä¿¡æ¯"
    
    company_name = task_config.get('company_name')
    if not company_name:
        return False, "è«‹åœ¨??§ä»»å??ç½®ä¸­è¨­ç½®å…¬?¸å?ç¨±ï?company_nameï¼?
    
    if not containers:
        return True, "æ²’æ??°åŒ¹?ç?å®¹å™¨"
    
    matched = [c for c in containers if c.get('matched', False)]
    unmatched = [c for c in containers if not c.get('matched', False)]
    
    lines = []
    lines.append(f"?š¢ {company_name} ??§?šçŸ¥")
    lines.append(f"?¹é?: {len(matched)} / ?ªåŒ¹?? {len(unmatched)}")
    lines.append(f"?‚é?: {get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')}")
    
    sample = (matched + unmatched)[:5]
    if sample:
        lines.append("----")
        for item in sample:
            code = item.get('glosa_codigo') or item.get('codigo') or '-'
            estado = item.get('estado') or '-'
            lines.append(f"- {code} | {estado}")
    
    message = "\n".join(lines)
    return send_telegram_message(bot_token, chat_id, message)

