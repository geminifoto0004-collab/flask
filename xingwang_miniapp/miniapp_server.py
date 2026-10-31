# -*- coding: utf-8 -*-
"""XINGWANG Mini App relay: no business database or Telegram bot token on Render.
Only a paired local worker can respond. The worker validates Telegram initData and group membership.
Run exactly one worker.
"""
import asyncio
import hmac
import json
import os
import time
import logging
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from contextlib import asynccontextmanager

SECRET = os.environ.get("BRIDGE_SHARED_SECRET", "")
if len(SECRET) < 32:
    raise RuntimeError("BRIDGE_SHARED_SECRET must be at least 32 characters")
stock_mcp_service = None

async def _scanner_tidb_bootstrap():
    """Best-effort setup; scanner DB failure must not block Telegram / Xiaozhi."""
    from xingwang_miniapp import scanner_tidb
    logger = logging.getLogger("uvicorn.error")
    if not scanner_tidb.configured():
        logger.info("SCANNER_TIDB_NOT_CONFIGURED")
        return
    logger.info("SCANNER_TIDB_CONNECTING")
    try:
        result = await asyncio.to_thread(scanner_tidb.check_and_initialize)
        logger.info(
            "SCANNER_TIDB_READY database=xingwang_stock tables=%d stock=%d samples=%d",
            len(result["tables"]), result["stock_count"], result["sample_count"],
        )
    except Exception as exc:
        # Avoid logging secret URL or connection credentials.
        errno = (getattr(exc, "args", ()) or (None,))[0]
        errno = errno if isinstance(errno, int) else "unknown"
        logger.error(
            "SCANNER_TIDB_SETUP_FAILED error_type=%s error_code=%s",
            type(exc).__name__, errno,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One additional background client inside this same Render web service.
    # Completely disabled by default; Telegram and ChatGPT MCP stay unchanged.
    scanner_setup_task = asyncio.create_task(
        _scanner_tidb_bootstrap(), name="scanner-tidb-bootstrap"
    )
    xiaozhi_task = None
    if os.environ.get("XW_XIAOZHI_ENABLED", "0") == "1":
        from xingwang_miniapp.xiaozhi_mcp import run_forever
        xiaozhi_task = asyncio.create_task(run_forever(), name="xiaozhi-mcp")
    try:
        if stock_mcp_service is None:
            yield
        else:
            async with stock_mcp_service.session_manager.run():
                yield
    finally:
        scanner_setup_task.cancel()
        await asyncio.gather(scanner_setup_task, return_exceptions=True)
        if xiaozhi_task is not None:
            xiaozhi_task.cancel()
            await asyncio.gather(xiaozhi_task, return_exceptions=True)

app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None, lifespan=lifespan)
from xingwang_miniapp.stock_sync_api import router as stock_sync_router
app.include_router(stock_sync_router)
PAGE = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
active_bridge = None
active_role = None
bridge_lock = asyncio.Lock()
peers = {}
waiting = {}  # id -> (future, owner socket)
MAX_INFLIGHT = 20
# The old host's 12-sec local lease and in-flight requests must expire.
HANDOVER_SECONDS = 32
# Local LeaderGate.TTL_SECONDS is 12. Keep 2s extra for network/clock
# scheduling when the SAME local machine reconnects. Different hosts and
# cold Render restarts still wait the original conservative 32s.
SAME_ROLE_RECONNECT_GRACE_SECONDS = 14
_last_active_role = None
_last_active_lease_until = 0.0
HEARTBEAT_SECONDS = 3
PEER_TIMEOUT_SECONDS = 10
handover_task = None
handover_version = 0
# This pilot is OFF unless enabled with a separate, revocable 32+ char ticket.
# No time-based expiry: operator can disable the flag or rotate the ticket.
pilot_recent_calls = []
pilot_rate_lock = asyncio.Lock()

# Public read-only stock URL for ChatGPT voice / browser URL reads.
# Intentionally has NO token. It exposes only stock quantities and incoming
# quantities, never prices, customers, orders, notes, or raw Flask payloads.
public_stock_recent_calls = []
public_stock_rate_lock = asyncio.Lock()

@app.middleware("http")
async def nocache(request:Request,call_next):
    # A true server-side request receives a unique trace ID. A web search
    # response copied from a prior crawl cannot have a fresh Render trace.
    stock_trace = request.url.path == "/stock" or request.url.path.startswith("/stock/")
    if stock_trace:
        request.state.stock_trace_id = uuid4().hex
        started = time.monotonic()
        product = (request.url.path[len("/stock/"):] if request.url.path.startswith("/stock/") else request.query_params.get("code", ""))[:60]
        logging.getLogger("uvicorn.error").info(
            "STOCK_TRACE start id=%s product=%r",
            request.state.stock_trace_id, product,
        )
    response = await call_next(request)
    if stock_trace:
        trace_id = request.state.stock_trace_id
        response.headers["X-XW-Stock-Request-ID"] = trace_id
        logging.getLogger("uvicorn.error").info(
            "STOCK_TRACE finish id=%s status=%s duration_ms=%d",
            trace_id, response.status_code,
            round((time.monotonic() - started) * 1000),
        )
    response.headers["Cache-Control"] = "private, no-store, no-cache, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Surrogate-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(PAGE)

@app.get("/admin", response_class=HTMLResponse)
async def admin():
    return HTMLResponse(PAGE)

@app.get("/healthz")
async def healthz():
    return {"service":"xingwang-miniapp","local_online":active_bridge is not None,"active_site":active_role,"home_online":"home" in peers,"company_online":"company" in peers}


async def send_peer(role, payload):
    peer=peers.get(role)
    if peer is not None:
        async with peer["send_lock"]:
            await peer["ws"].send_json(payload)

def best_role():
    return "company" if "company" in peers else "home" if "home" in peers else None

def cancel_owner(ws):
    for future,owner in waiting.values():
        if owner is ws and not future.done():
            future.set_result({"ok":False,"code":"SWITCHING",
                               "error":"正在切换公司／家里的电脑，请稍后重新查询"})

def _handover_delay_for(selected: str) -> float:
    """Short recovery ONLY if this process observed the old same-role owner.

    Never shorten cold startup or cross-role handover; in those cases an old
    machine/previous Render instance could still hold a Telegram lease.
    """
    if selected == _last_active_role and _last_active_lease_until > 0:
        return min(HANDOVER_SECONDS, max(0.0, _last_active_lease_until - time.monotonic()))
    return HANDOVER_SECONDS


async def promote_after(version, delay: float):
    global active_bridge,active_role
    await asyncio.sleep(delay)
    async with bridge_lock:
        if version!=handover_version or active_bridge is not None:return
        role=best_role()
        if role is None:return
        target=peers[role]["ws"]
        try:
            await send_peer(role,{"type":"active","epoch":version})
        except (RuntimeError,WebSocketDisconnect,OSError):
            return
        active_bridge=target
        active_role=role
        logging.getLogger("uvicorn.error").info(
            "BRIDGE_ACTIVE role=%s epoch=%s", role, version
        )

async def rebalance():
    """Must hold bridge_lock. Old lease expires before promotion."""
    global active_bridge,active_role,handover_task,handover_version
    global _last_active_role, _last_active_lease_until
    selected=best_role()
    if active_bridge is not None and active_role==selected:
        for role in peers:
            if role!=active_role:
                try:await send_peer(role,{"type":"standby"})
                except (RuntimeError,WebSocketDisconnect,OSError):pass
        return
    former=active_bridge
    if former is not None:
        _last_active_role=active_role
        _last_active_lease_until=time.monotonic()+SAME_ROLE_RECONNECT_GRACE_SECONDS
    active_bridge=None
    active_role=None
    if former is not None:cancel_owner(former)
    handover_version+=1
    if handover_task is not None:handover_task.cancel()
    for role in peers:
        try:await send_peer(role,{"type":"standby"})
        except (RuntimeError,WebSocketDisconnect,OSError):pass
    if selected is not None:
        delay=_handover_delay_for(selected)
        logging.getLogger("uvicorn.error").info(
            "BRIDGE_HANDOVER role=%s wait_seconds=%.2f same_role=%s",
            selected, delay, selected == _last_active_role,
        )
        handover_task=asyncio.create_task(promote_after(handover_version,delay))

async def peer_heartbeat(role,ws):
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        entry=peers.get(role)
        if entry is None or entry["ws"] is not ws:return
        if time.monotonic()-entry["last_pong"]>PEER_TIMEOUT_SECONDS:
            logging.getLogger("uvicorn.error").warning(
                "BRIDGE_DISCONNECT role=%s cause=heartbeat_timeout", role
            )
            try:await ws.close(code=1011,reason="Heartbeat timeout")
            except (RuntimeError,WebSocketDisconnect,OSError):pass
            return
        try:await send_peer(role,{"type":"ping"})
        except (RuntimeError,WebSocketDisconnect,OSError):return

@app.post("/api/query")
async def query(request:Request):
    try:
        raw = await request.body()
        if len(raw)>6000:raise HTTPException(413,"Request too large")
        payload = json.loads(raw)
    except HTTPException:raise
    except (ValueError,UnicodeError):raise HTTPException(400,"Invalid JSON")
    if not isinstance(payload,dict):raise HTTPException(400,"Invalid query")
    alias,action,q,init_data = (payload.get(k) for k in ("bot","action","q","init_data"))
    if alias not in ("STOCK","ADMIN") or action not in ("stock","camino","orders","nota","history_more","nota_media","nota_details"):
        raise HTTPException(400,"Unsupported action")
    if not isinstance(q,str) or not ((q=="@" and action=="nota") or (action=="nota" and len(q)==1 and q.isdecimal()) or 2<=len(q)<=40) or not isinstance(init_data,str) or not (1<=len(init_data)<=4096):
        raise HTTPException(400,"Invalid input")
    session = payload.get("miniapp_session", "")
    if not isinstance(session, str) or len(session) > 100:
        raise HTTPException(400, "Invalid Mini App session")
    extra = {"miniapp_session": session}
    if action == "nota":
        span = payload.get("date_span","2y")
        if not isinstance(span,str) or span not in ("1y","2y","all"):
            raise HTTPException(400,"Invalid Nota date range")
        extra.update({"date_span":span})
    if action == "history_more":
        cursor = payload.get("cursor")
        include_older = payload.get("include_older")
        if type(cursor) is not int or not (0<=cursor<=5000) or type(include_older) is not bool:
            raise HTTPException(400,"Invalid history pagination")
        extra.update({"cursor":cursor,"include_older":include_older})
    if action in ("nota_media","nota_details"):
        customer=payload.get("customer","")
        if not q.isdecimal() or not 2<=len(q)<=12 or not isinstance(customer,str) or len(customer)>130:
            raise HTTPException(400,"Invalid Nota image request")
        extra.update({"customer":customer})
    async with bridge_lock:
        ws=active_bridge
        role=active_role
        if ws is None or role is None:raise HTTPException(503,"本机切换中或未连线，请稍后重试")
        if len(waiting)>=MAX_INFLIGHT:raise HTTPException(429,"查詢過多")
        req_id=uuid4().hex
        future=asyncio.get_running_loop().create_future()
        waiting[req_id]=(future,ws)
        try:
            await send_peer(role,{"type":"query","id":req_id,"bot":alias,"action":action,"q":q,"init_data":init_data,**extra})
        except (RuntimeError,WebSocketDisconnect):
            waiting.pop(req_id,None)
            raise HTTPException(503,"連線中斷")
    try:
        response=await asyncio.wait_for(future,45)
    except asyncio.TimeoutError:
        raise HTTPException(504,"查詢逾時")
    finally:
        waiting.pop(req_id,None)
    if not response.get("ok"):
        # Authorization problems are 403; local API failures are 502, never "zero inventory".
        code = response.get("code") or "ACCESS_DENIED"
        status = 503 if code in ("SWITCHING","STANDBY") else 502 if code in ("LOCAL_API", "INTERNAL") else 409 if code == "HISTORY_EXPIRED" else 400 if code == "INPUT" else 403
        return JSONResponse({"ok":False, "code":code,
                             "error":str(response.get("error") or "查詢未完成")[:150]},
                            status_code=status)
    result = {"ok":True,"data":response.get("data")}
    session_return = response.get("miniapp_session", "")
    if isinstance(session_return, str) and len(session_return) <= 100 and session_return.startswith("xw_"):
        result["miniapp_session"] = session_return
    return result

@app.websocket("/bridge")
async def bridge(ws:WebSocket):
    role=ws.query_params.get("role","")
    proto=ws.query_params.get("protocol","")
    if (not hmac.compare_digest(ws.headers.get("authorization",""),"Bearer "+SECRET)
        or role not in ("home","company") or proto!="v20"):
        await ws.close(code=1008)
        return
    await ws.accept()
    async with bridge_lock:
        if role in peers:
            await ws.close(code=1008)
            return
        peers[role]={"ws":ws,"last_pong":time.monotonic(),"send_lock":asyncio.Lock()}
        await rebalance()
    heartbeat=asyncio.create_task(peer_heartbeat(role,ws))
    try:
        while True:
            msg=await ws.receive_json()
            if not isinstance(msg,dict):continue
            if msg.get("type")=="pong":
                entry=peers.get(role)
                if entry is not None and entry["ws"] is ws:
                    entry["last_pong"]=time.monotonic()
            elif msg.get("type")=="response" and active_bridge is ws:
                record=waiting.get(msg.get("id"))
                if record is not None:
                    future,owner=record
                    if owner is ws and not future.done():
                        future.set_result(msg)
    except (WebSocketDisconnect,RuntimeError,ValueError) as exc:
        # Log only exception class and a WebSocket close code, not credentials.
        logging.getLogger("uvicorn.error").warning(
            "BRIDGE_DISCONNECT role=%s cause=%s close_code=%s",
            role, type(exc).__name__,
            getattr(exc, "code", None),
        )
    finally:
        heartbeat.cancel()
        async with bridge_lock:
            if peers.get(role,{}).get("ws") is ws:
                peers.pop(role,None)
                cancel_owner(ws)
                await rebalance()

# ----------------------- XINGWANG STOCK MCP -----------------------
# Completely separate from Telegram init_data. Disabled by default.
# No public MCP endpoint exists until XW_STOCK_MCP_ENABLED=1 AND the
# OAuth identity provider, audience and approved subjects are configured.
async def relay_stock_mcp(product_code: str) -> dict:
    async with bridge_lock:
        ws = active_bridge
        role = active_role
        if ws is None or role is None:
            return {"ok": False, "code": "LOCAL_OFFLINE"}
        if len(waiting) >= MAX_INFLIGHT:
            return {"ok": False, "code": "BUSY"}
        req_id = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        waiting[req_id] = (future, ws)
        try:
            # Distinct worker action; existing Telegram action='stock' cannot
            # be called with missing or fabricated Telegram credentials.
            await send_peer(role, {
                "type": "query",
                "id": req_id,
                "source": "chatgpt_oauth",
                "bot": "STOCK",
                "action": "stock_mcp",
                "q": product_code,
            })
        except (RuntimeError, WebSocketDisconnect, OSError):
            waiting.pop(req_id, None)
            return {"ok": False, "code": "LOCAL_OFFLINE"}
    try:
        reply = await asyncio.wait_for(future, timeout=35)
    except asyncio.TimeoutError:
        return {"ok": False, "code": "TIMEOUT"}
    finally:
        waiting.pop(req_id, None)
    if not isinstance(reply, dict):
        return {"ok": False, "code": "INVALID_RESPONSE"}
    if reply.get("ok") is not True:
        return {"ok": False, "code": reply.get("code", "LOCAL_API")}
    return {"ok": True, "data": reply.get("data"), "source": role}


def _render_stock_variant_table(variants: list[dict]) -> str:
    """HTML contains only already-allowlisted product codes and quantities."""
    from html import escape
    def safe(value):
        return escape(str(value if value is not None else "NULL"), quote=True)
    if not variants:
        return "<h2>各商品庫存明細</h2><p>沒有可列出的子商品明細</p>"
    lines = [
        "<h2>各商品編號庫存明細</h2>",
        "<table border='1' cellspacing='0' cellpadding='6'>",
        "<thead><tr><th>商品編號</th><th>庫存匹數</th>"
        "<th>庫存米數</th><th>待到貨箱數</th></tr></thead><tbody>",
    ]
    for row in variants:
        lines.append(
            "<tr>"
            f"<td>{safe(row['code'])}</td>"
            f"<td>{safe(row['stock_rolls'])}</td>"
            f"<td>{safe(row['stock_meters'])}</td>"
            f"<td>{safe(row['incoming_boxes'])}</td>"
            "</tr>"
        )
    lines.append("</tbody></table>")
    lines.append("<p>「NULL」代表資料未提供，不等於 0。負數庫存保留 ERP 原始數字；"
                 "待到貨單位是箱，不換算成匹或米。</p>")
    return "".join(lines)


async def _relay_readonly_stock_with_reconnect_retry(product_code: str) -> dict:
    """Three attempts maximum; retry ONLY a safe, transient bridge handover.

    No retry for NOT_FOUND, LOCAL_API, invalid data, timeout or busy workers.
    7+8s is enough for the safe 14s same-host lease expiry in normal cases.
    Cross-host/cold 32s safety hold is NOT bypassed; it can still return 503.
    These are actual server-side retries; a GPT Cache miss before HTTP arrival
    cannot be retried by Render.
    """
    reply = {"ok": False, "code": "LOCAL_OFFLINE"}
    for attempt, backoff in enumerate((0.0, 7.0, 8.0), start=1):
        if backoff:
            await asyncio.sleep(backoff)
        reply = await relay_stock_mcp(product_code)
        if isinstance(reply, dict):
            reply["bridge_attempts"] = attempt
        if isinstance(reply, dict) and reply.get("ok") is True:
            return reply
        code = reply.get("code") if isinstance(reply, dict) else None
        if code not in ("LOCAL_OFFLINE", "SWITCHING", "STANDBY"):
            return reply
        logging.getLogger("uvicorn.error").info(
            "STOCK_BRIDGE_RETRY product=%r attempt=%s state=%s",
            product_code, attempt, code,
        )
    return reply


# ---------------- Public read-only stock URL ----------------
# Example:
#   /stock?code=1314
#   /stock?code=120-07&format=html
# This endpoint is deliberately token-free so ordinary ChatGPT voice can
# construct and read the URL directly. Keep the response strictly allowlisted.
@app.get("/stock")
async def stock_public(request: Request, code: str = ""):
    from xingwang_miniapp.stock_mcp import CODE_PATTERN, normalize_stock, stock_variant_breakdown

    code = (code or "").strip()
    if not CODE_PATTERN.fullmatch(code):
        raise HTTPException(400, "Invalid product code")

    # Global abuse guard. This is intentionally simple because the endpoint is
    # public; it prevents the public URL from flooding the local Windows bridge.
    async with public_stock_rate_lock:
        now = time.monotonic()
        public_stock_recent_calls[:] = [
            t for t in public_stock_recent_calls if now - t < 60
        ]
        if len(public_stock_recent_calls) >= 30:
            raise HTTPException(429, "Public stock query limit reached")
        public_stock_recent_calls.append(now)

    # Optional client-supplied nonce is echoed for end-to-end freshness checks.
    # It never bypasses rate limits, never changes the stock lookup, and cannot
    # force third-party AI web tools to make a network request.
    nonce = request.query_params.get("nonce", "")
    if nonce and (len(nonce) > 64 or not all(ch.isalnum() or ch in "-_" for ch in nonce)):
        raise HTTPException(400, "Invalid nonce")

    raw = await _relay_readonly_stock_with_reconnect_retry(code)
    normalized = normalize_stock(raw, code)
    served_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    request_id = request.state.stock_trace_id

    noindex_headers = {
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "X-XW-Stock-Nonce": nonce,
        "Access-Control-Allow-Origin": "*",
    }

    if not normalized.get("ok"):
        upstream_code = str(normalized.get("code") or "STOCK_UNAVAILABLE")
        status = 404 if upstream_code == "NOT_FOUND" else 503
        return JSONResponse(
            {
                "ok": False,
                "product_code": code,
                "code": upstream_code,
                "error": "STOCK_UNAVAILABLE",
                "request_id": request_id,
                "nonce": nonce,
                "served_at_utc": served_at_utc,
                "bridge_attempts": raw.get("bridge_attempts", 1),
            },
            status_code=status,
            headers=noindex_headers,
        )

    clean = {
        "ok": True,
        "product_code": code,
        "request_id": request_id,
        "nonce": nonce,
        "served_at_utc": served_at_utc,
        "bridge_attempts": raw.get("bridge_attempts", 1),
        "stock_rolls": normalized["stock_rolls"],
        "stock_meters": normalized["stock_meters"],
        "stock_rolls_missing": normalized.get("stock_rolls_missing", 0),
        "stock_meters_missing": normalized.get("stock_meters_missing", 0),
        "variants": stock_variant_breakdown(normalized),
        "incoming_rolls": normalized.get("incoming_rolls"),
        "incoming_meters": normalized.get("incoming_meters"),
        "incoming_boxes": normalized.get("incoming_boxes"),
        "source": normalized.get("source"),
        "as_of": normalized.get("as_of"),
    }

    if request.query_params.get("format") == "html":
        from html import escape

        def safe(value):
            return escape(
                str(value if value is not None else "未提供"),
                quote=True,
            )

        contents = (
            "<!doctype html><html lang='zh-Hant'><head>"
            "<meta charset='utf-8'>"
            "<meta name='robots' content='noindex,nofollow,noarchive'>"
            f"<title>XINGWANG STOCK {safe(code)}</title></head><body>"
            f"<main><h1>商品系列 {safe(code)}</h1>"
            "<h2>系列合計</h2>"
            f"<p>庫存匹數：<strong>{safe(clean['stock_rolls'])}</strong> 匹</p>"
            f"<p>庫存米數：<strong>{safe(clean['stock_meters'])}</strong> 米</p>"
            f"<p>匹數缺失筆數：{safe(clean['stock_rolls_missing'])}；"
            f"米數缺失筆數：{safe(clean['stock_meters_missing'])}</p>"
            f"<p>待到貨箱數：<strong>{safe(clean['incoming_boxes'])}</strong> 箱</p>"
            f"<p>待到貨匹數：{safe(clean['incoming_rolls'])}</p>"
            f"<p>待到貨米數：{safe(clean['incoming_meters'])}</p>"
            f"<p>資料來源：{safe(clean['source'])}</p>"
            f"<p>查詢時間：{safe(clean['as_of'])}</p>"
            f"<p>本次請求編號：{safe(clean['request_id'])}</p>"
            f"<p>本次驗證參數 nonce：{safe(clean['nonce'])}</p>"
            f"<p>Render 回傳時間 (UTC)：{safe(clean['served_at_utc'])}</p>"
            f"<p>橋接查詢次數：{safe(clean['bridge_attempts'])}</p>"
            + _render_stock_variant_table(clean["variants"])
            + "</main></body></html>"
        )
        return HTMLResponse(contents, headers=noindex_headers)

    return JSONResponse(clean, headers=noindex_headers)


# Path-style alias to give AI web readers and iOS Shortcuts a distinct URL for
# each product. Both public URLs share the same live local bridge, schema,
# rate limit and no-cache policy; no stock data is stored on Render.
# Path changes alone cannot force a third-party web tool to bypass its cache.
@app.get("/stock/{code}")
async def stock_public_by_path(request: Request, code: str):
    return await stock_public(request, code=code)


# ---------------- Temporary REAL STOCK URL pilot ----------------
# GET is needed for ordinary ChatGPT URL-reading experiments.
# Never remove the ticket check; never expose prices or other Flask outputs.
# This is not the long-term username/password login flow.
@app.get("/stock-test")
async def stock_test(request: Request, code: str = "", ticket: str = ""):
    from xingwang_miniapp.stock_mcp import (
        normalize_stock, pilot_access_allowed, pilot_stock_view
    )
    if not pilot_access_allowed(
        code=code,
        ticket=ticket,
        enabled=os.environ.get("XW_STOCK_TEST_ENABLED", ""),
        server_secret=os.environ.get("XW_STOCK_TEST_TICKET", ""),
    ):
        # Do not reveal whether a real stock service is running.
        raise HTTPException(404, "Not Found")

    async with pilot_rate_lock:
        now = time.monotonic()
        pilot_recent_calls[:] = [t for t in pilot_recent_calls if now - t < 60]
        if len(pilot_recent_calls) >= 8:
            raise HTTPException(429, "Temporary test query limit reached")
        pilot_recent_calls.append(now)

    raw = await relay_stock_mcp(code)
    normalized = normalize_stock(raw, code)
    clean = pilot_stock_view(normalized, code)
    # No zero-stock fabrication on upstream failure.
    if not clean.get("ok"):
        return JSONResponse(
            {"ok": False, "test_only": True, "error": "本機庫存暫時無法取得"},
            status_code=503,
            headers={"X-Robots-Tag": "noindex, nofollow, noarchive"},
        )
    noindex_headers = {"X-Robots-Tag": "noindex, nofollow, noarchive"}
    if request.query_params.get("format") == "html":
        # Render only the already-allowlisted stock fields; never forward
        # raw Flask results, pricing, customers, or user-supplied HTML.
        from html import escape
        def safe(value):
            return escape(str(value if value is not None else "未提供"), quote=True)
        contents = (
            "<!doctype html><html lang='zh-Hant'><head>"
            "<meta charset='utf-8'><meta name='robots' content='noindex,nofollow,noarchive'>"
            f"<title>XINGWANG STOCK {safe(code)} 即時庫存</title></head><body>"
            f"<main><h1>XINGWANG STOCK：商品 {safe(code)}</h1>"
            "<p>這是現有 Windows Flask 的即時查詢結果，僅供授權測試；不是模擬資料。</p>"
            f"<p>庫存匹數：<strong>{safe(clean['stock_rolls'])}</strong> 匹</p>"
            f"<p>庫存米數：<strong>{safe(clean['stock_meters'])}</strong> 米</p>"
            f"<p>匹數缺失筆數：{safe(clean['stock_rolls_missing'])}；"
            f"米數缺失筆數：{safe(clean['stock_meters_missing'])}</p>"
            f"<p>待到貨箱數：<strong>{safe(clean['incoming_boxes'])}</strong> 箱</p>"
            f"<p>待到貨匹數：{safe(clean['incoming_rolls'])}；"
            f"待到貨米數：{safe(clean['incoming_meters'])}</p>"
            f"<p>資料來源：{safe(clean['source'])}；查詢時間：{safe(clean['as_of'])}</p>"
            "<p>本頁不提供售價、成本、客戶或訂單資料。</p>"
            "</main></body></html>"
        )
        return HTMLResponse(contents, headers=noindex_headers)
    return JSONResponse(clean, headers=noindex_headers)

# QR scanner is a separate, authenticated interface. Keep it before MCP root mount.
from xingwang_miniapp.scanner_backend import router as scanner_router, attach_stock_lookup
attach_stock_lookup(relay_stock_mcp)
app.include_router(scanner_router)

if os.environ.get("XW_STOCK_MCP_PUBLIC", "") == "1":
    from xingwang_miniapp.stock_mcp import create_public_stock_mcp
    stock_mcp_service, stock_mcp_asgi = create_public_stock_mcp(
        _relay_readonly_stock_with_reconnect_retry
    )
    # Mount LAST so /stock, /api/query, /bridge and the Mini App remain unchanged.
    app.mount("/", stock_mcp_asgi, name="xingwang-stock-mcp")
elif os.environ.get("XW_STOCK_MCP_ENABLED", "") == "1":
    from xingwang_miniapp.stock_mcp import create_stock_mcp
    stock_mcp_service, stock_mcp_asgi = create_stock_mcp(relay_stock_mcp)
    # OAuth-protected mode remains available for a future private deployment.
    app.mount("/", stock_mcp_asgi, name="xingwang-stock-mcp")
