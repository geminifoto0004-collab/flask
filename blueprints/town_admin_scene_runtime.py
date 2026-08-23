"""Make admin free-text story commands choose the right atomic scene tool."""

from .town_ai_director_runtime import DIRECTOR_TOOLS
from . import town_admin_runtime as _admin


def _name(tool):
    return str((tool.get("function") or {}).get("name") or "")


def _only_tool(name):
    return [tool for tool in DIRECTOR_TOOLS if _name(tool) == name]


def install_admin_scene_runtime():
    original_select = _admin._select_admin_tools

    def select_admin_tools(prompt):
        text = str(prompt or "").lower()
        officer_words = (
            "抱怨", "生氣", "生气", "罵", "骂", "清狗屎", "狗屎", "狗便", "清理狗", "清理",
            "趕走", "赶走", "趕狗", "赶狗", "所有的狗", "所有狗", "全部的狗", "全部狗",
            "打掃", "打扫", "掃地", "扫地", "澆花", "浇花", "整理文件",
        )
        officer_named = any(name in text for name in ("mia", "ana", "lia"))
        if officer_named and any(word in text for word in officer_words):
            tools = _only_tool("officer_scene")
            if tools:
                return tools

        entity_scene_words = (
            "探班", "探望", "拜訪", "拜访", "來找", "来找", "找 mia", "找 ana", "找 lia",
            "帶晚餐", "带晚餐", "帶飯", "带饭", "送晚餐", "送飯", "送饭", "帶咖啡", "带咖啡",
            "帶禮物", "带礼物", "送禮", "送礼", "外送", "朋友", "客人", "訪客", "访客",
            "visitor", "visit", "visita", "oscar", "待一下", "等一下再離開", "离开", "離開",
            "追求", "追她", "追他", "分手", "喜歡", "喜欢", "愛上", "爱上", "心動", "心动",
            "驚為天人", "惊为天人", "告白", "表白", "拒絕", "拒绝", "接受", "交往", "約會", "约会",
            "看ai怎麼", "让ai", "讓ai", "自己導演", "自己导演", "自己決定", "自己决定",
        )
        if any(word in text for word in entity_scene_words):
            tools = _only_tool("entity_scene")
            if tools:
                return tools
        return original_select(prompt)

    _admin._select_admin_tools = select_admin_tools
