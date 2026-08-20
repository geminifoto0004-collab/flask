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
    """Return True only after a complete ORDER mirror was committed.

    A previous implementation switched to the unified TiDB reader as soon as the
    ``users`` and ``orders`` tables happened to exist. That is too weak during a
    failed/partial first migration: the browser can enter the LAN SQL path while
    other ORDER tables are still missing or stale, which leaves the home screen
    waiting on ``/api/orders/all-for-filter``.

    The full-mirror writer updates ``__order_mirror_state`` only after staging row
    counts pass and the table swap completes. Use that state row plus the critical
    ORDER tables as the readiness gate. Until then Render keeps the legacy reader.
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
            critical = (
                '__order_mirror_state',
                'users',
                'orders',
                'workflows',
                'workflow_status_history',
            )
            placeholders = ','.join(['%s'] * len(critical))
            cur.execute(
                f"""SELECT COUNT(*) AS cnt FROM information_schema.tables
                    WHERE table_schema=DATABASE() AND table_name IN ({placeholders})""",
                critical,
            )
            row = cur.fetchone() or {}
            if int(row.get('cnt') or 0) == len(critical):
                cur.execute(
                    """SELECT snapshot_hash, table_count, row_count, committed_at
                       FROM __order_mirror_state WHERE id=1 LIMIT 1"""
                )
                state = cur.fetchone() or {}
                snapshot_hash = str(state.get('snapshot_hash') or '').strip()
                committed_at = str(state.get('committed_at') or '').strip()
                table_count = int(state.get('table_count') or 0)
                row_count = int(state.get('row_count') or 0)
                ready = (
                    len(snapshot_hash) == 64
                    and table_count >= 4
                    and row_count >= 0
                    and bool(committed_at)
                )
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
