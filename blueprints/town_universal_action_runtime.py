"""Universal low-level world verbs for CUSTOMS AGENT TOWN.

The director should not need a bespoke function for every story. One validated
world_action tool can operate on persistent officers and generic entities using
small composable verbs. Browser physics remains authoritative for movement.
"""

import re
import time

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS, _fn

_OFFICERS = {"MIA", "ANA", "LIA"}
_ENTITY_TYPES = {"human", "vehicle", "animal", "item", "decoration"}
_ZONES = {"office", "office_door", "harbor_walkway", "pier", "sea"}
_OPERATIONS = {"spawn", "move", "say", "wait", "interact", "give", "set_state", "set_presence", "leave", "remove", "set_relationship"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _name(tool):
    return str((tool.get("function") or {}).get("name") or "")


def _text(value, limit=80):
    return str(value or "").strip()[:limit]


def _num(value, low, high, default=None):
    try:
        value = float(value)
    except Exception:
        return default
    return round(max(low, min(high, value)), 2)


def _ensure_tool():
    if any(_name(tool) == "world_action" for tool in DIRECTOR_TOOLS):
        return
    DIRECTOR_TOOLS.append(_fn(
        "world_action",
        (
            "Universal atomic world verb. Compose several calls to direct a complete scene instead of asking for a new story-specific function. "
            "Existing officers MIA/ANA/LIA are real persistent actors: NEVER spawn copies of them. For an absent officer returning to work, first use "
            "set_state with key=onDuty and valueBool=true; the browser will make them appear outside and walk in through the door. You may then say, move, "
            "interact, give, wait or change relationship. New visitors/animals/vehicles/items use spawn first with a stable id. Use set_relationship only for "
            "a genuine persistent interpersonal change. Respect admin hard requirements; creatively fill unspecified dialogue, pacing and reactions."
        ),
        {
            "operation": {"type": "string", "enum": sorted(_OPERATIONS)},
            "entity": {"type": "string", "maxLength": 64},
            "id": {"type": "string", "maxLength": 64},
            "name": {"type": "string", "maxLength": 28},
            "entityType": {"type": "string", "enum": sorted(_ENTITY_TYPES)},
            "zone": {"type": "string", "enum": sorted(_ZONES)},
            "target": {"type": "string", "maxLength": 64},
            "x": {"type": "number", "minimum": 12, "maximum": 628},
            "y": {"type": "number", "minimum": 60, "maximum": 390},
            "speed": {"type": "number", "minimum": 12, "maximum": 80},
            "text": {"type": "string", "maxLength": 160},
            "text_zh": {"type": "string", "maxLength": 160},
            "seconds": {"type": "number", "minimum": 0.2, "maximum": 120},
            "item": {"type": "string", "maxLength": 24},
            "intent": {"type": "string", "maxLength": 80},
            "key": {"type": "string", "enum": ["onDuty", "mood", "energy", "relationship", "partnerName", "careerState"]},
            "valueString": {"type": "string", "maxLength": 64},
            "valueNumber": {"type": "number", "minimum": 0, "maximum": 1},
            "valueBool": {"type": "boolean"},
            "present": {"type": "boolean"},
            "status": {"type": "string", "maxLength": 40},
            "intensity": {"type": "number", "minimum": 0, "maximum": 1},
            "note": {"type": "string", "maxLength": 140},
            "bodyColor": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
            "accentColor": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
            "carrying": {"type": "array", "maxItems": 6, "items": {"type": "string", "maxLength": 24}},
        },
        ["operation"],
    ))


def install_universal_action_runtime():
    _ensure_tool()
    previous_validate = _base._validate_actions
    previous_apply = _base._apply_persistent_actions

    def validate_actions(raw_actions):
        if not isinstance(raw_actions, list):
            return []
        output = []
        for raw in raw_actions[:20]:
            if not isinstance(raw, dict) or str(raw.get("type") or "") != "world_action":
                output.extend(previous_validate([raw]))
                if len(output) >= 18:
                    break
                continue
            op = _text(raw.get("operation") or raw.get("op"), 24).lower()
            if op not in _OPERATIONS:
                continue
            action = {"type": "world_action", "operation": op}
            entity = _text(raw.get("entity") or raw.get("actor"), 64)
            if entity:
                action["entity"] = entity
            if op == "spawn":
                entity_id = _text(raw.get("id") or entity, 64)
                name = _text(raw.get("name") or entity_id, 28)
                entity_type = _text(raw.get("entityType") or raw.get("entity_type"), 24).lower()
                zone = _text(raw.get("zone") or "harbor_walkway", 24)
                if not entity_id or not name or entity_type not in _ENTITY_TYPES or zone not in _ZONES or entity_id.upper() in _OFFICERS:
                    continue
                action.update({"id": entity_id, "name": name, "entityType": entity_type, "zone": zone})
                for key, low, high in (("x", 12, 628), ("y", 60, 390), ("speed", 12, 80)):
                    value = _num(raw.get(key), low, high)
                    if value is not None:
                        action[key] = value
                for key, fallback in (("bodyColor", "#b7a58e"), ("accentColor", "#8670a0")):
                    value = str(raw.get(key) or "")
                    action[key] = value if _HEX.match(value) else fallback
                action["carrying"] = [_text(v, 24) for v in (raw.get("carrying") if isinstance(raw.get("carrying"), list) else []) if _text(v, 24)][:6]
            elif op in {"move", "say", "wait", "interact", "give", "set_state", "set_presence", "leave", "remove", "set_relationship"}:
                if not entity:
                    continue
                target = _text(raw.get("target"), 64)
                if target:
                    action["target"] = target
                zone = _text(raw.get("zone"), 24)
                if zone in _ZONES:
                    action["zone"] = zone
                if op == "move":
                    for key, low, high in (("x", 12, 628), ("y", 60, 390), ("speed", 12, 80)):
                        value = _num(raw.get(key), low, high)
                        if value is not None:
                            action[key] = value
                    action["intent"] = _text(raw.get("intent"), 80)
                    if not target and "zone" not in action and "x" not in action:
                        continue
                elif op == "say":
                    text = _text(raw.get("text"), 160)
                    if not text:
                        continue
                    action.update({"text": text, "text_zh": _text(raw.get("text_zh"), 160)})
                elif op == "wait":
                    action["seconds"] = _num(raw.get("seconds"), 0.2, 120, 1)
                elif op == "interact":
                    if not target:
                        continue
                    action["intent"] = _text(raw.get("intent"), 80) or "interact"
                elif op == "give":
                    item = _text(raw.get("item"), 24)
                    if not target or not item:
                        continue
                    action["item"] = item
                elif op == "set_state":
                    key = _text(raw.get("key"), 24)
                    if key not in {"onDuty", "mood", "energy", "relationship", "partnerName", "careerState"}:
                        continue
                    action["key"] = key
                    if key == "onDuty":
                        action["value"] = bool(raw.get("valueBool"))
                    elif key in {"mood", "energy"}:
                        action["value"] = _num(raw.get("valueNumber"), 0, 1, 0.5)
                    else:
                        action["value"] = _text(raw.get("valueString"), 64)
                elif op == "set_presence":
                    action["present"] = raw.get("present") is not False
                elif op == "set_relationship":
                    if not target:
                        continue
                    status = _text(raw.get("status"), 40)
                    if not status:
                        continue
                    action.update({"status": status, "intensity": _num(raw.get("intensity"), 0, 1, 0.5), "note": _text(raw.get("note"), 140)})
            output.append(action)
            if len(output) >= 18:
                break
        return output[:18]

    def apply_persistent_actions(world, actions):
        actions = actions or []
        universal = [a for a in actions if str(a.get("type") or "") == "world_action"]
        evolved = previous_apply(world, [a for a in actions if str(a.get("type") or "") != "world_action"])
        agents = [dict(a) for a in evolved.get("agents", []) if isinstance(a, dict)]
        entities = [dict(e) for e in evolved.get("genericEntities", []) if isinstance(e, dict)]
        relationships = [dict(r) for r in evolved.get("relationships", []) if isinstance(r, dict)]
        stamp = int(time.time() * 1000)

        def find_agent(name):
            key = str(name or "").upper()
            return next((a for a in agents if str(a.get("name") or a.get("slot") or "").upper() == key), None)

        for action in universal:
            op = action.get("operation")
            entity_id = str(action.get("entity") or action.get("id") or "")
            if op == "spawn":
                if any(str(e.get("id")) == str(action.get("id")) for e in entities):
                    continue
                entities.append({
                    "id": action.get("id"), "name": action.get("name"), "entityType": action.get("entityType"),
                    "zone": action.get("zone"), "x": action.get("x", 320), "y": action.get("y", 292),
                    "bodyColor": action.get("bodyColor"), "accentColor": action.get("accentColor"),
                    "carrying": action.get("carrying") or [], "script": [], "createdAt": stamp, "updatedAt": stamp,
                })
            elif op == "remove":
                entities = [e for e in entities if str(e.get("id")) != entity_id]
            elif op == "set_state":
                agent = find_agent(entity_id)
                if agent:
                    key = action.get("key")
                    if key == "onDuty":
                        agent["manualOffDuty"] = not bool(action.get("value"))
                    elif key in {"mood", "energy", "relationship", "partnerName", "careerState"}:
                        agent[key] = action.get("value")
            elif op == "set_relationship":
                target = str(action.get("target") or "")
                relationships = [r for r in relationships if not (str(r.get("actor") or "").lower() == entity_id.lower() and str(r.get("target") or "").lower() == target.lower())]
                relationships.append({"actor": entity_id, "target": target, "status": action.get("status"), "intensity": action.get("intensity", 0.5), "note": action.get("note", ""), "updatedAt": stamp})
        evolved["agents"] = agents
        evolved["genericEntities"] = entities[-40:]
        evolved["relationships"] = relationships[-100:]
        return evolved

    _base._validate_actions = validate_actions
    _base._apply_persistent_actions = apply_persistent_actions
