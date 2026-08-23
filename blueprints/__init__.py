# ========== blueprints/__init__.py ==========
"""
Blueprints 包初始化

主 Render 只載入正式系統需要的共用 Blueprint。
AI 小鎮模組仍保留在 repository，之後可由獨立 Render 入口載入，
但這個主服務不再 import、install 或 register 任何 town runtime。
"""

import os as _os
import sys as _sys

# Render must never run the full schema bootstrap inside a user's first HTTP
# request. app.py imports init_database before importing this package, so replace
# only app.py's bound reference while the app module is still being imported.
# The real database.init_database function remains available for explicit
# maintenance/migration jobs; normal web requests go straight to their routes.
if _os.environ.get('RENDER') or _os.environ.get('RENDER_SERVICE_NAME'):
    _app_module = _sys.modules.get('app')
    if _app_module is not None and hasattr(_app_module, 'init_database'):
        def _skip_render_request_database_init():
            return None
        _app_module.init_database = _skip_render_request_database_init
        print('✅ Render request-time database bootstrap disabled')

from .user_auth_bp import user_auth_bp
from .b2_test_bp import b2_test_bp

# AI town is intentionally NOT imported here.
# Keeping the town source files in blueprints/ lets a future dedicated Render
# service import and register them from its own lightweight town_app.py entry.
print('✅ AI town disabled on main Render service')

__all__ = ['user_auth_bp', 'b2_test_bp']
