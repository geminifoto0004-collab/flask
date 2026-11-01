"""Positive stock/ALL are display-only, including in sample inspection."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_sample_positive_and_all():
 s=(ROOT/"scanner.html").read_text("utf-8")
 for id in ("samplePositiveBtn","sampleAllBtn","fullPositiveBtn","fullAllBtn"):
  assert 'id="'+id+'"' in s
 assert "samplePositiveOnly?all.filter(r=>hasPositivePieces(r.stock_rolls)):all" in s
 assert "hasPositivePieces(row.pieces)" in s
 assert "aria-pressed" in s
def test_save_only_confirmed_subset():
 s=(ROOT/"scanner.html").read_text("utf-8")
 assert "post('/scanner/api/save',{scan_id:current.scan_id,present,missing})" in s
 assert "sampleStates.set(x.code,select.value)" in s
 backend=(ROOT/"scanner_backend.py").read_text("utf-8")
 assert "tuple(v for v in skus if v in confirmed)" in backend
def test_stock_snapshot_retains_all():
 s=(ROOT/"scanner_tidb.py").read_text("utf-8")
 assert 'def read_sample_from_snapshot(code):' in s
 assert "stock_rolls>0" not in s[s.index('def read_fast_stock'):s.index('def read_sample_from_snapshot')]
