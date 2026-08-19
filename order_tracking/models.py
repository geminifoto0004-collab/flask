"""
订单流程追踪系统 - 数据模型
"""
import sqlite3
import os
from datetime import datetime, date
try:
    from werkzeug.security import generate_password_hash
except ImportError:
    # 如果沒有werkzeug，使用簡單的hash（僅開發環境）
    def generate_password_hash(password):
        return f"hash_{password}"

from .config import DATABASE_PATH, LIGHT_RULES
from .db_backend import get_tracking_db_connection
from .status_config import STATUS  # 向后兼容：简体中文
from .status_definitions import STATUS_KEYS, get_status_label

# 数据库默认状态值（使用 key）
DEFAULT_STATUS = STATUS_KEYS['NEW_ORDER']

def get_db():
    """获取数据库连接；本机 SQLite，Render Cloud 由 TiDB factory 提供。"""
    return get_tracking_db_connection()

def ensure_factory_visit_tables(conn=None):
    """Create/upgrade factory visit tables. Safe to run repeatedly."""
    owns_conn = conn is None
    if conn is None:
        conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS factory_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visit_date DATE,
            factory_name TEXT NOT NULL,
            main_business TEXT,
            companions TEXT,
            business_status TEXT,
            main_market TEXT,
            price_position TEXT,
            visit_note TEXT,
            analysis TEXT,
            created_by_id INTEGER,
            created_by_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by_id INTEGER,
            updated_by_name TEXT,
            updated_at TIMESTAMP,
            is_deleted INTEGER DEFAULT 0,
            deleted_by_id INTEGER,
            deleted_by_name TEXT,
            deleted_at TIMESTAMP,
            delete_reason TEXT,
            FOREIGN KEY (created_by_id) REFERENCES users(id),
            FOREIGN KEY (updated_by_id) REFERENCES users(id),
            FOREIGN KEY (deleted_by_id) REFERENCES users(id)
        )
    ''')

    cursor.execute("PRAGMA table_info(factory_visits)")
    existing = {row[1] for row in cursor.fetchall()}
    columns = {
        'visit_date': 'DATE',
        'factory_name': 'TEXT',
        'main_business': 'TEXT',
        'companions': 'TEXT',
        'business_status': 'TEXT',
        'main_market': 'TEXT',
        'price_position': 'TEXT',
        'visit_note': 'TEXT',
        'analysis': 'TEXT',
        'created_by_id': 'INTEGER',
        'created_by_name': 'TEXT',
        'created_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
        'updated_by_id': 'INTEGER',
        'updated_by_name': 'TEXT',
        'updated_at': 'TIMESTAMP',
        'is_deleted': 'INTEGER DEFAULT 0',
        'deleted_by_id': 'INTEGER',
        'deleted_by_name': 'TEXT',
        'deleted_at': 'TIMESTAMP',
        'delete_reason': 'TEXT',
    }
    for name, ddl in columns.items():
        if name not in existing:
            cursor.execute(f'ALTER TABLE factory_visits ADD COLUMN {name} {ddl}')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS factory_visit_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visit_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor_id INTEGER,
            actor_name TEXT,
            actor_role TEXT,
            before_json TEXT,
            after_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (visit_id) REFERENCES factory_visits(id),
            FOREIGN KEY (actor_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_factory_visits_deleted ON factory_visits(is_deleted)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_factory_visits_created_by ON factory_visits(created_by_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_factory_visits_visit_date ON factory_visits(visit_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_factory_visits_factory_name ON factory_visits(factory_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_factory_visit_audit_visit ON factory_visit_audit_logs(visit_id)')
    conn.commit()
    if owns_conn:
        conn.close()

def ensure_local_guest_link_tables(conn=None):
    """Create/upgrade local office guest-link tables. Safe to run repeatedly."""
    owns_conn = conn is None
    if conn is None:
        conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS local_guest_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL,
            created_at_epoch INTEGER NOT NULL,
            expires_at_epoch INTEGER NOT NULL,
            created_by_id INTEGER,
            created_by_name TEXT,
            revoked_at_epoch INTEGER,
            last_accessed_at_epoch INTEGER,
            access_count INTEGER NOT NULL DEFAULT 0,
            allow_pdf_download INTEGER NOT NULL DEFAULT 0,
            allow_report_pdf_download INTEGER NOT NULL DEFAULT 0,
            show_pdf_pages INTEGER NOT NULL DEFAULT 1,
            history_scope TEXT NOT NULL DEFAULT 'current',
            include_cancelled INTEGER NOT NULL DEFAULT 0,
            share_mode TEXT NOT NULL DEFAULT 'lan',
            is_permanent INTEGER NOT NULL DEFAULT 0,
            password_hash TEXT,
            password_kind TEXT NOT NULL DEFAULT 'none',
            share_url TEXT,
            qr_data_uri TEXT,
            last_synced_at_epoch INTEGER,
            snapshot_version TEXT
        )
    ''')

    cursor.execute("PRAGMA table_info(local_guest_links)")
    existing = {row[1] for row in cursor.fetchall()}
    columns = {
        'token_hash': 'TEXT',
        'customer_name': 'TEXT',
        'created_at_epoch': 'INTEGER',
        'expires_at_epoch': 'INTEGER',
        'created_by_id': 'INTEGER',
        'created_by_name': 'TEXT',
        'revoked_at_epoch': 'INTEGER',
        'last_accessed_at_epoch': 'INTEGER',
        'access_count': 'INTEGER NOT NULL DEFAULT 0',
        'allow_pdf_download': 'INTEGER NOT NULL DEFAULT 0',
        'allow_report_pdf_download': 'INTEGER NOT NULL DEFAULT 0',
        'show_pdf_pages': 'INTEGER NOT NULL DEFAULT 1',
        'history_scope': "TEXT NOT NULL DEFAULT 'current'",
        'include_cancelled': 'INTEGER NOT NULL DEFAULT 0',
        'share_mode': "TEXT NOT NULL DEFAULT 'lan'",
        'is_permanent': 'INTEGER NOT NULL DEFAULT 0',
        'password_hash': 'TEXT',
        'password_kind': "TEXT NOT NULL DEFAULT 'none'",
        'share_url': 'TEXT',
        'qr_data_uri': 'TEXT',
        'last_synced_at_epoch': 'INTEGER',
        'snapshot_version': 'TEXT',
    }
    for name, ddl in columns.items():
        if name not in existing:
            cursor.execute(f'ALTER TABLE local_guest_links ADD COLUMN {name} {ddl}')

    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_local_guest_links_token_hash ON local_guest_links(token_hash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_local_guest_links_customer ON local_guest_links(customer_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_local_guest_links_expires ON local_guest_links(expires_at_epoch)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_local_guest_links_creator ON local_guest_links(created_by_id)')
    conn.commit()
    if owns_conn:
        conn.close()


def ensure_public_guest_share_registry(conn=None):
    """Create/upgrade the local management mirror for Render/public guest shares.

    This table stores only management metadata returned by the configured public-share
    provider. It does not contain provider credentials or customer source data. Safe to
    call repeatedly against the live production SQLite database.
    """
    owns_conn = conn is None
    if conn is None:
        conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS public_guest_share_registry (
            share_id TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            created_at_epoch INTEGER,
            expires_at_epoch INTEGER,
            created_by_id INTEGER,
            created_by_name TEXT,
            revoked_at_epoch INTEGER,
            last_accessed_at_epoch INTEGER,
            access_count INTEGER NOT NULL DEFAULT 0,
            show_pdf_pages INTEGER NOT NULL DEFAULT 1,
            allow_report_pdf_download INTEGER NOT NULL DEFAULT 0,
            history_scope TEXT NOT NULL DEFAULT 'current',
            include_cancelled INTEGER NOT NULL DEFAULT 0,
            is_permanent INTEGER NOT NULL DEFAULT 0,
            password_kind TEXT NOT NULL DEFAULT 'none',
            share_url TEXT,
            qr_data_uri TEXT,
            updated_at_epoch INTEGER
        )
    """)
    cursor.execute("PRAGMA table_info(public_guest_share_registry)")
    existing = {row[1] for row in cursor.fetchall()}
    columns = {
        'share_id': 'TEXT',
        'customer_name': 'TEXT',
        'created_at_epoch': 'INTEGER',
        'expires_at_epoch': 'INTEGER',
        'created_by_id': 'INTEGER',
        'created_by_name': 'TEXT',
        'revoked_at_epoch': 'INTEGER',
        'last_accessed_at_epoch': 'INTEGER',
        'access_count': 'INTEGER NOT NULL DEFAULT 0',
        'show_pdf_pages': 'INTEGER NOT NULL DEFAULT 1',
        'allow_report_pdf_download': 'INTEGER NOT NULL DEFAULT 0',
        'history_scope': "TEXT NOT NULL DEFAULT 'current'",
        'include_cancelled': 'INTEGER NOT NULL DEFAULT 0',
        'is_permanent': 'INTEGER NOT NULL DEFAULT 0',
        'password_kind': "TEXT NOT NULL DEFAULT 'none'",
        'share_url': 'TEXT',
        'qr_data_uri': 'TEXT',
        'updated_at_epoch': 'INTEGER',
    }
    for name, ddl in columns.items():
        if name not in existing:
            cursor.execute(f'ALTER TABLE public_guest_share_registry ADD COLUMN {name} {ddl}')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_public_guest_share_customer ON public_guest_share_registry(customer_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_public_guest_share_expires ON public_guest_share_registry(expires_at_epoch)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_public_guest_share_revoked ON public_guest_share_registry(revoked_at_epoch)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_public_guest_share_created ON public_guest_share_registry(created_at_epoch)')
    conn.commit()
    if owns_conn:
        conn.close()


def get_order_number_sort_expr(table_alias='o'):
    # Normalize order numbers with letter prefixes (e.g. KC00001) to numeric.
    return f"CAST(ltrim({table_alias}.order_number, 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz') AS INTEGER)"

def get_order_sort_clause(sort_by, sort_order):
    order_number_expr = get_order_number_sort_expr('o')
    allowed = {
        'id': 'o.id',
        'order_number': order_number_expr,
        'customer_name': 'o.customer_name COLLATE NOCASE',
        'order_date': 'o.order_date',
        'status': 'o.status',
        'created_at': 'o.created_at',
        'project_count': 'project_count'
    }
    sort_expr = allowed.get(sort_by) or allowed['created_at']
    direction = 'ASC' if sort_order == 'asc' else 'DESC'
    return sort_expr, direction

def init_db():
    """初始化数据库 - 重构后的订单号管理架构"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. 用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            display_name VARCHAR(100) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'viewer',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 2. 订单号管理表（重构后：只管理订单号生命周期）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number VARCHAR(50) UNIQUE NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'UNLOCKED',
            visibility VARCHAR(50) DEFAULT 'admin_only',
            customer_name VARCHAR(100),
            order_date DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by VARCHAR(50),
            updated_at TIMESTAMP,
            updated_by VARCHAR(50)
        )
    ''')
    
    # 3. 业务流程表（原 products 表，改名为 workflows）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_number VARCHAR(20) UNIQUE NOT NULL,
            order_number VARCHAR(50) NOT NULL,
            
            product_name VARCHAR(200),
            product_code VARCHAR(50),
            quantity VARCHAR(50),
            factory VARCHAR(100),
            production_type VARCHAR(100),
            expected_delivery_date DATE,
            
            current_status VARCHAR(50) DEFAULT 'NEW_ORDER',
            status_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status_days INTEGER DEFAULT 0,
            
            created_by_id INTEGER,
            handler_id INTEGER,
            
            folder_path VARCHAR(500),
            notes TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (order_number) REFERENCES orders(order_number) ON DELETE CASCADE,
            FOREIGN KEY (created_by_id) REFERENCES users(id),
            FOREIGN KEY (handler_id) REFERENCES users(id)
        )
    ''')
    
    # 4. 订单文件表（订单层级文件）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number VARCHAR(50) NOT NULL,
            original_filename VARCHAR(255) NOT NULL,
            stored_filename VARCHAR(255) NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            file_type VARCHAR(50),
            mime_type VARCHAR(100),
            description TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            uploaded_by VARCHAR(50),
            FOREIGN KEY (order_number) REFERENCES orders(order_number) ON DELETE CASCADE
        )
    ''')
    
    # 迁移旧数据：如果存在 file_name 字段，迁移到 original_filename 和 stored_filename
    try:
        cursor.execute("PRAGMA table_info(order_files)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # 如果存在 file_name 字段但不存在新字段，添加新字段
        if 'file_name' in columns:
            if 'original_filename' not in columns:
                cursor.execute('ALTER TABLE order_files ADD COLUMN original_filename VARCHAR(255)')
            if 'stored_filename' not in columns:
                cursor.execute('ALTER TABLE order_files ADD COLUMN stored_filename VARCHAR(255)')
            
            # 迁移数据：从 file_path 提取 stored_filename，file_name -> original_filename
            cursor.execute('SELECT id, file_name, file_path FROM order_files WHERE original_filename IS NULL OR stored_filename IS NULL')
            for row in cursor.fetchall():
                file_id = row[0]
                original_name = row[1] or ''
                old_path = row[2] or ''
                
                # 从 file_path 提取文件名
                stored_name = os.path.basename(old_path) if old_path and os.path.basename(old_path) else ''
                # file_path 只保留目录
                new_path = os.path.dirname(old_path) if old_path else ''
                
                cursor.execute('''
                    UPDATE order_files 
                    SET original_filename = COALESCE(original_filename, ?), 
                        stored_filename = COALESCE(stored_filename, ?), 
                        file_path = COALESCE(NULLIF(?, ''), file_path)
                    WHERE id = ?
                ''', (original_name, stored_name, new_path, file_id))
            
            conn.commit()
    except Exception as e:
        print(f"数据迁移警告: {e}")
        conn.rollback()
    
    # 5. 订单备注表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number VARCHAR(50) NOT NULL,
            note_type VARCHAR(50),
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by VARCHAR(50),
            FOREIGN KEY (order_number) REFERENCES orders(order_number) ON DELETE CASCADE
        )
    ''')
    
    # 6. 业务流程文件表（原 files 表）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workflow_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_number VARCHAR(20) NOT NULL,
            file_name VARCHAR(500) NOT NULL,
            file_path VARCHAR(1000) NOT NULL,
            file_size INTEGER,
            file_type VARCHAR(100),
            uploaded_by_id INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_deleted BOOLEAN DEFAULT 0,
            deleted_by_id INTEGER,
            deleted_at TIMESTAMP,
            FOREIGN KEY (workflow_number) REFERENCES workflows(workflow_number) ON DELETE CASCADE,
            FOREIGN KEY (uploaded_by_id) REFERENCES users(id),
            FOREIGN KEY (deleted_by_id) REFERENCES users(id)
        )
    ''')
    
    # 7. 业务流程状态历史表（原 product_status_history）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workflow_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_number VARCHAR(20) NOT NULL,
            order_number VARCHAR(50),
            from_status VARCHAR(50),
            to_status VARCHAR(50) NOT NULL,
            action_date DATE NOT NULL,
            operator_id INTEGER,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (operator_id) REFERENCES users(id)
        )
    ''')
    
    # 8. 业务流程交接日志表（原 product_handover_log）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workflow_handover_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_number VARCHAR(20) NOT NULL,
            order_number VARCHAR(50),
            from_handler_id INTEGER,
            to_handler_id INTEGER,
            handover_by_id INTEGER,
            handover_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason TEXT,
            FOREIGN KEY (from_handler_id) REFERENCES users(id),
            FOREIGN KEY (to_handler_id) REFERENCES users(id),
            FOREIGN KEY (handover_by_id) REFERENCES users(id)
        )
    ''')
    
    # 9. 修图需求表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_number VARCHAR(50) UNIQUE NOT NULL,
            customer_name VARCHAR(100) NOT NULL,
            request_date DATE NOT NULL,
            requirements TEXT,
            current_status VARCHAR(50) NOT NULL DEFAULT 'received',
            completed_date DATE,
            converted_to_order_id INTEGER,
            converted_to_order_number VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 10. 系统设定表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key VARCHAR(50) PRIMARY KEY,
            value TEXT NOT NULL,
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 11. 图片表（预留）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type VARCHAR(20) NOT NULL,
            item_id INTEGER NOT NULL,
            stage VARCHAR(50),
            file_path VARCHAR(255) NOT NULL,
            file_size INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 12. 操作日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type VARCHAR(50) NOT NULL,
            order_number VARCHAR(50),
            old_status VARCHAR(50),
            new_status VARCHAR(50),
            operator VARCHAR(50) NOT NULL,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 13. 操作日志表（扩展）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            operation_type VARCHAR(50) NOT NULL,
            operation_desc VARCHAR(500),
            order_number VARCHAR(50),
            workflow_number VARCHAR(20),
            target_user_id INTEGER,
            details TEXT,
            ip_address VARCHAR(50),
            user_agent VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # 14. 通知表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type VARCHAR(50) NOT NULL,
            title VARCHAR(200) NOT NULL,
            message TEXT,
            order_number VARCHAR(50),
            workflow_number VARCHAR(20),
            priority VARCHAR(20) DEFAULT 'normal',
            is_read BOOLEAN DEFAULT 0,
            read_at TIMESTAMP,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # 15. 系统设置表（键值对）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key VARCHAR(100) PRIMARY KEY,
            value TEXT NOT NULL,
            description VARCHAR(200),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 插入默认设置（如果不存在）
    cursor.execute('''
        INSERT OR IGNORE INTO system_settings (key, value, description)
        VALUES ('notification_visible_days', '30', '通知保留天数（超过后自动从数据库删除）')
    ''')
    cursor.execute('''
        UPDATE system_settings
        SET description = '通知保留天数（超过后自动从数据库删除）'
        WHERE key = 'notification_visible_days'
    ''')

    # 给 notifications 表添加新字段（兼容旧数据库）
    try:
        cursor.execute("PRAGMA table_info(notifications)")
        notif_columns = [row[1] for row in cursor.fetchall()]
        new_cols = {
            'workflow_number': "ALTER TABLE notifications ADD COLUMN workflow_number VARCHAR(20)",
            'order_number':    "ALTER TABLE notifications ADD COLUMN order_number VARCHAR(50)",
            'priority':        "ALTER TABLE notifications ADD COLUMN priority VARCHAR(20) DEFAULT 'normal'",
            'expires_at':      "ALTER TABLE notifications ADD COLUMN expires_at TIMESTAMP",
            'message':         "ALTER TABLE notifications ADD COLUMN message TEXT",
        }
        for col, sql in new_cols.items():
            if col not in notif_columns:
                cursor.execute(sql)
                print(f"  [OK] notifications 表添加字段: {col}")
    except Exception as e:
        print(f"[WARN] 更新 notifications 表结构: {e}")
    
    # 清理重复告警通知（保留每组最早的一条）
    try:
        cursor.execute('''
            DELETE FROM notifications WHERE id NOT IN (
                SELECT MIN(id) FROM notifications
                WHERE type IN ('delivery_warning', 'delivery_overdue', 'red_light')
                GROUP BY user_id, type, workflow_number, DATE(created_at)
            ) AND type IN ('delivery_warning', 'delivery_overdue', 'red_light')
        ''')
        dup_count = cursor.rowcount
        if dup_count > 0:
            print(f"  [OK] 清理了 {dup_count} 条重复告警通知")
        # 清理锁标记
        cursor.execute("DELETE FROM notifications WHERE type = '_alert_check_lock'")
    except Exception as e:
        print(f"[WARN] 清理重复通知: {e}")
    
    # 检查并重建 orders 表（如果结构不对）
    try:
        cursor.execute("PRAGMA table_info(orders)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # 检查关键列是否存在，不符合新结构则重建
        if ('status' not in columns) or ('id' not in columns):
            print("[WARN] 检测到旧的 orders 表结构，正在重建...")
            # 先删除旧表
            cursor.execute("DROP TABLE IF EXISTS orders")
            # 重新创建新表
            cursor.execute('''
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_number VARCHAR(50) UNIQUE NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'UNLOCKED',
                    visibility VARCHAR(50) DEFAULT 'admin_only',
                    customer_name VARCHAR(100),
                    order_date DATE,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by VARCHAR(50),
                    updated_at TIMESTAMP,
                    updated_by VARCHAR(50)
                )
            ''')
            print("[OK] orders 表已重建")
    except Exception as e:
        print(f"[WARN] 检查 orders 表结构时出错: {e}")
    
    # 创建索引
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_orders_id ON orders(id)",
        "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_orders_customer_name ON orders(customer_name)",
        "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)",
        "CREATE INDEX IF NOT EXISTS idx_orders_visibility ON orders(visibility)",
        "CREATE INDEX IF NOT EXISTS idx_workflows_order ON workflows(order_number)",
        "CREATE INDEX IF NOT EXISTS idx_workflows_handler ON workflows(handler_id)",
        "CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(current_status)",
        "CREATE INDEX IF NOT EXISTS idx_order_files_order ON order_files(order_number)",
        "CREATE INDEX IF NOT EXISTS idx_order_notes_order ON order_notes(order_number)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_files_workflow ON workflow_files(workflow_number)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_files_deleted ON workflow_files(is_deleted)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_status_history_workflow ON workflow_status_history(workflow_number)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_handover_log_workflow ON workflow_handover_log(workflow_number)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(is_read)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_revision_number ON revisions(revision_number)",
        "CREATE INDEX IF NOT EXISTS idx_audit_order ON audit_log(order_number)"
    ]
    
    for index_sql in indexes:
        try:
            cursor.execute(index_sql)
        except Exception as e:
            print(f"[WARN] Index failed: {index_sql}, err: {e}")
    
    # 初始化用户
    try:
        admin_hash = generate_password_hash('admin123')
        viewer_hash = generate_password_hash('viewer123')
        cursor.execute('''
            INSERT OR IGNORE INTO users (username, password_hash, display_name, role)
            VALUES ('admin', ?, '管理员', 'admin')
        ''', (admin_hash,))
        cursor.execute('''
            INSERT OR IGNORE INTO users (username, password_hash, display_name, role)
            VALUES ('viewer', ?, '查看者', 'viewer')
        ''', (viewer_hash,))
    except:
        pass
    
    # 初始化设定
    settings_data = [
        ('draft_yellow_days', '3', '图稿确认超过X天变黄色'),
        ('draft_red_days', '5', '图稿确认超过X天变红色'),
        ('sampling_yellow_days', '2', '打样确认超过X天变黄色'),
        ('sampling_red_days', '3', '打样确认超过X天变红色'),
        ('new_order_yellow_days', '5', '新订单超过X天未发图变黄色'),
        ('new_order_red_days', '7', '新订单超过X天未发图变红色'),
        ('ready_sample_yellow_days', '5', '待打样超过X天变黄色'),
        ('ready_sample_red_days', '7', '待打样超过X天变红色'),
        ('sampling_process_yellow_days', '10', '打样中超过X天变黄色'),
        ('ready_production_yellow_days', '3', '待生产超过X天变黄色'),
        ('ready_production_red_days', '5', '待生产超过X天变红色'),
        ('delivery_warning_days', '3', '距离交货少于X天提醒'),
        ('revision_yellow_days', '3', '修图超过X天变黄色'),
        ('revision_red_days', '5', '修图超过X天变红色')
    ]
    
    for key, value, desc in settings_data:
        cursor.execute('''
            INSERT OR IGNORE INTO settings (key, value, description)
            VALUES (?, ?, ?)
        ''', (key, value, desc))
    
    # ===== 清理冗餘表（在最後執行）=====
    print("\nCleanup legacy tables...")

    for legacy_table in ['order_number_pool', 'products', 'files', 'product_status_history', 'product_handover_log']:
        try:
            cursor.execute(f"DROP TABLE IF EXISTS {legacy_table}")
            print(f"  [OK] Dropped {legacy_table}")
        except Exception as e:
            print(f"  [WARN] Drop {legacy_table} failed: {e}")

    print("Cleanup done!\n")
    ensure_factory_visit_tables(conn)
    ensure_local_guest_link_tables(conn)
    # ===== 清理结束 =====
    
    conn.commit()
    conn.close()
    
    print("=" * 50)
    print("[OK] 数据库初始化完成（重构后架构）")
    print("=" * 50)

def calculate_status_light(order):
    """
    计算订单的灯号
    支持新格式（key）和旧格式（中文）的状态值
    """
    today = date.today()
    current_status = order['current_status']
    last_change = order['last_status_change_date']
    
    if not last_change:
        return 'green'
    
    if isinstance(last_change, str):
        # 处理可能包含时间的日期字符串（如 '2026-01-25  23:11:15'）
        # 只取日期部分（空格前的部分）
        date_str = last_change.strip().split()[0] if last_change.strip() else last_change
        last_change = datetime.strptime(date_str, '%Y-%m-%d').date()
    
    days = (today - last_change).days
    
    # 正規化狀態：如果是中文，轉換成 key；如果已經是 key，直接使用
    status_key = current_status
    if current_status not in STATUS_KEYS.values():
        # 可能是舊的中文狀態，嘗試找到對應的 key
        for key, label_zh_cn in STATUS.items():
            if label_zh_cn == current_status:
                status_key = key
                break
        # 如果找不到，可能是未知狀態，返回綠燈
        if status_key not in STATUS_KEYS.values():
            return 'green'

    # 燈號不受交期影響（交期由其他功能顯示/提醒）
    
    # 根據狀態 key 和等待天數判斷
    if status_key == STATUS_KEYS['NEW_ORDER']:
        rules = LIGHT_RULES['new_order']
        if days >= rules['red_days']:
            return 'red'
        elif days >= rules['yellow_days']:
            return 'yellow'
    
    elif status_key == STATUS_KEYS['QUOTE_CONFIRMING']:
        rules = LIGHT_RULES['draft_confirm']  # 报价待确认使用图稿确认规则
        if days >= rules['red_days']:
            return 'red'
        elif days >= rules['yellow_days']:
            return 'yellow'
    
    elif status_key == STATUS_KEYS['DRAFT_MAKING']:
        # 图稿制作中：内部制作阶段，阈值沿用图稿阶段规则
        rules = LIGHT_RULES['draft_confirm']
        if days >= rules['red_days']:
            return 'red'
        elif days >= rules['yellow_days']:
            return 'yellow'
    
    elif status_key == STATUS_KEYS['DRAFT_CONFIRMING']:
        rules = LIGHT_RULES['draft_confirm']
        if days >= rules['red_days']:
            return 'red'
        elif days >= rules['yellow_days']:
            return 'yellow'
    
    elif status_key == STATUS_KEYS['DRAFT_REVISING']:
        rules = LIGHT_RULES['draft_confirm']  # 图稿修改中使用图稿确认规则
        if days >= rules['red_days']:
            return 'red'
        elif days >= rules['yellow_days']:
            return 'yellow'
    
    elif status_key == STATUS_KEYS['PENDING_SAMPLE']:
        rules = LIGHT_RULES['ready_sample']
        if days >= rules['red_days']:
            return 'red'
        elif days >= rules['yellow_days']:
            return 'yellow'
    
    elif status_key == STATUS_KEYS['SAMPLING']:
        rules = LIGHT_RULES['sampling_process']
        if rules['red_days'] and days >= rules['red_days']:
            return 'red'
        elif days >= rules['yellow_days']:
            return 'yellow'
    
    elif status_key == STATUS_KEYS['SAMPLE_CONFIRMING']:
        rules = LIGHT_RULES['sampling_confirm']
        if days >= rules['red_days']:
            return 'red'
        elif days >= rules['yellow_days']:
            return 'yellow'
    
    elif status_key == STATUS_KEYS['SAMPLE_REVISING']:
        rules = LIGHT_RULES['sampling_confirm']  # 打样修改中使用打样确认规则
        if days >= rules['red_days']:
            return 'red'
        elif days >= rules['yellow_days']:
            return 'yellow'
    
    elif status_key == STATUS_KEYS['PENDING_PRODUCTION']:
        rules = LIGHT_RULES['ready_production']
        if days >= rules['red_days']:
            return 'red'
        elif days >= rules['yellow_days']:
            return 'yellow'
    
    elif status_key == STATUS_KEYS['PRODUCING']:
        # 生產中：以交貨期判斷燈號
        # 有交期且未超期 → 綠燈
        # 有交期且已超期 → 紅燈
        # 沒有交期       → 黃燈（提醒資料不完整）
        delivery_date = order.get('expected_delivery_date')
        if delivery_date:
            if isinstance(delivery_date, str):
                try:
                    delivery_date = datetime.strptime(delivery_date.strip().split()[0], '%Y-%m-%d').date()
                except (ValueError, AttributeError):
                    delivery_date = None
            if delivery_date:
                if today > delivery_date:
                    return 'red'
                else:
                    return 'green'
        # 沒有交期 → 黃燈
        return 'yellow'

    return 'green'


def get_status_light_hint(order):
    """生成燈號說明文字（用於前端提示）"""
    today = date.today()
    current_status = order.get('current_status')
    last_change = order.get('last_status_change_date')
    if not last_change:
        return '无状态变更日期，默认绿色'

    if isinstance(last_change, str):
        date_str = last_change.strip().split()[0] if last_change.strip() else last_change
        try:
            last_change = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return '状态日期格式异常，默认绿色'

    days = max(0, (today - last_change).days)

    status_key = current_status
    if current_status not in STATUS_KEYS.values():
        for key, label_zh_cn in STATUS.items():
            if label_zh_cn == current_status:
                status_key = key
                break

    # 交期不影響燈號提示（由其他位置顯示/提醒）

    rule_key = None
    if status_key == STATUS_KEYS['NEW_ORDER']:
        rule_key = 'new_order'
    elif status_key in [STATUS_KEYS['QUOTE_CONFIRMING'], STATUS_KEYS['DRAFT_MAKING'], STATUS_KEYS['DRAFT_CONFIRMING'], STATUS_KEYS['DRAFT_REVISING']]:
        rule_key = 'draft_confirm'
    elif status_key == STATUS_KEYS['PENDING_SAMPLE']:
        rule_key = 'ready_sample'
    elif status_key == STATUS_KEYS['SAMPLING']:
        rule_key = 'sampling_process'
    elif status_key in [STATUS_KEYS['SAMPLE_CONFIRMING'], STATUS_KEYS['SAMPLE_REVISING']]:
        rule_key = 'sampling_confirm'
    elif status_key == STATUS_KEYS['PENDING_PRODUCTION']:
        rule_key = 'ready_production'

    # 生產中：特殊處理，以交貨期判斷
    if status_key == STATUS_KEYS['PRODUCING']:
        delivery_date = order.get('expected_delivery_date')
        if delivery_date:
            if isinstance(delivery_date, str):
                try:
                    delivery_date = datetime.strptime(delivery_date.strip().split()[0], '%Y-%m-%d').date()
                except (ValueError, AttributeError):
                    delivery_date = None
            if delivery_date:
                diff = (delivery_date - today).days
                if diff < 0:
                    return f'生產中，交貨期已逾期 {abs(diff)} 天（{delivery_date}）'
                else:
                    return f'生產中，距交貨期還有 {diff} 天（{delivery_date}）'
        return '生產中，尚未填寫交貨期'

    status_label = get_status_label(status_key, 'zh_cn') if status_key in STATUS_KEYS.values() else (current_status or '未知状态')
    if not rule_key or rule_key not in LIGHT_RULES:
        return f'{status_label} 已停留 {days} 天'

    rules = LIGHT_RULES[rule_key]
    yellow = rules.get('yellow_days')
    red = rules.get('red_days')
    return f'{status_label} 已停留 {days} 天（黄≥{yellow}天 / 红≥{red}天）'



def update_status_light(order_id, conn=None):
    """更新订单灯号（修复版 - 兼容 sqlite3.Row）"""
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True
    
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    
    if order:
        light = calculate_status_light(order)
        
        # 计算天数（修复：确保不是负数）
        if order['last_status_change_date']:
            try:
                last_change = date.fromisoformat(order['last_status_change_date'])
                today = date.today()
                
                # 修复1: 如果 last_change 是未来日期，修正为今天
                if last_change > today:
                    # 修复：使用 order['order_number'] 而不是 order.get()
                    try:
                        order_num = order['order_number']
                    except (KeyError, IndexError):
                        order_num = f"ID:{order_id}"
                    
                    print(f"⚠️  警告: 订单 {order_num} 的最后变更日期是未来 ({last_change})，已修正为今天")
                    last_change = today
                    # 同时更新数据库中的日期
                    cursor.execute('''
                        UPDATE orders 
                        SET last_status_change_date = ?
                        WHERE id = ?
                    ''', (today.isoformat(), order_id))
                
                days = (today - last_change).days
                
                # 修复2: 双重保护 - 确保不是负数
                days = max(0, days)
                
            except (ValueError, TypeError) as e:
                try:
                    order_num = order['order_number']
                except (KeyError, IndexError):
                    order_num = f"ID:{order_id}"
                
                print(f"❌ 错误: 订单 {order_num} 日期格式错误: {e}")
                days = 0
        else:
            days = 0
        
        cursor.execute('''
            UPDATE orders 
            SET status_light = ?, 
                status_days = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (light, days, order_id))
        conn.commit()
    
    if should_close:
        conn.close()






def generate_revision_number():
    """生成修图编号"""
    today = datetime.now().strftime('%Y%m%d')
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) as count 
        FROM revisions 
        WHERE revision_number LIKE ?
    ''', (f'REV-{today}-%',))
    
    count = cursor.fetchone()['count'] + 1
    revision_number = f'REV-{today}-{count:03d}'
    
    conn.close()
    return revision_number


# ==================== 新增：數據庫遷移工具 ====================
# 添加在 models.py 文件末尾

def migrate_database():
    """
    執行數據庫遷移
    添加新表和新欄位，不影響現有數據
    """
    conn = get_db()
    cursor = conn.cursor()
    
    print("=" * 50)
    print("開始數據庫遷移...")
    print("=" * 50)
    
    # ===== 檢查並添加 users 表的新欄位 =====
    try:
        cursor.execute("SELECT real_name FROM users LIMIT 1")
        print("[OK] users.real_name 欄位已存在")
    except:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN real_name VARCHAR(100)")
            print("[OK] 成功添加 users.real_name 欄位")
            
            # 為現有用戶設置默認值
            cursor.execute("UPDATE users SET real_name = display_name WHERE real_name IS NULL")
            conn.commit()
        except Exception as e:
            print(f"[WARN] 添加 users.real_name 失敗: {e}")
    
    # ===== 添加員工ID欄位（用於顯示，不是主鍵）=====
    try:
        cursor.execute("SELECT employee_id FROM users LIMIT 1")
        print("[OK] users.employee_id 欄位已存在")
    except:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN employee_id VARCHAR(20)")
            print("[OK] 成功添加 users.employee_id 欄位")
            
            # 為現有用戶生成員工ID（格式：EMP001, EMP002...）
            cursor.execute("SELECT id FROM users WHERE employee_id IS NULL OR employee_id = '' ORDER BY id")
            users = cursor.fetchall()
            for idx, user in enumerate(users, 1):
                employee_id = f"EMP{idx:03d}"
                cursor.execute("UPDATE users SET employee_id = ? WHERE id = ?", (employee_id, user['id']))
            conn.commit()
            print("[OK] 已為現有用戶生成員工ID")
        except Exception as e:
            print(f"[WARN] 添加 users.employee_id 失敗: {e}")
    
    # ===== 添加用戶狀態欄位 =====
    try:
        cursor.execute("SELECT status FROM users LIMIT 1")
        print("[OK] users.status 欄位已存在")
    except:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN status VARCHAR(20) DEFAULT 'active'")
            print("[OK] 成功添加 users.status 欄位")
            
            # 為現有用戶設置默認值為 active
            cursor.execute("UPDATE users SET status = 'active' WHERE status IS NULL")
            conn.commit()
        except Exception as e:
            print(f"[WARN] 添加 users.status 失敗: {e}")
    
    # ===== 添加密碼重置標記欄位 =====
    try:
        cursor.execute("SELECT needs_password_reset FROM users LIMIT 1")
        print("[OK] users.needs_password_reset 欄位已存在")
    except:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN needs_password_reset BOOLEAN DEFAULT 0")
            print("[OK] 成功添加 users.needs_password_reset 欄位")
            conn.commit()
        except Exception as e:
            print(f"[WARN] 添加 users.needs_password_reset 失敗: {e}")
    
    # ===== 添加 orders.is_locked 欄位（M0 核心）=====
    try:
        cursor.execute("SELECT is_locked FROM orders LIMIT 1")
        print("[OK] orders.is_locked 欄位已存在")
    except:
        try:
            cursor.execute("ALTER TABLE orders ADD COLUMN is_locked BOOLEAN DEFAULT 1")
            print("[OK] 成功添加 orders.is_locked 欄位")
            
            # 為現有訂單設置為已解鎖（保持向後兼容）
            cursor.execute("UPDATE orders SET is_locked = 0 WHERE is_locked IS NULL")
            conn.commit()
            print("[OK] 現有訂單已設為已解鎖狀態")
        except Exception as e:
            print(f"[WARN] 添加 orders.is_locked 失敗: {e}")

    # ===== 添加 orders.created_by_id 欄位 =====
    try:
        cursor.execute("SELECT created_by_id FROM orders LIMIT 1")
        print("[OK] orders.created_by_id 欄位已存在")
    except:
        try:
            cursor.execute("ALTER TABLE orders ADD COLUMN created_by_id INTEGER")
            print("[OK] 成功添加 orders.created_by_id 欄位")
        except Exception as e:
            print(f"[WARN] 添加 orders.created_by_id 失敗: {e}")

    # ===== 添加 orders.created_by_name 欄位 =====
    try:
        cursor.execute("SELECT created_by_name FROM orders LIMIT 1")
        print("[OK] orders.created_by_name 欄位已存在")
    except:
        try:
            cursor.execute("ALTER TABLE orders ADD COLUMN created_by_name VARCHAR(100)")
            print("[OK] 成功添加 orders.created_by_name 欄位")
        except Exception as e:
            print(f"[WARN] 添加 orders.created_by_name 失敗: {e}")
    
    # 注意：旧表已删除，不再创建以下表：
    # - order_number_pool (已删除，使用 orders 表)
    # - products (已删除，改用 workflows)
    # - files (已删除，改用 workflow_files)
    # - product_status_history (已删除，改用 workflow_status_history)
    # - product_handover_log (已删除，改用 workflow_handover_log)
    
    # ===== 創建 operation_logs 表（M5 會用到）=====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            
            operation_type VARCHAR(50) NOT NULL,
            operation_desc VARCHAR(500),
            
            order_number VARCHAR(50),
            workflow_number VARCHAR(20),
            target_user_id INTEGER,
            
            details TEXT,
            ip_address VARCHAR(50),
            user_agent VARCHAR(500),
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    print("[OK] operation_logs 表已創建")
    
    # ===== 創建 notifications 表 =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            
            type VARCHAR(50) NOT NULL,
            title VARCHAR(200) NOT NULL,
            message TEXT,
            
            order_number VARCHAR(50),
            workflow_number VARCHAR(20),
            priority VARCHAR(20) DEFAULT 'normal',
            
            is_read BOOLEAN DEFAULT 0,
            read_at TIMESTAMP,
            expires_at TIMESTAMP,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    print("[OK] notifications 表已創建")
    
    # ===== 创建索引 =====
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_orders_id ON orders(id)",
        "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_orders_customer_name ON orders(customer_name)",
        "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)",
        "CREATE INDEX IF NOT EXISTS idx_orders_visibility ON orders(visibility)",
        "CREATE INDEX IF NOT EXISTS idx_workflows_order ON workflows(order_number)",
        "CREATE INDEX IF NOT EXISTS idx_workflows_handler ON workflows(handler_id)",
        "CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(current_status)",
        "CREATE INDEX IF NOT EXISTS idx_order_files_order ON order_files(order_number)",
        "CREATE INDEX IF NOT EXISTS idx_order_notes_order ON order_notes(order_number)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_files_workflow ON workflow_files(workflow_number)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_files_deleted ON workflow_files(is_deleted)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_status_history_workflow ON workflow_status_history(workflow_number)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_handover_log_workflow ON workflow_handover_log(workflow_number)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(is_read)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at)",
    ]
    
    for index_sql in indexes:
        cursor.execute(index_sql)
    
    print("[OK] 索引已创建")
    
    conn.commit()
    conn.close()
    
    print("=" * 50)
    print("[OK] 数据库迁移完成（重构后架构）！")
    print("=" * 50)


def check_migration_status():
    """检查迁移状态"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 检查新表是否存在
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' 
        AND name IN ('workflows', 'workflow_files', 'workflow_handover_log', 'workflow_status_history', 
                     'order_files', 'order_notes', 'operation_logs', 'notifications')
    """)
    
    existing_tables = [row['name'] for row in cursor.fetchall()]
    
    print("\n检查迁移状态:")
    print("-" * 30)
    
    required_tables = ['workflows', 'workflow_files', 'workflow_handover_log', 'workflow_status_history',
                       'order_files', 'order_notes', 'operation_logs', 'notifications']
    for table in required_tables:
        if table in existing_tables:
            print(f"[OK] {table} 表存在")
        else:
            print(f"[FAIL] {table} 表不存在")
    
    # 检查旧表是否已删除
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' 
        AND name IN ('products', 'files', 'product_handover_log', 'product_status_history', 'order_number_pool')
    """)
    
    old_tables = [row['name'] for row in cursor.fetchall()]
    
    if old_tables:
        print("\n警告：以下旧表仍然存在，建议删除:")
        for table in old_tables:
            print(f"[WARN] {table} 表仍存在")
    else:
        print("\n[OK] 所有旧表已删除或不存在")
    
    conn.close()
