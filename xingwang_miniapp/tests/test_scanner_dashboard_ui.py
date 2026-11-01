"""UI regression checks: cards, meter formatting, table sorts, header checkbox, admin back."""
from pathlib import Path
UI=(Path(__file__).resolve().parents[1]/'scanner.html').read_text(encoding='utf-8')
def test_cards_meters_and_table_sort():
 assert 'class="sample-stats"' in UI
 assert "card.className='sample-stat'" in UI
 assert "label==='M'?fmtMeters(value):fmt(value)" in UI
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

def test_series_heading_is_a_single_mobile_row():
 assert '<div class="sample-series-header"><h2 id="series"></h2>' in UI
 assert 'class="sample-sync"' in UI
 assert 'id="asof"' in UI and 'id="source"' in UI
 assert '.sample-series-header{display:flex;align-items:center;' in UI
 assert '.sample-series-header #source{flex:none;white-space:nowrap}' in UI

def test_compact_scanner_statistics_and_missing_meter_sums():
 assert "['SKU',visible.length" not in UI
 assert "['ROLL',totalsForShownRows(visible,'stock_rolls')]" in UI
 assert "['M',totalsForShownRows(visible,'stock_meters')]" in UI
 assert 'grid-template-columns:repeat(2,minmax(0,1fr))' in UI
 assert "function meterForSum(value)" in UI
 assert "if(!s||s==='—'||s==='-'||s==='–')return 0" in UI
 assert 'id="samplePositiveCount"' in UI and 'id="sampleAllCount"' in UI
 assert 'post(\'/scanner/api/save\',{scan_id:current.scan_id,present,missing})' in UI
