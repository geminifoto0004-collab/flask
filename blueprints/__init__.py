# ========== blueprints/__init__.py ==========
"""
Blueprints 包初始化
"""

from .user_auth_bp import user_auth_bp
from .b2_test_bp import b2_test_bp
from . import town_ai_bp as _town_ai_module
from .town_ai_director_runtime import director_model_decision
from . import town_page_bp as _town_page_module
from .town_latest_page_runtime import latest_town_html

# Render /api/town/think uses the validated AI director. The model can only
# return town-director actions; browser physics and backend validation remain the
# execution/security boundary.
_town_ai_module._model_decision = director_model_decision
town_ai_bp = _town_ai_module.town_ai_bp

# Serve the exact current App Block snapshot. Do not run the legacy layered
# string-replacement patch chain on top of the new build.
town_page_bp = _town_page_module.town_page_bp
_town_page_module._patched_town_html = latest_town_html

# b2_test_bp has no url_prefix and is already registered by app.py.
# Nest the town blueprints under it so both the browser page and /api/town/*
# become available without changing the large app.py entry point.
b2_test_bp.register_blueprint(town_ai_bp)
b2_test_bp.register_blueprint(town_page_bp)

__all__ = ['user_auth_bp', 'town_ai_bp', 'town_page_bp']
