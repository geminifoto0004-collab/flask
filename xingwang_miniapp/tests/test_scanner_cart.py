"""Cart access/CRUD structure regression checks for existing scanner.

No TiDB credentials are necessary for these tests.
"""
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xingwang_miniapp import scanner_cart as cart
from xingwang_miniapp import scanner_backend as staff

ROOT = Path(__file__).resolve().parents[1]


def test_guest_cookie_is_scoped_signed_and_expires():
    cart_id = "a" * 32
    expiry = int(time.time()) + 120
    with patch.object(staff, "_key", return_value=b"test-only-secret"):
        token = cart._sign_session(cart_id, 7, expiry)
        request = SimpleNamespace(cookies={cart.GUEST_COOKIE: token})
        assert cart._parse_session(request) == (cart_id, 7)
        request.cookies[cart.GUEST_COOKIE] = token[:-1] + ("0" if token[-1] != "0" else "1")
        assert cart._parse_session(request) is None
        request.cookies[cart.GUEST_COOKIE] = cart._sign_session(cart_id, 7, int(time.time()) - 10)
        assert cart._parse_session(request) is None


def test_temporary_cart_guest_cannot_use_scanner_staff_api():
    source = (ROOT / "scanner_cart.py").read_text(encoding="utf-8")
    backend = (ROOT / "scanner_backend.py").read_text(encoding="utf-8")
    assert 'path="/scanner/api/cart"' in source
    assert 'reply.delete_cookie(staff.COOKIE, path="/scanner"' in source
    assert 'reply.delete_cookie(GUEST_COOKIE, path="/scanner/api/cart"' in source
    assert "_guest_access(conn, request)" in source
    assert "cart_id != allowed_id" in source
    assert "guest_generation=guest_generation+1" in source
    assert 'staff._require(request)' in source
    assert '@router.post("/scanner/api/save")' in backend
    assert '_require(request)' in backend
    for endpoint in ("create", "open", "item", "state", "share", "guest-login"):
        assert f'@router.post("/scanner/api/cart/{endpoint}")' in source


def test_cart_uses_only_snapshot_reference_not_reserved_access_write():
    code = (ROOT / "scanner_cart.py").read_text(encoding="utf-8")
    assert "FROM xw_stock_snapshot" in code
    assert "SELECT stock_rolls" in code
    assert "FOR UPDATE" in code
    assert "old_revision != revision" in code
    assert "xw_cart_events" in code
    assert "ON DUPLICATE KEY UPDATE" in code
    assert "state=CASE WHEN %s AND state='ready' THEN 'open' ELSE state END" in code
    assert "CREATE TABLE IF NOT EXISTS xw_carts" in code
    assert "CREATE TABLE IF NOT EXISTS xw_cart_items" in code
    assert "UPDATE Access" not in code


def test_same_page_has_staff_and_guest_cart_with_continuous_scan():
    html = (ROOT / "scanner.html").read_text(encoding="utf-8")
    js = (ROOT / "scanner_cart.js").read_text(encoding="utf-8")
    assert 'id="cartNav"' in html
    assert 'id="cartWorkspace"' in html
    assert 'id="guestCode"' in html
    assert 'id="modeSample"' in html
    assert 'id="modeFull"' in html
    assert '<script src="/scanner/cart.js"></script>' in html
    assert "if(mode==='cart')" in html
    assert "lastQrCode=code;" in html
    assert "window.cartLookup=cartLookup" in js
    assert "cart_id:cartData.id,revision:cartData.revision,sku,qty" in js
    assert "if(role==='guest')" in js
    assert "current=null;fullData=null;" in js
    assert "history.replaceState" in js
    assert "window.cartBootstrap=cartBootstrap" in js
