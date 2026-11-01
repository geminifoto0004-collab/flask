"""Cart note persistence & staff-only routing — no TiDB credentials required."""
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from xingwang_miniapp import scanner_cart as cart


class FakeConn:
    def __init__(self, revision=7, state="open", note=""):
        self.revision, self.state, self.note = revision, state, note
        self.result = None
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args):
        self.statements.append((sql, args))
        if sql.startswith("SELECT revision,state FROM"):
            self.result = (self.revision, self.state)
        elif sql.startswith("SELECT state FROM"):
            self.result = (self.state,)
        elif sql.startswith("SELECT note FROM"):
            self.result = (self.note,)
        elif sql.startswith("INSERT INTO xw_cart_notes"):
            self.note = args[1]
        elif sql.startswith("UPDATE xw_carts SET revision=revision+1"):
            self.revision += 1
        else:
            raise AssertionError("Unexpected SQL: " + sql)

    def fetchone(self):
        return self.result

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def test_cart_note_roundtrip_and_revision_increment():
    conn = FakeConn()
    with patch.object(cart, "_db", return_value=conn):
        rev = cart._cart_note_save("a" * 32, 7, "12-225D USD 1.80 / MT")
        value = cart._cart_note_get("a" * 32)
    assert rev == 8
    assert value == "12-225D USD 1.80 / MT"
    assert conn.commits == 1
    assert not any("DELETE" in query for query, _ in conn.statements)


def test_cart_note_conflict_never_overwrites():
    conn = FakeConn(revision=8, note="A")
    with patch.object(cart, "_db", return_value=conn), pytest.raises(HTTPException) as ex:
        cart._cart_note_save("a" * 32, 7, "B")
    assert ex.value.status_code == 409
    assert conn.note == "A" and conn.commits == 0


def test_cart_note_rejects_cancelled_cart():
    conn = FakeConn(state="cancelled")
    with patch.object(cart, "_db", return_value=conn), pytest.raises(HTTPException) as ex:
        cart._cart_note_save("a" * 32, 7, "B")
    assert ex.value.status_code == 409
    assert conn.commits == 0


def test_staff_only_note_endpoints_and_normal_cart_api_separated():
    source = Path(cart.__file__).read_text(encoding="utf-8")
    for route in ('/scanner/api/cart/note/get', '/scanner/api/cart/note/save'):
        block = source[source.index(route):source.index(route)+180]
        assert "staff._require(request)" in block
    assert "CREATE TABLE IF NOT EXISTS xw_cart_notes" in source
    assert "note FROM xw_cart_notes" in source


def test_cart_list_defaults_and_customer_name_priority():
    js = (Path(cart.__file__).parent / "scanner_cart.js").read_text(encoding="utf-8")
    html = (Path(cart.__file__).parent / "scanner.html").read_text(encoding="utf-8")
    assert "cartDesktopAutoOpenDone" not in js
    assert "title.textContent=(item.customer_name||'').trim()" in js
    assert "edit.innerHTML=CART_PENCIL_ICON;" in js
    assert 'id="cartNoteText"' in html
    assert 'id="cartNoteSave"' in html
