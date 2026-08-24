"""Use ORDER's native guest templates on Render while preserving all fast caches."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import re
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, unquote

from flask import Response, current_app, g, has_request_context, request

from blueprints.b2_test_bp import b2_test_bp
from services import order_public_share_fast as _fast
from services import order_public_share_multi_b2_page as _page
from services import order_share_direct_cover_cache as _direct
from services import order_share_render_cache as _render

ROOT = Path(__file__).resolve().parents[1]
ORDER = ROOT / "order_tracking"
TPL = ORDER / "templates" / "tracking"
STATIC = ORDER / "static"
_LOCK = threading.RLock()
_COMPILED = {}
_ORIG_RENDER = _render._ORIGINAL_RENDER_TEMPLATE
_ORIG_FILTER = _fast._filter_space

_STATIC_RE = re.compile(r"\{\{\s*url_for\(\s*['\"]tracking_bp\.static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_GUEST_RE = re.compile(r"\{\{\s*url_for\(\s*['\"]tracking_bp\.local_guest_customer['\"]\s*,\s*token\s*=\s*token\s*\)\s*\}\}")


def _load_status_module():
    path = ORDER / "status_definitions.py"
    spec = importlib.util.spec_from_file_location("_order_native_status", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _status_module():
    return _load_status_module()


def _key(value):
    return str(value or "").strip().upper()


def _label(value, lang):
    key = _key(value)
    try:
        item = (_status_module().STATUS_LABELS or {}).get(key) or {}
        text = str(item.get(lang) or "").strip()
        if text:
            return text
    except Exception:
        pass
    return "进行中" if lang == "zh_cn" else "En proceso"


def _stage(value):
    key = _key(value)
    try:
        groups = _status_module().STAGE_GROUPS or {}
        for name in ("draft", "sampling", "production", "shipping"):
            if key in ((groups.get(name) or {}).get("status_keys") or []):
                return name
        if key in ((groups.get("completed") or {}).get("status_keys") or []):
            return "shipping"
    except Exception:
        pass
    return "order"


def _is_image(asset):
    return isinstance(asset, dict) and (
        _key(asset.get("asset_type")) == "IMAGE"
        or str(asset.get("content_type") or "").lower().startswith("image/")
    )


def _route(token, asset):
    key = str((asset or {}).get("asset_key") or "").strip().lower()
    return f"/share/{token}/image/{key}" if len(key) == 64 else ""


def _images(order, workflow, token):
    assets = [a for a in (order.get("assets") or []) if _is_image(a)]
    wf_keys = {
        str((workflow or {}).get("workflow_key") or "").strip(),
        str((workflow or {}).get("workflow_number") or "").strip(),
    } - {""}
    if workflow:
        groups = [
            ("workflow", [a for a in assets if str(a.get("workflow_key") or "").strip() in wf_keys]),
            ("order", [a for a in assets if not str(a.get("workflow_key") or "").strip()]),
        ]
    else:
        groups = [("order", assets)]
    result = []
    for kind, rows in groups:
        for asset in rows:
            url = _route(token, asset)
            if url:
                result.append({
                    "name": str(asset.get("display_name") or asset.get("asset_key") or "Imagen"),
                    "media_type": "image", "pdf_page_number": 0, "pdf_page_count": 0,
                    "url": url, "preview_url": url, "_source_kind": kind,
                })
    return result


def _pick(workflow, order, key):
    value = (workflow or {}).get(key)
    return value if value not in (None, "") else order.get(key)


def _card(order, workflow, token):
    wf_no = str((workflow or {}).get("workflow_number") or (workflow or {}).get("workflow_key") or "").strip()
    order_no = str(order.get("order_number") or "").strip()
    status = ((workflow or {}).get("status") or order.get("order_status") or "")
    detail_key = wf_no or order_no
    return {
        "workflow_number": wf_no, "order_number": order_no, "current_status": status,
        "status_zh": _label(status, "zh_cn"), "status_es": _label(status, "es"),
        "product_name": _pick(workflow, order, "product_name"),
        "production_type": _pick(workflow, order, "production_type"),
        "product_code": _pick(workflow, order, "product_code"),
        "quantity": _pick(workflow, order, "quantity"),
        "order_date": order.get("order_date"),
        "expected_delivery_date": _pick(workflow, order, "expected_delivery_date"),
        "images": _images(order, workflow, token),
        "detail_url": f"/share/{token}/order/{quote(detail_key, safe='')}",
    }


def _cards(space, token):
    result = []
    for order in (space or {}).get("orders") or []:
        if not isinstance(order, dict):
            continue
        workflows = [w for w in (order.get("workflows") or []) if isinstance(w, dict)]
        if workflows:
            result.extend(_card(order, w, token) for w in workflows)
        else:
            result.append(_card(order, None, token))
    return result


def _expiry(share):
    value = (share or {}).get("expires_at")
    if not value:
        return 0
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except Exception:
            return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


@lru_cache(maxsize=1)
def _fingerprint():
    h = hashlib.sha256()
    for path in (
        Path(__file__), TPL / "guest_customer.html", TPL / "guest_order.html",
        ORDER / "status_definitions.py", STATIC / "css" / "guest.css",
        STATIC / "js" / "ui_i18n.js", STATIC / "js" / "theme.js",
        STATIC / "js" / "guest_reports.js",
    ):
        if path.is_file():
            h.update(path.read_bytes())
    return h.hexdigest()


def _customer_context(space, share, token):
    customer = (space or {}).get("customer") or {}
    expires = _expiry(share)
    return {
        "customer_name": str(customer.get("customer_name") or customer.get("customer_key") or ""),
        "token": token, "orders": _cards(space, token), "expires_at_epoch": expires,
        "is_permanent": not bool(expires), "allow_pdf_download": False, "pdf_count": 0,
        "allow_report_pdf_download": False, "STATIC_VER": _fingerprint()[:12],
        "cloud_guest_base_url": f"/share/{token}",
    }


def _history(workflow):
    return [{
        "date": item.get("action_date") or "", "status_key": _key(item.get("status") or item.get("to_status")),
        "status_es": _label(item.get("status") or item.get("to_status"), "es"),
        "status_zh": _label(item.get("status") or item.get("to_status"), "zh_cn"),
    } for item in ((workflow or {}).get("timeline") or []) if isinstance(item, dict)]


def _stages(card, workflow):
    defs = [("order", "Pedido"), ("draft", "Diseño"), ("sampling", "Muestra"), ("production", "Producción"), ("shipping", "Envío")]
    dates = {"order": card.get("order_date")} if card.get("order_date") else {}
    for item in ((workflow or {}).get("timeline") or []):
        if isinstance(item, dict) and item.get("action_date"):
            dates.setdefault(_stage(item.get("status") or item.get("to_status")), item.get("action_date"))
    keys = [x[0] for x in defs]
    current = _stage(card.get("current_status"))
    idx = keys.index(current) if current in keys else 0
    return [{"key": key, "label_es": es, "date": dates.get(key) or "", "state": "done" if i < idx else "current" if i == idx else "pending"} for i, (key, es) in enumerate(defs)]


def _order_context(space, share, token, detail_key):
    for order in (space or {}).get("orders") or []:
        if not isinstance(order, dict):
            continue
        workflows = [w for w in (order.get("workflows") or []) if isinstance(w, dict)]
        for workflow in workflows:
            if detail_key in {str(workflow.get("workflow_number") or "").strip(), str(workflow.get("workflow_key") or "").strip()}:
                card = _card(order, workflow, token)
                expires = _expiry(share)
                customer = (space or {}).get("customer") or {}
                return {"customer_name": str(customer.get("customer_name") or ""), "order": card, "history": _history(workflow), "timeline_stages": _stages(card, workflow), "token": token, "expires_at_epoch": expires, "is_permanent": not bool(expires), "STATIC_VER": _fingerprint()[:12], "cloud_guest_base_url": f"/share/{token}"}
        if not workflows and detail_key == str(order.get("order_number") or "").strip():
            card = _card(order, None, token)
            expires = _expiry(share)
            customer = (space or {}).get("customer") or {}
            return {"customer_name": str(customer.get("customer_name") or ""), "order": card, "history": [], "timeline_stages": _stages(card, None), "token": token, "expires_at_epoch": expires, "is_permanent": not bool(expires), "STATIC_VER": _fingerprint()[:12], "cloud_guest_base_url": f"/share/{token}"}
    return None


def _source(name):
    text = (TPL / name).read_text("utf-8")
    text = _STATIC_RE.sub(lambda m: "/tracking/static/tracking/" + m.group(1), text)
    return _GUEST_RE.sub("{{ cloud_guest_base_url }}", text)


def _template(app, name):
    key = (id(app), name, _fingerprint())
    with _LOCK:
        if key in _COMPILED:
            return _COMPILED[key]
    with app.app_context():
        tpl = app.jinja_env.from_string(_source(name))
    with _LOCK:
        _COMPILED.clear(); _COMPILED[key] = tpl
    return tpl


def _render_native(app, name, context):
    with app.app_context():
        return _template(app, name).render(**context)


def _native_skeleton(app, share, bundle):
    space = copy.deepcopy((bundle or {}).get("space") or {})
    if not space:
        return None
    _ORIG_FILTER(space, share)
    return _render_native(app, "guest_customer.html", _customer_context(space, share, _render._TOKEN_PLACEHOLDER))


def _native_fallback(template_name, *args, **kwargs):
    if template_name != _render._TEMPLATE:
        return _ORIG_RENDER(template_name, *args, **kwargs)
    return _render_native(current_app._get_current_object(), "guest_customer.html", _customer_context(kwargs.get("space") or {}, kwargs.get("share") or {}, str(kwargs.get("share_token") or "")))


def _cover_assets(space, limit=6):
    result = []
    for order in (space or {}).get("orders") or []:
        assets = [a for a in (order.get("assets") or []) if _is_image(a) and a.get("object_key")]
        workflows = [w for w in (order.get("workflows") or []) if isinstance(w, dict)]
        if not workflows and assets:
            result.append(assets[0])
        for workflow in workflows:
            keys = {str(workflow.get("workflow_key") or "").strip(), str(workflow.get("workflow_number") or "").strip()} - {""}
            chosen = next((a for a in assets if str(a.get("workflow_key") or "").strip() in keys), None) or next((a for a in assets if not str(a.get("workflow_key") or "").strip()), None)
            if chosen:
                result.append(chosen)
            if len(result) >= limit:
                return result
    return result[:limit]


def _inject(html, token, space):
    if not html or not token:
        return html
    started = time.perf_counter(); count = hits = misses = 0; sign_ms = 0.0; urls = []
    try:
        for asset in _cover_assets(space, getattr(_render, "_DIRECT_COVER_LIMIT", 6)):
            key = str(asset.get("asset_key") or "").strip().lower()
            marker = attr = None
            for one_attr in ("src", "data-src"):
                marker = next((m for m in _direct._route_markers(token, key, one_attr) if m in html), None)
                if marker:
                    attr = one_attr; break
            if not marker:
                continue
            try:
                url, _, hit, one_ms = _direct._cached_signed_get(asset)
            except Exception:
                continue
            from html import escape
            html = html.replace(marker, f'{attr}="{escape(str(url), quote=True)}"', 1)
            urls.append(url); count += 1; sign_ms += float(one_ms or 0); hits += int(hit); misses += int(not hit)
        return _direct._inject_resource_hints(html, urls)
    finally:
        if has_request_context():
            g._order_direct_cover_count = count; g._order_direct_cover_sign_ms = sign_ms
            g._order_direct_cover_cache_hits = hits; g._order_direct_cover_cache_misses = misses
            g._order_direct_cover_inject_ms = (time.perf_counter() - started) * 1000.0


@b2_test_bp.before_app_request
def _native_detail():
    if request.method != "GET":
        return None
    parts = (request.path or "").strip("/").split("/")
    if len(parts) != 4 or parts[0] != "share" or parts[2] != "order":
        return None
    token = parts[1]
    share, bundle, error = _page._load_page_data(token)
    if error:
        return error
    space = bundle.get("space") or {}; _fast._filter_space(space, share)
    context = _order_context(space, share, token, unquote(parts[3]))
    if not context:
        return Response("Pedido no encontrado.", 404, mimetype="text/plain")
    response = Response(_render_native(current_app._get_current_object(), "guest_order.html", context), mimetype="text/html")
    response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    response.headers["X-Order-UI-Source"] = "order_tracking-native"
    return response


@b2_test_bp.after_app_request
def _ui_header(response):
    parts = (request.path or "").strip("/").split("/")
    if parts and parts[0] == "share" and (len(parts) == 2 or (len(parts) == 4 and parts[2] == "order")):
        response.headers["X-Order-UI-Source"] = "order_tracking-native"
    return response


def install():
    _render._compute_template_hash = lambda app: _fingerprint()
    _render._render_skeleton = _native_skeleton
    _render._ORIGINAL_RENDER_TEMPLATE = _native_fallback
    _render._cover_assets = _cover_assets
    _render._inject_direct_cover_urls = _inject


install()
