"""Health-aware reuse guard for ORDER direct B2 uploads.

Adds one important recovery control: the office uploader may send ``avoid_backend``
after repeated direct-PUT failures. Render then signs the other readable B2 backend
without proxying any image bytes.
"""
from __future__ import annotations

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from services.order_cloud_asset_service import _validate_content_type, _validate_sha256
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY, backend_ready
from services.order_cloud_multi_b2_auto import probe_backend_class_b, select_readable_backend
from services import order_cloud_direct_multi_b2 as direct

_ALLOWED = {PRIMARY, SECONDARY}


def _selection_avoiding(avoid_backend):
    avoid_backend = str(avoid_backend or '').strip().lower()
    if avoid_backend not in _ALLOWED:
        return select_readable_backend(force_probe=False)

    wanted = SECONDARY if avoid_backend == PRIMARY else PRIMARY
    wanted_health = probe_backend_class_b(wanted, force=False)
    avoided_health = probe_backend_class_b(avoid_backend, force=False)
    if wanted_health.get('class_b_ok'):
        selection = {'selected': wanted, 'primary': None, 'secondary': None, 'avoided': avoid_backend}
        selection['primary'] = wanted_health if wanted == PRIMARY else avoided_health
        selection['secondary'] = wanted_health if wanted == SECONDARY else avoided_health
        return wanted, selection
    raise RuntimeError(
        f'alternate B2 backend is not readable after avoiding {avoid_backend}: '
        f'{wanted}={wanted_health.get("status")} HTTP={wanted_health.get("http_status")}'
    )


@b2_test_bp.before_app_request
def _health_aware_direct_presign():
    if request.method != 'POST' or request.path != '/api/order-cloud/assets/direct-presign':
        return None

    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True) or {}
    variant = str(payload.get('variant') or 'image').strip().lower()
    if variant != 'image':
        return None

    try:
        _ensure_order_cloud_tables()
        sha256_hex = _validate_sha256(payload.get('sha256'))
        content_type = _validate_content_type(payload.get('content_type'))
        order_number = str(payload.get('order_number') or '').strip()
        workflow_key = str(payload.get('workflow_key') or '').strip() or None
        avoid_backend = str(payload.get('avoid_backend') or '').strip().lower()
        if avoid_backend not in _ALLOWED:
            avoid_backend = ''
        if not order_number:
            return None

        try:
            file_size = int(payload.get('file_size') or 0)
        except Exception:
            file_size = 0
        if file_size and file_size > direct._NEW_IMAGE_MAX_BYTES:
            raise ValueError('optimized image exceeds 1,000,000-byte policy')

        order_number, customer_key, workflow_key = direct._resolve_owner(order_number, workflow_key)
        existing = direct._existing_asset(order_number, workflow_key, sha256_hex)
        existing_health = None
        if existing:
            existing_backend = str(existing.get('storage_backend') or PRIMARY).strip().lower()
            if (
                existing_backend in _ALLOWED
                and existing_backend != avoid_backend
                and backend_ready(existing_backend)
                and existing.get('object_key')
            ):
                existing_health = probe_backend_class_b(existing_backend, force=False)
                if existing_health.get('class_b_ok'):
                    return jsonify({'ok': True, 'result': {
                        'exists': True,
                        'reused': True,
                        'variant': 'image',
                        'sha256': sha256_hex,
                        'asset_sha256': sha256_hex,
                        'content_type': existing.get('content_type') or content_type,
                        'file_size': int(existing.get('file_size') or 0),
                        'object_key': existing.get('object_key'),
                        'storage_backend': existing_backend,
                        'asset_key': existing.get('asset_key'),
                        'upload_mode': 'tidb_reuse_health_checked_cached_probe',
                        'render_receives_image_bytes': False,
                        'b2_head_calls_per_image': 0,
                        'backend_selection': {
                            'selected': existing_backend,
                            'existing_backend_status': existing_health.get('status'),
                            'existing_backend_cached': existing_health.get('cached'),
                            'avoided_backend': avoid_backend or None,
                        },
                    }})

        object_key = direct._scoped_object_key(
            customer_key, order_number, workflow_key, sha256_hex, content_type
        )
        backend, selection = _selection_avoiding(avoid_backend)
        upload_url = direct._presigned_put(backend, object_key, content_type, seconds=600)
        result = {
            'exists': False,
            'reused': False,
            'variant': 'image',
            'sha256': sha256_hex,
            'asset_sha256': sha256_hex,
            'content_type': content_type,
            'object_key': object_key,
            'storage_backend': backend,
            'upload_url': upload_url,
            'expires_seconds': 600,
            'upload_mode': 'pc_direct_b2_health_aware_failover',
            'render_receives_image_bytes': False,
            'b2_head_calls_per_image': 0,
            'customer_namespace': direct._customer_namespace(customer_key),
            'backend_selection': {
                'selected': selection.get('selected'),
                'primary_status': (selection.get('primary') or {}).get('status'),
                'primary_cached': (selection.get('primary') or {}).get('cached'),
                'secondary_status': (selection.get('secondary') or {}).get('status') if selection.get('secondary') else None,
                'secondary_cached': (selection.get('secondary') or {}).get('cached') if selection.get('secondary') else None,
                'existing_backend_status': (existing_health or {}).get('status'),
                'avoided_backend': avoid_backend or None,
            },
        }
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
