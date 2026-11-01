"""Sample snapshot timing independent of Telegram-authorized full inquiry."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_sample_and_full_mode_routes():
 front=(ROOT/"scanner.html").read_text("utf-8")
 back=(ROOT/"scanner_backend.py").read_text("utf-8")
 assert "post('/scanner/api/sample',{code})" in front
 assert "'/scanner/api/stock-freshness'" in front
 assert 'id="freshnessPanel"' in front
 assert "post('/scanner/api/save',{scan_id:current.scan_id,present,missing})" in front
 assert '@router.post("/scanner/api/sample")' in back
 assert 'fresh["synced_at_utc"] != snapshot_version' in back
