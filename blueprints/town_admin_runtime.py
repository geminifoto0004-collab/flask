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
    # These generic verbs stay available for every admin instruction so DeepSeek
    # can compose scenes we never anticipated instead of falling back to a
    # bespoke story-specific function.
    wanted = {"spawn_entity", "move_entity", "say", "give", "wait", "leave", "remove_entity", "set_relationship"}
    if any(k in text for k in ("車", "车", "car", "auto", "coche", "聖誕", "圣诞", "christmas", "navidad", "章魚", "章鱼", "octopus", "pulpo", "海豹", "seal", "foca", "生成", "出現", "出现", "放一", "來一", "来一")):
        wanted.update({"world_object_spawn", "world_object_move", "world_object_remove", "sea_creature_spawn"})
    if any(k in text for k in ("探班", "探望", "拜訪", "拜访", "帶晚餐", "带晚餐", "帶咖啡", "带咖啡", "visitor", "visit", "visita", "oscar", "朋友", "客人", "外送", "追求", "分手", "喜歡", "喜欢", "愛上", "爱上")):
        wanted.update({"agent_say", "agent_shift", "set_relationship"})
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
    if any(k in text for k in ("mia", "ana", "lia")):
        wanted.update({"agent_action", "agent_shift", "agent_say", "agent_chat"})
    selected = [tool for tool in DIRECTOR_TOOLS if _tool_name(tool) in wanted]
    return selected[:16] if selected else DIRECTOR_TOOLS[:16]


def _slim_world(world):
    source = world if isinstance(world, dict) else {}
    keep = (
        "worldMap", "agents", "onDutyAgents", "nightShiftAgent", "stats",
        "worldObjects", "genericEntities", "seaCreatures", "visitors", "characterProfiles",
        "recentDialogue", "dialoguePolicy", "relationships", "furniture", "plants", "dogs",
    )
    return {key: source.get(key) for key in keep if key in source}


def _scene_metadata(raw_actions):
    for action in raw_actions or []:
        if not isinstance(action, dict) or str(action.get("type") or "") != "entity_scene":
            continue
        must_keep = [str(v).strip()[:90] for v in action.get("mustKeep", []) if str(v).strip()][:6] if isinstance(action.get("mustKeep"), list) else []
        creative = [str(v).strip()[:90] for v in action.get("creativeFreedom", []) if str(v).strip()][:6] if isinstance(action.get("creativeFreedom"), list) else []
        return {
            "intent_summary": str(action.get("intentSummary") or "").strip()[:140],
            "must_keep": must_keep,
            "creative_freedom": creative,
            "director_note": str(action.get("directorNote") or "").strip()[:180],
        }
    return {"intent_summary": "", "must_keep": [], "creative_freedom": [], "director_note": ""}


def _admin_model_command(prompt, world):
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    model = (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip()
    context = _base._iquique_context()
    tools = _select_admin_tools(prompt)
    system_prompt = """You are the privileged WORLD DIRECTOR for CUSTOMS AGENT TOWN in Iquique, Chile.
The administrator gives you a story seed. Fulfil it ONLY through the provided tools. Do not narrate unsupported physical events.
MIA, ANA and LIA are literal persistent officer IDs.

DIRECTOR AUTHORITY VS ADMIN AUTHORITY — CRITICAL:
- Infer which parts are HARD requirements and which parts are CREATIVE freedom from the administrator's wording.
- Strong wording such as "一定", "必須", "要", "不要改", "一定要", "must", "do not change" means preserve that story beat unless it is physically impossible or violates world safety.
- Wording such as "看AI怎麼發展", "讓AI決定", "如果太怪可以改", "要不要讓她自己決定", "自己想辦法" explicitly grants you freedom to improve pacing, dialogue, reactions and outcomes.
- Mixed instructions are allowed. Example: "Oscar 去追 ANA，但是 ANA 要不要接受讓她自己決定" means Oscar pursuing ANA is binding, ANA's response is yours to decide.
- Do not silently throw away an explicit binding beat just because you would write a different story. You may stage it more naturally.
- Other characters retain agency unless the administrator explicitly dictates their action. Attraction never forces reciprocation.

GENERAL STORY ENGINE:
- For a multi-step visitor/person/animal/vehicle story, prefer entity_scene so the whole scene arrives atomically instead of only spawning the actor.
- Inside a scene, you decide whether talking is actually useful. Do not force dialogue just because two people are near each other.
- Use officer_say only for an on-duty MIA/ANA/LIA who is physically present.
- Use relationship steps only when the story genuinely changes a relationship; relationship state is persistent world memory.
- If a named officer is absent/off duty, DO NOT magically materialize them. Read onDutyAgents/nightShiftAgent and adapt without violating explicit must-keep conditions.
- A new visitor does not automatically know every officer. Respect existing relationship memory and the story context.
- A human entering/leaving the office must use the door; vehicles/animals/items must use physically sensible zones.

WORLD OBJECTS:
- Use world_object_spawn for non-actor scenery/creatures that do not need a multi-step personal script.
- Cars belong on harbor_walkway; octopus/seal belong in sea.

OFFICERS:
- Use agent_shift only for explicit on/off duty requests.
- At night only nightShiftAgent is normally physically present.

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
        "temperature": 0.68,
        "max_tokens": 1500,
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
    raw_actions = _tool_calls_to_actions(message)
    metadata = _scene_metadata(raw_actions)
    actions = _base._validate_actions(raw_actions)
    intent = metadata.get("intent_summary") or str(prompt)[:110]
    note = metadata.get("director_note") or "保留明確指定的核心情節，其餘依目前人物、值班與關係狀態自行導演。"
    thought = f"你要的：{intent}；AI 改編：{note}"[:300]
    return {
        "ok": True,
        "actions": actions,
        "model": model,
        "context": context,
        "thought": thought,
        **metadata,
    }


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
            for key_name in ("onDutyAgents", "nightShiftAgent", "dialoguePolicy", "relationships"):
                if key_name in browser_world:
                    world[key_name] = browser_world.get(key_name)
            result = _admin_model_command(prompt, world)
            actions = result.get("actions") or []
            if not actions:
                return jsonify({"ok": False, "error": "no_supported_action"}), 422
            if command_id:
                for index, action in enumerate(actions):
                    # Generic spawn_entity IDs are chosen by the model because
                    # later tool calls in the same response must reference them.
                    if action.get("type") in {"world_object_spawn", "visitor_visit"}:
                        action["id"] = f"{command_id}-{index}"[:80]
            decision = {
                "ok": True,
                "thought": result.get("thought") or "管理員劇情已轉成可執行世界動作",
                "actions": actions,
                "model": result.get("model") or "deepseek-chat",
                "context": result.get("context") or _base._iquique_context(),
                "command_id": command_id,
                "director_intent": result.get("intent_summary") or "",
                "must_keep": result.get("must_keep") or [],
                "creative_freedom": result.get("creative_freedom") or [],
                "director_note": result.get("director_note") or "",
            }
            plan = _base._save_plan(decision, "admin-command")
            evolved_world = _base._apply_persistent_actions(world, plan.get("actions") or [])
            _base._write_json(_base._WORLD_PATH, {"saved_at": int(time.time()), "world": evolved_world})
            payload = {**plan, **{k: decision[k] for k in ("director_intent", "must_keep", "creative_freedom", "director_note")}, "ok": True, "admin_command": True, "world": evolved_world, "command_id": command_id}
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
