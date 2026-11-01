# -*- coding: utf-8 -*-
"""TiDB-backed customer carts for the existing XINGWANG SCANNER.

Guests receive a time-limited cart-scoped HttpOnly cookie, never the staff
cookie.  Cart quantities are requests only: this module never reserves stock
or writes Access.  Snapshot quantities are reference figures, not a promise
that RESERVAR has already been reconciled.
"""
import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from xingwang_miniapp import scanner_tidb as stockdb
from xingwang_miniapp import scanner_backend as staff

router = APIRouter()
GUEST_COOKIE = "xw_cart_guest"
GUEST_LIFETIME = 8 * 3600
MAX_QTY = 9999
_CART_LOCK = threading.Lock()
_CART_SCHEMA_READY = False
_GUEST_ATTEMPTS = {}
_QUERY_ATTEMPTS = {}
_THROTTLE_LOCK = asyncio.Lock()
LOG = logging.getLogger("uvicorn.error")

CART_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS xw_carts (
        id CHAR(32) NOT NULL PRIMARY KEY,
        short_code VARCHAR(36) NOT NULL UNIQUE,
        customer_name VARCHAR(80) NOT NULL DEFAULT '',
        state VARCHAR(12) NOT NULL DEFAULT 'open',
        revision INT NOT NULL DEFAULT 0,
        guest_hash CHAR(64) NULL UNIQUE,
        guest_expires DATETIME(6) NULL,
        guest_generation INT NOT NULL DEFAULT 0,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        KEY idx_carts_updated (updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS xw_cart_items (
        cart_id CHAR(32) NOT NULL,
        sku VARCHAR(128) NOT NULL,
        qty INT NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        PRIMARY KEY (cart_id, sku)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS xw_cart_events (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        cart_id CHAR(32) NOT NULL,
        revision INT NOT NULL,
        sku VARCHAR(128) NOT NULL,
        old_qty INT NOT NULL,
        new_qty INT NOT NULL,
        actor VARCHAR(12) NOT NULL,
        changed_at DATETIME(6) NOT NULL,
        KEY idx_cart_revision (cart_id, revision)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _db():
    conn = stockdb._connect()
    try:
        stockdb._ensure(conn)
        global _CART_SCHEMA_READY
        if not _CART_SCHEMA_READY:
            with _CART_LOCK:
                if not _CART_SCHEMA_READY:
                    with conn.cursor() as cur:
                        for ddl in CART_SCHEMA:
                            cur.execute(ddl)
                    conn.commit()
                    _CART_SCHEMA_READY = True
        return conn
    except Exception:
        conn.close()
        raise


def _code_hash(code):
    key = staff._key()
    if not key:
        raise HTTPException(503, "Staff login is not configured")
    return hmac.new(key, ("cart-code-v1:" + code).encode("ascii"), hashlib.sha256).hexdigest()


def _sign_session(cart_id, generation, expires):
    data = f"{cart_id}.{generation}.{expires}"
    mac = hmac.new(staff._key(), ("cart-session-v1:" + data).encode(), hashlib.sha256).hexdigest()
    return data + "." + mac


def _parse_session(request):
    token = request.cookies.get(GUEST_COOKIE, "")
    if len(token) > 200 or staff._key() is None:
        return None
    try:
        cart_id, gen, exp, mac = token.split(".")
        if not re.fullmatch(r"[0-9a-f]{32}", cart_id):
            return None
        if not gen.isdecimal() or not exp.isdecimal():
            return None
        if not int(time.time()) < int(exp) <= int(time.time()) + GUEST_LIFETIME + 60:
            return None
        expected = _sign_session(cart_id, int(gen), int(exp)).rsplit(".", 1)[1]
        if not hmac.compare_digest(mac, expected):
            return None
        return cart_id, int(gen)
    except (ValueError, TypeError):
        return None


def _row_dict(row):
    if not row:
        return None
    fields = ("id", "short_code", "customer_name", "state", "revision",
              "guest_expires", "guest_generation", "created_at", "updated_at")
    return dict(zip(fields, row))


def _load(conn, cart_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id,short_code,customer_name,state,revision,guest_expires,"
            "guest_generation,created_at,updated_at FROM xw_carts WHERE id=%s",
            (cart_id,),
        )
        cart = _row_dict(cur.fetchone())
        if not cart:
            return None
        cur.execute(
            "SELECT sku,qty FROM xw_cart_items WHERE cart_id=%s ORDER BY sku", (cart_id,)
        )
        cart["items"] = [{"sku": sku, "qty": int(qty)} for sku, qty in cur.fetchall()]
    cart["guest_expires"] = cart["guest_expires"].isoformat() + "Z" if cart["guest_expires"] else None
    cart["created_at"] = cart["created_at"].isoformat() + "Z"
    cart["updated_at"] = cart["updated_at"].isoformat() + "Z"
    return cart


def _guest_access(conn, request):
    pair = _parse_session(request)
    if pair is None:
        return None
    cart_id, generation = pair
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state,guest_expires,guest_generation FROM xw_carts WHERE id=%s",
            (cart_id,),
        )
        row = cur.fetchone()
    if (not row or row[0] == "cancelled" or row[1] is None or
        row[1] <= utcnow() or int(row[2]) != generation):
        return None
    return cart_id


def _authorize(conn, request, cart_id=None, *, staff_only=False):
    if staff._authorized(request):
        if cart_id is None:
            return None, "staff"
        return cart_id, "staff"
    if staff_only:
        raise HTTPException(401, "Staff login required")
    allowed_id = _guest_access(conn, request)
    if not allowed_id or (cart_id and cart_id != allowed_id):
        raise HTTPException(401, "Cart access expired")
    return allowed_id, "guest"


async def _body(request):
    if int(request.headers.get("content-length", "0") or "0") > 2048:
        raise HTTPException(413, "Request too large")
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid body")
    return payload


def _id(body, name="cart_id"):
    value = body.get(name)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise HTTPException(400, "Invalid cart ID")
    return value


def _error_safe(exc, code):
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, ValueError):
        raise HTTPException(409, str(exc))
    LOG.exception("CART_%s_FAILED", code)
    raise HTTPException(503, "Cart storage unavailable")


def _generate_code():
    return f"{secrets.randbelow(100000000):08d}"


def _new_cart(name):
    conn = _db()
    try:
        now = utcnow()
        cart_id = uuid4().hex
        short_code = "C-" + now.strftime("%y%m%d") + "-" + secrets.token_hex(4).upper()
        access_code = _generate_code()
        expires = now + timedelta(seconds=GUEST_LIFETIME)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO xw_carts "
                "(id,short_code,customer_name,state,revision,guest_hash,guest_expires,"
                "guest_generation,created_at,updated_at) "
                "VALUES (%s,%s,%s,'open',0,%s,%s,1,%s,%s)",
                (cart_id, short_code, name, _code_hash(access_code), expires, now, now),
            )
        conn.commit()
        return _load(conn, cart_id), access_code
    finally:
        conn.close()


def _list_carts():
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.id,c.short_code,c.customer_name,c.state,c.revision,c.updated_at,"
                "COUNT(i.sku),COALESCE(SUM(i.qty),0) "
                "FROM xw_carts c LEFT JOIN xw_cart_items i ON i.cart_id=c.id "
                "GROUP BY c.id,c.short_code,c.customer_name,c.state,c.revision,c.updated_at "
                "ORDER BY c.updated_at DESC LIMIT 60"
            )
            rows = cur.fetchall()
        return [{"id": row[0], "short_code": row[1], "customer_name": row[2],
                 "state": row[3], "revision": int(row[4]),
                 "updated_at": row[5].isoformat() + "Z",
                 "sku_count": int(row[6]), "qty_total": int(row[7])}
                for row in rows]
    finally:
        conn.close()


def _get_cart(cart_id):
    conn = _db()
    try:
        cart = _load(conn, cart_id)
        if not cart:
            raise HTTPException(404, "Cart not found")
        return cart
    finally:
        conn.close()


def _lookup(code):
    # No reserved or customer data is returned to guests.
    data = stockdb.read_fast_stock(code)
    return {"product_code": data["product_code"],
            "variants": data["variants"],
            "as_of": data["as_of"], "fresh": bool(data["freshness"]["fresh"])}


def _mutate(cart_id, revision, *, sku=None, qty=None, name=None, state=None, actor="staff"):
    conn = _db()
    try:
        now = utcnow()
        with conn.cursor() as cur:
            cur.execute("SELECT revision,state FROM xw_carts WHERE id=%s FOR UPDATE", (cart_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Cart not found")
            old_revision, current_state = int(row[0]), row[1]
            if old_revision != revision:
                raise HTTPException(409, "Cart changed on another device. Reload before editing.")
            if current_state == "cancelled":
                raise HTTPException(409, "Cart is cancelled")
            if sku is not None:
                cur.execute("SELECT qty FROM xw_cart_items WHERE cart_id=%s AND sku=%s",
                            (cart_id, sku))
                prev = cur.fetchone()
                old_qty = int(prev[0]) if prev else 0
                if qty > 0:
                    cur.execute(
                        "SELECT stock_rolls FROM xw_stock_snapshot "
                        "WHERE sku=%s AND is_active=1", (sku,)
                    )
                    stock = cur.fetchone()
                    available = max(0, int(stock[0])) if stock and stock[0] is not None else 0
                    if qty > available:
                        raise HTTPException(409, "Requested quantity exceeds current stock reference")
                if qty != old_qty:
                    if qty:
                        cur.execute(
                            "INSERT INTO xw_cart_items(cart_id,sku,qty,updated_at)"
                            " VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE"
                            " qty=VALUES(qty),updated_at=VALUES(updated_at)",
                            (cart_id, sku, qty, now),
                        )
                    else:
                        cur.execute("DELETE FROM xw_cart_items WHERE cart_id=%s AND sku=%s",
                                    (cart_id, sku))
                    cur.execute(
                        "INSERT INTO xw_cart_events(cart_id,revision,sku,old_qty,new_qty,actor,changed_at)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (cart_id, revision + 1, sku, old_qty, qty, actor, now),
                    )
                else:
                    return _load(conn, cart_id)
            elif name is not None:
                cur.execute("UPDATE xw_carts SET customer_name=%s WHERE id=%s", (name, cart_id))
            elif state is not None:
                cur.execute("UPDATE xw_carts SET state=%s WHERE id=%s", (state, cart_id))
            cur.execute(
                "UPDATE xw_carts SET revision=revision+1,updated_at=%s,"
                "state=CASE WHEN %s AND state='ready' THEN 'open' ELSE state END "
                "WHERE id=%s",
                (now, bool(sku is not None and qty != old_qty), cart_id),
            )
        conn.commit()
        return _load(conn, cart_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _renew(cart_id):
    conn = _db()
    try:
        access_code = _generate_code()
        expires = utcnow() + timedelta(seconds=GUEST_LIFETIME)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE xw_carts SET guest_hash=%s,guest_expires=%s,"
                "guest_generation=guest_generation+1 WHERE id=%s AND state!='cancelled'",
                (_code_hash(access_code), expires, cart_id),
            )
            if not cur.rowcount:
                raise HTTPException(404, "Cart not found or cancelled")
        conn.commit()
        return _load(conn, cart_id), access_code
    finally:
        conn.close()


def _login_guest(code):
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id,guest_generation,guest_expires FROM xw_carts "
                "WHERE guest_hash=%s AND state!='cancelled'",
                (_code_hash(code),),
            )
            row = cur.fetchone()
        if not row or not row[2] or row[2] <= utcnow():
            raise HTTPException(401, "Temporary code invalid or expired")
        return row[0], int(row[1]), row[2]
    finally:
        conn.close()


async def _guard_guest(request):
    ip = request.client.host if request.client else "unknown"
    async with _THROTTLE_LOCK:
        now = time.monotonic()
        for key, entries in list(_GUEST_ATTEMPTS.items()):
            entries[:] = [t for t in entries if now - t < 900]
            if not entries:
                del _GUEST_ATTEMPTS[key]
        local = _GUEST_ATTEMPTS.setdefault(ip, [])
        if len(local) >= 12 or sum(len(v) for v in _GUEST_ATTEMPTS.values()) >= 300:
            raise HTTPException(429, "Too many attempts")
        local.append(now)


async def _guard_query(request):
    ip = request.client.host if request.client else "unknown"
    async with _THROTTLE_LOCK:
        now = time.monotonic()
        entries = _QUERY_ATTEMPTS.setdefault(ip, [])
        entries[:] = [t for t in entries if now - t < 60]
        if len(entries) >= 80:
            raise HTTPException(429, "Too many scans")
        entries.append(now)
        if len(_QUERY_ATTEMPTS) > 2048:
            _QUERY_ATTEMPTS.clear()


@router.get("/scanner/api/cart/session")
async def cart_session(request: Request):
    if staff._authorized(request):
        return {"role": "staff"}
    if not stockdb.configured():
        return {"role": "none"}
    try:
        conn = await asyncio.to_thread(_db)
        try:
            cart_id = await asyncio.to_thread(_guest_access, conn, request)
        finally:
            conn.close()
    except Exception:
        LOG.exception("CART_SESSION_FAILED")
        return {"role": "none"}
    return {"role": "guest", "cart_id": cart_id} if cart_id else {"role": "none"}


@router.post("/scanner/api/cart/guest-login")
async def guest_login(request: Request):
    staff._check_origin(request)
    await _guard_guest(request)
    body = await _body(request)
    code = body.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{8}", code):
        raise HTTPException(401, "Temporary code invalid or expired")
    try:
        cart_id, generation, expires = await asyncio.to_thread(_login_guest, code)
    except HTTPException:
        raise
    except Exception as exc:
        _error_safe(exc, "LOGIN")
    ttl = min(GUEST_LIFETIME, max(1, int((expires - utcnow()).total_seconds())))
    exp = int(time.time()) + ttl
    reply = JSONResponse({"ok": True, "cart_id": cart_id})
    reply.set_cookie(GUEST_COOKIE, _sign_session(cart_id, generation, exp),
                     max_age=ttl, httponly=True, secure=True, samesite="lax",
                     path="/scanner/api/cart")
    # Prevent a shared company device from retaining privileged staff access.
    reply.delete_cookie(staff.COOKIE, path="/scanner", secure=True, httponly=True, samesite="lax")
    return reply


@router.post("/scanner/api/cart/guest-logout")
async def guest_logout(request: Request):
    staff._check_origin(request)
    reply = JSONResponse({"ok": True})
    reply.delete_cookie(GUEST_COOKIE, path="/scanner/api/cart",
                        secure=True, httponly=True, samesite="lax")
    return reply


@router.post("/scanner/api/cart/create")
async def create_cart(request: Request):
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request)
    name = body.get("name", "")
    if not isinstance(name, str) or len(name.strip()) > 80:
        raise HTTPException(400, "Invalid customer name")
    try:
        cart, code = await asyncio.to_thread(_new_cart, name.strip())
        return {"ok": True, "cart": cart, "guest_code": code}
    except Exception as exc:
        _error_safe(exc, "CREATE")


@router.get("/scanner/api/cart/list")
async def list_carts(request: Request):
    staff._require(request)
    try:
        return {"ok": True, "carts": await asyncio.to_thread(_list_carts)}
    except Exception as exc:
        _error_safe(exc, "LIST")


@router.post("/scanner/api/cart/open")
async def open_cart(request: Request):
    staff._check_origin(request)
    body = await _body(request)
    conn = None
    try:
        conn = await asyncio.to_thread(_db)
        target = body.get("cart_id")
        if staff._authorized(request):
            cart_id = _id(body)
        else:
            cart_id, _ = await asyncio.to_thread(_authorize, conn, request, target)
        cart = await asyncio.to_thread(_load, conn, cart_id)
        if not cart:
            raise HTTPException(404, "Cart not found")
        return {"ok": True, "cart": cart}
    except Exception as exc:
        _error_safe(exc, "OPEN")
    finally:
        if conn:
            conn.close()


@router.post("/scanner/api/cart/lookup")
async def cart_lookup(request: Request):
    staff._check_origin(request)
    body = await _body(request)
    code = body.get("code")
    if not isinstance(code, str) or not staff.CODE.fullmatch(code.strip()):
        raise HTTPException(400, "Invalid SKU")
    conn = None
    try:
        conn = await asyncio.to_thread(_db)
        cart_id = _id(body) if staff._authorized(request) else body.get("cart_id")
        cart_id, _ = await asyncio.to_thread(_authorize, conn, request, cart_id)
        cart = await asyncio.to_thread(_load, conn, cart_id)
        if not cart or cart["state"] == "cancelled":
            raise HTTPException(404, "Cart not found")
        await _guard_query(request)
        data = await asyncio.to_thread(_lookup, code.strip().upper())
        if not data["variants"]:
            raise HTTPException(404, "No stock SKU matches this QR")
        return {"ok": True, **data}
    except Exception as exc:
        _error_safe(exc, "LOOKUP")
    finally:
        if conn:
            conn.close()


@router.post("/scanner/api/cart/item")
async def cart_item(request: Request):
    staff._check_origin(request)
    body = await _body(request)
    sku = body.get("sku")
    qty = body.get("qty")
    rev = body.get("revision")
    if (not isinstance(sku, str) or not staff.CODE.fullmatch(sku) or
        type(qty) is not int or qty < 0 or qty > MAX_QTY or
        type(rev) is not int or rev < 0):
        raise HTTPException(400, "Invalid SKU, quantity or revision")
    conn = None
    try:
        conn = await asyncio.to_thread(_db)
        target = _id(body) if staff._authorized(request) else body.get("cart_id")
        cart_id, role = await asyncio.to_thread(_authorize, conn, request, target)
        conn.close()
        conn = None
        cart = await asyncio.to_thread(_mutate, cart_id, rev, sku=sku, qty=qty, actor=role)
        return {"ok": True, "cart": cart}
    except Exception as exc:
        _error_safe(exc, "ITEM")
    finally:
        if conn:
            conn.close()


@router.post("/scanner/api/cart/name")
async def cart_name(request: Request):
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request)
    name, rev = body.get("name"), body.get("revision")
    if not isinstance(name, str) or len(name.strip()) > 80 or type(rev) is not int or rev < 0:
        raise HTTPException(400, "Invalid customer name")
    try:
        cart = await asyncio.to_thread(_mutate, _id(body), rev, name=name.strip())
        return {"ok": True, "cart": cart}
    except Exception as exc:
        _error_safe(exc, "NAME")


@router.post("/scanner/api/cart/state")
async def cart_state(request: Request):
    staff._check_origin(request)
    body = await _body(request)
    state, rev = body.get("state"), body.get("revision")
    if state not in ("open", "ready") or type(rev) is not int or rev < 0:
        raise HTTPException(400, "Invalid cart state")
    conn = None
    try:
        conn = await asyncio.to_thread(_db)
        target = _id(body) if staff._authorized(request) else body.get("cart_id")
        cart_id, role = await asyncio.to_thread(_authorize, conn, request, target)
        conn.close()
        conn = None
        cart = await asyncio.to_thread(_mutate, cart_id, rev, state=state, actor=role)
        return {"ok": True, "cart": cart}
    except Exception as exc:
        _error_safe(exc, "STATE")
    finally:
        if conn:
            conn.close()


@router.post("/scanner/api/cart/share")
async def cart_share(request: Request):
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request)
    try:
        cart, code = await asyncio.to_thread(_renew, _id(body))
        return {"ok": True, "cart": cart, "guest_code": code}
    except Exception as exc:
        _error_safe(exc, "SHARE")
