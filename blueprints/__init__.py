# ========== blueprints/__init__.py ==========
"""
Blueprints 包初始化
"""

from .user_auth_bp import user_auth_bp
from .b2_test_bp import b2_test_bp
from .town_ai_bp import town_ai_bp
from . import town_page_bp as _town_page_module
from .town_world_runtime_patch import patch_town_world

# Keep the existing page blueprint, but wrap its HTML renderer with the newest
# autonomous-world layer so the large base template does not need to be copied.
town_page_bp = _town_page_module.town_page_bp
_town_page_base_renderer = _town_page_module._patched_town_html


def _render_town_with_world_patch():
    return patch_town_world(_town_page_base_renderer())


_town_page_module._patched_town_html = _render_town_with_world_patch

# b2_test_bp has no url_prefix and is already registered by app.py.
# Nest the town blueprints under it so both the browser page and /api/town/*
# become available without changing the large app.py entry point.
b2_test_bp.register_blueprint(town_ai_bp)
b2_test_bp.register_blueprint(town_page_bp)

__all__ = ['user_auth_bp', 'town_ai_bp', 'town_page_bp']