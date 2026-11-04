# -*- coding: utf-8 -*-
"""Mobile QR scanner for stock/sample inspection.

Separate, authenticated operator interface. Existing Telegram, Xiaozhi and
public /stock endpoints remain unchanged. Never writes Access; TiDB is optional.
"""
import asyncio
import hashlib
import hmac
import os
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from xingwang_miniapp import scanner_tidb

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

router = APIRouter()
COOKIE = "xw_scanner_session"
TTL = 30 * 86400
CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()/-]{1,39}$")
LOGIN_ATTEMPTS = {}
REQUEST_TIMES = []
ORDER_REQUEST_TIMES = []  # Separate V41 budget; concurrent TiDB scans must not double-count.
LOCK = asyncio.Lock()
PENDING_SCANS = {}  # random scan_id => (time, signed-in device, series, real SKUs)
PAGE = Path(__file__).with_name("scanner.html").read_text(encoding="utf-8")


def _passcode():
    return os.environ.get("XW_SCANNER_PASSCODE", "")


def _key():
    password = _passcode()
    # Any non-empty configured password is valid; exact-match login is rate-limited.
    if not password:
        return None
    return hmac.new(os.environ["BRIDGE_SHARED_SECRET"].encode("utf-8"),
                    ("xw-scanner-cookie-v1:" + password).encode("utf-8"),
                    hashlib.sha256).digest()


def _sign(data):
    return hmac.new(_key(), data.encode("ascii"), hashlib.sha256).hexdigest()


def _authorized(request):
    if _key() is None:
        return False
    token = request.cookies.get(COOKIE, "")
    if len(token) > 200:
        return False
    try:
        exp, nonce, mac = token.split(".")
        if not exp.isdecimal() or not re.fullmatch(r"[a-f0-9]{24}", nonce):
            return False
        if not re.fullmatch(r"[a-f0-9]{64}", mac):
            return False
        now = time.time()
        if not now < int(exp) <= now + TTL + 60:
            return False
        return hmac.compare_digest(mac, _sign(exp + "." + nonce))
    except (ValueError, TypeError):
        return False


def _check_origin(request):
    # The UI only calls same-origin POSTs. Prevent cross-site cookie abuse.
    origin = request.headers.get("origin", "")
    host = request.headers.get("host", "")
    if not origin or origin not in ("https://" + host, "http://localhost:" + host.split(":")[-1]):
        raise HTTPException(403, "Invalid origin")


def _require(request):
    if not _authorized(request):
        raise HTTPException(401, "請先登入掃描器")


@router.get("/scanner", response_class=HTMLResponse)
async def scanner_page():
    # Prevent browser Back/cache from displaying an old staff workspace
    # after the dedicated guest entry has invalidated staff credentials.
    return HTMLResponse(PAGE, headers={
        "Cache-Control": "no-store, private, max-age=0",
        "Pragma": "no-cache",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "frame-ancestors 'none'",
    })


@router.get("/scanner/guest", response_class=HTMLResponse, include_in_schema=False)
async def scanner_guest_page(request: Request):
    headers = {
        "Cache-Control": "no-store, private, max-age=0",
        "Pragma": "no-cache",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "frame-ancestors 'none'",
    }
    if _authorized(request):
        # Do not silently sign staff out or let a staff browser enter guest
        # mode with privileged cookies. Customer must use their own browser.
        return HTMLResponse("""<!doctype html><html lang="zh-Hant"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>XINGWANG · Cliente</title>
<style>
:root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#28141c;background:#f8f4f5}
body{min-height:100dvh;display:grid;place-items:center;margin:0;padding:20px;box-sizing:border-box}
main{width:min(100%,440px);background:#fff;padding:24px;border-radius:16px;border:1px solid #e5d9df}
h1{font-size:19px;margin:0 0 10px}p{font-size:14px;line-height:1.7;color:#685860}
a{display:inline-flex;align-items:center;gap:8px;padding:12px 15px;border-radius:10px;color:#fff;background:#6a1b36;text-decoration:none;font-weight:700}
</style></head><body><main><h1>员工已登录 / Personal conectado</h1>
<p>当前是员工浏览器。为保护其他客户资料，请将专属连结发送给客户，在客户自己的手机或浏览器中打开。你的员工登录保持不变。</p>
<a href="/scanner" aria-label="回到员工首页 / Inicio">
<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" aria-hidden="true"><path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-7h6v7"/></svg>Home / Inicio</a>
</main></body></html>""", headers=headers)
    return HTMLResponse(PAGE, headers=headers)


@router.get("/scanner/start", response_class=HTMLResponse, include_in_schema=False)
async def scanner_public_start(request: Request):
    # Reuse the current Scanner HTML, never a second cart application.
    # A printed public QR contains no customer credential and no cart ID.
    if _authorized(request):
        # Staff opening the public QR keep their employee session; they
        # see the existing Home-only interstitial instead of guest access.
        return await scanner_guest_page(request)
    from xingwang_miniapp import scanner_cart
    token = scanner_cart.issue_start_cookie(request)
    response = HTMLResponse(PAGE, headers={
        "Cache-Control": "no-store, private, max-age=0",
        "Pragma": "no-cache",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "frame-ancestors 'none'",
    })
    response.set_cookie(scanner_cart.START_COOKIE, token,
                        max_age=scanner_cart.START_TTL, httponly=True,
                        secure=True,samesite="lax", path="/scanner")
    return response


@router.get("/scanner/cart.js", include_in_schema=False)
async def scanner_cart_javascript():
    source = Path(__file__).with_name("scanner_cart.js").read_text(encoding="utf-8")
    return Response(source, media_type="application/javascript", headers={
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/scanner/admin", include_in_schema=False)
async def scanner_admin_page():
    # Previous bookmarks now switch to a tab within the same /scanner HTML.
    return RedirectResponse(url="/scanner#admin",status_code=307)


@router.get("/scanner/api/session")
async def session(request: Request):
    return {"ok": True, "signed_in": _authorized(request),
            "configured": _key() is not None,
            "db_configured": scanner_tidb.configured()}


@router.post("/scanner/api/db/setup")
async def scanner_db_setup(request: Request):
    _check_origin(request)
    _require(request)
    if not scanner_tidb.configured():
        raise HTTPException(503, "請先在 Render Environment 設定 XW_SCANNER_TIDB_URL")
    try:
        result = await asyncio.to_thread(scanner_tidb.check_and_initialize)
        logging.getLogger("uvicorn.error").info(
            "SCANNER_TIDB_READY tables=%d",len(result["tables"])
        )
        return {"ok":True, **result}
    except Exception:
        logging.getLogger("uvicorn.error").exception("SCANNER_TIDB_SETUP_FAILED")
        raise HTTPException(503, "TiDB 連線或建表失敗，請檢查 Render 日誌")



# Manual Access -> Render -> TiDB snapshot. Uses the authenticated V33 bridge
# and the existing Flask /search endpoint; never executes arbitrary SQL.
_INVENTORY_LOCK = asyncio.Lock()
_INVENTORY_JOB = {"state": "idle"}
_INVENTORY_TASK = None


async def _inventory_run(job_id):
    global _INVENTORY_JOB
    from xingwang_miniapp import miniapp_server as relay
    from xingwang_miniapp import stock_sync_api
    import base64
    import zlib
    import json

    request_id = uuid4().hex
    started_clock = time.perf_counter()
    future = asyncio.get_running_loop().create_future()
    try:
        async with relay.bridge_lock:
            if relay.active_bridge is None or relay.active_role is None:
                raise RuntimeError("V33 is not online; please start the updated V33 bridge")
            if len(relay.waiting) >= relay.MAX_INFLIGHT:
                raise RuntimeError("V33 bridge is busy")
            ws = relay.active_bridge
            relay.waiting[request_id] = (future, ws)
            try:
                await relay.send_peer(relay.active_role, {
                    "type": "query", "id": request_id, "source": "scanner_admin",
                    "action": "stock_snapshot", "q": "@"
                })
            except Exception:
                relay.waiting.pop(request_id, None)
                raise RuntimeError("Failed to send stock sync command to V33")
        try:
            response = await asyncio.wait_for(future, timeout=220)
        finally:
            relay.waiting.pop(request_id, None)

        bridge_ms = round((time.perf_counter() - started_clock) * 1000)
        if not isinstance(response, dict) or response.get("ok") is not True:
            code = response.get("code", "UNAVAILABLE") if isinstance(response, dict) else "INVALID"
            if code == "ACCESS_DENIED":
                raise RuntimeError("V33 does not support the new sync command; install V33 Sync")
            safe_errors = {
                "FLASK_TIMEOUT": "本機 Flask /search 查詢逾時，請檢查本機 Flask 的 CMD 日誌",
                "FLASK_OFFLINE": "本機 Flask 無法連線，請確認 Flask 正在運行",
                "FLASK_AUTH": "V33 登入本機 Flask 失敗，請檢查原有 Flask 設定",
                "FLASK_HTTP": "本機 Flask 回傳 HTTP 錯誤，請檢查 Flask 日誌",
                "FLASK_QUERY": "本機 Flask /api/stock-snapshot 查詢失敗，請檢查 Flask CMD",
                "FLASK_API_MISSING": "本機 Flask 尚未啟用 /api/stock-snapshot，請啟動已加入 API 的 V246",
                "INVENTORY_INCOMPLETE": "Flask 完整快照標記、筆數或分類統計不一致，已取消同步",
                "INVENTORY_BAD_DATA": "Flask 完整庫存包含格式錯誤的商品或數量，已取消同步",
                "FLASK_FILTER_IGNORED": "舊版 V33 庫存篩選失敗，請更換最新 V33 Flask API 版",
                "INVENTORY_EMPTY": "Flask 回傳空庫存，已取消同步；請檢查 Access 查詢",
                "INVENTORY_MISSING": "部分庫存數量缺失，已取消同步",
                "INVENTORY_DUPLICATE": "庫存編號重複，已取消同步",
                "LOCAL_API": "本機 Flask 庫存資料檢查失敗，請查看 V33 CMD 同步錯誤代碼",
            }
            message = safe_errors.get(code, "V33 庫存同步無法完成")
            raise RuntimeError(message + " [" + str(code)[:30] + "]")
        data = response.get("data")
        if not isinstance(data, dict) or data.get("encoding") != "zlib-base64":
            raise RuntimeError("Invalid inventory transfer format from V33")
        encoded = data.get("payload")
        if not isinstance(encoded, str) or len(encoded) > 16 * 1024 * 1024:
            raise RuntimeError("Compressed inventory exceeds allowed size")
        compressed = base64.b64decode(encoded, validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, 20 * 1024 * 1024 + 1)
        if (len(raw) > 20 * 1024 * 1024 or not decoder.eof
                or decoder.unconsumed_tail or decoder.unused_data
                or len(raw) != data.get("original_bytes")
                or hashlib.sha256(raw).hexdigest() != data.get("sha256")):
            raise RuntimeError("Corrupted or oversized stock snapshot")
        snapshot = stock_sync_api._validate(json.loads(raw))
        read_ms = round((time.perf_counter() - started_clock) * 1000)
        async with _INVENTORY_LOCK:
            if _INVENTORY_JOB.get("id") == job_id:
                _INVENTORY_JOB = {"state":"writing", "id":job_id,
                                  "started_at":_INVENTORY_JOB["started_at"]}
        loop = asyncio.get_running_loop()
        def publish_progress(phase, completed, total):
            # Store progress on the event loop, never mutate response state
            # from the database worker thread.
            def update():
                if _INVENTORY_JOB.get("id") == job_id:
                    _INVENTORY_JOB.update({
                        "phase":phase,
                        "processed":int(completed),
                        "total_changes":int(total),
                        "snapshot_count":len(snapshot),
                    })
            loop.call_soon_threadsafe(update)
        db_start_clock = time.perf_counter()
        result = await asyncio.to_thread(
            stock_sync_api._sync_blocking, snapshot, False, publish_progress
        )
        db_ms = round((time.perf_counter() - db_start_clock) * 1000)
        result["timings_ms"] = {
            "bridge":bridge_ms, "validation_and_transfer":read_ms-bridge_ms,
            "database":db_ms,
            "total":round((time.perf_counter()-started_clock)*1000),
        }
        async with _INVENTORY_LOCK:
            if _INVENTORY_JOB.get("id") == job_id:
                _INVENTORY_JOB = {"state":"success", "id":job_id, "result":result}
        logging.getLogger("uvicorn.error").info(
            "STOCK_SYNC_OK total=%d inserted=%d updated=%d deactivated=%d bridge_ms=%d db_ms=%d total_ms=%d",
            result["sku_count"], result["inserted"],
            result["updated"], result["deactivated"],
            bridge_ms, db_ms, result["timings_ms"]["total"])
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Never include host/credential details from arbitrary DB exceptions.
        if isinstance(exc, RuntimeError):
            safe = str(exc)[:180]
        elif isinstance(exc, ValueError):
            # These messages are fixed constants from the validator, never SKU,
            # quantity, credential or raw client data.
            allowed_reasons = {
                "Unsupported payload format",
                "Full snapshot required",
                "Invalid inventory size",
                "Inventory row count mismatch",
                "Invalid inventory row",
                "Invalid SKU in inventory",
                "Duplicate SKU in inventory",
                "Missing stock quantity field",
                "Missing or invalid inventory quantity",
                "Invalid inventory quantity",
                "Out-of-range inventory quantity",
                "Inventory quantity has too many decimal places",
                "Inventory category count mismatch",
            }
            reason = str(exc)
            if reason.startswith("STOCK_SNAPSHOT_TOO_SMALL:"):
                safe = (
                    "完整庫存筆數比目前 TiDB 少超過 20%，已保留舊庫存；"
                    "請檢查 Access 是否完整回傳"
                )
                reason_code = "STOCK_SNAPSHOT_TOO_SMALL"
            elif reason.startswith("STOCK_SCOPE_MISMATCH:"):
                safe = "庫存範圍不一致，已保留 TiDB 原資料"
                reason_code = "STOCK_SCOPE_MISMATCH"
            elif reason in allowed_reasons:
                safe = "資料驗證失敗：" + reason
                reason_code = reason
            else:
                safe = "Inventory validation failed; previous TiDB snapshot retained"
                reason_code = "UNKNOWN"
            logging.getLogger("uvicorn.error").warning(
                "STOCK_VALIDATION_REJECTED reason=%s", reason_code,
            )
        else:
            safe = "Stock sync failed; see Render logs"
        logging.getLogger("uvicorn.error").error(
            "STOCK_SYNC_TASK_FAILED kind=%s", type(exc).__name__)
        async with _INVENTORY_LOCK:
            if _INVENTORY_JOB.get("id") == job_id:
                _INVENTORY_JOB = {"state":"failed", "id":job_id, "error":safe}


@router.post("/scanner/api/inventory/start")
async def inventory_start(request: Request):
    global _INVENTORY_TASK, _INVENTORY_JOB
    _check_origin(request)
    _require(request)
    if not scanner_tidb.configured():
        raise HTTPException(503, "TiDB is not configured in Render")
    from xingwang_miniapp import miniapp_server as relay
    async with _INVENTORY_LOCK:
        if _INVENTORY_JOB.get("state") in ("reading", "writing"):
            raise HTTPException(409, "Stock sync already in progress")
        if relay.active_bridge is None or relay.active_role is None:
            raise HTTPException(503, "V33 is not online. Open local Flask and the updated V33.")
        job_id = uuid4().hex
        _INVENTORY_JOB = {
            "state":"reading", "id":job_id,
            "started_at":datetime.now(timezone.utc).isoformat(timespec="seconds")
        }
        _INVENTORY_TASK = asyncio.create_task(_inventory_run(job_id),
                                              name="manual-access-stock-sync")
    return {"ok":True, "state":"reading", "job_id":job_id}


@router.get("/scanner/api/inventory/status")
async def inventory_status(request: Request):
    _require(request)
    from xingwang_miniapp import stock_sync_api
    job = dict(_INVENTORY_JOB)
    if job.get("state") in ("reading", "writing"):
        # A TiDB connection on each 3-second poll slowed down small Starter
        # instances. Do not query the database while a write is running.
        return {"ok":True, "job":job,
                "last_success":{"success":True,"has_synced":False,"pending":True}}
    try:
        last = await asyncio.to_thread(stock_sync_api._status_blocking)
    except Exception:
        last = {"success":False, "has_synced":False}
    return {"ok":True, "job":job, "last_success":last}


@router.post("/scanner/api/login")
async def login(request: Request):
    _check_origin(request)
    if _key() is None:
        raise HTTPException(503, "請先在 Render 設定掃描器登入碼")
    async with LOCK:
        now = time.monotonic()
        # Both per-client and global limits; no password in error responses/logs.
        for key, values in list(LOGIN_ATTEMPTS.items()):
            LOGIN_ATTEMPTS[key] = [v for v in values if now - v < 900]
            if not LOGIN_ATTEMPTS[key]:
                del LOGIN_ATTEMPTS[key]
        ip = request.client.host if request.client else "unknown"
        values = LOGIN_ATTEMPTS.setdefault(ip, [])
        total = sum(len(v) for v in LOGIN_ATTEMPTS.values())
        if len(values) >= 8 or total >= 80:
            raise HTTPException(429, "登入嘗試過多，請稍後再試")
        values.append(now)
    if int(request.headers.get("content-length", "0") or 0) > 256:
        raise HTTPException(413, "Request too large")
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid JSON")
    code = body.get("passcode") if isinstance(body, dict) else None
    if not isinstance(code, str) or not hmac.compare_digest(code, _passcode()):
        raise HTTPException(401, "登入碼錯誤")
    expires = str(int(time.time()) + TTL)
    nonce = secrets.token_hex(12)
    data = expires + "." + nonce
    resp = JSONResponse({"ok": True, "signed_in": True})
    resp.set_cookie(COOKIE, data + "." + _sign(data),
                    max_age=TTL, httponly=True, secure=True, samesite="lax",
                    path="/scanner")
    return resp


@router.post("/scanner/api/logout")
async def logout(request: Request):
    _check_origin(request)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/scanner", secure=True, httponly=True, samesite="lax")
    return resp




@router.post("/scanner/api/quick")
async def scanner_quick_stock(request: Request):
    """Fast stock-only lookup; never returns a customer's business records."""
    _check_origin(request)
    _require(request)
    if not scanner_tidb.configured():
        raise HTTPException(503, "TiDB 庫存尚未設定")
    if int(request.headers.get("content-length","0") or 0) > 512:
        raise HTTPException(413, "Request too large")
    try:
        payload = await request.json()
    except (ValueError,UnicodeError):
        raise HTTPException(400, "Invalid JSON")
    code = payload.get("code") if isinstance(payload,dict) else None
    if not isinstance(code,str) or not CODE.fullmatch(code.strip()):
        raise HTTPException(400, "商品編號格式不正確")
    async with LOCK:
        now = time.monotonic()
        REQUEST_TIMES[:] = [v for v in REQUEST_TIMES if now-v < 60]
        if len(REQUEST_TIMES) >= 35:
            raise HTTPException(429, "查詢太頻繁，請稍後重試")
        REQUEST_TIMES.append(now)
    start = time.perf_counter()
    try:
        data = await asyncio.to_thread(scanner_tidb.read_fast_stock, code.strip().upper())
    except ValueError:
        raise HTTPException(422, "商品編號範圍太大，請輸入更完整編號")
    except Exception:
        logging.getLogger("uvicorn.error").exception("SCANNER_QUICK_STOCK_FAILED")
        raise HTTPException(503, "快速庫存查詢失敗")
    if not data["variants"]:
        raise HTTPException(404, "快照中沒有符合的商品編號")
    return JSONResponse({"ok": True, **data,
                         "elapsed_ms":round((time.perf_counter()-start)*1000,1),
                         "db_connected":False,"scan_id":None,
                         "previous_status":{}})


@router.get("/scanner/api/stock-freshness")
async def sample_stock_freshness(request: Request):
    _require(request)
    if not scanner_tidb.configured():
        raise HTTPException(503, "TiDB 尚未設定，無法盤點")
    try:
        return await asyncio.to_thread(scanner_tidb.stock_freshness)
    except Exception:
        logging.getLogger("uvicorn.error").exception("SAMPLE_FRESHNESS_FAILED")
        raise HTTPException(503, "無法讀取庫存同步時間，請檢查 TiDB")


@router.post("/scanner/api/sample")
async def sample_from_tidb(request: Request):
    _check_origin(request)
    _require(request)
    if not scanner_tidb.configured():
        raise HTTPException(503, "TiDB 尚未設定，無法盤點")
    if int(request.headers.get("content-length", "0") or 0) > 512:
        raise HTTPException(413, "Request too large")
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid JSON")
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str) or not CODE.fullmatch(code.strip()):
        raise HTTPException(400, "商品編號格式不正確")
    if "allow_stale" in body and type(body["allow_stale"]) is not bool:
        raise HTTPException(400, "Invalid stale snapshot choice")
    allow_stale = body.get("allow_stale") is True
    code = code.strip().upper()
    async with LOCK:
        now = time.monotonic()
        REQUEST_TIMES[:] = [t for t in REQUEST_TIMES if now - t < 60]
        if len(REQUEST_TIMES) >= 35:
            raise HTTPException(429, "查詢太頻繁，請稍後再試")
        REQUEST_TIMES.append(now)
    try:
        data = await asyncio.to_thread(scanner_tidb.read_sample_from_snapshot, code, allow_stale)
    except ValueError as exc:
        if str(exc) == "TOO_MANY_SAMPLE_SKUS":
            raise HTTPException(422, "這個系列超過 500 個編號，請輸入更完整的商品編號")
        raise HTTPException(422, "快照包含不支援的商品編號，請檢查庫存資料")
    except Exception:
        logging.getLogger("uvicorn.error").exception("SAMPLE_SNAPSHOT_READ_FAILED")
        raise HTTPException(503, "TiDB 庫存查詢失敗，請稍後再試")
    fresh = data["freshness"]
    if not fresh["has_synced"]:
        raise HTTPException(409, "尚無有效庫存快照，請先更新庫存")
    if not fresh["fresh"] and not allow_stale:
        raise HTTPException(409, "庫存超過 60 分鐘，請選擇繼續使用舊庫存或先更新")
    if not fresh["fresh"]:
        logging.getLogger("uvicorn.error").info(
            "SAMPLE_STALE_SNAPSHOT_ACK series=%r snapshot=%s",
            code, fresh["synced_at_utc"])
    variants = data["variants"]
    if not variants:
        raise HTTPException(404, "TiDB 庫存快照找不到這個商品編號")
    scan_id = uuid4().hex
    device = hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest()[:16]
    now = time.monotonic()
    for token, entry in list(PENDING_SCANS.items()):
        if now - entry[0] > 1800:
            PENDING_SCANS.pop(token, None)
    if len(PENDING_SCANS) >= 500:
        PENDING_SCANS.pop(next(iter(PENDING_SCANS)))
    PENDING_SCANS[scan_id] = (
        now, device, code, tuple(v["code"] for v in variants),
        fresh["synced_at_utc"]
    )
    return JSONResponse({
        "ok": True, "product_code": code,
        "stock_rolls": data["stock_rolls"],
        "stock_meters": data["stock_meters"],
        "variants": variants, "source": "tidb",
        "as_of": fresh["synced_at_utc"],
        "freshness": fresh,
        "db_connected": True, "db_error": False,
        "scan_id": scan_id, "previous_status": data["previous_status"],
        "last_checked_at": data["last_checked_at"],
        "last_checked_count": data["last_checked_count"],
        "last_missing_count": data["last_missing_count"],
    })


def attach_stock_lookup(stock_lookup, order_stock_select):
    """Bind the existing read-only V33 stock bridge, without modifying it."""
    @router.post("/scanner/api/stock")
    async def scanner_stock(request: Request):
        _check_origin(request)
        _require(request)
        if int(request.headers.get("content-length", "0") or 0) > 512:
            raise HTTPException(413, "Request too large")
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid JSON")
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str) or not CODE.fullmatch(code.strip()):
            raise HTTPException(400, "Invalid product code")
        code = code.strip().upper()
        async with LOCK:
            now = time.monotonic()
            REQUEST_TIMES[:] = [v for v in REQUEST_TIMES if now - v < 60]
            if len(REQUEST_TIMES) >= 35:
                raise HTTPException(429, "查詢太頻繁，請稍後重試")
            REQUEST_TIMES.append(now)
        from xingwang_miniapp.stock_mcp import normalize_stock, stock_variant_breakdown
        raw = await stock_lookup(code)
        clean = normalize_stock(raw, code)
        if not clean.get("ok"):
            err = clean.get("code") or "STOCK_UNAVAILABLE"
            status = 404 if err == "NOT_FOUND" else 429 if err == "BUSY" else 503
            return JSONResponse({"ok": False, "code": err,
                "error": "庫存不存在" if status == 404 else
                         "本機 V33 離線或庫存暫時無法查詢，請確認 V33 已開啟"}, status_code=status)
        variants = stock_variant_breakdown(clean)
        return JSONResponse({"ok": True, "product_code": code,
            "stock_rolls": clean.get("stock_rolls"),
            "stock_meters": clean.get("stock_meters"),
            "incoming_boxes": clean.get("incoming_boxes"),
            "variants": variants,
            "source": clean.get("source"), "as_of": clean.get("as_of"),
            "db_connected": False, "db_error": False,
            "scan_id": None, "previous_status": {}})

    @router.post("/scanner/api/orders")
    async def scanner_order_stock(request: Request):
        """Authenticated, fixed-query V41 order stock lookup (never saves SKUs)."""
        _check_origin(request)
        _require(request)
        if int(request.headers.get("content-length", "0") or 0) > 256:
            raise HTTPException(413, "Request too large")
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid JSON")
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str) or not CODE.fullmatch(code.strip()):
            raise HTTPException(400, "Invalid product code")
        code = code.strip().upper()
        async with LOCK:
            now = time.monotonic()
            ORDER_REQUEST_TIMES[:] = [v for v in ORDER_REQUEST_TIMES if now - v < 60]
            if len(ORDER_REQUEST_TIMES) >= 35:
                raise HTTPException(429, "查询过于频繁")
            ORDER_REQUEST_TIMES.append(now)
        upstream = await order_stock_select(code)
        if not isinstance(upstream, dict) or not upstream.get("ok"):
            reason = upstream.get("code", "UNAVAILABLE") if isinstance(upstream, dict) else "UNAVAILABLE"
            safe_messages = {
                "DISABLED": "本机 V41 唯读 SELECT 通道尚未启用",
                "LOCAL_OFFLINE": "本机连接离线，订单库存无法核对",
                "BUSY": "本机忙碌，稍后重新查询",
                "STANDBY": "本机正在切换，稍后重新查询",
                "SWITCHING": "本机正在切换，稍后重新查询",
                "TIMEOUT": "本机订单库存查询超时",
                "LOCAL_API": "本机唯读 Access 快照或登入尚不可用",
                "ACCESS_DENIED": "本机 V41 不支持此唯读查询",
            }
            return JSONResponse({"ok": False, "code": reason,
                                 "error": safe_messages.get(reason, "本机订单库存暂时无法查询")},
                                status_code=429 if reason == "BUSY" else 503)
        payload = upstream.get("data")
        if not isinstance(payload, dict):
            raise HTTPException(502, "Invalid local SELECT response")
        columns, rows = payload.get("columns"), payload.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list) or len(rows) > 200:
            raise HTTPException(502, "Invalid local SELECT rows")
        try:
            indices = {str(name).lower(): idx for idx, name in enumerate(columns)}
            sku_idx = indices["sku"]
            rolls_idx = indices["rollos"]
            meters_idx = indices["metros"]
        except (KeyError, ValueError, TypeError):
            raise HTTPException(502, "Invalid local SELECT columns")
        from decimal import Decimal, InvalidOperation
        order_rows = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or max(sku_idx, rolls_idx, meters_idx) >= len(row):
                raise HTTPException(502, "Invalid order row")
            sku = row[sku_idx]
            if not isinstance(sku, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.()/*-]{1,99}", sku) or not sku.upper().startswith(code):
                raise HTTPException(502, "Invalid order SKU")
            if not re.search(r"\([^()]{1,40}\)", sku):
                continue
            try:
                rolls = Decimal(str(row[rolls_idx]))
                if not rolls.is_finite() or rolls <= 0:
                    continue
            except (InvalidOperation, TypeError, ValueError):
                continue
            meters = row[meters_idx]
            if meters is not None:
                try:
                    value = Decimal(str(meters))
                    meters = str(value) if value.is_finite() else None
                except (InvalidOperation, TypeError, ValueError):
                    meters = None
            order_rows.append({"code": sku, "stock_rolls": str(rolls),
                               "stock_meters": meters})
        return JSONResponse({"ok": True, "product_code": code, "variants": order_rows,
                             "count": len(order_rows), "source": "access_v41_readonly"})


    @router.post("/scanner/api/save")
    async def scanner_save(request: Request):
        _check_origin(request)
        _require(request)
        if not scanner_tidb.configured():
            raise HTTPException(503, "TiDB 尚未設定，無法保存")
        if int(request.headers.get("content-length", "0") or 0) > 6000:
            raise HTTPException(413, "Request too large")
        try:
            data = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid JSON")
        if not isinstance(data, dict):
            raise HTTPException(400, "Invalid request")
        scan_id = data.get("scan_id")
        missed = data.get("missing")
        present = data.get("present")
        if "allow_stale" in data and type(data["allow_stale"]) is not bool:
            raise HTTPException(400, "Invalid stale snapshot choice")
        allow_stale = data.get("allow_stale") is True
        # Explicitly confirmed states only: never write hidden, unchecked or
        # unreviewed SKUs. An empty or overlapping selection is invalid.
        if (not isinstance(scan_id,str) or
            not re.fullmatch(r"[a-f0-9]{32}",scan_id) or
            not isinstance(missed,list) or not isinstance(present,list) or
            len(missed)+len(present)>500 or
            any(not isinstance(v,str) for v in missed+present) or
            len(set(missed)) != len(missed) or
            len(set(present)) != len(present) or
            set(missed).intersection(present) or
            not (missed or present)):
            raise HTTPException(400, "請至少確認一個有樣或無樣的商品")
        session = PENDING_SCANS.get(scan_id)
        if not session or time.monotonic()-session[0]>1800 or len(session)!=5:
            raise HTTPException(409, "這次掃描已過期，請重新查詢")
        started, owner, series, skus, snapshot_version = session
        device_id = hashlib.sha256(request.cookies.get(COOKIE,"").encode()).hexdigest()[:16]
        confirmed = set(missed) | set(present)
        if not hmac.compare_digest(owner,device_id) or not confirmed.issubset(skus):
            raise HTTPException(403, "Invalid scan authorization")
        try:
            fresh = await asyncio.to_thread(scanner_tidb.stock_freshness)
            if not fresh["has_synced"] or fresh["synced_at_utc"] != snapshot_version:
                raise HTTPException(
                    409, "庫存快照已重新同步或無效；請重新查詢布樣"
                )
            if not fresh["fresh"] and not allow_stale:
                raise HTTPException(
                    409, "庫存已超過 60 分鐘；請選擇繼續使用舊庫存後再儲存"
                )
            result=await asyncio.to_thread(
                scanner_tidb.save_scan, scan_id, series,
                tuple(v for v in skus if v in confirmed), missed, device_id
            )
        except HTTPException:
            raise
        except Exception:
            logging.getLogger("uvicorn.error").exception(
                "SCANNER_TIDB_SAVE_FAILED series=%r",series
            )
            raise HTTPException(503, "TiDB 無法寫入，這次盤點未成功保存")
        return JSONResponse({"ok":True,"scan_id":scan_id,**result})
