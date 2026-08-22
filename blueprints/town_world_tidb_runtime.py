"""Persist the shared CUSTOMS AGENT TOWN world in the configured database.

The existing town runtime stores plans/history in small JSON files. This module
only redirects the authoritative world snapshot to the application database so
all Render workers/viewers see the same state and profiles survive restarts.
"""

import json
import time

from flask import jsonify

from database import execute_sql, get_db_connection
from . import town_ai_bp as _base

_ORIGINAL_READ_JSON = _base._read_json
_ORIGINAL_WRITE_JSON = _base._write_json
_SCHEMA_READY = False
_SCHEMA_RETRY_AT = 0.0


def _close(conn):
    try:
        conn.close()
    except Exception:
        pass


def _ensure_schema(force=False):
    global _SCHEMA_READY, _SCHEMA_RETRY_AT
    now = time.time()
    if _SCHEMA_READY:
        return True
    if not force and now < _SCHEMA_RETRY_AT:
        return False
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        execute_sql(cur, """
            CREATE TABLE IF NOT EXISTS town_world_state (
                state_key VARCHAR(64) PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at_ms BIGINT NOT NULL
            )
        """)
        conn.commit()
        _SCHEMA_READY = True
        return True
    except Exception:
        _SCHEMA_RETRY_AT = now + 30
        return False
    finally:
        if conn is not None:
            _close(conn)


def _db_read_world(default=None):
    if not _ensure_schema():
        return default or {}
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        execute_sql(cur, "SELECT payload_json FROM town_world_state WHERE state_key = ?", ("main",))
        row = cur.fetchone()
        if not row:
            return default or {}
        raw = row.get("payload_json") if isinstance(row, dict) else row[0]
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else (default or {})
    except Exception:
        return default or {}
    finally:
        if conn is not None:
            _close(conn)


def _db_write_world(data):
    if not _ensure_schema():
        return False
    payload = json.dumps(data if isinstance(data, dict) else {}, ensure_ascii=False, separators=(",", ":"))
    now_ms = int(time.time() * 1000)
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        execute_sql(cur, "SELECT state_key FROM town_world_state WHERE state_key = ?", ("main",))
        if cur.fetchone():
            execute_sql(cur, "UPDATE town_world_state SET payload_json = ?, updated_at_ms = ? WHERE state_key = ?", (payload, now_ms, "main"))
        else:
            execute_sql(cur, "INSERT INTO town_world_state (state_key, payload_json, updated_at_ms) VALUES (?, ?, ?)", ("main", payload, now_ms))
        conn.commit()
        return True
    except Exception:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        return False
    finally:
        if conn is not None:
            _close(conn)


def _world_profiles(payload):
    world = payload.get("world") if isinstance(payload, dict) and isinstance(payload.get("world"), dict) else {}
    profiles = world.get("characterProfiles") if isinstance(world.get("characterProfiles"), list) else []
    result = []
    for item in profiles[:3]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").upper()
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        if name:
            result.append({"name": name, "profile": profile})
    return result


def install_tidb_world_runtime():
    _ensure_schema()

    def read_json(path, default=None):
        if path == _base._WORLD_PATH:
            data = _db_read_world(default)
            if data:
                return data
        return _ORIGINAL_READ_JSON(path, default)

    def write_json(path, data):
        if path == _base._WORLD_PATH and _db_write_world(data):
            return
        return _ORIGINAL_WRITE_JSON(path, data)

    _base._read_json = read_json
    _base._write_json = write_json

    @_base.town_ai_bp.route("/storage-status", methods=["GET"])
    def town_storage_status():
        stored = _db_read_world({})
        profiles = _world_profiles(stored)
        saved_at = int(stored.get("saved_at") or 0) if isinstance(stored, dict) else 0
        return jsonify({
            "ok": True,
            "world_storage": "database" if bool(stored) else "database_empty_or_unavailable",
            "world_saved_at": saved_at,
            "profiles": profiles,
            "profile_count": len(profiles),
        })
