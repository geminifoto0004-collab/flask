"""Read-only staff popularity ranking and minimal Scanner navigation."""
import ast
from datetime import date
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(name):
    return (ROOT / name).read_text(encoding="utf-8")

def test_remove_next_query_only_and_keep_history_paging():
    html = read("scanner.html")
    assert 'id="fullNext"' not in html
    assert "clearFullQuery()" not in html
    assert 'id="fullHistoryMore"' in html
    assert "$('fullHistoryMore').onclick" in html

def test_ranking_navigation_only_for_staff():
    html = read("scanner.html")
    assert 'id="rankingLink"' in html and 'href="/scanner/ranking"' in html
    assert "$('rankingLink').classList.toggle('hidden',role!=='staff')" in html
    assert "$('rankingLink').classList.add('hidden')" in html

def test_ranking_routes_auth_and_parameters():
    source=read("scanner_backend.py")
    ast.parse(source)
    api=source.split('@router.get("/scanner/api/search-ranking")',1)[1].split('@router.get("/scanner/ranking"',1)[0]
    assert "_require(request)" in api
    assert 'days_raw not in ("7", "30")' in api
    assert 'limit_raw not in ("20", "50")' in api
    assert "scanner_tidb.read_search_ranking" in api
    page=source.split('@router.get("/scanner/ranking"',1)[1].split('@router.get("/scanner",',1)[0]
    assert "if not _authorized(request):" in page

def test_ranking_sql_is_bounded_and_existing_table_only():
    source=read("scanner_tidb.py")
    ast.parse(source)
    part=source.split("def read_search_ranking(",1)[1]
    assert "xw_scanner_search_daily" in part
    assert "(days - 1, limit + 1)" in part
    assert "limit not in (20, 50)" in part
    assert "CREATE TABLE" not in part

def test_pending_count_merge_and_time_window():
    source=read("scanner_backend.py")
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=="_merge_search_ranking")
    scope={"_SUGGEST_CODE":re.compile(r"^[A-Z0-9][A-Z0-9._/-]{1,39}$")}
    exec(compile(ast.Module(body=[node],type_ignores=[]),"<ranking>","exec"),scope)
    persisted=[{"code":"12-288W","hits":5},{"code":"12-291","hits":9}]
    pending=[((date(2026,11,5),"12-288W"),(6,None)),
             ((date(2026,10,1),"12-291"),(100,None))]
    got=scope["_merge_search_ranking"](persisted,pending,7,20,date(2026,11,6))
    assert got["rows"] == [{"code":"12-288W","hits":11},{"code":"12-291","hits":9}]
    assert not got["has_more"]

def test_ranking_page_starts_at_20_and_fetches_50_on_demand():
    html=read("scanner_ranking.html")
    assert "loadRanking(20)" in html and "loadRanking(50)" in html
    assert "'/scanner/api/search-ranking?days='" in html
    assert "credentials:'same-origin'" in html
    assert "sku.textContent=row.code" in html
    assert "setInterval(" not in html
