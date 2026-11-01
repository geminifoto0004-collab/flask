"""UI separation: STOCK Telegram and scanner public workflow remain uncluttered."""
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def test_telegram_title_svg_uses_separate_tab():
    s=(BASE/'index.html').read_text(encoding='utf-8')
    assert '<h1>XINGWANG STOCK</h1><a class="scanner-icon-link"' in s
    assert 'target="_blank"' in s and 'tg.openLink(scannerShortLink)' in s
    assert 'id="scannerShare"' not in s
def test_scanner_tabs_and_protected_management():
    s=(BASE/'scanner.html').read_text(encoding='utf-8')
    for x in ('id="cameraStart"','id="modeSample"','id="saveBtn"',
              'id="modeStock"','id="modeFull"','id="adminTab"',
              'id="inventoryStartBtn"','id="shareScannerBtn"'):
        assert x in s
    assert "('adminLink').onclick=()=>setMode('admin')" in s
def test_admin_alias_retained():
    b=(BASE/'scanner_backend.py').read_text(encoding='utf-8')
    assert 'RedirectResponse(url="/scanner#admin"' in b
    assert 'def _require(request):' in b
