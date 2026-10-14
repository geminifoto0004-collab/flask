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
        "stock_rolls_missing": 0, "stock_meters_missing": 0,
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


def test_nullable_stock_quantity_requires_confirmed_missing_rows():
    from xingwang_miniapp.stock_mcp import normalize_stock
    raw = {
        "ok": True, "source": "company",
        "data": {
            "product_code": "120-07",
            "stock_rolls": None, "stock_meters": 372.5,
            "stock_rolls_missing": 1, "stock_meters_missing": 0,
            "incoming_rolls": None, "incoming_meters": None,
            "incoming_boxes": 8, "matches": [
                {"code": "120-07", "stock_rolls": None, "stock_meters": 372.5}
            ], "incoming_matches": [],
            "customer": "NEVER_LEAK", "price": 999,
        },
    }
    result = normalize_stock(raw, "120-07")
    assert result["ok"] is True
    assert result["stock_rolls"] is None and result["stock_rolls_missing"] == 1
    assert result["stock_meters"] == 372.5 and result["stock_meters_missing"] == 0
    assert "customer" not in str(result) and "price" not in str(result)
    wrong = {
        **raw, "data": {**raw["data"], "stock_rolls": 0}
    }
    assert normalize_stock(wrong, "120-07")["ok"] is False
    wrong = {
        **raw, "data": {**raw["data"], "stock_rolls_missing": 0}
    }
    assert normalize_stock(wrong, "120-07")["ok"] is False


def test_partial_stock_html_and_json_show_unknown_not_zero(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("BRIDGE_SHARED_SECRET", "ci_only_bridge_secret_1234567890123")
    server = importlib.import_module("xingwang_miniapp.miniapp_server")

    async def fake_local(code):
        return {
            "ok": True, "source": "company",
            "data": {
                "product_code": code,
                "stock_rolls": None, "stock_meters": 372.5,
                "stock_rolls_missing": 1, "stock_meters_missing": 0,
                "incoming_rolls": None, "incoming_meters": None,
                "incoming_boxes": 8,
                "matches": [{"code": code, "stock_rolls": None, "stock_meters": 372.5}],
                "incoming_matches": [],
                "price": "SECRET_PRICE_NEVER_SEND",
                "customer": "SECRET_CUSTOMER_NEVER_SEND",
            },
        }

    monkeypatch.setattr(server, "relay_stock_mcp", fake_local)
    with TestClient(server.app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        response = client.get("/stock", params={"code": "120-07"})
        assert response.status_code == 200
        data = response.json()
        assert data["stock_rolls"] is None
        assert data["stock_rolls_missing"] == 1
        assert data["stock_meters"] == 372.5
        assert "SECRET_PRICE_NEVER_SEND" not in response.text
        assert "SECRET_CUSTOMER_NEVER_SEND" not in response.text
        page = client.get("/stock", params={"code": "120-07", "format": "html"})
        assert page.status_code == 200
        assert "未提供" in page.text
        assert "匹數缺失筆數：1" in page.text
        assert "SECRET_PRICE_NEVER_SEND" not in page.text


def test_v31_negative_inventory_is_valid_but_never_leaks_prices():
    raw = {
        "ok": True, "source": "company",
        "data": {
            "product_code": "120-07",
            "stock_rolls": -3, "stock_meters": -10.5,
            "stock_rolls_missing": 0, "stock_meters_missing": 0,
            "incoming_rolls": None, "incoming_meters": None,
            "incoming_boxes": 8,
            "matches": [{"code": "120-07", "stock_rolls": -3, "stock_meters": -10.5}],
            "incoming_matches": [],
            "price": "NEVER_EXPOSE_PRICE", "customer": "NEVER_EXPOSE_CUSTOMER",
        },
    }
    got = normalize_stock(raw, "120-07")
    assert got["ok"] is True
    assert got["stock_rolls"] == -3
    assert got["stock_meters"] == -10.5
    assert got["matches"][0]["stock_rolls"] == -3
    assert "NEVER_EXPOSE_PRICE" not in str(got)
    assert "NEVER_EXPOSE_CUSTOMER" not in str(got)
    # V32 accepts true signed incoming ERP boxes as well as signed stock.
    signed = {**raw, "data": {**raw["data"], "incoming_boxes": -8}}
    assert normalize_stock(signed, "120-07")["incoming_boxes"] == -8
    invalid = {**raw, "data": {**raw["data"], "stock_rolls": float("nan")}}
    assert normalize_stock(invalid, "120-07")["ok"] is False
    invalid = {**raw, "data": {**raw["data"], "stock_meters_missing": 1}}
    assert normalize_stock(invalid, "120-07")["ok"] is False


def test_v31_negative_inventory_public_html_and_json(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BRIDGE_SHARED_SECRET", "ci_only_bridge_secret_1234567890123")
    server = importlib.import_module("xingwang_miniapp.miniapp_server")

    async def fake_worker(code):
        return {
            "ok": True, "source": "company",
            "data": {
                "product_code": code,
                "stock_rolls": -5, "stock_meters": -123.5,
                "stock_rolls_missing": 0, "stock_meters_missing": 0,
                "incoming_rolls": None, "incoming_meters": None,
                "incoming_boxes": 2,
                "matches": [{"code": code, "stock_rolls": -5, "stock_meters": -123.5}],
                "incoming_matches": [],
                "price": "DONT_EXPOSE_PRICE",
                "customer": "DONT_EXPOSE_CUSTOMER",
            },
        }

    monkeypatch.setattr(server, "relay_stock_mcp", fake_worker)
    with TestClient(server.app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        response = client.get("/stock", params={"code": "120-07"})
        assert response.status_code == 200
        data = response.json()
        assert data["stock_rolls"] == -5
        assert data["stock_meters"] == -123.5
        assert "DONT_EXPOSE_PRICE" not in response.text
        assert "DONT_EXPOSE_CUSTOMER" not in response.text
        page = client.get("/stock", params={"code": "120-07", "format": "html"})
        assert page.status_code == 200
        assert ">-5</strong>" in page.text
        assert ">-123.5</strong>" in page.text
        assert "DONT_EXPOSE_PRICE" not in page.text


def test_v31_per_sku_totals_and_incoming_are_kept_separate():
    from xingwang_miniapp.stock_mcp import stock_variant_breakdown
    normalized = {
        "ok": True,
        "matches": [
            {"code": "120-07-10", "stock_rolls": 4, "stock_meters": 220.0},
            {"code": "120-07-2", "stock_rolls": 2, "stock_meters": 101.5},
            {"code": "120-07-2", "stock_rolls": -1, "stock_meters": -10.0},
            {"code": "120-07-3", "stock_rolls": None, "stock_meters": 30.0},
            {"code": "120-07-3", "stock_rolls": 8, "stock_meters": None},
        ],
        "incoming_matches": [
            {"code": "120-07-2", "incoming_boxes": 12},
            {"code": "120-07-2", "incoming_boxes": 5},
            {"code": "120-07-4", "incoming_boxes": 6},
            {"code": "120-07-3", "incoming_boxes": None},
        ],
        "customer": "PRIVATE", "price": 125,
    }
    rows = stock_variant_breakdown(normalized)
    assert [row["code"] for row in rows] == [
        "120-07-2", "120-07-3", "120-07-4", "120-07-10"
    ]
    assert rows[0]["stock_rolls"] == 1
    assert rows[0]["stock_meters"] == 91.5
    assert rows[0]["incoming_boxes"] == 17
    assert rows[1]["stock_rolls"] is None
    assert rows[1]["stock_meters"] is None
    assert rows[1]["incoming_boxes"] is None
    assert rows[1]["stock_rolls_missing"] == 1
    assert rows[1]["stock_meters_missing"] == 1
    assert rows[2]["stock_rolls"] is None
    assert rows[2]["incoming_boxes"] == 6
    assert rows[3]["incoming_boxes"] is None
    assert "PRIVATE" not in str(rows) and "125" not in str(rows)


def test_v31_per_sku_public_json_and_html_match_no_pricing(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("BRIDGE_SHARED_SECRET", "ci_only_bridge_secret_1234567890123")
    server = importlib.import_module("xingwang_miniapp.miniapp_server")

    async def fake_worker(code):
        return {
            "ok": True, "source": "home",
            "data": {
                "product_code": code,
                "stock_rolls": 7, "stock_meters": 410.5,
                "stock_rolls_missing": 0, "stock_meters_missing": 0,
                "incoming_rolls": None, "incoming_meters": None,
                "incoming_boxes": 15,
                "matches": [
                    {"code": "120-07-2", "stock_rolls": 5, "stock_meters": 300.0},
                    {"code": "120-07-10", "stock_rolls": 2, "stock_meters": 110.5},
                ],
                "incoming_matches": [
                    {"code": "120-07-2", "incoming_boxes": 10},
                    {"code": "120-07-11", "incoming_boxes": 5},
                ],
                "price": "SENSITIVE_PRICE_TOKEN",
                "customer": "SENSITIVE_CUSTOMER_TOKEN",
            },
        }

    monkeypatch.setattr(server, "relay_stock_mcp", fake_worker)
    with TestClient(server.app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        response = client.get("/stock", params={"code": "120-07"})
        assert response.status_code == 200
        result = response.json()
        assert result["stock_rolls"] == 7
        assert result["stock_meters"] == 410.5
        assert result["incoming_boxes"] == 15
        assert [row["code"] for row in result["variants"]] == [
            "120-07-2", "120-07-10", "120-07-11"
        ]
        assert result["variants"][0]["stock_rolls"] == 5
        assert result["variants"][0]["incoming_boxes"] == 10
        assert result["variants"][2]["stock_rolls"] is None
        assert "SENSITIVE_PRICE_TOKEN" not in response.text
        assert "SENSITIVE_CUSTOMER_TOKEN" not in response.text
        page = client.get("/stock", params={"code": "120-07", "format": "html"})
        assert page.status_code == 200
        assert "系列合計" in page.text and "各商品編號庫存明細" in page.text
        assert "120-07-2" in page.text and "120-07-11" in page.text
        assert "410.5" in page.text and "未提供" in page.text
        assert "SENSITIVE_PRICE_TOKEN" not in page.text
        assert "SENSITIVE_CUSTOMER_TOKEN" not in page.text


def test_v32_literal_prefix_allows_13140_and_1268a_1_variants():
    from xingwang_miniapp.stock_mcp import normalize_stock, stock_variant_breakdown
    raw = {
        "ok": True, "source": "home",
        "data": {
            "product_code": "1314", "stock_rolls": 1, "stock_meters": 35.5,
            "incoming_boxes": -4, "incoming_rolls": None, "incoming_meters": None,
            "matches": [
                {"code": "1314-2", "stock_rolls": 4, "stock_meters": 40.5},
                {"code": "13140-3", "stock_rolls": -3, "stock_meters": -5},
            ],
            "incoming_matches": [
                {"code": "13140-3", "incoming_boxes": -4},
            ],
            "price": "PRIVATE_NUMBER_SHOULD_NOT_LEAK",
        },
    }
    data = normalize_stock(raw, "1314")
    assert data["ok"] is True and data["stock_rolls"] == 1
    assert data["incoming_boxes"] == -4
    assert [x["code"] for x in stock_variant_breakdown(data)] == ["1314-2", "13140-3"]
    assert "PRIVATE_NUMBER_SHOULD_NOT_LEAK" not in str(data)

    # A raw worker must NOT attach an unrelated SKU to a valid prefix query.
    changed = {**raw, "data": {
        **raw["data"],
        "matches": [*raw["data"]["matches"], {"code":"1315-1", "stock_rolls":1, "stock_meters":2}],
    }}
    assert normalize_stock(changed, "1314")["ok"] is False

    raw2 = {**raw, "data": {
        **raw["data"], "product_code": "1268A-1",
        "matches": [
            {"code": "1268A-1(2)", "stock_rolls": 1, "stock_meters": -1},
            {"code": "1268A-10", "stock_rolls": 0, "stock_meters": 4},
        ],
        "stock_rolls": 1, "stock_meters": 3, "incoming_matches": [], "incoming_boxes": None,
    }}
    got = normalize_stock(raw2, "1268A-1")
    assert got["ok"] is True
    assert {r["code"] for r in stock_variant_breakdown(got)} == {"1268A-1(2)", "1268A-10"}


def test_v32_null_signed_zero_are_shown_not_filtered():
    from xingwang_miniapp.stock_mcp import normalize_stock, stock_variant_breakdown
    raw = {"ok": True, "source": "home", "data": {
        "product_code": "1314", "stock_rolls": None, "stock_meters": -8,
        "stock_rolls_missing": 1, "stock_meters_missing": 0,
        "incoming_boxes": None, "incoming_rolls": None, "incoming_meters": None,
        "matches": [
            {"code": "1314-NULL", "stock_rolls": None, "stock_meters": -10},
            {"code": "1314-ZERO", "stock_rolls": 0, "stock_meters": 0},
            {"code": "1314-NEG", "stock_rolls": -4, "stock_meters": 2},
        ],
        "incoming_matches": [
            {"code": "1314-NULL", "incoming_boxes": None},
            {"code": "1314-ZERO", "incoming_boxes": 0},
            {"code": "1314-NEG", "incoming_boxes": -2},
        ],
        "incoming_boxes_missing": 1,
    }}
    result = normalize_stock(raw, "1314")
    assert result["ok"] is True
    rows = {r["code"]: r for r in stock_variant_breakdown(result)}
    assert rows["1314-NULL"]["stock_rolls"] is None
    assert rows["1314-NULL"]["incoming_boxes"] is None
    assert rows["1314-NEG"]["stock_rolls"] == -4
    assert rows["1314-NEG"]["incoming_boxes"] == -2
    assert rows["1314-ZERO"]["stock_rolls"] == 0
    assert rows["1314-ZERO"]["incoming_boxes"] == 0


def test_v32_more_than_200_stock_rows_are_not_discarded():
    from xingwang_miniapp.stock_mcp import normalize_stock, stock_variant_breakdown
    rows = [
        {"code": f"1314-{i}", "stock_rolls": 1, "stock_meters": 30}
        for i in range(250)
    ]
    data = {
        "ok": True, "source": "company",
        "data": {
            "product_code": "1314", "stock_rolls": 250, "stock_meters": 7500,
            "incoming_rolls": None, "incoming_meters": None, "incoming_boxes": None,
            "matches": rows, "incoming_matches": [],
        },
    }
    result = normalize_stock(data, "1314")
    assert result["ok"] is True
    details = stock_variant_breakdown(result)
    assert len(details) == 250
    assert details[0]["code"] == "1314-0"
    assert details[-1]["code"] == "1314-249"


def test_v32_null_cells_render_as_null_text_in_stock_html(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("BRIDGE_SHARED_SECRET", "ci_only_bridge_secret_1234567890123")
    server = importlib.import_module("xingwang_miniapp.miniapp_server")

    async def fake_worker(code):
        return {"ok": True, "source": "home", "data": {
            "product_code": code,
            "stock_rolls": None, "stock_meters": -3,
            "stock_rolls_missing": 1, "stock_meters_missing": 0,
            "incoming_boxes": None, "incoming_rolls": None, "incoming_meters": None,
            "matches": [{"code": "1314-NULL", "stock_rolls": None, "stock_meters": -3}],
            "incoming_matches": [{"code": "1314-NULL", "incoming_boxes": None}],
            "price": "DO_NOT_EXPOSE_PRICE",
        }}

    monkeypatch.setattr(server, "relay_stock_mcp", fake_worker)
    with TestClient(server.app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        resp = client.get("/stock", params={"code": "1314", "format": "html"})
        assert resp.status_code == 200
        assert "1314-NULL" in resp.text
        assert "<td>NULL</td>" in resp.text
        assert "<td>-3</td>" in resp.text
        assert "DO_NOT_EXPOSE_PRICE" not in resp.text


def test_stock_trace_proves_fresh_request_and_reports_errors(monkeypatch):
    """Every actual HTTP GET has its own server-generated trace, even on failure."""
    import importlib
    from datetime import datetime
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BRIDGE_SHARED_SECRET", "ci_only_bridge_secret_1234567890123")
    server = importlib.import_module("xingwang_miniapp.miniapp_server")
    monkeypatch.setattr(server, "public_stock_recent_calls", [])

    async def fake_worker(code):
        if code == "6616":
            return {"ok": True, "source": "home", "data": {
                "product_code": code, "stock_rolls": 13, "stock_meters": 273,
                "incoming_boxes": None, "incoming_rolls": None,
                "incoming_meters": None,
                "matches": [{"code": "6616", "stock_rolls": 13, "stock_meters": 273}],
                "incoming_matches": [], "price": "SECRET_STOCK_PRICE",
            }}
        return {"ok": False, "code": "LOCAL_API"}

    monkeypatch.setattr(server, "relay_stock_mcp", fake_worker)
    with TestClient(server.app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        one = client.get("/stock", params={"code": "6616"})
        two = client.get("/stock", params={"code": "6616", "format": "html"})
        fail = client.get("/stock", params={"code": "1268"})

    assert one.status_code == 200 and two.status_code == 200
    assert fail.status_code == 503
    first = one.json()
    third = fail.json()
    ids = [first["request_id"], third["request_id"], two.headers["x-xw-stock-request-id"]]
    assert all(len(identifier) == 32 for identifier in ids)
    assert len(set(ids)) == 3
    assert one.headers["x-xw-stock-request-id"] == first["request_id"]
    assert fail.headers["x-xw-stock-request-id"] == third["request_id"]
    assert "本次請求編號：" in two.text
    assert ids[2] in two.text
    assert "Render 回傳時間 (UTC)" in two.text
    assert "SECRET_STOCK_PRICE" not in one.text and "SECRET_STOCK_PRICE" not in two.text
    assert all(datetime.fromisoformat(value).tzinfo is not None for value in [
        first["served_at_utc"], third["served_at_utc"],
    ])
    assert "no-store" in one.headers["cache-control"]
    assert "noindex" in one.headers["x-robots-tag"]
    assert third["code"] == "LOCAL_API"



def test_stock_path_alias_uses_same_live_worker_and_trace(monkeypatch):
    """Path-style URLs and old query URLs both fetch the worker afresh."""
    import importlib
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BRIDGE_SHARED_SECRET", "ci_only_bridge_secret_1234567890123")
    server = importlib.import_module("xingwang_miniapp.miniapp_server")
    monkeypatch.setattr(server, "public_stock_recent_calls", [])
    calls = []

    async def fake_worker(code):
        calls.append(code)
        if code == "FAIL":
            return {"ok": False, "code": "LOCAL_API"}
        count = len(calls)
        return {"ok": True, "source": "home", "data": {
            "product_code": code, "stock_rolls": count, "stock_meters": count * 70,
            "incoming_boxes": 1, "incoming_rolls": None, "incoming_meters": None,
            "matches": [{"code": code + "-A", "stock_rolls": count, "stock_meters": count * 70}],
            "incoming_matches": [{"code": code + "-A", "incoming_boxes": 1}],
            "price": "MUST_NOT_LEAK",
        }}

    monkeypatch.setattr(server, "relay_stock_mcp", fake_worker)
    with TestClient(server.app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        first = client.get("/stock/1268")
        second = client.get("/stock/1268")
        old = client.get("/stock", params={"code": "1268"})
        dashed = client.get("/stock/12-225", params={"format": "html", "nonce": "probe-20261014"})
        failure = client.get("/stock/FAIL")
        invalid = client.get("/stock/%40bad")

    assert [first.status_code, second.status_code, old.status_code, dashed.status_code] == [200] * 4
    assert calls == ["1268", "1268", "1268", "12-225", "FAIL"]
    assert first.json()["stock_rolls"] == 1
    assert second.json()["stock_rolls"] == 2
    assert old.json()["stock_rolls"] == 3
    assert len(set([first.json()["request_id"], second.json()["request_id"],
                    old.json()["request_id"], dashed.headers["x-xw-stock-request-id"],
                    failure.json()["request_id"]])) == 5
    assert first.json()["request_id"] == first.headers["x-xw-stock-request-id"]
    assert "12-225" in dashed.text and "probe-20261014" in dashed.text
    assert "MUST_NOT_LEAK" not in dashed.text
    assert "no-store" in dashed.headers["cache-control"]
    assert failure.status_code == 503 and failure.json()["code"] == "LOCAL_API"
    assert invalid.status_code == 400


def test_short_same_role_reconnect_preserves_lease_and_safe_cross_role_delay(monkeypatch):
    """Fast home reconnection is safe only with locally recorded expired lease."""
    import importlib
    server = importlib.import_module("xingwang_miniapp.miniapp_server")
    monkeypatch.setattr(server.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(server, "_last_active_role", None)
    monkeypatch.setattr(server, "_last_active_lease_until", 0.0)
    assert server._handover_delay_for("home") == server.HANDOVER_SECONDS
    monkeypatch.setattr(server, "_last_active_role", "home")
    monkeypatch.setattr(server, "_last_active_lease_until", 114.0)
    assert server._handover_delay_for("home") == 14.0
    assert server._handover_delay_for("company") == server.HANDOVER_SECONDS
    monkeypatch.setattr(server, "_last_active_lease_until", 99.0)
    assert server._handover_delay_for("home") == 0.0


def test_stock_retry_transient_three_attempts_but_stop_on_real_errors(monkeypatch):
    import asyncio
    import importlib
    server = importlib.import_module("xingwang_miniapp.miniapp_server")
    observed = []
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    async def fake_worker(code):
        observed.append(code)
        if len(observed) == 1:
            return {"ok": False, "code": "LOCAL_OFFLINE"}
        if len(observed) == 2:
            return {"ok": False, "code": "SWITCHING"}
        return {"ok": True, "source": "home", "data": {"product_code": code}}

    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(server, "relay_stock_mcp", fake_worker)
    response = asyncio.run(server._relay_readonly_stock_with_reconnect_retry("6616"))
    assert response["ok"] is True and response["bridge_attempts"] == 3
    assert observed == ["6616", "6616", "6616"] and waits == [7.0, 8.0]

    observed.clear()
    waits.clear()
    async def not_found(code):
        observed.append(code)
        return {"ok": False, "code": "NOT_FOUND"}
    monkeypatch.setattr(server, "relay_stock_mcp", not_found)
    response = asyncio.run(server._relay_readonly_stock_with_reconnect_retry("6616"))
    assert response["code"] == "NOT_FOUND"
    assert response["bridge_attempts"] == 1
    assert observed == ["6616"] and waits == []

    observed.clear()
    async def local_api(code):
        observed.append(code)
        return {"ok": False, "code": "LOCAL_API"}
    monkeypatch.setattr(server, "relay_stock_mcp", local_api)
    response = asyncio.run(server._relay_readonly_stock_with_reconnect_retry("6616"))
    assert response["code"] == "LOCAL_API"
    assert observed == ["6616"] and waits == []

    observed.clear()
    waits.clear()
    async def still_offline(code):
        observed.append(code)
        return {"ok": False, "code": "LOCAL_OFFLINE"}
    monkeypatch.setattr(server, "relay_stock_mcp", still_offline)
    response = asyncio.run(server._relay_readonly_stock_with_reconnect_retry("6616"))
    assert response["ok"] is False
    assert response["bridge_attempts"] == 3
    assert observed == ["6616"] * 3 and waits == [7.0, 8.0]


def test_stock_retry_in_http_api_preserves_no_price_rule(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    server = importlib.import_module("xingwang_miniapp.miniapp_server")
    monkeypatch.setenv("BRIDGE_SHARED_SECRET", "ci_only_bridge_secret_1234567890123")
    monkeypatch.setattr(server, "public_stock_recent_calls", [])
    tries = []

    async def fake_sleep(seconds):
        return None

    async def relay(code):
        tries.append(code)
        if len(tries) == 1:
            return {"ok": False, "code": "LOCAL_OFFLINE"}
        return {"ok": True, "source": "home", "data": {
            "product_code": code, "stock_rolls": -2, "stock_meters": 200,
            "incoming_rolls": None, "incoming_meters": None,
            "incoming_boxes": 0,
            "matches": [{"code": code, "stock_rolls": -2, "stock_meters": 200}],
            "incoming_matches": [{"code": code, "incoming_boxes": 0}],
            "price": "SECRET_PRICE_DO_NOT_LEAK",
            "customer": "SECRET_CUSTOMER_DO_NOT_LEAK",
        }}

    monkeypatch.setattr(server, "relay_stock_mcp", relay)
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)
    with TestClient(server.app, base_url="https://xingwang-stock-miniapp.onrender.com") as client:
        response = client.get("/stock", params={"code": "6616"})
        assert response.status_code == 200
        data = response.json()
        assert data["bridge_attempts"] == 2
        assert data["stock_rolls"] == -2
        assert data["stock_meters"] == 200
        assert data["incoming_boxes"] == 0
        assert "SECRET_PRICE_DO_NOT_LEAK" not in response.text
        assert "SECRET_CUSTOMER_DO_NOT_LEAK" not in response.text
        page = client.get("/stock", params={"code": "6616", "format": "html"})
        assert page.status_code == 200
        assert "橋接查詢次數：1" in page.text
    assert tries == ["6616", "6616", "6616"]
