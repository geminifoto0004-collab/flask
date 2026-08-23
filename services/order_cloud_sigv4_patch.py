"""Force AWS Signature V4 for all ORDER Backblaze B2 S3 clients.

Backblaze B2 S3-Compatible API accepts SigV4 only. Botocore can otherwise choose the
legacy SigV2 query format for presigned URLs on a custom endpoint, which B2 rejects as
an unauthenticated request. This module patches the shared ORDER B2 client factory so
both presigned PUT and presigned GET URLs use SigV4.
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
    # Compatibility fallback for any S3-compatible custom endpoint.
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


# Runtime patch: functions already defined in order_cloud_multi_b2 resolve this global
# at call time, so presigned GETs and future shared B2 calls also use SigV4.
multi.client_for_backend = sigv4_client_for_backend
