"""Cart filter bar: ALL / positive inventory / chosen rolls."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_cart_has_three_separate_filters_in_requested_order():
    js=(ROOT/"scanner_cart.js").read_text(encoding="utf-8")
    html=(ROOT/"scanner.html").read_text(encoding="utf-8")
    assert "let cartFilterMode='all'" in js
    i_all=js.index("key:'all',items:all,label:'全部'")
    i_stock=js.index("key:'stock',items:inStock,label:'有库存'")
    i_selected=js.index("key:'selected',items:selected,label:'已选'")
    assert i_all < i_stock < i_selected
    assert "button.setAttribute('aria-pressed',String(cartFilterMode===choice.key))" in js
    assert ".cart-filter.cc-three-filters" in html
    assert "grid-template-columns:repeat(3,minmax(0,1fr))!important" in html


def test_positive_stock_independent_from_selected_qty():
    js=(ROOT/"scanner_cart.js").read_text(encoding="utf-8")
    assert "selected=all.filter(v=>cartItemQty(v.code)>0)" in js
    assert "inStock=all.filter(v=>Number(v.stock_rolls)>0)" in js
    assert "cartFilterMode==='stock'?pools.inStock" in js
    assert "cartFilterMode==='selected'?pools.selected" in js
    assert "v.code.toLowerCase().includes(cartSkuSearch.toLowerCase())" in js
    assert "cartSearch=d;cartFilterMode='all'" in js
    assert "compareSkus(a.code,b.code)" in js


def test_cart_filter_does_not_modify_save_or_scanner():
    js=(ROOT/"scanner_cart.js").read_text(encoding="utf-8")
    html=(ROOT/"scanner.html").read_text(encoding="utf-8")
    assert "cartPending=new Map()" in js
    assert "post('/scanner/api/cart/confirm'" in js
    assert "cartScanNow').onclick=cartScanNow" in js
    assert "await reader.start({facingMode:'environment'},{fps:10,qrbox:{width:220,height:220}},onScan,()=>{});" in html
