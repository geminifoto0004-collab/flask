"""Fast control-plane patch for ORDER direct B2 image publishing.

The direct path must never block Render on B2 health/HEAD calls. Presigned URL
creation is local cryptographic work; the PC performs the actual PUT. We only
reuse an object when the exact ORDER/workflow/sha metadata is already active in
TiDB. After a successful client PUT, direct-register trusts the successful HTTP
PUT and writes metadata without a second B2 HEAD round trip.
"""


def _configured_backend(svc, avoid_backend=""):
    avoid = str(avoid_backend or "").strip().lower()
    ordered = ["b2_primary", "b2_secondary"]
    if avoid in svc.BACKENDS:
        ordered = [x for x in ordered if x != avoid] + [avoid]
    for backend in ordered:
        cfg = svc._backend_config(backend, required=False)
        if cfg.get("configured"):
            return backend, cfg
    raise RuntimeError("Primary / Secondary B2 are not configured")


def fast_backend_health(force=False):
    """Configuration-only health hint. Never perform Render -> B2 probes here."""
    import services.order_cloud_asset_service as svc

    primary_cfg = svc._backend_config("b2_primary", required=False)
    secondary_cfg = svc._backend_config("b2_secondary", required=False)
    primary = {
        "status": "configured" if primary_cfg.get("configured") else "not_configured",
        "missing": primary_cfg.get("missing") or [],
    }
    secondary = {
        "status": "configured" if secondary_cfg.get("configured") else "not_configured",
        "missing": secondary_cfg.get("missing") or [],
    }
    selected = ""
    if primary_cfg.get("configured"):
        selected = "b2_primary"
    elif secondary_cfg.get("configured"):
        selected = "b2_secondary"
    return {"selected": selected, "primary": primary, "secondary": secondary}


def _exact_registered_asset(svc, order_number, workflow_key, sha256_hex):
    asset_key = svc._asset_key(str(order_number or "").strip(), str(workflow_key or "").strip() or None, sha256_hex)
    conn = svc.get_db_connection()
    cur = svc.get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, sha256, object_key, storage_backend, content_type, file_size
               FROM cloud_assets
               WHERE asset_key=? AND active=TRUE
               LIMIT 1""",
            (asset_key,),
        )
        row = cur.fetchone()
        return svc.get_row_dict(row, cur) if row else None
    finally:
        conn.close()


def fast_direct_presign(order_number, workflow_key, sha256_hex, content_type, file_size,
                        source_site=None, avoid_backend=None):
    """Return a presigned PUT URL without making any Render -> B2 network call."""
    import services.order_cloud_asset_service as svc

    order_number, _customer_key, workflow_key = svc._validate_order_target(order_number, workflow_key)
    sha256_hex = svc._validate_sha256(sha256_hex)
    content_type = svc._validate_content_type(content_type)
    file_size = int(file_size or 0)
    if file_size < 1 or file_size > svc.MAX_IMAGE_BYTES:
        raise ValueError("file_size is invalid")
    object_key = svc._object_key(sha256_hex, content_type)

    # Fast repeat-share path: only reuse when this exact ORDER/workflow already has
    # active metadata. This avoids a B2 HEAD and also avoids cross-order metadata loss.
    existing = _exact_registered_asset(svc, order_number, workflow_key, sha256_hex)
    if existing and str(existing.get("object_key") or "") == object_key:
        backend = str(existing.get("storage_backend") or "b2_primary").strip().lower()
        return {
            "exists": True,
            "sha256": sha256_hex,
            "content_type": content_type,
            "file_size": int(existing.get("file_size") or file_size),
            "object_key": object_key,
            "storage_backend": backend,
            "upload_url": "",
            "backend_selection": {"primary_status": "not_probed", "secondary_status": "not_probed"},
        }

    backend, cfg = _configured_backend(svc, avoid_backend=avoid_backend)
    s3 = svc._b2_client(cfg)
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": cfg["bucket_name"], "Key": object_key, "ContentType": content_type},
        ExpiresIn=300,
        HttpMethod="PUT",
    )
    return {
        "exists": False,
        "sha256": sha256_hex,
        "content_type": content_type,
        "file_size": file_size,
        "object_key": object_key,
        "storage_backend": backend,
        "upload_url": upload_url,
        "backend_selection": {"primary_status": "not_probed", "secondary_status": "not_probed"},
    }


def fast_direct_register(order_number, workflow_key, sha256_hex, content_type, file_size,
                         object_key, storage_backend, source_site=None):
    """Register metadata after the client's successful presigned PUT, with no B2 HEAD."""
    import services.order_cloud_asset_service as svc

    sha256_hex = svc._validate_sha256(sha256_hex)
    content_type = svc._validate_content_type(content_type)
    object_key = svc._validate_object_key(object_key, sha256_hex, content_type)
    storage_backend = str(storage_backend or "b2_primary").strip().lower()
    if storage_backend not in svc.BACKENDS:
        raise ValueError("invalid storage_backend")
    file_size = int(file_size or 0)
    if file_size < 1 or file_size > svc.MAX_IMAGE_BYTES:
        raise ValueError("file_size is invalid")

    result = svc._upsert_asset_metadata(
        order_number, workflow_key, sha256_hex, object_key, content_type,
        file_size, source_site=source_site, storage_backend=storage_backend,
    )
    result["deduplicated"] = False
    result["uploaded_to_b2"] = True
    result["direct_upload"] = True
    result["register_verified_by"] = "successful_client_put"
    return result


def install():
    import services.order_cloud_asset_service as svc
    svc.backend_health = fast_backend_health
    svc.direct_presign = fast_direct_presign
    svc.direct_register = fast_direct_register
    return True
