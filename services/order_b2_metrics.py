"""Read-only B2 S3 request telemetry for ORDER.

Counts outgoing HTTP *attempts* from Render boto3 clients via botocore before-send
events, including retry sends. No HEAD, GET, PUT or LIST calls are created here.

Not counted: PC->B2 direct uploads, browser->B2 signed GETs, Cloudflare-origin GETs,
or other apps/accounts. Do not treat the numbers as the Backblaze billing total.

Logs are aggregate, process-local deltas: no bucket, object key, customer name,
share token, URL, signed query string, credentials or payload is logged.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
import json
import threading

_METHODS = {
    "HeadObject": "HEAD",
    "GetObject": "GET",
    "PutObject": "PUT",
    "ListObjects": "LIST",
    "ListObjectsV2": "LIST",
}
_LOCK = threading.Lock()
_PENDING = Counter()
_TOTALS = Counter()
_ACTIVITY = ContextVar("order_b2_activity", default="")


def _activity():
    explicit = _ACTIVITY.get()
    if explicit:
        return explicit
    try:
        from flask import has_request_context, request
        if has_request_context():
            path = str(request.path or "")
            if path.endswith("/assets/check-batch") or path.endswith("/assets/check"):
                return "deep_audit"
            if "/assets/direct-presign" in path:
                return "upload_presign"
            if "/assets/direct-register" in path:
                return "upload_register"
            if path.startswith("/share/"):
                return "public_share"
            if "/b2/" in path:
                return "b2_diagnostic"
            if path.startswith("/api/order-cloud/"):
                return "cloud_api"
    except (ImportError, RuntimeError):
        pass
    return "background"


@contextmanager
def activity_context(name):
    """Propagate audit attribution into a ThreadPoolExecutor worker explicitly."""
    token = _ACTIVITY.set(str(name or "background")[:40])
    try:
        yield
    finally:
        _ACTIVITY.reset(token)


def record_attempt(backend, component, operation):
    """Record exactly one outgoing SDK HTTP send attempt; never perform a request."""
    method = _METHODS.get(str(operation or ""), str(operation or "").upper())
    if method not in {"HEAD", "GET", "PUT", "LIST"}:
        return
    key = (
        str(backend or "unknown")[:24],
        str(component or "unknown")[:40],
        _activity(),
        method,
    )
    with _LOCK:
        _PENDING[key] += 1
        _TOTALS[key] += 1


def instrument_client(client, *, backend, component):
    """Attach non-invasive botocore per-send observers to this one S3 client."""
    if getattr(client, "_order_b2_metrics_installed", False):
        return client
    events = client.meta.events
    for operation in _METHODS:
        def on_send(request=None, _operation=operation, **_kwargs):
            record_attempt(backend, component, _operation)
        events.register(
            "before-send.s3." + operation,
            on_send,
            unique_id="order-b2-metrics:" + str(component) + ":" + operation,
        )
    client._order_b2_metrics_installed = True
    return client


def snapshot(*, drain=False):
    """Return aggregated counters, optionally clearing only the pending deltas."""
    with _LOCK:
        counts = dict(_PENDING if drain else _TOTALS)
        if drain:
            _PENDING.clear()
    rows = [
        {"backend": backend, "component": component, "activity": activity,
         "operation": operation, "count": count}
        for (backend, component, activity, operation), count in sorted(counts.items())
    ]
    totals = {name: sum(row["count"] for row in rows if row["operation"] == name)
              for name in ("HEAD", "GET", "PUT", "LIST")}
    return {"totals": totals, "details": rows}


def log_pending():
    """One structured log line per Flask response with any newly observed traffic."""
    result = snapshot(drain=True)
    if not result["details"]:
        return
    result["scope"] = "render_botocore_http_send_attempts_only"
    result["excludes"] = ["browser_b2_get", "cdn_origin_get", "pc_direct_b2_put"]
    print("[ORDER B2 USAGE] " + json.dumps(result, separators=(",", ":")), flush=True)
