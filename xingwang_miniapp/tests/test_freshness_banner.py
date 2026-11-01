"""Reminder can be acknowledged without lying about stale stock freshness.
An explicit employee choice is required before stale sample reads or saves.
"""
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def test_fresh_snapshot_does_not_display_expiry_banner():
    ui=(BASE/"scanner.html").read_text(encoding="utf-8")
    assert 'id="freshnessPanel" class="notice hidden"' in ui
    assert 'id="freshnessContinueBtn"' in ui
    assert "mode!=='sample'||!stale" in ui
    assert "staleAcceptedVersion=lastFreshness.synced_at_utc" in ui
    assert 'id="freshnessDismissBtn"' in ui
    assert "freshnessDismissedKey=freshnessKey(lastFreshness);" in ui
    assert "freshnessDismissedKey=null;" in ui
    assert "staleAcceptedVersion=lastFreshness.synced_at_utc;" in ui

def test_stale_permission_is_explicit_and_snapshot_is_version_bound():
    ui=(BASE/"scanner.html").read_text(encoding="utf-8")
    back=(BASE/"scanner_backend.py").read_text(encoding="utf-8")
    assert "if(!fresh.fresh&&!staleAccepted(fresh))" in ui
    assert "allow_stale:staleAccepted(fresh)" in ui
    assert "allow_stale:staleAccepted()" in ui
    assert 'if not fresh["fresh"] and not allow_stale:' in back
    assert 'fresh["synced_at_utc"] != snapshot_version' in back
