"""Cross-target ORDER sync receipts.

B2 is the independent recovery copy, NOT a replacement for checking the
selected TiDB target before publishing. Each source site owns its own B2
object, preventing HOME from overwriting COMPANY checkpoints.
"""
from __future__ import annotations

import gzip
import hmac
import os
import hashlib
import json
import re
import threading
import time

from botocore.exceptions import ClientError
from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _order_cloud_auth_source

_LOCK = threading.RLock()
_SITES = ("COMPANY", "HOME")
_TARGETS = ("TIDB1", "TIDB2", "GLOBAL")
_KINDS = ("media", "audit", "scope", "status")
_HEX = re.compile(r"^[a-f0-9]{64}$")


def _check(value, options, label):
    value = str(value or "").strip().upper()
    if value not in options:
        raise ValueError("invalid " + label)
    return value


def _key(kind, target, site):
    return f"order-cloud/sync-ledger/v272/{kind}/{target}/{site}.json.gz"


def _storage():
    # Do not probe TiDB here. The checkpoint must stay readable when TiDB1
    # exhausts RU, even if the active target has not yet been switched.
    from services.order_cloud_asset_service import _backend_client
    return _backend_client("b2_primary")


def _read(kind, target, site):
    s3, cfg = _storage()
    try:
        obj = s3.get_object(Bucket=cfg["bucket_name"], Key=_key(kind, target, site))
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
            return {}
        raise
    raw = obj["Body"].read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("checkpoint object exceeds limit")
    body = json.loads(gzip.decompress(raw))
    if body.get("version") != 272 or body.get("kind") != kind or body.get("target") != target or body.get("site") != site:
        raise ValueError("checkpoint scope mismatch")
    entries = body.get("entries")
    return entries if isinstance(entries, dict) else {}


def _merge(kind, target):
    entries = {}
    for site in _SITES:
        for key, item in _read(kind, target, site).items():
            if isinstance(item, dict) and _HEX.fullmatch(str(key)) and (
                    int(item.get("checked_at") or 0) > int((entries.get(key) or {}).get("checked_at") or 0)):
                entries[key] = item
    return entries


def _ti_db_mirror(kind, target, rows):
    if not rows:
        return False
    # Never read or connect to the other TiDB. It may be RU-exhausted.
    from database import get_db_connection, get_cursor
    conn = get_db_connection()
    try:
        if target != "GLOBAL" and getattr(conn, "active_target", "") != target:
            return False
        cur = get_cursor(conn)
        cur.execute("""CREATE TABLE IF NOT EXISTS cloud_sync_receipts_v272 (
            target VARCHAR(8) NOT NULL,
            kind VARCHAR(12) NOT NULL,
            receipt_key CHAR(64) NOT NULL,
            fingerprint CHAR(64) NOT NULL,
            checked_at BIGINT NOT NULL,
            PRIMARY KEY (target, kind, receipt_key)
        )""")
        cur.executemany(
            """INSERT INTO cloud_sync_receipts_v272
            (target,kind,receipt_key,fingerprint,checked_at) VALUES (?,?,?,?,?)
            ON DUPLICATE KEY UPDATE fingerprint=VALUES(fingerprint),checked_at=VALUES(checked_at)""",
            [(target, kind, key, row["fingerprint"], row["checked_at"]) for key, row in rows.items()],
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@b2_test_bp.route("/api/order-cloud/sync/checkpoints", methods=["GET", "POST"])
def order_cloud_sync_checkpoints():
    _, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    # ORDER=1 alone is a feature gate, not authentication. Do not expose a
    # writable 'skip work' journal to public clients. Reuse the existing
    # paired desktop sync grant or an explicitly configured shared key.
    from services.order_desktop_grant import authorized
    key = str(os.environ.get("ORDER_SYNC_CHECKPOINT_KEY") or "").strip()
    supplied = str(request.headers.get("X-Order-Checkpoint-Key") or "")
    if not (authorized("replicas:verify-repair") or (
            len(key) >= 24 and hmac.compare_digest(key, supplied))):
        return jsonify({"ok": False, "error": "checkpoint authorization required"}), 401
    try:
        payload = (request.get_json(silent=True) or {}) if request.method == "POST" else request.args
        kind = _check(payload.get("kind"), _KINDS, "kind").lower()
        target = _check(payload.get("target"), _TARGETS, "target")
        if request.method == "GET":
            return jsonify({"ok": True, "result": {
                "entries": _merge(kind, target), "target": target, "kind": kind,
                "independent_of_tidb": True,
            }})
        site = _check(payload.get("site"), _SITES, "site")
        items = payload.get("entries")
        if not isinstance(items, dict) or not 1 <= len(items) <= 100:
            raise ValueError("entries must contain 1..100 items")
        now = int(time.time())
        rows = {}
        for key, item in items.items():
            if not isinstance(key, str) or not _HEX.fullmatch(key) or not isinstance(item, dict):
                raise ValueError("invalid receipt identity")
            fingerprint = str(item.get("fingerprint") or "").lower()
            if not _HEX.fullmatch(fingerprint):
                raise ValueError("invalid receipt fingerprint")
            checked_at = int(item.get("checked_at") or now)
            if checked_at > now + 300 or checked_at < now - 30 * 86400:
                raise ValueError("invalid receipt timestamp")
            rows[key] = {"fingerprint": fingerprint, "checked_at": checked_at}
            if kind == "audit":
                generation = str(item.get("generation") or "")[:96]
                if generation:
                    rows[key]["generation"] = generation
        with _LOCK:
            saved = _read(kind, target, site)
            for key, item in rows.items():
                if item["checked_at"] >= int((saved.get(key) or {}).get("checked_at") or 0):
                    saved[key] = item
            # Prevent unbounded growth. Recency only accelerates later checks;
            # no receipt is authoritative proof of current TiDB content.
            saved = dict(sorted(saved.items(),
                                key=lambda pair: int((pair[1] or {}).get("checked_at") or 0),
                                reverse=True)[:25000])
            body = {"version": 272, "site": site, "target": target,
                    "kind": kind, "entries": saved}
            packed = gzip.compress(json.dumps(body, separators=(",", ":"),
                                              sort_keys=True).encode("utf-8"))
            if len(packed) > 3 * 1024 * 1024:
                raise ValueError("checkpoint exceeds 3 MiB")
            s3, cfg = _storage()
            s3.put_object(Bucket=cfg["bucket_name"], Key=_key(kind, target, site),
                          Body=packed, ContentType="application/json",
                          ContentEncoding="gzip")
        mirrored = False
        mirror_error = ""
        try:
            mirrored = _ti_db_mirror(kind, target, rows)
        except Exception as exc:
            mirror_error = type(exc).__name__
            # B2 receipt is still durable. No attempt to read TiDB1 here.
        return jsonify({"ok": True, "result": {
            "saved": len(rows), "target": target, "kind": kind, "site": site,
            "b2_recorded": True, "tidb_recorded": mirrored,
            "tidb_warning": mirror_error,
        }})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"checkpoint unavailable: {type(exc).__name__}"}), 503
