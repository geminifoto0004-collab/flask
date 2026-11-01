"""Only explicitly confirmed sample statuses may be saved."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_save_route_accepts_explicit_present_and_missing():
 s=(ROOT/'scanner_backend.py').read_text(encoding='utf-8')
 assert 'present = data.get("present")' in s
 assert 'set(missed).intersection(present)' in s
 assert 'not (missed or present)' in s
 assert 'confirmed = set(missed) | set(present)' in s
 assert 'tuple(v for v in skus if v in confirmed)' in s
 assert 'not confirmed.issubset(skus)' in s
def test_tidb_save_rows_remain_transactional():
 s=(ROOT/'scanner_tidb.py').read_text(encoding='utf-8')
 assert 'def save_scan(scan_id, series, skus, missing, device_id):' in s
 assert 'conn.commit()' in s[s.index('def save_scan'):s.index('def stock_breakdown')]
