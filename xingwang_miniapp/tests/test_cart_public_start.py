"""Public fixed QR: privacy, lazy cart creation, idempotent tickets.

No production TiDB data is used in these tests.
"""
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from xingwang_miniapp import scanner_backend as staff
from xingwang_miniapp import scanner_cart as cart

app=FastAPI()
app.include_router(staff.router)
app.include_router(cart.router)
ROOT=Path(__file__).resolve().parents[1]


def test_public_qr_issues_ticket_without_creating_any_cart():
    with (patch.object(staff, "_authorized", return_value=False),
          patch.object(staff, "_key", return_value=b"0"*32),
          patch.object(cart, "_db", side_effect=AssertionError("GET must never touch TiDB"))):
        with TestClient(app) as client:
            response=client.get("/scanner/start")
    assert response.status_code==200
    assert "no-store" in response.headers["cache-control"]
    assert "xw_cart_start=" in response.headers["set-cookie"]
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "secure" in response.headers["set-cookie"].lower()
    assert "id=\"cartPublicStart\"" in response.text


def test_two_scans_from_different_devices_receive_independent_tickets():
    with (patch.object(staff,"_authorized",return_value=False),
          patch.object(staff,"_key",return_value=b"1"*32)):
        with TestClient(app) as a, TestClient(app) as b:
            a.get("/scanner/start")
            b.get("/scanner/start")
            a_ticket=a.cookies.get(cart.START_COOKIE)
            b_ticket=b.cookies.get(cart.START_COOKIE)
    assert a_ticket and b_ticket and a_ticket!=b_ticket
    assert cart._parse_start_token(a_ticket) is None  # no signing key outside patch


def test_anonymous_lookup_does_not_create_cart():
    stock={"product_code":"12-225","variants":[{"code":"12-225D-1","stock_rolls":"2"}],
           "as_of":None,"fresh":False}
    with (patch.object(staff,"_authorized",return_value=False),
          patch.object(staff,"_key",return_value=b"1"*32),
          patch.object(staff,"_check_origin",return_value=None),
          patch.object(cart,"_guard_query",return_value=None),
          patch.object(cart,"_lookup",return_value=stock),
          patch.object(cart,"_create_public_cart",side_effect=AssertionError("must not create"))):
        with TestClient(app) as client:
            client.get("/scanner/start")
            res=client.post("/scanner/api/cart/start/lookup",json={"code":"12-225"})
    assert res.status_code==200
    assert res.json()["variants"][0]["code"]=="12-225D-1"


def test_first_positive_sku_selection_creates_scoped_guest_cookie():
    now=cart.utcnow()
    data={"id":"a"*32,"short_code":"C-TEST","items":[{"sku":"12-225D-1","qty":10}],
          "revision":1}
    captured=[]
    def fake_create(start_data,sku,qty,ip):
        captured.append((start_data,sku,qty))
        return data,1,now+timedelta(hours=8)
    with (patch.object(staff,"_authorized",return_value=False),
          patch.object(staff,"_key",return_value=b"1"*32),
          patch.object(staff,"_check_origin",return_value=None),
          patch.object(cart,"_create_public_cart",side_effect=fake_create)):
        with TestClient(app) as client:
            client.get("/scanner/start")
            before=client.cookies.get(cart.START_COOKIE)
            res=client.post("/scanner/api/cart/start/add",json={"sku":"12-225D-1","qty":10})
    assert res.status_code==200
    assert len(captured)==1
    assert captured[0][1:] == ("12-225D-1",10)
    assert before and res.json()["cart_id"]=="a"*32
    assert "xw_cart_guest=" in res.headers.get("set-cookie","")


def test_start_guards_and_source_invariants():
    py=(ROOT/"scanner_cart.py").read_text("utf-8")
    ui=(ROOT/"scanner.html").read_text("utf-8")
    js=(ROOT/"scanner_cart.js").read_text("utf-8")
    assert "xw_cart_start_limits" in py
    assert "start_hash" in py
    assert "SELECT 1 FROM xw_stock_snapshot" in py
    assert "WHERE start_hash=%s FOR UPDATE" in py
    assert "if publicEntry&&role==='none'" not in ui  # actual JavaScript syntax below
    assert "if(publicEntry&&role==='none')" in ui
    assert "window.publicStartReady=publicStartReady" in js
    assert "await post('/scanner/api/cart/start/add',{sku,qty})" in js
    assert "cartShareOpenStart" in js
    assert "location.origin+'/scanner/start'" in js
