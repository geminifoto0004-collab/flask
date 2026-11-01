"""Single-page scanner with three work modes and an embedded management tab."""
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"scanner.html"
def test_internal_tabs_and_management():
 html=p.read_text(encoding="utf-8")
 for label in ('布樣盤點','快速庫存','完整查詢','id="adminTab"','id="dbSetupBtn"',
               'id="inventoryStartBtn"','id="shareScannerBtn"',
               "('adminLink').onclick=()=>setMode('admin')"):
  assert label in html,label
 assert 'href="/scanner/admin" target="_blank"' not in html
 assert "mode==='sample'?'/scanner/api/sample':'/scanner/api/quick'" in html
 assert 'function fullRenderProduct(data)' in html
 assert "'/api/query'" in html
 assert "if(!initData)throw Error(" in html
 assert 'mode=\\'admin\\'' in html
def test_telegram_query_not_leaked_through_quick():
 source=(p.parent/"scanner_backend.py").read_text(encoding="utf-8")
 start=source.index('@router.post("/scanner/api/quick")')
 end=source.index('@router.post("/scanner/api/sample")',start)
 assert "read_fast_stock" in source[start:end]
 for secret in ('"customer":','"history":','"price":'):
  assert secret not in source[start:end]
