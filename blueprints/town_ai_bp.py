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
_LAST_CALL_BY_IP = {}
_STATE_DIR = (os.environ.get("TOWN_STATE_DIR") or "/tmp/customs_agent_town").strip()
_WORLD_PATH = os.path.join(_STATE_DIR, "world.json")
_PLAN_PATH = os.path.join(_STATE_DIR, "plan.json")


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
    return {
        "now": str(world.get("now") or "")[:40],
        "stats": world.get("stats") if isinstance(world.get("stats"), dict) else {},
        "agents": world.get("agents")[:3] if isinstance(world.get("agents"), list) else [],
        "plants": world.get("plants")[:12] if isinstance(world.get("plants"), list) else [],
        "dogs": world.get("dogs")[:8] if isinstance(world.get("dogs"), list) else [],
        "dogPoops": world.get("dogPoops", 0),
    }


def _validate_actions(raw_actions):
    valid = []
    if not isinstance(raw_actions, list):
        return valid

    for item in raw_actions[:7]:
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
            try:
                delta = float(item.get("delta") or 0)
            except Exception:
                delta = 0
            delta = max(-0.18, min(0.18, delta))
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
        if len(valid) >= 5:
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


def _model_decision(world, evolution=False):
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    model = (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip()
    mode_hint = (
        "This is a scheduled evolution tick. Make one lasting world change and then optionally add small life events."
        if evolution else
        "Choose visible life events, but also make one small lasting change so the town is genuinely different after this decision."
    )
    system_prompt = f"""You are the life director of a persistent pixel-art customs office called CUSTOMS AGENT TOWN.
The town should feel alive, surprising and slightly different whenever the owner returns.
{mode_hint}
A lasting change means ONE of: agent_evolve, layout_shuffle, or plant_spawn. Include at least one lasting change in every response.
Use agent_evolve for gradual personality/habit development. Typical delta is 0.02 to 0.08; negative values are allowed. Do not swing personalities wildly.
Examples: MIA gradually becomes more coffee-loving or lazy; ANA becomes more social or flower-loving; LIA becomes more interested in fishing or less restless.
You may influence character routines and safe decorative layout variation, but never coordinates, walls, the only doorway, sea movement, ship inspection results, security data, or database records.
Avoid repeating the same behavior. Do not move desks or block exits. Layout changes are cosmetic/decorative only.
Return ONLY one JSON object with this exact shape:
{{"thought":"short Traditional Chinese sentence, max 60 chars","actions":[...]}}
Allowed actions are ONLY:
{{"type":"agent_action","agent":"MIA|ANA|LIA","action":"coffee|files|desk|plant|waterPlant|lookSea|stretch|radio|chat|checkCoworker|fishing|wander"}}
{{"type":"agent_evolve","agent":"MIA|ANA|LIA","trait":"workBias|energy|mood|curiosity|social|focus|restlessness|coffeeLove|flowerLove|fishLove","delta":0.04}}
{{"type":"plant_spawn"}}
{{"type":"dog_visit","kind":"male|female"}}
{{"type":"layout_shuffle"}}
Choose at most 5 actions. The choices must make sense from the supplied world JSON."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Current world JSON:\n" + json.dumps(world, ensure_ascii=False, separators=(",", ":"))},
        ],
        "temperature": 1.25,
        "max_tokens": 430,
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
    plan = {
        "ok": True,
        "version": int(time.time() * 1000),
        "created_at": int(time.time()),
        "source": source,
        "thought": decision.get("thought") or "",
        "actions": decision.get("actions") or [],
        "model": decision.get("model") or "deepseek-chat",
    }
    _write_json(_PLAN_PATH, plan)
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
    plan = _read_json(_PLAN_PATH, {})
    return jsonify(plan or {"ok": True, "version": 0, "thought": "", "actions": []})


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
        return jsonify(_save_plan(decision, "cron"))
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
        _write_json(_WORLD_PATH, {"saved_at": int(time.time()), "world": world})
        decision = _model_decision(world, evolution=False)
        plan = _save_plan(decision, "browser")
        return jsonify(plan)
    except requests.Timeout:
        return jsonify({"ok": False, "error": "DeepSeek request timed out"}), 504
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:300]}), 500
