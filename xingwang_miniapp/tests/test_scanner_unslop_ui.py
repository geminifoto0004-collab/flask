"""Unslop UI-only regression guardrails.

The target appearance is the user-supplied CC design-preview. These checks
verify the nonfunctional contract; they are not pixel-diff screenshot tests.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(name):
    return (ROOT / name).read_text(encoding="utf-8")

def test_unslop_does_not_change_camera_or_stocktaking_controls():
    html = read("scanner.html")
    assert "await reader.start({facingMode:'environment'},{fps:10,qrbox:{width:220,height:220}},onScan,()=>{});" in html
    assert "async function stopCamera(){" in html
    assert "function onScan(raw){" in html
    assert "post('/scanner/api/save'" in html
    assert "body.cc-sample-detail #scanPanel" in html
    assert 'id="freshnessDismissBtn"' in html

def test_unslop_preserves_cart_event_targets_and_access_modes():
    html = read("scanner.html")
    js = read("scanner_cart.js")
    for node_id in (
        "ccLoginStaff", "ccLoginGuest", "cartNewName", "cartRecent",
        "cartProducts", "cartStateButton", "cartSavedAt",
        "ccCartTotalInfo", "ccSummaryClose", "samplePositiveBtn",
        "sampleAllBtn", "saveBtn", "reader", "cameraToggle"
    ):
        assert f'id="{node_id}"' in html
    assert "cartFilterMode==='stock'" in js
    assert "cartFilterMode==='selected'" in js
    assert "post('/scanner/api/cart/confirm'" in js

def test_unslop_css_mobile_dock_and_markup_invariants():
    html=read("scanner.html")
    style=html.split("</style>",1)[0]
    assert "@media(max-width:430px)" in style
    assert "#cartWorkspace #cartStateButton{width:112px!important;min-width:112px!important}" in style
    assert "#cartWorkspace .cart-save-status{font-size:10px!important;white-space:nowrap}" in style
    ids=re.findall(r'\bid="([^"]+)"',html)
    assert len(ids)==len(set(ids))
    assert "!important" in style  # Not all old CSS is clean yet.
