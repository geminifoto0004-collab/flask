"""Telegram-inspired scanner stock view with separate trusted full data."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_admin_icon_in_header():
    s=(ROOT/'scanner.html').read_text('utf-8')
    assert 'id="adminLink"' in s and 'type="button"' in s
    assert '<svg viewBox="0 0 24 24"' in s
    assert "('adminLink').classList.toggle('hidden',!d.signed_in)" in s
def test_quick_stock_features():
    s=(ROOT/'scanner.html').read_text('utf-8')
    for x in ('id="stockResult"','id="stockStats"','id="stockFilter"',
              'id="stockTableHead"','id="stockTableBody"',
              "['stock_rolls','匹數']", "['stock_meters','米數']",
              'function renderStockResult()', 'aria-sort'):
        assert x in s
    assert "('stockFilter').addEventListener('input',renderStockResult)" in s
def test_full_auth_does_not_use_scanner_passcode():
    s=(ROOT/'scanner.html').read_text('utf-8')
    assert "window.Telegram?.WebApp?.initData" in s
    assert "if(!initData)throw Error(" in s
    assert "bot:'STOCK',action,q,init_data:initData" in s
