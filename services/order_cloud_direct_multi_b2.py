"""Direct PC -> B2 upload signer for ORDER customer-share images.

Formal image policy:
- one local source image -> one optimized cloud object;
- image bytes always travel PC -> B2, never through Render;
- new object keys are scoped by stable TiDB customer/order/workflow ownership, never
  by a share token, so changing/revoking a share link never changes image ownership;
- an existing cloud_assets row is reused without a B2 HEAD request.

Legacy WEB/THUMB requests remain accepted during rollout, but new clients use
variant=image and never upload a second thumbnail object.
"""
from __future__ import annotations

import hashlib
import re
import threading

from flask import jsonify, request

from blueprints.b2_test_bp import (
    b2_test_bp,
    _ensure_order_cloud_tables,
    _order_cloud_auth_source,
)
from database import get_cursor, get_db_connection, get_row_dict
from services import order_cloud_asset_service as asset_service
from services.order_cloud_asset_service import (
    ALLOWED_IMAGE_TYPES,
    _object_key,
    _validate_content_type,
    _validate_sha256,
)
from services.order_cloud_direct_b2 import _thumb_object_key
from services.order_cloud_multi_b2 import (
    PRIMARY,
    SECONDARY,
    backend_ready,
    config_for_backend,
)
from services.order_cloud_multi_b2_auto import select_readable_backend

_ALLOWED_BACKENDS = {PRIMARY, SECONDARY}
_NEW_IMAGE_MAX_BYTES = 1_000_000
_LEGACY_MAX_BYTES = 15 * 1024 * 1024
_CLIENTS = {}
_CLIENTS_LOCK = threading.Lock()


def _client_for_backend(backend):
    """Reuse one boto3 client per backend instead of rebuilding it per image."""
    import boto3

    backend = str(backend or PRIMARY).strip().lower()
    cfg = config_for_backend(backend, required=True)
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(backend)
        if client is None:
            client = boto3.client(
                's3',
                endpoint_url=cfg['endpoint'],
                aws_access_key_id=cfg['key_id'],
                aws_secret_access_key=cfg['application_key'],
            )
            _CLIENTS[backend] = client
        return client


def _presigned_put(backend, object_key, content_type, seconds=600):
    cfg = config_for_backend(backend, required=True)
    return _client_for_backend(backend).generate_presigned_url(
        ClientMethod='put_object',
        Params={
            'Bucket': cfg['bucket_name'],
            'Key': object_key,
            'ContentType': content_type,
        },
        ExpiresIn=int(seconds),
        HttpMethod='PUT',
    )


def _safe_component(value, fallback):
    raw = str(value or '').strip()
    if not raw:
        return fallback
    slug = re.sub(r'[^A-Za-z0-9._-]+', '-', raw).strip('-.') or fallback
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]
    return f'{slug[:72]}-{digest}'


def _customer_namespace(customer_key):
    """Stable, non-human-readable folder derived from TiDB customer_key, never token."""
    value = str(customer_key or '').strip()
    if not value:
        raise ValueError('customer_key is required')
    return 'c_' + hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


def _scoped_object_key(customer_key, order_number, workflow_key, sha256_hex, content_type):
    content_type = _validate_content_type(content_type)
    sha256_hex = _validate_sha256(sha256_hex)
    extension = ALLOWED_IMAGE_TYPES[content_type]
    customer = _customer_namespace(customer_key)
    order = _safe_component(order_number, 'order')
    workflow = _safe_component(workflow_key, '_order') if workflow_key else '_order'
    return (
        f'customers/{customer}/orders/{order}/workflows/{workflow}/images/'
        f'{sha256_hex}{extension}'
    )


def _resolve_owner(order_number, workflow_key):
    """Resolve canonical ownership once from TiDB and validate workflow membership."""
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        order_number, customer_key, workflow_key = asset_service._resolve_order_and_workflow(
            cur, order_number, workflow_key
        )
        return order_number, str(customer_key or '').strip(), workflow_key
    finally:
        conn.close()


def _existing_asset(order_number, workflow_key, sha256_hex):
    """Trust registered metadata for reuse; deliberately do not HEAD B2 per image."""
    asset_key = asset_service._asset_key(order_number, workflow_key, sha256_hex)
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, sha256,
                      object_key, content_type, file_size, storage_backend
               FROM cloud_assets
               WHERE asset_key=? AND active=TRUE LIMIT 1""",
            (asset_key,),
        )
        row = cur.fetchone()
        return get_row_dict(row, cur) if row else None
    finally:
        conn.close()


def _upsert_registered_asset(order_number, customer_key, workflow_key, sha256_hex,
                             object_key, content_type, file_size, source_site,
                             storage_backend):
    """Fast metadata upsert for the direct path; no schema migration inside requests."""
    asset_key = asset_service._asset_key(order_number, workflow_key, sha256_hex)
    display_name = f'Imagen {order_number}'
    source_site = str(source_site or '').strip().upper()[:16] or None

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute('SELECT asset_key FROM cloud_assets WHERE asset_key=?', (asset_key,))
        values = (
            customer_key,
            order_number,
            workflow_key,
            sha256_hex,
            object_key,
            content_type,
            int(file_size),
            display_name,
            source_site,
            storage_backend,
            asset_key,
        )
        if cur.fetchone():
            cur.execute(
                """UPDATE cloud_assets
                   SET customer_key=?, order_number=?, workflow_key=?, asset_type='IMAGE',
                       sha256=?, object_key=?, content_type=?, file_size=?, display_name=?,
                       source_site=?, storage_backend=?, active=TRUE,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE asset_key=?""",
                values,
            )
        else:
            cur.execute(
                """INSERT INTO cloud_assets
                   (customer_key, order_number, workflow_key, asset_type, sha256,
                    object_key, content_type, file_size, display_name, source_site,
                    storage_backend, asset_key)
                   VALUES (?, ?, ?, 'IMAGE', ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        'asset_key': asset_key,
        'customer_key': customer_key,
        'order_number': order_number,
        'workflow_key': workflow_key,
        'asset_type': 'IMAGE',
        'sha256': sha256_hex,
        'object_key': object_key,
        'content_type': content_type,
        'file_size': int(file_size),
        'display_name': display_name,
        'source_site': source_site,
        'storage_backend': storage_backend,
    }


@b2_test_bp.route('/api/order-cloud/assets/direct-presign', methods=['POST'])
def order_cloud_asset_direct_presign():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        variant = str(payload.get('variant') or 'image').strip().lower()
        if variant not in {'image', 'web', 'thumb'}:
            raise ValueError('variant must be image, web or thumb')

        byte_sha256 = _validate_sha256(payload.get('sha256'))
        selection = None

        # Legacy two-object client support during rollout only.
        if variant == 'thumb':
            asset_sha256 = _validate_sha256(payload.get('asset_sha256'))
            content_type = 'image/jpeg'
            object_key = _thumb_object_key(asset_sha256)
            from services.order_cloud_multi_b2 import storage_backend_for_sha
            backend = storage_backend_for_sha(asset_sha256)
            if backend not in _ALLOWED_BACKENDS or not backend_ready(backend):
                raise RuntimeError('thumbnail B2 backend is not configured')
            upload_url = _presigned_put(backend, object_key, content_type, seconds=600)
            return jsonify({'ok': True, 'result': {
                'exists': False,
                'variant': variant,
                'sha256': byte_sha256,
                'asset_sha256': asset_sha256,
                'content_type': content_type,
                'object_key': object_key,
                'storage_backend': backend,
                'upload_url': upload_url,
                'expires_seconds': 600,
                'upload_mode': 'legacy_thumb_pc_direct_b2',
                'render_receives_image_bytes': False,
                'b2_head_calls_per_image': 0,
            }})

        asset_sha256 = byte_sha256
        content_type = _validate_content_type(payload.get('content_type'))
        order_number = str(payload.get('order_number') or '').strip()
        workflow_key = str(payload.get('workflow_key') or '').strip() or None

        # New formal client: owner is known before upload, enabling token-independent
        # folders and metadata-only reuse checks.
        if order_number:
            order_number, customer_key, workflow_key = _resolve_owner(order_number, workflow_key)
            existing = _existing_asset(order_number, workflow_key, asset_sha256)
            if existing:
                backend = str(existing.get('storage_backend') or PRIMARY).strip().lower()
                if backend in _ALLOWED_BACKENDS and backend_ready(backend) and existing.get('object_key'):
                    return jsonify({'ok': True, 'result': {
                        'exists': True,
                        'reused': True,
                        'variant': 'image',
                        'sha256': asset_sha256,
                        'asset_sha256': asset_sha256,
                        'content_type': existing.get('content_type') or content_type,
                        'file_size': int(existing.get('file_size') or 0),
                        'object_key': existing.get('object_key'),
                        'storage_backend': backend,
                        'asset_key': existing.get('asset_key'),
                        'upload_mode': 'tidb_metadata_reuse_no_b2_head',
                        'render_receives_image_bytes': False,
                        'b2_head_calls_per_image': 0,
                    }})

            object_key = _scoped_object_key(
                customer_key, order_number, workflow_key, asset_sha256, content_type
            )
            try:
                file_size = int(payload.get('file_size') or 0)
            except Exception:
                file_size = 0
            if file_size and file_size > _NEW_IMAGE_MAX_BYTES:
                raise ValueError('optimized image exceeds 1,000,000-byte policy')
        else:
            # Backward-compatible direct client from commit 32d32da. It is kept so a
            # Render deploy does not break an office PC that has not been swapped yet.
            customer_key = ''
            object_key = _object_key(asset_sha256, content_type)

        backend, selection = select_readable_backend(force_probe=False)
        upload_url = _presigned_put(backend, object_key, content_type, seconds=600)
        result = {
            'exists': False,
            'reused': False,
            'variant': 'image',
            'sha256': byte_sha256,
            'asset_sha256': asset_sha256,
            'content_type': content_type,
            'object_key': object_key,
            'storage_backend': backend,
            'upload_url': upload_url,
            'expires_seconds': 600,
            'upload_mode': 'pc_direct_b2_single_image',
            'render_receives_image_bytes': False,
            'b2_head_calls_per_image': 0,
        }
        if customer_key:
            result['customer_namespace'] = _customer_namespace(customer_key)
        if selection:
            result['backend_selection'] = {
                'selected': selection.get('selected'),
                'primary_status': (selection.get('primary') or {}).get('status'),
                'primary_cached': (selection.get('primary') or {}).get('cached'),
                'secondary_status': (selection.get('secondary') or {}).get('status') if selection.get('secondary') else None,
                'secondary_cached': (selection.get('secondary') or {}).get('cached') if selection.get('secondary') else None,
            }
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500


@b2_test_bp.route('/api/order-cloud/assets/direct-register', methods=['POST'])
def order_cloud_asset_direct_register():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        order_number = str(payload.get('order_number') or '').strip()
        workflow_key = str(payload.get('workflow_key') or '').strip() or None
        sha256_hex = _validate_sha256(payload.get('sha256'))
        content_type = _validate_content_type(payload.get('content_type'))
        backend = str(payload.get('storage_backend') or '').strip().lower()
        if backend not in _ALLOWED_BACKENDS or not backend_ready(backend):
            raise ValueError('storage_backend is invalid or not configured')
        try:
            file_size = int(payload.get('file_size') or 0)
        except Exception:
            raise ValueError('file_size must be an integer')
        if file_size <= 0 or file_size > _LEGACY_MAX_BYTES:
            raise ValueError('file_size is outside the allowed range')

        order_number, customer_key, workflow_key = _resolve_owner(order_number, workflow_key)
        scoped_object_key = _scoped_object_key(
            customer_key, order_number, workflow_key, sha256_hex, content_type
        )
        legacy_object_key = _object_key(sha256_hex, content_type)
        supplied_object_key = str(payload.get('object_key') or '').strip()
        object_key = supplied_object_key or scoped_object_key
        if object_key not in {scoped_object_key, legacy_object_key}:
            raise ValueError('object_key does not match canonical owner/sha256/content_type')
        if object_key == scoped_object_key and file_size > _NEW_IMAGE_MAX_BYTES:
            raise ValueError('optimized image exceeds 1,000,000-byte policy')

        result = _upsert_registered_asset(
            order_number,
            customer_key,
            workflow_key,
            sha256_hex,
            object_key,
            content_type,
            file_size,
            source_site,
            backend,
        )
        result['upload_mode'] = (
            'pc_direct_b2_single_image_registered'
            if object_key == scoped_object_key
            else 'pc_direct_b2_legacy_registered'
        )
        result['render_received_image_bytes'] = False
        result['b2_head_calls'] = 0
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
