"""One scanner HTML with sample, company-authorized full inquiry and in-page management."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_single_page():
 s=(ROOT/'scanner.html').read_text('utf-8')
 for item in ('id="modeSample"','id="modeFull"','id="adminTab"',
              'id="inventoryStartBtn"','id="shareScannerBtn"','id="cameraToggle"'):
  assert item in s,item
 assert 'id="modeStock"' not in s
 assert "('adminLink').onclick=()=>setMode(mode==='admin'?lastWorkMode:'admin')" in s
 assert "function fullRenderProduct(data)" in s
def test_full_company_auth():
 ui=(ROOT/'scanner.html').read_text('utf-8')
 assert "fetch('/scanner/api/full'" in ui
 assert 'if(!initData)throw Error(' not in ui
 b=(ROOT/'miniapp_server.py').read_text('utf-8')
 assert 'scanner_backend._require(request)' in b
