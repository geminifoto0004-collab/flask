"""V279 manual B2 space reclamation. Fail closed; never touch SQLite or old APIs.

The preview is read-only; execute needs a paired desktop grant / checkpoint key,
a one-use server plan, matching local payload fingerprints, the literal DELETE
confirmation, and ORDER_B2_CLEANUP_ENABLED=1.  A scheduled task never calls it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _order_cloud_auth_source, _ensure_order_cloud_tables
from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY, client_for_backend, config_for_backend
from services.order_desktop_grant import authorized
from services.order_media_lifecycle import CANCELLED, pending_pickup, retention_reason
from services.order_cloud_asset_admin import _invalidate_customer_snapshots

_LOCK = threading.RLock()
_PLANS = {}
_ALLOWED = {PRIMARY, SECONDARY}
_PREFIXES = ("order-cloud/images/", "order-cloud/thumbs/")
_LIMIT = 250
_MAX_DELETE = 20
_TTL = 300


def _permission():
    _, error = _order_cloud_auth_source()
    if error:
        return error
    configured = (os.environ.get("ORDER_SYNC_CHECKPOINT_KEY") or "").strip()
    supplied = request.headers.get("X-Order-Checkpoint-Key") or ""
    if not (authorized("replicas:verify-repair")
            or (len(configured) >= 24 and hmac.compare_digest(configured, supplied))):
        return jsonify({"ok": False, "error": "desktop sync authorization required"}), 401
    return None


def _canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse(raw):
    if isinstance(raw, dict):
        return dict(raw)
    value = json.loads(raw) if isinstance(raw, (str, bytes)) and raw else {}
    if not isinstance(value, dict):
        raise ValueError("invalid ORDER payload")
    return value


def _share_rows(cur):
    cur.execute("""SELECT customer_key, history_scope, include_cancelled
                   FROM cloud_share_tokens WHERE status='active'
                     AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP)""")
    data = {}
    for raw in cur.fetchall() or []:
        row = get_row_dict(raw, cur) or {}
        key = str(row.get("customer_key") or "").strip()
        if key:
            data.setdefault(key, []).append(row)
    return data


def _eligible_reason(order, asset, shares, active):
    if not active or not isinstance(order, dict):
        return ""
    if pending_pickup(order):
        return ""  # Pending pickup always wins, even after three months.
    status = str(order.get("order_status") or order.get("current_status") or "").strip().upper()
    if status in CANCELLED:
        # An old custom link may explicitly include cancelled orders.
        return "" if any(bool(r.get("include_cancelled")) for r in shares) else "cancelled_order"
    if not shares:
        return "no_active_share"
    if any(str(r.get("history_scope") or "current").strip().lower() in
           {"all", "6m", "12m"} for r in shares):
        return ""
    logistics = [r for r in (order.get("logistics") or []) if isinstance(r, dict)]
    arrived = [r for r in logistics if str(r.get("status") or "").upper() == "ARRIVED_IQUIQUE"]
    if not arrived or len(arrived)!=len(logistics) or any(
            str(r.get("pickup_status") or "").lower() != "picked_up" for r in arrived):
        return ""  # EVERY shipment must be in Iquique and picked up.
    workflows = [w for w in (order.get("workflows") or []) if isinstance(w, dict)]
    if not workflows or any(str(w.get("status") or w.get("current_status") or "").upper()
                            != "COMPLETED" for w in workflows):
        return ""
    # Retention policy also needs authoritative image-source evidence and
    # checks the exact three-calendar-month Chilean date cutoff.
    return "completed_picked_up" if retention_reason(order, asset, True) == (
        "candidate_completed_over_three_months") else ""


def _references(cur, row):
    # Never remove a content-addressed original or thumbnail while ANY other
    # TiDB metadata row (even inactive) references the same object.
    backend = row["storage_backend"]
    cur.execute("""SELECT COUNT(*) AS n FROM cloud_assets
                   WHERE storage_backend=? AND asset_key<>?
                     AND (sha256=? OR object_key=? OR thumb_object_key=?)""",
                (backend, row["asset_key"], row["sha256"],
                 row["object_key"], row.get("thumb_object_key") or ""))
    return int((get_row_dict(cur.fetchone(), cur) or {}).get("n") or 0)


def _asset_safe(cur, row, shares):
    if row.get("storage_backend") not in _ALLOWED:
        return ""
    object_key = str(row.get("object_key") or "")
    if not object_key.startswith(_PREFIXES) or ".." in object_key:
        return ""
    thumb_key = str(row.get("thumb_object_key") or "")
    if thumb_key and (not thumb_key.startswith("order-cloud/thumbs/") or ".." in thumb_key):
        return ""
    if _references(cur, row):
        return ""
    try:
        order = _parse(row.get("render_payload"))
    except (ValueError, TypeError):
        return ""
    # Recent uploads are protected from overlap with ongoing publication.
    updated = row.get("asset_updated_at")
    if isinstance(updated, datetime):
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - updated).total_seconds() < 900:
            return ""
    return _eligible_reason(order, row, shares.get(row["customer_key"], []),
                            bool(row.get("order_active")))


def _query(cur, after, limit):
    cur.execute("""SELECT a.asset_key,a.customer_key,a.order_number,a.sha256,
                          a.object_key,a.thumb_object_key,a.storage_backend,
                          a.file_size,a.thumb_file_size,a.updated_at AS asset_updated_at,
                          o.active AS order_active,o.render_payload
                   FROM cloud_assets a
                   JOIN cloud_orders o ON o.order_number=a.order_number
                       AND o.customer_key=a.customer_key
                   WHERE a.active=TRUE AND a.asset_key>?
                   ORDER BY a.asset_key LIMIT ?""", (after, limit))
    return [get_row_dict(x, cur) for x in cur.fetchall() or []]


def _other_target_clear(row, selected):
    """Protect shared B2 bytes from the independent alternate TiDB target.

    Absence or lack of permission never means "unused".  Any active reference,
    unavailable alternate target, or unknown schema blocks deletion.
    """
    from tidb_targets import other_target, target_configured, pymysql_kwargs
    import pymysql
    other = other_target(selected)
    if not target_configured(other):
        return True  # The installation has only one configured TiDB.
    try:
        conn = pymysql.connect(**pymysql_kwargs(other, connect_timeout=5, read_timeout=8))
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT COUNT(*) FROM cloud_assets
                       WHERE active=TRUE AND storage_backend=%s
                       AND (sha256=%s OR object_key=%s OR thumb_object_key=%s)""",
                    (row["storage_backend"], row["sha256"],
                     row["object_key"], row.get("thumb_object_key") or ""))
                return int(cursor.fetchone()[0]) == 0
        finally:
            conn.close()
    except Exception as exc:
        print("[B2 Cleanup] other TiDB protection: " + type(exc).__name__, flush=True)
        return False


def _item(cur, row, shares, target):
    reason = _asset_safe(cur, row, shares)
    if not reason or not _other_target_clear(row, target):
        return None
    parsed = _parse(row["render_payload"])
    return {
        "asset_key": str(row["asset_key"]),
        "customer_key": str(row["customer_key"]),
        "order_number": str(row["order_number"]),
        "order_sha256": _canonical_hash(parsed),
        "reason": reason,
        "storage_backend": row["storage_backend"],
        "estimated_bytes": max(0,int(row.get("file_size") or 0))+
                           max(0,int(row.get("thumb_file_size") or 0)),
        "sha256": row["sha256"],
        "object_key": row["object_key"],
        "thumb_object_key": row.get("thumb_object_key") or "",
    }


def _preview(after):
    if not isinstance(after, str) or len(after)>191:
        raise ValueError("invalid scan cursor")
    _ensure_order_cloud_tables()
    conn = get_db_connection()
    try:
        target = getattr(conn, "active_target", "")
        if target not in {"TIDB1", "TIDB2"}:
            raise ValueError("selected TiDB target is unknown")
        cur = get_cursor(conn)
        shares = _share_rows(cur)
        rows = _query(cur, after, _LIMIT)
        items = []
        last = after
        for row in rows:
            last = str(row["asset_key"])
            candidate = _item(cur, row, shares, target)
            if candidate:
                items.append(candidate)
                if len(items) >= _MAX_DELETE:
                    break
        has_more = len(rows) == _LIMIT or (len(items) >= _MAX_DELETE
                   and last != str(rows[-1]["asset_key"]))
    finally:
        conn.close()
    token = secrets.token_urlsafe(32)
    with _LOCK:
        for key, value in list(_PLANS.items()):
            if time.monotonic() - value["created"] > _TTL or len(_PLANS)>40:
                _PLANS.pop(key,None)
        _PLANS[token] = {"created":time.monotonic(), "target":target, "items":items}
    return {"plan_token":token, "target":target, "scanned":len(rows),
            "candidates":[{k:x[k] for k in ("asset_key","customer_key","order_number",
              "order_sha256","reason","storage_backend","estimated_bytes")} for x in items],
            "estimated_bytes":sum(x["estimated_bytes"] for x in items),
            "next_after":last if has_more else "", "read_only":True,
            "execution_enabled":os.environ.get("ORDER_B2_CLEANUP_ENABLED")=="1"}


def _delete_versions(backend, key):
    """Reclaim versioned B2 bytes too; refuse incomplete S3 versions listing."""
    if not key:
        return
    if not key.startswith(_PREFIXES) or ".." in key:
        raise ValueError("unsafe B2 object key")
    cfg = config_for_backend(backend, required=True)
    client = client_for_backend(backend)
    resp = client.list_object_versions(Bucket=cfg["bucket_name"],Prefix=key,MaxKeys=1000)
    if resp.get("IsTruncated"):
        raise ValueError("B2 object has too many versions; manual review required")
    entries = [x for kind in ("Versions", "DeleteMarkers")
               for x in resp.get(kind, []) if x.get("Key")==key]
    for entry in entries:
        client.delete_object(Bucket=cfg["bucket_name"],Key=key,VersionId=entry["VersionId"])
    # If an unversioned bucket had no versions, remove the current object.
    if not entries:
        client.delete_object(Bucket=cfg["bucket_name"],Key=key)
    check = client.list_object_versions(Bucket=cfg["bucket_name"],Prefix=key,MaxKeys=1000)
    if check.get("IsTruncated") or any(x.get("Key")==key for kind in ("Versions","DeleteMarkers")
                                        for x in check.get(kind, [])):
        raise RuntimeError("B2 version still present after delete")


def _execute(body):
    if os.environ.get("ORDER_B2_CLEANUP_ENABLED")!="1":
        raise PermissionError("B2 deletion is disabled; enable ORDER_B2_CLEANUP_ENABLED=1 only after acceptance tests")
    if body.get("word")!="DELETE":
        raise PermissionError("literal uppercase DELETE is required")
    token = str(body.get("plan_token") or "")
    with _LOCK:
        plan = _PLANS.pop(token, None)  # single-use even on failure
    if not plan or time.monotonic()-plan["created"]>_TTL:
        raise ValueError("preview expired or already used")
    evidence = body.get("evidence")
    if not isinstance(evidence, dict) or not plan["items"]:
        raise ValueError("fresh local attestation is mandatory")
    expected = {r["order_number"]:r["order_sha256"] for r in plan["items"]}
    if expected != evidence or body.get("target")!=plan["target"]:
        raise ValueError("local source fingerprint/target mismatch")
    deleted=[];failed=[];customers=set();bytes_estimate=0
    with _LOCK:  # cleanup requests cannot interleave on this Render worker
        for original in plan["items"]:
            conn = get_db_connection()
            try:
                if getattr(conn,"active_target","")!=plan["target"]:
                    raise ValueError("TiDB target changed; stop and re-preview")
                cur = get_cursor(conn)
                cur.execute("""SELECT a.asset_key,a.customer_key,a.order_number,a.sha256,
                                      a.object_key,a.thumb_object_key,a.storage_backend,
                                      a.file_size,a.thumb_file_size,a.updated_at AS asset_updated_at,
                                      o.active AS order_active,o.render_payload
                               FROM cloud_assets a JOIN cloud_orders o
                               ON a.customer_key=o.customer_key AND a.order_number=o.order_number
                               WHERE a.asset_key=? AND a.active=TRUE FOR UPDATE""",
                            (original["asset_key"],))
                row = get_row_dict(cur.fetchone(),cur)
                if not row:
                    raise ValueError("asset changed or already cleaned")
                now = _item(cur,row,_share_rows(cur),plan["target"])
                if not now or any(now[k]!=original[k] for k in (
                        "asset_key","order_number","customer_key","order_sha256","reason",
                        "storage_backend","sha256","object_key","thumb_object_key")):
                    raise ValueError("eligibility or share changed; re-preview")
                if not hmac.compare_digest(evidence[now["order_number"]], now["order_sha256"]):
                    raise ValueError("local attestation changed")
                _delete_versions(now["storage_backend"], now["object_key"])
                if now["thumb_object_key"] and now["thumb_object_key"]!=now["object_key"]:
                    _delete_versions(now["storage_backend"], now["thumb_object_key"])
                cur.execute("""UPDATE cloud_assets SET active=FALSE,
                               updated_at=CURRENT_TIMESTAMP WHERE asset_key=? AND active=TRUE""",
                            (now["asset_key"],))
                conn.commit()
                customers.add(now["customer_key"])
                bytes_estimate+=now["estimated_bytes"]
                deleted.append({"asset_key":now["asset_key"],"order_number":now["order_number"],
                                "reason":now["reason"],"estimated_bytes":now["estimated_bytes"]})
                print("[B2 Manual Cleanup] completed order="+now["order_number"]+
                      " asset="+now["asset_key"]+" backend="+now["storage_backend"],flush=True)
            except Exception as exc:
                try:conn.rollback()
                except Exception:pass
                failed.append({"asset_key":original["asset_key"],"error":type(exc).__name__})
            finally:
                conn.close()
    _invalidate_customer_snapshots(customers)
    return {"deleted":deleted,"failed":failed,"bytes_estimate":bytes_estimate,
            "deleted_count":len(deleted),"partial":bool(failed),
            "note":"B2 bytes deleted; cloud_assets rows marked inactive. Local originals untouched."}


@b2_test_bp.route("/api/order-cloud/assets/safe-cleanup/preview",methods=["POST"])
def b2_safe_cleanup_preview():
    denied=_permission()
    if denied:
        return denied
    try:
        raw=request.get_json(silent=True) or {}
        if not isinstance(raw,dict):
            raise ValueError("expected JSON object")
        result=_preview(raw.get("after") or "")
        return jsonify({"ok":True,"result":result})
    except (ValueError,TypeError) as exc:
        return jsonify({"ok":False,"error":str(exc)}),400
    except Exception as exc:
        print("[B2 Cleanup preview] "+type(exc).__name__,flush=True)
        return jsonify({"ok":False,"error":"cleanup preview unavailable"}),503


@b2_test_bp.route("/api/order-cloud/assets/safe-cleanup/execute",methods=["POST"])
def b2_safe_cleanup_execute():
    denied=_permission()
    if denied:
        return denied
    try:
        raw=request.get_json(silent=True) or {}
        if not isinstance(raw,dict):
            raise ValueError("expected JSON object")
        return jsonify({"ok":True,"result":_execute(raw)})
    except (ValueError,PermissionError,TypeError) as exc:
        return jsonify({"ok":False,"error":str(exc)}),409
    except Exception as exc:
        print("[B2 Cleanup execute] "+type(exc).__name__,flush=True)
        return jsonify({"ok":False,"error":"cleanup failed; inspect B2 objects and re-preview"}),503
