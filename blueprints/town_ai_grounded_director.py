"""Ground user-visible town AI narration in validated executable commands."""

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
    return kind or "未知指令"


def grounded_model_decision(world, evolution=False):
    from .town_ai_bp import _extract_json, _validate_actions

    text, model, context, news = _call_model(world, evolution)
    decision = _extract_json(text)
    actions = _validate_actions(decision.get("actions"))

    if not actions:
        text, model, context, news = _call_model(
            world,
            evolution,
            retry_note=(
                "Your previous response produced no executable action after validation. "
                "Return 1-3 valid actions only. Keep MIA/ANA/LIA exactly in Latin letters. "
                "If anyone talks, use agent_chat with actual turns or agent_say with actual text."
            ),
        )
        decision = _extract_json(text)
        actions = _validate_actions(decision.get("actions"))

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
