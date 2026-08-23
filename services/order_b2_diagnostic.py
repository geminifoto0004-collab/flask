"""Authenticated B2 diagnostics for ORDER customer-share media.

This module is intentionally isolated from the production upload path.  It exposes one
protected endpoint that reports which Render B2 settings are present (without exposing
secrets) and performs a tiny write/read/delete probe under the same order-cloud/images
prefix used by production images.
"""
import os
import uuid

from botocore.exceptions import ClientError
from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _order_cloud_auth_source
from services.order_cloud_asset_service import _b2_client, _b2_config


def _safe_error(exc):
    data = {
        "ok": False,
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
    if isinstance(exc, ClientError):
        response = exc.response or {}
        err = response.get("Error") or {}
        meta = response.get("ResponseMetadata") or {}
        data.update({
            "http_status": meta.get("HTTPStatusCode"),
            "aws_code": err.get("Code"),
            "aws_message": err.get("Message"),
            "request_id": meta.get("RequestId"),
        })
    return data


def _step(fn, expected=None):
    try:
        value = fn()
        result = {"ok": True}
        if expected:
            result["expected"] = expected
        if isinstance(value, dict):
            result.update(value)
        return result
    except Exception as exc:
        result = _safe_error(exc)
        if expected:
            result["expected"] = expected
        return result


@b2_test_bp.route('/api/order-cloud/b2/diagnose', methods=['POST'])
def order_cloud_b2_diagnose():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    env_key_id = (os.environ.get('B2_KEY_ID') or '').strip()
    env_app_key = (os.environ.get('B2_APPLICATION_KEY') or '').strip()
    env_bucket = (os.environ.get('B2_BUCKET_NAME') or '').strip()
    env_endpoint = (os.environ.get('B2_ENDPOINT') or '').strip().rstrip('/')

    report = {
        "ok": True,
        "config": {
            "key_id_present": bool(env_key_id),
            "key_id_suffix": env_key_id[-4:] if env_key_id else None,
            "application_key_present": bool(env_app_key),
            "bucket_name": env_bucket or None,
            "endpoint": env_endpoint or None,
        },
        "tests": {},
    }

    try:
        cfg = _b2_config()
        s3 = _b2_client(cfg)
        report["tests"]["client_create"] = {"ok": True}
    except Exception as exc:
        report["ok"] = False
        report["tests"]["client_create"] = _safe_error(exc)
        return jsonify(report), 200

    # Use the exact production image prefix so an application-key prefix restriction is
    # exercised the same way as customer images.  The object is tiny and removed when
    # delete permission is available.
    diag_key = f"order-cloud/images/__diagnostics__/{uuid.uuid4().hex}.txt"
    body = b"ORDER B2 diagnostic probe\n"

    # On a unique not-yet-created key, working read/head permission should normally
    # produce a 404/NotFound.  A 403 here is the clearest signal that HEAD is forbidden.
    try:
        s3.head_object(Bucket=cfg['bucket_name'], Key=diag_key)
        report["tests"]["head_missing_before_put"] = {
            "ok": True,
            "unexpected": "object already existed",
        }
    except ClientError as exc:
        response = exc.response or {}
        err = response.get('Error') or {}
        meta = response.get('ResponseMetadata') or {}
        status = meta.get('HTTPStatusCode')
        code = str(err.get('Code') or '')
        if status == 404 or code in {'404', 'NoSuchKey', 'NotFound'}:
            report["tests"]["head_missing_before_put"] = {
                "ok": True,
                "expected": "404 means HEAD/read permission works on a missing key",
                "http_status": status,
                "aws_code": code,
            }
        else:
            report["tests"]["head_missing_before_put"] = _safe_error(exc)
    except Exception as exc:
        report["tests"]["head_missing_before_put"] = _safe_error(exc)

    report["tests"]["put_object"] = _step(
        lambda: s3.put_object(
            Bucket=cfg['bucket_name'],
            Key=diag_key,
            Body=body,
            ContentType='text/plain',
            Metadata={'purpose': 'order-b2-diagnostic'},
        ),
        expected="requires write permission",
    )

    if report["tests"]["put_object"].get("ok"):
        report["tests"]["head_after_put"] = _step(
            lambda: {
                "content_length": int(
                    s3.head_object(Bucket=cfg['bucket_name'], Key=diag_key).get('ContentLength') or 0
                )
            },
            expected="requires HEAD/read permission",
        )

        def _get_probe():
            obj = s3.get_object(Bucket=cfg['bucket_name'], Key=diag_key)
            data = obj['Body'].read()
            return {"bytes": len(data), "matches": data == body}

        report["tests"]["get_after_put"] = _step(
            _get_probe,
            expected="requires read permission",
        )
        report["tests"]["delete_object"] = _step(
            lambda: s3.delete_object(Bucket=cfg['bucket_name'], Key=diag_key),
            expected="requires delete permission",
        )
    else:
        report["tests"]["head_after_put"] = {"ok": False, "skipped": True}
        report["tests"]["get_after_put"] = {"ok": False, "skipped": True}
        report["tests"]["delete_object"] = {"ok": False, "skipped": True}

    important = [
        report["tests"].get("put_object", {}).get("ok"),
        report["tests"].get("head_after_put", {}).get("ok"),
        report["tests"].get("get_after_put", {}).get("ok"),
    ]
    report["ok"] = all(important)
    report["probe_object_key"] = diag_key if not report["tests"].get("delete_object", {}).get("ok") else None
    return jsonify(report), 200
