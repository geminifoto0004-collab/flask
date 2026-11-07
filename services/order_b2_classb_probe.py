"""Owner-only, opt-in, single-run B2 Class-B probe for ORDER V287.

POST makes at most one HTTP HEAD send attempt per configured backend by using
botocore with retries disabled. No object write, GET, LIST, DELETE or TiDB access.
A unique nonexistent key receives HTTP 404 when HEAD access works.

Security: default-off flag + independent 32+ character shared token in an HTTP
header; an exclusive per-instance file prevents concurrent/repeated POSTs.
This one-use guard is per Render filesystem/instance, NOT a global distributed
quota across replicas or future deployments.
"""
from __future__ import annotations

import hmac
import json
import os
import tempfile
import time
import uuid

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp
from services.order_b2_metrics import activity_context, instrument_client, snapshot
from services.order_cloud_multi_b2 import (
    PRIMARY,
    SECONDARY,
    backend_ready,
    client_for_backend,
    config_for_backend,
)

_DIAG_PATH = os.path.join(tempfile.gettempdir(), "order_b2_v287_step4_one_shot.json")
_TOKEN_HEADER = "X-ORDER-B2-Diag-Token"


def _probe_backend(backend, client_factory=None):
    """Inspect an absent object using exactly one SDK call (and no object writes).

    Production passes the explicitly no-retry client factory; optional default
    preserves the prior offline contract and is not used by the public route.
    """
    if not backend_ready(backend):
        return {"configured": False, "class_b_ok": None, "status": "not_configured"}

    cfg = config_for_backend(backend, required=True)
    key = f"order-cloud/images/__classb_probe__/{uuid.uuid4().hex}.jpg"
    result = {"configured": True, "backend": backend}
    try:
        (client_factory or client_for_backend)(backend).head_object(
            Bucket=cfg["bucket_name"], Key=key,
        )
        result.update({
            "class_b_ok": True, "status": "ok", "http_status": 200,
            "note": "HEAD succeeded on unique probe key",
        })
        return result
    except ClientError as exc:
        response = exc.response or {}
        err = response.get("Error") or {}
        meta = response.get("ResponseMetadata") or {}
        status = meta.get("HTTPStatusCode")
        code = str(err.get("Code") or "")
        message = str(err.get("Message") or "")
        low = (code + " " + message).lower()
        if status == 404 or (status is None and code in {"404", "NoSuchKey", "NotFound"}):
            result.update({
                "class_b_ok": True, "status": "ok", "http_status": 404,
                "aws_code": code,
                "note": "404 on missing key means HEAD/Class-B access works",
            })
            return result
        cap_exceeded = status == 403 and any(token in low for token in (
            "cap exceeded", "transaction cap", "class b", "download bandwidth",
        ))
        result.update({
            "class_b_ok": False,
            "status": "cap_exceeded" if cap_exceeded else "forbidden_or_error",
            "http_status": status, "aws_code": code or None,
        })
        return result
    except Exception as exc:
        result.update({
            "class_b_ok": False, "status": "error",
            "error_type": type(exc).__name__,
        })
        return result


def _single_attempt_client(backend):
    """Separate diagnostics from existing multi-B2 retry behavior."""
    cfg = config_for_backend(backend, required=True)
    client = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["key_id"],
        aws_secret_access_key=cfg["application_key"],
        config=BotoConfig(
            retries={"total_max_attempts": 1},
            connect_timeout=5,
            read_timeout=5,
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )
    return instrument_client(client, backend=backend, component="classb_probe")


def _diagnostic_auth_error():
    # The ordinary ORDER switch is NOT authorization. Nothing runs by default.
    if os.environ.get("ORDER_B2_DIAG_ENABLED", "").strip() != "1":
        return jsonify({"ok": False, "code": "DIAGNOSTIC_DISABLED"}), 404
    secret = os.environ.get("ORDER_B2_DIAG_TOKEN", "")
    supplied = request.headers.get(_TOKEN_HEADER, "")
    if len(secret) < 32 or not hmac.compare_digest(secret, supplied):
        return jsonify({"ok": False, "code": "DIAGNOSTIC_FORBIDDEN"}), 403
    return None


def _diagnostic_attempts():
    """Process-local diagnostic sends only, including raw SDK retries if any."""
    rows = snapshot(drain=False)["details"]
    return {
        backend: sum(row["count"] for row in rows
                     if row["backend"] == backend
                     and row["component"] == "classb_probe"
                     and row["activity"] == "b2_diagnostic"
                     and row["operation"] == "HEAD")
        for backend in (PRIMARY, SECONDARY)
    }


def _read_result():
    try:
        with open(_DIAG_PATH, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return {"state": "not_run" if not os.path.exists(_DIAG_PATH) else "running"}


def _reserve_once():
    """Atomic per-filesystem reservation across Gunicorn worker processes."""
    try:
        fd = os.open(_DIAG_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump({"state": "running", "started_at_epoch": int(time.time())}, file)
    return True


def _save_result(value):
    # Atomic replace keeps read-only status GETs from seeing half-written JSON.
    path = f"{_DIAG_PATH}.{os.getpid()}.tmp"
    try:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(value, file, separators=(",", ":"), ensure_ascii=True)
        os.replace(path, _DIAG_PATH)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _respond(value, status=200):
    response = jsonify(value)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response, status


@b2_test_bp.route("/api/order-cloud/b2/class-b/status", methods=["GET"])
def order_cloud_b2_diagnostic_status():
    error = _diagnostic_auth_error()
    if error is not None:
        return error
    return _respond({
        "ok": True,
        "scope": "per_render_instance_not_global_b2_usage",
        "last_run": _read_result(),
        "process_counters": snapshot(drain=False)["totals"],
        "diagnostic_head_attempts_process": _diagnostic_attempts(),
    })


@b2_test_bp.route("/api/order-cloud/b2/class-b", methods=["POST"])
def order_cloud_b2_class_b_probe():
    error = _diagnostic_auth_error()
    if error is not None:
        return error
    try:
        reserved = _reserve_once()
    except OSError:
        return _respond({"ok": False, "code": "DIAGNOSTIC_GUARD_UNAVAILABLE"}, 503)
    if not reserved:
        return _respond({
            "ok": False, "code": "DIAGNOSTIC_ALREADY_USED",
            "last_run": _read_result(),
        }, 409)

    try:
        before = _diagnostic_attempts()
        with activity_context("b2_diagnostic"):
            backends = {
                backend: _probe_backend(backend, client_factory=_single_attempt_client)
                for backend in (PRIMARY, SECONDARY)
            }
        after = _diagnostic_attempts()
        attempts = {name: max(0, after[name] - before[name])
                    for name in (PRIMARY, SECONDARY)}
        available = [name for name, item in backends.items() if item["configured"]]
        result = {
            "state": "completed",
            "ok": bool(available) and all(backends[name]["class_b_ok"] for name in available),
            "completed_at_epoch": int(time.time()),
            "scope": "one_run_per_render_instance_no_sdk_retries",
            "backends": backends,
            "head_http_send_attempts": attempts,
            "total_head_http_send_attempts": sum(attempts.values()),
            "process_counters": snapshot(drain=False)["totals"],
        }
    except Exception as exc:
        # Reservation remains consumed even if diagnostics fail: fail closed.
        result = {
            "state": "error", "ok": False, "error_type": type(exc).__name__,
            "completed_at_epoch": int(time.time()),
        }
    try:
        _save_result(result)
    except OSError:
        # The exclusive reservation file still blocks further POSTs.
        return _respond({"ok": False, "code": "DIAGNOSTIC_RESULT_NOT_SAVED"}, 503)
    print("[ORDER B2 DIAG] " + json.dumps({
        "state": result["state"],
        "statuses": {name: item["status"] for name, item in result.get("backends", {}).items()},
        "head_attempts": result.get("head_http_send_attempts", {}),
    }, separators=(",", ":")), flush=True)
    return _respond(result)
