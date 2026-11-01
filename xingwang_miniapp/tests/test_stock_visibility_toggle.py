"""Stock visibility must not discard zero/negative stock or affect sample saves."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_positive_and_all_stock_ui_controls():
    s=(ROOT/"scanner.html").read_text(encoding="utf-8")
    for name in ("stockPositiveBtn","stockAllBtn","fullPositiveBtn","fullAllBtn"):
        assert 'id="'+name+'"' in s
    assert "hasPositivePieces(r.stock_rolls)" in s
    assert "hasPositivePieces(row.pieces)" in s
    assert "Number.isFinite(amount)&&amount>0" in s
    assert "aria-pressed" in s
    assert "fullTab!=='stock'" in s

def test_sample_scan_and_save_still_include_zero_negative():
    s=(ROOT/"scanner.html").read_text(encoding="utf-8")
    assert "const arr=Array.isArray(current.variants)?current.variants:[]" in s
    assert "missing:[...missing]" in s
    assert "mode==='sample'?'/scanner/api/sample':'/scanner/api/quick'" in s

def test_db_snapshot_queries_not_filtered_server_side():
    s=(ROOT/"scanner_tidb.py").read_text(encoding="utf-8")
    assert 'def read_fast_stock(code):' in s
    assert 'def read_sample_from_snapshot(code):' in s
    assert "stock_rolls>0" not in s[s.index('def read_fast_stock'):s.index('def read_sample_from_snapshot')]
