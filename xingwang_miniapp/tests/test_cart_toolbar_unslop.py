"""Scanner cart toolbar / desktop presentation regression guards.

These are static checks only; live browser and authenticated API remain separate QA.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_single_visible_cart_search_and_plus_adjacent():
    html = (ROOT / "scanner.html").read_text(encoding="utf-8")
    segment = html[html.index('<div id="cartStaffList"'):html.index('<div id="cartActive"')]
    assert segment.count('id="cartFilter"') == 1
    assert segment.count('id="cartSidebarCreateBtn"') == 1
    assert segment.index('id="cartFilter"') < segment.index('id="cartSidebarCreateBtn"')
    assert segment.index('id="cartSidebarCreateBtn"') < segment.index('id="cartStart"')
    assert 'id="cartStart" class="cc-cart-new hidden"' in segment
    assert segment.count('id="cartNewName"') == 1
    assert segment.count('id="cartCreateBtn"') == 1
    assert "cc-carts-head" not in segment


def test_create_is_inline_and_edit_button_only_stays_search_toolbar():
    js = (ROOT / "scanner_cart.js").read_text(encoding="utf-8")
    assert "cartCreateEditorOpen=!cartCreateEditorOpen" in js
    assert "cartCreateEditorOpen=false;cartMsgClean()" in js
    assert "$('cartNewName').focus()" in js
    assert "void cartCreate()" in js
    assert "cartCreateEditorOpen=false;cartClearTimer()" in js
    assert "if(item.state==='ready')foot.append(count,status,edit)" in js
    assert "status.textContent='✓'" in js
    assert "$('cartStateLabel').classList.toggle('hidden',!ready)" in js


def test_copy_icon_only_and_single_center_scroll():
    html = (ROOT / "scanner.html").read_text(encoding="utf-8")
    start = html.index('id="cartCopy"')
    end = html.index('</button>',start)
    assert '<svg ' in html[start:end]
    assert '<span' not in html[start:end]
    css = html[html.index("<style>"):html.index("</style>")]
    assert "#cartWorkspace #cartProducts{max-height:72vh;overflow:auto}" not in css
    assert "#cartWorkspace.cart-has-active[data-cart-role=\"staff\"] #cartProducts{max-height:none;overflow:visible}" in css
    assert "scrollbar-width:thin" in css
    assert "grid-template-columns:minmax(0,1fr) 50px" in css
    assert "#cartWorkspace.cart-has-active[data-cart-role=\"staff\"] #cartStart{display:none!important}" not in css


def test_existing_workflows_remain_connected():
    js = (ROOT / "scanner_cart.js").read_text(encoding="utf-8")
    html = (ROOT / "scanner.html").read_text(encoding="utf-8")
    for endpoint in ("/scanner/api/cart/create", "/scanner/api/cart/delete",
                     "/scanner/api/cart/undo-delete", "/scanner/api/cart/batch",
                     "/scanner/api/cart/item-note/save"):
        assert endpoint in js
    for key in ("cartSeriesLookup","cartSkuFilter","cartNoteSave","cartCopy",
                "cartUndoButton","cartCreateBtn","cartSidebarCreateBtn"):
        assert f'id="{key}"' in html
    assert "items.map(i=>i.sku+'\\t'+i.qty).join('\\n')" in js
