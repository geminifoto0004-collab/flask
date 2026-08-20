"""Cloud/read-only helpers for the shared order_tracking Blueprint.

There are now two different concepts:
- legacy cloud/provider mode (old Render adapter path), and
- unified remote DB mode, where the exact LAN ORDER routes/UI run against a TiDB
  mirror through the DB compatibility layer.

Unified remote DB mode intentionally reports ``cloud_mode=False`` to the ORDER
routes/templates so they do not branch into a second Render-specific UI/provider.
Read-only enforcement remains independent and can stay enabled on Render.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Dict

from flask import current_app, jsonify, request

from .config import CLOUD_MODE, CLOUD_READ_ONLY
from .permissions_config import PERMISSION_MATRIX
from .runtime_mode import unified_remote_db_enabled

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# POST endpoints that are semantically read-only/auth related. Unknown non-GET
# endpoints are still denied while Render is configured read-only.
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
    """Return legacy provider-mode status for ORDER route/UI branching.

    In unified WAN mode this must be False: the point is to execute the exact LAN
    routes against TiDB rather than maintaining a second cloud implementation.
    """
    if unified_remote_db_enabled():
        return False
    return bool(current_app.config.get("TRACKING_CLOUD_MODE", CLOUD_MODE))


def cloud_read_only_enabled() -> bool:
    """Return whether business writes must be rejected."""
    # Keep this separate from cloud_mode_enabled(); unified WAN reuses LAN routes
    # while Render can still enforce a server-side read-only policy.
    default = CLOUD_READ_ONLY or unified_remote_db_enabled() or cloud_mode_enabled()
    return bool(current_app.config.get("TRACKING_CLOUD_READ_ONLY", default))


def effective_permission_matrix() -> Dict[str, Dict[str, list]]:
    """Return the role matrix used to render ORDER.

    Unified WAN intentionally keeps the LAN menu/controls visible so the visual
    product is the same. Backend read-only enforcement is still authoritative.
    Legacy provider mode keeps the old behaviour of removing write capabilities.
    """
    matrix = deepcopy(PERMISSION_MATRIX)
    if unified_remote_db_enabled():
        return matrix
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
    """Blueprint before_request guard."""
    if not cloud_read_only_enabled():
        return None
    if request.method in _SAFE_METHODS:
        return None
    if request.endpoint in _CLOUD_READ_ONLY_POST_ALLOWLIST:
        return None
    return cloud_read_only_response()
