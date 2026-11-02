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
    assert "LEFT JOIN xw_stock_snapshot" in code
    assert "stock_rolls" in code
    assert "qty > available" not in code
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
    assert "cart_id:cartData.id,revision,items" in js
    assert "CART_SAVE_DELAY=1200" in js
    assert "keepalive:true" in js
    assert "/scanner/api/cart/confirm" in js
    assert "cartPending=new Map()" in js
    assert "if(role==='guest')" in js
    assert "current=null;fullData=null;" in js
    assert "history.replaceState" in js
    assert "window.cartBootstrap=cartBootstrap" in js


def test_cart_schema_safe_migration_and_two_confirmed_times():
    code = (ROOT / "scanner_cart.py").read_text(encoding="utf-8")
    assert "SHOW COLUMNS FROM xw_carts" in code
    assert "guest_opened_at" in cart._CART_COLUMNS
    assert "confirmed_at" in cart._CART_COLUMNS
    assert "confirmed_revision" in cart._CART_COLUMNS
    assert "confirmed_version" in cart._CART_COLUMNS
    assert "CREATE TABLE IF NOT EXISTS xw_cart_confirmations" in code
    assert "CREATE TABLE IF NOT EXISTS xw_cart_confirmation_items" in code
    assert "guest_opened_at IS NULL" in code  # first visit, not per SKU tap
    assert "confirmed_at=%s,updated_at=%s" in code
    assert "state='open' WHERE id=%s" in code
    assert "cur.executemany(" in code  # batch changes, immutable version items


def test_guest_no_qr_and_time_is_only_cart_level():
    html = (ROOT / "scanner.html").read_text(encoding="utf-8")
    js = (ROOT / "scanner_cart.js").read_text(encoding="utf-8")
    assert 'id="cartOpenedAt"' in html
    assert 'id="cartConfirmedAt"' in html
    assert 'id="cartVersionBtn"' in html
    assert 'id="cartConfirmedBox"' in html
    assert 'id="cartStateButton"' in html
    assert 'id="cartGuestCode"' in html
    assert "cartEffectiveItems()" in js
    assert "async function cartFlush()" in js
    assert "cartSaveJob" in js
    assert "/scanner/api/cart/confirmed" in js
    assert "cartShareBtn" in js
    assert 'id="cartGuestQr"' not in html


class _FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, args=None):
        self.connection.sql.append((sql, args))
        if "SELECT revision,state,confirmed_revision,confirmed_version,customer_name" in sql:
            self.result = [(3, "open", 0, 0, "TEST")]
        elif "SELECT revision,state FROM xw_carts" in sql:
            self.result = [(3, "ready")]
        elif "SELECT sku,qty FROM xw_cart_items" in sql:
            self.result = [("12-225D-5", 2), ("12-225D-53", 3)]
        elif "SELECT sku,stock_rolls FROM xw_stock_snapshot" in sql:
            self.result = [("12-225D-5", 10)]
        else:
            self.result = []

    def executemany(self, sql, params):
        self.connection.sql.append((sql, list(params)))

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result


class _FakeConnection:
    def __init__(self):
        self.sql = []
        self.committed = 0
        self.rolled_back = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        pass


def test_confirm_writes_full_snapshot_atomically_without_per_tap_time():
    fake = _FakeConnection()
    with patch.object(cart, "_db", return_value=fake), patch.object(cart, "_load", return_value={"confirmed_version": 1}):
        outcome = cart._confirm_cart("a" * 32, 3)
    assert outcome["confirmed_version"] == 1
    assert fake.committed == 1 and fake.rolled_back == 0
    sql = "\n".join(statement for statement, _ in fake.sql)
    assert "INSERT INTO xw_cart_confirmations" in sql
    assert "INSERT INTO xw_cart_confirmation_items" in sql
    assert "confirmed_version=%s" in sql
    item_statement = next(params for statement, params in fake.sql
                          if "INSERT INTO xw_cart_confirmation_items" in statement)
    assert len(item_statement) == 2
    assert item_statement[0][-1] == 2
    assert item_statement[1][-1] == 3


def test_batch_saves_multiple_skus_with_one_cart_revision():
    fake = _FakeConnection()
    with patch.object(cart, "_db", return_value=fake), patch.object(cart, "_load", return_value={"revision": 4}):
        outcome = cart._mutate_batch("a" * 32, 3, {"12-225D-5": 4, "12-225D-53": 0}, "guest")
    assert outcome["revision"] == 4
    assert fake.committed == 1 and fake.rolled_back == 0
    sql = "\n".join(statement for statement, _ in fake.sql)
    assert "INSERT INTO xw_cart_items" in sql
    assert "DELETE FROM xw_cart_items" in sql
    assert "INSERT INTO xw_cart_events" in sql
    assert sql.count("UPDATE xw_carts SET revision=revision+1") == 1


def test_cart_mobile_pick_review_ux_is_compact_and_role_safe():
    ui=(ROOT/"scanner.html").read_text("utf-8")
    js=(ROOT/"scanner_cart.js").read_text("utf-8")
    assert 'id="cartDetailsBtn"' in ui
    assert 'id="cartMeta" class="cart-meta hidden"' in ui
    assert 'id="cartSwitchView"' in ui
    assert 'id="cartDock"' in ui
    assert 'id="cartPickView"' in ui
    assert 'id="cartItemView" class="cc-cart-summary-sheet hidden"' in ui
    assert 'id="cartSkuFilter"' in ui
    assert 'id="cartShareRow"' not in ui  # guest code no longer shown to staff
    assert 'cart-scanner-parked' in ui  # do not close camera on review
    assert 'if(window.cartIsReviewing?.())return;' in ui
    assert "window.cartIsReviewing=()=>!cartCameraOpen" in js
    assert "value.type='text'" in js
    assert "value.inputMode='numeric'" in js
    assert "cartChange(sku,number)" in js
    assert "cartView='pick'" in js
    assert "cartSummaryOpen=false" in js
    assert "'cartDetailsBtn').onclick" in js
    assert "'cartSwitchView').onclick" in js
    assert "window.cartLookup=cartLookup" in js
    assert "cartPending=new Map()" in js
    assert "cartStateButton" in js


def test_cc_ui_redesign_keeps_real_apis_and_camera():
    html=(ROOT/"scanner.html").read_text("utf-8")
    js=(ROOT/"scanner_cart.js").read_text("utf-8")
    assert "--wine:#6A1B36" in html
    assert 'id="cartScanNow"' in html
    assert 'id="cartMeta"' in html
    assert 'id="cartDetailsBtn"' in html
    assert 'id="xwDialog"' in html
    assert 'id="xwDialogInput"' in html
    assert 'id="xwDialogCopy"' in html
    assert 'async function xwConfirm' in html
    assert "await xwConfirm(" in html
    assert "window.prompt(" not in html
    assert "window.prompt(" not in js
    assert "cartSaveListName(item,field)" in js  # inline editor, no customer modal
    assert "await xwConfirm(" in js
    assert "cartScanNow').onclick=cartScanNow;" in js
    assert "await startCamera()" in js
    assert "if(!running)" in js
    assert "compareSkus(a.code,b.code)" in js
    assert "compareSkus(a.sku,b.sku)" in js
    assert "const selected=all.filter(v=>cartItemQty(v.code)>0)" in js
    assert "cartPending=new Map()" in js
    assert "post('/scanner/api/cart/confirm'" in js
    assert 'id="modeSample"' in html
    assert 'id="modeFull"' in html
    assert 'id="saveBtn"' in html
    assert "post('/scanner/api/save'" in html


def test_cc_ui_no_duplicate_dom_ids():
    import re
    html=(ROOT/"scanner.html").read_text("utf-8")
    ids=re.findall(r'\bid="([^"]+)"',html)
    assert len(ids)==len(set(ids)), sorted({i for i in ids if ids.count(i)>1})


def test_cc_zip_11_page_workflows_and_staff_guest_separation():
    html=(ROOT/"scanner.html").read_text(encoding="utf-8")
    js=(ROOT/"scanner_cart.js").read_text(encoding="utf-8")
    for id_ in (
        "ccLoginStaff", "ccLoginGuest", "ccStaffFields", "ccGuestFields",
        "ccCartTotalInfo", "ccSummaryShade", "ccSummaryClose",
        "ccCartCameraClose", "ccSampleBack", "ccStockBack", "ccAdminBack",
        "ccStockOptions", "ccStockWarnDismiss", "ccStockWarnContinue",
        "cartNewName", "cartCreateBtn", "cartRecent", "cartSavedAt",
        "sampleHeaderCheck", "samplePositiveBtn", "saveBtn", "fullPositiveBtn"
    ):
        assert f'id="{id_}"' in html
    assert "const ccLoginMode=which=>" in html
    assert "window.cartCloseCamera=cartCloseCamera;" in js
    assert "cartCameraOpen=true" in js
    assert "cartSummaryOpen=true" in js
    assert "cartEffectiveItems()" in js
    assert "ccFullStockRows(rows)" in html
    assert "ccResultView='sample'" in html
    assert "ccResultView='stock'" in html
    assert "if(mode==='cart')" in html
    assert "if(role==='guest')" in js
    assert "current=null;fullData=null" in js
    assert "const selected=all.filter(v=>cartItemQty(v.code)>0)" in js
    assert "cart_id:cartData.id,revision,items" in js
    assert "CART_SAVE_DELAY=1200" in js
