"""Cloud/read-only helpers for the shared order_tracking Blueprint.

The shared package is used by both local deployments and the Render deployment.
Local behaviour stays unchanged by default. Render can opt in with app config or
environment variables and provide its own read-only order data provider later.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from flask import current_app, jsonify, request

from .config import CLOUD_MODE, CLOUD_READ_ONLY
from .permissions_config import PERMISSION_MATRIX

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# POST endpoints that are semantically read-only. Keep this list deliberately
# small; unknown non-GET endpoints are denied in cloud read-only mode.
_CLOUD_READ_ONLY_POST_ALLOWLIST = {
    "tracking_bp.login",
    "tracking_bp.logout",
    "tracking_bp.api_orders_advanced_search",
    "tracking_bp.api_export_workflows_xlsx",
    "tracking_bp.api_customer_exact_orders_batch",
    "tracking_bp.api_order_number_pool_diff",
    "tracking_bp.api_create_public_guest_link_placeholder",
    "tracking_bp.api_revoke_public_guest_link",
}

_WRITE_ACTIONS = {
    "edit",
    "delete",
    "create",
    "lock",
    "unlock",
    "upload",
}


def cloud_mode_enabled() -> bool:
    """Return whether this mounted Blueprint is running in cloud mode."""
    return bool(current_app.config.get("TRACKING_CLOUD_MODE", CLOUD_MODE))


def cloud_read_only_enabled() -> bool:
    """Return whether business writes must be rejected."""
    # Cloud mode defaults to read-only unless the parent app explicitly opts out.
    default = CLOUD_READ_ONLY or cloud_mode_enabled()
    return bool(current_app.config.get("TRACKING_CLOUD_READ_ONLY", default))


def effective_permission_matrix() -> Dict[str, Dict[str, list]]:
    """Return the normal role matrix with write capabilities removed in cloud mode.

    This changes only what the UI advertises. The server-side request guard remains
    the authoritative protection.
    """
    matrix = deepcopy(PERMISSION_MATRIX)
    if not cloud_read_only_enabled():
        return matrix

    for resources in matrix.values():
        for resource_type, actions in list(resources.items()):
            resources[resource_type] = [action for action in actions if action not in _WRITE_ACTIONS]
    return matrix


def cloud_read_only_response():
    return jsonify({
        "success": False,
        "error": "雲端版本只能查看，請回公司系統修改。",
        "code": "CLOUD_READ_ONLY",
    }), 403


def enforce_cloud_read_only_request():
    """Blueprint before_request guard.

    GET/HEAD/OPTIONS remain available. A very small set of POST endpoints that do
    not change business data is allowed. Everything else is denied while cloud
    read-only mode is enabled. This is intentionally backend-enforced rather than
    relying on hidden buttons.
    """
    if not cloud_read_only_enabled():
        return None
    if request.method in _SAFE_METHODS:
        return None
    if request.endpoint in _CLOUD_READ_ONLY_POST_ALLOWLIST:
        return None
    return cloud_read_only_response()
