"""Runtime switches for the single-codebase ORDER deployment."""
from __future__ import annotations

import os

from flask import current_app, has_app_context


def _env_bool(name: str, default=False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {'1', 'true', 'yes', 'on', 'y'}


def unified_remote_db_enabled() -> bool:
    """True when the same LAN ORDER code should read the TiDB mirror.

    Render enables this automatically. It may also be enabled explicitly with
    TRACKING_UNIFIED_REMOTE_DB=1 for another WAN deployment.
    """
    default = bool(os.environ.get('RENDER') or os.environ.get('RENDER_SERVICE_NAME'))
    env_value = _env_bool('TRACKING_UNIFIED_REMOTE_DB', default)
    if has_app_context():
        return bool(current_app.config.get('TRACKING_UNIFIED_REMOTE_DB', env_value))
    return env_value
