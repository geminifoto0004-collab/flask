"""Demand vs snapshot stock and staff-only per-SKU price notes.

These tests use no real TiDB data; do not assert actual browser/Render verification.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from xingwang_miniapp import scanner_cart as cart


class FakeConn:
    def __init__(self):
        self.state = "open"
        self.rev = 3
        self.notes = {}
        self.result = None
        self.querylog = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args=None):
        self.querylog.append(sql)
        if sql.startswith("SELECT revision,state FROM"):
            self.result = (self.rev, self.state)
        elif sql.startswith("SELECT state FROM"):
            self.result = (self.state,)
        elif sql.startswith("SELECT sku,qty FROM"):
            self.result = [("12-225D-104", 0)]
        elif sql.startswith("SELECT sku,stock_rolls"):
            self.result = [("12-225D-104", 2)]
        elif sql.startswith("SELECT version FROM"):
            value = self.notes.get(args[1])
            self.result = (value[1],) if value else None
        elif sql.startswith("SELECT sku,note,version FROM"):
            self.result = [(sku,*value) for sku,value in self.notes.items()]
        elif sql.startswith("INSERT INTO xw_cart_item_notes"):
            self.notes[args[1]] = (args[2], 1)
        elif sql.startswith("UPDATE xw_cart_item_notes"):
            note,_,_,sku = args
            self.notes[sku] = (note,self.notes[sku][1]+1)
        elif sql.startswith("UPDATE xw_carts SET revision=revision+1"):
            self.rev += 1
        else:
            self.result = []

    def executemany(self, sql, data):
        self.querylog.append(sql)

    def fetchone(self):
        return self.result[0] if isinstance(self.result,list) and self.result else self.result

    def fetchall(self):
        return self.result if isinstance(self.result,list) else []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def test_requested_ten_rolls_not_blocked_by_stock_of_two():
    db = FakeConn()
    with patch.object(cart, "_db", return_value=db), patch.object(cart, "_load", return_value={"revision": 4}):
        result = cart._mutate_batch("a"*32, 3, {"12-225D-104": 10}, "staff")
    assert result["revision"] == 4
    assert db.commits == 1
    assert not any("SELECT sku,stock_rolls" in q for q in db.querylog)
    assert any("INSERT INTO xw_cart_events" in q for q in db.querylog)


def test_per_sku_note_roundtrip_and_stale_version():
    db = FakeConn()
    with patch.object(cart, "_db", return_value=db):
        version = cart._item_note_save("a"*32, "12-225D-104", "USD 1.80 / MT", 0)
        notes = cart._item_notes_get("a"*32)
        assert version == 1
        assert notes["12-225D-104"] == {"note": "USD 1.80 / MT", "version": 1}
        with pytest.raises(HTTPException) as exc:
            cart._item_note_save("a"*32, "12-225D-104", "USD 2.00 / MT", 0)
    assert exc.value.status_code == 409
    assert db.notes["12-225D-104"][0] == "USD 1.80 / MT"


def test_cancelled_cart_cannot_update_item_note():
    db = FakeConn()
    db.state = "cancelled"
    with patch.object(cart, "_db", return_value=db), pytest.raises(HTTPException) as exc:
        cart._item_note_save("a"*32, "12-225D-104", "x", 0)
    assert exc.value.status_code == 404
    assert db.commits == 0


def test_staff_only_note_routes_and_zebra_warning_ui():
    from pathlib import Path
    root = Path(cart.__file__).resolve().parent
    py = (root/"scanner_cart.py").read_text("utf-8")
    js = (root/"scanner_cart.js").read_text("utf-8")
    html = (root/"scanner.html").read_text("utf-8")
    for route in ("/scanner/api/cart/item-notes", "/scanner/api/cart/item-note/save"):
        block = py[py.index('"' + route + '"'):][:280]
        assert "staff._require(request)" in block
    assert "stock_rolls" in py
    assert "qty > available" not in py
    assert "cart-shortfall" in js
    assert "cartItemNoteDirty" in js
    assert "cart-line.insufficient" in html
    assert "nth-of-type(odd)" in html
    assert 'placeholder="客户 / Carritos"' in html
    assert 'placeholder="系列编号 / Buscar SKU"' in html
