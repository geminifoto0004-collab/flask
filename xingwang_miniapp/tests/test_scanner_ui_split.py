"""Telegram link and scanner two-tab UI."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_telegram_title_svg_link():
 s=(ROOT/"index.html").read_text("utf-8")
 assert '<h1>XINGWANG STOCK</h1><a class="scanner-icon-link"' in s
 assert "tg.openLink(scannerShortLink)" in s
def test_two_tabs_and_inpage_management():
 s=(ROOT/"scanner.html").read_text("utf-8")
 for id in ("modeSample","modeFull","cameraToggle","adminTab","saveBtn",
            "inventoryStartBtn","shareScannerBtn"):
  assert 'id="'+id+'"' in s
 assert 'id="modeStock"' not in s
 assert "('adminLink').onclick=()=>setMode(mode==='admin'?lastWorkMode:'admin')" in s
def test_admin_old_alias():
 b=(ROOT/"scanner_backend.py").read_text("utf-8")
 assert 'RedirectResponse(url="/scanner#admin"' in b
