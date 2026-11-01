"""Only a proven legacy PEDIDO scope migration may bypass the 20% protection."""
from decimal import Decimal
from unittest.mock import patch
import pytest
from xingwang_miniapp import stock_sync_api as mod

class FakeCursor:
    def __init__(self, old):
        self.old=old
        self.statements=[]
        self.rows=[]
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def execute(self, sql, params=None):
        self.statements.append(sql)
        if sql.startswith("SELECT sku, series"):
            self.rows=[(x, x, Decimal(1), Decimal(2), 1) for x in self.old]
        elif "SELECT id FROM" in sql:
            self.rows=[(1,)]
        else: self.rows=[]
    def executemany(self, sql, params):
        self.statements.append(sql)
    def fetchall(self): return self.rows
    def fetchone(self): return self.rows[0] if self.rows else None

class FakeConnection:
    def __init__(self, old):
        self.c=FakeCursor(old)
        self.committed=False
        self.rolled_back=False
    def cursor(self): return self.c
    def commit(self): self.committed=True
    def rollback(self): self.rolled_back=True
    def close(self): pass

def test_only_old_pedido_keys_are_auto_deactivated():
    old=[f"STOCK-{i}" for i in range(100)]+[f"PEDIDO-{i}(1)" for i in range(80)]
    new={f"STOCK-{i}":("STOCK",Decimal(1),Decimal(2)) for i in range(100)}
    new.update({f"NEW-{i}":("NEW",Decimal(0),Decimal(0)) for i in range(100)})
    conn=FakeConnection(old)
    with patch.object(mod.scanner_tidb,"_connect",return_value=conn), patch.object(mod.scanner_tidb,"_ensure"):
        result=mod._sync_blocking(new)
    assert conn.committed
    assert result["deactivated"]==80
    assert result["sku_count"]==200

def test_missing_genuine_stock_prevents_migration():
    old=[f"STOCK-{i}" for i in range(100)]+[f"PEDIDO-{i}(1)" for i in range(80)]
    new={f"STOCK-{i}":("STOCK",Decimal(1),Decimal(2)) for i in range(99)}
    new.update({f"NEW-{i}":("NEW",Decimal(0),Decimal(0)) for i in range(101)})
    conn=FakeConnection(old)
    with patch.object(mod.scanner_tidb,"_connect",return_value=conn), patch.object(mod.scanner_tidb,"_ensure"):
        with pytest.raises(ValueError,match="STOCK_SCOPE_MISMATCH"):
            mod._sync_blocking(new)
    assert not conn.committed
    assert conn.rolled_back

def test_short_snapshot_is_never_migrated():
    old=[f"STOCK-{i}" for i in range(100)]+[f"PEDIDO-{i}(1)" for i in range(80)]
    new={f"STOCK-{i}":("STOCK",Decimal(1),Decimal(2)) for i in range(100)}
    conn=FakeConnection(old)
    with patch.object(mod.scanner_tidb,"_connect",return_value=conn), patch.object(mod.scanner_tidb,"_ensure"):
        with pytest.raises(ValueError,match="STOCK_SCOPE_MISMATCH"):
            mod._sync_blocking(new)
    assert not conn.committed
