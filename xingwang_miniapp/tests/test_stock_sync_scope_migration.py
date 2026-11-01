"""Verify stage-and-swap inventory replaces only stock and is reversible."""
from decimal import Decimal
from unittest.mock import patch
import pytest
from xingwang_miniapp import stock_sync_api as m

class Cursor:
    def __init__(self,c): self.c=c; self.result=None
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def execute(self,sql,params=None):
        c=self.c
        c.statements.append(sql)
        if sql.startswith("SELECT COUNT(*) FROM xw_stock_snapshot WHERE"):
            self.result=(len(c.tables["xw_stock_snapshot"]),)
        elif sql.startswith("CREATE TABLE"):
            c.tables[sql.split()[2]]={}
        elif sql.startswith("SELECT COUNT(*) FROM"):
            self.result=(len(c.tables[sql.split()[-1]]),)
        elif sql.startswith("SELECT COALESCE(SUM"):
            tbl=c.tables[sql.split()[-1]]
            vals=[v[1] for v in tbl.values()]
            self.result=(
                sum(x is not None and x>0 for x in vals),
                sum(x is not None and x==0 for x in vals),
                sum(x is not None and x<0 for x in vals),
                sum(x is None for x in vals))
        elif sql.startswith("RENAME TABLE"):
            names=sql.split()
            old1,new1,old2,new2=names[2],names[4][:-1],names[5],names[7]
            c.tables[new1]=c.tables.pop(old1)
            c.tables[new2]=c.tables.pop(old2)
        elif sql.startswith("DROP TABLE"):
            c.tables.pop(sql.split()[-1],None)
        elif sql.startswith("INSERT INTO xw_stock_sync_state"):
            c.success_count=int(params[1])
    def executemany(self,sql,rows):
        tbl=sql.split()[2]
        if self.c.fail_inserts: raise RuntimeError("simulated staging insert failure")
        for sku,series,rolls,meters,is_active,stamp in rows:
            assert is_active == 1
            self.c.tables[tbl][sku]=(series,rolls,meters)
    def fetchone(self):return self.result

class Conn:
    def __init__(self,old=0,fail_inserts=False):
        self.tables={"xw_stock_snapshot":{str(i):("s",Decimal(1),Decimal(0))
                      for i in range(old)}}
        self.samples={"sample-1":"missing"}
        self.statements=[]
        self.fail_inserts=fail_inserts
        self.rollbacks=0
        self.success_count=None
    def cursor(self):return Cursor(self)
    def commit(self):pass
    def rollback(self):self.rollbacks+=1
    def close(self):pass

def run(conn,data):
    with patch.object(m.scanner_tidb,"_connect",return_value=conn), \
         patch.object(m.scanner_tidb,"_ensure"):
        return m._sync_blocking(data)

def sample(n):
    return {f"sample-{i}":("s",Decimal(-1) if i%3==0 else Decimal(0),None)
            for i in range(n)}

def test_full_swap_preserves_sample_tables_and_stock_counts():
    c=Conn(old=200)
    r=run(c,sample(520))
    assert r["sku_count"]==520
    assert r["mode"]=="replace"
    assert c.success_count==520
    assert len(c.tables["xw_stock_snapshot"])==520
    assert c.samples["sample-1"]=="missing"
    assert not any(x.startswith("DELETE FROM") for x in c.statements)
    assert any(x.startswith("RENAME TABLE") for x in c.statements)

def test_failed_staging_never_changes_existing_stock():
    c=Conn(old=200,fail_inserts=True)
    with pytest.raises(RuntimeError,match="simulated"):
        run(c,sample(520))
    assert len(c.tables["xw_stock_snapshot"])==200
    assert c.rollbacks
    assert c.success_count is None
    assert c.samples["sample-1"]=="missing"

def test_reject_shrunken_snapshot_before_staging():
    c=Conn(old=200)
    with pytest.raises(ValueError,match="TOO_SMALL"):
        run(c,sample(10))
    assert len(c.tables)==1
    assert len(c.tables["xw_stock_snapshot"])==200


def test_stock_insert_uses_real_pymysql_bulk_sql(monkeypatch):
    """Guard against a 250x RTT regression: every VALUES arg is a placeholder."""
    from pymysql.cursors import RE_INSERT_VALUES
    c=Conn(old=0)
    import xingwang_miniapp.stock_sync_api as mod
    observed=[]
    orig=Cursor.executemany
    def spy(self, sql, rows):
        assert RE_INSERT_VALUES.match(sql) is not None, (
            "PyMySQL executemany would fall back to single-row INSERTs"
        )
        assert sql.count("%s") == 6
        observed.append(len(rows))
        return orig(self, sql, rows)
    monkeypatch.setattr(Cursor,"executemany",spy)
    result=run(c,sample(2300))
    assert result["sku_count"]==2300
    assert observed==[1000,1000,300]
