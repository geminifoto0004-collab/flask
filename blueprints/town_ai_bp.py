"""DeepSeek-powered life director for CUSTOMS AGENT TOWN.

The browser can ask for immediate decisions while an external cron can advance
server-side town plans even when nobody has the page open. Browser physics and
pathfinding remain authoritative; the model emits only validated world actions.
"""

from datetime import datetime
import json
import os
import re
import time
from zoneinfo import ZoneInfo

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
_ALLOWED_PERSONAS = {"lazy", "busybody", "restless"}
_LAST_CALL_BY_IP = {}
_STATE_DIR = (os.environ.get("TOWN_STATE_DIR") or "/tmp/customs_agent_town").strip()
_WORLD_PATH = os.path.join(_STATE_DIR, "world.json")
_PLAN_PATH = os.path.join(_STATE_DIR, "plan.json")
_HISTORY_PATH = os.path.join(_STATE_DIR, "plan_history.json")
_CONTEXT_CACHE = {"at": 0.0, "data": {}}


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


def _weather_description(code):
    try:
        code = int(code)
    except Exception:
        return "unknown"
    if code == 0:
        return "clear"
    if code in {1, 2}:
        return "partly_cloudy"
    if code == 3:
        return "overcast"
    if code in {45, 48}:
        return "fog"
    if code in {51, 53, 55, 56, 57}:
        return "drizzle"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "thunderstorm"
    return "mixed"


def _iquique_context(force=False):
    now_ts = time.time()
    if not force and _CONTEXT_CACHE.get("data") and now_ts - _CONTEXT_CACHE.get("at", 0) < 600:
        return dict(_CONTEXT_CACHE["data"])

    tz = ZoneInfo("America/Santiago")
    local_now = datetime.now(tz)
    context = {
        "city": "IQUIQUE",
        "timezone": "America/Santiago",
        "local_time": local_now.isoformat(timespec="seconds"),
        "hour": local_now.hour,
        "minute": local_now.minute,
        "weather": {
            "description": "unknown",
            "temperature": None,
            "wind": None,
            "code": None,
            "is_day": 1 if 7 <= local_now.hour < 20 else 0,
        },
    }
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": -20.2141,
                "longitude": -70.1524,
                "current": "temperature_2m,weather_code,wind_speed_10m,is_day",
                "timezone": "America/Santiago",
            },
            timeout=12,
        )
        if response.ok:
            current = response.json().get("current") or {}
            code = current.get("weather_code")
            context["weather"] = {
                "description": _weather_description(code),
                "temperature": current.get("temperature_2m"),
                "wind": current.get("wind_speed_10m"),
                "code": code,
                "is_day": current.get("is_day"),
            }
    except Exception:
        pass

    _CONTEXT_CACHE["at"] = now_ts
    _CONTEXT_CACHE["data"] = context
    return dict(context)


def _clean_world(world):
    if not isinstance(world, dict):
        return {}
    try:
        decor_variant = int(world.get("decorVariant", 0)) % 4
    except Exception:
        decor_variant = 0
    return {
        "now": str(world.get("now") or "")[:40],
        "iquiqueTime": str(world.get("iquiqueTime") or "")[:40],
        "decorVariant": decor_variant,
        "stats": world.get("stats") if isinstance(world.get("stats"), dict) else {},
        "agents": world.get("agents")[:3] if isinstance(world.get("agents"), list) else [],
        "formerAgents": world.get("formerAgents")[-12:] if isinstance(world.get("formerAgents"), list) else [],
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


def _clean_traits(raw):
    raw = raw if isinstance(raw, dict) else {}
    traits = {}
    for trait in _ALLOWED_TRAITS:
        if trait in raw:
            traits[trait] = round(_bounded_number(raw.get(trait), 0.05, 1.0, 0.5), 3)
    return traits


def _validate_actions(raw_actions):
    valid = []
    if not isinstance(raw_actions, list):
        return valid

    for item in raw_actions[:10]:
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
        elif kind == "agent_life":
            agent = str(item.get("agent") or "").upper()
            event = str(item.get("event") or "")
            if agent in _ALLOWED_AGENTS and event in {"marry", "divorce"}:
                valid.append({
                    "type": "agent_life",
                    "agent": agent,
                    "event": event,
                    "partnerName": str(item.get("partnerName") or item.get("partner_name") or "")[:18],
                })
        elif kind == "replace_agent":
            agent = str(item.get("agent") or "").upper()
            new_name = str(item.get("newName") or item.get("new_name") or "").strip()[:18]
            persona = str(item.get("persona") or "busybody")
            if agent in _ALLOWED_AGENTS and new_name:
                valid.append({
                    "type": "replace_agent",
                    "agent": agent,
                    "newName": new_name,
                    "persona": persona if persona in _ALLOWED_PERSONAS else "busybody",
                    "reason": str(item.get("reason") or "離開海關辦公室")[:50],
                    "traits": _clean_traits(item.get("traits")),
                })
        elif kind == "former_visit":
            valid.append({
                "type": "former_visit",
                "formerId": str(item.get("formerId") or item.get("id") or item.get("name") or "")[:80],
            })
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
        if len(valid) >= 7:
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
    former_agents = [dict(f) for f in world.get("formerAgents", []) if isinstance(f, dict)]
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
        elif kind == "agent_life":
            for agent in agents:
                if str(agent.get("name") or "").upper() == action.get("agent"):
                    if action.get("event") == "marry":
                        agent["relationship"] = "married"
                        agent["partnerName"] = action.get("partnerName") or ""
                    elif action.get("event") == "divorce":
                        agent["relationship"] = "single"
                        agent["partnerName"] = ""
                    break
        elif kind == "replace_agent":
            for agent in agents:
                if str(agent.get("name") or "").upper() == action.get("agent"):
                    former_agents.append({
                        "id": f"former-{int(time.time() * 1000)}-{agent.get('name')}",
                        "slot": agent.get("name"),
                        "displayName": agent.get("displayName") or agent.get("name"),
                        "persona": agent.get("persona") or "",
                        "reason": action.get("reason") or "離開海關辦公室",
                        "leftAt": int(time.time() * 1000),
                    })
                    agent["displayName"] = action.get("newName")
                    agent["persona"] = action.get("persona") or "busybody"
                    agent["relationship"] = "single"
                    agent["partnerName"] = ""
                    agent["careerState"] = "active"
                    agent["generation"] = int(agent.get("generation") or 1) + 1
                    for trait, value in (action.get("traits") or {}).items():
                        if trait in _ALLOWED_TRAITS:
                            agent[trait] = value
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
    world["formerAgents"] = former_agents[-24:]
    world["furniture"] = furniture[:24]
    return _clean_world(world)


def _model_decision(world, evolution=False):
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    model = (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip()
    context = _iquique_context()
    mode_hint = (
        "This is a scheduled evolution tick. Make at least one meaningful lasting change, not merely a temporary activity."
        if evolution else
        "Direct what happens now. Prefer choices that make the world visibly and narratively evolve instead of only narrating it."
    )
    system_prompt = f"""You are the autonomous world director of a persistent pixel-art customs office in IQUIQUE, Chile, called CUSTOMS AGENT TOWN.
The owner explicitly does NOT want a preset random animation. You are responsible for the macro-story and long-term changes; the game engine only enforces physics and safety.
{mode_hint}

AUTHORITATIVE REAL-WORLD CONTEXT:
- City: IQUIQUE, Chile
- Local time and current weather are supplied in server_context. Use them. Night should feel different from daytime; weather may influence routines and plans.
- Do not invent weather that contradicts server_context.

You may:
- gradually change personalities and habits;
- let a character marry or later divorce;
- decide that a colleague retires, moves away, or leaves for a life reason, then replace that work slot with a new named colleague;
- invite a former colleague back for a visit when formerAgents contains someone;
- create, move, or remove small furniture/decor;
- grow the plant corner, trigger dog visits, and choose character activities.

Use replacement sparingly. It should feel like a life event, not a slot machine. Marriage does not automatically require leaving. A former colleague visit should only be requested when there is a former colleague. Do not repeatedly marry or replace the same person without narrative reason.
Do not touch the three core work desks, walls, the only doorway, harbor geometry, sea, ship inspection results, security data, or business database records.
Furniture coordinates are preferences; the browser will reject unsafe placements. Avoid overcrowding.

Return ONLY one JSON object:
{{"thought":"short Traditional Chinese sentence, max 80 chars","actions":[...]}}

Allowed actions:
{{"type":"agent_action","agent":"MIA|ANA|LIA","action":"coffee|files|desk|plant|waterPlant|lookSea|stretch|radio|chat|checkCoworker|fishing|wander"}}
{{"type":"agent_evolve","agent":"MIA|ANA|LIA","trait":"workBias|energy|mood|curiosity|social|focus|restlessness|coffeeLove|flowerLove|fishLove","delta":0.04}}
{{"type":"agent_life","agent":"MIA|ANA|LIA","event":"marry|divorce","partnerName":"name"}}
{{"type":"replace_agent","agent":"MIA|ANA|LIA","newName":"new colleague name","persona":"lazy|busybody|restless","reason":"retired/moved/etc","traits":{{"workBias":0.7,"social":0.6}}}}
{{"type":"former_visit","formerId":"existing formerAgents id or name"}}
{{"type":"plant_spawn"}}
{{"type":"dog_visit","kind":"male|female"}}
{{"type":"layout_shuffle"}}
{{"type":"furniture_add","furniture":"file_box|chair|plant_shelf|dog_bowl|side_table|wall_frame|floor_lamp|small_cabinet|rug|notice_board","x":500,"y":210,"w":28,"h":22,"label":"short label"}}
{{"type":"furniture_move","id":"existing furniture id","x":480,"y":220}}
{{"type":"furniture_remove","id":"existing furniture id"}}

For scheduled evolution, include at least one lasting action from agent_evolve, agent_life, replace_agent, plant_spawn, layout_shuffle, furniture_add, furniture_move, or furniture_remove. Choose at most 7 coherent actions."""

    user_payload = {
        "server_context": context,
        "world": world,
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))},
        ],
        "temperature": 1.25,
        "max_tokens": 720,
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
        "thought": str(decision.get("thought") or "AI 看了一下 IQUIQUE 小鎮，暫時沒有特別安排。")[:160],
        "actions": _validate_actions(decision.get("actions")),
        "model": model,
        "context": context,
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
        "context": decision.get("context") or _iquique_context(),
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
        "life_events": True,
        "iquique_context": True,
        "plan_history": True,
    })


@town_ai_bp.route("/context", methods=["GET", "OPTIONS"])
def context():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    data = _iquique_context(force=request.args.get("refresh") == "1")
    return jsonify({"ok": True, **data})


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
