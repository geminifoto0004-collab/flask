"""Canonical thumbnail metadata/signing for ORDER public shares.

The existing multi-B2 before_app_request hook stays registered.  Its global function
lookups are replaced here so /thumb signs thumb_object_key, never asset.object_key,
and never performs B2 HEAD/GET/resize/PUT work while a customer is swiping.
"""
from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime

from flask import Response, has_request_context, redirect, request

from blueprints.b2_test_bp import b2_test_bp
from database import get_cursor, get_db_connection, get_row_dict
from services import order_cloud_asset_service as _asset_service
from services import order_cloud_multi_b2_public as _media
from services import order_customer_share_snapshot as _snapshot
from services import order_public_share_fast as _fast
from services.order_cloud_multi_b2 import PRIMARY, _backend_order, client_for_backend, config_for_backend
from services.order_share_image_policy import asset_allowed



_B2_RECOVERY_LOCK = threading.Lock()
_B2_RECOVERY_DONE = set()

_B2_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _b2_safe_component(value, fallback):
    """Mirror order_cloud_direct_multi_b2._safe_component exactly."""
    raw = str(value or "").strip()
    if not raw:
        return fallback
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-.") or fallback
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:72]}-{digest}"


def _b2_customer_namespace(customer_key):
    """Mirror the direct-B2 customer namespace; it is stable and never uses share tokens."""
    value = str(customer_key or "").strip()
    if not value:
        raise ValueError("customer_key is required")
    return "c_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _asset_insert_sql():
    """Idempotent insert syntax for the DB engines supported by database.py."""
    try:
        import config
        db_type = str(getattr(config, "DATABASE_TYPE", "") or "").strip().lower()
    except Exception:
        db_type = ""
    columns = (
        "(asset_key, customer_key, order_number, workflow_key, asset_type, sha256, "
        "object_key, storage_backend, content_type, file_size, display_name, source_site, active)"
    )
    values = "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    if db_type in ("mysql", "tidb"):
        return f"INSERT IGNORE INTO cloud_assets {columns} {values}"
    if db_type == "postgresql":
        return f"INSERT INTO cloud_assets {columns} {values} ON CONFLICT (asset_key) DO NOTHING"
    return f"INSERT OR IGNORE INTO cloud_assets {columns} {values}"


def _recover_customer_assets_from_b2(customer_key):
    """Rebuild deterministic B2 -> ORDER metadata after switching to a fresh TiDB.

    Image ownership is encoded in the canonical B2 path:
      customers/<customer>/orders/<order>/workflows/<workflow>/images/<sha>.<ext>

    Therefore a TiDB failover does not require re-uploading image bytes.  We list the
    customer's B2 prefix, map the deterministic path back to the already-synced ORDER
    rows, and recreate only missing cloud_assets rows.  Existing rows (including
    inactive/manual exceptions) are never overwritten.
    """
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return 0

    with _B2_RECOVERY_LOCK:
        conn = get_db_connection()
        # AUTO can switch TiDB within one Render process. A customer scanned on
        # TiDB1 must still be scanned when TiDB2 becomes active.
        recovery_key = (str(getattr(conn, 'active_target', '') or 'single'), customer_key)
        if recovery_key in _B2_RECOVERY_DONE:
            conn.close()
            return 0
        cur = get_cursor(conn)
        scan_succeeded = False
        inserted = 0
        try:
            cur.execute(
                """SELECT order_number
                   FROM cloud_orders
                   WHERE customer_key=? AND active=TRUE""",
                (customer_key,),
            )
            order_numbers = []
            for row in cur.fetchall():
                data = get_row_dict(row, cur) or {}
                number = str(data.get("order_number") or "").strip()
                if number:
                    order_numbers.append(number)
            if not order_numbers:
                # ORDER sync may still be running.  Do not mark this customer done;
                # a later request can retry after cloud_orders arrives.
                return 0

            order_by_component = {
                _b2_safe_component(number, "order"): number
                for number in order_numbers
            }

            cur.execute(
                """SELECT w.order_number, w.workflow_key
                   FROM cloud_workflows w
                   INNER JOIN cloud_orders o ON o.order_number=w.order_number
                   WHERE o.customer_key=? AND o.active=TRUE AND w.active=TRUE""",
                (customer_key,),
            )
            workflow_by_component = {}
            for row in cur.fetchall():
                data = get_row_dict(row, cur) or {}
                number = str(data.get("order_number") or "").strip()
                workflow_key = str(data.get("workflow_key") or "").strip()
                if number and workflow_key:
                    workflow_by_component[
                        (number, _b2_safe_component(workflow_key, "_order"))
                    ] = workflow_key

            # Include inactive rows in this set: an intentionally disabled image must
            # not be silently resurrected merely because the B2 object still exists.
            cur.execute(
                "SELECT asset_key FROM cloud_assets WHERE customer_key=?",
                (customer_key,),
            )
            existing_keys = {
                str((get_row_dict(row, cur) or {}).get("asset_key") or "").strip().lower()
                for row in cur.fetchall()
            }

            root = f"customers/{_b2_customer_namespace(customer_key)}/orders/"
            discovered = []
            seen_keys = set()

            for backend in _backend_order():
                try:
                    cfg = config_for_backend(backend, required=True)
                    client = client_for_backend(backend)
                    continuation = None
                    while True:
                        kwargs = {
                            "Bucket": cfg["bucket_name"],
                            "Prefix": root,
                            "MaxKeys": 1000,
                        }
                        if continuation:
                            kwargs["ContinuationToken"] = continuation
                        page = client.list_objects_v2(**kwargs)
                        scan_succeeded = True

                        for obj in page.get("Contents") or []:
                            object_key = str(obj.get("Key") or "")
                            if not object_key.startswith(root):
                                continue
                            relative = object_key[len(root):]
                            parts = relative.split("/")
                            if (
                                len(parts) != 5
                                or parts[1] != "workflows"
                                or parts[3] != "images"
                            ):
                                continue

                            order_number = order_by_component.get(parts[0])
                            if not order_number:
                                continue

                            workflow_component = parts[2]
                            if workflow_component == "_order":
                                workflow_key = None
                            else:
                                workflow_key = workflow_by_component.get(
                                    (order_number, workflow_component)
                                )
                                if not workflow_key:
                                    continue

                            filename = parts[4]
                            match = re.fullmatch(
                                r"([0-9a-fA-F]{64})(\.(?:jpg|jpeg|png|webp))",
                                filename,
                            )
                            if not match:
                                continue
                            sha256_hex = match.group(1).lower()
                            extension = match.group(2).lower()
                            content_type = _B2_CONTENT_TYPES.get(extension)
                            if not content_type:
                                continue

                            asset_key = _asset_service._asset_key(
                                order_number, workflow_key, sha256_hex
                            )
                            if asset_key in existing_keys or asset_key in seen_keys:
                                continue
                            seen_keys.add(asset_key)
                            discovered.append(
                                (
                                    asset_key,
                                    customer_key,
                                    order_number,
                                    workflow_key,
                                    "IMAGE",
                                    sha256_hex,
                                    object_key,
                                    backend,
                                    content_type,
                                    int(obj.get("Size") or 0),
                                    f"Imagen {order_number}",
                                    "B2_RECOVER",
                                    True,
                                )
                            )

                        if not page.get("IsTruncated"):
                            break
                        continuation = page.get("NextContinuationToken")
                        if not continuation:
                            break
                except Exception as exc:
                    print(
                        f"[WARN] ORDER B2 metadata recovery backend {backend} skipped: "
                        f"{type(exc).__name__}: {exc}"
                    )

            if not scan_succeeded:
                # B2 may be temporarily unavailable. Keep retry capability.
                return 0

            sql = _asset_insert_sql()
            for values in discovered:
                cur.execute(sql, values)
                try:
                    inserted += max(int(cur.rowcount or 0), 0)
                except Exception:
                    pass
            conn.commit()
            _B2_RECOVERY_DONE.add(recovery_key)
            if discovered:
                print(
                    f"[ORDER] B2 metadata auto-recovery discovered={len(discovered)} "
                    f"inserted={inserted}"
                )
            return inserted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _safe_recover_customer_assets(customer_key):
    try:
        return _recover_customer_assets_from_b2(customer_key)
    except Exception as exc:
        # Fail open: an existing TiDB metadata path must continue to work even when
        # B2 listing is temporarily unavailable.
        print(
            f"[WARN] ORDER B2 metadata auto-recovery skipped: "
            f"{type(exc).__name__}: {exc}"
        )
        return 0


def _list_customer_assets(customer_key):
    _safe_recover_customer_assets(customer_key)
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, asset_type,
                      sha256, object_key, storage_backend, content_type, file_size, display_name,
                      thumb_object_key, thumb_sha256, thumb_content_type, thumb_file_size,
                      source_site, updated_at
               FROM cloud_assets WHERE customer_key=? AND active=TRUE
               ORDER BY order_number, created_at, asset_key""",
            (customer_key,),
        )
        return [get_row_dict(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()


def _get_asset(asset_key):
    asset_key = str(asset_key or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", asset_key):
        return None
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, asset_type,
                      sha256, object_key, storage_backend, content_type, file_size,
                      thumb_object_key, thumb_sha256, thumb_content_type, thumb_file_size,
                      display_name, source_site, active
               FROM cloud_assets WHERE asset_key=? AND active=TRUE""",
            (asset_key,),
        )
        row = cur.fetchone()
        return get_row_dict(row, cur) if row else None
    finally:
        conn.close()


_asset_service.list_customer_assets = _list_customer_assets
_asset_service.get_asset = _get_asset


def _load_build_rows(customer_key):
    """Rebuilt persisted snapshots carry the same thumb metadata as TiDB."""
    _safe_recover_customer_assets(customer_key)
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT order_number, customer_key AS row_customer_key, customer_name,
                      order_status, order_date, expected_delivery_date, production_type,
                      product_name, product_code, pattern_code, quantity,
                      source_site AS row_source_site, updated_at AS row_updated_at, render_payload
               FROM cloud_orders
               WHERE customer_key=? AND active=TRUE
                 AND UPPER(COALESCE(NULLIF(TRIM(order_status),''),'ACTIVE'))='ACTIVE'
               ORDER BY order_date DESC, order_number DESC""",
            (customer_key,),
        )
        order_rows = [get_row_dict(row, cur) for row in cur.fetchall()]
        cur.execute(
            """SELECT a.asset_key, a.customer_key, a.order_number, a.workflow_key, a.asset_type,
                      a.sha256, a.object_key, a.content_type, a.file_size, a.display_name,
                      a.source_site, a.storage_backend,
                      a.thumb_object_key, a.thumb_sha256, a.thumb_content_type, a.thumb_file_size,
                      a.updated_at, a.created_at
               FROM cloud_assets a
               INNER JOIN cloud_orders o ON o.order_number=a.order_number
                                      AND o.customer_key=a.customer_key AND o.active=TRUE
                                      AND UPPER(COALESCE(NULLIF(TRIM(o.order_status),''),'ACTIVE'))='ACTIVE'
               WHERE a.customer_key=? AND a.active=TRUE
               ORDER BY a.order_number, a.created_at, a.asset_key""",
            (customer_key,),
        )
        return order_rows, [get_row_dict(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()


_snapshot._load_build_rows = _load_build_rows


def _asset_from_bundle(bundle, asset_key):
    """Use memory only when the snapshot proves thumb metadata was loaded."""
    asset_key = str(asset_key or "").strip().lower()
    space = (bundle or {}).get("space") or {}
    for order in space.get("orders") or []:
        if not isinstance(order, dict):
            continue
        for item in order.get("assets") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("asset_key") or "").strip().lower() != asset_key:
                continue
            if not item.get("object_key") or "thumb_object_key" not in item:
                return None
            return {
                "asset_key": item.get("asset_key"),
                "order_number": item.get("order_number") or order.get("order_number"),
                "workflow_key": item.get("workflow_key"),
                "asset_type": item.get("asset_type"),
                "asset_kind": item.get("asset_kind"),
                "sha256": item.get("sha256"),
                "object_key": item.get("object_key"),
                "content_type": item.get("content_type"),
                "file_size": item.get("file_size"),
                "storage_backend": item.get("storage_backend"),
                "thumb_object_key": item.get("thumb_object_key"),
                "thumb_sha256": item.get("thumb_sha256"),
                "thumb_content_type": item.get("thumb_content_type"),
                "thumb_file_size": item.get("thumb_file_size"),
            }
    return None


def _authorized_asset_from_tidb(token, asset_key):
    token_hash = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT s.status AS share_status, s.expires_at AS share_expires_at,
                      s.show_images AS share_show_images,
                      s.show_workflow_images AS share_show_workflow_images,
                      s.show_pdf_pages AS share_show_pdf_pages,
                      a.asset_key, a.order_number, a.workflow_key, a.sha256,
                      a.asset_type, a.object_key, a.content_type, a.file_size, a.storage_backend,
                      a.thumb_object_key, a.thumb_sha256, a.thumb_content_type, a.thumb_file_size
               FROM cloud_share_tokens s
               INNER JOIN cloud_assets a ON a.asset_key=? AND a.active=TRUE
               INNER JOIN cloud_orders o ON o.order_number=a.order_number
                                         AND o.customer_key=s.customer_key AND o.active=TRUE
               WHERE s.token_hash=? LIMIT 1""",
            (asset_key, token_hash),
        )
        row = cur.fetchone(); data = get_row_dict(row, cur) if row else None
        if not data:
            return None, Response("Archivo no encontrado.", 404, mimetype="text/plain")
        if str(data.get("share_status") or "") != "active":
            return None, Response("Este enlace ya no está disponible.", 410, mimetype="text/plain")
        expiry = _media._parse_expiry(data.get("share_expires_at"))
        if expiry and datetime.utcnow() >= expiry:
            return None, Response("Este enlace ha expirado.", 410, mimetype="text/plain")
        asset = {key: data.get(key) for key in (
            "asset_key", "order_number", "workflow_key", "asset_type", "sha256",
            "object_key", "content_type", "file_size", "storage_backend",
            "thumb_object_key", "thumb_sha256", "thumb_content_type", "thumb_file_size",
        )}
        settings = {
            "show_images": data.get("share_show_images"),
            "show_workflow_images": data.get("share_show_workflow_images"),
            "show_pdf_pages": data.get("share_show_pdf_pages"),
        }
        if not asset_allowed(asset, settings) or not asset.get("object_key"):
            return None, Response("Archivo no encontrado.", 404, mimetype="text/plain")
        return asset, None
    finally:
        conn.close()


_ORIGINAL_SIGNED_GET = _media._signed_get


def signed_thumb_get(asset, seconds=600):
    thumb_key = str((asset or {}).get("thumb_object_key") or "").strip()
    if not thumb_key or not thumb_key.startswith("order-cloud/thumbs/"):
        raise ValueError("thumbnail metadata is not available")
    backend = str((asset or {}).get("storage_backend") or PRIMARY).strip().lower()
    if backend not in _media._ALLOWED_BACKENDS:
        backend = PRIMARY
    client, cfg = _media._cached_client(backend)
    url = client.generate_presigned_url(
        "get_object", Params={"Bucket": cfg["bucket_name"], "Key": thumb_key},
        ExpiresIn=int(seconds),
    )
    if "X-Amz-Algorithm=AWS4-HMAC-SHA256" not in str(url):
        raise RuntimeError("public B2 thumbnail URL is not Signature V4")
    return url, backend


def _is_thumb_request():
    if not has_request_context():
        return False
    parts = (request.path or "").strip("/").split("/")
    return len(parts) == 4 and parts[0] == "share" and parts[2] == "thumb"


def _signed_get_router(asset, seconds=600):
    if not _is_thumb_request():
        return _ORIGINAL_SIGNED_GET(asset, seconds=seconds)
    backend = str((asset or {}).get("storage_backend") or PRIMARY).strip().lower() or PRIMARY
    if not str((asset or {}).get("thumb_object_key") or "").strip():
        return request.host_url.rstrip("/") + "/order-share-thumb-placeholder.svg", backend
    return signed_thumb_get(asset, seconds=seconds)


@b2_test_bp.route("/order-share-thumb-placeholder.svg", methods=["GET"])
def _thumb_placeholder():
    body = ('<svg xmlns="http://www.w3.org/2000/svg" width="480" height="480">'
            '<rect width="480" height="480" fill="#f2f2f4"/>'
            '<text x="240" y="242" text-anchor="middle" fill="#9699a1" '
            'font-family="Arial,sans-serif" font-size="22">Sin miniatura</text></svg>')
    resp = Response(body, mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "public, max-age=300"
    resp.headers["X-Order-Media-Mode"] = "thumb-placeholder-metadata-missing"
    return resp


def _legacy_thumb_redirect(asset):
    if not str((asset or {}).get("thumb_object_key") or "").strip():
        return redirect("/order-share-thumb-placeholder.svg", code=302)
    url, backend = signed_thumb_get(asset, seconds=600)
    resp = redirect(url, code=302); resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Order-Storage-Backend"] = backend
    return resp


_media._asset_from_bundle = _asset_from_bundle
_media._authorized_asset_from_tidb = _authorized_asset_from_tidb
_media._signed_thumb_get = signed_thumb_get
_media._signed_get = _signed_get_router
_fast._thumb_redirect = _legacy_thumb_redirect
