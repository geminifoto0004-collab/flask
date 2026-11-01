"""Fast stock-only query and old admin address compatibility."""
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
from xingwang_miniapp import scanner_tidb as db
BASE=Path(__file__).resolve().parents[1]

class Cursor:
 def __init__(self):
  self.sql=[]
  self.result=None
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def execute(self,q,params=None):
  self.sql.append((q,params))
  if "xw_stock_sync_state" in q:self.result=(datetime.now(timezone.utc).replace(tzinfo=None),10443)
  else:self.result=[("12-225D-5",Decimal("0"),Decimal("0")),("12-225D-9",Decimal("-2"),None)]
 def fetchone(self):return self.result
 def fetchall(self):return self.result
class Conn:
 def __init__(self):self.c=Cursor()
 def cursor(self):return self.c
 def close(self):pass

def test_stock_only_retains_zero_negative_null_and_staleness():
 c=Conn()
 with patch.object(db,"_connect",return_value=c),patch.object(db,"_ensure"):
  result=db.read_fast_stock("12-225")
 assert len(result["variants"])==2
 assert result["variants"][0]["stock_rolls"]=="0"
 assert result["variants"][1]["stock_rolls"]=="-2"
 assert result["stock_rolls"]=="-2"
 assert result["stock_meters"] is None
 assert result["incoming_boxes"] is None
 assert all("customer" not in row for row in result["variants"])
 assert "ESCAPE '!'" in c.c.sql[1][0]

def test_scanner_admin_old_link_redirects_into_tab():
 source=(BASE/"scanner_backend.py").read_text(encoding="utf-8")
 assert 'RedirectResponse(url="/scanner#admin"' in source
 assert '@router.post("/scanner/api/quick")' in source
