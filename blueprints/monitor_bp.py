"""
監控任務 Blueprint
功能：用戶和管理員的監控任務管理、API 檢查端點
"""

from flask import Blueprint, request, jsonify, session, render_template
from functools import wraps
from datetime import datetime
import json
from database import get_db_connection
from services.monitor_service import (
    create_monitor_task, get_user_monitor_tasks, get_monitor_task,
    update_monitor_task, delete_monitor_task, get_task_by_api_key,
    check_monitor_task, has_result_changed, send_notification_email,
    send_notification_telegram, compute_result_hash,
    generate_api_key, clear_check_history
)
from utils.time_utils import get_chile_time_naive

# 創建 Blueprint
monitor_bp = Blueprint('monitor', __name__)


# ========== 登入驗證裝飾器 ==========
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': '請先登入'}), 401
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': '請先登入'}), 401
        role = session.get('role', 'user')
        if role not in ['admin', 'super_admin']:
            return jsonify({'success': False, 'error': '權限不足'}), 403
        return f(*args, **kwargs)
    return decorated_function


def _mask_secret(value: str, tail: int = 4) -> str:
    """遮罩敏感資訊，只顯示結尾幾碼"""
    if not value:
        return ""
    if len(value) <= tail:
        return "*" * len(value)
    return "*" * (len(value) - tail) + value[-tail:]


def _parse_bool(value, default: bool = False) -> bool:
    """Parse bool from JSON values safely."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


# ========== 用戶端：獲取我的監控任務列表 ==========
@monitor_bp.route('/user/monitor/tasks', methods=['GET'])
@login_required
def user_monitor_tasks_page():
    """用戶監控任務列表頁面"""
    return render_template('user/monitor_tasks.html')


@monitor_bp.route('/api/user/monitor/tasks', methods=['GET'])
@login_required
def get_user_monitor_tasks_api():
    """獲取用戶的監控任務列表（API）"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': '用戶ID不存在'}), 400
        
        tasks = get_user_monitor_tasks(user_id)
        
        # 隱藏敏感信息
        for task in tasks:
            task.pop('zofri_password', None)
        
        return jsonify({'success': True, 'tasks': tasks})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 用戶端：創建監控任務 ==========
@monitor_bp.route('/api/user/monitor/tasks', methods=['POST'])
@login_required
def create_user_monitor_task():
    """創建監控任務"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': '用戶ID不存在'}), 400
        
        data = request.get_json()
        zofri_username = data.get('zofri_username', '').strip()
        zofri_password = data.get('zofri_password', '').strip()
        zofri_rut_entidad = data.get('zofri_rut_entidad', '').strip()
        notification_emails = data.get('notification_emails', [])
        company_name = data.get('company_name', '').strip()
        email_subject = data.get('email_subject', '').strip()
        notify_email = _parse_bool(data.get('notify_email'), True)
        notify_telegram = _parse_bool(data.get('notify_telegram'), False)
        telegram_bot_token = data.get('telegram_bot_token', '').strip()
        telegram_chat_id = data.get('telegram_chat_id', '').strip()
        telegram_mode = (data.get('telegram_mode') or 'text').strip().lower()
        telegram_include_matched = _parse_bool(data.get('telegram_include_matched'), True)
        telegram_include_unmatched = _parse_bool(data.get('telegram_include_unmatched'), True)
        telegram_max_rows = data.get('telegram_max_rows', 200)
        
        if not all([zofri_username, zofri_password, zofri_rut_entidad, company_name]):
            return jsonify({'success': False, 'error': '請填寫所有必填欄位'}), 400
        
        if not notify_email and not notify_telegram:
            return jsonify({'success': False, 'error': '請至少選擇一種通知方式'}), 400
        
        if notify_email and (not notification_emails or not isinstance(notification_emails, list)):
            return jsonify({'success': False, 'error': '至少需要一個通知郵箱'}), 400
        
        if notify_telegram and (not telegram_bot_token or not telegram_chat_id):
            return jsonify({'success': False, 'error': '請填寫 Telegram Bot Token 與 Chat ID'}), 400
        
        success, result = create_monitor_task(
            user_id=user_id,
            zofri_username=zofri_username,
            zofri_password=zofri_password,
            zofri_rut_entidad=zofri_rut_entidad,
            zofri_rut_representante='',  # 不使用，傳空字符串
            notification_emails=notification_emails,
            company_name=company_name,
            email_subject=email_subject if email_subject else None,
            notify_email=notify_email,
            notify_telegram=notify_telegram,
            telegram_bot_token=telegram_bot_token if telegram_bot_token else None,
            telegram_chat_id=telegram_chat_id if telegram_chat_id else None,
            telegram_mode=telegram_mode,
            telegram_include_matched=telegram_include_matched,
            telegram_include_unmatched=telegram_include_unmatched,
            telegram_max_rows=telegram_max_rows
        )
        
        if success:
            return jsonify({'success': True, 'task_id': result, 'message': '任務創建成功'})
        else:
            return jsonify({'success': False, 'error': result}), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 用戶端：更新監控任務 ==========
@monitor_bp.route('/api/user/monitor/tasks/<int:task_id>', methods=['PUT'])
@login_required
def update_user_monitor_task(task_id):
    """更新監控任務"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': '用戶ID不存在'}), 400
        
        data = request.get_json()
        telegram_bot_token = data.get('telegram_bot_token')
        telegram_chat_id = data.get('telegram_chat_id')
        notify_email = _parse_bool(data.get('notify_email'), None) if 'notify_email' in data else None
        notify_telegram = _parse_bool(data.get('notify_telegram'), None) if 'notify_telegram' in data else None
        telegram_include_matched = _parse_bool(data.get('telegram_include_matched'), None) if 'telegram_include_matched' in data else None
        telegram_include_unmatched = _parse_bool(data.get('telegram_include_unmatched'), None) if 'telegram_include_unmatched' in data else None
        telegram_max_rows = data.get('telegram_max_rows') if 'telegram_max_rows' in data else None
        
        success, message = update_monitor_task(
            task_id=task_id,
            user_id=user_id,
            zofri_username=data.get('zofri_username'),
            zofri_password=data.get('zofri_password'),
            zofri_rut_entidad=data.get('zofri_rut_entidad'),
            notification_emails=data.get('notification_emails'),
            company_name=data.get('company_name'),
            email_subject=data.get('email_subject'),
            notify_email=notify_email,
            notify_telegram=notify_telegram,
            telegram_bot_token=telegram_bot_token.strip() if isinstance(telegram_bot_token, str) and telegram_bot_token.strip() else None,
            telegram_chat_id=telegram_chat_id.strip() if isinstance(telegram_chat_id, str) and telegram_chat_id.strip() else None,
            telegram_mode=(data.get('telegram_mode') or '').strip().lower() if 'telegram_mode' in data else None,
            telegram_include_matched=telegram_include_matched,
            telegram_include_unmatched=telegram_include_unmatched,
            telegram_max_rows=telegram_max_rows,
            is_active=data.get('is_active')
        )
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 用戶端：刪除監控任務 ==========
@monitor_bp.route('/api/user/monitor/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def delete_user_monitor_task(task_id):
    """刪除監控任務"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': '用戶ID不存在'}), 400
        
        success, message = delete_monitor_task(task_id, user_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 用戶端：獲取 API Key ==========
@monitor_bp.route('/api/user/monitor/tasks/<int:task_id>/api-key', methods=['GET'])
@login_required
def get_task_api_key(task_id):
    """獲取任務的 API Key"""
    try:
        user_id = session.get('user_id')
        task = get_monitor_task(task_id, user_id)
        
        if not task:
            return jsonify({'success': False, 'error': '任務不存在'}), 404
        
        return jsonify({
            'success': True,
            'api_key': task['api_key'],
            'task_id': task_id
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 用戶端：獲取任務詳情 ==========
@monitor_bp.route('/api/user/monitor/tasks/<int:task_id>', methods=['GET'])
@login_required
def get_user_monitor_task_detail(task_id):
    """獲取任務詳情（用於編輯）"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': '用戶ID不存在'}), 400
        
        task = get_monitor_task(task_id, user_id)
        
        if not task:
            return jsonify({'success': False, 'error': '任務不存在'}), 404
        
        # 隱藏敏感信息（密碼不返回）
        task.pop('zofri_password', None)
        telegram_token = task.pop('telegram_bot_token', None)
        task['telegram_token_masked'] = _mask_secret(telegram_token)
        task['telegram_token_last4'] = telegram_token[-4:] if telegram_token else ''
        task['telegram_configured'] = True if (telegram_token and task.get('telegram_chat_id')) else False
        task.pop('last_email_result_hash', None)
        task.pop('last_telegram_result_hash', None)
        
        return jsonify({'success': True, 'task': task})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 用戶端：清空檢查歷史 ==========
@monitor_bp.route('/api/user/monitor/tasks/<int:task_id>/clear-history', methods=['POST'])
@login_required
def clear_task_history(task_id):
    """清空任務的檢查歷史（用於測試）"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': '用戶ID不存在'}), 400
        
        success, message = clear_check_history(task_id, user_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 用戶端：重新生成 API Key ==========
@monitor_bp.route('/api/user/monitor/tasks/<int:task_id>/regenerate-key', methods=['POST'])
@login_required
def regenerate_api_key(task_id):
    """重新生成 API Key"""
    try:
        user_id = session.get('user_id')
        task = get_monitor_task(task_id, user_id)
        
        if not task:
            return jsonify({'success': False, 'error': '任務不存在'}), 404
        
        new_api_key = generate_api_key()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_monitor_configs
            SET api_key = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
        ''', (new_api_key, get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S'), task_id, user_id))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'api_key': new_api_key,
            'message': 'API Key 已重新生成'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 管理員端：獲取用戶的監控任務 ==========
@monitor_bp.route('/api/admin/users/<int:user_id>/monitor-tasks', methods=['GET'])
@admin_required
def get_user_monitor_tasks_admin(user_id):
    """獲取指定用戶的監控任務（管理員）"""
    try:
        tasks = get_user_monitor_tasks(user_id)
        
        # 隱藏敏感信息
        for task in tasks:
            task.pop('zofri_password', None)
        
        return jsonify({'success': True, 'tasks': tasks})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 管理員端：更新用戶的監控任務 ==========
@monitor_bp.route('/api/admin/monitor/tasks/<int:task_id>', methods=['PUT'])
@admin_required
def update_monitor_task_admin(task_id):
    """更新監控任務（管理員）"""
    try:
        data = request.get_json()
        
        # 獲取任務以確定 user_id
        task = get_monitor_task(task_id)
        if not task:
            return jsonify({'success': False, 'error': '任務不存在'}), 404
        
        success, message = update_monitor_task(
            task_id=task_id,
            user_id=task['user_id'],
            zofri_username=data.get('zofri_username'),
            zofri_password=data.get('zofri_password'),
            zofri_rut_entidad=data.get('zofri_rut_entidad'),
            notification_emails=data.get('notification_emails'),
            is_active=data.get('is_active')
        )
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 管理員端：刪除監控任務 ==========
@monitor_bp.route('/api/admin/monitor/tasks/<int:task_id>', methods=['DELETE'])
@admin_required
def delete_monitor_task_admin(task_id):
    """刪除監控任務（管理員）"""
    try:
        task = get_monitor_task(task_id)
        if not task:
            return jsonify({'success': False, 'error': '任務不存在'}), 404
        
        success, message = delete_monitor_task(task_id, task['user_id'])
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 公開 API：監控檢查（用於 cron-job） ==========
@monitor_bp.route('/api/monitor/check', methods=['GET'])
def check_monitor_api():
    """
    監控檢查 API（公開，需要 API Key）
    用於 console.cron-job.org 定時調用
    """
    try:
        api_key = request.args.get('api_key')
        if not api_key:
            return jsonify({'success': False, 'error': '缺少 API Key'}), 400
        
        # 獲取任務配置
        task_config = get_task_by_api_key(api_key)
        if not task_config:
            return jsonify({'success': False, 'error': '無效的 API Key'}), 401
        
        if not task_config.get('is_active', False):
            return jsonify({'success': False, 'error': '任務已停用'}), 400
        
        # 使用異步任務執行檢查（避免超過 Render 的 30 秒超時限制）
        try:
            from services.async_task_service import create_async_task
            async_task_id = create_async_task('monitor_check', task_config)
            
            # 立即返回任務 ID，任務在後台執行
            current_time = get_chile_time_naive()
            return jsonify({
                'success': True,
                'message': '任務已啟動，正在後台執行',
                'task_id': async_task_id,
                'status': 'pending',
                'task_config_id': task_config['id'],
                'request_time': current_time.strftime('%Y-%m-%d %H:%M:%S'),
                'request_time_readable': current_time.strftime('%Y年%m月%d日 %H:%M:%S'),
                'note': '請使用 /api/monitor/task/' + async_task_id + ' 查詢任務狀態'
            }), 202  # 202 Accepted 表示請求已接受，正在處理
        except ImportError:
            # 如果異步任務服務不可用，回退到同步執行（可能超時）
            print(f"[監控API] 異步任務服務不可用，使用同步執行模式")
            success, result, error = check_monitor_task(task_config)
            
            if not success:
                return jsonify({
                    'success': False,
                    'error': error,
                    'task_id': task_config['id']
                }), 500
            
            # 同步執行模式：對比上次結果，判斷是否有變化
            last_result = task_config.get('last_check_result')
            should_send = has_result_changed(last_result, result)
            result_hash = compute_result_hash(result)
            
            print(f"[監控API] 任務ID: {task_config['id']}, 應該發送: {should_send}")
            print(f"[監控API] 上次結果存在: {last_result is not None}")
            print(f"[監控API] 當前容器數量: {len(result.get('containers', []))}")
            
            notify_email = True if task_config.get('notify_email') is None else bool(task_config.get('notify_email'))
            notify_telegram = bool(task_config.get('notify_telegram'))
            
            email_sent = None
            email_error = None
            email_attempted = False
            if notify_email:
                if task_config.get('last_email_result_hash') != result_hash:
                    print(f"[監控API] 準備發送郵件，收件人: {task_config['notification_emails']}")
                    send_success, send_message = send_notification_email(
                        task_config['notification_emails'],
                        result.get('containers', []),
                        task_config
                    )
                    email_attempted = True
                    email_sent = send_success
                    email_error = None if send_success else send_message
                    print(f"[監控API] 郵件發送結果: {send_success}, 消息: {send_message}")
                else:
                    email_sent = True
                    print(f"[監控API] 郵件已對此結果發送，跳過")
            
            telegram_sent = None
            telegram_error = None
            telegram_attempted = False
            if notify_telegram:
                if task_config.get('last_telegram_result_hash') != result_hash:
                    print(f"[監控API] 準備發送 Telegram 通知")
                    send_success, send_message = send_notification_telegram(
                        task_config.get('telegram_bot_token'),
                        task_config.get('telegram_chat_id'),
                        result.get('containers', []),
                        task_config
                    )
                    telegram_attempted = True
                    telegram_sent = send_success
                    telegram_error = None if send_success else send_message
                    print(f"[監控API] Telegram 發送結果: {send_success}, 消息: {send_message}")
                else:
                    telegram_sent = True
                    print(f"[監控API] Telegram 已對此結果發送，跳過")
            
            # 計算變化數量（用於響應信息）
            new_matches_count = 0
            if last_result:
                try:
                    last_data = json.loads(last_result)
                    last_containers = last_data.get('containers', [])
                    last_status_map = {c['codigo']: c.get('matched', False) for c in last_containers}
                    current_containers = result.get('containers', [])
                    for c in current_containers:
                        codigo = c.get('codigo')
                        current_matched = c.get('matched', False)
                        last_matched = last_status_map.get(codigo, None)
                        if last_matched is False and current_matched is True:
                            new_matches_count += 1
                except:
                    pass
            
            # 更新數據庫記錄
            check_time = get_chile_time_naive()
            check_time_str = check_time.strftime('%Y-%m-%d %H:%M:%S')
            check_time_readable = check_time.strftime('%Y年%m月%d日 %H:%M:%S')
            
            conn = get_db_connection()
            cursor = conn.cursor()
            updates = ['last_check_time = ?', 'last_check_result = ?']
            params = [check_time_str, json.dumps(result)]
            
            if notify_email and email_attempted and email_sent:
                updates.append('last_email_result_hash = ?')
                params.append(result_hash)
            
            if notify_telegram and telegram_attempted and telegram_sent:
                updates.append('last_telegram_result_hash = ?')
                params.append(result_hash)
            
            params.append(task_config['id'])
            cursor.execute(f'''
                UPDATE user_monitor_configs
                SET {', '.join(updates)}
                WHERE id = ?
            ''', params)
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'task_id': task_config['id'],
                'matched_count': result.get('matched_count', 0),
                'unmatched_count': result.get('unmatched_count', 0),
                'new_matches_count': new_matches_count,
                'email_sent': email_sent,
                'telegram_sent': telegram_sent,
                'email_error': email_error,
                'telegram_error': telegram_error,
                'check_time': check_time_str,
                'check_time_readable': check_time_readable  # 人類可讀的時間格式
            })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 公開 API：查詢異步任務狀態 ==========
@monitor_bp.route('/api/monitor/task/<task_id>', methods=['GET'])
def get_async_task_status(task_id):
    """
    查詢異步任務狀態（公開，不需要認證）
    用於查詢 /api/monitor/check 返回的異步任務狀態
    """
    try:
        from services.async_task_service import get_task_status
        task_status = get_task_status(task_id)
        
        if not task_status:
            return jsonify({
                'success': False,
                'error': '任務不存在'
            }), 404
        
        # 解析 result 和 error（如果是 JSON 字符串）
        if task_status.get('result'):
            try:
                task_status['result'] = json.loads(task_status['result'])
            except:
                pass
        
        if task_status.get('error'):
            try:
                task_status['error'] = json.loads(task_status['error'])
            except:
                pass
        
        return jsonify({
            'success': True,
            'task': task_status
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

