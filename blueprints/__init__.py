# ========== blueprints/__init__.py ==========
"""
Blueprints 包初始化
"""

from .user_auth_bp import user_auth_bp
from .b2_test_bp import b2_test_bp
from . import town_ai_bp as _town_ai_module
from .town_ai_action_runtime import install_latest_action_runtime
from .town_ai_visibility_runtime import install_visibility_runtime
from .town_ai_history_runtime import install_history_runtime
from .town_ai_profile_runtime import install_profile_runtime
from .town_ai_bilingual_runtime import install_bilingual_runtime
from .town_ai_grounded_director import grounded_model_decision
from . import town_page_bp as _town_page_module
from .town_latest_page_runtime import latest_town_html
from .town_render_visibility_patch import patch_render_visibility
from .town_render_action_patch import patch_render_actions
from .town_render_depth_patch import patch_render_depth
from .town_render_fishing_patch import patch_render_fishing
from .town_render_chat_timing_patch import patch_render_chat_timing
from .town_render_profile_patch import patch_render_profiles
from .town_render_dialogue_panel_patch import patch_render_dialogue_panel
from .town_render_dialogue_fix_patch import patch_render_dialogue_fix
from .town_render_chatapp_panel_patch import patch_render_chatapp_panel
from .town_render_boot_safety_patch import patch_render_boot_safety
from .town_render_frame_safety_patch import patch_render_frame_safety

# Install validation/persistence for the current browser capabilities before the
# blueprint is registered on the Flask app.
install_latest_action_runtime()
install_visibility_runtime()
install_history_runtime()
install_profile_runtime()
install_bilingual_runtime()

# Render /api/town/think uses the grounded AI world director. User-visible
# narration is rebuilt from validated executable actions, so the log cannot
# claim a physical event that was never actually sent to the browser.
_town_ai_module._model_decision = grounded_model_decision
town_ai_bp = _town_ai_module.town_ai_bp

# Serve the current embedded town snapshot with small runtime patches for the
# latest visibility/animation fixes while the App Block continues to evolve.
town_page_bp = _town_page_module.town_page_bp
_town_page_module._patched_town_html = lambda: patch_render_frame_safety(patch_render_boot_safety(patch_render_chatapp_panel(patch_render_dialogue_fix(patch_render_dialogue_panel(patch_render_profiles(patch_render_chat_timing(patch_render_fishing(patch_render_depth(patch_render_actions(patch_render_visibility(latest_town_html())))))))))))

# b2_test_bp has no url_prefix and is already registered by app.py.
# Nest the town blueprints under it so both the browser page and /api/town/*
# become available without changing the large app.py entry point.
b2_test_bp.register_blueprint(town_ai_bp)
b2_test_bp.register_blueprint(town_page_bp)

__all__ = ['user_auth_bp', 'town_ai_bp', 'town_page_bp']
