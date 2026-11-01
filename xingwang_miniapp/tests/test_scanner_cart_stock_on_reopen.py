"""Cart item stock must survive closing/reopening the cart without re-scanning.

This test doesn't connect to TiDB. A fake cursor exercises the real _load logic.
"""
from datetime import datetime
from pathlib import Path
from decimal import Decimal
from xingwang_miniapp import scanner_cart

ROOT = Path(__file__).resolve().parents[1]


class _StockCursor:
    def __init__(self):
        self.sql = []
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        self.sql.append((query, params))
        if "FROM xw_carts WHERE id=%s" in query:
            now = datetime(2026, 11, 1, 12, 0)
            self.rows = [("a" * 32, "C-261101-TEST", "Customer", "open", 2,
                          None, 1, now, now, None, None, 0, 0)]
        elif "LEFT JOIN xw_stock_snapshot" in query:
            self.rows = [
                ("12-225D-5", 4, Decimal("19.000")),
                ("12-225D-53", 1, Decimal("0.000")),
                ("12-225D-104", 1, None),
            ]
        else:
            raise AssertionError("unexpected SQL: " + query)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _StockConnection:
    def __init__(self):
        self.cursor_instance = _StockCursor()

    def cursor(self):
        return self.cursor_instance


def test_reopen_joins_stock_in_existing_item_query():
    conn = _StockConnection()
    cart = scanner_cart._load(conn, "a" * 32)
    assert cart["items"] == [
        {"sku": "12-225D-5", "qty": 4, "stock_rolls": "19.000"},
        {"sku": "12-225D-53", "qty": 1, "stock_rolls": "0.000"},
        {"sku": "12-225D-104", "qty": 1, "stock_rolls": None},
    ]
    sql = conn.cursor_instance.sql
    assert len(sql) == 2  # header query + items/stock JOIN, not N queries
    assert sql[1][1] == ("a" * 32,)
    assert "LEFT JOIN xw_stock_snapshot" in sql[1][0]
    assert "s.is_active=1" in sql[1][0]
    assert "WHERE i.cart_id=%s" in sql[1][0]
    assert "stock_rolls" in sql[1][0]


def test_cart_js_shows_stock_on_saved_cart_and_correctly_filters_positive():
    js = (ROOT / "scanner_cart.js").read_text(encoding="utf-8")
    assert "knownStock=new Map((cartData.items||[])" in js
    assert "stock_rolls:knownStock.get(i.sku)??null" in js
    assert "inStock=all.filter(v=>v.stock_rolls!=null&&Number(v.stock_rolls)>0)" in js
    assert "cartRow(item.code,cartItemQty(item.code),item.stock_rolls,true)" in js
    assert "cartRow(item.sku,item.qty,knownStock.get(item.sku)??null,true)" in js
    assert "selected=all;" in js  # selected quantity doesn't depend on stock
    assert "post('/scanner/api/cart/confirm'" in js


def test_reopen_has_no_new_route_or_camera_changes():
    source = (ROOT / "scanner_cart.py").read_text(encoding="utf-8")
    frontend = (ROOT / "scanner.html").read_text(encoding="utf-8")
    assert "@router.post(\"/scanner/api/cart/open\")" in source
    assert 'await reader.start({facingMode:\'environment\'},{fps:10,qrbox:{width:220,height:220}},onScan,()=>{});' in frontend
    assert "post('/scanner/api/save'" in frontend
