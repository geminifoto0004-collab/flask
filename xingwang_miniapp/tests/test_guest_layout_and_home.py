"""Customer mode should never acquire the employee three-column layout or index.

These tests are lightweight source guards, not real-device acceptance.
"""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_employee_grid_requires_employee_role():
    html=(ROOT/"scanner.html").read_text("utf-8")
    assert '#app:has(#cartWorkspace:not(.hidden)[data-cart-role="staff"]) #cartWorkspace' in html
    assert '#cartWorkspace[data-cart-role="staff"]:has(#cartActive:not(.hidden)) #cartStaffList' in html
    assert '#cartWorkspace:has(#cartActive:not(.hidden)) #cartStaffList{' not in html
    assert '#cartWorkspace[data-cart-role="staff"]:has(#cartActive:not(.hidden)) #cartActive' in html


def test_guest_cart_is_single_column_and_no_employee_search():
    html=(ROOT/"scanner.html").read_text("utf-8")
    assert '#cartWorkspace[data-cart-role="guest"] #cartStaffList{display:none!important}' in html
    assert '#cartWorkspace[data-cart-role="guest"] #cartActive{display:block;' in html
    assert '#cartWorkspace[data-cart-role="guest"] #cartMeta{display:none!important}' in html
    assert 'body:has(#cartWorkspace:not(.hidden)[data-cart-role="guest"]) main{max-width:840px' in html


def test_guest_total_is_aligned_to_cart_not_full_browser():
    html=(ROOT/"scanner.html").read_text("utf-8")
    assert '#cartWorkspace[data-cart-role="guest"] #cartDock{left:50%;right:auto;transform:translateX(-50%);width:min(780px,calc(100vw - 24px))' in html


def test_guest_has_home_exit_without_staff_escalation():
    html=(ROOT/"scanner.html").read_text("utf-8")
    js=(ROOT/"scanner_cart.js").read_text("utf-8")
    assert html.count('id="cartGuestExitBtn"')==1
    assert "m3 10 9-7 9 7v10H3z" in html
    assert "$('cartGuestExitBtn').classList.toggle('hidden',!guest)" in js
    assert "$('cartGuestExitBtn').onclick=async()=>{" in js
    assert "await post('/scanner/api/cart/guest-logout');" in js
    assert "location.replace('/scanner');" in js
    assert "if((cartPending.size||cartSaveJob)&&!(await cartFlush()))return;" in js
    assert "if(cartRole==='guest'&&m!=='cart')m='cart';" in html


def test_staff_home_still_enters_sample_without_logging_out():
    js=(ROOT/"scanner_cart.js").read_text("utf-8")
    start=js.index("async function cartExitToScanner()")
    end=js.index("$('cartExitBtn').onclick",start)
    code=js[start:end]
    assert "setMode('sample');" in code
    assert "await post('/scanner/api/cart/guest-logout');" not in code
