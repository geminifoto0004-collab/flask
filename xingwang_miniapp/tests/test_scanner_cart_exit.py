"""Scanner cart return navigation and stale banner cleanup.

Source-contract checks; production TiDB, camera and browser interactions are untouched.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cart_has_staff_only_back_to_scanner_without_reloading():
    html = (ROOT / "scanner.html").read_text(encoding="utf-8")
    js = (ROOT / "scanner_cart.js").read_text(encoding="utf-8")
    assert html.count('id="cartExitBtn"') == 1
    assert '返回 / Volver' in html
    assert "$('cartExitBtn').onclick=cartExitToScanner;" in js
    assert "if(cartRole!=='staff'||mode!=='cart'||cartBusy)return" in js
    assert "setMode('sample');" in js[js.index("async function cartExitToScanner()"):js.index("$('cartExitBtn').onclick")]
    assert "if((cartPending.size||cartSaveJob)&&!(await cartFlush()))return" in js
    assert "if(!(await cartSaveNote()))return" in js
    assert "if(!(await cartSaveEditingNote()))return" in js
    assert "if(cartCameraOpen)await cartCloseCamera()" in js


def test_cart_header_uses_same_exit_handler_when_visible():
    js = (ROOT / "scanner_cart.js").read_text(encoding="utf-8")
    assert "if(mode==='cart'){await cartExitToScanner();return}" in js
    assert "setMode('cart');" in js
    assert "void cartLoadList();" in js


def test_only_top_brand_is_visible_on_scanner_home():
    html = (ROOT / "scanner.html").read_text(encoding="utf-8")
    assert '<header><div><h1>XINGWANG</h1>' in html
    assert '<footer class="muted">XINGWANG</footer>' not in html


def test_remove_redundant_check_not_actual_stock_refresh():
    html = (ROOT / "scanner.html").read_text(encoding="utf-8")
    assert 'freshnessCheckBtn' not in html
    assert 'id="freshnessAdminBtn"' in html
    assert 'id="freshnessContinueBtn"' in html
    assert 'id="freshnessDismissBtn"' in html
    assert 'id="inventoryStartBtn"' in html
    assert "function checkFreshness()" in html or "async function checkFreshness()" in html


def test_sample_camera_and_sample_save_markers_remain():
    html = (ROOT / "scanner.html").read_text(encoding="utf-8")
    assert 'id="cameraToggle"' in html
    assert "fps:10,qrbox:{width:220,height:220}" in html
    assert 'id="saveBtn"' in html
    assert 'id="cartNav"' in html
