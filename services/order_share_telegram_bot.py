"""Private Telegram lookup for existing Render shares, via Automation Hub.

No local ORDER changes, new shares, order uploads or image reads. The Hub owns
token encryption and webhook verification; this plugin adds a numeric user-ID
allowlist and runs its small lookup/reply away from the Flask request thread.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import html
import logging
import os
import re
import threading
import time
from urllib.parse import urlsplit

import requests

_LOG = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="order-share-bot")
_SLOTS = threading.BoundedSemaphore(16)
_LOCK = threading.Lock()
_RECENT = {}
_LIMIT = 5


def _allowed_ids():
    raw = os.environ.get("ORDER_SHARE_TELEGRAM_ALLOWED_IDS", "")
    return {int(value) for value in re.split(r"[,;\s]+", raw.strip())
            if value.isdecimal() and int(value) > 0}


def _actor(update):
    message = update.get("message") if isinstance(update, dict) else None
    if not isinstance(message, dict):
        return None
    sender, chat = message.get("from") or {}, message.get("chat") or {}
    user_id, chat_id = sender.get("id"), chat.get("id")
    text = message.get("text")
    if (type(user_id) is not int or user_id <= 0 or type(chat_id) is not int
            or chat_id != user_id or chat.get("type") != "private"
            or sender.get("is_bot") or not isinstance(text, str)):
        return None
    return user_id, chat_id, text.strip()[:256]


def _current_bot_key():
    from blueprints.automation_hub import registry
    return registry.current_bot_key()


def _load_bot(bot_key):
    from blueprints.automation_hub import storage
    bot = storage.get_bot_by_key(bot_key, with_token=True)
    if (not bot or not bot.get("enabled") or bot.get("plugin_key") != "ORDER_SHARES"
            or not bot.get("webhook_secret")):
        return None
    return bot


def _base_url():
    from blueprints.automation_hub import settings
    base = str(settings.PUBLIC_BASE_URL or "").rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("A public HTTPS service URL is required")
    return base


def _lookup_shares(query):
    """One bounded SELECT. Use the same active/expiry rule as the directory."""
    from database import get_db_connection, get_cursor, get_row_dict
    literal = query.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
    pattern = "%" + literal + "%"
    conn = get_db_connection()
    try:
        cur = get_cursor(conn)
        cur.execute(
            """SELECT s.token_hash, s.customer_key,
                      COALESCE(NULLIF(c.customer_name,''), s.customer_key) AS customer_name,
                      s.created_at, s.expires_at
               FROM cloud_share_tokens s
               JOIN cloud_customers c ON c.customer_key=s.customer_key
               WHERE s.status='active' AND c.active=TRUE
                 AND (s.expires_at IS NULL OR s.expires_at>UTC_TIMESTAMP())
                 AND (LOWER(c.customer_name) LIKE ? ESCAPE '!'
                      OR LOWER(s.customer_key) LIKE ? ESCAPE '!')
               ORDER BY CASE WHEN LOWER(TRIM(c.customer_name))=? THEN 0 ELSE 1 END,
                        c.customer_name, s.created_at DESC, s.token_hash
               LIMIT ?""",
            (pattern, pattern, query.lower(), _LIMIT + 1),
        )
        return [get_row_dict(row, cur) or {} for row in cur.fetchall()]
    finally:
        conn.close()


def _date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%d-%m-%Y")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return "—"


def _name(value, limit=64):
    value = " ".join(str(value or "").split())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _share_url(row):
    from services.order_share_links import share_link_token
    return _base_url() + "/share/" + share_link_token(row.get("token_hash"))


def _search_reply(query, rows):
    if not rows:
        return "没有找到符合名称的有效分享。请换一个客户名称。", []
    lines = ["<b>客户分享链接</b>", "查询：" + html.escape(_name(query, 80))]
    buttons = []
    shown = 0
    for row in rows[:_LIMIT]:
        name = _name(row.get("customer_name") or row.get("customer_key"))
        url = _share_url(row)
        expiry = "永久" if not row.get("expires_at") else "至 " + _date(row["expires_at"])
        line = "\n<b>" + html.escape(name) + "</b>\n" + expiry + " · 建立 " + _date(row.get("created_at"))
        controls = [{"text": "打开 · " + _name(name, 30), "url": url}]
        if len(url) <= 256:
            controls.append({"text": "复制链接", "copy_text": {"text": url}})
        else:
            line += "\n<code>" + html.escape(url) + "</code>"
        if len("\n".join(lines) + line) > 3600:
            break
        lines.append(line)
        buttons.append(controls)
        shown += 1
    if len(rows) > shown:
        lines.append("\n还有更多有效分享，请输入更完整的客户名称。")
    return "\n".join(lines), buttons


def _send_reply(token, chat_id, text, buttons=()):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "link_preview_options": {"is_disabled": True}}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        response = requests.post("https://api.telegram.org/bot" + token + "/sendMessage",
                                 json=payload, timeout=10)
        if response.status_code != 200 or not response.json().get("ok"):
            raise ValueError("reply rejected")
    except Exception:
        # requests exceptions include the credential-bearing URL. Never expose it.
        raise RuntimeError("Telegram reply could not be delivered") from None


def _process(bot_key, user_id, chat_id, text):
    bot = _load_bot(bot_key)
    if not bot or not bot.get("token"):
        return
    command, _, argument = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    if command == "/id":
        return _send_reply(bot["token"], chat_id, "你的 Telegram ID：<code>" + str(user_id) + "</code>")
    if user_id not in _allowed_ids():
        return _send_reply(bot["token"], chat_id, "此账号没有查询权限。发送 /id 查看自己的 Telegram ID，再交给管理员设定。")
    if command in {"/start", "/help", "/links"} and (command != "/links" or not argument.strip()):
        return _send_reply(bot["token"], chat_id, "<b>客户分享链接</b>\n直接输入客户名称，例如 OSCAR 或 SERGIO。\n也可以输入 <code>/links OSCAR</code>。\n只显示有效分享，可直接打开或复制链接。")
    if text.startswith("/") and command != "/links":
        return _send_reply(bot["token"], chat_id, "输入客户名称，或用 <code>/links 客户名称</code> 查询。")
    query = " ".join((argument if command == "/links" else text).split())[:160]
    if not query:
        return
    try:
        rows = _lookup_shares(query)
        reply, buttons = _search_reply(query, rows)
    except Exception:
        reply, buttons = "分享资料暂时无法读取，请稍后重试。", []
        _LOG.warning("ORDER share lookup unavailable")
    _send_reply(bot["token"], chat_id, reply, buttons)


def handle_update(update):
    actor, bot_key = _actor(update), _current_bot_key()
    if actor is None or not bot_key:
        return False
    update_id = update.get("update_id")
    if type(update_id) is not int:
        return False
    now = time.monotonic()
    identity = (bot_key, update_id)
    with _LOCK:
        for key, at in list(_RECENT.items()):
            if now - at > 300:
                _RECENT.pop(key, None)
        if identity in _RECENT:
            return True
        if not _SLOTS.acquire(blocking=False):
            _LOG.warning("ORDER share bot queue full")
            return False
        _RECENT[identity] = now
        while len(_RECENT) > 512:
            _RECENT.pop(next(iter(_RECENT)))

    def work():
        try:
            _process(bot_key, *actor)
        except Exception:
            _LOG.warning("ORDER share bot reply unavailable")
        finally:
            _SLOTS.release()
    try:
        _EXECUTOR.submit(work)
    except Exception:
        _SLOTS.release()
        with _LOCK:
            _RECENT.pop(identity, None)
        raise RuntimeError("ORDER share bot could not queue the request") from None
    return True
