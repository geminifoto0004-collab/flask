"""The freshness reminder is nonintrusive and dismissible.
The server-side sample freshness / 1-hour save guard must be unchanged.
"""
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def test_fresh_snapshot_never_displays_banner():
    ui=(BASE/"scanner.html").read_text(encoding="utf-8")
    assert 'id="freshnessPanel" class="notice hidden"' in ui
    assert 'id="freshnessDismissBtn"' in ui
    assert "if(data?.fresh){" in ui
    assert "freshnessDismissed=false;" in ui
    assert "'hidden',mode!=='sample'||!stale||freshnessDismissed" in ui
def test_dismiss_does_not_disable_backend_validation():
    ui=(BASE/"scanner.html").read_text(encoding="utf-8")
    assert "freshnessDismissed=true;" in ui
    assert "if(!fresh?.fresh)throw" in ui
    backend=(BASE/"scanner_backend.py").read_text(encoding="utf-8")
    assert 'if not fresh["fresh"]:' in backend
    assert 'fresh["synced_at_utc"] != snapshot_version' in backend
