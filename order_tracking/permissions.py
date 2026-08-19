"""
统一权限检查与过滤逻辑
"""

import functools
import sqlite3
from flask import request, jsonify, session, redirect, url_for, g

from .cloud_mode import cloud_read_only_enabled

from .models import get_db
from .permissions_config import PERMISSION_MATRIX, OWNERSHIP_RULES, STATUS_RULES


def _normalize_role(role):
    if role is None:
        return 'viewer'
    role_str = str(role).strip().lower()
    if role_str in {'administrator', 'admin', 'root', 'superuser', '管理员', '主管'}:
        return 'admin'
    if role_str in {'sales', 'seller', 'biz', 'business', '业务员', '業務員'}:
        return 'sales'
    if role_str in {'viewer', 'view', 'read', 'readonly', '查看者', '只读', '只讀'}:
        return 'viewer'
    return role_str or 'viewer'


def _get_current_user():
    """统一获取当前用户信息（Session / JWT）"""
    if hasattr(g, 'current_user') and g.current_user:
        return {
            'id': g.current_user.get('id'),
            'role': _normalize_role(g.current_user.get('role', 'viewer')),
            'username': g.current_user.get('username')
        }
    return {
        'id': session.get('user_id'),
        'role': _normalize_role(session.get('role', 'viewer')),
        'username': session.get('username')
    }


def get_current_user_context():
    """对外提供当前用户上下文（供业务层统一使用）"""
    return _get_current_user()


def _get_role_and_user_id(role=None, user_id=None):
    current = _get_current_user()
    resolved_role = _normalize_role(role or current.get('role', 'viewer'))
    resolved_user_id = user_id if user_id is not None else current.get('id')
    return resolved_role, resolved_user_id


def can_manage_by_owner(owner_id, user_id=None, role=None):
    """管理员或资源负责人可操作（不包含锁状态判断）"""
    resolved_role, resolved_user_id = _get_role_and_user_id(role, user_id)
    if resolved_role == 'admin':
        return True
    if owner_id is None or resolved_user_id is None:
        return False
    return _normalize_owner_value(owner_id) == _normalize_owner_value(resolved_user_id)


def can_access_visibility(visibility, role=None):
    """管理员或公开给业务员的资源可访问"""
    resolved_role, _ = _get_role_and_user_id(role, None)
    if resolved_role == 'admin':
        return True
    return visibility == 'all_sales'


def get_visibility_where_clause(role=None, table_alias='o', column='visibility'):
    """为查询生成可见性过滤条件（非管理员仅可见 all_sales）"""
    resolved_role, _ = _get_role_and_user_id(role, None)
    if resolved_role == 'admin':
        return None
    return f"{table_alias}.{column} = 'all_sales'"


def is_admin(role=None):
    """基于权限配置判断管理员身份"""
    allowed, _ = check_permission('user', None, 'view', role=role)
    return allowed

def _normalize_owner_value(value):
    if value is None:
        return None
    return str(value)


def ensure_order_lock_columns(conn):
    """确保 orders 表具备锁定相关字段（兼容旧数据库）"""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(orders)")
    columns = {row[1] for row in cursor.fetchall()}
    altered = False
    if 'is_locked' not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN is_locked INTEGER DEFAULT 0")
        altered = True
    if 'locked_at' not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN locked_at TIMESTAMP")
        altered = True
    if 'locked_by_id' not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN locked_by_id INTEGER")
        altered = True
    if 'locked_by_name' not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN locked_by_name TEXT")
        altered = True
    if altered:
        conn.commit()


def get_resource_info(resource_type, resource_id):
    """获取资源所有者与锁定信息"""
    conn = get_db()
    cursor = conn.cursor()
    owner_col = None
    has_lock = False
    try:
        cursor.execute("PRAGMA table_info(orders)")
        columns = {row[1] for row in cursor.fetchall()}
        owner_col = 'created_by_id' if 'created_by_id' in columns else ('created_by' if 'created_by' in columns else None)
        has_lock = 'is_locked' in columns
    except sqlite3.Error:
        owner_col = None
        has_lock = False

    try:
        if resource_type == 'order':
            ensure_order_lock_columns(conn)
            cursor.execute('SELECT * FROM orders WHERE order_number = ?', (resource_id,))
            row = cursor.fetchone()
            if not row:
                return None
            row = dict(row)
            owner_id = row.get(owner_col) if owner_col else None
            is_locked = bool(row.get('is_locked')) if has_lock else False
            return {
                'created_by_id': owner_id,
                'is_locked': is_locked
            }

        if resource_type == 'workflow':
            ensure_order_lock_columns(conn)
            cursor.execute('''
                SELECT w.*, o.is_locked
                FROM workflows w
                LEFT JOIN orders o ON w.order_number = o.order_number
                WHERE w.workflow_number = ?
            ''', (resource_id,))
            row = cursor.fetchone()
            if not row:
                return None
            row = dict(row)
            owner_id = row.get('handler_id') or row.get('created_by_id')
            is_locked = bool(row.get('is_locked')) if 'is_locked' in row else False
            return {
                'created_by_id': owner_id,
                'is_locked': is_locked
            }

        if resource_type == 'order_file':
            ensure_order_lock_columns(conn)
            cursor.execute('''
                SELECT o.*
                FROM order_files f
                INNER JOIN orders o ON f.order_number = o.order_number
                WHERE f.id = ?
            ''', (resource_id,))
            row = cursor.fetchone()
            if not row:
                cursor.execute('''
                    SELECT * FROM orders WHERE order_number = ?
                ''', (resource_id,))
                row = cursor.fetchone()
            if not row:
                return None
            row = dict(row)
            owner_id = row.get(owner_col) if owner_col else None
            is_locked = bool(row.get('is_locked')) if has_lock else False
            return {
                'created_by_id': owner_id,
                'is_locked': is_locked
            }

        if resource_type == 'workflow_file':
            ensure_order_lock_columns(conn)
            cursor.execute('''
                SELECT w.handler_id, w.created_by_id, o.is_locked
                FROM workflow_files f
                INNER JOIN workflows w ON f.workflow_number = w.workflow_number
                LEFT JOIN orders o ON w.order_number = o.order_number
                WHERE f.id = ?
            ''', (resource_id,))
            row = cursor.fetchone()
            if not row:
                cursor.execute('''
                    SELECT w.handler_id, w.created_by_id, o.is_locked
                    FROM workflows w
                    LEFT JOIN orders o ON w.order_number = o.order_number
                    WHERE w.workflow_number = ?
                ''', (resource_id,))
                row = cursor.fetchone()
            if not row:
                return None
            row = dict(row)
            owner_id = row.get('handler_id') or row.get('created_by_id')
            is_locked = bool(row.get('is_locked')) if 'is_locked' in row else False
            return {
                'created_by_id': owner_id,
                'is_locked': is_locked
            }
    finally:
        conn.close()

    return None


def check_permission(resource_type, resource_id, action, user_id=None, role=None):
    """统一权限检查入口"""
    if action != 'view' and cloud_read_only_enabled():
        return False, '雲端版本只能查看，請回公司系統修改。'
    current = _get_current_user()
    role = _normalize_role(role or current.get('role', 'viewer'))
    user_id = user_id if user_id is not None else current.get('id')

    allowed_actions = PERMISSION_MATRIX.get(role, {}).get(resource_type, [])
    if action not in allowed_actions:
        return False, '您没有权限执行此操作'

    ownership_rule = OWNERSHIP_RULES.get(role, {}).get(resource_type, 'owner_only')
    if ownership_rule == 'owner_only' and resource_id is not None:
        info = get_resource_info(resource_type, resource_id)
        if not info:
            return False, '资源不存在'
        owner_id = _normalize_owner_value(info.get('created_by_id'))
        if owner_id is not None and _normalize_owner_value(user_id) != owner_id:
            return False, '您只能操作自己的资源'

    status_rule = STATUS_RULES.get(role, {}).get(resource_type, {}).get(action)
    if status_rule == 'respect_lock' and resource_id is not None:
        info = get_resource_info(resource_type, resource_id)
        if info and info.get('is_locked'):
            return False, '资源已锁定，无法执行此操作'

    return True, None


def require_permission(resource_type, action, resource_id_param=None):
    """装饰器：统一权限检查"""
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            resource_id = None
            if resource_id_param:
                resource_id = kwargs.get(resource_id_param)
                if resource_id is None and request.view_args:
                    resource_id = request.view_args.get(resource_id_param)

            has_permission, error_msg = check_permission(resource_type, resource_id, action)
            if not has_permission:
                if request.path.startswith('/tracking/api') or request.is_json:
                    return jsonify({'success': False, 'error': error_msg, 'code': 'FORBIDDEN'}), 403
                return redirect(url_for('tracking_bp.index'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def get_filtered_resources(resource_type, role, user_id):
    """
    返回基于所有权规则的过滤条件
    """
    role = _normalize_role(role)
    ownership_rule = OWNERSHIP_RULES.get(role, {}).get(resource_type, 'owner_only')
    if ownership_rule == 'all':
        return {'rule': 'all', 'where_sql': '', 'params': []}

    if resource_type == 'order':
        return {'rule': 'owner_only', 'where_sql': 'o.created_by_id = ?', 'params': [user_id]}
    if resource_type == 'workflow':
        return {'rule': 'owner_only', 'where_sql': 'w.handler_id = ?', 'params': [user_id]}
    if resource_type == 'order_file':
        return {'rule': 'owner_only', 'where_sql': 'o.created_by_id = ?', 'params': [user_id]}
    if resource_type == 'workflow_file':
        return {'rule': 'owner_only', 'where_sql': 'w.handler_id = ?', 'params': [user_id]}

    return {'rule': ownership_rule, 'where_sql': '', 'params': []}

