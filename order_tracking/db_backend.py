"""Database backend switch for shared ORDER code.

Local production remains SQLite unless cloud mode is explicitly enabled.
Render/cloud must register a TiDB-compatible connection factory. Cloud mode
never falls back to a temporary SQLite file, preventing split-brain data.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

from flask import current_app, has_app_context

from .config import CLOUD_MODE, DATABASE_PATH

_EXTENSION_KEY = "order_tracking_cloud_db_factory"


def cloud_mode_enabled_for_db() -> bool:
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
    # IMPORTANT: this branch is intentionally the exact legacy local behavior.
    if not cloud_mode_enabled_for_db():
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return conn

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
