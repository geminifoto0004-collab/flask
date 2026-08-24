"""Persistent pre-render cache for ORDER public share HTML.

The public page already keeps token metadata and customer snapshots hot. This module
also persists the token-neutral rendered HTML skeleton in TiDB so a newly started
Render/Gunicorn worker can serve the very first customer without compiling/rendering
the large Jinja template.

Only customer-visible HTML with a fixed token placeholder is stored. Raw share tokens,
image bytes, B2 credentials, local paths, phone/payment/deposit data are never stored.
"""
from __future__ import annotations

import copy
import hashlib
import threading

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

_VARIANT_HTML = {}
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


def _variant_key_from_parts(customer_key, history_scope, include_cancelled):
    if not _TEMPLATE_HASH:
        return ""
    raw = (
        f"{_TEMPLATE_HASH}\0"
        f"{str(customer_key or '').strip()}\0"
        f"{str(history_scope or 'current').strip().lower() or 'current'}\0"
        f"{1 if include_cancelled else 0}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _variant_key(share):
    customer_key, history_scope, include_cancelled = _share_variant(share)
    if not customer_key:
        return ""
    return _variant_key_from_parts(customer_key, history_scope, include_cancelled)


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
    if not app:
        return ""
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
    if not key or not html:
        return ""
    with _LOCK:
        _VARIANT_HTML[key] = html
    return key


def _persist_variant(share, html):
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


def _load_persisted_memory(customer_key=None):
    if not _TEMPLATE_HASH:
        return 0
    _ensure_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        if customer_key:
            cur.execute(
                f"""SELECT cache_key, html
                    FROM {_TABLE}
                    WHERE template_hash=? AND customer_key=?""",
                (_TEMPLATE_HASH, str(customer_key).strip()),
            )
        else:
            cur.execute(
                f"""SELECT cache_key, html
                    FROM {_TABLE}
                    WHERE template_hash=?""",
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
                _VARIANT_HTML[key] = html
                loaded += 1
    return loaded


def _load_persisted_variant(share):
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
                _VARIANT_HTML[key] = html
            return html
    except Exception as exc:
        print(
            f"[WARN] ORDER share persisted HTML read skipped: "
            f"{type(exc).__name__}: {exc}"
        )
    return None


def _active_variants(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return []

    variants = {}
    try:
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT token_hash, customer_key, mode, status, source_site,
                          created_at, expires_at, history_scope, include_cancelled
                   FROM cloud_share_tokens
                   WHERE customer_key=? AND status='active'""",
                (customer_key,),
            )
            rows = [get_row_dict(row, cur) for row in cur.fetchall()]
        finally:
            conn.close()
        for row in rows:
            share, error = _page._validate_share(row)
            if error or not share:
                continue
            variant = _share_variant(share)
            variants[variant] = share
    except Exception as exc:
        print(
            f"[WARN] ORDER share active HTML variants read skipped for {customer_key}: "
            f"{type(exc).__name__}: {exc}"
        )

    if variants:
        return list(variants.values())

    # Safe fallback if the direct variant query was unavailable.
    with _page._cache_lock:
        for _token_hash_value, item in list(_hot._HASH_TOKEN_CACHE.items()):
            try:
                share = item[1]
            except Exception:
                continue
            if str((share or {}).get("customer_key") or "").strip() != customer_key:
                continue
            variant = _share_variant(share)
            variants[variant] = dict(share or {})
    return list(variants.values())


def _load_bundle(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return None

    cached = _page._cache_get(_page._space_cache, customer_key)
    if cached is not None:
        return copy.deepcopy(cached)

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
        if bundle:
            _ORIGINAL_CACHE_SPACE(customer_key, bundle)
            return bundle
    except Exception as exc:
        print(
            f"[WARN] ORDER share HTML snapshot load skipped for {customer_key}: "
            f"{type(exc).__name__}: {exc}"
        )
    return None


def _render_placeholder(app, share, bundle):
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


def _prebuild_customer(customer_key, bundle=None):
    app = _APP
    customer_key = str(customer_key or "").strip()
    if not app or not customer_key or not _TEMPLATE_HASH:
        return 0

    if bundle is None:
        bundle = _load_bundle(customer_key)
    if not bundle:
        return 0

    shares = _active_variants(customer_key)
    if not shares:
        return 0

    rendered = {}
    built = 0
    for share in shares:
        variant = _share_variant(share)
        html = rendered.get(variant)
        if html is None:
            try:
                html = _render_placeholder(app, share, bundle)
            except Exception as exc:
                print(
                    f"[WARN] ORDER share HTML pre-render failed for {customer_key}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            if not html:
                continue
            rendered[variant] = html

        _memory_put(share, html)
        try:
            _persist_variant(share, html)
        except Exception as exc:
            print(
                f"[WARN] ORDER share HTML persist failed for {customer_key}: "
                f"{type(exc).__name__}: {exc}"
            )
        built += 1
    return built


def _cache_space_and_prerender(customer_key, bundle):
    result = _ORIGINAL_CACHE_SPACE(customer_key, bundle)
    try:
        _prebuild_customer(customer_key, bundle)
    except Exception as exc:
        print(
            f"[WARN] ORDER share HTML cache refresh skipped for {customer_key}: "
            f"{type(exc).__name__}: {exc}"
        )
    return result


def _cached_render_template(template_name, *args, **kwargs):
    if template_name != _TEMPLATE:
        return _ORIGINAL_RENDER_TEMPLATE(template_name, *args, **kwargs)

    token = str(kwargs.get("share_token") or "").strip()
    share = kwargs.get("share") or {}
    if not token:
        return _ORIGINAL_RENDER_TEMPLATE(template_name, *args, **kwargs)

    token_hash = _token_hash(token)
    variant_key = _variant_key(share)

    with _LOCK:
        token_item = _TOKEN_HTML.get(token_hash)
        if token_item and token_item.get("variant_key") == variant_key:
            html = token_item.get("html")
        else:
            html = _VARIANT_HTML.get(variant_key)

    if not html:
        # Normally unused after startup; protects correctness if startup TiDB was down.
        html = _load_persisted_variant(share)

    if html:
        with _LOCK:
            _TOKEN_HTML[token_hash] = {
                "customer_key": str((share or {}).get("customer_key") or "").strip(),
                "variant_key": variant_key,
                "html": html,
            }
        return html.replace(_TOKEN_PLACEHOLDER, token)

    # Last-resort correctness fallback. Persist immediately so later requests and
    # future workers no longer pay the large Jinja render.
    rendered = _ORIGINAL_RENDER_TEMPLATE(template_name, *args, **kwargs)
    if isinstance(rendered, str) and rendered:
        skeleton = rendered.replace(token, _TOKEN_PLACEHOLDER)
        _memory_put(share, skeleton)
        try:
            _persist_variant(share, skeleton)
        except Exception as exc:
            print(
                f"[WARN] ORDER share HTML fallback persist skipped: "
                f"{type(exc).__name__}: {exc}"
            )
    return rendered


def _revoke_and_drop_html(raw_token):
    changed = _ORIGINAL_REVOKE(raw_token)
    if changed:
        with _LOCK:
            _TOKEN_HTML.pop(_token_hash(raw_token), None)
    return changed


@b2_test_bp.record_once
def _order_share_html_startup(state):
    """Load current-template skeletons, then backfill any missing active variant."""
    global _APP, _TEMPLATE_HASH
    _APP = state.app
    _TEMPLATE_HASH = _compute_template_hash(_APP)
    if not _TEMPLATE_HASH:
        return

    try:
        loaded = _load_persisted_memory()
        print(f"[ORDER] persisted share HTML loaded: {loaded}")
    except Exception as exc:
        print(
            f"[WARN] ORDER persisted share HTML startup load skipped: "
            f"{type(exc).__name__}: {exc}"
        )

    customers = set()
    try:
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT DISTINCT customer_key
                   FROM cloud_share_tokens
                   WHERE status='active' AND customer_key IS NOT NULL"""
            )
            for row in cur.fetchall():
                data = get_row_dict(row, cur) or {}
                customer_key = str(data.get("customer_key") or "").strip()
                if customer_key:
                    customers.add(customer_key)
        finally:
            conn.close()
    except Exception as exc:
        print(
            f"[WARN] ORDER active share HTML startup scan skipped: "
            f"{type(exc).__name__}: {exc}"
        )

    for customer_key in customers:
        shares = _active_variants(customer_key)
        with _LOCK:
            missing = any(_variant_key(share) not in _VARIANT_HTML for share in shares)
        if missing:
            _prebuild_customer(customer_key)


def install():
    _hot._cache_space = _cache_space_and_prerender
    _page.render_template = _cached_render_template
    if callable(_ORIGINAL_REVOKE):
        _cloud_service.revoke_live_share = _revoke_and_drop_html


install()
