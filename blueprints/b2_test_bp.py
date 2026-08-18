"""Temporary isolated Backblaze B2 connectivity test."""

import os
import boto3
from botocore.exceptions import ClientError
from flask import Blueprint, jsonify

b2_test_bp = Blueprint("b2_test", __name__)


@b2_test_bp.route("/api/test-b2", methods=["GET"])
def test_b2():
    key_id = (os.environ.get("B2_KEY_ID") or "").strip()
    application_key = (os.environ.get("B2_APPLICATION_KEY") or "").strip()
    bucket_name = (os.environ.get("B2_BUCKET_NAME") or "").strip()
    endpoint = (os.environ.get("B2_ENDPOINT") or "").strip().rstrip("/")

    missing = [name for name, value in (
        ("B2_KEY_ID", key_id),
        ("B2_APPLICATION_KEY", application_key),
        ("B2_BUCKET_NAME", bucket_name),
        ("B2_ENDPOINT", endpoint),
    ) if not value]

    if missing:
        return jsonify({"ok": False, "step": "environment", "missing": missing}), 500

    test_key = "_test/render_connection_test.txt"
    test_content = b"RENDER TO BACKBLAZE B2 TEST OK"
    s3 = None
    uploaded = False

    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key_id,
            aws_secret_access_key=application_key,
        )
        s3.put_object(Bucket=bucket_name, Key=test_key, Body=test_content, ContentType="text/plain")
        uploaded = True

        obj = s3.get_object(Bucket=bucket_name, Key=test_key)
        if obj["Body"].read() != test_content:
            raise RuntimeError("Downloaded B2 test content does not match")

        s3.delete_object(Bucket=bucket_name, Key=test_key)
        uploaded = False

        try:
            s3.head_object(Bucket=bucket_name, Key=test_key)
            raise RuntimeError("B2 test object still exists after deletion")
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = exc.response.get("Error", {}).get("Code")
            if status != 404 and code not in ("404", "NoSuchKey", "NotFound"):
                raise

        return jsonify({
            "ok": True,
            "message": "Render -> Backblaze B2 TEST SUCCESS",
            "bucket": bucket_name,
            "upload": "OK",
            "read": "OK",
            "delete": "OK",
        })
    except Exception as exc:
        if uploaded and s3 is not None:
            try:
                s3.delete_object(Bucket=bucket_name, Key=test_key)
            except Exception:
                pass
        result = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
        if isinstance(exc, ClientError):
            result["error_code"] = exc.response.get("Error", {}).get("Code")
            result["http_status"] = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return jsonify(result), 500
