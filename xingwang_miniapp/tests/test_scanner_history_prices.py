"""Company scanner shows existing historical prices without changing the local worker."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def mapper():
    source = (ROOT / "miniapp_server.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    function = next(n for n in module.body if isinstance(n, ast.FunctionDef)
                    and n.name == "_scanner_staff_history_prices")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<staff-prices>", "exec"), namespace)
    return namespace["_scanner_staff_history_prices"]


def test_history_prices_and_zero_are_preserved():
    data = {"price_allowed": False, "history": [
        {"code": "12-288W-40", "PRECIO": 27.5},
        {"code": "12-288W-3", "price": 0, "PRECIO": 99},
        {"code": "12-288W-11", "Precio": "28.00"},
        {"code": "12-288W-44"},
    ]}
    actual = mapper()(data, "stock")
    assert actual["price_allowed"] is True
    assert [r.get("price") for r in actual["history"]] == [27.5, 0, "28.00", None]


def test_history_more_uses_existing_prices_without_extra_queries():
    data = {"rows": [{"precio": 20}, {"PRECIO": 0}, {"price": 12}]}
    actual = mapper()(data, "history_more")
    assert [r.get("price") for r in actual["rows"]] == [20, 0, 12]


def test_other_actions_do_not_acquire_prices():
    data = {"rows": [{"PRECIO": 100}]}
    assert mapper()(data, "nota") is data
    assert "price" not in data["rows"][0]


def test_price_visibility_restricted_to_company_endpoint():
    server = (ROOT / "miniapp_server.py").read_text(encoding="utf-8")
    company = server.split('@app.post("/scanner/api/full")', 1)[1].split('@app.websocket("/bridge")', 1)[0]
    telegram = server.split('@app.post("/api/query")', 1)[1].split('@app.post("/scanner/api/full")', 1)[0]
    assert 'scanner_backend._require(request)' in company
    assert '_scanner_staff_history_prices(response.get("data"),action)' in company
    assert '_scanner_staff_history_prices(response.get("data"),action)' not in telegram


def test_mobile_sale_price_column_keeps_sorting_and_missing_price_note():
    html = (ROOT / "scanner.html").read_text(encoding="utf-8")
    assert "fullTab==='history'&&data.price_allowed?[...fullFields.history,['price','成交單價']]" in html
    assert 'missingHistoryPrices' in html
    assert '本頁為公司唯讀查詢，不提供成交單價。' not in html
    assert '#fullResult[data-full-tab="history"] .full-table tbody td:nth-child(6)' in html
