# -*- coding: utf-8 -*-
"""OAuth-protected, read-only MCP entrypoint for XINGWANG stock.

Enabled ONLY with XW_STOCK_MCP_ENABLED=1 and complete identity-provider
configuration. This module never handles Telegram initData and never creates
an unauthenticated alternate stock endpoint.
"""
from __future__ import annotations

import asyncio
import os
import re
import math
from typing import Annotated, Awaitable, Callable
from urllib.parse import urlsplit

import jwt
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field

RESOURCE_URL = "https://xingwang-stock-miniapp.onrender.com/mcp"
READ_SCOPE = "stock:read"
CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{1,39}$")


def read_configuration() -> dict:
    """Fail closed: no issuer, key set, audience or owner allowlist = no MCP."""
    required = (
        "XW_STOCK_OAUTH_ISSUER",
        "XW_STOCK_OAUTH_JWKS_URI",
        "XW_STOCK_OAUTH_AUDIENCE",
        "XW_STOCK_ALLOWED_SUBJECTS",
    )
    values = {key: os.environ.get(key, "").strip() for key in required}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError("XINGWANG STOCK MCP missing required environment: " + ", ".join(missing))

    issuer = values["XW_STOCK_OAUTH_ISSUER"]  # Preserve exact issuer: Auth0 normally ends in "/"
    jwks_url = values["XW_STOCK_OAUTH_JWKS_URI"]
    if (
        urlsplit(issuer).scheme != "https"
        or urlsplit(jwks_url).scheme != "https"
        or urlsplit(issuer).netloc != urlsplit(jwks_url).netloc
        or not urlsplit(jwks_url).path
        or urlsplit(issuer).username is not None
        or urlsplit(jwks_url).username is not None
    ):
        raise RuntimeError("OAuth issuer and JWKS must use HTTPS and the same trusted host")

    # Resource Indicator MUST match the MCP endpoint, not the Telegram API.
    if values["XW_STOCK_OAUTH_AUDIENCE"] != RESOURCE_URL:
        raise RuntimeError("XW_STOCK_OAUTH_AUDIENCE must equal the canonical /mcp resource URL")

    allowed = frozenset(x.strip() for x in values["XW_STOCK_ALLOWED_SUBJECTS"].split(",") if x.strip())
    if not allowed:
        raise RuntimeError("XW_STOCK_ALLOWED_SUBJECTS cannot be empty")
    return {"issuer": issuer, "jwks_uri": jwks_url, "audience": RESOURCE_URL, "allowed": allowed}


class OwnerJWTVerifier(TokenVerifier):
    """Verify signature, issuer, aud, expiry, stock scope and owner identity."""

    def __init__(self, config: dict):
        self._config = config
        self._jwks_client = PyJWKClient(config["jwks_uri"], cache_jwk_set=True, lifespan=300)

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or len(token) > 8192:
            return None
        try:
            key = await asyncio.to_thread(self._jwks_client.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self._config["issuer"],
                audience=self._config["audience"],
                options={"require": ["iss", "aud", "exp", "iat", "sub"]},
                leeway=30,
            )
        except (InvalidTokenError, PyJWKClientError, ValueError, OSError):
            return None

        subject = claims.get("sub")
        if not isinstance(subject, str) or subject not in self._config["allowed"]:
            return None
        raw_scopes = claims.get("scope", "")
        scopes = raw_scopes.split() if isinstance(raw_scopes, str) else []
        if READ_SCOPE not in scopes:
            return None
        client_id = claims.get("azp") or claims.get("client_id") or subject
        if not isinstance(client_id, str):
            return None
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(claims["exp"]),
            resource=RESOURCE_URL,
            subject=subject,
        )


def normalize_stock(raw: dict, product_code: str) -> dict:
    """Do not invent quantities or assume that incoming uses a particular unit."""
    if not isinstance(raw, dict) or raw.get("ok") is not True:
        code = raw.get("code") if isinstance(raw, dict) else None
        code = code if code in ("NOT_FOUND", "LOCAL_OFFLINE", "TIMEOUT", "BUSY", "STANDBY", "LOCAL_API", "INTERNAL") else "LOCAL_API"
        return {"ok": False, "code": code, "error": "本機查詢未成功"}
    data = raw.get("data")
    if not isinstance(data, dict):
        return {"ok": False, "code": "INVALID_RESPONSE", "error": "本機尚未回傳規範化庫存資料"}
    if data.get("product_code") != product_code:
        return {"ok": False, "code": "INVALID_RESPONSE", "error": "回傳商品編號不一致"}
    # V30 may report an unknown aggregate when one or more underlying SKU
    # rows do not have that unit. Never silently convert a missing count to 0,
    # and never accept a partial numeric aggregate as a complete total.
    stock_rows = data.get("matches")
    missing = {}
    for field in ("stock_rolls", "stock_meters"):
        missing_field = field + "_missing"
        absent = data.get(missing_field, 0)
        if (type(absent) is not int or absent < 0 or
                not isinstance(stock_rows, list) or absent > len(stock_rows)):
            return {"ok": False, "code": "INVALID_RESPONSE", "error": "庫存缺失數量格式不正確"}
        value = data.get(field)
        if value is None:
            if absent == 0:
                return {"ok": False, "code": "INVALID_RESPONSE", "error": "回傳庫存格式不正確"}
        elif (absent > 0 or isinstance(value, bool) or
              not isinstance(value, (int, float)) or
              not math.isfinite(value) or value < 0):
            return {"ok": False, "code": "INVALID_RESPONSE", "error": "回傳庫存格式不正確"}
        missing[field] = absent
    for field in ("incoming_rolls", "incoming_meters"):
        value = data.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            return {"ok": False, "code": "INVALID_RESPONSE", "error": "待到貨單位格式不正確"}
    boxes = data.get("incoming_boxes")
    if boxes is not None and (
        isinstance(boxes, bool) or not isinstance(boxes, (int, float)) or
        not math.isfinite(boxes) or boxes < 0
    ):
        return {"ok": False, "code": "INVALID_RESPONSE", "error": "待到貨箱數格式不正確"}
    matches = data.get("matches")
    incoming_matches = data.get("incoming_matches")
    if not isinstance(matches, list) or not isinstance(incoming_matches, list) or len(matches) > 200 or len(incoming_matches) > 200:
        return {"ok": False, "code": "INVALID_RESPONSE", "error": "庫存明細格式不正確"}
    def safe_rows(rows, fields):
        out=[]
        for item in rows:
            if not isinstance(item, dict) or not isinstance(item.get("code"), str) or not CODE_PATTERN.fullmatch(item["code"]):
                return None
            row={"code":item["code"]}
            for field in fields:
                n=item.get(field)
                if n is not None and (isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<0):
                    return None
                row[field]=n
            out.append(row)
        return out
    safe_stock=safe_rows(matches, ("stock_rolls", "stock_meters"))
    safe_incoming=safe_rows(incoming_matches, ("incoming_boxes",))
    if safe_stock is None or safe_incoming is None:
        return {"ok": False, "code": "INVALID_RESPONSE", "error": "庫存明細單位不正確"}
    for field in ("stock_rolls", "stock_meters"):
        if safe_stock:
            actual_missing = sum(item[field] is None for item in safe_stock)
            if missing[field] != actual_missing:
                return {"ok": False, "code": "INVALID_RESPONSE", "error": "庫存缺失數量與明細不一致"}
    return {
        "ok": True,
        "product_code": product_code,
        "stock_rolls": data["stock_rolls"],
        "stock_meters": data["stock_meters"],
        "stock_rolls_missing": missing["stock_rolls"],
        "stock_meters_missing": missing["stock_meters"],
        "incoming_rolls": data.get("incoming_rolls"),
        "incoming_meters": data.get("incoming_meters"),
        "incoming_boxes": boxes,
        "incoming_boxes_missing": data.get("incoming_boxes_missing"),
        "matches": safe_stock,
        "incoming_matches": safe_incoming,
        "match_mode": data.get("match_mode") if data.get("match_mode") in ("exact", "prefix") else None,
        "as_of": data.get("as_of") if isinstance(data.get("as_of"), str) else None,
        "source": raw.get("source") if raw.get("source") in ("company", "home") else None,
    }




# Temporary browser/ChatGPT voice URL pilot for arbitrary stock codes.
# The URL is a revocable bearer capability with NO time-based expiry.
# Authorization still requires a separate long secret and is OFF by default;
# never accept Telegram credentials or Auth0 passwords as GET parameters.
PILOT_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def pilot_access_allowed(
    *,
    code: str,
    ticket: str,
    enabled: str,
    server_secret: str,
) -> bool:
    """Require valid product syntax and a revocable long secret, without expiry."""
    import hmac

    if enabled != "1" or not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
        return False
    if not isinstance(server_secret, str) or not PILOT_SECRET_PATTERN.fullmatch(server_secret):
        return False
    if not isinstance(ticket, str) or len(ticket) != len(server_secret):
        return False
    return hmac.compare_digest(ticket, server_secret)


def pilot_stock_view(normalized: dict, requested_code: str) -> dict:
    """Never expose raw worker data: no prices, customers, history or notes."""
    if not isinstance(normalized, dict) or normalized.get("ok") is not True:
        return {"ok": False, "error": "庫存暫時無法取得"}
    if not CODE_PATTERN.fullmatch(requested_code) or normalized.get("product_code") != requested_code:
        return {"ok": False, "error": "商品編號不一致"}
    return {
        "ok": True,
        "test_only": True,
        "product_code": requested_code,
        "stock_rolls": normalized["stock_rolls"],
        "stock_meters": normalized["stock_meters"],
        "stock_rolls_missing": normalized.get("stock_rolls_missing", 0),
        "stock_meters_missing": normalized.get("stock_meters_missing", 0),
        "incoming_rolls": normalized.get("incoming_rolls"),
        "incoming_meters": normalized.get("incoming_meters"),
        "incoming_boxes": normalized.get("incoming_boxes"),
        "source": normalized.get("source"),
        "as_of": normalized.get("as_of"),
    }


def create_stock_mcp(
    bridge_query: Callable[[str], Awaitable[dict]],
):
    """Return (SDK server, ASGI app); parent FastAPI owns server lifespan."""
    config = read_configuration()
    server = MCPServer(
        "XINGWANG STOCK",
        token_verifier=OwnerJWTVerifier(config),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(config["issuer"]),
            resource_server_url=AnyHttpUrl(RESOURCE_URL),
            required_scopes=[READ_SCOPE],
            validate_token_resource=True,
        ),
    )

    @server.tool(
        title="查詢 XINGWANG 商品即時庫存",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False),
        meta={"securitySchemes": [{"type": "oauth2", "scopes": [READ_SCOPE]}]},
    )
    async def search_stock(
        product_code: Annotated[str, Field(min_length=2, max_length=40, description="商品編號，例如 1314")],
    ) -> dict:
        """唯讀查詢公司 Flask 的商品庫存匹數、米數及待到貨，不查客人、不改資料。"""
        access = get_access_token()
        if access is None or READ_SCOPE not in access.scopes or access.subject not in config["allowed"]:
            return {"ok": False, "code": "UNAUTHORIZED", "error": "無權查詢"}
        if not CODE_PATTERN.fullmatch(product_code):
            return {"ok": False, "code": "INPUT", "error": "商品編號格式不正確"}
        response = await bridge_query(product_code)
        return normalize_stock(response, product_code)

    # The SDK supplies standard Streamable HTTP and OAuth resource discovery.
    from mcp.server.transport_security import TransportSecuritySettings
    security = TransportSecuritySettings(
        allowed_hosts=["xingwang-stock-miniapp.onrender.com"],
        allowed_origins=["https://chatgpt.com"],
    )
    return server, server.streamable_http_app(transport_security=security)
