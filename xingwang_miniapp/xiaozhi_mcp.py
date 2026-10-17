"""Xiaozhi MCP outbound client inside the existing Render stock service.

Disabled by default. No new service, process, public API or Windows worker.
Only uses the read-only V33 bridge in this same FastAPI process.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
from urllib.parse import urlsplit, parse_qs

LOG = logging.getLogger("uvicorn.error")  # Render-visible info; never log MCP credentials
TOOL_NAME = "search_stock"
TOOL = {
    "name": TOOL_NAME,
    "description": (
        "查询 XINGWANG 商品系列即时库存、匹数、米数、待到货箱数。"
        "商品编号必须原样传入，例如 1314、1268A、120-07、158-217-；保留末尾连字符。"
        "仅报告真实查询值，NULL 不代表零，查询失败绝对不可猜数字。"
        "Look up real read-only stock using the exact original product code."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"code": {
            "type": "string",
            "description": "Literal product or series code, preserve the final hyphen if any",
        }},
        "required": ["code"],
        "additionalProperties": False,
    },
}


def valid_endpoint(endpoint: str) -> bool:
    """Require a private official Xiaozhi WSS URL, never print it."""
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        return False
    try:
        u = urlsplit(endpoint)
        tokens = parse_qs(u.query, keep_blank_values=True).get("token", [])
        return (u.scheme == "wss" and u.hostname is not None
                and (u.hostname == "xiaozhi.me" or u.hostname.endswith(".xiaozhi.me"))
                and u.username is None and u.password is None
                and len(tokens) == 1 and len(tokens[0]) >= 8 and not u.fragment)
    except ValueError:
        return False


def _ok(req_id, data):
    return {"jsonrpc": "2.0", "id": req_id, "result": data}


def _error(req_id, code: int, message: str):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def compact_stock(normalized: dict, code: str) -> dict:
    """Quantity-only result under Xiaozhi voice device message limits."""
    if not isinstance(normalized, dict) or normalized.get("ok") is not True:
        err = normalized.get("code", "STOCK_UNAVAILABLE") if isinstance(normalized, dict) else "STOCK_UNAVAILABLE"
        return {"ok": False, "code": code, "error_code": str(err),
                "message": "库存暂时无法取得，请稍后重试"}
    fields = ("stock_rolls", "stock_meters", "stock_rolls_missing", "stock_meters_missing",
              "incoming_boxes", "incoming_rolls", "incoming_meters", "as_of")
    result = {"ok": True, "code": code}
    for field in fields:
        result[field] = normalized.get(field)
    from xingwang_miniapp.stock_mcp import stock_variant_breakdown
    rows = stock_variant_breakdown(normalized)
    result["variant_count"] = len(rows)
    result["variants"] = []
    for row in rows[:8]:
        item = {k: row.get(k) for k in ("code", "stock_rolls", "stock_meters", "incoming_boxes")}
        candidate = {**result, "variants": [*result["variants"], item]}
        if len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 950:
            break
        result["variants"].append(item)
    if len(rows) > len(result["variants"]):
        result["more_variants"] = len(rows) - len(result["variants"])
    return result


async def stock_lookup(code: str) -> dict:
    """Call the real local worker through the existing authenticated WS bridge."""
    from xingwang_miniapp.miniapp_server import relay_stock_mcp
    from xingwang_miniapp.stock_mcp import CODE_PATTERN, normalize_stock
    if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
        return {"ok": False, "error_code": "INVALID_CODE", "message": "商品编号格式无效"}
    try:
        raw = await asyncio.wait_for(relay_stock_mcp(code), timeout=25)
    except asyncio.TimeoutError:
        return {"ok": False, "error_code": "TIMEOUT", "message": "库存查询超时，请重试"}
    except Exception:
        LOG.exception("Stock relay error")
        return {"ok": False, "error_code": "LOCAL_API", "message": "库存暂不可用"}
    return compact_stock(normalize_stock(raw, code), code)


async def handle_message(msg: object, lookup=stock_lookup) -> dict | None:
    """One Xiaozhi MCP JSON-RPC request or notification."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid request")
    if "id" not in msg:
        return None
    req_id = msg["id"]
    if isinstance(req_id, (dict, list, bool)):
        return _error(None, -32600, "Invalid request id")
    method = msg.get("method")
    if method == "initialize":
        params = msg.get("params") or {}
        version = params.get("protocolVersion") if isinstance(params, dict) else None
        if version not in ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"):
            version = "2024-11-05"
        return _ok(req_id, {
            "protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "XINGWANG Stock Read-only", "version": "1.0.0"},
        })
    if method == "ping":
        return _ok(req_id, {})
    if method == "tools/list":
        return _ok(req_id, {"tools": [TOOL]})
    if method == "tools/call":
        params = msg.get("params")
        if not isinstance(params, dict) or params.get("name") != TOOL_NAME:
            return _error(req_id, -32602, "Unknown tool")
        args = params.get("arguments")
        if not isinstance(args, dict) or set(args) != {"code"}:
            return _error(req_id, -32602, "Invalid arguments")
        try:
            data = await lookup(args["code"])
        except Exception:
            LOG.exception("Xiaozhi tool read failed")
            data = {"ok": False, "error_code": "LOCAL_API", "message": "库存暂不可用"}
        value = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return _ok(req_id, {"content": [{"type": "text", "text": value}],
                            "isError": data.get("ok") is not True})
    return _error(req_id, -32601, "Method not found")


async def session(ws, lookup=stock_lookup):
    """Keep MCP pings responsive even while stock requests are running."""
    write_lock = asyncio.Lock()
    sem = asyncio.Semaphore(2)
    pending: set[asyncio.Task] = set()

    async def answer(msg):
        async with sem:
            response = await handle_message(msg, lookup)
        if response is not None:
            async with write_lock:
                await ws.send(json.dumps(response, ensure_ascii=False, separators=(",", ":")))

    try:
        async for frame in ws:
            if isinstance(frame, bytes):
                try:
                    frame = frame.decode("utf-8")
                except UnicodeDecodeError:
                    continue
            if not isinstance(frame, str) or len(frame) > 16384:
                continue
            try:
                msg = json.loads(frame)
            except (ValueError, TypeError):
                continue
            if isinstance(msg, dict) and msg.get("method") == "tools/call":
                if len(pending) >= 4:
                    async with write_lock:
                        await ws.send(json.dumps(_error(msg.get("id"), -32000, "Busy")))
                    continue
                t = asyncio.create_task(answer(msg))
                pending.add(t)
                t.add_done_callback(pending.discard)
            else:
                await answer(msg)
    finally:
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def run_forever():
    endpoint = os.getenv("XW_XIAOZHI_MCP_ENDPOINT", "").strip()
    if not valid_endpoint(endpoint):
        LOG.error("Xiaozhi enabled but endpoint missing/invalid (credential not logged)")
        return
    import websockets
    backoff = 3
    while True:
        try:
            LOG.info("Connecting to Xiaozhi MCP (token hidden)")
            async with websockets.connect(
                endpoint, open_timeout=18, close_timeout=8,
                ping_interval=25, ping_timeout=30, max_size=1024 * 1024
            ) as ws:
                LOG.info("Xiaozhi MCP connected")
                backoff = 3
                await session(ws)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("Xiaozhi disconnected (%s); retry in %ss",
                        type(exc).__name__, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
