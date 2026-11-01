"""TiDB sample mode and Telegram full mode must be isolated."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_mode_routing():
 s=(ROOT/'scanner.html').read_text(encoding='utf-8')
 assert "mode==='sample'?'/scanner/api/sample':'/scanner/api/quick'" in s
 assert "'/scanner/api/stock-freshness'" in s
 assert 'id="freshnessPanel"' in s
 assert 'id="fullResult"' in s
 b=(ROOT/'scanner_backend.py').read_text(encoding='utf-8')
 assert '@router.post("/scanner/api/sample")' in b
 assert '@router.post("/scanner/api/quick")' in b
 assert 'fresh["synced_at_utc"] != snapshot_version' in b
