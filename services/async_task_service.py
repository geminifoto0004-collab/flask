"""
異步任務服務
用於處理耗時的監控任務，避免 HTTP 請求超時
"""

import threading
import time
from datetime import datetime
from typing import Dict, Optional
from database import get_db_connection, get_cursor
from utils.time_utils import get_chile_time_naive


# 任務狀態
TASK_STATUS_PENDING = 'pending'
TASK_STATUS_RUNNING = 'running'
TASK_STATUS_COMPLETED = 'completed'
TASK_STATUS_FAILED = 'failed'


def create_async_task(task_type: str, task_config: Dict, task_data: Dict = None) -> str:
    """
    創建異步任務
    返回：任務 ID
    """
    conn = get_db_connection()
    cursor = get_cursor(conn)
    
    task_id = f"{task_type}_{int(time.time() * 1000)}"
    status = TASK_STATUS_PENDING
    created_at = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
    
    # 將任務配置和數據序列化為 JSON
    import json
    config_json = json.dumps(task_config) if task_config else '{}'
    data_json = json.dumps(task_data) if task_data else '{}'
    
    try:
        cursor.execute('''
            INSERT INTO async_tasks (task_id, task_type, status, task_config, task_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (task_id, task_type, status, config_json, data_json, created_at))
        
        conn.commit()
        conn.close()
        
        # 啟動後台任務
        thread = threading.Thread(target=_run_task, args=(task_id, task_type, task_config, task_data))
        thread.daemon = True
        thread.start()
        
        return task_id
    except Exception as e:
        conn.close()
        raise Exception(f"創建任務失敗: {str(e)}")


def get_task_status(task_id: str) -> Optional[Dict]:
    """
    獲取任務狀態
    返回：任務狀態字典或 None
    """
    conn = get_db_connection()
    cursor = get_cursor(conn)
    
    try:
        cursor.execute('''
            SELECT task_id, task_type, status, result, error, created_at, updated_at
            FROM async_tasks WHERE task_id = ?
        ''', (task_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        # 處理返回格式（可能是字典或元組）
        if isinstance(row, dict):
            return {
                'task_id': row.get('task_id'),
                'task_type': row.get('task_type'),
                'status': row.get('status'),
                'result': row.get('result'),
                'error': row.get('error'),
                'created_at': row.get('created_at'),
                'updated_at': row.get('updated_at')
            }
        else:
            return {
                'task_id': row[0],
                'task_type': row[1],
                'status': row[2],
                'result': row[3],
                'error': row[4],
                'created_at': row[5],
                'updated_at': row[6] if len(row) > 6 else None
            }
    except Exception as e:
        conn.close()
        return None


def _run_task(task_id: str, task_type: str, task_config: Dict, task_data: Dict):
    """
    執行任務（後台線程）
    """
    conn = get_db_connection()
    cursor = get_cursor(conn)
    
    try:
        # 更新狀態為運行中
        updated_at = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            UPDATE async_tasks 
            SET status = ?, updated_at = ?
            WHERE task_id = ?
        ''', (TASK_STATUS_RUNNING, updated_at, task_id))
        conn.commit()
        
        # 執行任務
        if task_type == 'monitor_check':
            from services.monitor_service import check_monitor_task
            success, result, error = check_monitor_task(task_config)
            
            # 更新任務結果
            import json
            updated_at = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
            
            if success:
                result_json = json.dumps(result)
                cursor.execute('''
                    UPDATE async_tasks 
                    SET status = ?, result = ?, updated_at = ?
                    WHERE task_id = ?
                ''', (TASK_STATUS_COMPLETED, result_json, updated_at, task_id))
                conn.commit()
                
                # 處理郵件通知（在後台執行）
                try:
                    from services.monitor_service import has_result_changed, send_notification_email
                    # 獲取任務配置中的上次結果
                    cursor.execute('''
                        SELECT last_check_result FROM user_monitor_configs WHERE id = ?
                    ''', (task_config.get('id'),))
                    last_result_row = cursor.fetchone()
                    last_result = None
                    if last_result_row:
                        if isinstance(last_result_row, dict):
                            last_result = last_result_row.get('last_check_result')
                        else:
                            last_result = last_result_row[0] if len(last_result_row) > 0 else None
                    
                    should_send = has_result_changed(last_result, result)
                    if should_send:
                        send_notification_email(
                            task_config.get('notification_emails', []),
                            result.get('containers', []),
                            task_config
                        )
                except Exception as e:
                    # 郵件發送失敗不影響任務完成狀態
                    print(f"[Async Task] 郵件發送失敗: {e}")
            else:
                cursor.execute('''
                    UPDATE async_tasks 
                    SET status = ?, error = ?, updated_at = ?
                    WHERE task_id = ?
                ''', (TASK_STATUS_FAILED, error, updated_at, task_id))
                conn.commit()
        else:
            # 未知任務類型
            updated_at = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('''
                UPDATE async_tasks 
                SET status = ?, error = ?, updated_at = ?
                WHERE task_id = ?
            ''', (TASK_STATUS_FAILED, f"未知任務類型: {task_type}", updated_at, task_id))
            conn.commit()
        
    except Exception as e:
        # 更新任務為失敗
        updated_at = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            UPDATE async_tasks 
            SET status = ?, error = ?, updated_at = ?
            WHERE task_id = ?
        ''', (TASK_STATUS_FAILED, str(e), updated_at, task_id))
        conn.commit()
    finally:
        conn.close()

