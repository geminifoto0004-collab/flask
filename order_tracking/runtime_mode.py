"""Runtime switches for the single-codebase ORDER deployment."""
from __future__ import annotations

import os
import time

from flask import current_app, has_app_context

_READY_CACHE = {'value': False, 'checked_at': 0.0}


def _env_bool(name: str, default=False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {'1', 'true', 'yes', 'on', 'y'}


def _render_detected() -> bool:
    return bool(os.environ.get('RENDER') or os.environ.get('RENDER_SERVICE_NAME'))


def _mirror_ready() -> bool:
    """Cheap cached readiness probe so first deploy can keep the legacy reader.

    Before the first complete mirror exists, Render continues using the existing
    provider/cloud_* path. As soon as users + orders exist in the isolated ORDER
    TiDB database, the same process automatically switches to the unified LAN SQL
    path without another configuration change.
    """
    now = time.monotonic()
    if now - float(_READY_CACHE.get('checked_at') or 0.0) < 10.0:
        return bool(_READY_CACHE.get('value'))
    ready = False
    try:
        from services.order_tidb_connection import get_order_tidb_connection
        conn = get_order_tidb_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT COUNT(*) AS cnt FROM information_schema.tables
                   WHERE table_schema=DATABASE() AND table_name IN ('users','orders')"""
            )
            row = cur.fetchone() or {}
            ready = int(row.get('cnt') or 0) == 2
        finally:
            conn.close()
    except Exception:
        ready = False
    _READY_CACHE['value'] = ready
    _READY_CACHE['checked_at'] = now
    return ready


def unified_remote_db_enabled() -> bool:
    """True when the same LAN ORDER code should read the TiDB mirror."""
    explicit = os.environ.get('TRACKING_UNIFIED_REMOTE_DB')
    if explicit is not None and not _env_bool('TRACKING_UNIFIED_REMOTE_DB', False):
        return False

    requested = _env_bool('TRACKING_UNIFIED_REMOTE_DB', _render_detected())
    if has_app_context():
        requested = bool(current_app.config.get('TRACKING_UNIFIED_REMOTE_DB', requested))
    if not requested:
        return False
    return _mirror_ready()
