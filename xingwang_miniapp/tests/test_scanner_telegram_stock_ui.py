"""Full business query retains Telegram permissions; sample stock uses TiDB."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_header_admin_svg():
 s=(ROOT/"scanner.html").read_text("utf-8")
 assert 'id="adminLink"' in s
 assert '<svg viewBox="0 0 24 24"' in s
def test_sample_stock_display():
 s=(ROOT/"scanner.html").read_text("utf-8")
 assert 'id="samplePositiveBtn"' in s
 assert 'id="sampleAllBtn"' in s
 assert "samplePositiveOnly?all.filter(r=>hasPositivePieces(r.stock_rolls)):all" in s
 assert "['present','有樣']" in s and "['missing','無樣']" in s
def test_full_auth_not_scanner_passcode():
 s=(ROOT/"scanner.html").read_text("utf-8")
 assert "window.Telegram?.WebApp?.initData" in s
 assert "if(!initData)throw Error(" in s
 assert "bot:'STOCK',action,q,init_data:initData" in s
