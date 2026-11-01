"""UI separation: STOCK Telegram and scanner public workflow remain uncluttered."""
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def test_telegram_title_svg_uses_separate_tab():
    s=(BASE/'index.html').read_text(encoding='utf-8')
    assert '<h1>XINGWANG STOCK</h1><a class="scanner-icon-link"' in s
    assert 'target="_blank"' in s and 'tg.openLink(scannerShortLink)' in s
    assert 'id="scannerShare"' not in s
def test_scanner_main_has_no_management_controls():
    s=(BASE/'scanner.html').read_text(encoding='utf-8')
    for x in ('id="cameraStart"','id="modeSample"','id="saveBtn"'):
        assert x in s
    for x in ('id="dbSetupBtn"','id="inventoryPanel"','id="inventoryStartBtn"','id="shareScannerBtn"','inventoryPolling'):
        assert x not in s
def test_admin_separate_and_protected_by_existing_api():
    s=(BASE/'scanner_admin.html').read_text(encoding='utf-8')
    for x in ('id="dbSetupBtn"','id="inventoryStartBtn"','id="shareScannerBtn"','/scanner/api/session'):
        assert x in s
    b=(BASE/'scanner_backend.py').read_text(encoding='utf-8')
    assert '@router.get("/scanner/admin", response_class=HTMLResponse)' in b
    assert 'def _require(request):' in b
