"""Make admin free-text visitor/story commands use the atomic generic scene tool."""

from .town_ai_director_runtime import DIRECTOR_TOOLS
from . import town_admin_runtime as _admin


def _name(tool):
    return str((tool.get("function") or {}).get("name") or "")


def install_admin_scene_runtime():
    original_select = _admin._select_admin_tools

    def select_admin_tools(prompt):
        text = str(prompt or "").lower()
        scene_words = (
            "探班", "探望", "拜訪", "拜访", "來找", "来找", "找 mia", "找 ana", "找 lia",
            "帶晚餐", "带晚餐", "帶飯", "带饭", "送晚餐", "送飯", "送饭", "帶咖啡", "带咖啡",
            "帶禮物", "带礼物", "送禮", "送礼", "外送", "朋友", "客人", "訪客", "访客",
            "visitor", "visit", "visita", "oscar", "待一下", "等一下再離開", "离开", "離開",
        )
        if any(word in text for word in scene_words):
            scene = [tool for tool in DIRECTOR_TOOLS if _name(tool) == "entity_scene"]
            if scene:
                return scene
        return original_select(prompt)

    _admin._select_admin_tools = select_admin_tools
