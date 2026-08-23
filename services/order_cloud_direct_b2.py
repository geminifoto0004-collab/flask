"""Direct private-B2 upload support for ORDER.

The local Chile Flask never receives B2 credentials.  It authenticates to Render with
ORDER_SYNC_API_KEY_CL, Render returns a short-lived S3-compatible presigned PUT URL,
and the image bytes go directly from the office PC to B2.  The existing protected
/register endpoint is still used afterwards to attach the uploaded hash to an order.
"""
from flask import jsonify, request
from botocore.exceptions import ClientError

from blueprints.b2_test_bp import (
    b2_test_bp,
    _ensure_order_cloud_tables,
    _order_cloud_auth_source,
)
from services.order_cloud_asset_service import (
    _b2_client,
    _b2_config,
    _is_not_found,
    _object_key,
    _validate_content_type,
    _validate_sha256,
)


@b2_test_bp.route('/api/order-cloud/assets/presign', methods=['POST'])
def order_cloud_asset_presign():
    """Return either `exists=true` or a short-lived direct B2 PUT URL.

    This endpoint never exposes B2 credentials.  The generated URL is restricted to one
    content-addressed object key and expires after ten minutes.
    """
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        sha256_hex = _validate_sha256(payload.get('sha256'))
        content_type = _validate_content_type(payload.get('content_type'))
        object_key = _object_key(sha256_hex, content_type)
        cfg = _b2_config()
        s3 = _b2_client(cfg)

        try:
            info = s3.head_object(Bucket=cfg['bucket_name'], Key=object_key)
            return jsonify({
                'ok': True,
                'result': {
                    'exists': True,
                    'sha256': sha256_hex,
                    'content_type': content_type,
                    'file_size': int(info.get('ContentLength') or 0),
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
                'sha256': sha256_hex,
                'content_type': content_type,
                'upload_url': upload_url,
                'expires_seconds': 600,
                'upload_mode': 'direct_b2',
            },
        })
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
