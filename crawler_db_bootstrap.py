"""Idempotent independent-TiDB schema setup for the XINGWANG crawler.

Runs ONLY in the crawler service process. Never reads or copies ORDER rows.
Database connection comes from crawler_app, which routes exclusively through
CRAWLER_TIDB_URL and disables TIDB mirror/failover.
"""
from __future__ import annotations

import threading

CORE_TABLES = (
    "users", "services", "user_services", "service_versions", "user_sessions",
    "verification_codes", "user_monitor_configs", "async_tasks",
    "container_access_admin", "container_access_tokens",
    "container_access_sessions", "container_items", "container_iti_cache",
)
AUTOMATION_TABLES = ("automation_telegram_bots",)
ADUANA_TABLES = (
    "aduana_users", "aduana_monitors", "aduana_scan_targets",
    "aduana_records", "aduana_notifications", "aduana_runs",
)
EXCEL_TABLES = ("monitor_excel_container_days",)
REQUIRED_TABLES = CORE_TABLES + AUTOMATION_TABLES + ADUANA_TABLES + EXCEL_TABLES

_LOCK = threading.Lock()


def probe_schema():
    """Non-destructive diagnostic. No full table scans or secrets."""
    from database import get_db_connection, get_cursor, get_table_names
    conn = get_db_connection()
    try:
        cur = get_cursor(conn)
        cur.execute("SELECT DATABASE() AS db_name")
        row = cur.fetchone()
        db_name = (row.get("db_name") if isinstance(row, dict) else row[0]) if row else None
        table_names = set(get_table_names(cur))
        missing = [name for name in REQUIRED_TABLES if name not in table_names]
        return {
            "connected": True,
            "db_name": db_name,
            "expected": len(REQUIRED_TABLES),
            "found": len(REQUIRED_TABLES) - len(missing),
            "missing": missing,
            "complete": not missing,
        }
    finally:
        conn.close()


def initialize_schema():
    """Initialize exactly the original 0004 crawler-related schemas, safely.

    Creating tables does not restore Telegram Bot records, historical data,
    subscriptions or user permissions from the original TiDB.
    """
    from database import get_db_connection, get_cursor, init_database
    from blueprints.automation_hub import storage as automation_storage
    from blueprints.aduana_monitor import storage as aduana_storage
    from blueprints.container_excel_bp import CREATE_TABLE

    with _LOCK:
        init_database()  # original users/monitor/containers/admin schema and columns
        automation_storage.ensure_schema()
        aduana_storage.ensure_schema(force=True)
        conn = get_db_connection()
        try:
            cur = get_cursor(conn)
            cur.execute(CREATE_TABLE)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        result = probe_schema()
        if not result["complete"]:
            raise RuntimeError(
                "Crawler database missing required tables: "
                + ", ".join(result["missing"])
            )
        return result
