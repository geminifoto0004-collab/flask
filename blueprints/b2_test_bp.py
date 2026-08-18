"""Temporary isolated Backblaze B2 connectivity tests."""

import os
import uuid

import boto3
from botocore.exceptions import ClientError
from flask import Blueprint, jsonify, request

b2_test_bp = Blueprint("b2_test", __name__)


def _b2_config():
    values = {
        "key_id": (os.environ.get("B2_KEY_ID") or "").strip(),
        "application_key": (os.environ.get("B2_APPLICATION_KEY") or "").strip(),
        "bucket_name": (os.environ.get("B2_BUCKET_NAME") or "").strip(),
        "endpoint": (os.environ.get("B2_ENDPOINT") or "").strip().rstrip("/"),
    }
    missing = [
        env_name
        for env_name, value in (
            ("B2_KEY_ID", values["key_id"]),
            ("B2_APPLICATION_KEY", values["application_key"]),
            ("B2_BUCKET_NAME", values["bucket_name"]),
            ("B2_ENDPOINT", values["endpoint"]),
        )
        if not value
    ]
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
        s3.put_object(
            Bucket=cfg["bucket_name"],
            Key=test_key,
            Body=test_content,
            ContentType="text/plain",
        )
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

        return jsonify({
            "ok": True,
            "message": "Render -> Backblaze B2 TEST SUCCESS",
            "bucket": cfg["bucket_name"],
            "upload": "OK",
            "read": "OK",
            "delete": "OK",
        })
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
    """Receive one real image from a PC and keep it in B2 for inspection."""
    cfg, missing = _b2_config()
    if missing:
        return jsonify({"ok": False, "step": "environment", "missing": missing}), 500

    image = request.files.get("image")
    if image is None or not image.filename:
        return jsonify({"ok": False, "error": "multipart field 'image' is required"}), 400

    content_type = (image.mimetype or "").lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        return jsonify({
            "ok": False,
            "error": "Only JPEG, PNG and WEBP are allowed for this test",
            "content_type": content_type,
        }), 400

    data = image.read()
    if not data:
        return jsonify({"ok": False, "error": "Image is empty"}), 400

    max_bytes = 15 * 1024 * 1024
    if len(data) > max_bytes:
        return jsonify({"ok": False, "error": "Image exceeds 15 MB test limit"}), 413

    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }[content_type]
    object_key = f"_test/images/{uuid.uuid4().hex}{extension}"

    try:
        s3 = _client(cfg)
        s3.put_object(
            Bucket=cfg["bucket_name"],
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
        info = s3.head_object(Bucket=cfg["bucket_name"], Key=object_key)

        return jsonify({
            "ok": True,
            "message": "PC -> Render -> Backblaze B2 IMAGE UPLOAD SUCCESS",
            "bucket": cfg["bucket_name"],
            "object_key": object_key,
            "original_filename": image.filename,
            "content_type": content_type,
            "uploaded_bytes": len(data),
            "b2_size": info.get("ContentLength"),
            "note": "Test image is intentionally kept in B2 so it can be inspected, then deleted manually or by the next cleanup step.",
        })
    except Exception as exc:
        result = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
        if isinstance(exc, ClientError):
            result["error_code"] = exc.response.get("Error", {}).get("Code")
            result["http_status"] = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return jsonify(result), 500
