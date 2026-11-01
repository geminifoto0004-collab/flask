"""The sample reader must use a fresh TiDB snapshot, never a V33 query."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from xingwang_miniapp import scanner_tidb

BASE=Path(__file__).resolve().parents[1]

class Cursor:
    def __init__(self,rows):self.rows=rows;self.executions=[]
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql,params=None):
        self.executions.append((sql,params))
        if "FROM xw_stock_sync_state" in sql:
            self.value=self.rows["sync"]
        elif "FROM xw_stock_snapshot" in sql:
            self.value=self.rows["stock"]
        elif "FROM xw_sample_status" in sql:
            self.value=self.rows.get("sample", [])
    def fetchone(self):return self.value
    def fetchall(self):return self.value
class Conn:
    def __init__(self,rows):self.c=Cursor(rows)
    def cursor(self):return self.c
    def commit(self):pass
    def close(self):pass

def test_freshness_at_60_minutes_boundary():
    c=Conn({"sync":(datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=3580),10443)})
    ok=scanner_tidb._freshness_on_connection(c)
    assert ok["fresh"] and ok["sku_count"]==10443
    c=Conn({"sync":(datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=3620),10443)})
    bad=scanner_tidb._freshness_on_connection(c)
    assert not bad["fresh"] and bad["age_seconds"]>3600
def test_missing_sync_refuses_snapshot():
    c=Conn({"sync":None,"stock":[]})
    with patch.object(scanner_tidb,"_connect",return_value=c),patch.object(scanner_tidb,"_ensure"):
        out=scanner_tidb.read_sample_from_snapshot("12-225")
    assert not out["freshness"]["fresh"]
    assert not any("FROM xw_stock_snapshot" in sql for sql,_ in c.c.executions)
def test_typed_sample_snapshot_uses_literal_prefix_and_preserves_negative_null():
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    from decimal import Decimal
    c=Conn({"sync":(now,10443),"stock":[("12_225",Decimal(-2),None),("12_225-3",Decimal(0),Decimal(20))],
            "sample":[("12_225",1,now)]})
    with patch.object(scanner_tidb,"_connect",return_value=c),patch.object(scanner_tidb,"_ensure"):
        out=scanner_tidb.read_sample_from_snapshot("12_225")
    assert out["freshness"]["fresh"]
    assert out["stock_rolls"]=="-2"
    assert out["stock_meters"] is None
    assert out["variants"][0]["stock_rolls"]=="-2"
    assert out["previous_status"]["12_225"]["missing"]
    stockQuery=[(sql,params) for sql,params in c.c.executions if "FROM xw_stock_snapshot" in sql][0]
    assert stockQuery[1][2]=="12!_225%"
def test_scanner_ui_sample_is_separate_from_stock():
    frontend=(BASE/"scanner.html").read_text(encoding="utf-8")
    backend=(BASE/"scanner_backend.py").read_text(encoding="utf-8")
    assert "mode==='sample'?'/scanner/api/sample':'/scanner/api/stock'" in frontend
    assert "'/scanner/api/stock-freshness'" in frontend
    assert 'id="freshnessPanel"' in frontend
    assert '@router.post("/scanner/api/sample")' in backend
    assert '@router.get("/scanner/api/stock-freshness")' in backend
    assert 'fresh["synced_at_utc"] != snapshot_version' in backend
