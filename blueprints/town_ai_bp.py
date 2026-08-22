"""DeepSeek-powered life director for CUSTOMS AGENT TOWN.

The browser can ask for immediate decisions while an external cron can advance
server-side town plans even when nobody has the page open. Browser physics and
pathfinding remain authoritative; the model only emits whitelisted actions.
"""

import json
import os
import re
import time

import requests
from flask import Blueprint, jsonify, request


town_ai_bp = Blueprint("town_ai", __name__, url_prefix="/api/town")

_ALLOWED_AGENTS = {"MIA", "ANA", "LIA"}
_ALLOWED_AGENT_ACTIONS = {
    "coffee", "files", "desk", "plant", "waterPlant", "lookSea",
    "stretch", "radio", "chat", "checkCoworker", "fishing", "wander",
}
_ALLOWED_TRAITS = {
    "workBias", "energy", "mood", "curiosity", "social", "focus",
    "restlessness", "coffeeLove", "flowerLove", "fishLove",
}
_ALLOWED_DOG_KINDS = {"male", "female"}
_ALLOWED_FURNITURE_TYPES = {
    "file_box", "chair", "plant_shelf", "dog_bowl", "side_table",
    "wall_frame", "floor_lamp", "small_cabinet", "rug", "notice_board",
}
_LAST_CALL_BY_IP = {}
_STATE_DIR = (os.environ.get("TOWN_STATE_DIR") or "/tmp/customs_agent_town").strip()
_WORLD_PATH = os.path.join(_STATE_DIR, "world.json")
_PLAN_PATH = os.path.join(_STATE_DIR, "plan.json")
_HISTORY_PATH = os.path.join(_STATE_DIR, "plan_history.json")


def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS, GET"
    return response


@town_ai_bp.after_request
def _after_request(response):
    return _cors(response)


def _extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("DeepSeek did not return JSON")
        return json.loads(match.group(0))


def _clean_world(world):
    if not isinstance(world, dict):
        return {}
    try:
        decor_variant = int(world.get("decorVariant", 0)) % 4
    except Exception:
        decor_variant = 0
    return {
        "now": str(world.get("now") or "")[:40],
        "decorVariant": decor_variant,
        "stats": world.get("stats") if isinstance(world.get("stats"), dict) else {},
        "agents": world.get("agents")[:3] if isinstance(world.get("agents"), list) else [],
        "plants": world.get("plants")[:12] if isinstance(world.get("plants"), list) else [],
        "dogs": world.get("dogs")[:8] if isinstance(world.get("dogs"), list) else [],
        "dogPoops": world.get("dogPoops", 0),
        "furniture": world.get("furniture")[:24] if isinstance(world.get("furniture"), list) else [],
    }


def _bounded_number(value, low, high, default):
    try:
        number = float(value)
    except Exception:
        number = default
    return max(low, min(high, number))


def _validate_actions(raw_actions):
    valid = []
    if not isinstance(raw_actions, list):
        return valid

    for item in raw_actions[:8]:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "agent_action":
            agent = str(item.get("agent") or "").upper()
            action = str(item.get("action") or "")
            if agent in _ALLOWED_AGENTS and action in _ALLOWED_AGENT_ACTIONS:
                valid.append({"type": "agent_action", "agent": agent, "action": action})
        elif kind == "agent_evolve":
            agent = str(item.get("agent") or "").upper()
            trait = str(item.get("trait") or "")
            delta = _bounded_number(item.get("delta"), -0.18, 0.18, 0)
            if agent in _ALLOWED_AGENTS and trait in _ALLOWED_TRAITS and abs(delta) >= 0.01:
                valid.append({"type": "agent_evolve", "agent": agent, "trait": trait, "delta": round(delta, 3)})
        elif kind == "plant_spawn":
            valid.append({"type": "plant_spawn"})
        elif kind == "dog_visit":
            dog_kind = str(item.get("kind") or "male").lower()
            if dog_kind in _ALLOWED_DOG_KINDS:
                valid.append({"type": "dog_visit", "kind": dog_kind})
        elif kind == "layout_shuffle":
            valid.append({"type": "layout_shuffle"})
        elif kind == "furniture_add":
            furniture_type = str(item.get("furniture") or item.get("typeName") or "")
            if furniture_type in _ALLOWED_FURNITURE_TYPES:
                valid.append({
                    "type": "furniture_add",
                    "id": str(item.get("id") or "")[:80],
                    "furniture": furniture_type,
                    "x": round(_bounded_number(item.get("x"), 50, 590, 500), 1),
                    "y": round(_bounded_number(item.get("y"), 40, 250, 180), 1),
                    "w": round(_bounded_number(item.get("w"), 8, 72, 24), 1),
                    "h": round(_bounded_number(item.get("h"), 8, 60, 18), 1),
                    "label": str(item.get("label") or "")[:24],
                })
        elif kind == "furniture_move":
            furniture_id = str(item.get("id") or "")[:80]
            if furniture_id:
                valid.append({
                    "type": "furniture_move",
                    "id": furniture_id,
                    "x": round(_bounded_number(item.get("x"), 50, 590, 500), 1),
                    "y": round(_bounded_number(item.get("y"), 40, 250, 180), 1),
                })
        elif kind == "furniture_remove":
            furniture_id = str(item.get("id") or "")[:80]
            if furniture_id:
                valid.append({"type": "furniture_remove", "id": furniture_id})
        if len(valid) >= 6:
            break
    return valid


def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else (default or {})
    except Exception:
        return default or {}


def _write_json(path, data):
    os.makedirs(_STATE_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _assign_furniture_ids(actions, version):
    result = []
    for index, action in enumerate(actions or []):
        action = dict(action)
        if action.get("type") == "furniture_add" and not action.get("id"):
            action["id"] = f"ai-furn-{version}-{index}"
        result.append(action)
    return result


def _apply_persistent_actions(world, actions):
    world = _clean_world(world)
    agents = [dict(a) for a in world.get("agents", []) if isinstance(a, dict)]
    furniture = [dict(f) for f in world.get("furniture", []) if isinstance(f, dict)]

    for action in actions or []:
        kind = action.get("type")
        if kind == "agent_evolve":
            for agent in agents:
                if str(agent.get("name") or "").upper() == action.get("agent"):
                    trait = action.get("trait")
                    current = _bounded_number(agent.get(trait), 0.05, 1.0, 0.5)
                    agent[trait] = round(max(0.05, min(1.0, current + float(action.get("delta") or 0))), 3)
                    break
        elif kind == "layout_shuffle":
            world["decorVariant"] = (int(world.get("decorVariant", 0)) + 1) % 4
        elif kind == "furniture_add" and len(furniture) < 24:
            furniture_id = str(action.get("id") or "")[:80]
            if furniture_id and not any(str(f.get("id")) == furniture_id for f in furniture):
                furniture.append({
                    "id": furniture_id,
                    "type": action.get("furniture"),
                    "x": action.get("x"), "y": action.get("y"),
                    "w": action.get("w"), "h": action.get("h"),
                    "label": action.get("label") or "",
                })
        elif kind == "furniture_move":
            for furniture_item in furniture:
                if str(furniture_item.get("id")) == str(action.get("id")):
                    furniture_item["x"] = action.get("x")
                    furniture_item["y"] = action.get("y")
                    break
        elif kind == "furniture_remove":
            furniture = [f for f in furniture if str(f.get("id")) != str(action.get("id"))]

    world["agents"] = agents[:3]
    world["furniture"] = furniture[:24]
    return _clean_world(world)


def _model_decision(world, evolution=False):
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    model = (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip()
    mode_hint = (
        "This is a scheduled evolution tick. Make at least one lasting world change. Furniture creation, movement, gradual personality evolution, or plant growth are preferred over only temporary actions."
        if evolution else
        "Make something visibly happen now and, when appropriate, make one lasting change so the town slowly develops over time."
    )
    system_prompt = f"""You are the life director and interior caretaker of a persistent pixel-art customs office called CUSTOMS AGENT TOWN.
The owner wants to return later and genuinely notice that the office and its people have evolved.
{mode_hint}

You may gradually change personalities and habits, create small furniture/decor, move AI-created furniture, remove AI-created furniture, spawn plants, trigger a dog visit, or choose character activities.
Do NOT merely narrate changes: use the structured actions below.
Do not touch the three core work desks, walls, the only doorway, harbor geometry, sea, ship inspection results, security data, or database records.
Furniture coordinates are preferences only; the browser will reject or relocate unsafe placements. Avoid overcrowding. Prefer 0-2 furniture operations per decision.
When furniture already exists, sometimes move, replace, or remove something instead of endlessly adding objects.
Use labels only as short descriptive hints, for example "ANA 的花架" or "狗狗水碗".

Return ONLY one JSON object:
{{"thought":"short Traditional Chinese sentence, max 60 chars","actions":[...]}}

Allowed actions:
{{"type":"agent_action","agent":"MIA|ANA|LIA","action":"coffee|files|desk|plant|waterPlant|lookSea|stretch|radio|chat|checkCoworker|fishing|wander"}}
{{"type":"agent_evolve","agent":"MIA|ANA|LIA","trait":"workBias|energy|mood|curiosity|social|focus|restlessness|coffeeLove|flowerLove|fishLove","delta":0.04}}
{{"type":"plant_spawn"}}
{{"type":"dog_visit","kind":"male|female"}}
{{"type":"layout_shuffle"}}
{{"type":"furniture_add","furniture":"file_box|chair|plant_shelf|dog_bowl|side_table|wall_frame|floor_lamp|small_cabinet|rug|notice_board","x":500,"y":210,"w":28,"h":22,"label":"short label"}}
{{"type":"furniture_move","id":"existing furniture id","x":480,"y":220}}
{{"type":"furniture_remove","id":"existing furniture id"}}

For scheduled evolution, include at least one lasting action from agent_evolve, plant_spawn, layout_shuffle, furniture_add, furniture_move, or furniture_remove.
Choose at most 6 actions and make them coherent with the supplied world JSON, including its current furniture list."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Current world JSON:\n" + json.dumps(world, ensure_ascii=False, separators=(",", ":"))},
        ],
        "temperature": 1.3,
        "max_tokens": 560,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=35,
    )
    if not response.ok:
        raise RuntimeError(f"DeepSeek HTTP {response.status_code}: {response.text[:220]}")
    raw = response.json()
    text = (((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    decision = _extract_json(text)
    return {
        "ok": True,
        "thought": str(decision.get("thought") or "AI 看了一下小鎮，暫時沒有特別安排。")[:120],
        "actions": _validate_actions(decision.get("actions")),
        "model": model,
    }


def _save_plan(decision, source):
    version = int(time.time() * 1000)
    actions = _assign_furniture_ids(decision.get("actions") or [], version)
    plan = {
        "ok": True,
        "version": version,
        "created_at": int(time.time()),
        "source": source,
        "thought": decision.get("thought") or "",
        "actions": actions,
        "model": decision.get("model") or "deepseek-chat",
    }
    _write_json(_PLAN_PATH, plan)
    history_data = _read_json(_HISTORY_PATH, {"plans": []})
    plans = history_data.get("plans") if isinstance(history_data.get("plans"), list) else []
    plans.append(plan)
    _write_json(_HISTORY_PATH, {"plans": plans[-48:]})
    return plan


def _cron_authorized():
    expected = (os.environ.get("TOWN_CRON_TOKEN") or "").strip()
    if not expected:
        return False
    auth = (request.headers.get("Authorization") or "").strip()
    supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not supplied:
        supplied = (request.args.get("token") or "").strip()
    return supplied == expected


@town_ai_bp.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    return jsonify({
        "ok": True,
        "deepseek_configured": bool((os.environ.get("DEEPSEEK_API_KEY") or "").strip()),
        "cron_ready": bool((os.environ.get("TOWN_CRON_TOKEN") or "").strip()),
        "model": (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip(),
        "furniture_ai": True,
        "plan_history": True,
    })


@town_ai_bp.route("/state", methods=["POST", "OPTIONS"])
def save_state():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        try:
            body = json.loads(request.get_data(as_text=True) or "{}")
        except Exception:
            body = {}
    world = _clean_world(body.get("world"))
    _write_json(_WORLD_PATH, {"saved_at": int(time.time()), "world": world})
    return jsonify({"ok": True})


@town_ai_bp.route("/plan", methods=["GET", "OPTIONS"])
def get_plan():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    latest = _read_json(_PLAN_PATH, {})
    history_data = _read_json(_HISTORY_PATH, {"plans": []})
    plans = history_data.get("plans") if isinstance(history_data.get("plans"), list) else []
    result = dict(latest or {"ok": True, "version": 0, "thought": "", "actions": []})
    result["plans"] = plans[-48:]
    return jsonify(result)


@town_ai_bp.route("/evolve", methods=["GET", "POST", "OPTIONS"])
def evolve():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    if not (os.environ.get("TOWN_CRON_TOKEN") or "").strip():
        return jsonify({"ok": False, "error": "TOWN_CRON_TOKEN is not configured"}), 503
    if not _cron_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        stored = _read_json(_WORLD_PATH, {})
        world = _clean_world(stored.get("world"))
        decision = _model_decision(world, evolution=True)
        plan = _save_plan(decision, "cron")
        evolved_world = _apply_persistent_actions(world, plan.get("actions"))
        _write_json(_WORLD_PATH, {"saved_at": int(time.time()), "world": evolved_world})
        return jsonify(plan)
    except requests.Timeout:
        return jsonify({"ok": False, "error": "DeepSeek request timed out"}), 504
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:300]}), 500


@town_ai_bp.route("/think", methods=["POST", "OPTIONS"])
def think():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))

    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    now = time.time()
    previous = _LAST_CALL_BY_IP.get(ip, 0)
    if now - previous < 3:
        return jsonify({"ok": False, "error": "AI is thinking; please wait a few seconds"}), 429
    _LAST_CALL_BY_IP[ip] = now

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        try:
            body = json.loads(request.get_data(as_text=True) or "{}")
        except Exception:
            body = {}
    world = _clean_world(body.get("world"))
    try:
        decision = _model_decision(world, evolution=False)
        plan = _save_plan(decision, "browser")
        evolved_world = _apply_persistent_actions(world, plan.get("actions"))
        _write_json(_WORLD_PATH, {"saved_at": int(time.time()), "world": evolved_world})
        return jsonify(plan)
    except requests.Timeout:
        return jsonify({"ok": False, "error": "DeepSeek request timed out"}), 504
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:300]}), 500
