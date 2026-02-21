"""
????璅∠?
?嚗TI/ZOFRI ??瑼Ｘ?遙?恣?隞園
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


# ========== ?? API Key ==========
def generate_api_key() -> str:
    """???臭???API Key"""
    return str(uuid.uuid4()).replace('-', '')


# ========== ??撖Ⅳ ==========
def hash_password(password: str) -> str:
    """雿輻 SHA256 ??撖Ⅳ"""
    return hashlib.sha256(password.encode()).hexdigest()


def compute_result_hash(result: Dict) -> str:
    """閮???蝯??帘摰?Hash"""
    try:
        payload = json.dumps(result, sort_keys=True, default=str)
    except Exception:
        payload = str(result)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


# ========== ?萄遣??隞餃? ==========
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
    ?萄遣??隞餃?
    餈?嚗??臬??, ?航炊靽⊥?遙?D)
    """
    if not company_name:
        return False, "company_name is required"
    
    if not notify_email and not notify_telegram:
        return False, "?喳??閬??蝔桅?孵?"
    
    if notify_email and not notification_emails:
        return False, "?喳??閬???萇拳"
    
    if notify_telegram and (not telegram_bot_token or not telegram_chat_id):
        return False, "telegram_bot_token and telegram_chat_id are required when telegram is enabled"
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ?? API Key
        api_key = generate_api_key()
        
        # 瘜冽?嚗?蝣潭????摮嚗???ZOFRI ?駁??閬?憪?蝣潘?
        # TODO: 敺??寧雿輻 AES ?舫?撖?
        
        # 撠蝞勗?銵刻???JSON
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
        return False, f"?萄遣憭望?: {str(e)}"


# ========== ?脣??冽??找遙??==========
def get_user_monitor_tasks(user_id: int) -> List[Dict]:
    """?脣??冽????找遙??""
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
            # 閫???萇拳?”
            task['notification_emails'] = json.loads(task['notification_emails'] or '[]')
            task['notify_email'] = True if task.get('notify_email') is None else bool(task.get('notify_email'))
            task['notify_telegram'] = bool(task.get('notify_telegram'))
            tasks.append(task)
        
        conn.close()
        return tasks
        
    except Exception as e:
        print(f"?脣?隞餃?憭望?: {e}")
        return []


# ========== ?脣??桀遙??==========
def get_monitor_task(task_id: int, user_id: int = None) -> Optional[Dict]:
    """?脣??桀?找遙???舫?冽ID撽?嚗?""
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
        print(f"?脣?隞餃?憭望?: {e}")
        return None


# ========== ?湔??隞餃? ==========
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
    """?湔??隞餃?"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 瑼Ｘ隞餃??臬摮銝惇?潸府?冽
        cursor.execute('''
            SELECT id, notification_emails, notify_email, notify_telegram, telegram_bot_token, telegram_chat_id
            FROM user_monitor_configs
            WHERE id = ? AND user_id = ?
        ''', (task_id, user_id))
        existing = cursor.fetchone()
        if not existing:
            conn.close()
            return False, "隞餃?銝??冽??⊥???
        
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
        
        # 瑽遣?湔隤
        updates = []
        params = []
        
        if zofri_username:
            updates.append('zofri_username = ?')
            params.append(zofri_username)
        
        if zofri_password:
            updates.append('zofri_password = ?')
            params.append(zofri_password)  # ?急?銝?撖?
        
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
        
        # 撽???蔭
        final_notify_email = existing_notify_email if notify_email is None else notify_email
        final_notify_telegram = existing_notify_telegram if notify_telegram is None else notify_telegram
        final_emails = existing_emails if notification_emails is None else notification_emails
        final_token = telegram_bot_token if telegram_bot_token else existing_token
        final_chat_id = telegram_chat_id if telegram_chat_id else existing_chat_id
        
        if not final_notify_email and not final_notify_telegram:
            conn.close()
            return False, "?喳??閬??蝔桅?孵?"
        
        if final_notify_email and not final_emails:
            conn.close()
            return False, "?喳??閬???萇拳"
        
        if final_notify_telegram and (not final_token or not final_chat_id):
            conn.close()
            return False, "Telegram Bot Token ??Chat ID ?芾身蝵?
        
        if not updates:
            conn.close()
            return False, "瘝??閬?啁?摮挾"
        
        # ?亙???孵????湧?格?嚗?蝵桀????潮???        if (notify_email is not None and notify_email and not existing_notify_email) or (notification_emails is not None):
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
        
        return True, "?湔??"
        
    except Exception as e:
        return False, f"?湔憭望?: {str(e)}"


# ========== ?芷??隞餃? ==========
def delete_monitor_task(task_id: int, user_id: int) -> Tuple[bool, str]:
    """?芷??隞餃?"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 瑼Ｘ隞餃??臬摮銝惇?潸府?冽
        cursor.execute('SELECT id FROM user_monitor_configs WHERE id = ? AND user_id = ?', 
                      (task_id, user_id))
        if not cursor.fetchone():
            conn.close()
            return False, "隞餃?銝??冽??⊥???
        
        cursor.execute('DELETE FROM user_monitor_configs WHERE id = ?', (task_id,))
        conn.commit()
        conn.close()
        
        return True, "?芷??"
        
    except Exception as e:
        return False, f"?芷憭望?: {str(e)}"


# ========== 皜征隞餃??炎?交風??==========
def clear_check_history(task_id: int, user_id: int = None) -> Tuple[bool, str]:
    """
    皜征隞餃??炎?交風?莎?撠?last_check_result 閮剔 NULL嚗?
    餈?嚗??臬??, ?航炊靽⊥)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if user_id:
            # 瑼Ｘ隞餃??臬摮銝惇?潸府?冽
            cursor.execute('SELECT id FROM user_monitor_configs WHERE id = ? AND user_id = ?', 
                          (task_id, user_id))
            if not cursor.fetchone():
                conn.close()
                return False, "隞餃?銝??冽??⊥???
            
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
        return True, "瑼Ｘ甇瑕撌脫?蝛?
        
    except Exception as e:
        return False, f"皜征憭望?: {str(e)}"


# ========== ?寞? API Key ?脣?隞餃? ==========
def get_task_by_api_key(api_key: str) -> Optional[Dict]:
    """?寞? API Key ?脣?隞餃??蔭"""
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
        print(f"?脣?隞餃?憭望?: {e}")
        return None


# ========== 雿輻隞餃??蔭?駁? ZOFRI ==========
def login_zofri_with_config(task_config: Dict) -> Tuple[bool, Dict, str]:
    """
    雿輻隞餃??蔭?駁? ZOFRI
    餈?嚗??臬??, cookies摮, ?航炊靽⊥)
    瘜冽?嚗ㄐ?身撖Ⅳ?冽?澈銝剜?????閬圾撖?
    雿鈭陛???急????豢?摨怨???銝圾撖?敺??閬祕?橘?
    """
    try:
        session = requests.Session()
        login_url = 'https://zvirtual.zofri.cl/controller?accion=login'
        
        # 瘜冽?嚗ㄐ?閬??豢?摨怨???憪?蝣潭?閫??
        # ?桀???閮?task_config 銝剖歇蝬?甇?Ⅱ??蝣?
        login_data = {
            'usuario': task_config['zofri_username'],
            'clave': task_config['zofri_password'],  # 雿輻?冽頛詨??蝣潘?敺?澈霈??
            'rutEntidad': task_config['zofri_rut_entidad'],
            'rutRepresentante': '',  # 銝蝙??RUT 隞?”
            'identificador': 'zsve',
            'tipoUsuario': 'TUSU3'
        }
        
        response = session.post(login_url, data=login_data, verify=False, timeout=10)
        if response.status_code != 200 or 'success' not in response.text:
            return False, {}, "ZOFRI ?駁?憭望?嚗?瑼Ｘ鞈祈?撖Ⅳ"
        
        cookies_dict = {cookie.name: cookie.value for cookie in session.cookies}
        return True, cookies_dict, ""
        
    except Exception as e:
        return False, {}, f"?駁?憭望?: {str(e)}"


# ========== ?瑁???瑼Ｘ ==========
def check_monitor_task(task_config: Dict) -> Tuple[bool, Dict, str]:
    """
    ?瑁???瑼Ｘ
    餈?嚗??臬??, 瑼Ｘ蝯?, ?航炊靽⊥)
    """
    import uuid
    execution_id = str(uuid.uuid4())[:8]  # ???臭??瑁?ID?冽餈質馱
    print(f"[??瑼Ｘ-{execution_id}] ???瑁???瑼Ｘ嚗遙?D: {task_config.get('id', 'N/A')}")
    
    try:
        # 1. 雿輻隞餃??蔭?駁? ZOFRI
        login_success, cookies_dict, error = login_zofri_with_config(task_config)
        if not login_success:
            return False, {}, error
        
        # 2. ?脣? ZOFRI ?豢?嚗?8憭拙嚗?
        
        today = get_chile_time_naive()
        end_date = today.strftime('%Y-%m-%d')
        start_date = (today - timedelta(days=28)).strftime('%Y-%m-%d')
        
        # ??撖衣 fetch_tickets ?摩嚗蝙?典?亦? cookies嚗?
        busqueda_url = "https://zvirtual.zofri.cl/controller?accion=busquedaDocumentosSolicitar"
        data_busqueda = {
            "rutEmpresa": task_config['zofri_rut_entidad'],
            "formato": "json",
            "fechaDesde": start_date,
            "fechaHasta": end_date
        }
        
        time.sleep(3)  # ZOFRI ?閬?????
        
        try:
            r = requests.post(busqueda_url, json=data_busqueda, cookies=cookies_dict, verify=False, timeout=10)
            r.raise_for_status()
            j = r.json()
            ticket = j.get("data", {}).get("entity", {}).get("ticket")
        except:
            ticket = None
        
        # 頛芾岷?脣? ticket
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
            return False, {}, "?⊥??脣? ZOFRI ticket"
        
        # 3. ?脣????豢?嚗??祕?橘?雿輻?喳??cookies嚗?
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
                
                # ???豢?嚗?閬??cookies_dict嚗?
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
        
        # 4. ?脣? ITI ?豢?銝血??
        print(f"[??瑼Ｘ-{execution_id}] ZOFRI 摰孵蝮賣: {len(df_zofri)}")
        
        iti_results = iti_data()
        
        matched_data = pd.DataFrame()
        matched_indices = pd.Series([False] * len(df_zofri), index=df_zofri.index)
        iti_info_map = {}  # 摮?寥???ITI 靽⊥嚗index: {iti_item, vessel_name, fecha}}
        
        for iti_item in iti_results:
            if len(iti_item) == 7:
                iti_codigo = (iti_item[2] + iti_item[3] + iti_item[4]).strip()
                # 雿輻 _container_number ?脰??寥?
                if '_container_number' not in df_zofri.columns:
                    # 憒?瘝? _container_number嚗???唬蝙??glosa_codigo
                    df_zofri['_container_number'] = df_zofri['glosa_codigo']
                df_zofri['_container_number'] = df_zofri['_container_number'].astype(str).str.strip()
                match = df_zofri[df_zofri['_container_number'] == iti_codigo]
                
                if not match.empty:
                    match = match.copy()
                    # 靽? ITI 靽⊥
                    for match_idx in match.index:
                        # ???交?嚗ti_item[5] ?舀??蝚虫葡嚗撘?05/01/2026 10:24嚗?
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
        
        # ? ZOFRI 摰孵?寥?蝯?
        matched_count = int(matched_indices.sum())
        unmatched_count = len(unmatched_data)
        print(f"[??瑼Ｘ-{execution_id}] ZOFRI 摰孵?寥?蝯?: 蝮賣={len(df_zofri)}, 撌脣??VISADO)={matched_count}, ?芸??{unmatched_count}")
        
        # ?撌脣?? ZOFRI 摰孵
        if matched_count > 0:
            print(f"[??瑼Ｘ-{execution_id}] ========== 撌脣??VISADO)??ZOFRI 摰孵 (??{matched_count} ?? ==========")
            for idx, row in df_zofri[matched_indices].iterrows():
                codigo = row.get('codigo', 'N/A')
                glosa_codigo = row.get('glosa_codigo', 'N/A')
                glosa_descripcion = row.get('glosa_descripcion', 'N/A')
                estado = row.get('nombre', 'N/A')
                print(f"[??瑼Ｘ-{execution_id}] ??VISADO: codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
            print(f"[??瑼Ｘ-{execution_id}] ========== 撌脣?捆?典?銵函???==========")
        
        # ??芸?? ZOFRI 摰孵
        if unmatched_count > 0:
            print(f"[??瑼Ｘ-{execution_id}] ========== ?芸?? ZOFRI 摰孵 (??{unmatched_count} ?? ==========")
            for idx, row in unmatched_data.iterrows():
                codigo = row.get('codigo', 'N/A')
                glosa_codigo = row.get('glosa_codigo', 'N/A')
                glosa_descripcion = row.get('glosa_descripcion', 'N/A')
                estado = row.get('nombre', 'N/A')
                print(f"[??瑼Ｘ-{execution_id}] ???芸?? codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
            print(f"[??瑼Ｘ-{execution_id}] ========== ?芸?捆?典?銵函???==========")
        else:
            print(f"[??瑼Ｘ-{execution_id}] ?????ZOFRI 摰孵?賢歇?寥?(VISADO)嚗???寥??捆??)
        
        # 5. 頧??箏??詨?銵剁???iti.py ??頛荔?
        all_containers = []
        for idx, row in df_zofri.iterrows():
            # 雿輻 matched_indices 靘?瑟?血????iti.py ?摩銝?湛?
            # matched_indices ??index ??df_zofri ??index 銝?湛??臭誑?湔閮芸?
            try:
                is_matched = bool(matched_indices.loc[idx])
            except (KeyError, IndexError):
                # 憒?蝝Ｗ?銝??剁?暺??箸?寥?
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
            
            # 憒??臬歇?寥???瘛餃? ITI 靽⊥
            if idx in iti_info_map:
                container['iti_item'] = iti_info_map[idx]['iti_item']
                container['vessel_name'] = iti_info_map[idx]['vessel_name']
                container['fecha'] = iti_info_map[idx]['fecha']
            all_containers.append(container)
        
        # 隤輯岫嚗??啣?絞閮???iti.py ???圈?頛臭??湛?
        matched_count = int(matched_indices.sum())
        unmatched_count = len(unmatched_data)  # 雿輻 unmatched_data ?摨佗???iti.py 銝?湛?
        print(f"[??瑼Ｘ-{execution_id}] 摰孵蝯梯?: 蝮賣={len(all_containers)}, 撌脣??{matched_count}, ?芸??{unmatched_count}")
        
        # 憿?隤輯岫嚗??唳?寥?摰孵?底蝝唬縑?荔???iti.py ???圈?頛臭??湛?
        if not unmatched_data.empty:
            print(f"[??瑼Ｘ-{execution_id}] ========== ?芸?捆?典?銵?(??{len(unmatched_data)} ?? ==========")
            for idx, row in unmatched_data.iterrows():
                codigo = row.get('codigo', 'N/A')
                glosa_codigo = row.get('glosa_codigo', 'N/A')
                glosa_descripcion = row.get('glosa_descripcion', 'N/A')
                estado = row.get('nombre', 'N/A')
                print(f"[??瑼Ｘ-{execution_id}] ???芸?? codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
            print(f"[??瑼Ｘ-{execution_id}] ========== ?芸?捆?典?銵函???==========")
        else:
            print(f"[??瑼Ｘ-{execution_id}] ????捆?券撌脣??瘝??芸??摰孵")
        
        result = {
            'containers': all_containers,
            'matched_count': len(matched_data),
            'unmatched_count': len(unmatched_data)
        }
        
        print(f"[??瑼Ｘ-{execution_id}] ??瑼Ｘ摰?")
        return True, result, ""
        
    except Exception as e:
        print(f"[??瑼Ｘ-{execution_id}] ??瑼Ｘ憭望?: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, {}, f"瑼Ｘ憭望?: {str(e)}"


# ========== 撠?銝活蝯?嚗?瑟?行?霈? ==========
def has_result_changed(last_result: Optional[str], current_result: Dict) -> bool:
    """
    撠?銝活?甈∠????斗?臬????閬?隞?
    餈?嚗rue 銵函內????閬??False 銵函內瘝?霈?
    
    ?摩嚗?
    1. 蝚砌?甈⊥炎?伐?last_result ?箇征嚗?憒????餈? True嚗???捆?剁???寥???寥???
    2. 敺?瑼Ｘ嚗?
       - 憒??捆?典? unmatched ??matched嚗???True嚗???捆?剁?
       - 憒??憓?摰孵嚗隢???佗?嚗???True嚗???捆?剁?
       - 憒?摰孵?賊?????餈? True嚗???捆?剁?
       - ?血?餈? False嚗??潮?
    """
    if not last_result:
        # 蝚砌?甈⊥炎?伐?憒??捆?冽??撠梁????寥???寥???
        containers = current_result.get('containers', [])
        return len(containers) > 0
    
    try:
        # 撠?銝活?甈∠???
        last_data = json.loads(last_result)
        
        # ?脣?摰孵?”
        last_containers = last_data.get('containers', [])
        current_containers = current_result.get('containers', [])
        
        # 憒?摰孵?賊??????潮?
        if len(last_containers) != len(current_containers):
            return True
        
        # ?萄遣摰孵???撠?{codigo: matched}
        def create_status_map(data):
            containers = data.get('containers', [])
            status_map = {}
            for c in containers:
                codigo = c.get('codigo', '')
                if codigo:  # 蝣箔? codigo 銝蝛?
                    matched = c.get('matched', False)
                    status_map[codigo] = matched
            return status_map
        
        last_map = create_status_map(last_data)
        current_map = create_status_map(current_result)
        
        # ?曉?勗?摮?捆?剁??拇活瑼Ｘ?賢??函?摰孵嚗?
        common_codes = set(last_map.keys()) & set(current_map.keys())
        
        # 憒??憓?摰孵嚗??其?甈∠??葉??嚗??
        new_codes = set(current_map.keys()) - set(last_map.keys())
        if new_codes:
            return True
        
        # 瑼Ｘ?勗?摮?捆?剁??臬?? unmatched ??matched ????
        for codigo in common_codes:
            last_matched = last_map.get(codigo)
            current_matched = current_map.get(codigo)
            
            # 憒?銝活?芸???祆活?寥?鈭????閬??
            if last_matched is False and current_matched is True:
                return True
        
        # 瘝?霈?嚗捆?冽???瘝??啣?嚗???unmatched ??matched ????
        return False
        
    except Exception as e:
        print(f"撠?憭望?: {e}")
        import traceback
        traceback.print_exc()
        # 撠?憭望????箔?摰韏瑁?嚗??箸?霈?嚗???捆?剁?
        return True


# ========== ?潮?萎辣 ==========
def send_notification_email(emails: List[str], containers: List[Dict], task_config: Dict = None) -> Tuple[bool, str]:
    """
    ?潮?折?萎辣
    ?嚗?
        emails - ?嗡辣鈭粹蝞勗?銵?
        containers - 摰孵?豢??”
        task_config - ??隞餃??蔭嚗?賂?? company_name ??email_subject嚗?
    餈?嚗?bool, str) - (?臬??, ?航炊靽⊥)
    """
    print(f"[???萎辣] 皞??潮隞塚??嗡辣鈭? {emails}, 摰孵?賊?: {len(containers)}")
    
    if not containers:
        print("[???萎辣] 瘝?摰孵?豢?嚗歲???)
        return True, "瘝??啣??摰孵"
    
    if not emails:
        print("[???萎辣] 瘝??嗡辣鈭粹蝞梧?頝喲??潮?)
        return False, "瘝??嗡辣鈭粹蝞?
    
    # 蝯梯??寥???寥??捆?冽???冽隤輯岫嚗?
    matched_count = sum(1 for c in containers if c.get('matched', False))
    unmatched_count = len(containers) - matched_count
    print(f"[???萎辣] 摰孵蝯梯?: 蝮賣={len(containers)}, 撌脣??{matched_count}, ?芸??{unmatched_count}")
    
    # 敺遙??蝵桃??詨?蝔梧?敹‵嚗?
    if not task_config:
        return False, "蝻箏?隞餃??蔭靽⊥"
    
    company_name = task_config.get('company_name')
    if not company_name:
        return False, "隢??隞餃??蔭銝剛身蝵桀?詨?蝔梧?company_name嚗?
    
    # ?脣??萎辣銝駁?嚗??隞餃??蔭嚗????停雿輻暺??澆?嚗?
    email_subject = None
    if task_config:
        email_subject = task_config.get('email_subject')
    
    # 憒?瘝??芸?蝢拐蜓憿?雿輻暺??澆?嚗??怠?詨?蝔梧?
    if not email_subject:
        email_subject = f"? {company_name} 瑹???"
    
    # ???萎辣?批捆
    matched_list = []
    unmatched_list = []
    
    print(f"[???萎辣] ???? {len(containers)} ?捆??..")
    for container in containers:
        is_matched = container.get('matched', False)
        status_class = "status-matched" if is_matched else "status-unmatched"
        status_text = "撌脣?? if is_matched else "?芸??
        
        # 憿舐內嚗?餈啜???鋆拳?Ⅳ?漱鞎冽??4??撌脣?隤選?
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
            print(f"[???萎辣] 撌脣?捆?? {container.get('glosa_codigo', 'N/A')}")
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
            print(f"[???萎辣] ???芸?捆?? codigo={codigo}, glosa_codigo={glosa_codigo}, descripcion={glosa_descripcion}, estado={estado}")
    
    print(f"[???萎辣] ?萎辣?批捆??: 撌脣??{len(matched_list)}, ?芸??{len(unmatched_list)}")
    
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
                <h1 style="color: #000000 !important; margin: 0 0 8px 0; font-size: 24px; font-weight: 600;">? {company_name} 瑹???</h1>
                <p>摰孵?寥?????/p>
            </div>
            
            <div class="content">
                <div class="stats">
                    <div class="stat-box">
                        <span class="stat-number">{len(containers)}</span>
                        <span class="stat-label">蝮賣</span>
                    </div>
                    <div class="stat-box matched">
                        <span class="stat-number">{len(matched_list)}</span>
                        <span class="stat-label">撌脣??/span>
                    </div>
                    <div class="stat-box unmatched">
                        <span class="stat-number">{len(unmatched_list)}</span>
                        <span class="stat-label">?芸??/span>
                    </div>
                </div>
                
                <div class="section">
                    <div class="section-header matched">
                        <span>??/span>
                        <span>撌脣? ITI ({len(matched_list)} ??</span>
                    </div>
                    {f'<div class="table-container"><table cellpadding="0" cellspacing="0" style="width: 100%; border-collapse: collapse; background: white; border: 2px solid #000000;"><thead><tr><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">?膩</th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">???/th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap;">??蝞梯?蝣?/th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap; min-width: 120px;">鈭方疏?交?</th></tr></thead><tbody>{"".join(matched_list)}</tbody></table></div>' if matched_list else '<div class="empty-message">?怎撌脣??摰孵</div>'}
                </div>
                
                {f'<div class="section"><div class="section-header unmatched"><span>??/span><span>?芸? ITI ({len(unmatched_list)} ??</span></div><div class="table-container"><table cellpadding="0" cellspacing="0" style="width: 100%; border-collapse: collapse; background: white; border: 2px solid #000000;"><thead><tr><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">?膩</th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000;">???/th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap;">??蝞梯?蝣?/th><th style="border: 1px solid #000000; padding: 14px 10px; text-align: left; font-weight: 700; font-size: 13px; color: #000000; background: #e5e7eb; border-bottom: 2px solid #000000; white-space: nowrap; min-width: 120px;">鈭方疏?交?</th></tr></thead><tbody>{"".join(unmatched_list)}</tbody></table></div></div>' if unmatched_list else ''}
            </div>
            
            <div class="footer">
                <div>瑼Ｘ??嚗get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')}</div>
                <div style="margin-top: 5px;">蝮質?嚗len(containers)} ?捆??/div>
            </div>
        </div>
    </body>
    </html>
    """
    
    # ?潮??蝞?
    success_count = 0
    error_messages = []
    
    # 皜???霅隞嗅?
    from services.email_service import clean_email_address, validate_email_format
    cleaned_emails = []
    for email in emails:
        cleaned = clean_email_address(str(email))
        if cleaned and validate_email_format(cleaned):
            cleaned_emails.append(cleaned)
        else:
            print(f"[???萎辣] 頝喲??⊥??隞嗅?: {email}")
    
    if not cleaned_emails:
        return False, "瘝????隞嗅?"
    
    for email in cleaned_emails:
        print(f"[???萎辣] 甇??潮隞嗅: {email}")
        success, error = send_email(
            email,
            email_subject,  # 雿輻???脣??隞嗡蜓憿?
            html_content
        )
        if success:
            success_count += 1
            print(f"[???萎辣] ???萎辣撌脫???: {email}")
        else:
            error_messages.append(f"{email}: {error}")
            print(f"[???萎辣] ???萎辣?潮仃? {email}: {error}")
    
    if success_count > 0:
        result_msg = f"撌脩? {success_count}/{len(emails)} ?蝞?
        print(f"[???萎辣] ??{result_msg}")
        return True, result_msg
    else:
        result_msg = "; ".join(error_messages)
        print(f"[???萎辣] ????隞嗥?仃?? {result_msg}")
        return False, result_msg


# ========== ?潮?Telegram ? ==========
def send_notification_telegram(bot_token: str, chat_id: str, containers: List[Dict], task_config: Dict = None) -> Tuple[bool, str]:
    """
    ?潮?折??Telegram
    ?嚗?        bot_token - Telegram Bot Token
        chat_id - Chat ID ??@channelusername
        containers - 摰孵?豢??”
        task_config - ??隞餃??蔭嚗???company_name嚗?    餈?嚗?bool, str) - (?臬??, ?航炊靽⊥)
    """
    if not task_config:
        return False, "蝻箏?隞餃??蔭靽⊥"
    
    company_name = task_config.get('company_name')
    if not company_name:
        return False, "隢??隞餃??蔭銝剛身蝵桀?詨?蝔梧?company_name嚗?
    
    if not containers:
        return True, "瘝??啣??摰孵"
    
    matched = [c for c in containers if c.get('matched', False)]
    unmatched = [c for c in containers if not c.get('matched', False)]
    
    lines = []
    lines.append(f"? {company_name} ???")
    lines.append(f"?寥?: {len(matched)} / ?芸?? {len(unmatched)}")
    lines.append(f"??: {get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')}")
    
    sample = (matched + unmatched)[:5]
    if sample:
        lines.append("----")
        for item in sample:
            code = item.get('glosa_codigo') or item.get('codigo') or '-'
            estado = item.get('estado') or '-'
            lines.append(f"- {code} | {estado}")
    
    message = "\n".join(lines)
    return send_telegram_message(bot_token, chat_id, message)

