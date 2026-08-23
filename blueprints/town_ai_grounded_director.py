"""Ground user-visible town AI narration in validated executable commands."""

from datetime import datetime

from .town_ai_language_runtime import _call_model


def _action_summary(action):
    kind = str(action.get("type") or "")
    agent = str(action.get("agent") or "")
    if kind == "agent_action":
        labels = {
            "coffee": "去沖咖啡", "files": "去整理文件", "desk": "回工位工作",
            "plant": "去看植物", "waterPlant": "去澆花", "lookSea": "去窗邊看海",
            "stretch": "伸展一下", "radio": "去用海事電台", "checkCoworker": "去找同事",
            "fishing": "去釣魚", "wander": "走一走",
        }
        return f"{agent} {labels.get(str(action.get('action') or ''), str(action.get('action') or '行動'))}"
    if kind == "agent_chat":
        return f"{action.get('from')} 和 {action.get('to')} 開始 {len(action.get('turns') or [])} 句對話"
    if kind == "agent_say":
        return f"{agent} 說了一句話"
    if kind == "agent_outfit":
        return f"{agent} 換了今天的衣服"
    if kind == "agent_profile":
        return f"{agent} 建立／更新生活檔案"
    if kind == "agent_evolve":
        return f"{agent} 的 {action.get('trait')} 改變"
    if kind == "agent_life":
        return f"{agent} 發生人生事件 {action.get('event')}"
    if kind == "replace_agent":
        return f"{agent} 的職位由 {action.get('newName')} 接替"
    if kind == "former_visit":
        return "前同事來訪"
    if kind == "plant_spawn":
        return "辦公室增加一盆植物"
    if kind == "dog_visit":
        return "一隻狗來到辦公室附近"
    if kind == "layout_shuffle":
        return "重新布置辦公室"
    if kind == "furniture_add":
        return f"新增家具 {action.get('furniture')}"
    if kind == "furniture_move":
        return f"移動家具 {action.get('id')}"
    if kind == "furniture_remove":
        return f"移除家具 {action.get('id')}"
    if kind == "object_add":
        return f"新增物件 {action.get('label') or ''}".strip()
    if kind == "world_object_spawn":
        return f"在 {action.get('zone') or 'world'} 生成 {action.get('label') or action.get('name') or '物件'}"
    if kind == "world_object_move":
        return f"移動世界物件 {action.get('id')}"
    if kind == "world_object_remove":
        return f"移除世界物件 {action.get('id')}"
    if kind == "agent_shift":
        return f"{agent} {'下班' if action.get('mode') == 'off' else '回來上班'}"
    return kind or "未知指令"


def _rotating_night_agent(context):
    try:
        local_time = str((context or {}).get("local_time") or "")
        dt = datetime.fromisoformat(local_time)
        index = abs(dt.year * 372 + dt.month * 31 + dt.day) % 3
        return ["MIA", "ANA", "LIA"][index]
    except Exception:
        return ""


def _on_duty_agents(world, context):
    world = world if isinstance(world, dict) else {}
    named = world.get("onDutyAgents")
    if isinstance(named, list):
        result = {str(v or "").upper() for v in named if str(v or "").upper() in {"MIA", "ANA", "LIA"}}
        if result:
            return result
    agents = world.get("agents") if isinstance(world.get("agents"), list) else []
    explicit = {
        str(a.get("name") or a.get("slot") or "").upper()
        for a in agents if isinstance(a, dict) and a.get("onDuty") is True
    }
    explicit &= {"MIA", "ANA", "LIA"}
    if explicit:
        return explicit
    hour = int((context or {}).get("hour") or 0)
    if hour >= 20 or hour < 7:
        night_agent = str(world.get("nightShiftAgent") or "").upper()
        if night_agent not in {"MIA", "ANA", "LIA"}:
            night_agent = _rotating_night_agent(context)
        return {night_agent} if night_agent else set()
    result = set()
    for a in agents:
        if not isinstance(a, dict) or bool(a.get("manualOffDuty")):
            continue
        name = str(a.get("name") or a.get("slot") or "").upper()
        if name in {"MIA", "ANA", "LIA"}:
            result.add(name)
    return result or {"MIA", "ANA", "LIA"}


def _filter_duty_actions(actions, world, context):
    duty = _on_duty_agents(world, context)
    hour = int((context or {}).get("hour") or 0)
    night = hour >= 20 or hour < 7
    filtered = []
    for action in actions or []:
        kind = str(action.get("type") or "")
        if kind == "agent_chat":
            a = str(action.get("from") or "").upper()
            b = str(action.get("to") or "").upper()
            if night or len(duty) < 2 or a not in duty or b not in duty:
                continue
        elif kind in {"agent_action", "agent_say"}:
            agent = str(action.get("agent") or "").upper()
            if agent not in duty:
                continue
        filtered.append(action)
    return filtered


def grounded_model_decision(world, evolution=False):
    from .town_ai_bp import _extract_json, _validate_actions

    text, model, context, news = _call_model(world, evolution)
    decision = _extract_json(text)
    actions = _filter_duty_actions(_validate_actions(decision.get("actions")), world, context)

    if not actions:
        text, model, context, news = _call_model(
            world,
            evolution,
            retry_note=(
                "Your previous response produced no executable action after validation. "
                "Return 1-3 valid actions only. Keep MIA/ANA/LIA exactly in Latin letters. "
                "Respect onDutyAgents. At Iquique night there is only ONE duty officer, so NEVER use agent_chat; "
                "use agent_say or a non-dialogue world action instead."
            ),
        )
        decision = _extract_json(text)
        actions = _filter_duty_actions(_validate_actions(decision.get("actions")), world, context)

    thought = "；".join(_action_summary(action) for action in actions[:5])
    if not thought:
        thought = "本輪沒有可執行的 AI 指令"

    return {
        "ok": True,
        "thought": thought[:220],
        "actions": actions,
        "model": model,
        "context": context,
        "news_context_count": len(news),
        "director_tools": True,
        "grounded": True,
    }
