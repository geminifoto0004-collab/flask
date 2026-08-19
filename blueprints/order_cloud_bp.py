"""Render API for ORDER -> TiDB cloud publishing."""
import hmac
import os
from functools import wraps
from flask import Blueprint, jsonify, request
from services.order_cloud_service import init_order_cloud_tables, sync_order, get_order

order_cloud_bp = Blueprint('order_cloud', __name__, url_prefix='/api/order-cloud')
_initialized = False


def _ensure_tables():
    global _initialized
    if not _initialized:
        init_order_cloud_tables()
        _initialized = True


def sync_auth_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        expected = os.environ.get('ORDER_SYNC_API_KEY', '').strip()
        supplied = request.headers.get('X-Order-Sync-Key', '').strip()
        if not expected:
            return jsonify({'ok': False, 'error': 'ORDER_SYNC_API_KEY is not configured'}), 503
        if not supplied or not hmac.compare_digest(supplied, expected):
            return jsonify({'ok': False, 'error': 'unauthorized'}), 401
        return fn(*args, **kwargs)
    return wrapped


@order_cloud_bp.route('/health', methods=['GET'])
def health():
    try:
        _ensure_tables()
        return jsonify({'ok': True, 'service': 'order-cloud', 'phase': 1})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@order_cloud_bp.route('/sync/order', methods=['POST'])
@sync_auth_required
def sync_one_order():
    try:
        _ensure_tables()
        payload = request.get_json(silent=True) or {}
        result = sync_order(payload)
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@order_cloud_bp.route('/debug/order/<path:order_number>', methods=['GET'])
@sync_auth_required
def debug_order(order_number):
    try:
        _ensure_tables()
        result = get_order(order_number)
        if result is None:
            return jsonify({'ok': False, 'error': 'not found'}), 404
        return jsonify({'ok': True, 'order': result})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500
