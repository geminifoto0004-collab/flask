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
from datetime import datetime, timezone
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

    issuer = values["XW_STOCK_OAUTH_ISSUER"].rstrip("/")
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
        return {"ok": False, "code": "LOCAL_API", "error": "本機查詢未成功"}
    data = raw.get("data")
    if not isinstance(data, dict):
        return {"ok": False, "code": "INVALID_RESPONSE", "error": "本機尚未回傳規範化庫存資料"}
    if data.get("product_code") != product_code:
        return {"ok": False, "code": "INVALID_RESPONSE", "error": "回傳商品編號不一致"}
    # The worker must explicitly supply rolls/meters with their true units.
    for field in ("stock_rolls", "stock_meters"):
        value = data.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return {"ok": False, "code": "INVALID_RESPONSE", "error": "回傳庫存格式不正確"}
    for field in ("incoming_rolls", "incoming_meters"):
        value = data.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
            return {"ok": False, "code": "INVALID_RESPONSE", "error": "待到貨單位格式不正確"}
    return {
        "ok": True,
        "product_code": product_code,
        "stock_rolls": data["stock_rolls"],
        "stock_meters": data["stock_meters"],
        "incoming_rolls": data.get("incoming_rolls"),
        "incoming_meters": data.get("incoming_meters"),
        "as_of": data.get("as_of") if isinstance(data.get("as_of"), str) else None,
        "source": raw.get("source") if raw.get("source") in ("company", "home") else None,
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
