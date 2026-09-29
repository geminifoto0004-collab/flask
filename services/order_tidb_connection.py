"""Dedicated TiDB connection for the unified ORDER mirror with TiDB1/TiDB2 HA.

The dedicated ``order_tracking`` logical database is mirrored to both TiDB clusters.
Reads use the selected/preferred target. Every mutation issued by the full-mirror
pipeline is replayed to the other target when it is reachable. A broken standby never
blocks the selected database; the next full snapshot heals any missed writes.
"""
from __future__ import annotations

import os
import re
import threading

from tidb_targets import (
    failover_enabled,
    mirror_enabled,
    other_target,
    preferred_target,
    pymysql_kwargs,
    selected_target,
    target_candidates,
    target_configured,
)

_DB_NAME = (os.environ.get('ORDER_TIDB_DATABASE') or 'order_tracking').strip()
if not re.fullmatch(r'[A-Za-z0-9_]+', _DB_NAME):
    raise RuntimeError('ORDER_TIDB_DATABASE may contain only letters, digits and underscore')

_init_lock = threading.Lock()
_database_ready = set()
_order_mirror_dirty = threading.Event()
_order_mirror_warned = set()
_MUTATION_RE = re.compile(
    r'^\s*(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|TRUNCATE|RENAME)\b',
    re.IGNORECASE,
)


def order_mirror_dirty_event():
    return _order_mirror_dirty


def _is_mutation(sql):
    return bool(_MUTATION_RE.search(str(sql or '')))


def _idempotent_mirror_error(exc):
    code = None
    try:
        code = int((getattr(exc, 'args', None) or [None])[0])
    except Exception:
        code = None
    return code in {1050, 1060, 1061, 1068, 1091}


def _connect_target(target, database=None):
    import pymysql
    import pymysql.cursors

    kwargs = pymysql_kwargs(
        target,
        database_override=database,
        require_database=database is not None,
        connect_timeout=10,
        read_timeout=45,
        write_timeout=45,
    )
    kwargs['cursorclass'] = pymysql.cursors.DictCursor
    return pymysql.connect(**kwargs)


def ensure_order_database(target=None):
    """Create the isolated ORDER logical database once per target/process."""
    target = str(target or preferred_target()).strip().upper()
    if target not in {'TIDB1', 'TIDB2'}:
        raise ValueError('target must be TIDB1 or TIDB2')
    if target in _database_ready:
        return _DB_NAME

    with _init_lock:
        if target in _database_ready:
            return _DB_NAME
        conn = _connect_target(target, database=None)
        try:
            cur = conn.cursor()
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{_DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            conn.commit()
        finally:
            conn.close()
        _database_ready.add(target)
    return _DB_NAME


def get_order_tidb_connection_for_target(target):
    """Connect to one exact ORDER TiDB target without failover or mirroring."""
    target = str(target or '').strip().upper()
    if target not in {'TIDB1', 'TIDB2'}:
        raise ValueError('target must be TIDB1 or TIDB2')
    ensure_order_database(target)
    conn = _connect_target(target, database=_DB_NAME)
    try:
        conn.active_target = target
    except Exception:
        pass
    return conn


def _select_active_connection():
    preferred = preferred_target()
    errors = []
    allow = failover_enabled() or selected_target() == 'AUTO'
    for target in target_candidates(preferred, allow_failover=allow):
        if not target_configured(target, require_database=False):
            continue
        try:
            return get_order_tidb_connection_for_target(target), target
        except Exception as exc:
            errors.append((target, exc))
    if errors:
        target, exc = errors[-1]
        raise RuntimeError(f'No ORDER TiDB target is reachable; last target {target}: {exc}') from exc
    raise RuntimeError('No ORDER TiDB target is configured')


class _DualOrderCursor:
    def __init__(self, connection, active_cursor):
        self._connection = connection
        self._active = active_cursor

    def __getattr__(self, name):
        return getattr(self._active, name)

    def execute(self, sql, params=None):
        if params is None:
            result = self._active.execute(sql)
        else:
            result = self._active.execute(sql, params)
        if _is_mutation(sql):
            self._connection._mirror_execute(sql, params, many=False)
        return result

    def executemany(self, sql, params_list):
        if _is_mutation(sql):
            rows = params_list if isinstance(params_list, (list, tuple)) else list(params_list)
            result = self._active.executemany(sql, rows)
            self._connection._mirror_execute(sql, rows, many=True)
            return result
        return self._active.executemany(sql, params_list)


class _DualOrderConnection:
    def __init__(self, active, active_target, mirror_target):
        self._active = active
        self.active_target = str(active_target or '').upper()
        self.mirror_target = str(mirror_target or '').upper()
        self._mirror = None
        self._mirror_failed = False

    def __getattr__(self, name):
        return getattr(self._active, name)

    def cursor(self, *args, **kwargs):
        return _DualOrderCursor(self, self._active.cursor(*args, **kwargs))

    def _mark_failed(self, exc):
        self._mirror_failed = True
        _order_mirror_dirty.set()
        key = (self.active_target, self.mirror_target, type(exc).__name__, str(exc)[:160])
        if key not in _order_mirror_warned:
            _order_mirror_warned.add(key)
            print(
                f'[WARN] ORDER TiDB mirror {self.active_target}->{self.mirror_target} '
                f'temporarily skipped: {type(exc).__name__}: {exc}'
            )
        if self._mirror is not None:
            try:
                self._mirror.rollback()
            except Exception:
                pass
            try:
                self._mirror.close()
            except Exception:
                pass
            self._mirror = None

    def _get_mirror(self):
        if self._mirror_failed:
            return None
        if self._mirror is None:
            try:
                self._mirror = get_order_tidb_connection_for_target(self.mirror_target)
            except Exception as exc:
                self._mark_failed(exc)
                return None
        return self._mirror

    def _mirror_execute(self, sql, params, *, many):
        mirror = self._get_mirror()
        if mirror is None:
            return
        try:
            cur = mirror.cursor()
            if many:
                cur.executemany(sql, params)
            elif params is None:
                cur.execute(sql)
            else:
                cur.execute(sql, params)
        except Exception as exc:
            if _idempotent_mirror_error(exc):
                return
            self._mark_failed(exc)

    def commit(self):
        result = self._active.commit()
        if self._mirror is not None and not self._mirror_failed:
            try:
                self._mirror.commit()
            except Exception as exc:
                self._mark_failed(exc)
        return result

    def rollback(self):
        try:
            result = self._active.rollback()
        finally:
            if self._mirror is not None:
                try:
                    self._mirror.rollback()
                except Exception:
                    pass
        return result

    def close(self):
        try:
            self._active.close()
        finally:
            if self._mirror is not None:
                try:
                    self._mirror.close()
                except Exception:
                    pass
                self._mirror = None


def get_order_tidb_connection():
    """Return selected ORDER connection; writes are mirrored to the other TiDB."""
    active, active_target = _select_active_connection()
    mirror_target = other_target(active_target)
    if mirror_enabled() and target_configured(mirror_target, require_database=False):
        return _DualOrderConnection(active, active_target, mirror_target)
    try:
        active.active_target = active_target
    except Exception:
        pass
    return active


def order_database_name():
    return _DB_NAME
