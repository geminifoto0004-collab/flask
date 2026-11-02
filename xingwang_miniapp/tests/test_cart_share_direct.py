"""Customer cart sharing, Home navigation and local QR regression guards.

No production cart is created or modified by these tests.
"""
import base64
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from xingwang_miniapp import scanner_backend, scanner_cart

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI()
app.include_router(scanner_backend.router)
app.include_router(scanner_cart.router)


def test_staff_opening_guest_link_keeps_login_and_only_shows_safe_home():
    with patch.object(scanner_backend, "_authorized", return_value=True):
        with TestClient(app) as client:
            result = client.get("/scanner/guest")
    assert result.status_code == 200
    assert "Home / Inicio" in result.text
    assert 'id="cartWorkspace"' not in result.text
    assert "no-store" in result.headers.get("cache-control", "")
    assert "set-cookie" not in result.headers


def test_qr_is_local_svg_and_requires_staff():
    with (patch.object(scanner_backend, "_require", return_value=True),
          patch.object(scanner_backend, "_check_origin", return_value=None)):
        with TestClient(app) as client:
            result = client.post("/scanner/api/cart/share-qr", json={"code": "12345678"})
    assert result.status_code == 200
    svg = base64.b64decode(result.json()["svg_base64"])
    assert svg.startswith(b"<svg")
    assert b"<path" in svg
    assert result.headers["cache-control"] == "no-store"


def test_share_qr_rejects_invalid_access_codes():
    with (patch.object(scanner_backend, "_require", return_value=True),
          patch.object(scanner_backend, "_check_origin", return_value=None)):
        with TestClient(app) as client:
            result = client.post("/scanner/api/cart/share-qr", json={"code": "not-a-code"})
    assert result.status_code == 400


def test_list_share_and_whatsapp_direct_workflow():
    html = (ROOT / "scanner.html").read_text("utf-8")
    js = (ROOT / "scanner_cart.js").read_text("utf-8")
    for field in ("cartSharePanel", "cartShareWhatsApp", "cartShareCopy", "cartShareQr",
                  "cartShareFeedback", "cartShareQrImage"):
        assert html.count(f'id="{field}"') == 1
    assert "share.onclick=()=>cartShareOpen(item)" in js
    assert "https://wa.me/?text=" in js
    assert "encodeURIComponent(msg)" in js
    assert "cartShareEnsureLink()" in js
    assert "cartShareLink&&Date.now()<cartShareExpiry" in js
    assert "location.origin+'/scanner/guest#v='+result.guest_code" in js
    assert "window.open('about:blank','_blank')" in js


def test_cart_home_is_icon_not_previous_arrow():
    html = (ROOT / "scanner.html").read_text("utf-8")
    start = html.index('id="cartExitBtn"')
    button = html[start:html.index("</button>", start)]
    assert 'aria-label="回主頁 / Inicio"' in button
    assert '<path d="m3 10 9-7 9 7v10H3z"' in button
    assert 'm15 18-6-6 6-6' not in button


def test_render_local_requirements_install_qrcode():
    req = (ROOT / "requirements.txt").read_text("utf-8")
    assert "qrcode>=7.4,<9" in req
