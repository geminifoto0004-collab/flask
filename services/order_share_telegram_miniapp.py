"""Secure Telegram Mini App directory for existing active ORDER share links.

The public HTML shell contains no customer data.  The API accepts only fresh,
Telegram-signed Mini App initData and rechecks private staff-group membership.
It is exclusively read-only and uses the existing share-link signing scheme.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl

from flask import Blueprint, jsonify, request, send_file

miniapp_bp = Blueprint("order_share_telegram_miniapp", __name__)
_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "order_share_telegram"
_MAX_INIT_DATA_AGE = 3600
_BOT_USERNAME = "xingwangorderlinkbot"


def _bot():
    from blueprints.automation_hub import storage
    matches = [item for item in storage.list_bots()
               if item.get("plugin_key") == "ORDER_SHARES"
               and item.get("enabled")
               and str(item.get("bot_username") or "").lower() == _BOT_USERNAME]
    if len(matches) != 1:
        return None
    return storage.get_bot_by_key(matches[0]["bot_key"], with_token=True)


def validate_init_data(raw, bot_token, now=None):
    """Return verified Telegram numeric user ID or None; never trust initDataUnsafe."""
    if not isinstance(raw, str) or not raw or len(raw) > 12000 or not bot_token:
        return None
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=40)
        data = dict(pairs)
        if len(data) != len(pairs):
            return None
        signature = data.pop("hash", "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"),
                          hashlib.sha256).digest()
        digest = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest, signature.lower()):
            return None
        current = time.time() if now is None else now
        authorized_at = int(data["auth_date"])
        if authorized_at > current + 30 or current - authorized_at > _MAX_INIT_DATA_AGE:
            return None
        user = json.loads(data["user"])
        if not isinstance(user, dict) or user.get("is_bot"):
            return None
        user_id = user.get("id")
        return user_id if type(user_id) is int and user_id > 0 else None
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return None


@miniapp_bp.after_request
def security_headers(response):
    response.headers["Cache-Control"] = "no-store, private, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@miniapp_bp.get("/telegram/order-shares")
def index():
    response = send_file(_TEMPLATE_DIR / "index.html", mimetype="text/html")
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self' https://telegram.org; "
        "style-src 'unsafe-inline'; connect-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'none'; "
        "frame-ancestors https://web.telegram.org"
    )
    return response


@miniapp_bp.get("/telegram/order-shares/app.js")
def client_script():
    return send_file(_TEMPLATE_DIR / "app.js",
                     mimetype="text/javascript")


@miniapp_bp.post("/api/telegram/order-shares/directory")
def directory():
    from services import order_share_telegram_access as access
    from services import order_share_telegram_bot as lookup

    if request.content_length is not None and request.content_length > 15000:
        return jsonify(ok=False, error="invalid_request"), 413
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error="invalid_request"), 400
    raw = data.get("initData")
    if not access.configured():
        return jsonify(ok=False, error="not_available"), 503

    bot = _bot()
    if not bot or not bot.get("token") or not bot.get("enabled"):
        return jsonify(ok=False, error="not_available"), 503
    user_id = validate_init_data(raw, bot["token"])
    if user_id is None:
        return jsonify(ok=False, error="telegram_auth_required"), 403
    if not access.is_authorized(bot["bot_key"], user_id, bot["token"]):
        return jsonify(ok=False, error="not_staff"), 403

    try:
        rows = lookup._lookup_all_full()
        items = [
            {
                "name": " ".join(str(r.get("customer_name")
                                      or r.get("customer_key") or "").split()),
                "url": lookup._share_url(r),
                "expires": lookup._date(r["expires_at"]) if r.get("expires_at") else None,
            }
            for r in rows
        ]
    except Exception:
        # Do not log URL tokens, group membership or raw Telegram initData.
        return jsonify(ok=False, error="temporarily_unavailable"), 503
    return jsonify(ok=True, items=items, count=len(items))
