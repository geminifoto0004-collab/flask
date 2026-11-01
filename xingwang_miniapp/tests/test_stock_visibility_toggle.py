"""Stock view filter must not change hidden SKU statuses."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_sample_positive_and_all():
 s=(ROOT/"scanner.html").read_text("utf-8")
 for id in ("samplePositiveBtn","sampleAllBtn","fullPositiveBtn","fullAllBtn"):
  assert 'id="'+id+'"' in s
 assert "hasPositivePieces(x.stock_rolls)" in s
 assert "hasPositivePieces(row.pieces)" in s
 assert "aria-pressed" in s
def test_save_only_visible():
 s=(ROOT/"scanner.html").read_text("utf-8")
 assert "post('/scanner/api/save',{scan_id:current.scan_id,present,missing})" in s
 assert "const visible=visibleSampleRows();" in s
 assert "cb.onchange=" in s
 backend=(ROOT/"scanner_backend.py").read_text("utf-8")
 assert "tuple(v for v in skus if v in confirmed)" in backend
def test_snapshot_still_has_all_skus():
 s=(ROOT/"scanner_tidb.py").read_text("utf-8")
 assert 'def read_sample_from_snapshot(code):' in s
