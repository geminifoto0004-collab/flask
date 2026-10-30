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
HOLIDAY_TABLES = ("holiday_effects",)
REQUIRED_TABLES = CORE_TABLES + AUTOMATION_TABLES + ADUANA_TABLES + EXCEL_TABLES + HOLIDAY_TABLES

# Check a representative set of columns required by the original pages.
# Do not scan any customer/monitor records to diagnose the schema.
EXPECTED_COLUMNS = {
    "users": ("id", "username", "email", "password_hash", "role", "company_name"),
    "services": ("id", "name", "version", "config_json"),
    "user_services": ("id", "user_id", "service_id", "status", "config_json"),
    "user_sessions": ("id", "user_id", "session_token", "device_info"),
    "user_monitor_configs": (
        "id", "user_id", "telegram_bot_token", "telegram_chat_id",
        "telegram_mode", "last_telegram_result_hash",
    ),
    "automation_telegram_bots": (
        "id", "bot_key", "plugin_key", "token_encrypted", "webhook_secret",
        "enabled", "is_default",
    ),
    "aduana_users": ("id", "telegram_user_id", "role", "status", "permission_level"),
    "aduana_monitors": ("id", "user_id", "rut", "aduana", "enabled"),
    "aduana_runs": ("id", "started_at", "status", "targets_checked"),
    "container_items": ("id", "access_token", "save_id", "saved_at"),
    "monitor_excel_container_days": (
        "container_no", "loading_date", "free_days", "imported_at",
    ),
    "holiday_effects": (
        "id", "effect_key", "display_name", "enabled",
        "start_month", "start_day", "end_month", "end_day", "config_json",
    ),
}
_LOCK = threading.Lock()


def _safe_error_category(exc):
    """Classify TiDB errors without exposing credentials or connection URL."""
    seen = set()
    current = exc
    code = None
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        args = getattr(current, "args", ()) or ()
        if args:
            try:
                code = int(args[0])
                break
            except (ValueError, TypeError, IndexError):
                pass
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)

    msg = str(exc).lower()
    if code in {1045, 1044, 1698}:
        return "auth", "TiDB 拒絕登入（資料庫帳號或密碼不正確、權限不足）", code
    if code == 1049:
        return "database_missing", "TiDB 連線成功，但指定的資料庫不存在", code
    if code in {2002, 2003, 2005, 2006, 2013, 1159}:
        return "network", "Render 無法連到 TiDB，請檢查區域、Host、Port、端點與網路", code
    if code in {1040, 1203, 1226}:
        return "connection_limit", "TiDB 連線數額度不足或連線受限制", code
    if "quota" in msg or "resource unit" in msg or "ru limit" in msg:
        return "quota", "TiDB 已觸及資源或使用額度限制", code
    if "ssl" in msg or "tls" in msg or "certificate" in msg:
        return "tls", "TiDB SSL/TLS 連線設定有問題", code
    if "not configured" in msg or "no tidb target is configured" in msg or "not configured:" in msg:
        return "config", "程式未取得完整的獨立 TiDB 連線設定", code
    if "schema incomplete" in msg:
        return "schema", "已連接 TiDB，但部分必要表格或欄位仍未建立", code
    return "unknown", "TiDB 發生未分類錯誤；請查看 Render Logs 的錯誤代碼", code


def diagnose_connection():
    """Bounded TiDB SELECT 1 health check, never logs or returns passwords."""
    from database import get_db_connection_for_target, get_cursor
    from tidb_targets import target_settings
    cfg = target_settings("TIDB1")
    diagnostic = {
        "host": cfg["host"], "database": cfg["database"],
        "user_hint": ((cfg["user"][:4] + "…") if cfg["user"] else ""),
        "configured": bool(cfg["configured"]),
        "password_set": bool(cfg["password"]),
        "connected": False, "error_type": None, "error_message": None,
        "error_code": None,
    }
    if not cfg["configured"] or not cfg["password"]:
        diagnostic["error_type"] = "config"
        diagnostic["error_message"] = (
            "CRAWLER_TIDB_URL 缺少帳號、資料庫名稱或密碼；請在 Render Environment 修正"
        )
        return diagnostic
    conn = None
    try:
        # Avoid reusing stale pools when diagnosing first deployment.
        conn = get_db_connection_for_target("TIDB1", pooled=False)
        cur = get_cursor(conn)
        cur.execute("SELECT DATABASE() AS db_name")
        row = cur.fetchone()
        db = row.get("db_name") if isinstance(row, dict) else row[0]
        diagnostic["actual_database"] = db
        diagnostic["connected"] = True
    except Exception as exc:
        category, detail, code = _safe_error_category(exc)
        diagnostic["error_type"] = category
        diagnostic["error_message"] = detail
        diagnostic["error_code"] = code
    finally:
        if conn is not None:
            conn.close()
    return diagnostic


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
        missing_columns = {}
        # A single metadata query is cheaper than querying each table.
        cur.execute("""
            SELECT table_name AS tbl_name, column_name AS col_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
        """)
        column_names = {}
        for item in (cur.fetchall() or []):
            if isinstance(item, dict):
                t, c = item["tbl_name"], item["col_name"]
            else:
                t, c = item[0], item[1]
            column_names.setdefault(str(t), set()).add(str(c).lower())
        for table, columns in EXPECTED_COLUMNS.items():
            if table not in table_names:
                continue
            absent = [column for column in columns
                      if column.lower() not in column_names.get(table, set())]
            if absent:
                missing_columns[table] = absent
        return {
            "connected": True,
            "db_name": db_name,
            "expected": len(REQUIRED_TABLES),
            "found": len(REQUIRED_TABLES) - len(missing),
            "missing": missing,
            "missing_columns": missing_columns,
            "complete": not missing and not missing_columns,
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS holiday_effects (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    effect_key VARCHAR(40) NOT NULL UNIQUE,
                    display_name VARCHAR(100) NOT NULL,
                    enabled TINYINT(1) NOT NULL DEFAULT 1,
                    start_month TINYINT NOT NULL,
                    start_day TINYINT NOT NULL,
                    end_month TINYINT NOT NULL,
                    end_day TINYINT NOT NULL,
                    config_json TEXT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_holiday_enabled (enabled)
                )
            """)
            defaults = (
                ("halloween", "Halloween", 1, 10, 30, 11, 2,
                 '{"overlay":"halloween-js"}'),
                ("christmas", "Christmas", 1, 12, 1, 12, 30,
                 '{"overlay":"christmas-mode"}'),
                ("new_year", "New Year", 1, 12, 31, 1, 5,
                 '{"overlay":"fireworks"}'),
            )
            for row in defaults:
                cur.execute("""
                    INSERT IGNORE INTO holiday_effects
                    (effect_key, display_name, enabled,
                     start_month, start_day, end_month, end_day, config_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, row)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        result = probe_schema()
        if not result["complete"]:
            raise RuntimeError(
                "Crawler schema incomplete: tables="
                + ", ".join(result["missing"])
                + "; columns="
                + ", ".join(sorted(result["missing_columns"]))
            )
        return result
