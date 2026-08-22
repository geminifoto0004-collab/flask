"""Shared CUSTOMS AGENT TOWN dialogue history backed by the app database.

On Render the existing database layer points at TiDB. The browser posts only
validated/executed dialogue here, and every viewer reads the same recent history.
UI language preferences remain browser-local.
"""

import time
import uuid

from flask import jsonify, request

from database import execute_sql, get_db_connection
from . import town_ai_bp as _base

_AGENT_IDS = {"MIA", "ANA", "LIA"}
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
            CREATE TABLE IF NOT EXISTS town_dialogue_messages (
                message_id VARCHAR(96) PRIMARY KEY,
                conversation_id VARCHAR(96) NOT NULL,
                speaker VARCHAR(18) NOT NULL,
                listener VARCHAR(18),
                text_es TEXT NOT NULL,
                text_zh TEXT,
                created_at_ms BIGINT NOT NULL,
                turn_index INTEGER NOT NULL,
                source VARCHAR(24) NOT NULL
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


def _clean_turn(turn, members):
    if not isinstance(turn, dict):
        return None
    speaker = str(turn.get("speaker") or "").upper()
    if speaker not in _AGENT_IDS or speaker not in members:
        return None
    text_es = str(turn.get("text") or turn.get("text_es") or "").strip()[:500]
    text_zh = str(turn.get("textZh") or turn.get("text_zh") or "").strip()[:500]
    if not text_es:
        return None
    listener = next((m for m in members if m != speaker), "")
    return {"speaker": speaker, "listener": listener, "text": text_es, "text_zh": text_zh}


def _save_dialogue(payload):
    if not _ensure_schema():
        return False, "database unavailable"
    members = [str(v or "").upper() for v in (payload.get("members") or [])]
    members = [v for v in members if v in _AGENT_IDS][:2]
    if len(members) != 2 or members[0] == members[1]:
        return False, "invalid members"
    turns = []
    for turn in payload.get("turns") if isinstance(payload.get("turns"), list) else []:
        cleaned = _clean_turn(turn, members)
        if cleaned:
            turns.append(cleaned)
        if len(turns) >= 12:
            break
    if not turns:
        return False, "no valid turns"

    try:
        created_at_ms = int(payload.get("at") or payload.get("created_at_ms") or int(time.time() * 1000))
    except Exception:
        created_at_ms = int(time.time() * 1000)
    conversation_id = str(payload.get("id") or payload.get("conversation_id") or "")[:96]
    if not conversation_id:
        conversation_id = "conv-" + uuid.uuid4().hex
    source = str(payload.get("source") or "browser")[:24]

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        for index, turn in enumerate(turns):
            message_id = f"{conversation_id}:{index}"[:96]
            execute_sql(cur, "SELECT message_id FROM town_dialogue_messages WHERE message_id = ?", (message_id,))
            if cur.fetchone():
                continue
            execute_sql(cur, """
                INSERT INTO town_dialogue_messages
                (message_id, conversation_id, speaker, listener, text_es, text_zh, created_at_ms, turn_index, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_id, conversation_id, turn["speaker"], turn["listener"],
                turn["text"], turn["text_zh"], created_at_ms, index, source,
            ))
        conn.commit()
        return True, conversation_id
    except Exception as exc:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        return False, str(exc)[:160]
    finally:
        if conn is not None:
            _close(conn)


def _recent_dialogues(limit=12):
    if not _ensure_schema():
        return []
    limit = max(1, min(30, int(limit or 12)))
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Fetch a bounded message window, then group it in Python. This keeps the
        # SQL portable across TiDB/MySQL, PostgreSQL and SQLite development.
        execute_sql(cur, """
            SELECT conversation_id, speaker, listener, text_es, text_zh, created_at_ms, turn_index
            FROM town_dialogue_messages
            ORDER BY created_at_ms DESC, conversation_id DESC, turn_index DESC
            LIMIT ?
        """, (limit * 12,))
        rows = cur.fetchall() or []
        rows = list(reversed(rows))
        grouped = []
        by_id = {}
        for row in rows:
            if isinstance(row, dict):
                getter = row.get
            else:
                # Adapted database cursors normally return dict rows, but keep a
                # tuple fallback for local development.
                values = list(row)
                keys = ["conversation_id", "speaker", "listener", "text_es", "text_zh", "created_at_ms", "turn_index"]
                data = dict(zip(keys, values))
                getter = data.get
            cid = str(getter("conversation_id") or "")
            if not cid:
                continue
            item = by_id.get(cid)
            if item is None:
                item = {
                    "id": cid,
                    "at": int(getter("created_at_ms") or 0),
                    "members": [],
                    "turns": [],
                    "text": "",
                }
                by_id[cid] = item
                grouped.append(item)
            speaker = str(getter("speaker") or "").upper()
            listener = str(getter("listener") or "").upper()
            for person in (speaker, listener):
                if person in _AGENT_IDS and person not in item["members"]:
                    item["members"].append(person)
            item["turns"].append({
                "speaker": speaker,
                "text": str(getter("text_es") or ""),
                "text_zh": str(getter("text_zh") or ""),
            })
        grouped = grouped[-limit:]
        for item in grouped:
            item["turns"].sort(key=lambda turn: next((i for i, r in enumerate(rows) if str((r.get("conversation_id") if isinstance(r, dict) else r[0]) or "") == item["id"] and str((r.get("speaker") if isinstance(r, dict) else r[1]) or "") == turn["speaker"] and str((r.get("text_es") if isinstance(r, dict) else r[3]) or "") == turn["text"]), 0))
            item["text"] = " ".join(f"{t['speaker']}: {t['text']}" for t in item["turns"])[:1200]
        return grouped
    except Exception:
        return []
    finally:
        if conn is not None:
            _close(conn)


def install_tidb_dialogue_runtime():
    # Do not make app startup depend on TiDB availability. The first request will
    # create the table safely and retry later if the database is temporarily down.
    _ensure_schema()

    @_base.town_ai_bp.route("/dialogues", methods=["GET", "POST", "OPTIONS"])
    def town_dialogues():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            dialogue = body.get("dialogue") if isinstance(body, dict) else None
            dialogue = dialogue if isinstance(dialogue, dict) else body
            ok, detail = _save_dialogue(dialogue if isinstance(dialogue, dict) else {})
            if not ok:
                return jsonify({"ok": False, "error": detail}), 503
            return jsonify({"ok": True, "conversation_id": detail})
        return jsonify({"ok": True, "storage": "database", "dialogues": _recent_dialogues(request.args.get("limit", 12))})

    @_base.town_ai_bp.after_request
    def inject_shared_dialogue_history(response):
        # /world is created by an older runtime and reads the JSON snapshot.
        # Inject the database-backed dialogue history at the response boundary so
        # every browser gets the same conversations without rewriting that route.
        if request.method == "GET" and request.path.rstrip("/").endswith("/api/town/world") and response.is_json:
            try:
                data = response.get_json(silent=True)
                if isinstance(data, dict):
                    world = data.get("world") if isinstance(data.get("world"), dict) else {}
                    world["recentDialogue"] = _recent_dialogues(12)
                    data["world"] = world
                    data["dialogue_storage"] = "database"
                    response.set_data(_base.json.dumps(data, ensure_ascii=False, separators=(",", ":")))
                    response.content_type = "application/json; charset=utf-8"
            except Exception:
                pass
        return response
