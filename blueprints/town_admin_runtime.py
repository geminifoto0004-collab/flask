"""Independent admin controls for CUSTOMS AGENT TOWN.

Uses TOWN_ADMIN_PASSWORD from Render. The password never enters HTML/GitHub and
all privileged actions are rechecked server-side through the Flask session.
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


def _is_admin():
    try:
        return float(session.get(_ADMIN_SESSION_KEY) or 0) > time.time()
    except Exception:
        return False


def _require_admin():
    if not _is_admin():
        return jsonify({"ok": False, "error": "admin_required"}), 401
    return None


def _admin_model_command(prompt, world):
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    model = (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip()
    context = _base._iquique_context()
    news = _recent_news()
    system_prompt = """You are the privileged world director for CUSTOMS AGENT TOWN in Iquique, Chile.
The administrator has typed one direct instruction. Fulfil that instruction ONLY through the provided tools.
Never output arbitrary JavaScript, SQL, shell commands, URLs, secrets, or executable code.
MIA, ANA and LIA are literal agent IDs.
If the administrator asks to create a seal in the sea/harbor, use sea_creature_spawn with kind=seal.
If the request cannot be represented by the available tools, choose no unrelated action.
For dialogue, use natural Chilean Spanish in text and Traditional Chinese in text_zh where the schema supports it.
Return tool calls, not an imaginary narration."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({
                "admin_instruction": prompt,
                "server_context": context,
                "recent_news": news,
                "world": world,
            }, ensure_ascii=False, separators=(",", ":"))},
        ],
        "tools": DIRECTOR_TOOLS,
        "tool_choice": "required",
        "temperature": 0.85,
        "max_tokens": 1200,
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
    message = ((raw.get("choices") or [{}])[0].get("message") or {})
    actions = _base._validate_actions(_tool_calls_to_actions(message))
    return {"ok": True, "actions": actions, "model": model, "context": context}


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
        if not prompt:
            return jsonify({"ok": False, "error": "empty_prompt"}), 400
        try:
            stored = _base._read_json(_base._WORLD_PATH, {})
            world = _base._clean_world(stored.get("world"))
            result = _admin_model_command(prompt, world)
            actions = result.get("actions") or []
            if not actions:
                return jsonify({"ok": False, "error": "no_supported_action"}), 422
            decision = {
                "ok": True,
                "thought": "管理員指令已轉成可執行世界動作",
                "actions": actions,
                "model": result.get("model") or "deepseek-chat",
                "context": result.get("context") or _base._iquique_context(),
            }
            plan = _base._save_plan(decision, "admin-command")
            evolved_world = _base._apply_persistent_actions(world, plan.get("actions") or [])
            _base._write_json(_base._WORLD_PATH, {"saved_at": int(time.time()), "world": evolved_world})
            return jsonify({**plan, "ok": True, "admin_command": True})
        except requests.Timeout:
            return jsonify({"ok": False, "error": "DeepSeek request timed out"}), 504
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
