"""Authoritative geometry/zones for CUSTOMS AGENT TOWN.

The AI sees semantic zones instead of raw pixel collision code. The same map is
stored in the configured database (TiDB on Render) and injected into every
cleaned world snapshot. Browser physics remains the final safety boundary.
"""

import json
import time

from flask import jsonify

from database import execute_sql, get_db_connection
from . import town_ai_bp as _base

_MAP_KEY = "iquique-customs-v1"
_MAP_VERSION = 1
_SCHEMA_READY = False
_SCHEMA_RETRY_AT = 0.0

CANONICAL_WORLD_MAP = {
    "key": _MAP_KEY,
    "version": _MAP_VERSION,
    "canvas": {"width": 640, "height": 400},
    "rules": {
        "agent_water_forbidden": True,
        "dog_water_forbidden": True,
        "office_exit": "office_door",
        "sea_creatures_only_in": "seal_spawn",
        "ships_only_in": "ship_lane",
        "furniture_only_in": "office",
    },
    "zones": [
        {"id": "office", "type": "walkable", "x": 42, "y": 64, "w": 556, "h": 198, "allows": ["agent", "dog", "plant", "furniture"]},
        {"id": "south_wall_left", "type": "wall", "x": 34, "y": 262, "w": 220, "h": 12, "blocks": ["agent", "dog", "furniture"]},
        {"id": "south_wall_right", "type": "wall", "x": 386, "y": 262, "w": 220, "h": 12, "blocks": ["agent", "dog", "furniture"]},
        {"id": "office_door", "type": "door", "x": 254, "y": 262, "w": 132, "h": 18, "allows": ["agent", "dog"]},
        {"id": "harbor_walkway", "type": "road", "x": 40, "y": 276, "w": 560, "h": 28, "allows": ["agent", "dog"]},
        {"id": "pier", "type": "pier", "x": 282, "y": 300, "w": 76, "h": 18, "allows": ["agent", "dog"]},
        {"id": "sea", "type": "water", "x": 12, "y": 312, "w": 616, "h": 76, "allows": ["ship", "sea_creature"]},
        {"id": "seal_spawn", "type": "spawn_zone", "parent": "sea", "x": 70, "y": 326, "w": 500, "h": 48, "allows": ["seal"]},
        {"id": "ship_lane", "type": "ship_lane", "parent": "sea", "x": 360, "y": 318, "w": 260, "h": 60, "allows": ["ship"]},
        {"id": "fishing_left", "type": "fishing_spot", "x": 286, "y": 292, "w": 1, "h": 1, "allows": ["agent"]},
        {"id": "fishing_right", "type": "fishing_spot", "x": 352, "y": 292, "w": 1, "h": 1, "allows": ["agent"]},
    ],
}


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
            CREATE TABLE IF NOT EXISTS town_world_maps (
                map_key VARCHAR(64) PRIMARY KEY,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at_ms BIGINT NOT NULL
            )
        """)
        execute_sql(cur, "SELECT version FROM town_world_maps WHERE map_key = ?", (_MAP_KEY,))
        row = cur.fetchone()
        version = None
        if row:
            version = row.get("version") if isinstance(row, dict) else row[0]
        payload = json.dumps(CANONICAL_WORLD_MAP, ensure_ascii=False, separators=(",", ":"))
        now_ms = int(now * 1000)
        if row is None:
            execute_sql(cur, "INSERT INTO town_world_maps (map_key, version, payload_json, updated_at_ms) VALUES (?, ?, ?, ?)", (_MAP_KEY, _MAP_VERSION, payload, now_ms))
        elif int(version or 0) != _MAP_VERSION:
            execute_sql(cur, "UPDATE town_world_maps SET version = ?, payload_json = ?, updated_at_ms = ? WHERE map_key = ?", (_MAP_VERSION, payload, now_ms, _MAP_KEY))
        conn.commit()
        _SCHEMA_READY = True
        return True
    except Exception:
        _SCHEMA_RETRY_AT = now + 30
        return False
    finally:
        if conn is not None:
            _close(conn)


def get_world_map():
    if not _ensure_schema():
        return json.loads(json.dumps(CANONICAL_WORLD_MAP))
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        execute_sql(cur, "SELECT payload_json FROM town_world_maps WHERE map_key = ?", (_MAP_KEY,))
        row = cur.fetchone()
        raw = (row.get("payload_json") if isinstance(row, dict) else row[0]) if row else ""
        data = json.loads(raw or "{}")
        if isinstance(data, dict) and isinstance(data.get("zones"), list):
            return data
    except Exception:
        pass
    finally:
        if conn is not None:
            _close(conn)
    return json.loads(json.dumps(CANONICAL_WORLD_MAP))


def zone_by_id(zone_id):
    zone_id = str(zone_id or "")
    return next((dict(z) for z in get_world_map().get("zones", []) if str(z.get("id")) == zone_id), None)


def install_world_map_runtime():
    _ensure_schema()
    previous_clean = _base._clean_world

    def clean_world(world):
        cleaned = previous_clean(world)
        cleaned["worldMap"] = get_world_map()
        return cleaned

    _base._clean_world = clean_world

    @_base.town_ai_bp.route("/world-map", methods=["GET"])
    def town_world_map():
        return jsonify({"ok": True, "storage": "database", "worldMap": get_world_map()})
