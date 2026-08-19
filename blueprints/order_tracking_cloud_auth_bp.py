"""Authenticated sync endpoint for the isolated Render ORDER login mirror."""
from flask import Blueprint, jsonify, request

from blueprints.b2_test_bp import _order_cloud_auth_source
from services.order_tracking_cloud_auth import sync_order_users

order_tracking_cloud_auth_bp = Blueprint("order_tracking_cloud_auth", __name__)


@order_tracking_cloud_auth_bp.route("/api/order-cloud/sync/users", methods=["POST"])
def sync_users():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        payload = request.get_json(silent=True) or {}
        result = sync_order_users(payload.get("users") or [], source_site=source_site)
        return jsonify({"ok": True, "result": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
