"""Temporary Backblaze B2 tests plus isolated ORDER cloud gateway routes.

The ORDER cloud routes remain here temporarily because this blueprint is already
registered by app.py. Business/storage logic lives in services/order_cloud_service.py.
"""

import os
import uuid

import boto3
from botocore.exceptions import ClientError
from flask import Blueprint, Response, jsonify, render_template, request

b2_test_bp = Blueprint("b2_test", __name__)

TEST_IMAGE_KEY = "_test/images/1884e39ec9c149838a9e0b73197a34ad.png"


def _b2_config():
    values = {
        "key_id": (os.environ.get("B2_KEY_ID") or "").strip(),
        "application_key": (os.environ.get("B2_APPLICATION_KEY") or "").strip(),
        "bucket_name": (os.environ.get("B2_BUCKET_NAME") or "").strip(),
        "endpoint": (os.environ.get("B2_ENDPOINT") or "").strip().rstrip("/"),
    }
    missing = [env_name for env_name, value in (
        ("B2_KEY_ID", values["key_id"]),
        ("B2_APPLICATION_KEY", values["application_key"]),
        ("B2_BUCKET_NAME", values["bucket_name"]),
        ("B2_ENDPOINT", values["endpoint"]),
    ) if not value]
    return values, missing


def _client(cfg):
    return boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["key_id"],
        aws_secret_access_key=cfg["application_key"],
    )


@b2_test_bp.route("/api/test-b2", methods=["GET"])
def test_b2():
    cfg, missing = _b2_config()
    if missing:
        return jsonify({"ok": False, "step": "environment", "missing": missing}), 500
    test_key = "_test/render_connection_test.txt"
    test_content = b"RENDER TO BACKBLAZE B2 TEST OK"
    s3 = None
    uploaded = False
    try:
        s3 = _client(cfg)
        s3.put_object(Bucket=cfg["bucket_name"], Key=test_key, Body=test_content, ContentType="text/plain")
        uploaded = True
        obj = s3.get_object(Bucket=cfg["bucket_name"], Key=test_key)
        if obj["Body"].read() != test_content:
            raise RuntimeError("Downloaded B2 test content does not match")
        s3.delete_object(Bucket=cfg["bucket_name"], Key=test_key)
        uploaded = False
        try:
            s3.head_object(Bucket=cfg["bucket_name"], Key=test_key)
            raise RuntimeError("B2 test object still exists after deletion")
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = exc.response.get("Error", {}).get("Code")
            if status != 404 and code not in ("404", "NoSuchKey", "NotFound"):
                raise
        return jsonify({"ok": True, "message": "Render -> Backblaze B2 TEST SUCCESS", "bucket": cfg["bucket_name"], "upload": "OK", "read": "OK", "delete": "OK"})
    except Exception as exc:
        if uploaded and s3 is not None:
            try:
                s3.delete_object(Bucket=cfg["bucket_name"], Key=test_key)
            except Exception:
                pass
        result = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
        if isinstance(exc, ClientError):
            result["error_code"] = exc.response.get("Error", {}).get("Code")
            result["http_status"] = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return jsonify(result), 500


@b2_test_bp.route("/api/test-b2-image", methods=["POST"])
def test_b2_image():
    cfg, missing = _b2_config()
    if missing:
        return jsonify({"ok": False, "step": "environment", "missing": missing}), 500
    image = request.files.get("image")
    if image is None or not image.filename:
        return jsonify({"ok": False, "error": "multipart field 'image' is required"}), 400
    content_type = (image.mimetype or "").lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        return jsonify({"ok": False, "error": "Only JPEG, PNG and WEBP are allowed for this test", "content_type": content_type}), 400
    data = image.read()
    if not data:
        return jsonify({"ok": False, "error": "Image is empty"}), 400
    if len(data) > 15 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Image exceeds 15 MB test limit"}), 413
    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type]
    object_key = f"_test/images/{uuid.uuid4().hex}{extension}"
    try:
        s3 = _client(cfg)
        s3.put_object(Bucket=cfg["bucket_name"], Key=object_key, Body=data, ContentType=content_type)
        info = s3.head_object(Bucket=cfg["bucket_name"], Key=object_key)
        return jsonify({"ok": True, "message": "PC -> Render -> Backblaze B2 IMAGE UPLOAD SUCCESS", "bucket": cfg["bucket_name"], "object_key": object_key, "original_filename": image.filename, "content_type": content_type, "uploaded_bytes": len(data), "b2_size": info.get("ContentLength")})
    except Exception as exc:
        result = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
        if isinstance(exc, ClientError):
            result["error_code"] = exc.response.get("Error", {}).get("Code")
            result["http_status"] = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return jsonify(result), 500


@b2_test_bp.route("/share/test", methods=["GET"])
def share_test():
    html = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Estado del pedido</title><style>body{margin:0;background:#f5f6f8;font-family:Arial,sans-serif;color:#222}.wrap{max-width:760px;margin:0 auto;padding:22px 14px}.card{background:#fff;border-radius:14px;padding:22px;box-shadow:0 2px 12px rgba(0,0,0,.08)}h1{font-size:24px;margin:0 0 18px}.status{display:inline-block;background:#fff3cd;padding:7px 12px;border-radius:20px;font-weight:700}.row{margin:10px 0}.label{color:#777}.photo{width:100%;height:auto;margin-top:20px;border-radius:10px;display:block}.note{font-size:13px;color:#888;margin-top:16px}</style></head><body><div class="wrap"><div class="card"><h1>Estado del pedido</h1><div class="row"><span class="label">Pedido:</span> G-TEST-001</div><div class="row"><span class="label">Estado:</span> <span class="status">En producción</span></div><div class="row"><span class="label">Actualización:</span> Prueba de Render + B2 privado</div><img class="photo" src="/share/test/image" alt="Imagen del pedido"><div class="note">Página temporal de prueba.</div></div></div></body></html>"""
    return Response(html, mimetype="text/html")


@b2_test_bp.route("/share/test/image", methods=["GET"])
def share_test_image():
    cfg, missing = _b2_config()
    if missing:
        return jsonify({"ok": False, "step": "environment", "missing": missing}), 500
    try:
        obj = _client(cfg).get_object(Bucket=cfg["bucket_name"], Key=TEST_IMAGE_KEY)
        return Response(obj["Body"].read(), mimetype=obj.get("ContentType") or "image/png", headers={"Cache-Control": "private, max-age=60"})
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 404 or code in ("404", "NoSuchKey", "NotFound"):
            return jsonify({"ok": False, "error": "Test image not found in B2", "object_key": TEST_IMAGE_KEY}), 404
        return jsonify({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}), 500


_order_cloud_initialized = False


def _order_cloud_auth_source():
    import hmac
    supplied = (request.headers.get("X-Order-Sync-Key") or "").strip()
    configured = [
        ("CN", (os.environ.get("ORDER_SYNC_API_KEY_CN") or "").strip()),
        ("CL", (os.environ.get("ORDER_SYNC_API_KEY_CL") or "").strip()),
        ("LEGACY", (os.environ.get("ORDER_SYNC_API_KEY") or "").strip()),
    ]
    active = [(source, key) for source, key in configured if key]
    if not active:
        return None, (jsonify({"ok": False, "error": "ORDER sync API key is not configured"}), 503)
    for source, key in active:
        if supplied and hmac.compare_digest(supplied, key):
            return source, None
    return None, (jsonify({"ok": False, "error": "unauthorized"}), 401)


def _ensure_order_cloud_tables():
    global _order_cloud_initialized
    if not _order_cloud_initialized:
        from services.order_cloud_service import init_order_cloud_tables
        from services.order_cloud_asset_service import init_order_cloud_asset_table
        init_order_cloud_tables()
        init_order_cloud_asset_table()
        _order_cloud_initialized = True


@b2_test_bp.route("/api/order-cloud/health", methods=["GET"])
def order_cloud_health():
    try:
        _ensure_order_cloud_tables()
        return jsonify({"ok": True, "service": "order-cloud", "phase": 3, "assets": "sha256-b2"})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/api/order-cloud/sync/order", methods=["POST"])
def order_cloud_sync_order():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        from services.order_cloud_service import sync_order
        result = sync_order(request.get_json(silent=True) or {}, source_site=source_site)
        return jsonify({"ok": True, "result": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/api/order-cloud/debug/order/<path:order_number>", methods=["GET"])
def order_cloud_debug_order(order_number):
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        from services.order_cloud_service import get_order
        result = get_order(order_number)
        if result is None:
            return jsonify({"ok": False, "error": "not found"}), 404
        return jsonify({"ok": True, "order": result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/api/order-cloud/debug/customer/<path:customer_key>", methods=["GET"])
def order_cloud_debug_customer(customer_key):
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        from services.order_cloud_service import get_customer_space
        from services.order_cloud_asset_service import attach_assets_to_space
        result = get_customer_space(customer_key)
        if result is None:
            return jsonify({"ok": False, "error": "not found"}), 404
        return jsonify({"ok": True, "space": attach_assets_to_space(result)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/api/order-cloud/assets/check", methods=["POST"])
def order_cloud_asset_check():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        from services.order_cloud_asset_service import check_image_hash
        payload = request.get_json(silent=True) or {}
        return jsonify({"ok": True, "result": check_image_hash(payload.get("sha256"), payload.get("content_type"))})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/api/order-cloud/assets/register", methods=["POST"])
def order_cloud_asset_register():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        from services.order_cloud_asset_service import register_existing_image
        payload = request.get_json(silent=True) or {}
        result = register_existing_image(payload.get("order_number"), payload.get("workflow_key"), payload.get("sha256"), payload.get("content_type"), source_site=source_site)
        return jsonify({"ok": True, "result": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/api/order-cloud/assets/upload", methods=["POST"])
def order_cloud_asset_upload():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        from services.order_cloud_asset_service import MAX_IMAGE_BYTES, upload_image
        image = request.files.get("file")
        if image is None:
            return jsonify({"ok": False, "error": "multipart field 'file' is required"}), 400
        data = image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            return jsonify({"ok": False, "error": "image exceeds 15 MB limit"}), 413
        result = upload_image(
            request.form.get("order_number"),
            request.form.get("workflow_key"),
            data,
            image.mimetype,
            source_site=source_site,
            expected_sha256=request.form.get("sha256"),
        )
        return jsonify({"ok": True, "result": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/api/order-cloud/share/create", methods=["POST"])
def order_cloud_create_share():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        from services.order_cloud_service import create_live_share
        payload = request.get_json(silent=True) or {}
        result = create_live_share(payload.get("customer_key"), source_site=source_site, expires_hours=payload.get("expires_hours", 24), permanent=bool(payload.get("permanent", False)))
        token = result.pop("token")
        expires_at = result.get("expires_at")
        result["expires_at"] = expires_at.isoformat() if expires_at else None
        result["share_url"] = request.host_url.rstrip("/") + "/share/" + token
        return jsonify({"ok": True, "result": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/api/order-cloud/share/revoke", methods=["POST"])
def order_cloud_revoke_share():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        from services.order_cloud_service import revoke_live_share
        changed = revoke_live_share((request.get_json(silent=True) or {}).get("token"))
        return jsonify({"ok": True, "revoked": changed})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def _resolve_public_share_or_response(token):
    from services.order_cloud_service import resolve_live_share
    share, state = resolve_live_share(token)
    if state == "not_found":
        return None, Response("Enlace no encontrado.", status=404, mimetype="text/plain")
    if state == "expired":
        return None, Response("Este enlace ha expirado.", status=410, mimetype="text/plain")
    if state == "revoked":
        return None, Response("Este enlace ya no está disponible.", status=410, mimetype="text/plain")
    return share, None


@b2_test_bp.route("/share/<token>", methods=["GET"])
def order_cloud_public_share(token):
    try:
        _ensure_order_cloud_tables()
        from services.order_cloud_service import get_customer_space
        from services.order_cloud_asset_service import attach_assets_to_space
        share, error_response = _resolve_public_share_or_response(token)
        if error_response:
            return error_response
        space = get_customer_space(share.get("customer_key"))
        if not space:
            return Response("No hay información disponible.", status=404, mimetype="text/plain")
        attach_assets_to_space(space)
        return render_template("customer_share_live.html", space=space, share=share, share_token=token)
    except Exception:
        return Response("Servicio temporalmente no disponible.", status=503, mimetype="text/plain")


@b2_test_bp.route("/share/<token>/asset/<asset_key>", methods=["GET"])
def order_cloud_public_asset(token, asset_key):
    try:
        _ensure_order_cloud_tables()
        from services.order_cloud_asset_service import get_asset, read_private_asset
        share, error_response = _resolve_public_share_or_response(token)
        if error_response:
            return error_response
        asset = get_asset(asset_key)
        if not asset or asset.get("customer_key") != share.get("customer_key"):
            return Response("Archivo no encontrado.", status=404, mimetype="text/plain")
        data, content_type = read_private_asset(asset)
        return Response(data, mimetype=content_type, headers={"Cache-Control": "private, max-age=300", "ETag": '"' + str(asset.get("sha256") or "") + '"'})
    except FileNotFoundError:
        return Response("Archivo no encontrado.", status=404, mimetype="text/plain")
    except Exception:
        return Response("Servicio temporalmente no disponible.", status=503, mimetype="text/plain")
