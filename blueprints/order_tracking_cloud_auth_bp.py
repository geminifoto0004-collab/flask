"""Authenticated sync endpoints for Render ORDER cloud mirrors."""
import gzip
import json

from flask import Blueprint, jsonify, request

from blueprints.b2_test_bp import _order_cloud_auth_source
from services.order_tracking_cloud_auth import sync_order_users
from services.order_cloud_snapshot_service import get_snapshot_state, replace_snapshot
from services.order_full_mirror_service import get_full_mirror_state, replace_full_mirror
from services.order_full_mirror_chunk_service import (
    append_chunk,
    begin_chunked_mirror,
    finalize_chunked_mirror,
)

order_tracking_cloud_auth_bp = Blueprint("order_tracking_cloud_auth", __name__)


def _request_json_body():
    """Read normal JSON or gzip JSON used by ORDER mirror transport."""
    if str(request.headers.get('Content-Encoding') or '').strip().lower() == 'gzip':
        raw = request.get_data(cache=False)
        try:
            return json.loads(gzip.decompress(raw).decode('utf-8'))
        except Exception as exc:
            raise ValueError(f'invalid gzip JSON payload: {exc}') from exc
    return request.get_json(silent=True) or {}


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


@order_tracking_cloud_auth_bp.route("/api/order-cloud/sync/snapshot-state", methods=["GET"])
def snapshot_state():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        return jsonify({"ok": True, "result": get_snapshot_state()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@order_tracking_cloud_auth_bp.route("/api/order-cloud/sync/snapshot", methods=["POST"])
def sync_snapshot():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        payload = request.get_json(silent=True) or {}
        result = replace_snapshot(
            payload.get("orders") or [],
            payload.get("snapshot_hash"),
            source_watermark=payload.get("source_watermark"),
            source_site=source_site,
            force=bool(payload.get("force", False)),
        )
        return jsonify({"ok": True, "result": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@order_tracking_cloud_auth_bp.route('/api/order-cloud/sync/full-mirror-state', methods=['GET'])
def full_mirror_state():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        return jsonify({'ok': True, 'result': get_full_mirror_state()})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@order_tracking_cloud_auth_bp.route('/api/order-cloud/sync/full-mirror', methods=['POST'])
def sync_full_mirror():
    """Legacy one-request full mirror endpoint, retained for small databases."""
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        payload = _request_json_body()
        result = replace_full_mirror(
            payload.get('tables') or [],
            payload.get('snapshot_hash'),
            source_watermark=payload.get('source_watermark'),
            source_site=source_site,
            force=bool(payload.get('force', False)),
        )
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@order_tracking_cloud_auth_bp.route('/api/order-cloud/sync/full-mirror/begin', methods=['POST'])
def sync_full_mirror_begin():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        payload = _request_json_body()
        result = begin_chunked_mirror(
            payload.get('manifest') or [],
            payload.get('snapshot_hash'),
            source_watermark=payload.get('source_watermark'),
            source_site=source_site,
            force=bool(payload.get('force', False)),
        )
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@order_tracking_cloud_auth_bp.route('/api/order-cloud/sync/full-mirror/chunk', methods=['POST'])
def sync_full_mirror_chunk():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        payload = _request_json_body()
        result = append_chunk(
            payload.get('snapshot_hash'),
            payload.get('table_name'),
            payload.get('columns') or [],
            payload.get('rows') or [],
        )
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@order_tracking_cloud_auth_bp.route('/api/order-cloud/sync/full-mirror/finalize', methods=['POST'])
def sync_full_mirror_finalize():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        payload = _request_json_body()
        result = finalize_chunked_mirror(
            payload.get('manifest') or [],
            payload.get('snapshot_hash'),
            source_watermark=payload.get('source_watermark'),
            source_site=source_site,
            force=bool(payload.get('force', False)),
        )
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500
