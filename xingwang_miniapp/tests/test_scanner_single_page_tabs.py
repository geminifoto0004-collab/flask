"""Single HTML: sample and full inquiry, with management as a tab."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_page_structure_and_link():
 html=(ROOT/"scanner.html").read_text("utf-8")
 for x in ('id="modeSample"','id="modeFull"','id="adminTab"',
           'id="dbSetupBtn"','id="inventoryStartBtn"','id="shareScannerBtn"'):
  assert x in html
 for x in ('id="modeStock"','id="cameraStart"','id="cameraStop"'):
  assert x not in html
 assert "('adminLink').onclick=()=>setMode('admin')" in html
 assert "function fullRenderProduct(data)" in html
 assert "'/api/query'" in html
def test_full_query_no_credential_bypass():
 s=(ROOT/"scanner.html").read_text("utf-8")
 assert "if(!initData)throw Error(" in s
 b=(ROOT/"scanner_backend.py").read_text("utf-8")
 assert 'present = data.get("present")' in b
