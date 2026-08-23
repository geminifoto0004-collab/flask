"""Route free-text admin stories through the universal low-level world verb."""

from .town_ai_director_runtime import DIRECTOR_TOOLS
from . import town_admin_runtime as _admin


def _name(tool):
    return str((tool.get("function") or {}).get("name") or "")


def install_universal_action_admin_patch():
    universal = [tool for tool in DIRECTOR_TOOLS if _name(tool) == "world_action"]
    if not universal:
        return

    def select_admin_tools(_prompt):
        # One composable tool is intentional: the model can call it repeatedly
        # with different verbs instead of selecting a bespoke story function.
        return universal

    _admin._select_admin_tools = select_admin_tools
