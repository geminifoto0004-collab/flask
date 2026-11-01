"""No-database safety tests for cart soft deletion / undo.

Exercise the real transaction functions, not a simulated UI or a live TiDB cart.
"""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from xingwang_miniapp import scanner_cart as cart


class FakeCartDB:
    def __init__(self, state="open", revision=4):
        self.data = {"state": state, "revision": revision,
                     "deleted_prev_state": None, "deleted_until": None,
                     "guest_generation": 2, "guest_hash": "hash",
                     "guest_expires": datetime(2026, 11, 2)}
        self.sql = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, args):
        self.sql.append(sql)
        d = self.data
        if sql.startswith("SELECT revision,state,deleted_prev_state,deleted_until"):
            self.result = (d["revision"], d["state"], d["deleted_prev_state"], d["deleted_until"])
        elif sql.startswith("SELECT revision,state FROM"):
            self.result = (d["revision"], d["state"])
        elif "SET state='cancelled'" in sql:
            state, until, _, _ = args
            d.update(state="cancelled", revision=d["revision"] + 1,
                     deleted_prev_state=state, deleted_until=until,
                     guest_generation=d["guest_generation"] + 1,
                     guest_hash=None, guest_expires=None)
        elif "SET state=%s,revision=revision+1" in sql:
            restored_state, _, _ = args
            d.update(state=restored_state, revision=d["revision"] + 1,
                     deleted_prev_state=None, deleted_until=None)
        else:
            raise AssertionError("unexpected SQL: " + sql)

    def fetchone(self):
        return self.result

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def test_delete_preserves_items_and_versions_and_revokes_guest():
    fake = FakeCartDB("ready", 4)
    now = datetime(2026, 11, 1, 20, 0, 0)
    with patch.object(cart, "_db", return_value=fake), patch.object(cart, "utcnow", return_value=now):
        result = cart._soft_delete_cart("a"*32, 4)
    assert fake.data["state"] == "cancelled"
    assert fake.data["deleted_prev_state"] == "ready"
    assert fake.data["deleted_until"] == now + timedelta(seconds=8)
    assert fake.data["revision"] == 5 and result["revision"] == 5
    assert fake.data["guest_generation"] == 3
    assert fake.data["guest_hash"] is None and fake.data["guest_expires"] is None
    assert fake.commits == 1
    assert not any("DELETE FROM" in sql for sql in fake.sql)


def test_undo_restores_original_state_inside_eight_seconds():
    fake = FakeCartDB("ready", 4)
    now = datetime(2026, 11, 1, 20, 0, 0)
    with patch.object(cart, "_db", return_value=fake), patch.object(cart, "utcnow", return_value=now):
        cart._soft_delete_cart("a"*32, 4)
    with (patch.object(cart, "_db", return_value=fake),
          patch.object(cart, "utcnow", return_value=now + timedelta(seconds=7)),
          patch.object(cart, "_load", return_value={"state": "ready", "revision": 6})):
        result = cart._undo_delete_cart("a"*32, 5)
    assert result["state"] == "ready" and result["revision"] == 6
    assert fake.data["deleted_prev_state"] is None and fake.data["deleted_until"] is None
    assert fake.data["state"] == "ready" and fake.commits == 2


def test_expired_undo_rejected_and_soft_delete_retained():
    fake = FakeCartDB("open", 4)
    now = datetime(2026, 11, 1, 20, 0, 0)
    with patch.object(cart, "_db", return_value=fake), patch.object(cart, "utcnow", return_value=now):
        cart._soft_delete_cart("a"*32, 4)
    with (patch.object(cart, "_db", return_value=fake),
          patch.object(cart, "utcnow", return_value=now + timedelta(seconds=9)),
          pytest.raises(HTTPException) as err):
        cart._undo_delete_cart("a"*32, 5)
    assert err.value.status_code == 410
    assert fake.data["state"] == "cancelled"
    assert fake.commits == 1


def test_stale_revision_cannot_delete_or_restore():
    fake = FakeCartDB("open", 4)
    now = datetime(2026, 11, 1, 20, 0, 0)
    with (patch.object(cart, "_db", return_value=fake),
          patch.object(cart, "utcnow", return_value=now),
          pytest.raises(HTTPException) as err):
        cart._soft_delete_cart("a"*32, 3)
    assert err.value.status_code == 409 and fake.data["state"] == "open"
    with patch.object(cart, "_db", return_value=fake), patch.object(cart, "utcnow", return_value=now):
        cart._soft_delete_cart("a"*32, 4)
    with (patch.object(cart, "_db", return_value=fake),
          patch.object(cart, "utcnow", return_value=now + timedelta(seconds=2)),
          pytest.raises(HTTPException) as err):
        cart._undo_delete_cart("a"*32, 4)
    assert err.value.status_code == 409 and fake.data["state"] == "cancelled"


def test_cart_ui_copy_is_tsv_without_customer_or_cart_headers():
    root = Path(__file__).resolve().parents[1]
    js = (root / "scanner_cart.js").read_text(encoding="utf-8")
    html = (root / "scanner.html").read_text(encoding="utf-8")
    assert "i.sku+'\\t'+i.qty" in js
    assert "items.length+' 个编号" in js
    assert "cart-history-edit" in js and "touchend" in js
    assert 'id="cartUndoBar"' in html
    assert 'id="cartCustomerName"' not in html
