"""Guest-only cart entry and Excel-export placement regressions.

Pure route/static checks; does not read or alter any production cart.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from xingwang_miniapp import scanner_backend, scanner_cart

app = FastAPI()
app.include_router(scanner_backend.router)


def test_customer_entry_clears_staff_cookie_and_never_caches():
    with TestClient(app) as client:
        r = client.get("/scanner/guest")
    assert r.status_code == 200
    assert "no-store" in r.headers["cache-control"]
    assert "no-referrer" == r.headers["referrer-policy"]
    cookie = r.headers.get("set-cookie", "")
    assert scanner_backend.COOKIE in cookie
    assert "path=/scanner" in cookie.lower()
    assert "max-age=0" in cookie.lower()


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
    assert "location.origin+'/scanner/guest#v='+d.guest_code" in js
    assert "舊的訪客連結會立即失效" in js
