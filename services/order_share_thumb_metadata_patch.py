"""Canonical thumbnail metadata/signing for ORDER public shares.

The existing multi-B2 before_app_request hook stays registered.  Its global function
lookups are replaced here so /thumb signs thumb_object_key, never asset.object_key,
and never performs B2 HEAD/GET/resize/PUT work while a customer is swiping.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from flask import Response, has_request_context, redirect, request

from blueprints.b2_test_bp import b2_test_bp
from database import get_cursor, get_db_connection, get_row_dict
from services import order_cloud_asset_service as _asset_service
from services import order_cloud_multi_b2_public as _media
from services import order_customer_share_snapshot as _snapshot
from services import order_public_share_fast as _fast
from services.order_cloud_multi_b2 import PRIMARY
from services.order_share_image_policy import asset_allowed


def _list_customer_assets(customer_key):
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
