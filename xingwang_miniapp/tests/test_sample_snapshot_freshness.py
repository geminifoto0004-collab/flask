"""Sample snapshot timing independent of Telegram-authorized full inquiry."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_sample_and_full_mode_routes():
 front=(ROOT/"scanner.html").read_text("utf-8")
 back=(ROOT/"scanner_backend.py").read_text("utf-8")
 assert "post('/scanner/api/sample',{code,allow_stale:staleAccepted(fresh)})" in front
 assert "'/scanner/api/stock-freshness'" in front
 assert 'id="freshnessPanel"' in front
 assert "post('/scanner/api/save',{scan_id:current.scan_id,present,missing,allow_stale:staleAccepted()})" in front
 assert '@router.post("/scanner/api/sample")' in back
 assert 'fresh["synced_at_utc"] != snapshot_version' in back


def test_stale_stock_has_explicit_opt_in_and_page_scoped_dismissal():
 front=(ROOT/"scanner.html").read_text("utf-8")
 back=(ROOT/"scanner_backend.py").read_text("utf-8")
 db=(ROOT/"scanner_tidb.py").read_text("utf-8")
 assert 'id="freshnessContinueBtn"' in front
 assert "staleAcceptedVersion=lastFreshness.synced_at_utc;" in front
 assert "staleAcceptedVersion=null;" in front
 assert "mode!=='sample'||!stale" in front
 assert 'id="freshnessDismissBtn"' in front
 assert "freshnessDismissedKey=freshnessKey(lastFreshness);" in front
 assert "mode!=='sample'||!stale||dismissed" in front
 assert "staleAcceptedVersion=lastFreshness.synced_at_utc;" in front
 assert "'⚠ 庫存未更新 · '" in front
 assert 'if(!fresh?.has_synced)' in front
 assert "if(!fresh.fresh&&!staleAccepted(fresh))" in front
 assert 'allow_stale = body.get("allow_stale") is True' in back
 assert 'if not fresh["has_synced"]:' in back
 assert 'if not fresh["fresh"] and not allow_stale:' in back
 assert 'fresh["synced_at_utc"] != snapshot_version' in back
 assert 'def read_sample_from_snapshot(code, allow_stale=False)' in db
 assert 'if not freshness["has_synced"] or (not freshness["fresh"] and not allow_stale)' in db


def test_stale_snapshot_with_explicit_permission_returns_sample_rows():
 from datetime import datetime, timedelta, timezone
 from decimal import Decimal
 from unittest.mock import patch
 from xingwang_miniapp import scanner_tidb as db

 class Cursor:
  def __init__(self):
   self.data = []
  def __enter__(self):return self
  def __exit__(self,*args):return False
  def execute(self,sql,params=None):
   if "FROM xw_stock_sync_state" in sql:
    self.data = (datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(hours=4),2)
   elif "FROM xw_stock_snapshot" in sql:
    self.data = [("12-225D-5", Decimal("3"), Decimal("100"))]
   elif "FROM xw_sample_scans" in sql:
    self.data = None
   elif "FROM xw_sample_status" in sql:
    self.data = []
   else:
    raise AssertionError(sql)
  def fetchone(self):return self.data
  def fetchall(self):return self.data
 class Connection:
  def cursor(self):return Cursor()
  def commit(self):pass
  def close(self):pass
 with patch.object(db,"_connect",return_value=Connection()),patch.object(db,"_ensure"):
  blocked=db.read_sample_from_snapshot("12-225")
  allowed=db.read_sample_from_snapshot("12-225",True)
 assert blocked["freshness"]["has_synced"] is True
 assert blocked["freshness"]["fresh"] is False
 assert blocked["variants"]==[]
 assert allowed["freshness"]["fresh"] is False
 assert allowed["variants"][0]["code"] == "12-225D-5"
