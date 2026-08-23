"""Direct private-B2 upload support for ORDER.

The local Chile Flask never receives B2 credentials. It authenticates to Render with
ORDER_SYNC_API_KEY_CL; Render returns short-lived S3-compatible presigned PUT URLs and
image bytes go directly from the office PC to B2.

Current customer-share media policy:
- WEB: colour-managed, max 2560 px, JPEG Q95 / 4:4:4. This is the registered cloud asset.
- THUMB: max 480 px, JPEG Q85 / 4:4:4, keyed by the WEB asset SHA.
- ORIGINAL: never uploaded by the current client.

Old B2 objects are intentionally not deleted when metadata is pruned because a SHA
object can be reused by another order/share.
"""
from flask import jsonify, request
from botocore.exceptions import ClientError

from blueprints.b2_test_bp import (
    b2_test_bp,
    _ensure_order_cloud_tables,
    _order_cloud_auth_source,
)
from database import get_cursor, get_db_connection
from services.order_cloud_asset_service import (
    _b2_client,
    _b2_config,
    _is_not_found,
    _object_key,
    _validate_content_type,
    _validate_sha256,
)


def _thumb_object_key(asset_sha256):
    asset_sha256 = _validate_sha256(asset_sha256)
    return f"order-cloud/thumbs/{asset_sha256[:2]}/{asset_sha256}.jpg"


@b2_test_bp.route('/api/order-cloud/assets/presign', methods=['POST'])
def order_cloud_asset_presign():
    """Return `exists=true` or a short-lived direct B2 PUT URL.

    Backward compatibility: requests without `variant` are treated as WEB and keep
    accepting JPEG/PNG/WEBP. New two-tier clients send variant=web or variant=thumb.
    THUMB object names are derived from `asset_sha256` (the WEB image SHA), while the
    request `sha256` is the thumbnail byte digest used only for diagnostics.
    """
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        variant = str(payload.get('variant') or 'web').strip().lower()
        if variant not in {'web', 'thumb'}:
            raise ValueError('variant must be web or thumb')

        byte_sha256 = _validate_sha256(payload.get('sha256'))
        cfg = _b2_config()
        s3 = _b2_client(cfg)

        if variant == 'thumb':
            asset_sha256 = _validate_sha256(payload.get('asset_sha256'))
            content_type = 'image/jpeg'
            object_key = _thumb_object_key(asset_sha256)
        else:
            asset_sha256 = byte_sha256
            content_type = _validate_content_type(payload.get('content_type'))
            object_key = _object_key(asset_sha256, content_type)

        try:
            info = s3.head_object(Bucket=cfg['bucket_name'], Key=object_key)
            return jsonify({
                'ok': True,
                'result': {
                    'exists': True,
                    'variant': variant,
                    'sha256': byte_sha256,
                    'asset_sha256': asset_sha256,
                    'content_type': content_type,
                    'file_size': int(info.get('ContentLength') or 0),
                    'object_key': object_key,
                    'upload_mode': 'direct_b2',
                },
            })
        except ClientError as exc:
            if not _is_not_found(exc):
                raise

        upload_url = s3.generate_presigned_url(
            ClientMethod='put_object',
            Params={
                'Bucket': cfg['bucket_name'],
                'Key': object_key,
                'ContentType': content_type,
            },
            ExpiresIn=600,
            HttpMethod='PUT',
        )
        return jsonify({
            'ok': True,
            'result': {
                'exists': False,
                'variant': variant,
                'sha256': byte_sha256,
                'asset_sha256': asset_sha256,
                'content_type': content_type,
                'object_key': object_key,
                'upload_url': upload_url,
                'expires_seconds': 600,
                'upload_mode': 'direct_b2',
            },
        })
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500


@b2_test_bp.route('/api/order-cloud/assets/prune', methods=['POST'])
def order_cloud_asset_prune():
    """Remove stale asset *metadata* for one order after a complete local image scan.

    The local client sends the WEB SHA set that currently belongs to the order. Any old
    cloud_assets rows (including rows created when originals were uploaded) are removed
    from TiDB so they no longer appear in customer galleries. Physical B2 objects are
    kept for content-addressed deduplication and are never deleted here.
    """
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        order_number = str(payload.get('order_number') or '').strip()
        if not order_number:
            raise ValueError('order_number is required')
        raw_allowed = payload.get('allowed_sha256') or []
        if not isinstance(raw_allowed, list):
            raise ValueError('allowed_sha256 must be a list')
        allowed = sorted({_validate_sha256(value) for value in raw_allowed if str(value or '').strip()})

        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute('SELECT order_number FROM cloud_orders WHERE order_number=? AND active=TRUE LIMIT 1', (order_number,))
            if not cur.fetchone():
                raise ValueError('order not found')
            if allowed:
                placeholders = ','.join(['?'] * len(allowed))
                cur.execute(
                    f'DELETE FROM cloud_assets WHERE order_number=? AND sha256 NOT IN ({placeholders})',
                    tuple([order_number] + allowed),
                )
            else:
                cur.execute('DELETE FROM cloud_assets WHERE order_number=?', (order_number,))
            deleted = int(getattr(cur, 'rowcount', 0) or 0)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return jsonify({'ok': True, 'result': {'order_number': order_number, 'deleted_metadata_rows': deleted, 'kept_sha256': len(allowed)}})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
