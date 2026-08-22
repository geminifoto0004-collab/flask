"""DeepSeek-powered life director for CUSTOMS AGENT TOWN.

The browser sends a compact world snapshot. The model may only suggest a small
set of whitelisted life events; browser physics/pathfinding remains authoritative.
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
_ALLOWED_DOG_KINDS = {"male", "female"}
_LAST_CALL_BY_IP = {}


def _cors(response):
    # Prototype endpoint is called from the ChatGPT-hosted App Block preview.
    # DeepSeek credentials never leave Render; only model decisions are returned.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
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

    for item in raw_actions[:5]:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "agent_action":
            agent = str(item.get("agent") or "").upper()
            action = str(item.get("action") or "")
            if agent in _ALLOWED_AGENTS and action in _ALLOWED_AGENT_ACTIONS:
                valid.append({"type": "agent_action", "agent": agent, "action": action})
        elif kind == "plant_spawn":
            valid.append({"type": "plant_spawn"})
        elif kind == "dog_visit":
            dog_kind = str(item.get("kind") or "male").lower()
            if dog_kind in _ALLOWED_DOG_KINDS:
                valid.append({"type": "dog_visit", "kind": dog_kind})
        if len(valid) >= 3:
            break
    return valid


@town_ai_bp.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    return jsonify({
        "ok": True,
        "deepseek_configured": bool((os.environ.get("DEEPSEEK_API_KEY") or "").strip()),
        "model": (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip(),
    })


@town_ai_bp.route("/think", methods=["POST", "OPTIONS"])
def think():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))

    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "DEEPSEEK_API_KEY is not configured"}), 503

    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    now = time.time()
    previous = _LAST_CALL_BY_IP.get(ip, 0)
    if now - previous < 3:
        return jsonify({"ok": False, "error": "AI is thinking; please wait a few seconds"}), 429
    _LAST_CALL_BY_IP[ip] = now

    # The App Block sends a simple cross-origin POST so the browser does not need
    # an OPTIONS preflight. Accept both normal application/json and raw JSON text.
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        try:
            body = json.loads(request.get_data(as_text=True) or "{}")
        except Exception:
            body = {}
    world = _clean_world(body.get("world"))
    model = (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip()

    system_prompt = """You are the life director of a persistent pixel-art customs office called CUSTOMS AGENT TOWN.
The town must feel like a small electronic-pet world even when no ships arrive.
Choose at most 3 small, natural, varied life events based on the current world state and personalities.
Do not control coordinates, walls, sea movement, pathfinding, ship inspection results, or database records.
Avoid spawning dogs repeatedly. Prefer character behavior most of the time.
Return ONLY one JSON object with this exact shape:
{"thought":"short Traditional Chinese sentence, max 60 chars","actions":[...]}
Allowed actions are ONLY:
{"type":"agent_action","agent":"MIA|ANA|LIA","action":"coffee|files|desk|plant|waterPlant|lookSea|stretch|radio|chat|checkCoworker|fishing|wander"}
{"type":"plant_spawn"}
{"type":"dog_visit","kind":"male|female"}
The thought and action choices should make sense from the supplied world JSON."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Current world JSON:\n" + json.dumps(world, ensure_ascii=False, separators=(",", ":"))},
        ],
        "temperature": 1.15,
        "max_tokens": 320,
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=35,
        )
        if not response.ok:
            detail = response.text[:500]
            return jsonify({"ok": False, "error": f"DeepSeek HTTP {response.status_code}", "detail": detail}), 502

        raw = response.json()
        text = (((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        decision = _extract_json(text)
        actions = _validate_actions(decision.get("actions"))
        thought = str(decision.get("thought") or "AI 看了一下小鎮，暫時沒有特別安排。")[:120]
        return jsonify({"ok": True, "thought": thought, "actions": actions, "model": model})
    except requests.Timeout:
        return jsonify({"ok": False, "error": "DeepSeek request timed out"}), 504
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:300]}), 500
