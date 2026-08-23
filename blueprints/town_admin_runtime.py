"""Independent admin controls for CUSTOMS AGENT TOWN.

Uses TOWN_ADMIN_PASSWORD from Render. The password never enters HTML/GitHub and
all privileged actions are rechecked server-side through the Flask session.
Admin commands are intentionally small and fast: only relevant tools/world data
are sent to DeepSeek, and a client command_id makes retries idempotent.
"""

import hmac
import json
import os
import time

import requests
from flask import jsonify, request, session

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS, _recent_news, _tool_calls_to_actions

_ADMIN_SESSION_KEY = "town_admin_until"
_LOGIN_FAILURES = {}
_COMMAND_CACHE = {}


def _is_admin():
    try:
        return float(session.get(_ADMIN_SESSION_KEY) or 0) > time.time()
    except Exception:
        return False


def _require_admin():
    if not _is_admin():
        return jsonify({"ok": False, "error": "admin_required"}), 401
    return None


def _tool_name(item):
    return str((item.get("function") or {}).get("name") or "")


def _select_admin_tools(prompt):
    text = str(prompt or "").lower()
    wanted = set()
    if any(k in text for k in ("車", "车", "car", "auto", "coche", "聖誕", "圣诞", "christmas", "navidad", "章魚", "章鱼", "octopus", "pulpo", "海豹", "seal", "foca", "生成", "出現", "出现", "放一", "來一", "来一")):
        wanted.update({"world_object_spawn", "world_object_move", "world_object_remove", "sea_creature_spawn"})
    if any(k in text for k in ("探班", "探望", "拜訪", "拜访", "帶晚餐", "带晚餐", "帶咖啡", "带咖啡", "visitor", "visit", "visita", "oscar")):
        wanted.add("visitor_visit")
    if any(k in text for k in ("下班", "回來上班", "回来上班", "上班", "off duty", "go home", "shift")):
        wanted.add("agent_shift")
    if any(k in text for k in ("聊天", "對話", "对话", "說", "说", "聊一下", "hablar", "chat")):
        wanted.update({"agent_chat", "agent_say"})
    if any(k in text for k in ("家具", "椅", "桌", "櫃", "柜", "佈置", "布置", "layout", "furniture")):
        wanted.update({"furniture_add", "furniture_move", "furniture_remove", "layout_shuffle", "object_add"})
    if any(k in text for k in ("狗", "dog", "perro")):
        wanted.add("dog_visit")
    if any(k in text for k in ("植物", "花", "plant")):
        wanted.update({"plant_spawn", "agent_action"})
    if any(k in text for k in ("mIa", "ana", "lia", "MIA", "ANA", "LIA")) or not wanted:
        wanted.update({"agent_action", "agent_shift", "agent_say", "agent_chat", "visitor_visit", "world_object_spawn"})
    selected = [tool for tool in DIRECTOR_TOOLS if _tool_name(tool) in wanted]
    return selected[:10] if selected else DIRECTOR_TOOLS[:10]


def _slim_world(world):
    source = world if isinstance(world, dict) else {}
    keep = (
        "worldMap", "agents", "onDutyAgents", "nightShiftAgent", "stats",
        "worldObjects", "seaCreatures", "visitors", "characterProfiles",
        "recentDialogue", "dialoguePolicy", "furniture", "plants", "dogs",
    )
    return {key: source.get(key) for key in keep if key in source}


def _admin_model_command(prompt, world):
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    model = (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip()
    context = _base._iquique_context()
    tools = _select_admin_tools(prompt)
    system_prompt = """You are the privileged world director for CUSTOMS AGENT TOWN in Iquique, Chile.
The administrator typed one direct instruction. Fulfil that instruction ONLY through the provided tools.
Return tool calls immediately; do not narrate, explain, or invent unsupported actions.
MIA, ANA and LIA are literal agent IDs.

WORLD CREATION:
- Use world_object_spawn for visible objects and creatures without a dedicated tool.
- Prefer preset=car for a car, preset=christmas_tree for a Christmas tree, preset=octopus for an octopus, preset=seal for a seal. Presets are polished shared pixel sprites and are preferred over drawing those common objects from scratch.
- Cars belong on harbor_walkway and should normally drive_left/drive_right.
- Octopus/seal belong in sea and should swim/bob/float as appropriate.
- For uncommon objects, design safe rectangle parts yourself.

PEOPLE:
- Use visitor_visit when a named person comes to visit an officer, optionally bringing dinner/coffee/flowers/a gift. The visitor automatically leaves after staySeconds.
- Use agent_shift for on/off duty.
- At night only the named nightShiftAgent is normally on duty. Do not invent office conversations with absent officers unless the administrator explicitly changes duty state.

Never output JavaScript, SQL, shell commands, URLs, secrets, or executable code."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({
                "admin_instruction": prompt,
                "server_context": context,
                "world": _slim_world(world),
            }, ensure_ascii=False, separators=(",", ":"))},
        ],
        "tools": tools,
        "tool_choice": "required",
        "temperature": 0.45,
        "max_tokens": 900,
    }
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=(4, 12),
    )
    if not response.ok:
        raise RuntimeError(f"DeepSeek HTTP {response.status_code}: {response.text[:220]}")
    raw = response.json()
    message = ((raw.get("choices") or [{}])[0].get("message") or {})
    actions = _base._validate_actions(_tool_calls_to_actions(message))
    return {"ok": True, "actions": actions, "model": model, "context": context}


def _cache_get(command_id):
    now = time.time()
    for key, value in list(_COMMAND_CACHE.items()):
        if now - float(value.get("at") or 0) > 120:
            _COMMAND_CACHE.pop(key, None)
    item = _COMMAND_CACHE.get(command_id)
    return dict(item.get("payload") or {}) if item else None


def _cache_put(command_id, payload):
    if command_id:
        _COMMAND_CACHE[command_id] = {"at": time.time(), "payload": dict(payload)}


def install_town_admin_runtime():
    @_base.town_ai_bp.route("/admin/status", methods=["GET"])
    def town_admin_status():
        return jsonify({
            "ok": True,
            "configured": bool((os.environ.get("TOWN_ADMIN_PASSWORD") or "").strip()),
            "admin": _is_admin(),
        })

    @_base.town_ai_bp.route("/admin/login", methods=["POST"])
    def town_admin_login():
        configured = (os.environ.get("TOWN_ADMIN_PASSWORD") or "").strip()
        if not configured:
            return jsonify({"ok": False, "error": "TOWN_ADMIN_PASSWORD is not configured"}), 503
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "unknown").split(",")[0].strip()
        now = time.time()
        failures = [ts for ts in _LOGIN_FAILURES.get(ip, []) if now - ts < 300]
        if len(failures) >= 8:
            _LOGIN_FAILURES[ip] = failures
            return jsonify({"ok": False, "error": "too_many_attempts"}), 429
        body = request.get_json(silent=True) or {}
        supplied = str(body.get("password") or "")
        if not hmac.compare_digest(supplied, configured):
            failures.append(now)
            _LOGIN_FAILURES[ip] = failures
            return jsonify({"ok": False, "error": "wrong_password"}), 403
        _LOGIN_FAILURES.pop(ip, None)
        session[_ADMIN_SESSION_KEY] = now + 8 * 3600
        session.modified = True
        return jsonify({"ok": True, "admin": True, "expires_in": 8 * 3600})

    @_base.town_ai_bp.route("/admin/logout", methods=["POST"])
    def town_admin_logout():
        session.pop(_ADMIN_SESSION_KEY, None)
        session.modified = True
        return jsonify({"ok": True, "admin": False})

    @_base.town_ai_bp.route("/admin/command", methods=["POST"])
    def town_admin_command():
        denied = _require_admin()
        if denied:
            return denied
        body = request.get_json(silent=True) or {}
        prompt = str(body.get("prompt") or "").strip()[:300]
        command_id = str(body.get("command_id") or "").strip()[:80]
        if not prompt:
            return jsonify({"ok": False, "error": "empty_prompt"}), 400
        if command_id:
            cached = _cache_get(command_id)
            if cached:
                cached["duplicate"] = True
                return jsonify(cached)
        try:
            stored = _base._read_json(_base._WORLD_PATH, {})
            world = _base._clean_world(stored.get("world"))
            browser_world = body.get("world") if isinstance(body.get("world"), dict) else {}
            for key_name in ("onDutyAgents", "nightShiftAgent", "dialoguePolicy"):
                if key_name in browser_world:
                    world[key_name] = browser_world.get(key_name)
            result = _admin_model_command(prompt, world)
            actions = result.get("actions") or []
            if not actions:
                return jsonify({"ok": False, "error": "no_supported_action"}), 422
            if command_id:
                for index, action in enumerate(actions):
                    if action.get("type") in {"world_object_spawn", "visitor_visit"}:
                        action["id"] = f"{command_id}-{index}"[:80]
            decision = {
                "ok": True,
                "thought": "管理員指令已轉成可執行世界動作",
                "actions": actions,
                "model": result.get("model") or "deepseek-chat",
                "context": result.get("context") or _base._iquique_context(),
                "command_id": command_id,
            }
            plan = _base._save_plan(decision, "admin-command")
            evolved_world = _base._apply_persistent_actions(world, plan.get("actions") or [])
            _base._write_json(_base._WORLD_PATH, {"saved_at": int(time.time()), "world": evolved_world})
            payload = {**plan, "ok": True, "admin_command": True, "world": evolved_world, "command_id": command_id}
            _cache_put(command_id, payload)
            return jsonify(payload)
        except requests.Timeout:
            return jsonify({"ok": False, "error": "DeepSeek request timed out after 12 seconds"}), 504
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)[:300]}), 500

    @_base.town_ai_bp.route("/admin/think-now", methods=["POST"])
    def town_admin_think_now():
        denied = _require_admin()
        if denied:
            return denied
        try:
            stored = _base._read_json(_base._WORLD_PATH, {})
            world = _base._clean_world(stored.get("world"))
            decision = _base._model_decision(world, evolution=False)
            plan = _base._save_plan(decision, "admin-manual")
            evolved_world = _base._apply_persistent_actions(world, plan.get("actions") or [])
            _base._write_json(_base._WORLD_PATH, {"saved_at": int(time.time()), "world": evolved_world})
            return jsonify(plan)
        except requests.Timeout:
            return jsonify({"ok": False, "error": "DeepSeek request timed out"}), 504
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)[:300]}), 500
