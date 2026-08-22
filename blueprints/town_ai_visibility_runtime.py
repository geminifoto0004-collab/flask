"""Final validation layer for visible current-town actions.

This wrapper runs after the broader compatibility validator. It prevents a bare
`agent_action: chat` (which has no words) and preserves longer model-generated
conversation text for the browser/log.
"""

from . import town_ai_bp as _base

_AGENT_IDS = {"MIA", "ANA", "LIA"}


def install_visibility_runtime():
    previous = _base._validate_actions

    def validate(raw_actions):
        valid = []
        if not isinstance(raw_actions, list):
            return valid
        for item in raw_actions[:12]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "")
            if kind == "agent_action" and str(item.get("action") or "") == "chat":
                # Dialogue must contain model-written words through agent_chat or agent_say.
                continue
            if kind == "agent_chat":
                from_agent = str(item.get("from") or item.get("agent") or "").upper()
                to_agent = str(item.get("to") or item.get("target") or "").upper()
                if from_agent not in _AGENT_IDS or to_agent not in _AGENT_IDS or from_agent == to_agent:
                    continue
                turns = []
                source = item.get("turns") if isinstance(item.get("turns"), list) else []
                for index, turn in enumerate(source):
                    if not isinstance(turn, dict):
                        continue
                    speaker = str(turn.get("speaker") or turn.get("from") or (from_agent if index % 2 == 0 else to_agent)).upper()
                    text = str(turn.get("text") or turn.get("message") or "").strip()[:160]
                    if speaker in {from_agent, to_agent} and text:
                        turns.append({"speaker": speaker, "text": text})
                    if len(turns) >= 8:
                        break
                if turns:
                    action = {"type": "agent_chat", "from": from_agent, "to": to_agent, "turns": turns}
                    try:
                        at = max(0.0, min(300.0, float(item.get("at_seconds", item.get("at", 0)) or 0)))
                    except Exception:
                        at = 0
                    if at > 0:
                        action["at_seconds"] = round(at, 1)
                    valid.append(action)
            elif kind == "agent_say":
                agent = str(item.get("agent") or "").upper()
                text = str(item.get("text") or item.get("message") or "").strip()[:160]
                if agent in _AGENT_IDS and text:
                    action = {"type": "agent_say", "agent": agent, "text": text}
                    try:
                        at = max(0.0, min(300.0, float(item.get("at_seconds", item.get("at", 0)) or 0)))
                    except Exception:
                        at = 0
                    if at > 0:
                        action["at_seconds"] = round(at, 1)
                    valid.append(action)
            else:
                valid.extend(previous([item]))
            if len(valid) >= 10:
                break
        return valid[:10]

    _base._validate_actions = validate
