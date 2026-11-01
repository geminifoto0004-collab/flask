"""CC design-preview fidelity and continuous sample scanning regression checks.

Preview reference: user-supplied handoff zip / design-preview:
Login, Scan, Sample, Stock, Carts, Main, Web, Sheet, Confirm, Admin.
The real SAMPLE page intentionally keeps the live QR camera while stocktaking.
"""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]

def ui():
    return (ROOT/"scanner.html").read_text(encoding="utf-8")

def cartjs():
    return (ROOT/"scanner_cart.js").read_text(encoding="utf-8")

def test_preview_mobile_geometry_and_palette():
    h=ui()
    for css in (
        "--cc-bg:#F8F4F5",
        "--cc-dark:#241017",
        "--cc-wine:#6A1B36",
        "#login.cc-login",
        "padding:120px 28px 0!important",
        "#cartWorkspace .cart-line",
        "height:68px!important",
        "height:44px!important",
        "#result table tbody tr",
        "height:58px!important",
        "#fullResult[data-full-tab=\"stock\"] .cc-stock-row",
        "height:56px!important",
        "#xwDialog[data-kind=\"confirm\"] .xw-dialog-sheet",
        "#xwDialog[data-kind=\"sheet\"] .xw-dialog-sheet",
    ):
        assert css in h, css

def test_preview_scan_order_camera_stays_same_screen():
    h=ui()
    i=h.index('<section class="panel" id="scanPanel">')
    j=h.index('</section>',i)
    section=h[i:j]
    assert section.index('id="workModes"') < section.index('id="freshnessPanel"')
    assert section.index('id="freshnessPanel"') < section.index('id="code"')
    assert section.index('id="code"') < section.index('id="reader"')
    assert "body.cc-sample-detail #scanPanel" in h
    assert "display:block!important;visibility:visible!important" in h
    assert "reader.start({facingMode:'environment'}" in h
    assert "function onScan(raw){" in h
    assert "ccResultView&&mode!=='cart'" not in h
    assert "sampleDirty&&!saved" in h
    assert "post('/scanner/api/save'" in h

def test_preview_live_stock_and_cart_not_mock_data():
    h,j=ui(),cartjs()
    for id_ in ('ccLoginStaff','ccLoginGuest','cartRecent','cartProducts','cartTotal',
                'cartSavedAt','saveBtn','sampleSkuSort','fullDetails','fullTime',
                'xwDialogVisual','xwDialogFlow','freshnessDismissBtn'):
        assert f'id="{id_}"' in h
    assert "post('/scanner/api/cart/confirm'" in j
    assert "CART_SAVE_DELAY=1200" in j
    assert "read_sample_from_snapshot" not in h  # calls real API, not fake local data
    assert "post('/scanner/api/sample'" in h
    assert "post('/scanner/api/save'" in h
    assert "compareSkus(a.code,b.code)" in j
    assert "cartData.customer_name" in j

def test_no_duplicate_html_ids():
    ids=re.findall(r'\bid="([^"]+)"',ui())
    assert len(ids)==len(set(ids))

def test_modals_not_native_browser_prompt():
    h,j=ui(),cartjs()
    assert "function xwAsk(" in h
    assert "xwDialogCancel" in h and "xwDialogOk" in h
    assert "window.prompt(" not in j and "window.confirm(" not in j
