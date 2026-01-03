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
        
        if not all([zofri_username, zofri_password, zofri_rut_entidad]):
            return jsonify({'success': False, 'error': '請填寫所有必填欄位'}), 400
        
        if not notification_emails or not isinstance(notification_emails, list):
            return jsonify({'success': False, 'error': '至少需要一個通知郵箱'}), 400
        
        success, result = create_monitor_task(
            user_id=user_id,
            zofri_username=zofri_username,
            zofri_password=zofri_password,
            zofri_rut_entidad=zofri_rut_entidad,
            zofri_rut_representante='',  # 不使用，傳空字符串
            notification_emails=notification_emails
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
        
        success, message = update_monitor_task(
            task_id=task_id,
            user_id=user_id,
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
        
        # 執行檢查
        # 注意：需要從數據庫讀取原始密碼（目前先假設 task_config 中有）
        # TODO: 實現密碼解密邏輯
        success, result, error = check_monitor_task(task_config)
        
        if not success:
            return jsonify({
                'success': False,
                'error': error,
                'task_id': task_config['id']
            }), 500
        
        # 對比上次結果，判斷是否有變化
        last_result = task_config.get('last_check_result')
        should_send = has_result_changed(last_result, result)
        
        print(f"[監控API] 任務ID: {task_config['id']}, 應該發送: {should_send}")
        print(f"[監控API] 上次結果存在: {last_result is not None}")
        print(f"[監控API] 當前容器數量: {len(result.get('containers', []))}")
        
        # 如果有變化（或第一次檢查有數據），發送通知
        notification_sent = False
        if should_send:
            print(f"[監控API] 準備發送郵件，收件人: {task_config['notification_emails']}")
            # 發送所有當前容器
            send_success, send_message = send_notification_email(
                task_config['notification_emails'],
                result.get('containers', [])  # 發送所有容器
            )
            notification_sent = send_success
            print(f"[監控API] 郵件發送結果: {send_success}, 消息: {send_message}")
        else:
            print(f"[監控API] 不需要發送郵件（結果無變化）")
        
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_monitor_configs
            SET last_check_time = ?, last_check_result = ?
            WHERE id = ?
        ''', (
            get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S'),
            json.dumps(result),
            task_config['id']
        ))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'task_id': task_config['id'],
            'matched_count': result.get('matched_count', 0),
            'unmatched_count': result.get('unmatched_count', 0),
            'new_matches_count': new_matches_count,
            'notification_sent': notification_sent,
            'check_time': get_chile_time_naive().strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

