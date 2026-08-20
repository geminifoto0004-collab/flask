"""Database backend switch for the single-codebase ORDER application.

LAN: exact legacy sqlite3 connection.
WAN/Render unified mode: dedicated TiDB logical database wrapped so the existing
SQLite-flavoured ORDER SQL can run unchanged as far as practical.

The older registered cloud-factory path is retained only as a rollback/legacy path.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

from flask import current_app, has_app_context

from .config import CLOUD_MODE, DATABASE_PATH
from .runtime_mode import unified_remote_db_enabled

_EXTENSION_KEY = "order_tracking_cloud_db_factory"


def cloud_mode_enabled_for_db() -> bool:
    """Whether ORDER should use a remote database instead of local tracking.db."""
    if unified_remote_db_enabled():
        return True
    if has_app_context():
        return bool(current_app.config.get("TRACKING_CLOUD_MODE", CLOUD_MODE))
    return bool(CLOUD_MODE)


def register_cloud_db_connection_factory(app: Any, factory: Callable[[], Any]) -> None:
    if not callable(factory):
        raise TypeError("ORDER cloud DB factory must be callable")
    app.extensions[_EXTENSION_KEY] = factory


def get_registered_cloud_db_factory() -> Callable[[], Any] | None:
    if not has_app_context():
        return None
    factory = current_app.extensions.get(_EXTENSION_KEY)
    return factory if callable(factory) else None


def get_tracking_db_connection():
    # IMPORTANT: local/LAN behaviour is intentionally unchanged.
    if not cloud_mode_enabled_for_db():
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    if unified_remote_db_enabled():
        # Use a dedicated TiDB logical database so ORDER's users/orders/etc. can
        # keep their original table names without colliding with the parent Flask
        # application's own TiDB tables.
        from services.order_tidb_connection import get_order_tidb_connection
        from .db_compat import TiDBSQLiteCompatConnection

        return TiDBSQLiteCompatConnection(get_order_tidb_connection())

    # Legacy provider/cloud path kept for rollback compatibility.
    factory = get_registered_cloud_db_factory()
    if factory is None:
        raise RuntimeError(
            "ORDER cloud database is not registered. "
            "Render must register a TiDB connection factory; local SQLite fallback is disabled."
        )
    conn = factory()
    if conn is None:
        raise RuntimeError("ORDER cloud database factory returned no connection")
    return conn
