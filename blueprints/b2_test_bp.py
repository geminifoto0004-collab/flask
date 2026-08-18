"""Temporary isolated Backblaze B2 connectivity tests."""

import os
import uuid

import boto3
from botocore.exceptions import ClientError
from flask import Blueprint, Response, jsonify, request

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
    """Simple customer-facing page that displays a private B2 image through Render."""
    html = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Estado del pedido</title>
<style>
body{margin:0;background:#f5f6f8;font-family:Arial,sans-serif;color:#222}.wrap{max-width:760px;margin:0 auto;padding:22px 14px}.card{background:#fff;border-radius:14px;padding:22px;box-shadow:0 2px 12px rgba(0,0,0,.08)}h1{font-size:24px;margin:0 0 18px}.status{display:inline-block;background:#fff3cd;padding:7px 12px;border-radius:20px;font-weight:700}.row{margin:10px 0}.label{color:#777}.photo{width:100%;height:auto;margin-top:20px;border-radius:10px;display:block}.note{font-size:13px;color:#888;margin-top:16px}
</style>
</head>
<body><div class="wrap"><div class="card">
<h1>Estado del pedido</h1>
<div class="row"><span class="label">Pedido:</span> G-TEST-001</div>
<div class="row"><span class="label">Estado:</span> <span class="status">En producción</span></div>
<div class="row"><span class="label">Actualización:</span> Prueba de Render + B2 privado</div>
<img class="photo" src="/share/test/image" alt="Imagen del pedido">
<div class="note">Página temporal de prueba.</div>
</div></div></body></html>"""
    return Response(html, mimetype="text/html")


@b2_test_bp.route("/share/test/image", methods=["GET"])
def share_test_image():
    """Proxy the known private B2 test image without exposing B2 credentials."""
    cfg, missing = _b2_config()
    if missing:
        return jsonify({"ok": False, "step": "environment", "missing": missing}), 500
    try:
        obj = _client(cfg).get_object(Bucket=cfg["bucket_name"], Key=TEST_IMAGE_KEY)
        data = obj["Body"].read()
        content_type = obj.get("ContentType") or "image/png"
        return Response(data, mimetype=content_type, headers={"Cache-Control": "private, max-age=60"})
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 404 or code in ("404", "NoSuchKey", "NotFound"):
            return jsonify({"ok": False, "error": "Test image not found in B2", "object_key": TEST_IMAGE_KEY}), 404
        return jsonify({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}), 500
