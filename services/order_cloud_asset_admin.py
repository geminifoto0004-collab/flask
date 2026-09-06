"""Admin-only ORDER B2 asset management endpoints.

The browser never receives B2 credentials.  The local ORDER admin UI calls these
protected control-plane endpoints with X-Order-Sync-Key.  Normal listing is backed by
TiDB cloud_assets (fast); an explicit orphan scan lists B2 objects only on demand.
"""
from __future__ import annotations

import math

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY, backend_ready, client_for_backend, config_for_backend

_ALLOWED_BACKENDS = {PRIMARY, SECONDARY}
_ALLOWED_PREFIXES = ("customers/", "order-cloud/images/", "order-cloud/thumbs/")


def _backend(value):
    value = str(value or "").strip().lower()
    return value if value in _ALLOWED_BACKENDS else ""


def _thumb_key_from_sha(value):
    sha = str(value or "").strip().lower()
    return f"order-cloud/thumbs/{sha[:2]}/{sha}.jpg" if len(sha) == 64 else ""


def _safe_object_key(value):
    key = str(value or "").strip()
    if not key or not key.startswith(_ALLOWED_PREFIXES):
        raise ValueError("object_key is outside ORDER image prefixes")
    return key


def _presigned_get(backend, object_key, seconds=600):
    cfg = config_for_backend(backend, required=True)
    return client_for_backend(backend).generate_presigned_url(
        "get_object", Params={"Bucket": cfg["bucket_name"], "Key": object_key},
        ExpiresIn=max(60, min(int(seconds or 600), 3600)),
    )


def _delete_object(backend, object_key):
    if not object_key:
        return False
    key = _safe_object_key(object_key)
    cfg = config_for_backend(backend, required=True)
    client_for_backend(backend).delete_object(Bucket=cfg["bucket_name"], Key=key)
    return True


def _asset_select_base():
    return """
        SELECT a.asset_key, a.customer_key, a.order_number, a.workflow_key,
               a.sha256, a.object_key, a.storage_backend, a.content_type,
               a.file_size, a.display_name, a.source_site, a.active,
               a.created_at, a.updated_at,
               a.thumb_object_key, a.thumb_sha256, a.thumb_content_type, a.thumb_file_size,
               o.customer_name
        FROM cloud_assets a
        LEFT JOIN cloud_orders o ON o.order_number=a.order_number AND o.customer_key=a.customer_key
    """


def _row_to_public(row, preview=True):
    item = dict(row or {})
    backend = _backend(item.get("storage_backend")) or PRIMARY
    item["storage_backend"] = backend
    item["source_kind"] = "sales" if str(item.get("workflow_key") or "").strip() else "supervisor"
    item["source_kind_label"] = "业务员图片" if item["source_kind"] == "sales" else "主管参考图"
    item["file_size"] = int(item.get("file_size") or 0)
    item["thumb_file_size"] = int(item.get("thumb_file_size") or 0)
    if preview:
        thumb_key = str(item.get("thumb_object_key") or _thumb_key_from_sha(item.get("sha256")) or "").strip()
        try:
            item["preview_url"] = _presigned_get(backend, thumb_key, 600) if thumb_key else ""
        except Exception:
            item["preview_url"] = ""
    return item


def _invalidate_customer_snapshots(customer_keys):
    keys = {str(x or "").strip() for x in customer_keys if str(x or "").strip()}
    if not keys:
        return
    try:
        from services import order_customer_share_snapshot as snapshot
        for key in keys:
            snapshot.queue_snapshot_refresh(key, delay=0.05)
    except Exception as exc:
        print(f"[WARN] B2 admin snapshot refresh skipped: {type(exc).__name__}: {exc}")


@b2_test_bp.route("/api/order-cloud/assets/admin-list", methods=["GET"])
def order_cloud_admin_asset_list():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    _ensure_order_cloud_tables()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1
    try:
        page_size = max(10, min(100, int(request.args.get("page_size", 30))))
    except Exception:
        page_size = 30
    q = str(request.args.get("q") or "").strip()
    backend = _backend(request.args.get("backend"))
    source_kind = str(request.args.get("source_kind") or "all").strip().lower()
    clauses = ["a.active=TRUE"]
    params = []
    if q:
        like = f"%{q}%"
        clauses.append("(a.order_number LIKE ? OR a.customer_key LIKE ? OR COALESCE(o.customer_name,'') LIKE ? OR a.asset_key LIKE ?)")
        params.extend([like, like, like, like])
    if backend:
        clauses.append("a.storage_backend=?")
        params.append(backend)
    if source_kind == "sales":
        clauses.append("a.workflow_key IS NOT NULL AND TRIM(a.workflow_key)<>''")
    elif source_kind == "supervisor":
        clauses.append("(a.workflow_key IS NULL OR TRIM(a.workflow_key)='')")
    where = " WHERE " + " AND ".join(clauses)
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute("SELECT COUNT(*) AS n FROM cloud_assets a LEFT JOIN cloud_orders o ON o.order_number=a.order_number AND o.customer_key=a.customer_key" + where, tuple(params))
        total = int((get_row_dict(cur.fetchone(), cur) or {}).get("n") or 0)
        pages = max(1, math.ceil(total / page_size)); page = min(page, pages)
        cur.execute(_asset_select_base() + where + " ORDER BY a.created_at DESC, a.asset_key DESC LIMIT ? OFFSET ?", tuple(params + [page_size, (page - 1) * page_size]))
        rows = [_row_to_public(get_row_dict(r, cur), preview=True) for r in cur.fetchall()]
    finally:
        conn.close()
    return jsonify({"ok": True, "items": rows, "page": page, "page_size": page_size, "total": total, "total_pages": pages})


@b2_test_bp.route("/api/order-cloud/assets/admin-delete", methods=["POST"])
def order_cloud_admin_asset_delete():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    _ensure_order_cloud_tables()
    payload = request.get_json(silent=True) or {}
    asset_keys = [str(x or "").strip() for x in (payload.get("asset_keys") or []) if str(x or "").strip()]
    if not asset_keys:
        return jsonify({"ok": False, "error": "asset_keys is required"}), 400
    if len(asset_keys) > 100:
        return jsonify({"ok": False, "error": "maximum 100 assets per delete"}), 400
    marks = ",".join("?" for _ in asset_keys)
    conn = get_db_connection(); cur = get_cursor(conn)
    deleted, failed, customer_keys = [], [], set()
    try:
        cur.execute(_asset_select_base() + f" WHERE a.asset_key IN ({marks})", tuple(asset_keys))
        rows = [get_row_dict(r, cur) for r in cur.fetchall()]
        by_key = {str((r or {}).get("asset_key") or ""): r for r in rows}
        for asset_key in asset_keys:
            row = by_key.get(asset_key)
            if not row:
                failed.append({"asset_key": asset_key, "error": "asset not found"}); continue
            backend = _backend(row.get("storage_backend")) or PRIMARY
            try:
                _delete_object(backend, row.get("object_key"))
                thumb_key = row.get("thumb_object_key") or _thumb_key_from_sha(row.get("sha256"))
                if thumb_key:
                    _delete_object(backend, thumb_key)
                cur.execute("DELETE FROM cloud_assets WHERE asset_key=?", (asset_key,))
                customer_keys.add(str(row.get("customer_key") or "")); deleted.append(asset_key)
            except Exception as exc:
                failed.append({"asset_key": asset_key, "error": f"{type(exc).__name__}: {exc}"[:500]})
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
    _invalidate_customer_snapshots(customer_keys)
    return jsonify({"ok": True, "partial": bool(failed), "deleted": deleted, "failed": failed, "deleted_count": len(deleted)}), (200 if not failed else 207)


def _known_object_keys():
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute("SELECT object_key, thumb_object_key, sha256 FROM cloud_assets WHERE active=TRUE")
        known = set()
        for r in cur.fetchall():
            d = get_row_dict(r, cur) or {}
            for k in (d.get("object_key"), d.get("thumb_object_key"), _thumb_key_from_sha(d.get("sha256"))):
                if k: known.add(str(k))
        return known
    finally:
        conn.close()


@b2_test_bp.route("/api/order-cloud/assets/admin-orphans", methods=["GET"])
def order_cloud_admin_asset_orphans():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    if str(request.args.get("scan") or "").strip() not in {"1", "true", "yes"}:
        return jsonify({"ok": False, "error": "explicit scan=1 is required"}), 400
    try:
        max_objects = max(50, min(2000, int(request.args.get("limit", 500))))
    except Exception:
        max_objects = 500
    backend_filter = _backend(request.args.get("backend"))
    backends = [backend_filter] if backend_filter else [x for x in (PRIMARY, SECONDARY) if backend_ready(x)]
    known = _known_object_keys(); out = []; scanned = 0; truncated = False
    for backend in backends:
        cfg = config_for_backend(backend, required=True); s3 = client_for_backend(backend)
        for prefix in ("customers/", "order-cloud/images/", "order-cloud/thumbs/"):
            token = None
            while scanned < max_objects:
                kwargs = {"Bucket": cfg["bucket_name"], "Prefix": prefix, "MaxKeys": min(500, max_objects - scanned)}
                if token: kwargs["ContinuationToken"] = token
                response = s3.list_objects_v2(**kwargs); objects = response.get("Contents") or []; scanned += len(objects)
                for obj in objects:
                    key = str(obj.get("Key") or "")
                    if key and key not in known:
                        out.append({"storage_backend": backend, "object_key": key, "file_size": int(obj.get("Size") or 0), "last_modified": obj.get("LastModified").isoformat() if hasattr(obj.get("LastModified"), "isoformat") else str(obj.get("LastModified") or ""), "kind": "thumbnail" if key.startswith("order-cloud/thumbs/") else "image"})
                if not response.get("IsTruncated"): break
                token = response.get("NextContinuationToken")
                if not token: break
            if scanned >= max_objects:
                truncated = True; break
        if scanned >= max_objects:
            truncated = True; break
    return jsonify({"ok": True, "items": out, "scanned": scanned, "orphan_count": len(out), "truncated": truncated, "limit": max_objects})


@b2_test_bp.route("/api/order-cloud/assets/admin-delete-orphans", methods=["POST"])
def order_cloud_admin_delete_orphans():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or {}
    items = [dict(x or {}) for x in (payload.get("items") or []) if isinstance(x, dict)]
    if not items:
        return jsonify({"ok": False, "error": "items is required"}), 400
    if len(items) > 100:
        return jsonify({"ok": False, "error": "maximum 100 objects per delete"}), 400
    known = _known_object_keys(); deleted = []; failed = []
    for item in items:
        backend = _backend(item.get("storage_backend")); key = str(item.get("object_key") or "").strip()
        try:
            if not backend: raise ValueError("invalid storage_backend")
            key = _safe_object_key(key)
            if key in known: raise ValueError("object is registered in TiDB; delete it from the registered-assets list instead")
            _delete_object(backend, key); deleted.append({"storage_backend": backend, "object_key": key})
        except Exception as exc:
            failed.append({"storage_backend": backend, "object_key": key, "error": f"{type(exc).__name__}: {exc}"[:500]})
    return jsonify({"ok": True, "partial": bool(failed), "deleted": deleted, "failed": failed, "deleted_count": len(deleted)}), (200 if not failed else 207)
