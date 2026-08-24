"""Persistent pre-render cache for ORDER public share HTML.

The ORDER share data path is already prewarmed.  This module turns that same hot
snapshot into token-neutral HTML before Render starts serving requests, and persists
the HTML skeleton in TiDB for future workers/deploys.

Important invariants:
- raw share tokens are never persisted;
- no image bytes, B2 credentials, local paths, phone/payment/deposit data are stored;
- a request normally performs only an in-memory lookup plus placeholder replacement;
- snapshot refreshes rebuild the HTML skeleton immediately;
- only the first visible cover images receive short-lived direct B2 GET URLs at
  response time; the underlying canonical cloud object is never copied or moved.
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time
from html import escape as _html_escape

from flask import g, has_request_context

from blueprints.b2_test_bp import b2_test_bp
from database import get_cursor, get_db_connection, get_row_dict
from services import order_cloud_service as _cloud_service
from services import order_customer_share_hot_cache as _hot
from services import order_customer_share_snapshot as _snapshot
from services import order_public_share_fast as _fast
from services import order_public_share_multi_b2_page as _page

_TEMPLATE = "customer_share_live_fast.html"
_TOKEN_PLACEHOLDER = "__ORDER_SHARE_TOKEN_PLACEHOLDER_6E61C970__"
_TABLE = "cloud_customer_share_html_cache"
_DIRECT_COVER_LIMIT = 6
_DIRECT_SIGN_SECONDS = 600

_HTML = {}
_TOKEN_HTML = {}
_LOCK = threading.RLock()
_TABLE_LOCK = threading.Lock()
_TABLE_READY = False
_APP = None
_TEMPLATE_HASH = ""

_ORIGINAL_RENDER_TEMPLATE = _page.render_template
_ORIGINAL_CACHE_SPACE = _hot._cache_space
_ORIGINAL_REVOKE = getattr(_cloud_service, "revoke_live_share", None)


def _token_hash(raw_token):
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def _share_variant(share):
    share = share or {}
    return (
        str(share.get("customer_key") or "").strip(),
        str(share.get("history_scope") or "current").strip().lower() or "current",
        bool(share.get("include_cancelled")),
    )


def _variant_key(share):
    if not _TEMPLATE_HASH:
        return ""
    customer_key, history_scope, include_cancelled = _share_variant(share)
    if not customer_key:
        return ""
    raw = (
        f"{_TEMPLATE_HASH}\0{customer_key}\0{history_scope}\0"
        f"{1 if include_cancelled else 0}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ensure_table():
    global _TABLE_READY
    if _TABLE_READY:
        return
    with _TABLE_LOCK:
        if _TABLE_READY:
            return
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    cache_key VARCHAR(64) PRIMARY KEY,
                    customer_key VARCHAR(191) NOT NULL,
                    history_scope VARCHAR(32) NOT NULL DEFAULT 'current',
                    include_cancelled BOOLEAN NOT NULL DEFAULT FALSE,
                    template_hash VARCHAR(64) NOT NULL,
                    html LONGTEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_order_share_html_customer (customer_key),
                    INDEX idx_order_share_html_template (template_hash),
                    INDEX idx_order_share_html_updated (updated_at)
                )
                """
            )
            conn.commit()
            _TABLE_READY = True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _compute_template_hash(app):
    try:
        with app.app_context():
            source, _filename, _uptodate = app.jinja_env.loader.get_source(
                app.jinja_env, _TEMPLATE
            )
        return hashlib.sha256(str(source).encode("utf-8")).hexdigest()
    except Exception as exc:
        print(
            f"[WARN] ORDER share template fingerprint failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return ""


def _memory_put(share, html):
    key = _variant_key(share)
    if not key or not isinstance(html, str) or not html:
        return ""
    with _LOCK:
        _HTML[key] = html
    return key


def _persist(share, html):
    key = _variant_key(share)
    customer_key, history_scope, include_cancelled = _share_variant(share)
    if not key or not customer_key or not html or not _TEMPLATE_HASH:
        return
    _ensure_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(f"SELECT cache_key FROM {_TABLE} WHERE cache_key=? LIMIT 1", (key,))
        values = (
            customer_key,
            history_scope,
            bool(include_cancelled),
            _TEMPLATE_HASH,
            html,
            key,
        )
        if cur.fetchone():
            cur.execute(
                f"""UPDATE {_TABLE}
                    SET customer_key=?, history_scope=?, include_cancelled=?,
                        template_hash=?, html=?, updated_at=CURRENT_TIMESTAMP
                    WHERE cache_key=?""",
                values,
            )
        else:
            cur.execute(
                f"""INSERT INTO {_TABLE}
                    (customer_key, history_scope, include_cancelled,
                     template_hash, html, cache_key)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                values,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_all_persisted():
    if not _TEMPLATE_HASH:
        return 0
    _ensure_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            f"SELECT cache_key, html FROM {_TABLE} WHERE template_hash=?",
            (_TEMPLATE_HASH,),
        )
        rows = [get_row_dict(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()
    loaded = 0
    with _LOCK:
        for row in rows:
            key = str((row or {}).get("cache_key") or "").strip().lower()
            html = (row or {}).get("html")
            if key and isinstance(html, str) and html:
                _HTML[key] = html
                loaded += 1
    return loaded


def _load_one_persisted(share):
    key = _variant_key(share)
    if not key:
        return None
    try:
        _ensure_table()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                f"""SELECT html FROM {_TABLE}
                    WHERE cache_key=? AND template_hash=? LIMIT 1""",
                (key, _TEMPLATE_HASH),
            )
            row = cur.fetchone()
            data = get_row_dict(row, cur) if row else {}
        finally:
            conn.close()
        html = (data or {}).get("html")
        if isinstance(html, str) and html:
            with _LOCK:
                _HTML[key] = html
            return html
    except Exception as exc:
        print(
            f"[WARN] ORDER share persisted HTML read skipped: "
            f"{type(exc).__name__}: {exc}"
        )
    return None


def _hot_shares():
    """Return active share metadata already loaded by the hot-cache module.

    This is deliberately the first startup source.  The previous implementation
    enumerated customers through a new TiDB query during blueprint registration.  If
    that one startup query failed, the first real visitor had to render the entire
    Jinja page even though token+snapshot caches were already HIT.  Reusing the hot
    token cache removes that race.
    """
    shares = []
    with _page._cache_lock:
        for _token_hash_value, item in list(_hot._HASH_TOKEN_CACHE.items()):
            try:
                share = dict(item[1] or {})
            except Exception:
                continue
            share, error = _page._validate_share(share)
            if error or not share:
                continue
            if share.get("customer_key"):
                shares.append(share)
    return shares


def _db_shares():
    """Fallback/enrichment source for startup if the hot token cache was empty."""
    result = []
    try:
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT token_hash, customer_key, mode, status, source_site,
                          created_at, expires_at, history_scope, include_cancelled
                   FROM cloud_share_tokens
                   WHERE status='active' AND customer_key IS NOT NULL"""
            )
            rows = [get_row_dict(row, cur) for row in cur.fetchall()]
        finally:
            conn.close()
        for row in rows:
            share, error = _page._validate_share(row)
            if not error and share:
                result.append(share)
    except Exception as exc:
        print(
            f"[WARN] ORDER share HTML startup token scan skipped: "
            f"{type(exc).__name__}: {exc}"
        )
    return result


def _active_shares():
    by_variant = {}
    # Hot memory is authoritative for the startup fast path.  DB rows only add shares
    # that were not present there; they are not required for successful pre-render.
    for share in _hot_shares() + _db_shares():
        variant = _share_variant(share)
        if variant[0]:
            by_variant[variant] = share
    return list(by_variant.values())


def _bundle_for(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return None
    cached = _page._cache_get(_page._space_cache, customer_key)
    if cached is not None:
        return copy.deepcopy(cached)

    # Startup hot-cache normally makes this unnecessary, but a persisted snapshot is
    # a safe second source and still avoids rebuilding ORDER rows.
    try:
        _snapshot._ensure_table()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                f"SELECT payload FROM {_snapshot._TABLE} WHERE customer_key=? LIMIT 1",
                (customer_key,),
            )
            row = cur.fetchone()
            data = get_row_dict(row, cur) if row else {}
        finally:
            conn.close()
        bundle = _snapshot._decode_snapshot((data or {}).get("payload"))
        return bundle if bundle else None
    except Exception as exc:
        print(
            f"[WARN] ORDER share HTML snapshot load skipped for {customer_key}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None


def _render_skeleton(app, share, bundle):
    if not app or not share or not bundle:
        return None
    space = copy.deepcopy((bundle or {}).get("space") or {})
    if not space:
        return None
    _fast._filter_space(space, share)
    with app.app_context():
        template = app.jinja_env.get_template(_TEMPLATE)
        return template.render(
            space=space,
            share=share,
            share_token=_TOKEN_PLACEHOLDER,
        )


def _build_variant(share, bundle=None, persist=True):
    app = _APP
    customer_key = str((share or {}).get("customer_key") or "").strip()
    if not app or not customer_key or not _TEMPLATE_HASH:
        return False
    key = _variant_key(share)
    with _LOCK:
        if key and _HTML.get(key):
            return True
    if bundle is None:
        bundle = _bundle_for(customer_key)
    if not bundle:
        return False
    try:
        html = _render_skeleton(app, share, bundle)
    except Exception as exc:
        print(
            f"[WARN] ORDER share HTML pre-render failed for {customer_key}: "
            f"{type(exc).__name__}: {exc}"
        )
        return False
    if not html:
        return False
    _memory_put(share, html)
    if persist:
        try:
            _persist(share, html)
        except Exception as exc:
            # Memory pre-render is already enough to protect this worker. Persistence
            # is best-effort and will be retried on the next snapshot refresh/deploy.
            print(
                f"[WARN] ORDER share HTML persist failed for {customer_key}: "
                f"{type(exc).__name__}: {exc}"
            )
    return True


def _prebuild_all():
    shares = _active_shares()
    bundles = {}
    built = 0
    missing = 0
    for share in shares:
        customer_key = str(share.get("customer_key") or "").strip()
        key = _variant_key(share)
        with _LOCK:
            exists = bool(key and _HTML.get(key))
        if exists:
            continue
        if customer_key not in bundles:
            bundles[customer_key] = _bundle_for(customer_key)
        if _build_variant(share, bundle=bundles.get(customer_key)):
            built += 1
        else:
            missing += 1
    return {"shares": len(shares), "built": built, "missing": missing}


def _drop_customer(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return
    with _LOCK:
        stale = [
            key
            for key, item in list(_TOKEN_HTML.items())
            if str((item or {}).get("customer_key") or "").strip() == customer_key
        ]
        for key in stale:
            _TOKEN_HTML.pop(key, None)
        # Variant keys are hashes, so remove the customer's current variants by
        # recomputing keys from active share metadata.
        for share in _active_shares():
            if str(share.get("customer_key") or "").strip() == customer_key:
                _HTML.pop(_variant_key(share), None)


def _cache_space_and_prerender(customer_key, bundle):
    result = _ORIGINAL_CACHE_SPACE(customer_key, bundle)
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return result
    try:
        _drop_customer(customer_key)
        for share in _active_shares():
            if str(share.get("customer_key") or "").strip() == customer_key:
                _build_variant(share, bundle=bundle)
    except Exception as exc:
        print(
            f"[WARN] ORDER share HTML refresh skipped for {customer_key}: "
            f"{type(exc).__name__}: {exc}"
        )
    return result


def _cover_assets(space, limit=_DIRECT_COVER_LIMIT):
    """Return the first IMAGE asset for the first visible gallery orders."""
    result = []
    orders = (space or {}).get("orders") if isinstance(space, dict) else None
    if not isinstance(orders, list):
        return result
    for order in orders:
        if not isinstance(order, dict):
            continue
        assets = order.get("assets")
        if not isinstance(assets, list):
            continue
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            if str(asset.get("asset_type") or "").upper() != "IMAGE":
                continue
            if not asset.get("asset_key") or not asset.get("object_key"):
                continue
            result.append(asset)
            break
        if len(result) >= int(limit):
            break
    return result


def _inject_direct_cover_urls(html, token, space):
    """Replace only first gallery cover routes with short-lived direct B2 URLs.

    This removes the extra Browser -> Render -> 302 hop from the images users see
    first. Detail/full images keep the memory-authorized Render fallback path.
    """
    if not isinstance(html, str) or not html or not token:
        return html

    started = time.perf_counter()
    signed = 0
    try:
        from services import order_cloud_multi_b2_public as _media

        for asset in _cover_assets(space):
            asset_key = str(asset.get("asset_key") or "").strip().lower()
            if len(asset_key) != 64:
                continue
            route = f"/share/{token}/thumb/{asset_key}"
            marker = f'data-src="{route}"'
            if marker not in html:
                route = f"/share/{token}/image/{asset_key}"
                marker = f'data-src="{route}"'
            if marker not in html:
                continue
            try:
                url, _backend = _media._signed_get(asset, seconds=_DIRECT_SIGN_SECONDS)
            except Exception:
                continue
            html = html.replace(
                marker,
                f'data-src="{_html_escape(str(url), quote=True)}"',
                1,
            )
            signed += 1
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if has_request_context():
            g._order_direct_cover_count = signed
            g._order_direct_cover_sign_ms = elapsed_ms
    return html


def _cached_render_template(template_name, *args, **kwargs):
    if template_name != _TEMPLATE:
        return _ORIGINAL_RENDER_TEMPLATE(template_name, *args, **kwargs)

    token = str(kwargs.get("share_token") or "").strip()
    share = kwargs.get("share") or {}
    space = kwargs.get("space") or {}
    if not token:
        return _ORIGINAL_RENDER_TEMPLATE(template_name, *args, **kwargs)

    token_hash = _token_hash(token)
    variant_key = _variant_key(share)
    with _LOCK:
        token_item = _TOKEN_HTML.get(token_hash)
        if token_item and token_item.get("variant_key") == variant_key:
            html = token_item.get("html")
        else:
            html = _HTML.get(variant_key)

    if not html:
        html = _load_one_persisted(share)

    if html:
        with _LOCK:
            _TOKEN_HTML[token_hash] = {
                "customer_key": str((share or {}).get("customer_key") or "").strip(),
                "variant_key": variant_key,
                "html": html,
            }
        rendered = html.replace(_TOKEN_PLACEHOLDER, token)
        return _inject_direct_cover_urls(rendered, token, space)

    # Correctness fallback only.  It should not be reached when startup pre-render
    # succeeded, but if it is, immediately seed both memory and persistent cache.
    rendered = _ORIGINAL_RENDER_TEMPLATE(template_name, *args, **kwargs)
    if isinstance(rendered, str) and rendered:
        skeleton = rendered.replace(token, _TOKEN_PLACEHOLDER)
        _memory_put(share, skeleton)
        try:
            _persist(share, skeleton)
        except Exception as exc:
            print(
                f"[WARN] ORDER share HTML fallback persist skipped: "
                f"{type(exc).__name__}: {exc}"
            )
        rendered = _inject_direct_cover_urls(rendered, token, space)
    return rendered


def _revoke_and_drop_html(raw_token):
    changed = _ORIGINAL_REVOKE(raw_token)
    if changed:
        with _LOCK:
            _TOKEN_HTML.pop(_token_hash(raw_token), None)
    return changed


@b2_test_bp.record_once
def _order_share_html_startup(state):
    """Synchronously prepare HTML before Flask finishes blueprint registration."""
    global _APP, _TEMPLATE_HASH
    _APP = state.app
    _TEMPLATE_HASH = _compute_template_hash(_APP)
    if not _TEMPLATE_HASH:
        return

    loaded = 0
    try:
        loaded = _load_all_persisted()
    except Exception as exc:
        # Do not abort.  The already-hot token+snapshot memory can still be rendered
        # now, so the customer does not inherit a transient TiDB startup failure.
        print(
            f"[WARN] ORDER persisted share HTML startup load skipped: "
            f"{type(exc).__name__}: {exc}"
        )

    result = _prebuild_all()
    print(
        "[ORDER] share HTML startup ready: "
        f"persisted={loaded} active={result['shares']} "
        f"built={result['built']} missing={result['missing']}"
    )


def install():
    _hot._cache_space = _cache_space_and_prerender
    _page.render_template = _cached_render_template
    if callable(_ORIGINAL_REVOKE):
        _cloud_service.revoke_live_share = _revoke_and_drop_html


install()
