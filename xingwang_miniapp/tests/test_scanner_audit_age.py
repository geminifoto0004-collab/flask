"""Series age is based on completed save events, never QR reads."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_latest_completed_audit_read_only():
 db=(ROOT/'scanner_tidb.py').read_text('utf-8')
 part=db[db.index('def read_sample_from_snapshot('):db.index('def save_scan(')]
 assert 'FROM xw_sample_scans WHERE series=%s' in part
 assert 'ORDER BY checked_at DESC LIMIT 1' in part
 assert '"last_checked_at":' in part
 assert 'latest_scan[0].isoformat(timespec="seconds") + "Z"' in part
 assert '"last_checked_count": latest_scan[1]' in part
 api=(ROOT/'scanner_backend.py').read_text('utf-8')
 assert '"last_checked_at": data["last_checked_at"]' in api
def test_age_badge_and_short_inventory_timestamp():
 ui=(ROOT/'scanner.html').read_text('utf-8')
 assert "function auditAgeLabel(checkedAt)" in ui
 for label in ("'7−'", "'7+'", "'30+'", "'90+'", "'180+'", "'—'"):
  assert label in ui
 assert "badge.className='tag audit-badge '+auditAgeClass(age)" in ui
 assert "renderLastChecked();" in ui
 assert "current.last_checked_at=out.checked_at?" in ui
 assert "庫存更新：" in ui
 assert "智利時間" not in ui
