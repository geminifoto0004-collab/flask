"""Scanner stock dashboard and company-passcode full query remain separate."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_header_admin_return():
 s=(ROOT/'scanner.html').read_text('utf-8')
 assert 'id="adminLink"' in s
 assert 'mode===\'admin\'?lastWorkMode:\'admin\'' in s
def test_sample_stock():
 s=(ROOT/'scanner.html').read_text('utf-8')
 for id in ('samplePositiveBtn','sampleAllBtn','sampleHeaderCheck'):
  assert 'id="'+id+'"' in s
 assert 'function renderRows()' in s
 assert "fmtMeters(row.stock_meters)" in s
def test_full_not_telegram():
 s=(ROOT/'scanner.html').read_text('utf-8')
 assert "fetch('/scanner/api/full'" in s
 assert 'if(!initData)throw Error(' not in s
 assert 'window.Telegram?.WebApp?.initData' not in s
