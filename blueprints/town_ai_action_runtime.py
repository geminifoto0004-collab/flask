"""Compatibility/runtime layer for the newest browser director tools.

The base town_ai_bp intentionally stays conservative. This module expands only
purpose-built town actions used by the current App Block while keeping the
server as the validation boundary. No arbitrary JavaScript or SQL is accepted.
"""

import re
import time

from flask import jsonify

from . import town_ai_bp as _base


_ORIGINAL_VALIDATE = _base._validate_actions
_ORIGINAL_APPLY = _base._apply_persistent_actions
_ORIGINAL_CLEAN = _base._clean_world
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_AGENT_IDS = {"MIA", "ANA", "LIA"}


def _at_seconds(item):
    try:
        value = float(item.get("at_seconds", item.get("at", 0)) or 0)
    except Exception:
        value = 0
    return round(max(0.0, min(300.0, value)), 1)


def _attach_time(actions, item):
    at = _at_seconds(item)
    for action in actions:
        if at > 0:
            action["at_seconds"] = at
    return actions


def clean_world(world):
    """Keep safe recent stimuli that the older base cleaner did not know about."""
    cleaned = _ORIGINAL_CLEAN(world)
    if isinstance(world, dict):
        stimuli = world.get("stimuli")
        if isinstance(stimuli, list):
            safe = []
            for item in stimuli[-12:]:
                if not isinstance(item, dict):
                    continue
                safe.append({
                    "type": str(item.get("type") or "")[:40],
                    "agent": str(item.get("agent") or "")[:18],
                    "displayName": str(item.get("displayName") or "")[:24],
                    "reason": str(item.get("reason") or "")[:40],
                    "annoyance": item.get("annoyance"),
                    "dogLove": item.get("dogLove"),
                    "cleanliness": item.get("cleanliness"),
                    "mood": item.get("mood"),
                    "at": item.get("at"),
                })
            cleaned["stimuli"] = safe
    return cleaned


def validate_actions(raw_actions):
    valid = []
    if not isinstance(raw_actions, list):
        return valid

    for item in raw_actions[:12]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")

        if kind == "agent_chat":
            from_agent = str(item.get("from") or item.get("agent") or "").upper()
            to_agent = str(item.get("to") or item.get("target") or "").upper()
            if from_agent not in _AGENT_IDS or to_agent not in _AGENT_IDS or from_agent == to_agent:
                continue
            turns = []
            for index, turn in enumerate(item.get("turns") if isinstance(item.get("turns"), list) else []):
                if not isinstance(turn, dict):
                    continue
                speaker = str(turn.get("speaker") or turn.get("from") or (from_agent if index % 2 == 0 else to_agent)).upper()
                text = str(turn.get("text") or turn.get("message") or "").strip()[:96]
                if speaker in {from_agent, to_agent} and text:
                    turns.append({"speaker": speaker, "text": text})
                if len(turns) >= 8:
                    break
            if turns:
                valid.extend(_attach_time([{"type": "agent_chat", "from": from_agent, "to": to_agent, "turns": turns}], item))

        elif kind == "agent_say":
            agent = str(item.get("agent") or "").upper()
            text = str(item.get("text") or item.get("message") or "").strip()[:120]
            if agent in _AGENT_IDS and text:
                valid.extend(_attach_time([{"type": "agent_say", "agent": agent, "text": text}], item))

        elif kind == "agent_outfit":
            agent = str(item.get("agent") or "").upper()
            if agent not in _AGENT_IDS:
                continue
            valid.extend(_attach_time([{
                "type": "agent_outfit",
                "agent": agent,
                "shirt": str(item.get("shirt") or "#f3eee1") if _HEX.match(str(item.get("shirt") or "#f3eee1")) else "#f3eee1",
                "vest": str(item.get("vest") or "#3a5c78") if _HEX.match(str(item.get("vest") or "#3a5c78")) else "#3a5c78",
                "badge": str(item.get("badge") or "#31516a") if _HEX.match(str(item.get("badge") or "#31516a")) else "#31516a",
                "style": str(item.get("style") or "")[:24],
                "day": str(item.get("day") or "")[:10],
            }], item))

        elif kind == "object_add":
            parts = []
            for part in item.get("parts") if isinstance(item.get("parts"), list) else []:
                if not isinstance(part, dict) or str(part.get("shape") or "rect") != "rect":
                    continue
                color = str(part.get("color") or "#8b6748")
                if not _HEX.match(color):
                    color = "#8b6748"
                try:
                    x = max(-40.0, min(40.0, float(part.get("x", 0))))
                    y = max(-40.0, min(40.0, float(part.get("y", 0))))
                    w = max(2.0, min(72.0, float(part.get("w", 8))))
                    h = max(2.0, min(60.0, float(part.get("h", 8))))
                except Exception:
                    continue
                parts.append({"shape": "rect", "x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1), "color": color})
                if len(parts) >= 24:
                    break
            if parts:
                try:
                    x = max(60.0, min(570.0, float(item.get("x", 500))))
                    y = max(104.0, min(242.0, float(item.get("y", 210))))
                except Exception:
                    x, y = 500.0, 210.0
                valid.extend(_attach_time([{
                    "type": "object_add",
                    "id": str(item.get("id") or "")[:80],
                    "x": round(x, 1), "y": round(y, 1),
                    "label": str(item.get("label") or "AI object")[:24],
                    "parts": parts,
                }], item))

        elif kind == "agent_evolve" and str(item.get("trait") or "") in {"cleanliness", "dogLove"}:
            agent = str(item.get("agent") or "").upper()
            if agent not in _AGENT_IDS:
                continue
            try:
                delta = max(-0.18, min(0.18, float(item.get("delta", 0))))
            except Exception:
                delta = 0
            if abs(delta) >= 0.01:
                valid.extend(_attach_time([{"type": "agent_evolve", "agent": agent, "trait": str(item.get("trait")), "delta": round(delta, 3)}], item))

        else:
            valid.extend(_attach_time(_ORIGINAL_VALIDATE([item]), item))

        if len(valid) >= 10:
            break
    return valid[:10]


def apply_persistent_actions(world, actions):
    actions = actions or []
    transient = {"agent_chat", "agent_say", "agent_outfit", "object_add"}
    base_actions = [a for a in actions if a.get("type") not in transient and not (a.get("type") == "agent_evolve" and a.get("trait") in {"cleanliness", "dogLove"})]
    evolved = _ORIGINAL_APPLY(world, base_actions)
    evolved = clean_world(evolved)
    agents = [dict(a) for a in evolved.get("agents", []) if isinstance(a, dict)]
    furniture = [dict(f) for f in evolved.get("furniture", []) if isinstance(f, dict)]

    for action in actions:
        kind = action.get("type")
        if kind == "agent_outfit":
            for agent in agents:
                if str(agent.get("name") or "").upper() == action.get("agent"):
                    agent["outfitDay"] = action.get("day") or ""
                    agent["outfit"] = {
                        "shirt": action.get("shirt"), "vest": action.get("vest"),
                        "badge": action.get("badge"), "style": action.get("style") or "",
                    }
                    break
        elif kind == "agent_evolve" and action.get("trait") in {"cleanliness", "dogLove"}:
            for agent in agents:
                if str(agent.get("name") or "").upper() == action.get("agent"):
                    trait = action.get("trait")
                    try:
                        current = float(agent.get(trait, 0.5))
                        agent[trait] = round(max(0.05, min(1.0, current + float(action.get("delta") or 0))), 3)
                    except Exception:
                        pass
                    break
        elif kind == "object_add" and len(furniture) < 24:
            object_id = str(action.get("id") or f"ai-object-{int(time.time()*1000)}")[:80]
            if not any(str(f.get("id")) == object_id for f in furniture):
                furniture.append({
                    "id": object_id, "type": "custom_object", "x": action.get("x"), "y": action.get("y"),
                    "label": action.get("label") or "AI object", "parts": action.get("parts") or [],
                })

    evolved["agents"] = agents[:3]
    evolved["furniture"] = furniture[:24]
    return evolved


def install_latest_action_runtime():
    _base._validate_actions = validate_actions
    _base._apply_persistent_actions = apply_persistent_actions
    _base._clean_world = clean_world

    @_base.town_ai_bp.route("/world", methods=["GET"])
    def latest_town_world():
        stored = _base._read_json(_base._WORLD_PATH, {})
        world = _base._clean_world(stored.get("world"))
        try:
            version = int(stored.get("saved_at") or 0)
        except Exception:
            version = 0
        return jsonify({"ok": True, "version": version, "world": world})
