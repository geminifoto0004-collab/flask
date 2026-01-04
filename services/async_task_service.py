"""
異步任務服務
用於處理耗時的監控任務，避免 HTTP 請求超時
"""

import threading
import time
import json
from datetime import datetime, date
from typing import Dict, Optional
from database import get_db_connection, get_cursor
from utils.time_utils import get_chile_time_naive


# 自定義 JSON 編碼器，處理 datetime 和 date 對象
class DateTimeEncoder(json.JSONEncoder):
    """自定義 JSON 編碼器，處理 datetime 和 date 對象"""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


def _serialize_for_json(obj):
    """
    序列化對象為 JSON 兼容格式
    將 datetime 和 date 對象轉換為字符串
    """
    if isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_json(item) for item in obj]
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat() if hasattr(obj, 'isoformat') else str(obj)
    else:
        return obj


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
    
    # 將任務配置和數據序列化為 JSON（處理 datetime 對象）
    # 先清理 datetime 對象，轉換為字符串
    clean_config = _serialize_for_json(task_config) if task_config else {}
    clean_data = _serialize_for_json(task_data) if task_data else {}
    
    config_json = json.dumps(clean_config, cls=DateTimeEncoder) if clean_config else '{}'
    data_json = json.dumps(clean_data, cls=DateTimeEncoder) if clean_data else '{}'
    
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
        task_status = {}
        if isinstance(row, dict):
            task_status = {
                'task_id': row.get('task_id'),
                'task_type': row.get('task_type'),
                'status': row.get('status'),
                'result': row.get('result'),
                'error': row.get('error'),
                'created_at': row.get('created_at'),
                'updated_at': row.get('updated_at')
            }
        else:
            task_status = {
                'task_id': row[0],
                'task_type': row[1],
                'status': row[2],
                'result': row[3],
                'error': row[4],
                'created_at': row[5],
                'updated_at': row[6] if len(row) > 6 else None
            }
        
        # 添加人類可讀的時間格式
        if task_status.get('created_at'):
            try:
                from datetime import datetime
                created_dt = datetime.strptime(task_status['created_at'], '%Y-%m-%d %H:%M:%S')
                task_status['created_at_readable'] = created_dt.strftime('%Y年%m月%d日 %H:%M:%S')
            except:
                pass
        
        if task_status.get('updated_at'):
            try:
                from datetime import datetime
                updated_dt = datetime.strptime(task_status['updated_at'], '%Y-%m-%d %H:%M:%S')
                task_status['updated_at_readable'] = updated_dt.strftime('%Y年%m月%d日 %H:%M:%S')
            except:
                pass
        
        return task_status
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
            updated_at = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
            
            if success:
                # 清理 result 中的 datetime 對象
                clean_result = _serialize_for_json(result)
                result_json = json.dumps(clean_result, cls=DateTimeEncoder)
                
                # 先獲取上次結果（在更新之前），用於判斷是否需要發送郵件
                last_result = None
                try:
                    cursor.execute('''
                        SELECT last_check_result FROM user_monitor_configs WHERE id = ?
                    ''', (task_config.get('id'),))
                    last_result_row = cursor.fetchone()
                    if last_result_row:
                        if isinstance(last_result_row, dict):
                            last_result = last_result_row.get('last_check_result')
                        else:
                            last_result = last_result_row[0] if len(last_result_row) > 0 else None
                except Exception as e:
                    print(f"[Async Task] 獲取上次結果失敗: {e}")
                
                # 更新任務狀態（包含可讀時間）
                updated_at_readable = get_chile_time_naive().strftime('%Y年%m月%d日 %H:%M:%S')
                cursor.execute('''
                    UPDATE async_tasks 
                    SET status = ?, result = ?, updated_at = ?
                    WHERE task_id = ?
                ''', (TASK_STATUS_COMPLETED, result_json, updated_at, task_id))
                conn.commit()
                
                # 更新監控任務配置中的上次檢查結果
                try:
                    cursor.execute('''
                        UPDATE user_monitor_configs
                        SET last_check_time = ?, last_check_result = ?
                        WHERE id = ?
                    ''', (
                        updated_at,
                        result_json,
                        task_config.get('id')
                    ))
                    conn.commit()
                except Exception as e:
                    print(f"[Async Task] 更新監控任務配置失敗: {e}")
                
                # 處理郵件通知（在後台執行）
                try:
                    from services.monitor_service import has_result_changed, send_notification_email
                    
                    # 檢查是否有數據變化
                    should_send = has_result_changed(last_result, result)
                    if should_send:
                        # 有數據變化，發送通知郵件
                        send_success, send_message = send_notification_email(
                            task_config.get('notification_emails', []),
                            result.get('containers', []),
                            task_config
                        )
                        print(f"[Async Task] ✅ 郵件發送結果: {send_success}, {send_message}")
                    else:
                        print(f"[Async Task] ℹ️ 沒有數據變化，跳過郵件發送")
                except Exception as e:
                    # 郵件發送失敗不影響任務完成狀態
                    print(f"[Async Task] ❌ 郵件發送失敗: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                # 任務失敗，更新狀態並發送異常通知郵件
                cursor.execute('''
                    UPDATE async_tasks 
                    SET status = ?, error = ?, updated_at = ?
                    WHERE task_id = ?
                ''', (TASK_STATUS_FAILED, error, updated_at, task_id))
                conn.commit()
                
                # 發送異常通知郵件
                try:
                    from services.monitor_service import send_notification_email
                    from services.email_service import send_email
                    
                    # 獲取通知郵箱
                    notification_emails = task_config.get('notification_emails', [])
                    if notification_emails:
                        company_name = task_config.get('company_name', '監控系統')
                        email_subject = task_config.get('email_subject', f"⚠️ {company_name} 監控任務執行失敗")
                        
                        # 生成異常通知郵件內容
                        error_html = f"""
                        <html>
                        <body style="font-family: Arial, sans-serif; padding: 20px;">
                            <h2 style="color: #d32f2f;">⚠️ 監控任務執行失敗</h2>
                            <p><strong>任務 ID:</strong> {task_config.get('id')}</p>
                            <p><strong>執行時間:</strong> {updated_at}</p>
                            <p><strong>錯誤信息:</strong></p>
                            <div style="background-color: #ffebee; padding: 15px; border-left: 4px solid #d32f2f; margin: 10px 0;">
                                <pre style="white-space: pre-wrap; word-wrap: break-word;">{error}</pre>
                            </div>
                            <p style="color: #666; font-size: 12px; margin-top: 20px;">
                                此郵件由監控系統自動發送，請檢查任務配置和系統狀態。
                            </p>
                        </body>
                        </html>
                        """
                        
                        # 發送異常通知郵件
                        for email in notification_emails:
                            send_success, send_error = send_email(email, email_subject, error_html)
                            if send_success:
                                print(f"[Async Task] 異常通知郵件已發送到: {email}")
                            else:
                                print(f"[Async Task] 異常通知郵件發送失敗到 {email}: {send_error}")
                except Exception as e:
                    print(f"[Async Task] 發送異常通知郵件失敗: {e}")
                    import traceback
                    traceback.print_exc()
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
        # 更新任務為失敗（系統異常）
        import traceback
        error_msg = f"系統異常: {str(e)}\n{traceback.format_exc()}"
        updated_at = get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            UPDATE async_tasks 
            SET status = ?, error = ?, updated_at = ?
            WHERE task_id = ?
        ''', (TASK_STATUS_FAILED, error_msg, updated_at, task_id))
        conn.commit()
        
        # 發送異常通知郵件
        try:
            from services.email_service import send_email
            
            # 獲取通知郵箱
            notification_emails = task_config.get('notification_emails', [])
            if notification_emails:
                company_name = task_config.get('company_name', '監控系統')
                email_subject = task_config.get('email_subject', f"⚠️ {company_name} 監控任務系統異常")
                
                # 生成異常通知郵件內容
                error_html = f"""
                <html>
                <body style="font-family: Arial, sans-serif; padding: 20px;">
                    <h2 style="color: #d32f2f;">⚠️ 監控任務系統異常</h2>
                    <p><strong>任務 ID:</strong> {task_config.get('id')}</p>
                    <p><strong>任務類型:</strong> {task_type}</p>
                    <p><strong>執行時間:</strong> {updated_at}</p>
                    <p><strong>異常信息:</strong></p>
                    <div style="background-color: #ffebee; padding: 15px; border-left: 4px solid #d32f2f; margin: 10px 0;">
                        <pre style="white-space: pre-wrap; word-wrap: break-word; font-size: 12px;">{error_msg}</pre>
                    </div>
                    <p style="color: #666; font-size: 12px; margin-top: 20px;">
                        此郵件由監控系統自動發送，請檢查系統狀態和日誌。
                    </p>
                </body>
                </html>
                """
                
                # 發送異常通知郵件
                for email in notification_emails:
                    send_success, send_error = send_email(email, email_subject, error_html)
                    if send_success:
                        print(f"[Async Task] 系統異常通知郵件已發送到: {email}")
                    else:
                        print(f"[Async Task] 系統異常通知郵件發送失敗到 {email}: {send_error}")
        except Exception as email_error:
            print(f"[Async Task] 發送系統異常通知郵件失敗: {email_error}")
    finally:
        conn.close()

