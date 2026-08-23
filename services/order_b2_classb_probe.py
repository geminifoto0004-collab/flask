"""Minimal protected Class-B health probe for both ORDER B2 backends.

Each configured backend receives exactly one HEAD request against a unique missing
object key. A healthy account with read permission should answer 404/NoSuchKey.
A 403 carrying a cap-exceeded message exposes the Backblaze daily Class-B/download
limit without doing PUT/GET loops.
"""
from __future__ import annotations

import uuid

from botocore.exceptions import ClientError
from flask import jsonify

from blueprints.b2_test_bp import b2_test_bp, _order_cloud_auth_source
from services.order_cloud_multi_b2 import (
    PRIMARY,
    SECONDARY,
    backend_ready,
    client_for_backend,
    config_for_backend,
)


def _probe_backend(backend):
    if not backend_ready(backend):
        return {
            'configured': False,
            'class_b_ok': None,
            'status': 'not_configured',
        }

    cfg = config_for_backend(backend, required=True)
    key = f"order-cloud/images/__classb_probe__/{uuid.uuid4().hex}.jpg"
    result = {
        'configured': True,
        'backend': backend,
        'bucket_name': cfg.get('bucket_name'),
        'endpoint': cfg.get('endpoint'),
        'key_id_suffix': (cfg.get('key_id') or '')[-4:] or None,
        'class_b_requests_used': 1,
    }

    try:
        client_for_backend(backend).head_object(Bucket=cfg['bucket_name'], Key=key)
        # A UUID key should not already exist, but a successful HEAD still proves
        # Class-B/read access is currently available.
        result.update({
            'class_b_ok': True,
            'status': 'ok',
            'http_status': 200,
            'note': 'HEAD succeeded on unique probe key',
        })
        return result
    except ClientError as exc:
        response = exc.response or {}
        err = response.get('Error') or {}
        meta = response.get('ResponseMetadata') or {}
        status = meta.get('HTTPStatusCode')
        code = str(err.get('Code') or '')
        message = str(err.get('Message') or '')
        low = (code + ' ' + message).lower()

        if status == 404 or code in {'404', 'NoSuchKey', 'NotFound'}:
            result.update({
                'class_b_ok': True,
                'status': 'ok',
                'http_status': status,
                'aws_code': code,
                'note': '404 on missing key means HEAD/Class-B access works',
            })
            return result

        cap_exceeded = any(token in low for token in (
            'cap exceeded',
            'transaction cap',
            'class b',
            'download bandwidth',
        ))
        result.update({
            'class_b_ok': False,
            'status': 'cap_exceeded' if cap_exceeded else 'forbidden_or_error',
            'http_status': status,
            'aws_code': code or None,
            'aws_message': message or None,
            'request_id': meta.get('RequestId'),
        })
        return result
    except Exception as exc:
        result.update({
            'class_b_ok': False,
            'status': 'error',
            'error_type': type(exc).__name__,
            'error': str(exc),
        })
        return result


@b2_test_bp.route('/api/order-cloud/b2/class-b', methods=['POST'])
def order_cloud_b2_class_b_probe():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    primary = _probe_backend(PRIMARY)
    secondary = _probe_backend(SECONDARY)

    available = [x for x in (primary, secondary) if x.get('configured')]
    healthy = [x.get('backend') for x in available if x.get('class_b_ok') is True]
    blocked = [x.get('backend') for x in available if x.get('class_b_ok') is False]

    return jsonify({
        'ok': bool(available) and not blocked,
        'healthy_backends': healthy,
        'blocked_backends': blocked,
        'backends': {
            PRIMARY: primary,
            SECONDARY: secondary,
        },
        'total_class_b_requests_used': len(available),
    }), 200
