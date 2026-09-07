"""Keep backend ORDER search rows consistent with the home table.

The home table computes derived values from the latest workflow history row. The
legacy search endpoints use simpler SQL and can therefore return stale dates/waiting
days after a history date is edited. This runtime wrapper keeps the existing search
permissions/discovery SQL, then overlays active rows with the same canonical rows used
by `/api/orders/all-for-filter`.
"""
from __future__ import annotations

from functools import wraps

from flask import current_app, jsonify

_PATCHED = "_order_search_canonical_patch_v1"
_ENDPOINTS = (
    "tracking_bp.api_global_search",
    "tracking_bp.api_orders_advanced_search",
)


def _merge_rows(search_rows, canonical_rows):
    by_workflow = {}
    no_workflow_by_order = {}

    for raw in canonical_rows or []:
        item = dict(raw or {})
        workflow_number = str(item.get("workflow_number") or "").strip()
        order_number = str(item.get("order_number") or "").strip()
        if workflow_number:
            by_workflow[workflow_number] = item
        elif order_number and item.get("no_workflow"):
            no_workflow_by_order[order_number] = item

    merged = []
    for raw in search_rows or []:
        item = dict(raw or {})
        workflow_number = str(item.get("workflow_number") or "").strip()
        order_number = str(item.get("order_number") or "").strip()
        canonical = by_workflow.get(workflow_number) if workflow_number else None
        if canonical is None and not workflow_number and order_number:
            canonical = no_workflow_by_order.get(order_number)

        if canonical is not None:
            # Search-only placeholders must survive the canonical overlay.
            search_only = {
                key: item[key]
                for key in ("workflow_count", "others_workflow")
                if key in item
            }
            item.update(canonical)
            item.update(search_only)
        merged.append(item)
    return merged


def _copy_non_entity_headers(source, target):
    for key, value in source.headers.items():
        if key.lower() in {"content-type", "content-length"}:
            continue
        target.headers[key] = value


def _wrap_view(original):
    @wraps(original)
    def wrapped(*args, **kwargs):
        response = current_app.make_response(original(*args, **kwargs))
        if response.status_code != 200:
            return response

        payload = response.get_json(silent=True)
        if not isinstance(payload, dict) or not payload.get("success"):
            return response
        orders = payload.get("orders")
        if not isinstance(orders, list):
            return response

        try:
            # Import lazily: installer runs only after order_tracking has fully loaded
            # and its blueprint has been registered on the Flask app.
            from order_tracking import get_current_user_context, _load_home_orders_from_active_source

            ctx = get_current_user_context()
            canonical_rows = _load_home_orders_from_active_source(
                ctx.get("role", "viewer"), ctx.get("id")
            )
            payload["orders"] = _merge_rows(orders, canonical_rows)
            if "count" in payload:
                payload["count"] = len(payload["orders"])
        except Exception as exc:
            current_app.logger.warning(
                "ORDER search canonical overlay skipped: %s: %s",
                type(exc).__name__, exc,
            )
            return response

        replacement = jsonify(payload)
        replacement.status_code = response.status_code
        _copy_non_entity_headers(response, replacement)
        return replacement

    setattr(wrapped, _PATCHED, True)
    return wrapped


def install_search_result_canonical_patch(app):
    """Install after `tracking_bp` has been registered on *app*."""
    patched = 0
    for endpoint in _ENDPOINTS:
        view = app.view_functions.get(endpoint)
        if view is None or getattr(view, _PATCHED, False):
            continue
        app.view_functions[endpoint] = _wrap_view(view)
        patched += 1
    if patched:
        print(f"[ORDER] search canonical patch ready endpoints={patched}")
    return patched
