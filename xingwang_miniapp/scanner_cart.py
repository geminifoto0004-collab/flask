# -*- coding: utf-8 -*-
"""TiDB-backed customer carts for the existing XINGWANG SCANNER.

Guests receive a time-limited cart-scoped HttpOnly cookie, never the staff
cookie.  Cart quantities are requests only: this module never reserves stock
or writes Access.  Snapshot quantities are reference figures, not a promise
that RESERVAR has already been reconciled.
"""
import asyncio
import json
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
START_COOKIE = "xw_cart_start"
START_TTL = 30 * 60
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
        start_hash CHAR(64) NULL UNIQUE,
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
    """CREATE TABLE IF NOT EXISTS xw_cart_confirmations (
        cart_id CHAR(32) NOT NULL,
        version INT NOT NULL,
        revision INT NOT NULL,
        confirmed_at DATETIME(6) NOT NULL,
        customer_name VARCHAR(80) NOT NULL DEFAULT '',
        sku_count INT NOT NULL,
        qty_total INT NOT NULL,
        PRIMARY KEY (cart_id, version)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS xw_cart_confirmation_items (
        cart_id CHAR(32) NOT NULL,
        version INT NOT NULL,
        sku VARCHAR(128) NOT NULL,
        qty INT NOT NULL,
        PRIMARY KEY (cart_id, version, sku)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS xw_cart_notes (
        cart_id CHAR(32) NOT NULL PRIMARY KEY,
        note TEXT NOT NULL,
        updated_at DATETIME(6) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS xw_cart_start_limits (
        rate_key CHAR(64) NOT NULL PRIMARY KEY,
        hour_bucket BIGINT NOT NULL,
        hits INT NOT NULL,
        updated_at DATETIME(6) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS xw_cart_item_notes (
        cart_id CHAR(32) NOT NULL,
        sku VARCHAR(128) NOT NULL,
        note VARCHAR(240) NOT NULL DEFAULT '',
        version INT NOT NULL DEFAULT 1,
        updated_at DATETIME(6) NOT NULL,
        PRIMARY KEY(cart_id,sku)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
)

# Re-runnable upgrades. Existing stock and sample tables remain untouched.
_CART_COLUMNS = {
    "guest_opened_at": "DATETIME(6) NULL",
    "confirmed_at": "DATETIME(6) NULL",
    "confirmed_revision": "INT NOT NULL DEFAULT 0",
    "confirmed_version": "INT NOT NULL DEFAULT 0",
    "deleted_prev_state": "VARCHAR(12) NULL",
    "deleted_until": "DATETIME(6) NULL",
    "start_hash": "CHAR(64) NULL UNIQUE",
}


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
                        cur.execute("SHOW COLUMNS FROM xw_carts")
                        existing = {row[0] for row in cur.fetchall()}
                        for column, spec in _CART_COLUMNS.items():
                            if column not in existing:
                                try:
                                    cur.execute("ALTER TABLE xw_carts ADD COLUMN " + column + " " + spec)
                                except Exception as exc:
                                    # Another Render process might have finished the same upgrade.
                                    if not (getattr(exc, "args", ()) and exc.args[0] == 1060):
                                        raise
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


def _sign_start_token(token=None):
    """A bounded anonymous selection ticket; issuing one does not touch TiDB."""
    nonce = token or secrets.token_hex(16)
    created = int(time.time())
    data = str(created) + "." + nonce
    mac = hmac.new(staff._key(), ("cart-start-v1:" + data).encode("ascii"),
                   hashlib.sha256).hexdigest()
    return data + "." + mac


def _parse_start_token(token):
    if not isinstance(token, str) or len(token) > 140 or not staff._key():
        return None
    try:
        stamp, nonce, signature = token.split(".")
        if not re.fullmatch(r"[0-9]{10}", stamp) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            return None
        age = int(time.time()) - int(stamp)
        if age < -30 or age > START_TTL:
            return None
        data = stamp + "." + nonce
        mac = hmac.new(staff._key(), ("cart-start-v1:" + data).encode("ascii"),
                       hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, signature):
            return None
        return data
    except (ValueError, AttributeError):
        return None


def issue_start_cookie(request):
    token = request.cookies.get(START_COOKIE)
    if _parse_start_token(token):
        return token
    return _sign_start_token()


def _start_hash(start_data):
    return hmac.new(staff._key(), ("cart-start-key-v1:" + start_data).encode("ascii"),
                    hashlib.sha256).hexdigest()


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
              "guest_expires", "guest_generation", "created_at", "updated_at",
              "guest_opened_at", "confirmed_at", "confirmed_revision",
              "confirmed_version")
    return dict(zip(fields, row))


def _load(conn, cart_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id,short_code,customer_name,state,revision,guest_expires,"
            "guest_generation,created_at,updated_at,guest_opened_at,confirmed_at,"
            "confirmed_revision,confirmed_version FROM xw_carts WHERE id=%s",
            (cart_id,),
        )
        cart = _row_dict(cur.fetchone())
        if not cart:
            return None
        # Read the latest stock for this cart in the EXISTING items query.
        # This avoids one network request per SKU, and guests only receive
        # the quantities for SKUs already in their authorized cart.
        cur.execute(
            "SELECT i.sku,i.qty,s.stock_rolls "
            "FROM xw_cart_items i "
            "LEFT JOIN xw_stock_snapshot s ON s.sku=i.sku AND s.is_active=1 "
            "WHERE i.cart_id=%s ORDER BY i.sku", (cart_id,)
        )
        cart["items"] = [
            {"sku": sku, "qty": int(qty),
             "stock_rolls": str(rolls) if rolls is not None else None}
            for sku, qty, rolls in cur.fetchall()
        ]
    cart["guest_expires"] = cart["guest_expires"].isoformat() + "Z" if cart["guest_expires"] else None
    cart["created_at"] = cart["created_at"].isoformat() + "Z"
    cart["updated_at"] = cart["updated_at"].isoformat() + "Z"
    for field in ("guest_opened_at", "confirmed_at"):
        value = cart[field]
        cart[field] = value.isoformat() + "Z" if value else None
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


async def _body(request, *, limit=2048):
    if int(request.headers.get("content-length", "0") or "0") > limit:
        raise HTTPException(413, "Request too large")
    raw = await request.body()
    if len(raw) > limit:
        raise HTTPException(413, "Request too large")
    try:
        payload = json.loads(raw)
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
                "COUNT(i.sku),COALESCE(SUM(i.qty),0),c.guest_opened_at,c.confirmed_at,"
                "c.confirmed_version "
                "FROM xw_carts c LEFT JOIN xw_cart_items i ON i.cart_id=c.id "
                "WHERE c.state<>'cancelled' "
                "GROUP BY c.id,c.short_code,c.customer_name,c.state,c.revision,"
                "c.updated_at,c.guest_opened_at,c.confirmed_at,c.confirmed_version "
                "ORDER BY c.updated_at DESC LIMIT 60"
            )
            rows = cur.fetchall()
        return [{"id": row[0], "short_code": row[1], "customer_name": row[2],
                 "state": row[3], "revision": int(row[4]),
                 "updated_at": row[5].isoformat() + "Z",
                 "sku_count": int(row[6]), "qty_total": int(row[7]),
                 "guest_opened_at": row[8].isoformat()+"Z" if row[8] else None,
                 "confirmed_at": row[9].isoformat()+"Z" if row[9] else None,
                 "confirmed_version": int(row[10])}
                for row in rows]
    finally:
        conn.close()



def _soft_delete_cart(cart_id, revision):
    """Tombstone a cart without deleting items, confirmations or history."""
    conn = _db()
    try:
        now = utcnow()
        deadline = now + timedelta(seconds=8)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT revision,state FROM xw_carts WHERE id=%s FOR UPDATE", (cart_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Cart not found")
            if int(row[0]) != revision or row[1] == "cancelled":
                raise HTTPException(409, "Cart modified or already deleted")
            if row[1] not in ("open", "ready"):
                raise HTTPException(409, "This cart cannot be deleted")
            cur.execute(
                "UPDATE xw_carts SET state='cancelled',revision=revision+1,"
                "deleted_prev_state=%s,deleted_until=%s,updated_at=%s,"
                "guest_generation=guest_generation+1,guest_hash=NULL,guest_expires=NULL "
                "WHERE id=%s",
                (row[1], deadline, now, cart_id)
            )
        conn.commit()
        return {"cart_id": cart_id, "revision": revision + 1,
                "undo_until": deadline.isoformat() + "Z"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _undo_delete_cart(cart_id, revision):
    """Undo only inside the server-enforced 8-second window."""
    conn = _db()
    try:
        now = utcnow()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT revision,state,deleted_prev_state,deleted_until "
                "FROM xw_carts WHERE id=%s FOR UPDATE", (cart_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Cart not found")
            if int(row[0]) != revision or row[1] != "cancelled":
                raise HTTPException(409, "Cart changed since deletion")
            if row[2] not in ("open", "ready") or not row[3] or now > row[3]:
                raise HTTPException(410, "Undo window expired")
            cur.execute(
                "UPDATE xw_carts SET state=%s,revision=revision+1,"
                "deleted_prev_state=NULL,deleted_until=NULL,updated_at=%s WHERE id=%s",
                (row[2], now, cart_id)
            )
        conn.commit()
        return _load(conn, cart_id)
    except Exception:
        conn.rollback()
        raise
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
                # Cart stores customer demand; stock is only a reference.
                # A shortage is highlighted in UI, not rejected by the API.
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



def _mutate_batch(cart_id, revision, items, actor):
    """Merge explicit SKU quantities in one TiDB transaction/revision.

    'items' is a dict of SKU -> absolute quantity, not increments.
    This prevents retries from double-counting rolls.
    """
    if not isinstance(items, dict) or not 1 <= len(items) <= 100:
        raise HTTPException(400, "Batch must contain 1–100 items")
    for sku, qty in items.items():
        if (not isinstance(sku, str) or not staff.CODE.fullmatch(sku) or
            type(qty) is not int or not 0 <= qty <= MAX_QTY):
            raise HTTPException(400, "Invalid SKU or quantity")
    conn = _db()
    try:
        now = utcnow()
        with conn.cursor() as cur:
            cur.execute("SELECT revision,state FROM xw_carts WHERE id=%s FOR UPDATE", (cart_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Cart not found")
            old_revision, state = int(row[0]), row[1]
            if old_revision != revision:
                raise HTTPException(409, "Cart changed on another device. Reload before editing.")
            if state == "cancelled":
                raise HTTPException(409, "Cart is cancelled")
            cur.execute("SELECT sku,qty FROM xw_cart_items WHERE cart_id=%s", (cart_id,))
            existing = dict(cur.fetchall())
            delta = [(sku, int(existing.get(sku, 0)), qty)
                     for sku, qty in items.items() if int(existing.get(sku, 0)) != qty]
            if not delta:
                return _load(conn, cart_id)
            # Deliberately allow customer requested qty > snapshot stock.
            # Never write/reserve inventory as part of cart edits.
            updates = [(cart_id, sku, qty, now) for sku, _old, qty in delta if qty]
            deletes = [(cart_id, sku) for sku, _old, qty in delta if not qty]
            if updates:
                cur.executemany(
                    "INSERT INTO xw_cart_items(cart_id,sku,qty,updated_at) "
                    "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
                    "qty=VALUES(qty),updated_at=VALUES(updated_at)", updates
                )
            if deletes:
                cur.executemany(
                    "DELETE FROM xw_cart_items WHERE cart_id=%s AND sku=%s", deletes
                )
            # One event per changed SKU, not one event per '+' tap.
            cur.executemany(
                "INSERT INTO xw_cart_events(cart_id,revision,sku,old_qty,new_qty,actor,changed_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                [(cart_id, old_revision+1, sku, old, qty, actor, now)
                 for sku, old, qty in delta],
            )
            cur.execute(
                "UPDATE xw_carts SET revision=revision+1,updated_at=%s,"
                "state='open' WHERE id=%s",
                (now, cart_id),
            )
        conn.commit()
        return _load(conn, cart_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _confirm_cart(cart_id, revision):
    """Freeze an immutable copy of the selected items at each confirmation."""
    conn = _db()
    try:
        now = utcnow()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT revision,state,confirmed_revision,confirmed_version,customer_name "
                "FROM xw_carts WHERE id=%s FOR UPDATE", (cart_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Cart not found")
            current_revision, state, prev_confirmed_revision, version, name = row
            if int(current_revision) != revision:
                raise HTTPException(409, "Cart changed. Reload before confirming.")
            if state == "cancelled":
                raise HTTPException(409, "Cart is cancelled")
            if state == "ready" and int(version) > 0 and int(prev_confirmed_revision) == revision:
                return _load(conn, cart_id)
            cur.execute("SELECT sku,qty FROM xw_cart_items WHERE cart_id=%s ORDER BY sku",
                        (cart_id,))
            rows = cur.fetchall()
            if not rows:
                raise HTTPException(409, "Cannot confirm an empty cart")
            # Reopening a READY cart alone does not create a duplicate snapshot.
            if int(version) and int(prev_confirmed_revision) == revision:
                cur.execute("UPDATE xw_carts SET state='ready' WHERE id=%s", (cart_id,))
                conn.commit()
                return _load(conn, cart_id)
            new_version = int(version) + 1
            new_revision = revision + 1
            cur.execute(
                "INSERT INTO xw_cart_confirmations "
                "(cart_id,version,revision,confirmed_at,customer_name,sku_count,qty_total) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (cart_id, new_version, new_revision, now, name, len(rows),
                 sum(int(qty) for _sku, qty in rows)),
            )
            cur.executemany(
                "INSERT INTO xw_cart_confirmation_items(cart_id,version,sku,qty) "
                "VALUES (%s,%s,%s,%s)",
                [(cart_id, new_version, sku, int(qty)) for sku, qty in rows],
            )
            cur.execute(
                "UPDATE xw_carts SET state='ready',revision=%s,confirmed_version=%s,"
                "confirmed_revision=%s,confirmed_at=%s,updated_at=%s WHERE id=%s",
                (new_revision, new_version, new_revision, now, now, cart_id),
            )
        conn.commit()
        return _load(conn, cart_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _read_confirmed(cart_id, version=None):
    conn = _db()
    try:
        with conn.cursor() as cur:
            if version is None:
                cur.execute(
                    "SELECT version,revision,confirmed_at,customer_name,sku_count,qty_total "
                    "FROM xw_cart_confirmations WHERE cart_id=%s "
                    "ORDER BY version DESC LIMIT 1", (cart_id,)
                )
            else:
                cur.execute(
                    "SELECT version,revision,confirmed_at,customer_name,sku_count,qty_total "
                    "FROM xw_cart_confirmations WHERE cart_id=%s AND version=%s",
                    (cart_id, version),
                )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "No confirmed version")
            ver, revision, confirmed_at, name, count, total = row
            cur.execute(
                "SELECT sku,qty FROM xw_cart_confirmation_items "
                "WHERE cart_id=%s AND version=%s ORDER BY sku", (cart_id, ver)
            )
            return {"version": int(ver), "revision": int(revision),
                    "confirmed_at": confirmed_at.isoformat()+"Z",
                    "customer_name": name, "sku_count": int(count),
                    "qty_total": int(total),
                    "items": [{"sku": sku, "qty": int(qty)}
                              for sku, qty in cur.fetchall()]}
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
        # First actual guest entry only. Never rewrite on refresh or each scan.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE xw_carts SET guest_opened_at=%s "
                "WHERE id=%s AND guest_opened_at IS NULL",
                (utcnow(), row[0]),
            )
        conn.commit()
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
    if not stockdb.configured() or _parse_session(request) is None:
        # Anonymous page loads must never open TiDB or run schema checks.
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


def _create_public_cart(start_data, sku, qty, ip):
    """Create exactly one cart with its first requested SKU, atomically.

    A repeated request with the same HttpOnly start ticket returns the
    existing cart instead of adding another cart or incrementing quantity.
    """
    conn = _db()
    try:
        now = utcnow()
        token_hash = _start_hash(start_data)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id,guest_generation,guest_expires FROM xw_carts "
                "WHERE start_hash=%s FOR UPDATE", (token_hash,)
            )
            existing = cur.fetchone()
            if existing:
                if not existing[2] or existing[2] <= now:
                    raise HTTPException(410, "Selection session expired; reopen the QR")
                return _load(conn, existing[0]), int(existing[1]), existing[2]

            # This quantity is requested by a customer, not reserved stock.
            # Only active known SKU values can create customer carts.
            cur.execute("SELECT 1 FROM xw_stock_snapshot "
                        "WHERE sku=%s AND is_active=1 LIMIT 1", (sku,))
            if not cur.fetchone():
                raise HTTPException(404, "SKU is not in current stock reference")

            bucket = int(time.time()) // 3600
            ip_key = hmac.new(staff._key(), ("cart-start-ip:" + ip).encode(),
                              hashlib.sha256).hexdigest()
            # Global row first, then IP row: stable lock order across workers.
            for key, maximum in (("public-cart-global", 300), (ip_key, 45)):
                cur.execute(
                    "INSERT INTO xw_cart_start_limits(rate_key,hour_bucket,hits,updated_at) "
                    "VALUES(%s,%s,1,%s) ON DUPLICATE KEY UPDATE "
                    "hits=IF(hour_bucket=VALUES(hour_bucket),hits+1,1),"
                    "hour_bucket=VALUES(hour_bucket),updated_at=VALUES(updated_at)",
                    (key,bucket,now)
                )
                cur.execute("SELECT hits FROM xw_cart_start_limits WHERE rate_key=%s", (key,))
                if int(cur.fetchone()[0]) > maximum:
                    raise HTTPException(429, "Too many new carts. Please contact staff")

            cart_id = uuid4().hex
            short_code = "C-" + now.strftime("%y%m%d") + "-" + secrets.token_hex(4).upper()
            expires = now + timedelta(seconds=GUEST_LIFETIME)
            cur.execute(
                "INSERT INTO xw_carts "
                "(id,short_code,customer_name,state,revision,guest_hash,guest_expires,"
                "guest_generation,start_hash,created_at,updated_at) "
                "VALUES(%s,%s,'','open',1,NULL,%s,1,%s,%s,%s)",
                (cart_id, short_code, expires, token_hash, now, now)
            )
            cur.execute(
                "INSERT INTO xw_cart_items(cart_id,sku,qty,updated_at) VALUES(%s,%s,%s,%s)",
                (cart_id, sku, qty, now)
            )
            cur.execute(
                "INSERT INTO xw_cart_events(cart_id,revision,sku,old_qty,new_qty,actor,changed_at)"
                " VALUES(%s,1,%s,0,%s,'guest',%s)",
                (cart_id,sku,qty,now)
            )
        conn.commit()
        return _load(conn, cart_id), 1, expires
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/scanner/api/cart/start/lookup")
async def public_start_lookup(request: Request):
    staff._check_origin(request)
    if not _parse_start_token(request.cookies.get(START_COOKIE)):
        raise HTTPException(401, "Open the start QR again")
    await _guard_query(request)
    body = await _body(request)
    code = body.get("code")
    if not isinstance(code,str) or not staff.CODE.fullmatch(code.strip()):
        raise HTTPException(400, "Invalid series or SKU")
    try:
        result = await asyncio.to_thread(_lookup, code.strip().upper())
        if not result["variants"]:
            raise HTTPException(404, "No matching SKU")
        return {"ok":True, **result}
    except Exception as exc:
        _error_safe(exc, "PUBLIC_LOOKUP")


@router.post("/scanner/api/cart/start/add")
async def public_start_add(request: Request):
    staff._check_origin(request)
    start_data = _parse_start_token(request.cookies.get(START_COOKIE))
    if not start_data:
        raise HTTPException(401, "Open the start QR again")
    body = await _body(request)
    sku, qty = body.get("sku"), body.get("qty")
    if (not isinstance(sku,str) or not staff.CODE.fullmatch(sku) or
        type(qty) is not int or not 1 <= qty <= MAX_QTY):
        raise HTTPException(400, "Invalid selected SKU or quantity")
    try:
        ip = request.client.host if request.client else "unknown"
        cart, generation, expires = await asyncio.to_thread(
            _create_public_cart, start_data, sku, qty, ip
        )
    except Exception as exc:
        _error_safe(exc, "PUBLIC_CREATE")
    ttl = min(GUEST_LIFETIME,max(1,int((expires-utcnow()).total_seconds())))
    reply = JSONResponse({"ok":True,"cart_id":cart["id"],"cart":cart})
    reply.set_cookie(GUEST_COOKIE, _sign_session(cart["id"],generation,int(time.time())+ttl),
                     max_age=ttl,httponly=True,secure=True,samesite="lax",
                     path="/scanner/api/cart")
    reply.delete_cookie(START_COOKIE, path="/scanner/api/cart",
                        secure=True,httponly=True,samesite="lax")
    return reply


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
        if not cart or cart["state"] == "cancelled":
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



@router.post("/scanner/api/cart/batch")
async def cart_batch(request: Request):
    staff._check_origin(request)
    body = await _body(request, limit=16000)
    changes = body.get("items")
    revision = body.get("revision")
    if (type(revision) is not int or revision < 0 or
        not isinstance(changes, list) or not 1 <= len(changes) <= 100):
        raise HTTPException(400, "Invalid cart batch")
    updates = {}
    for item in changes:
        if not isinstance(item, dict):
            raise HTTPException(400, "Invalid cart item")
        sku, qty = item.get("sku"), item.get("qty")
        if (not isinstance(sku, str) or not staff.CODE.fullmatch(sku) or
            type(qty) is not int or not 0 <= qty <= MAX_QTY or
            sku in updates):
            raise HTTPException(400, "Invalid or duplicate SKU")
        updates[sku] = qty
    conn = None
    try:
        conn = await asyncio.to_thread(_db)
        cart_id = _id(body) if staff._authorized(request) else body.get("cart_id")
        cart_id, actor = await asyncio.to_thread(_authorize, conn, request, cart_id)
        conn.close()
        conn = None
        cart = await asyncio.to_thread(_mutate_batch, cart_id, revision, updates, actor)
        return {"ok": True, "cart": cart}
    except Exception as exc:
        _error_safe(exc, "BATCH")
    finally:
        if conn:
            conn.close()


@router.post("/scanner/api/cart/confirm")
async def cart_confirm(request: Request):
    staff._check_origin(request)
    body = await _body(request)
    revision = body.get("revision")
    if type(revision) is not int or revision < 0:
        raise HTTPException(400, "Invalid revision")
    conn = None
    try:
        conn = await asyncio.to_thread(_db)
        cart_id = _id(body) if staff._authorized(request) else body.get("cart_id")
        cart_id, _actor = await asyncio.to_thread(_authorize, conn, request, cart_id)
        conn.close()
        conn = None
        cart = await asyncio.to_thread(_confirm_cart, cart_id, revision)
        return {"ok": True, "cart": cart}
    except Exception as exc:
        _error_safe(exc, "CONFIRM")
    finally:
        if conn:
            conn.close()


@router.post("/scanner/api/cart/confirmed")
async def cart_confirmed(request: Request):
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request)
    version = body.get("version")
    if version is not None and (type(version) is not int or version < 1):
        raise HTTPException(400, "Invalid confirmation version")
    try:
        data = await asyncio.to_thread(_read_confirmed, _id(body), version)
        return {"ok": True, "confirmed": data}
    except Exception as exc:
        _error_safe(exc, "CONFIRMED")


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


@router.post("/scanner/api/cart/delete")
async def cart_delete(request: Request):
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request)
    revision = body.get("revision")
    if type(revision) is not int or revision < 0:
        raise HTTPException(400, "Invalid revision")
    try:
        result = await asyncio.to_thread(_soft_delete_cart, _id(body), revision)
        return {"ok": True, **result}
    except Exception as exc:
        _error_safe(exc, "DELETE")


@router.post("/scanner/api/cart/undo-delete")
async def cart_undo_delete(request: Request):
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request)
    revision = body.get("revision")
    if type(revision) is not int or revision < 0:
        raise HTTPException(400, "Invalid revision")
    try:
        cart = await asyncio.to_thread(_undo_delete_cart, _id(body), revision)
        return {"ok": True, "cart": cart}
    except Exception as exc:
        _error_safe(exc, "UNDO_DELETE")



def _cart_note_get(cart_id):
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT state FROM xw_carts WHERE id=%s", (cart_id,))
            cart = cur.fetchone()
            if not cart or cart[0] == "cancelled":
                raise HTTPException(404, "Cart not found")
            cur.execute("SELECT note FROM xw_cart_notes WHERE cart_id=%s", (cart_id,))
            row = cur.fetchone()
            return row[0] if row else ""
    finally:
        conn.close()


def _cart_note_save(cart_id, revision, note):
    # Separate staff-only note storage keeps quoted prices away from guest API data.
    conn = _db()
    try:
        now = utcnow()
        with conn.cursor() as cur:
            cur.execute("SELECT revision,state FROM xw_carts WHERE id=%s FOR UPDATE", (cart_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Cart not found")
            if row[1] == "cancelled":
                raise HTTPException(409, "Cart is cancelled")
            if int(row[0]) != revision:
                raise HTTPException(409, "Cart changed on another device. Reload before editing.")
            cur.execute(
                "INSERT INTO xw_cart_notes(cart_id,note,updated_at) VALUES(%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE note=VALUES(note),updated_at=VALUES(updated_at)",
                (cart_id, note, now)
            )
            cur.execute(
                "UPDATE xw_carts SET revision=revision+1,updated_at=%s WHERE id=%s",
                (now, cart_id)
            )
        conn.commit()
        return revision + 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _item_notes_get(cart_id):
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT state FROM xw_carts WHERE id=%s", (cart_id,))
            state = cur.fetchone()
            if not state or state[0] == "cancelled":
                raise HTTPException(404, "Cart not found")
            cur.execute(
                "SELECT sku,note,version FROM xw_cart_item_notes WHERE cart_id=%s",
                (cart_id,)
            )
            return {sku: {"note": note, "version": int(version)}
                    for sku,note,version in cur.fetchall()}
    finally:
        conn.close()


def _item_note_save(cart_id, sku, note, version):
    # Notes have their own revision. They must not race against qty revisions.
    conn = _db()
    try:
        now = utcnow()
        with conn.cursor() as cur:
            # Lock the parent row so concurrent first-note INSERTs serialize.
            cur.execute("SELECT state FROM xw_carts WHERE id=%s FOR UPDATE", (cart_id,))
            state = cur.fetchone()
            if not state or state[0] == "cancelled":
                raise HTTPException(404, "Cart not found")
            cur.execute(
                "SELECT version FROM xw_cart_item_notes "
                "WHERE cart_id=%s AND sku=%s FOR UPDATE", (cart_id, sku)
            )
            found = cur.fetchone()
            old_version = int(found[0]) if found else 0
            if old_version != version:
                raise HTTPException(409, "SKU note updated on another device")
            if found:
                cur.execute(
                    "UPDATE xw_cart_item_notes SET note=%s,version=version+1,"
                    "updated_at=%s WHERE cart_id=%s AND sku=%s",
                    (note,now,cart_id,sku)
                )
            else:
                cur.execute(
                    "INSERT INTO xw_cart_item_notes(cart_id,sku,note,version,updated_at) "
                    "VALUES(%s,%s,%s,1,%s)",
                    (cart_id,sku,note,now)
                )
        conn.commit()
        return old_version + 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/scanner/api/cart/item-notes")
async def cart_item_notes(request: Request):
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request)
    try:
        notes = await asyncio.to_thread(_item_notes_get, _id(body))
        return {"ok": True, "notes": notes}
    except Exception as exc:
        _error_safe(exc, "ITEM_NOTES")


@router.post("/scanner/api/cart/item-note/save")
async def cart_item_note_save(request: Request):
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request, limit=2048)
    sku, note, version = body.get("sku"), body.get("note"), body.get("version")
    if (not isinstance(sku,str) or not staff.CODE.fullmatch(sku) or
        not isinstance(note,str) or len(note)>180 or chr(0) in note or
        type(version) is not int or version<0):
        raise HTTPException(400, "Invalid item note")
    try:
        new_version = await asyncio.to_thread(
            _item_note_save, _id(body), sku, note.strip(), version
        )
        return {"ok": True, "sku": sku, "note": note.strip(), "version": new_version}
    except Exception as exc:
        _error_safe(exc, "ITEM_NOTE_SAVE")


@router.post("/scanner/api/cart/note/get")
async def cart_note_get(request: Request):
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request)
    try:
        note = await asyncio.to_thread(_cart_note_get, _id(body))
        return {"ok": True, "note": note}
    except Exception as exc:
        _error_safe(exc, "NOTE_GET")


@router.post("/scanner/api/cart/note/save")
async def cart_note_save(request: Request):
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request, limit=8192)
    note, rev = body.get("note"), body.get("revision")
    if (not isinstance(note, str) or len(note) > 1200 or
        type(rev) is not int or rev < 0 or chr(0) in note):
        raise HTTPException(400, "Invalid cart note")
    try:
        revision = await asyncio.to_thread(_cart_note_save, _id(body), rev, note.strip())
        return {"ok": True, "revision": revision, "note": note.strip()}
    except Exception as exc:
        _error_safe(exc, "NOTE_SAVE")


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
        cart = await asyncio.to_thread(
            _confirm_cart if state == "ready" else _mutate,
            cart_id, rev, **({} if state == "ready" else {"state": state, "actor": role})
        )
        return {"ok": True, "cart": cart}
    except Exception as exc:
        _error_safe(exc, "STATE")
    finally:
        if conn:
            conn.close()


@router.post("/scanner/api/cart/share-qr")
async def cart_share_qr(request: Request):
    """Render a customer QR locally; never send the access code to a QR site."""
    staff._check_origin(request)
    staff._require(request)
    body = await _body(request)
    code = body.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{8}", code):
        raise HTTPException(400, "Invalid customer share code")
    try:
        import base64
        import qrcode
        import qrcode.image.svg

        url = "https://xingwang-stock.onrender.com/scanner/guest#v=" + code
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=5, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        svg = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).to_string()
        return JSONResponse({"ok": True, "svg_base64": base64.b64encode(svg).decode("ascii")},
                            headers={"Cache-Control": "no-store"})
    except Exception as exc:
        _error_safe(exc, "SHARE_QR")


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
