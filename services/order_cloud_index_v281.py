"""V281 batched, read-only TiDB index for local roster/Dictionary comparison.

This endpoint returns metadata only. It never writes TiDB, touches B2, lists B2
objects, or downloads customer payloads to the desktop.
"""
from __future__ import annotations

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _order_cloud_auth_source
from database import get_cursor, get_db_connection, get_db_connection_for_target, get_row_dict


_MAX_CUSTOMERS = 200
_MAX_PAGE = 2000


class RosterChanged(ValueError):
    pass


def _norm(value):
    return " ".join(str(value or "").upper().split())


def _clean_customer_keys(value):
    if not isinstance(value, list):
        raise ValueError("customer_keys must be a list")
    if len(value) > _MAX_CUSTOMERS:
        raise ValueError("customer_keys exceeds 200")
    out = []
    seen = set()
    for raw in value:
        key = str(raw or "").strip()
        norm = _norm(key)
        if not key or not norm:
            raise ValueError("customer_keys cannot contain blank values")
        if norm not in seen:
            seen.add(norm)
            out.append(key)
    return out


def _parse_cursor(cursor, entity):
    if cursor in (None, ""):
        return None
    if not isinstance(cursor, dict):
        raise ValueError("cursor must be an object or null")
    customer_key = str(cursor.get("customer_key") or "").strip()
    item_key = str(cursor.get("order_number" if entity == "orders" else "asset_key") or "").strip()
    if not customer_key or not item_key:
        raise ValueError("cursor is incomplete")
    return customer_key, item_key


def _next_cursor(row, entity):
    return {
        "customer_key": str(row.get("customer_key") or ""),
        ("order_number" if entity == "orders" else "asset_key"): str(
            row.get("order_number" if entity == "orders" else "asset_key") or ""
        ),
    }


def _load_share_context(cur, customer_keys):
    placeholders = ",".join(["?"] * len(customer_keys))
    cur.execute(
        "SELECT token_hash,customer_key,show_images,show_workflow_images,show_pdf_pages "
        "FROM cloud_share_tokens WHERE status='active' "
        "AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP) "
        "AND customer_key IN (" + placeholders + ")",
        tuple(customer_keys),
    )
    tokens_by_customer = {}
    tokens_by_hash = {}
    for raw in cur.fetchall():
        row = get_row_dict(raw, cur) or {}
        token_hash = str(row.get("token_hash") or "")
        customer_key = str(row.get("customer_key") or "").strip()
        if not token_hash or not customer_key:
            continue
        token = {
            "token_hash": token_hash,
            "customer_key": customer_key,
            "show_images": bool(row.get("show_images")),
            "show_workflow_images": bool(row.get("show_workflow_images")),
            "show_pdf_pages": bool(row.get("show_pdf_pages")),
        }
        tokens_by_customer.setdefault(_norm(customer_key), []).append(token)
        tokens_by_hash[token_hash] = token
    missing = [key for key in customer_keys if not tokens_by_customer.get(_norm(key))]
    if missing:
        raise RosterChanged("WEB share roster changed during index read; refresh and retry")

    visibility_by_token = {}
    token_hashes = list(tokens_by_hash)
    for offset in range(0, len(token_hashes), 500):
        part = token_hashes[offset:offset + 500]
        cur.execute(
            "SELECT token_hash,order_number,show_order,show_images,show_workflow_images,show_logistics "
            "FROM cloud_share_order_visibility WHERE token_hash IN (" + ",".join(["?"] * len(part)) + ")",
            tuple(part),
        )
        for raw in cur.fetchall():
            row = get_row_dict(raw, cur) or {}
            token_hash = str(row.get("token_hash") or "")
            order_number = str(row.get("order_number") or "")
            if token_hash and order_number:
                visibility_by_token.setdefault(token_hash, {})[order_number] = {
                    "show_order": bool(row.get("show_order", True)),
                    "show_images": row.get("show_images"),
                    "show_workflow_images": row.get("show_workflow_images"),
                    "show_logistics": row.get("show_logistics"),
                }
    return tokens_by_customer, tokens_by_hash, visibility_by_token


def _order_customer_visible(order, tokens, visibility_by_token):
    if not bool(order.get("active", True)):
        return False
    status = str(order.get("order_status") or "").strip().upper()
    if status and status != "ACTIVE":
        return False
    order_number = str(order.get("order_number") or "")
    return any(
        bool(visibility_by_token.get(token["token_hash"], {}).get(order_number, {}).get("show_order", True))
        for token in tokens
    )


def _asset_customer_visible(asset, order, tokens, visibility_by_token):
    if (not order or not bool(asset.get("active", True))
            or not bool(asset.get("customer_visible", True))):
        return False
    if not _order_customer_visible(order, tokens, visibility_by_token):
        return False
    order_number = str(asset.get("order_number") or "")
    workflow_key = str(asset.get("workflow_key") or "").strip()
    asset_type = str(asset.get("asset_type") or "").strip().upper()
    for token in tokens:
        override = visibility_by_token.get(token["token_hash"], {}).get(order_number, {})
        if not bool(override.get("show_order", True)):
            continue
        if asset_type in {"PDF", "PDF_PAGE"}:
            visible = token.get("show_pdf_pages", True)
        elif workflow_key:
            override_value = override.get("show_workflow_images")
            visible = token.get("show_workflow_images", True) if override_value is None else bool(override_value)
        else:
            override_value = override.get("show_images")
            visible = token.get("show_images", True) if override_value is None else bool(override_value)
        if visible:
            return True
    return False


def _serialize_time(value):
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _fetch_page(cur, entity, customer_keys, cursor, limit):
    key_placeholders = ",".join(["?"] * len(customer_keys))
    cursor_clause = ""
    params = list(customer_keys)
    if cursor:
        cursor_clause = (
            " AND (customer_key>? OR (customer_key=? AND "
            + ("order_number" if entity == "orders" else "asset_key")
            + ">?))"
        )
        params.extend([cursor[0], cursor[0], cursor[1]])
    if entity == "orders":
        sql = (
            "SELECT order_number,customer_key,order_status,active,"
            "COALESCE(sync_fingerprint,SHA2(render_payload,256)) AS fp "
            "FROM cloud_orders WHERE customer_key IN (" + key_placeholders + ")"
            + cursor_clause + " ORDER BY customer_key,order_number LIMIT ?"
        )
    else:
        sql = (
            "SELECT asset_key,customer_key,order_number,workflow_key,asset_type,sha256,"
            "object_key,storage_backend,content_type,file_size,active,customer_visible,updated_at "
            "FROM cloud_assets WHERE customer_key IN (" + key_placeholders + ")"
            + cursor_clause + " ORDER BY customer_key,asset_key LIMIT ?"
        )
    params.append(int(limit) + 1)
    cur.execute(sql, tuple(params))
    rows = [get_row_dict(raw, cur) or {} for raw in cur.fetchall()]
    page = rows[:limit]
    next_value = _next_cursor(page[-1], entity) if len(rows) > limit and page else None
    return page, next_value


def _asset_order_rows(cur, assets):
    numbers = list(dict.fromkeys(str(row.get("order_number") or "").strip() for row in assets
                                 if str(row.get("order_number") or "").strip()))
    if not numbers:
        return {}
    out = {}
    for offset in range(0, len(numbers), 500):
        part = numbers[offset:offset + 500]
        cur.execute(
            "SELECT order_number,order_status,active FROM cloud_orders WHERE order_number IN ("
            + ",".join(["?"] * len(part)) + ")",
            tuple(part),
        )
        for raw in cur.fetchall():
            row = get_row_dict(raw, cur) or {}
            out[str(row.get("order_number") or "")] = row
    return out


@b2_test_bp.route("/api/order-cloud/sync/orders-index", methods=["POST"])
def order_cloud_sync_orders_index_v281():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        body = request.get_json(silent=True) or {}
        entity = str(body.get("entity") or "orders").strip().lower()
        if entity not in {"orders", "assets"}:
            return jsonify({"ok": False, "error": "entity must be orders or assets"}), 400
        customer_keys = _clean_customer_keys(body.get("customer_keys") or [])
        try:
            limit = int(body.get("limit") or _MAX_PAGE)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "limit must be an integer"}), 400
        if not 1 <= limit <= _MAX_PAGE:
            return jsonify({"ok": False, "error": "limit must be 1..2000"}), 400
        cursor = _parse_cursor(body.get("cursor"), entity)
        requested_target = str(body.get("target") or "").strip().upper()
        if requested_target and requested_target not in {"TIDB1", "TIDB2"}:
            return jsonify({"ok": False, "error": "target must be TIDB1 or TIDB2"}), 400
        if not customer_keys:
            return jsonify({"ok": True, "result": {
                "target": requested_target or None, "entity": entity,
                "items": [], "next_cursor": None, "count": 0,
            }})

        if requested_target:
            conn = get_db_connection_for_target(requested_target)
            conn.active_target = requested_target
        else:
            conn = get_db_connection()
        target = str(getattr(conn, "active_target", "") or "").strip().upper()
        if target not in {"TIDB1", "TIDB2"}:
            conn.close()
            return jsonify({"ok": False, "error": "active TiDB target is unavailable"}), 503
        cur = get_cursor(conn)
        try:
            tokens_by_customer, _tokens_by_hash, visibility_by_token = _load_share_context(cur, customer_keys)
            page, next_cursor = _fetch_page(cur, entity, customer_keys, cursor, limit)
            if entity == "orders":
                items = []
                for row in page:
                    tokens = tokens_by_customer.get(_norm(row.get("customer_key")), [])
                    items.append({
                        "order_number": str(row.get("order_number") or ""),
                        "customer_key": str(row.get("customer_key") or ""),
                        "fp": str(row.get("fp") or "").lower(),
                        "status": str(row.get("order_status") or ""),
                        "active": bool(row.get("active")),
                        "customer_visible": _order_customer_visible(row, tokens, visibility_by_token),
                    })
            else:
                parent_orders = _asset_order_rows(cur, page)
                items = []
                for row in page:
                    tokens = tokens_by_customer.get(_norm(row.get("customer_key")), [])
                    order = parent_orders.get(str(row.get("order_number") or ""))
                    object_key = str(row.get("object_key") or "")
                    asset_key = str(row.get("asset_key") or "")
                    items.append({
                        "asset_id": asset_key,
                        "asset_key": asset_key,
                        "customer_key": str(row.get("customer_key") or ""),
                        "order_number": str(row.get("order_number") or ""),
                        "workflow_key": str(row.get("workflow_key") or ""),
                        "asset_type": str(row.get("asset_type") or ""),
                        "sha256": str(row.get("sha256") or "").lower(),
                        "object_key": object_key,
                        "storage_backend": str(row.get("storage_backend") or ""),
                        "content_type": str(row.get("content_type") or ""),
                        "file_size": int(row.get("file_size") or 0),
                        "active": bool(row.get("active")),
                        "customer_visible": bool(row.get("customer_visible", True)),
                        "public_visible": _asset_customer_visible(row, order, tokens, visibility_by_token),
                        "b2_registered": bool(object_key),
                        "updated_at": _serialize_time(row.get("updated_at")),
                    })
            return jsonify({"ok": True, "result": {
                "target": target, "entity": entity, "items": items,
                "next_cursor": next_cursor, "count": len(items),
            }})
        finally:
            conn.close()
    except RosterChanged as exc:
        return jsonify({"ok": False, "error": str(exc), "code": "ROSTER_CHANGED"}), 409
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
