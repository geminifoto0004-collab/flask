"""Guest-only cart entry and Excel-export placement regressions.

Pure route/static checks; does not read or alter any production cart.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from xingwang_miniapp import scanner_backend, scanner_cart

app = FastAPI()
app.include_router(scanner_backend.router)


def test_guest_entry_never_caches_and_anonymous_cookies_unmodified():
    with TestClient(app) as client:
        r = client.get("/scanner/guest")
    assert r.status_code == 200
    assert "no-store" in r.headers["cache-control"]
    assert "no-referrer" == r.headers["referrer-policy"]
    assert scanner_backend.COOKIE not in r.headers.get("set-cookie", "")


def test_signed_in_staff_sees_home_only_not_guest_cart():
    from unittest.mock import patch
    with patch.object(scanner_backend, "_authorized", return_value=True):
        with TestClient(app) as client:
            r = client.get("/scanner/guest")
    assert r.status_code == 200
    assert "Home / Inicio" in r.text
    assert "员工已登录" in r.text
    assert 'id="cartWorkspace"' not in r.text
    assert 'Set-Cookie' not in r.headers
    assert "no-store" in r.headers["cache-control"]


def test_staff_entry_no_store_after_guest_handoff():
    with TestClient(app) as client:
        r = client.get("/scanner")
    assert r.status_code == 200
    assert "no-store" in r.headers["cache-control"]


def test_guest_scoped_cart_authentication_is_not_ui_only():
    import inspect
    auth = inspect.getsource(scanner_cart._authorize)
    assert "staff_only" in auth
    assert "_guest_access" in auth
    assert "cart_id != allowed_id" in auth
    import inspect
    lists = inspect.getsource(scanner_cart.list_carts)
    assert "staff._require(request)" in lists
    notes = inspect.getsource(scanner_cart.cart_item_note_save)
    assert "staff._require(request)" in notes


def test_copy_export_in_dock_and_share_action_outside_dock():
    from pathlib import Path
    html = Path(scanner_backend.__file__).with_name("scanner.html").read_text("utf-8")
    js = Path(scanner_cart.__file__).with_name("scanner_cart.js").read_text("utf-8")
    dock = html[html.index('id="cartDock"'):html.index('id="cartMessage"')]
    meta = html[html.index('id="cartMeta"'):html.index('id="cartScanAction"')]
    assert 'id="cartCopy"' in dock
    assert 'id="cartShareCustomer"' in meta
    assert 'id="cartCopy"' not in meta
    assert 'id="cartCopyMobile"' in meta
    assert "$('cartCopyMobile').onclick=cartCopyExcel" in js
    assert "/scanner/api/cart/share" in js


def test_secret_link_is_guest_only_fragment_and_scrubbed():
    from pathlib import Path
    html = Path(scanner_backend.__file__).with_name("scanner.html").read_text("utf-8")
    js = Path(scanner_cart.__file__).with_name("scanner_cart.js").read_text("utf-8")
    assert "location.pathname==='/scanner/guest'" in html
    assert "history.replaceState(null,'',location.pathname)" in html
    assert "guestEntry?(c.role==='guest'?'guest':'none')" in html
    assert "if(event.persisted)location.reload()" in html
    assert "location.origin+'/scanner/guest#v='+result.guest_code" in js
    assert "https://wa.me/?text=" in js
    assert "cartShareOpen(item)" in js
    assert "cartShareEnsureLink()" in js
