"""Unslop: restore all four existing full-stock query functions as visible tabs.

Only scanner.html changes. No new endpoint or new data model is required:
stock, camino, history and reservar are already read from fullData.
"""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_four_full_query_tabs_are_visible_in_stock_view():
    html=(ROOT/"scanner.html").read_text("utf-8")
    begin=html.index('<div id="fullTabs" class="full-tabs"')
    end=html.index('</div>',begin)
    tabs=html[begin:end]
    expected=[
        ('stock','庫存'),('camino','待到貨'),
        ('history','歷史購買'),('reservar','預訂'),
    ]
    for key,label in expected:
        assert f'data-fulltab="{key}"' in tabs
        assert f'>{label}</button>' in tabs
    assert [tabs.index(f'data-fulltab="{key}"') for key,_ in expected]==sorted(
        tabs.index(f'data-fulltab="{key}"') for key,_ in expected
    )
    css=html.split("</style>")[0]
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in css
    assert '#fullResult[data-full-tab="stock"] #fullTabs{display:none}' not in css
    assert "#ccStockOptions{display:none!important}" in css

def test_existing_real_api_tab_switching_is_unchanged():
    html=(ROOT/"scanner.html").read_text("utf-8")
    assert "const all=fullTab==='stock'?visibleStock:(Array.isArray(data[fullTab])?data[fullTab]:[])" in html
    assert "$('fullTabs').addEventListener('click',e=>" in html
    assert "fullTab=b.dataset.fulltab" in html
    assert "renderFullResult(fullData)" in html
    assert "if(fullKind==='nota'){fullRenderNota(data);return}" in html
    assert "fullAddCards(cards)" in html
    assert "fullTab==='history'&&data.price_allowed" in html
    assert "fullTab!=='stock'" in html
    assert '#fullResult .stock-visibility{display:flex;gap:' in html

def test_no_camera_sample_cart_logic_changes():
    html=(ROOT/"scanner.html").read_text("utf-8")
    assert "await reader.start({facingMode:'environment'},{fps:10,qrbox:{width:220,height:220}},onScan,()=>{});" in html
    assert "post('/scanner/api/save'" in html
    assert "body.cc-sample-detail #scanPanel #reader.camera-active" in html
    assert 'id="cartWorkspace"' in html
    assert 'id="fullResult"' in html
