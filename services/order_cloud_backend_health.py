"""Protected health status for ORDER dual-B2 direct uploads.

Used by the office PC before a publish job so failures are visible immediately in the
share-management UI instead of looking like a frozen 0/? progress bar. This endpoint
returns only health/status metadata; no credential, bucket name or signed URL is exposed.
"""
from __future__ import annotations

from flask import jsonify

from blueprints.b2_test_bp import b2_test_bp, _order_cloud_auth_source
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY
from services.order_cloud_multi_b2_auto import probe_backend_class_b


def _public_health(item):
    item = dict(item or {})
    return {
        'backend': item.get('backend'),
        'configured': bool(item.get('configured')),
        'class_b_ok': bool(item.get('class_b_ok')),
        'status': item.get('status'),
        'http_status': item.get('http_status'),
        'aws_code': item.get('aws_code'),
        'error_type': item.get('error_type'),
        'error': item.get('error'),
        'cached': item.get('cached'),
    }


@b2_test_bp.route('/api/order-cloud/assets/backend-health', methods=['GET'])
def order_cloud_backend_health():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    primary = probe_backend_class_b(PRIMARY, force=False)
    if primary.get('class_b_ok'):
        selected = PRIMARY
        secondary = {'backend': SECONDARY, 'configured': None, 'class_b_ok': None, 'status': 'not_checked'}
        ok = True
    else:
        secondary = probe_backend_class_b(SECONDARY, force=False)
        selected = SECONDARY if secondary.get('class_b_ok') else None
        ok = bool(selected)

    result = {
        'selected': selected,
        'primary': _public_health(primary),
        'secondary': _public_health(secondary),
    }
    if ok:
        return jsonify({'ok': True, 'result': result})

    return jsonify({
        'ok': False,
        'error': (
            'No readable B2 backend is available for ORDER images. '
            f"primary={result['primary'].get('status')} HTTP={result['primary'].get('http_status')}; "
            f"secondary={result['secondary'].get('status')} HTTP={result['secondary'].get('http_status')}"
        ),
        'result': result,
        'error_type': 'B2Unavailable',
    }), 503
