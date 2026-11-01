"""Transactional full stock replacement: snapshot only, never sample tables."""
from decimal import Decimal
from unittest.mock import patch
import pytest
from xingwang_miniapp import stock_sync_api as mod

class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = None
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None):
        self.conn.statements.append(sql)
        if "SELECT id FROM xw_stock_sync_state" in sql:
            self.result = (1,)
        elif "SELECT COUNT(*) FROM xw_stock_snapshot WHERE is_active=1" in sql:
            self.result = (len(self.conn.old),)
        elif sql.startswith("DELETE FROM xw_stock_snapshot"):
            self.conn.pending = {}
        elif sql.startswith("SELECT COUNT(*) FROM xw_stock_snapshot"):
            self.result = (len(self.conn.pending),)
    def executemany(self, sql, rows):
        if self.conn.fail_insert:
            raise RuntimeError("simulated_insert_failure")
        assert sql.startswith("INSERT INTO xw_stock_snapshot")
        for sku, series, rolls, meters, ts in rows:
            self.conn.pending[sku] = (series, rolls, meters)
    def fetchone(self): return self.result

class Connection:
    def __init__(self, old=None, fail_insert=False):
        self.old = dict(old or {})
        self.pending = dict(self.old)
        self.samples = {"SKU1": "missing"}
        self.fail_insert = fail_insert
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
    def cursor(self): return Cursor(self)
    def commit(self):
        self.old = dict(self.pending)
        self.commits += 1
    def rollback(self):
        self.pending = dict(self.old)
        self.rollbacks += 1
    def close(self): pass

def sync(conn, snapshot, **kwargs):
    with patch.object(mod.scanner_tidb, "_connect", return_value=conn), \\
         patch.object(mod.scanner_tidb, "_ensure"):
        return mod._sync_blocking(snapshot, **kwargs)

def test_full_snapshot_replaces_old_scope_without_upsert():
    conn = Connection({f"OLD-{i}": ("OLD", Decimal(1), Decimal(0)) for i in range(200)})
    data = {f"SKU{i}": ("S", Decimal(0) if i%2==0 else Decimal(-1), None)
            for i in range(520)}
    result = sync(conn, data)
    assert result["mode"] == "replace"
    assert result["sku_count"] == 520
    assert result["replaced_old"] == 200
    assert len(conn.old) == 520
    assert len([s for s in conn.statements if s.startswith("DELETE FROM")]) == 1
    assert conn.samples["SKU1"] == "missing"
    assert not any("ON DUPLICATE KEY" in sql for sql in conn.statements)
    assert conn.commits == 1

def test_insert_failure_rolls_back_delete_and_state():
    conn = Connection({"SKU1": ("S", Decimal(2), Decimal(0))}, fail_insert=True)
    with pytest.raises(RuntimeError, match="simulated_insert_failure"):
        sync(conn, {"SKU2": ("S", Decimal(0), None)})
    assert "SKU1" in conn.old
    assert conn.rollbacks == 1
    assert conn.commits == 0
    assert conn.samples == {"SKU1": "missing"}

def test_large_unexpected_shrink_rejected_before_delete():
    conn = Connection({f"SKU{i}": ("S", Decimal(2), Decimal(0)) for i in range(200)})
    with pytest.raises(ValueError, match="STOCK_SNAPSHOT_TOO_SMALL"):
        sync(conn, {f"SKU{i}": ("S", Decimal(0), Decimal(0)) for i in range(10)})
    assert not any(x.startswith("DELETE FROM") for x in conn.statements)
    assert conn.rollbacks == 1

def test_zero_negative_null_survive():
    conn = Connection()
    result = sync(conn, {"A":("A", Decimal(0), None),
                         "B":("B", Decimal(-2), Decimal(-22)),
                         "C":("C", None, None)})
    assert result["sku_count"] == 3
    assert conn.old["A"][1] == Decimal(0)
    assert conn.old["B"][1] == Decimal(-2)
    assert conn.old["C"][1] is None
