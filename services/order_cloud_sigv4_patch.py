"""Force AWS Signature V4 for all ORDER Backblaze B2 S3 clients.

Backblaze B2 S3-Compatible API accepts SigV4 only. Botocore can otherwise choose the
legacy SigV2 query format for presigned URLs on a custom endpoint, which B2 rejects as
an unauthenticated request. This module patches both the shared ORDER B2 client factory
and the direct PC->B2 presign client so PUT and GET signed URLs are always SigV4.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from services import order_cloud_multi_b2 as multi

_CLIENTS = {}


def _region_from_endpoint(endpoint):
    host = str(urlparse(str(endpoint or '')).hostname or '').lower()
    match = re.search(r'(?:^|\.)s3\.([^.]+)\.backblazeb2\.com$', host)
    if match:
        return match.group(1)
    return 'us-east-1'


def sigv4_client_for_backend(backend):
    backend = str(backend or multi.PRIMARY).strip().lower()
    cfg = multi.config_for_backend(backend, required=True)
    cache_key = (backend, cfg['endpoint'], cfg['key_id'])
    client = _CLIENTS.get(cache_key)
    if client is None:
        client = boto3.client(
            's3',
            endpoint_url=cfg['endpoint'],
            aws_access_key_id=cfg['key_id'],
            aws_secret_access_key=cfg['application_key'],
            region_name=_region_from_endpoint(cfg['endpoint']),
            config=Config(
                signature_version='s3v4',
                s3={'addressing_style': 'path'},
            ),
        )
        _CLIENTS[cache_key] = client
    return client


def validate_sigv4_presigned_url(url):
    text = str(url or '')
    if 'X-Amz-Algorithm=AWS4-HMAC-SHA256' not in text:
        raise RuntimeError('B2 presigned URL is not AWS Signature V4')
    return text


# Shared GET/HEAD/PUT client path.
multi.client_for_backend = sigv4_client_for_backend

# Direct PC->B2 presign path has its own client factory. It is imported before this
# patch from order_cloud_proxy_thumb.py, so replacing the module global here changes
# future _presigned_put() calls without touching image bytes or credentials on the PC.
try:
    from services import order_cloud_direct_multi_b2 as direct
    direct._client_for_backend = sigv4_client_for_backend

    _original_presigned_put = direct._presigned_put

    def _sigv4_presigned_put(backend, object_key, content_type, seconds=600):
        return validate_sigv4_presigned_url(
            _original_presigned_put(backend, object_key, content_type, seconds=seconds)
        )

    direct._presigned_put = _sigv4_presigned_put
except Exception:
    # Import order is controlled by order_cloud_proxy_thumb.py. Keep shared patch alive
    # even if a future deployment loads the direct module in a different order.
    pass
