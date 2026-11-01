"""SAMPLE mobile layout regressions (camera is frozen at the pre-CC behavior)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "scanner.html"


def test_cc_stats_are_vertical_and_fit_four_mobile_columns():
    h = UI.read_text("utf-8")
    section = h[h.index("/* SAMPLE mobile visual repair:"):h.index("</style>", h.index("/* SAMPLE mobile visual repair:"))]
    assert "grid-template-columns:repeat(4,minmax(0,1fr))!important" in section
    assert "flex-direction:column!important" in section
    assert "align-items:flex-start!important" in section
    assert "white-space:normal!important" in section
    assert "font-size:clamp(13px,4vw,21px)!important" in section
    assert "font-size:clamp(10px,2.7vw,12px)!important" in section


def test_sample_table_and_save_dock_do_not_cover_last_sku():
    h = UI.read_text("utf-8")
    section = h[h.index("/* SAMPLE mobile visual repair:"):h.index("</style>", h.index("/* SAMPLE mobile visual repair:"))]
    assert "padding-bottom:calc(124px + env(safe-area-inset-bottom,0px))!important" in section
    assert "width:62px!important" in section
    assert "position:fixed!important" in section
    assert "height:auto!important" in section
    assert "max-width:680px!important" in section
    assert "env(safe-area-inset-bottom,0px)" in section


def test_pre_cc_scanner_camera_decoding_unchanged():
    h = UI.read_text("utf-8")
    camera = h[h.index("async function startCamera(){"):h.index("async function stopCamera(){")]
    assert "await reader.start({facingMode:'environment'},{fps:10,qrbox:{width:220,height:220}},onScan,()=>{});" in camera
    assert "classList.add('camera-active')" in camera
    assert "fps:12" not in camera
    assert "function showResult(d){" in h
    assert "post('/scanner/api/save'" in h
