"""Read-only developer diagnostics for the order tracking system."""
from __future__ import annotations

import os
import platform
import sqlite3
import sys
from datetime import datetime
from importlib import metadata
from pathlib import Path

from .config import (
    DATA_DIR,
    DATABASE_PATH,
    SNAPSHOT_DIR,
    SNAPSHOT_ENABLED,
    SNAPSHOT_RETENTION_COUNT,
    SNAPSHOT_RETENTION_DAYS,
    SNAPSHOT_SCHEDULE_HOURS,
)


def _safe_file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _iso_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    except OSError:
        return ''


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def _table_row_counts(conn: sqlite3.Connection, tables: list[str]) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for table in tables:
        try:
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = int(conn.execute(f'SELECT COUNT(*) FROM {quoted}').fetchone()[0])
        except sqlite3.Error:
            counts[table] = None
    return counts


def _table_storage_bytes(conn: sqlite3.Connection) -> tuple[dict[str, int], bool]:
    """Return table+index storage grouped by owning table using SQLite dbstat."""
    try:
        object_rows = conn.execute(
            """
            SELECT name, type, COALESCE(tbl_name, name) AS tbl_name
            FROM sqlite_master
            WHERE type IN ('table', 'index')
            """
        ).fetchall()
        owner = {}
        for row in object_rows:
            name = str(row[0])
            obj_type = str(row[1])
            tbl_name = str(row[2] or name)
            owner[name] = tbl_name if obj_type == 'index' else name

        sizes: dict[str, int] = {}
        for row in conn.execute('SELECT name, SUM(pgsize) FROM dbstat GROUP BY name').fetchall():
            obj_name = str(row[0])
            size = int(row[1] or 0)
            table_name = owner.get(obj_name, obj_name)
            if table_name.startswith('sqlite_'):
                continue
            sizes[table_name] = sizes.get(table_name, 0) + size
        return sizes, True
    except sqlite3.Error:
        return {}, False


def _log_table_stats(conn: sqlite3.Connection) -> list[dict]:
    candidates = [
        ('operation_logs', 'created_at', '操作日志'),
        ('audit_log', 'created_at', '状态操作日志'),
        ('workflow_status_history', 'created_at', '流程状态历史'),
        ('workflow_handover_log', 'handover_date', '流程交接日志'),
        ('factory_visit_audit_logs', 'created_at', '工厂考察操作日志'),
        ('notifications', 'created_at', '通知记录'),
    ]
    existing = set(_table_names(conn))
    result = []
    for table, date_col, label in candidates:
        if table not in existing:
            continue
        quoted_table = '"' + table.replace('"', '""') + '"'
        quoted_col = '"' + date_col.replace('"', '""') + '"'
        try:
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN {quoted_col} >= datetime('now', '-7 days') THEN 1 ELSE 0 END) AS last_7_days,
                    SUM(CASE WHEN {quoted_col} >= datetime('now', '-30 days') THEN 1 ELSE 0 END) AS last_30_days,
                    MIN({quoted_col}) AS oldest,
                    MAX({quoted_col}) AS newest
                FROM {quoted_table}
                """
            ).fetchone()
            result.append({
                'table': table,
                'label': label,
                'total': int(row[0] or 0),
                'last_7_days': int(row[1] or 0),
                'last_30_days': int(row[2] or 0),
                'oldest': row[3] or '',
                'newest': row[4] or '',
            })
        except sqlite3.Error as exc:
            result.append({
                'table': table,
                'label': label,
                'total': None,
                'last_7_days': None,
                'last_30_days': None,
                'oldest': '',
                'newest': '',
                'error': str(exc),
            })
    return result


def _scalar(conn: sqlite3.Connection, sql: str, default=0):
    try:
        row = conn.execute(sql).fetchone()
        return row[0] if row else default
    except sqlite3.Error:
        return default


def _health_stats(conn: sqlite3.Connection) -> dict:
    try:
        quick_rows = conn.execute('PRAGMA quick_check').fetchall()
        quick_messages = [str(row[0]) for row in quick_rows]
    except sqlite3.Error as exc:
        quick_messages = [f'检查失败: {exc}']

    try:
        fk_rows = conn.execute('PRAGMA foreign_key_check').fetchall()
        fk_count = len(fk_rows)
        fk_examples = [list(row) for row in fk_rows[:10]]
    except sqlite3.Error:
        fk_count = -1
        fk_examples = []

    existing = set(_table_names(conn))
    checks = []

    if 'orders' in existing:
        duplicate_orders = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT order_number FROM orders
                WHERE order_number IS NOT NULL AND TRIM(order_number) <> ''
                GROUP BY order_number HAVING COUNT(*) > 1
            )
            """,
            0,
        )
        checks.append({'label': '重复订单号', 'value': int(duplicate_orders or 0)})

    if {'workflows', 'orders'}.issubset(existing):
        orphan_workflows = _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM workflows w
            LEFT JOIN orders o ON o.order_number = w.order_number
            WHERE o.order_number IS NULL
            """,
            0,
        )
        orders_without_workflow = _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM orders o
            LEFT JOIN workflows w ON w.order_number = o.order_number
            WHERE w.order_number IS NULL
            """,
            0,
        )
        checks.extend([
            {'label': '找不到订单的 Workflow', 'value': int(orphan_workflows or 0)},
            {'label': '没有 Workflow 的订单', 'value': int(orders_without_workflow or 0)},
        ])

    if 'workflows' in existing:
        blank_status = _scalar(
            conn,
            "SELECT COUNT(*) FROM workflows WHERE current_status IS NULL OR TRIM(current_status) = ''",
            0,
        )
        checks.append({'label': 'Workflow 状态为空', 'value': int(blank_status or 0)})

    if {'workflow_status_history', 'workflows'}.issubset(existing):
        orphan_history = _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM workflow_status_history h
            LEFT JOIN workflows w ON w.workflow_number = h.workflow_number
            WHERE w.workflow_number IS NULL
            """,
            0,
        )
        checks.append({'label': '找不到 Workflow 的历史记录', 'value': int(orphan_history or 0)})

    return {
        'quick_check_ok': quick_messages == ['ok'],
        'quick_check_messages': quick_messages[:20],
        'foreign_key_issue_count': fk_count,
        'foreign_key_examples': fk_examples,
        'checks': checks,
    }


def _snapshot_stats() -> dict:
    folder = Path(SNAPSHOT_DIR)
    files = []
    if folder.exists():
        for path in folder.glob('tracking_backup_*.db'):
            try:
                stat = path.stat()
                files.append({
                    'name': path.name,
                    'path': str(path),
                    'size_bytes': int(stat.st_size),
                    'modified_at': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    '_mtime': stat.st_mtime,
                })
            except OSError:
                continue
    files.sort(key=lambda item: item['_mtime'], reverse=True)
    for item in files:
        item.pop('_mtime', None)

    tmp_count = 0
    if folder.exists():
        try:
            tmp_count = sum(1 for p in folder.iterdir() if p.is_file() and p.name.endswith('.tmp'))
        except OSError:
            tmp_count = 0

    return {
        'enabled': bool(SNAPSHOT_ENABLED),
        'directory': str(folder),
        'count': len(files),
        'total_bytes': sum(item['size_bytes'] for item in files),
        'latest': files[0] if files else None,
        'recent': files[:10],
        'tmp_count': tmp_count,
        'retention_days': int(SNAPSHOT_RETENTION_DAYS),
        'retention_count': int(SNAPSHOT_RETENTION_COUNT),
        'schedule': ', '.join(f'{int(hour):02d}:00' for hour in SNAPSHOT_SCHEDULE_HOURS),
    }


def collect_diagnostics() -> dict:
    """Collect read-only diagnostic data. No schema or row data is modified."""
    db_path = os.path.abspath(DATABASE_PATH)
    db_file_size = _safe_file_size(db_path)
    wal_size = _safe_file_size(db_path + '-wal')
    shm_size = _safe_file_size(db_path + '-shm')

    if not os.path.isfile(db_path):
        raise FileNotFoundError(f'database not found: {db_path}')

    db_uri_path = db_path.replace('\\', '/')
    conn = sqlite3.connect(f'file:{db_uri_path}?mode=ro', uri=True, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        page_size = int(_scalar(conn, 'PRAGMA page_size', 0) or 0)
        page_count = int(_scalar(conn, 'PRAGMA page_count', 0) or 0)
        freelist_count = int(_scalar(conn, 'PRAGMA freelist_count', 0) or 0)
        journal_mode = str(_scalar(conn, 'PRAGMA journal_mode', '') or '')
        auto_vacuum = int(_scalar(conn, 'PRAGMA auto_vacuum', 0) or 0)

        tables = _table_names(conn)
        row_counts = _table_row_counts(conn, tables)
        storage_sizes, storage_exact = _table_storage_bytes(conn)

        table_stats = []
        for table in tables:
            table_stats.append({
                'name': table,
                'rows': row_counts.get(table),
                'size_bytes': storage_sizes.get(table),
            })
        table_stats.sort(
            key=lambda item: (
                item['size_bytes'] if item['size_bytes'] is not None else -1,
                item['rows'] if item['rows'] is not None else -1,
            ),
            reverse=True,
        )

        log_stats = _log_table_stats(conn)
        health = _health_stats(conn)
    finally:
        conn.close()

    free_bytes = freelist_count * page_size
    allocated_bytes = page_count * page_size
    auto_vacuum_label = {0: 'NONE', 1: 'FULL', 2: 'INCREMENTAL'}.get(auto_vacuum, str(auto_vacuum))

    try:
        flask_version = metadata.version('flask')
    except metadata.PackageNotFoundError:
        flask_version = 'Unknown'

    return {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'database': {
            'path': db_path,
            'file_size_bytes': db_file_size,
            'wal_size_bytes': wal_size,
            'shm_size_bytes': shm_size,
            'page_size': page_size,
            'page_count': page_count,
            'allocated_bytes': allocated_bytes,
            'freelist_count': freelist_count,
            'free_bytes': free_bytes,
            'used_page_bytes': max(0, allocated_bytes - free_bytes),
            'journal_mode': journal_mode.upper(),
            'auto_vacuum': auto_vacuum_label,
            'table_count': len(tables),
            'storage_exact': storage_exact,
        },
        'tables': table_stats,
        'logs': log_stats,
        'health': health,
        'snapshots': _snapshot_stats(),
        'system': {
            'data_dir': os.path.abspath(DATA_DIR),
            'python_version': platform.python_version(),
            'python_executable': sys.executable,
            'flask_version': flask_version,
            'sqlite_version': sqlite3.sqlite_version,
            'platform': platform.platform(),
        },
    }
