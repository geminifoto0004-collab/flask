"""Telegram-style scanner stock view; scanner auth and sample save stay separate."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_admin_icon_in_header():
    s=(ROOT/'scanner.html').read_text('utf-8')
    assert 'id="adminLink" href="/scanner/admin" target="_blank"' in s
    assert '<svg viewBox="0 0 24 24"' in s
    assert "('adminLink').classList.toggle('hidden',!d.signed_in)" in s
def test_telegram_style_stock_features():
    s=(ROOT/'scanner.html').read_text('utf-8')
    for v in ('id="stockResult"','id="stockStats"','id="stockFilter"','id="stockTableHead"',
              'id="stockTableBody"',"['code','商品編號']","['stock_rolls','匹數']",
              "['stock_meters','米數']","['incoming_boxes','待到貨(箱)']",
              "function renderStockResult()", "stockSort", "stockDesc", "aria-sort"):
        assert v in s,v
    assert "('stockFilter').addEventListener('input',renderStockResult)" in s
    assert "'stockResult').classList.toggle('hidden',mode!=='stock')" in s
    assert "id=\"saveBtn\"" in s
def test_api_exposes_only_allowlisted_quantity_fields():
    backend=(ROOT/'scanner_backend.py').read_text('utf-8')
    assert '"incoming_boxes": clean.get("incoming_boxes")' in backend
    src=backend[backend.indexOf('return JSONResponse({"ok": True, "product_code": code'): ]
    src=src.split('@router.post("/scanner/api/save")')[0]
    for forbidden in ('"price":', '"customer":', '"history":', '"nota":'):
        assert forbidden not in src
    assert 'normalize_stock(raw, code)' in src
