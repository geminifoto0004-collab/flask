# -*- coding: utf-8 -*-
"""Tests for the MCP boundary. No real stock data or credentials required."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from xingwang_miniapp.stock_mcp import (
    RESOURCE_URL,
    OwnerJWTVerifier,
    normalize_stock,
    read_configuration,
    create_stock_mcp,
)

ISSUER = "https://auth.example.com/"
JWKS = "https://auth.example.com/.well-known/jwks.json"


@pytest.fixture()
def valid_environment(monkeypatch):
    monkeypatch.setenv("XW_STOCK_OAUTH_ISSUER", ISSUER)
    monkeypatch.setenv("XW_STOCK_OAUTH_JWKS_URI", JWKS)
    monkeypatch.setenv("XW_STOCK_OAUTH_AUDIENCE", RESOURCE_URL)
    monkeypatch.setenv("XW_STOCK_ALLOWED_SUBJECTS", "approved-user")


def test_auth_config_fails_closed(monkeypatch):
    for key in (
        "XW_STOCK_OAUTH_ISSUER",
        "XW_STOCK_OAUTH_JWKS_URI",
        "XW_STOCK_OAUTH_AUDIENCE",
        "XW_STOCK_ALLOWED_SUBJECTS",
    ):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="missing required environment"):
        read_configuration()


def test_resource_must_be_correct(valid_environment, monkeypatch):
    monkeypatch.setenv("XW_STOCK_OAUTH_AUDIENCE", "https://evil.example/mcp")
    with pytest.raises(RuntimeError, match="canonical"):
        read_configuration()


def test_jwks_cannot_be_arbitrary_host(valid_environment, monkeypatch):
    monkeypatch.setenv("XW_STOCK_OAUTH_JWKS_URI", "https://other.example.com/jwks")
    with pytest.raises(RuntimeError, match="trusted host"):
        read_configuration()


def test_signed_token_requires_owner_audience_and_scope(valid_environment, monkeypatch):
    cfg = read_configuration()
    verifier = OwnerJWTVerifier(cfg)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(verifier._jwks_client, "get_signing_key_from_jwt",
                        lambda _: SimpleNamespace(key=private.public_key()))
    now = datetime.now(tz=timezone.utc)

    def signed(**overrides):
        body = dict(
            iss=ISSUER, aud=RESOURCE_URL, sub="approved-user",
            scope="stock:read", iat=int(now.timestamp()),
            exp=int((now + timedelta(minutes=5)).timestamp())
        )
        body.update(overrides)
        return jwt.encode(body, private, algorithm="RS256")

    valid = asyncio.run(verifier.verify_token(signed()))
    assert valid is not None and valid.subject == "approved-user"
    assert asyncio.run(verifier.verify_token(signed(sub="intruder"))) is None
    assert asyncio.run(verifier.verify_token(signed(scope="orders:read"))) is None
    assert asyncio.run(verifier.verify_token(signed(aud="https://other.example/mcp"))) is None
    assert asyncio.run(verifier.verify_token(signed(exp=int((now-timedelta(hours=1)).timestamp())))) is None
    assert asyncio.run(verifier.verify_token("not-a-jwt")) is None


def test_stock_schema_does_not_guess_units():
    raw = {
        "ok": True,
        "source": "company",
        "data": {
            "product_code": "1314",
            "stock_rolls": 0,
            "stock_meters": 0.0,
            "matches": [],
            "incoming_matches": [],
        },
    }
    out = normalize_stock(raw, "1314")
    assert out["ok"] is True
    assert out["incoming_rolls"] is None
    assert out["incoming_meters"] is None
    assert normalize_stock(raw, "9999")["ok"] is False
    assert normalize_stock({"ok": True, "data": {"product_code":"1314", "stock_rolls": "24","stock_meters": 99}}, "1314")["ok"] is False
    assert normalize_stock({"ok": False, "code": "LOCAL_OFFLINE"}, "1314")["ok"] is False


def test_mcp_registers_exactly_one_read_only_tool(valid_environment):
    async def bridge(code):
        raise AssertionError("No stock call should occur during MCP construction")
    server, app = create_stock_mcp(bridge)
    # Running through the SDK registry is better than inspecting private dicts.
    tools = asyncio.run(server.list_tools())
    assert len(tools) == 1
    assert tools[0].name == "search_stock"
    assert tools[0].annotations.read_only_hint is True
    assert app is not None


def test_http_mcp_rejects_anonymous_requests(valid_environment):
    """SDK-level auth must reject before WebSocket access."""
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    called = []

    async def bridge(code):
        called.append(code)
        raise AssertionError("The worker must never be called without OAuth")

    server, mcp_app = create_stock_mcp(bridge)

    @asynccontextmanager
    async def lifespan(_app):
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/", mcp_app)
    with TestClient(app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {"name": "search_stock", "arguments": {"product_code": "1314"}},
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 401
        assert "WWW-Authenticate" in response.headers
        assert not called
        meta = client.get("/.well-known/oauth-protected-resource/mcp")
        assert meta.status_code == 200
        assert meta.json()["resource"] == RESOURCE_URL
        assert meta.json()["authorization_servers"]


def test_worker_v24_box_units_remain_boxes_only():
    src={
      "ok":True,"source":"company",
      "data":{
        "product_code":"1314","stock_rolls":74,"stock_meters":8553.9,
        "incoming_rolls":None,"incoming_meters":None,"incoming_boxes":46,
        "incoming_boxes_missing":0,"match_mode":"prefix",
        "matches":[
          {"code":"1314-2","stock_rolls":32,"stock_meters":3821.2},
          {"code":"1314-4","stock_rolls":42,"stock_meters":4732.7},
        ],
        "incoming_matches":[{"code":"1314-4","incoming_boxes":46}],
      }
    }
    result=normalize_stock(src,"1314")
    assert result["ok"] is True
    assert result["stock_rolls"] == 74
    assert result["incoming_boxes"] == 46
    assert result["incoming_rolls"] is None and result["incoming_meters"] is None
    assert len(result["matches"]) == 2
    assert "source" in result and result["source"] == "company"
    src["data"]["stock_meters"]=float("nan")
    assert normalize_stock(src,"1314")["code"] == "INVALID_RESPONSE"

def test_worker_errors_are_not_fake_zero():
    for code in ("NOT_FOUND","LOCAL_OFFLINE","TIMEOUT","STANDBY"):
        result=normalize_stock({"ok":False,"code":code},"1314")
        assert result["ok"] is False and result["code"] == code
        assert "stock_rolls" not in result

def test_mcp_oauth_is_declared_on_stock_tool(valid_environment):
    async def relay(code):
        return {"ok":False,"code":"LOCAL_OFFLINE"}
    server,_=create_stock_mcp(relay)
    tools=asyncio.run(server.list_tools())
    assert tools[0].meta["securitySchemes"] == [{"type":"oauth2","scopes":["stock:read"]}]


def test_pilot_access_validates_code_and_revocable_ticket_without_expiry():
    from xingwang_miniapp.stock_mcp import pilot_access_allowed
    secret = "This_is_an_independent_very_long_test_ticket_2026"
    required = dict(
        code="1314", ticket=secret, enabled="1", server_secret=secret,
    )
    assert pilot_access_allowed(**required)
    assert pilot_access_allowed(**{**required, "code": "1314-4"}, )
    assert pilot_access_allowed(**{**required, "code": "120-07"}, )
    assert not pilot_access_allowed(**{**required, "code": "a"}, )
    assert not pilot_access_allowed(**{**required, "code": "120 07"}, )
    assert not pilot_access_allowed(**{**required, "code": "<script>"}, )
    assert not pilot_access_allowed(**{**required, "enabled": "0"}, )
    assert not pilot_access_allowed(**{**required, "ticket": "guess"}, )
    assert not pilot_access_allowed(**{**required, "server_secret": "short"}, )
    assert pilot_access_allowed(**required)  # no 15-minute timeout


def test_pilot_payload_does_not_include_prices_or_customers():
    from xingwang_miniapp.stock_mcp import pilot_stock_view
    normalized = {
        "ok": True, "product_code": "1314", "stock_rolls": 2,
        "stock_meters": 166.5, "incoming_rolls": None,
        "incoming_meters": None, "incoming_boxes": 4,
        "source": "home", "as_of": None,
        "precio": 123, "unit_price": 456, "cost": 789,
        "customer": "CONFIDENTIAL", "matches": [{"price": 999}],
    }
    view = pilot_stock_view(normalized, "1314")
    assert view == {
        "ok": True, "test_only": True, "product_code": "1314",
        "stock_rolls": 2, "stock_meters": 166.5,
        "incoming_rolls": None, "incoming_meters": None, "incoming_boxes": 4,
        "source": "home", "as_of": None,
    }
    assert pilot_stock_view({"ok": False}, "1314")["ok"] is False
    assert pilot_stock_view(normalized, "120-07")["ok"] is False


def test_pilot_real_stock_url_rejects_bad_ticket(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("BRIDGE_SHARED_SECRET", "local_bridge_secret_for_ci_only_123456")
    monkeypatch.delenv("XW_STOCK_TEST_ENABLED", raising=False)
    monkeypatch.delenv("XW_STOCK_TEST_TICKET", raising=False)
    server = importlib.import_module("xingwang_miniapp.miniapp_server")
    with TestClient(server.app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        response = client.get("/stock-test", params={"code": "1314", "ticket": "guess"})
    assert response.status_code == 404


def test_pilot_real_stock_url_returns_only_live_worker_stock(monkeypatch):
    import importlib
    import time
    from fastapi.testclient import TestClient
    ticket = "local_private_single_item_test_ticket_for_ci_2026"
    monkeypatch.setenv("BRIDGE_SHARED_SECRET", "local_bridge_secret_for_ci_only_123456")
    monkeypatch.setenv("XW_STOCK_TEST_ENABLED", "1")
    monkeypatch.setenv("XW_STOCK_TEST_TICKET", ticket)
    server = importlib.import_module("xingwang_miniapp.miniapp_server")
    calls = []

    async def fake_worker(code):
        calls.append(code)
        return {
            "ok": True,
            "source": "home",
            "data": {
                "product_code": code, "stock_rolls": 3, "stock_meters": 291.5,
                "incoming_rolls": None, "incoming_meters": None,
                "incoming_boxes": 2, "matches": [], "incoming_matches": [],
                "price": 111, "customer": "private",
            },
        }

    monkeypatch.setattr(server, "relay_stock_mcp", fake_worker)
    with TestClient(server.app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        wrong = client.get("/stock-test", params={"code": "bad code", "ticket": ticket})
        ok = client.get("/stock-test", params={"code": "120-07", "ticket": ticket})
        assert wrong.status_code == 404
        assert ok.status_code == 200
        assert ok.headers["x-robots-tag"].startswith("noindex")
        data = ok.json()
        assert data["stock_rolls"] == 3 and data["stock_meters"] == 291.5
        assert "price" not in data and "customer" not in data
    assert calls == ["120-07"]


def test_html_pilot_displays_only_allowed_stock_fields(monkeypatch):
    import time
    import importlib
    from fastapi.testclient import TestClient

    ticket = "standalone_html_voice_pilot_ticket_testing_only_2026"
    monkeypatch.setenv("BRIDGE_SHARED_SECRET", "ci_test_bridge_key_only_111111111111111")
    monkeypatch.setenv("XW_STOCK_TEST_ENABLED", "1")
    monkeypatch.setenv("XW_STOCK_TEST_TICKET", ticket)
    server = importlib.import_module("xingwang_miniapp.miniapp_server")
    monkeypatch.setattr(server, "pilot_recent_calls", [])
    requests = []

    async def fake_stock(code):
        requests.append(code)
        return {
            "ok": True, "source": "home",
            "data": {
                "product_code": code,
                "stock_rolls": 72, "stock_meters": 8553.9,
                "incoming_rolls": None, "incoming_meters": None,
                "incoming_boxes": 307,
                "matches": [], "incoming_matches": [],
                "price": "SECRET_PRICE_SENTINEL",
                "customer": "SECRET_CUSTOMER_SENTINEL",
            },
        }

    monkeypatch.setattr(server, "relay_stock_mcp", fake_stock)
    with TestClient(server.app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        fail = client.get("/stock-test", params={"code": "1314", "ticket": "wrong", "format": "html"})
        assert fail.status_code == 404
        html = client.get("/stock-test", params={"code": "120-07", "ticket": ticket, "format": "html"})
        assert html.status_code == 200
        assert html.headers["content-type"].startswith("text/html")
        assert "120-07" in html.text
        assert "72" in html.text and "8553.9" in html.text and "307" in html.text
        assert "SECRET_PRICE_SENTINEL" not in html.text
        assert "SECRET_CUSTOMER_SENTINEL" not in html.text
        assert "noindex" in html.headers["x-robots-tag"]
        plain = client.get("/stock-test", params={"code": "120-07", "ticket": ticket})
        assert plain.status_code == 200 and plain.json()["stock_rolls"] == 72
    assert requests == ["120-07", "120-07"]
