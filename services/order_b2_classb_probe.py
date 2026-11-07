"""V287: admin-paired, cooldown-limited B2 Class-B probe.

One explicit HEAD to a random nonexistent object per configured backend.
No LIST, GET, PUT, TiDB reads/writes, or customer object checks.

Safety: ORDER=1 is only a feature switch, NOT authentication. This endpoint
also requires the existing admin-issued desktop sync grant. A 15-minute,
process-local cooldown applies across COMPANY and HOME. Render currently
operates a single Gunicorn instance/worker; multiple workers would need a
shared lock before claiming an account-wide bound.
"""
from __future__ import annotations

import math
import threading
import time
import uuid

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _order_cloud_auth_source
from services.order_b2_metrics import instrument_client
from services.order_cloud_multi_b2 import (
    PRIMARY, SECONDARY, backend_ready, config_for_backend,
)

_PROBE_LOCK = threading.Lock()
_LAST_PROBE_AT = 0.0
_LAST_RESULT = None
_COOLDOWN_SECONDS = 900


def _one_shot_client(backend, cfg):
    """Disable SDK automatic retry so one logical HEAD means <=1 HTTP attempt."""
    client = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["key_id"],
        aws_secret_access_key=cfg["application_key"],
        config=BotoConfig(
            connect_timeout=3, read_timeout=5,
            retries={"total_max_attempts": 1},
            signature_version="s3v4",
        ),
    )
    return instrument_client(client, backend=backend, component="admin_b2_probe")


def _probe_backend(backend):
    if not backend_ready(backend):
        return {
            "backend": backend, "configured": False, "status": "not_configured",
            "class_b_ok": None, "head_requests": 0,
        }

    cfg = config_for_backend(backend, required=True)
    key = "order-cloud/images/__classb_probe__/" + uuid.uuid4().hex + ".probe"
    result = {
        "backend": backend, "configured": True,
        "class_b_ok": False, "head_requests": 1,
    }
    try:
        _one_shot_client(backend, cfg).head_object(Bucket=cfg["bucket_name"], Key=key)
        result.update(status="ok", class_b_ok=True, http_status=200)
        return result
    except ClientError as exc:
        response = getattr(exc, "response", None) or {}
        err = response.get("Error") or {}
        meta = response.get("ResponseMetadata") or {}
        http = meta.get("HTTPStatusCode")
        code = str(err.get("Code") or "")
        msg = str(err.get("Message") or "")
        low = (code + " " + msg).lower().replace("_", " ")
        if http == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            result.update(status="ok", class_b_ok=True, http_status=404)
        elif http == 403 and any(token in low for token in (
            "cap exceeded", "transaction cap", "class b",
            "download bandwidth", "rate limit",
        )):
            result.update(status="cap_exceeded", http_status=403,
                          retry_policy="pause_until_cap_reset_or_increase")
        elif http == 403:
            result.update(status="access_denied", http_status=403)
        else:
            result.update(status="b2_error", http_status=http if isinstance(http, int) else None)
        return result
    except Exception as exc:
        # Never include exception text, signed URLs, bucket names or secrets.
        result.update(status="network_error", error_type=type(exc).__name__)
        return result


def _read_or_run_probe(now=None):
    """Serialize tests and cache the result for both local offices."""
    global _LAST_RESULT, _LAST_PROBE_AT
    with _PROBE_LOCK:
        current = time.monotonic() if now is None else float(now)
        if _LAST_RESULT is not None and current - _LAST_PROBE_AT < _COOLDOWN_SECONDS:
            result = dict(_LAST_RESULT)
            result["cached"] = True
            result["retry_after_seconds"] = max(
                1, math.ceil(_COOLDOWN_SECONDS - (current - _LAST_PROBE_AT))
            )
            result["head_requests_this_call"] = 0
            return result

        # Reserve the cooldown before making requests; an exception must not
        # create an accidental immediate retry loop.
        _LAST_PROBE_AT = current
        _LAST_RESULT = {
            "status": "unavailable", "backends": {}, "head_requests_this_call": 0,
            "max_backend_checks": 2, "cooldown_seconds": _COOLDOWN_SECONDS,
        }
        rows = {}
        for backend in (PRIMARY, SECONDARY):
            try:
                rows[backend] = _probe_backend(backend)
            except Exception as exc:
                rows[backend] = {
                    "backend": backend, "status": "probe_error",
                    "class_b_ok": False, "error_type": type(exc).__name__,
                    "head_requests": 0,
                }
        requested = sum(int(x.get("head_requests") or 0) for x in rows.values())
        statuses = [v["status"] for v in rows.values() if v.get("configured")]
        status = "not_configured" if not statuses else (
            "healthy" if all(s == "ok" for s in statuses) else "attention"
        )
        _LAST_RESULT = {
            "status": status, "backends": rows, "cached": False,
            "head_requests_this_call": requested,
            "max_backend_checks": 2, "cooldown_seconds": _COOLDOWN_SECONDS,
            "retry_after_seconds": _COOLDOWN_SECONDS,
            "measurement_scope": "render_only_boto3_head",
        }
        return dict(_LAST_RESULT)


@b2_test_bp.route("/api/order-cloud/b2/class-b", methods=["POST"])
def order_cloud_b2_class_b_probe():
    _, gate_error = _order_cloud_auth_source()
    if gate_error:
        return gate_error

    # ORDER mode can be accessed by public browsers. Require the separately
    # administrator-issued, signed desktop repair scope before any B2 request.
    from services.order_desktop_grant import authorized
    if not authorized("replicas:verify-repair"):
        return jsonify(ok=False, error="desktop_sync_grant_required"), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("action") != "probe":
        return jsonify(ok=False, error="explicit_probe_action_required"), 400
    result = _read_or_run_probe()
    response = jsonify(ok=True, result=result)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Retry-After"] = str(result["retry_after_seconds"])
    return response
