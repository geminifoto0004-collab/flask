"""Persistent on/off-duty and temporary visitor capabilities for CUSTOMS AGENT TOWN."""

import time

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS, _fn

_AGENT_IDS = {"MIA", "ANA", "LIA"}


def _ensure_tools():
    names = {(item.get("function") or {}).get("name") for item in DIRECTOR_TOOLS}
    if "agent_shift" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "agent_shift",
            "Change one officer's duty state. Use mode=off when the administrator says someone should get off work/go home, and mode=on when asked to return to work.",
            {
                "agent": {"type": "string", "enum": ["MIA", "ANA", "LIA"]},
                "mode": {"type": "string", "enum": ["off", "on"]},
            },
            ["agent", "mode"],
        ))
    if "visitor_visit" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "visitor_visit",
            "Bring a temporary human visitor into the customs office to visit an officer, optionally carrying food/coffee/flowers/a gift. The visitor arrives, stays briefly, then leaves automatically. Use this for requests such as 'Oscar comes to visit MIA and brings dinner'.",
            {
                "name": {"type": "string", "minLength": 1, "maxLength": 18},
                "target": {"type": "string", "enum": ["MIA", "ANA", "LIA"]},
                "gift": {"type": "string", "maxLength": 24},
                "staySeconds": {"type": "integer", "minimum": 8, "maximum": 45},
            },
            ["name", "target", "staySeconds"],
        ))


def install_shift_runtime():
    _ensure_tools()
    previous_validate = _base._validate_actions
    previous_apply = _base._apply_persistent_actions
    previous_clean = _base._clean_world

    def validate_actions(raw_actions):
        if not isinstance(raw_actions, list):
            return []
        output = []
        for index, item in enumerate(raw_actions[:12]):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "")
            if kind == "agent_shift":
                agent = str(item.get("agent") or "").upper()
                mode = str(item.get("mode") or item.get("shift") or "").lower()
                if agent in _AGENT_IDS and mode in {"off", "on"}:
                    output.append({"type": "agent_shift", "agent": agent, "mode": mode})
            elif kind == "visitor_visit":
                name = str(item.get("name") or item.get("visitor") or "").strip()[:18]
                target = str(item.get("target") or item.get("to") or "").upper()
                gift = str(item.get("gift") or item.get("bring") or "").strip()[:24]
                try:
                    stay = int(item.get("staySeconds") or item.get("stay_seconds") or 18)
                except Exception:
                    stay = 18
                stay = max(8, min(45, stay))
                if name and target in _AGENT_IDS:
                    output.append({
                        "type": "visitor_visit",
                        "id": str(item.get("id") or item.get("action_id") or f"visitor-{int(time.time()*1000)}-{index}")[:80],
                        "name": name,
                        "target": target,
                        "gift": gift,
                        "staySeconds": stay,
                    })
            else:
                output.extend(previous_validate([item]))
        return output[:10]

    def clean_world(world):
        cleaned = previous_clean(world)
        source = world if isinstance(world, dict) else {}
        now_ms = int(time.time() * 1000)
        visitors = []
        raw_visitors = source.get("visitors") if isinstance(source.get("visitors"), list) else []
        for item in raw_visitors[-12:]:
            if not isinstance(item, dict):
                continue
            target = str(item.get("target") or "").upper()
            name = str(item.get("name") or "").strip()[:18]
            if not name or target not in _AGENT_IDS:
                continue
            created_at = int(item.get("createdAt") or item.get("created_at") or now_ms)
            stay = max(8, min(45, int(item.get("staySeconds") or 18)))
            expires_at = int(item.get("expiresAt") or (created_at + (stay + 10) * 1000))
            if expires_at < now_ms - 5000:
                continue
            visitors.append({
                "id": str(item.get("id") or "")[:80],
                "name": name,
                "target": target,
                "gift": str(item.get("gift") or "")[:24],
                "staySeconds": stay,
                "createdAt": created_at,
                "expiresAt": expires_at,
            })
        cleaned["visitors"] = visitors[-8:]
        return cleaned

    def apply_persistent_actions(world, actions):
        actions = actions or []
        people_actions = [a for a in actions if a.get("type") in {"agent_shift", "visitor_visit"}]
        evolved = previous_apply(world, [a for a in actions if a.get("type") not in {"agent_shift", "visitor_visit"}])
        agents = [dict(a) for a in evolved.get("agents", []) if isinstance(a, dict)]
        visitors = [dict(v) for v in evolved.get("visitors", []) if isinstance(v, dict)]
        now_ms = int(time.time() * 1000)
        for action in people_actions:
            if action.get("type") == "agent_shift":
                for agent in agents:
                    if str(agent.get("name") or agent.get("slot") or "").upper() != action.get("agent"):
                        continue
                    agent["manualOffDuty"] = action.get("mode") == "off"
                    agent["dutyState"] = "off" if action.get("mode") == "off" else "on"
                    break
            elif action.get("type") == "visitor_visit":
                visitor_id = str(action.get("id") or "")[:80]
                if visitor_id and not any(str(v.get("id")) == visitor_id for v in visitors):
                    stay = max(8, min(45, int(action.get("staySeconds") or 18)))
                    visitors.append({
                        "id": visitor_id,
                        "name": str(action.get("name") or "訪客")[:18],
                        "target": str(action.get("target") or "MIA").upper(),
                        "gift": str(action.get("gift") or "")[:24],
                        "staySeconds": stay,
                        "createdAt": now_ms,
                        "expiresAt": now_ms + (stay + 10) * 1000,
                    })
        evolved["agents"] = agents[:3]
        evolved["visitors"] = visitors[-8:]
        return clean_world(evolved)

    _base._validate_actions = validate_actions
    _base._apply_persistent_actions = apply_persistent_actions
    _base._clean_world = clean_world
