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
_PAGE_SIZE = 8
_MENU_LABEL = "📋 全部客戶"
_MENU_KEYBOARD = {"keyboard": [[{"text": _MENU_LABEL}]],
                  "resize_keyboard": True, "is_persistent": True,
                  "one_time_keyboard": False,
                  "input_field_placeholder": "輸入客戶名稱，如 SERGIO"}


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


def _group_actor(update):
    """Queries work in the configured staff group; /groupid also works before configuration."""
    message = update.get("message") if isinstance(update, dict) else None
    if not isinstance(message, dict):
        return None
    sender, chat = message.get("from") or {}, message.get("chat") or {}
    user_id, chat_id = sender.get("id"), chat.get("id")
    from services import order_share_telegram_access as access

    text = message.get("text")
    if (type(user_id) is not int or user_id <= 0 or type(chat_id) is not int
            or chat_id >= 0 or chat.get("type") not in {"group", "supergroup"}
            or sender.get("is_bot") or not isinstance(text, str)):
        return None
    text = text.strip()[:256]
    if not text:
        return None
    configured_group = access.group_id()
    if chat_id == configured_group:
        return user_id, chat_id, text
    # Let administrators find the group ID during first-time setup; all data
    # lookups are forbidden outside the configured group.
    if configured_group is None and re.fullmatch(
            r"/groupid(?:@[A-Za-z0-9_]{5,32})?", text, flags=re.I):
        return user_id, chat_id, "/groupid"
    return None

def _callback_actor(update):
    callback = update.get("callback_query") if isinstance(update, dict) else None
    if not isinstance(callback, dict):
        return None
    sender, message = callback.get("from") or {}, callback.get("message") or {}
    chat = message.get("chat") or {}
    user_id, chat_id = sender.get("id"), chat.get("id")
    data = str(callback.get("data") or "")
    match = re.fullmatch(r"order_shares:all:([1-9][0-9]{0,3})", data)
    callback_id = callback.get("id")
    from services import order_share_telegram_access as access

    private_chat = user_id == chat_id and chat.get("type") == "private"
    staff_group = (access.group_id() == chat_id
                   and chat.get("type") in {"group", "supergroup"})
    if (not match or not isinstance(callback_id, str) or not callback_id
            or type(user_id) is not int or user_id <= 0 or type(chat_id) is not int
            or not (private_chat or staff_group) or sender.get("is_bot")):
        return None
    return user_id, chat_id, "/all " + match.group(1), callback_id


def _answer_callback(token, callback_id):
    # Clear Telegram's progress indicator; errors do not disclose credentials.
    try:
        requests.post("https://api.telegram.org/bot" + token + "/answerCallbackQuery",
                      json={"callback_query_id": callback_id}, timeout=5)
    except Exception:
        pass


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
    """Bounded partial-name lookup; search words can appear in any order.

    Parameters are always bound, and SQL LIKE metacharacters are escaped.
    This is substring/keyword matching, not typo-tolerant fuzzy spelling.
    """
    from database import get_db_connection, get_cursor, get_row_dict

    terms = query.lower().split()[:16]
    if not terms:
        return []
    predicates = []
    values = []
    for term in terms:
        literal = term.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        pattern = "%" + literal + "%"
        predicates.append(
            "(LOWER(c.customer_name) LIKE ? ESCAPE '!' "
            "OR LOWER(s.customer_key) LIKE ? ESCAPE '!')"
        )
        values.extend((pattern, pattern))
    where = " AND ".join(predicates)
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
                 AND """ + where + """
               ORDER BY CASE WHEN LOWER(TRIM(c.customer_name))=? THEN 0 ELSE 1 END,
                        c.customer_name, s.created_at DESC, s.token_hash
               LIMIT ?""",
            (*values, query.lower(), _LIMIT + 1),
        )
        return [get_row_dict(row, cur) or {} for row in cur.fetchall()]
    finally:
        conn.close()


def _lookup_all(page):
    """Read only active, unexpired shares; return one extra row for next-page UI."""
    from database import get_db_connection, get_cursor, get_row_dict
    offset = (page - 1) * _PAGE_SIZE
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
               ORDER BY c.customer_name, s.created_at DESC, s.token_hash
               LIMIT ? OFFSET ?""",
            (_PAGE_SIZE + 1, offset),
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


def _copy_buttons(entries):
    """One compact copy grid; the number maps to the linked full name above."""
    if not entries:
        return []
    if len(entries) == 1:
        return [[{"text": "📋 複製連結", "copy_text": {"text": entries[0][1]}}]]
    buttons = [{"text": "📋" + str(index), "copy_text": {"text": url}}
               for index, url in entries]
    return [buttons[pos:pos + 4] for pos in range(0, len(buttons), 4)]


def _search_reply(query, rows, limit=_LIMIT, more_message=None, start_at=1):
    """Clickable full names plus compact numbered native Telegram copy buttons."""
    if not rows:
        return "沒有找到符合名稱的有效分享。請換一個客戶名稱。", []
    lines = ["<b>📋 客戶分享 · " + html.escape(_name(query, 80)) + "</b>",
             "點藍色姓名開啟連結："]
    entries = []
    shown = 0
    for row in rows[:limit]:
        name = html.escape(" ".join(str(
            row.get("customer_name") or row.get("customer_key") or "").split()))
        url = _share_url(row)
        expiry = "永久" if not row.get("expires_at") else "至 " + _date(row["expires_at"])
        line = (str(start_at + shown) + '. <a href="' + html.escape(url, quote=True) +
                '">' + name + "</a>  ·  " + html.escape(expiry))
        if len("\n".join(lines + [line])) > 3500:
            break
        lines.append(line)
        # Telegram's CopyTextButton limits copied text to 256 characters.
        if 1 <= len(url) <= 256:
            entries.append((start_at + shown, url))
        else:
            # Rare long URLs stay copyable by long pressing monospace link text.
            extra = "<code>" + html.escape(url) + "</code>"
            if len("\n".join(lines + [extra])) < 3600:
                lines.append(extra)
        shown += 1
    if entries and len(entries) > 1:
        lines.append("📋 點下方對應編號可複製連結")
    if len(rows) > shown:
        lines.append(more_message or "還有更多結果，請輸入更完整的客戶名稱。")
    return "\n".join(lines), _copy_buttons(entries)


def _all_reply(page, rows):
    text, buttons = _search_reply(
        "全部有效分享 · 第 " + str(page) + " 頁",
        rows,
        limit=_PAGE_SIZE,
        more_message="還有更多有效分享，點「下一頁」。",
        start_at=(page - 1) * _PAGE_SIZE + 1,
    )
    if not rows:
        text = "這一頁沒有有效分享。"
    navigation = []
    if page > 1:
        navigation.append({"text": "◀ 上一頁", "callback_data": "order_shares:all:" + str(page - 1)})
    navigation.append({"text": "📋 全部客戶", "callback_data": "order_shares:all:1"})
    if len(rows) > _PAGE_SIZE and page < 9999:
        navigation.append({"text": "下一頁 ▶", "callback_data": "order_shares:all:" + str(page + 1)})
    buttons.append(navigation)
    return text, buttons


def _send_reply(token, chat_id, text, buttons=(), *, show_menu=False):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "link_preview_options": {"is_disabled": True}}
    if show_menu:
        payload["reply_markup"] = _MENU_KEYBOARD
    elif buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        response = requests.post("https://api.telegram.org/bot" + token + "/sendMessage",
                                 json=payload, timeout=10)
        if response.status_code != 200 or not response.json().get("ok"):
            raise ValueError("reply rejected")
    except Exception:
        # requests exceptions include the credential-bearing URL. Never expose it.
        raise RuntimeError("Telegram reply could not be delivered") from None


def _process(bot_key, user_id, chat_id, text, callback_id=None):
    from services import order_share_telegram_access as access

    bot = _load_bot(bot_key)
    if not bot or not bot.get("token"):
        return
    if callback_id:
        _answer_callback(bot["token"], callback_id)
    command, _, argument = text.partition(" ")
    command_name, mention_sep, mention = command.partition("@")
    command = command_name.lower()
    if mention_sep and mention.lower() != str(bot.get("bot_username") or "").lower():
        return  # Command addressed to another bot

    configured_group = access.group_id()
    staff_group = configured_group is not None and chat_id == configured_group
    private_chat = chat_id == user_id
    if command == "/groupid" and chat_id < 0:
        if configured_group is None or staff_group:
            return _send_reply(bot["token"], chat_id,
                               "此群组 ID：<code>" + str(chat_id) + "</code>")
        return
    if not (private_chat or staff_group):
        return
    if command == "/id":
        return _send_reply(bot["token"], chat_id, "你的 Telegram ID：<code>" + str(user_id) + "</code>")

    # Check staff membership for both group and private queries on every request.
    # Legacy numeric-ID allowances apply only to private chats before group setup.
    try:
        authorized = (
            access.is_authorized(bot_key, user_id, bot["token"])
            if access.configured() else (private_chat and user_id in _allowed_ids())
        )
    except Exception:
        authorized = False
    if not authorized:
        reply = (
            "此账号不在公司私人群组，或群组成员资料暂时无法验证。"
            "请管理员邀请你加入公司私人 Telegram 群组；加入后重新发送 /start。"
            if access.configured()
            else "管理员尚未设置公司私人群组，请联系管理员。"
        )
        return _send_reply(bot["token"], chat_id, reply)

    if command in {"/start", "/help", "/menu", "/links"} and (
            command != "/links" or not argument.strip()) or text.strip() in {
                "選單", "菜单", "功能表", "menu", "MENU"}:
        return _send_reply(
            bot["token"], chat_id,
            "<b>XINGWANG ORDER LINK</b>\n已開啟下方「📋 全部客戶」快捷鍵盤，"
            "點一下即可查看有效分享。\n也可以輸入 SERGIO、CONDO SERGIO 搜尋客戶。"
            "\n藍色客戶名稱可以開啟連結，📋 編號可以複製連結。",
            show_menu=True,
        )
    all_aliases = {"all", "todo", "todos", "全部", "全部客戶", "全部客户",
                   _MENU_LABEL.casefold(), "📋 全部客户"}
    is_all = (command in {"/all", "/todo", "/todos"}
              or text.strip().casefold() in all_aliases)
    if is_all:
        raw_page = argument.strip() if command in {"/all", "/todo", "/todos"} else "1"
        raw_page = raw_page or "1"
        if not raw_page.isdecimal() or not 1 <= int(raw_page) <= 9999:
            return _send_reply(bot["token"], chat_id, "請輸入 /all 或 /all 2 查看指定頁。")
        try:
            page = int(raw_page)
            rows = _lookup_all(page)
            reply, buttons = _all_reply(page, rows)
        except Exception:
            reply, buttons = "分享資料暫時無法讀取，請稍後重試。", []
            _LOG.warning("ORDER share directory unavailable")
        return _send_reply(bot["token"], chat_id, reply, buttons)
    if text.startswith("/") and command != "/links":
        return _send_reply(bot["token"], chat_id, "输入 /all、全部或 todo 查看全部，或输入客户名称查询。")
    query = " ".join((argument if command == "/links" else text).split())[:160]
    if not query:
        return
    try:
        rows = _lookup_shares(query)
        # Avoid noisy replies to unrelated group conversation.
        if not rows and staff_group and command != "/links":
            return
        reply, buttons = _search_reply(query, rows)
        if rows:
            buttons.append([{"text": "📋 全部客戶", "callback_data": "order_shares:all:1"}])
    except Exception:
        reply, buttons = "分享资料暂时无法读取，请稍后重试。", []
        _LOG.warning("ORDER share lookup unavailable")
    _send_reply(bot["token"], chat_id, reply, buttons)


def handle_update(update):
    actor, bot_key = (_actor(update) or _group_actor(update) or _callback_actor(update)), _current_bot_key()
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
