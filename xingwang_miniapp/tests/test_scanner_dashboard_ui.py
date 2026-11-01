"""UI regression checks: cards, meter formatting, table sorts, header checkbox, admin back."""
from pathlib import Path
UI=(Path(__file__).resolve().parents[1]/'scanner.html').read_text(encoding='utf-8')
def test_cards_meters_and_table_sort():
 assert 'class="sample-stats"' in UI
 assert "card.className='sample-stat'" in UI
 assert "label==='庫存米數'?fmtMeters(value):fmt(value)" in UI
 assert 'fmtMeters(row.stock_meters)' in UI
 for name in ('sampleSkuSort','sampleRollsSort','sampleMetersSort'):
  assert 'id="'+name+'"' in UI
 assert "function setSampleSort(field)" in UI
 assert "th.onkeydown=e=>" in UI
def test_header_bulk_and_admin_back():
 assert 'id="sampleHeaderCheck"' in UI
 assert "('sampleHeaderCheck').onchange=" in UI
 for name in ('sampleSelectAll','sampleSelectNone'):
  assert 'id="'+name+'"' not in UI
 assert "mode==='admin'?lastWorkMode:'admin'" in UI
 assert 'nav.dataset.back=String(managing)' in UI
def test_no_filler():
 assert 'id="modeHelp"' not in UI
