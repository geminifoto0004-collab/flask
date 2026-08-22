"""Persistent on/off-duty capability for CUSTOMS AGENT TOWN."""

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS, _fn

_AGENT_IDS = {"MIA", "ANA", "LIA"}


def _ensure_tool():
    if any((item.get("function") or {}).get("name") == "agent_shift" for item in DIRECTOR_TOOLS):
        return
    DIRECTOR_TOOLS.append(_fn(
        "agent_shift",
        "Change one officer's duty state. Use mode=off when the administrator says someone should get off work/go home (for example: 讓MIA下班), and mode=on when asked to return to work.",
        {
            "agent": {"type": "string", "enum": ["MIA", "ANA", "LIA"]},
            "mode": {"type": "string", "enum": ["off", "on"]},
        },
        ["agent", "mode"],
    ))


def install_shift_runtime():
    _ensure_tool()
    previous_validate = _base._validate_actions
    previous_apply = _base._apply_persistent_actions

    def validate_actions(raw_actions):
        if not isinstance(raw_actions, list):
            return []
        output = []
        for item in raw_actions[:12]:
            if not isinstance(item, dict) or str(item.get("type") or "") != "agent_shift":
                output.extend(previous_validate([item]))
                continue
            agent = str(item.get("agent") or "").upper()
            mode = str(item.get("mode") or item.get("shift") or "").lower()
            if agent in _AGENT_IDS and mode in {"off", "on"}:
                output.append({"type": "agent_shift", "agent": agent, "mode": mode})
        return output[:10]

    def apply_persistent_actions(world, actions):
        actions = actions or []
        shift_actions = [a for a in actions if a.get("type") == "agent_shift"]
        evolved = previous_apply(world, [a for a in actions if a.get("type") != "agent_shift"])
        agents = [dict(a) for a in evolved.get("agents", []) if isinstance(a, dict)]
        for action in shift_actions:
            for agent in agents:
                if str(agent.get("name") or agent.get("slot") or "").upper() != action.get("agent"):
                    continue
                agent["manualOffDuty"] = action.get("mode") == "off"
                agent["dutyState"] = "off" if action.get("mode") == "off" else "on"
                break
        evolved["agents"] = agents[:3]
        return evolved

    _base._validate_actions = validate_actions
    _base._apply_persistent_actions = apply_persistent_actions
