"""NULL quantity regression tests: NULL != zero; missing field != NULL."""
from decimal import Decimal
import pytest
from xingwang_miniapp import stock_sync_api as mod

def payload(rows):
    return {"schema":"xw-stock-v1","complete_snapshot":True,"expected_count":len(rows),"rows":rows}

def test_valid_access_null_and_negative_values():
    result = mod._validate(payload([
        {"sku":"12-225-1","stock_rolls":"10","stock_meters":None},
        {"sku":"12-225-2","stock_rolls":None,"stock_meters":"0"},
        {"sku":"12-225-3","stock_rolls":None,"stock_meters":None},
        {"sku":"12-225-4","stock_rolls":"-5","stock_meters":"-13.5"},
    ]))
    assert len(result) == 4
    assert result["12-225-1"] == ("12-225", Decimal("10"), None)
    assert result["12-225-2"] == ("12-225", None, Decimal("0"))
    assert result["12-225-3"] == ("12-225", None, None)
    assert result["12-225-4"] == ("12-225", Decimal("-5"), Decimal("-13.5"))

def test_missing_quantity_field_rejected():
    with pytest.raises(ValueError,match="Missing stock quantity field"):
        mod._validate(payload([{"sku":"A-1","stock_rolls":None}]))

def test_bad_values_rejected():
    for bad in ("NaN","Infinity","not a number",True,"2.1234"):
        with pytest.raises(ValueError):
            mod._validate(payload([{"sku":"A-1","stock_rolls":bad,"stock_meters":None}]))

def test_duplicate_code_rejected():
    with pytest.raises(ValueError,match="Duplicate SKU"):
        mod._validate(payload([
            {"sku":"A-1","stock_rolls":None,"stock_meters":None},
            {"sku":"a-1","stock_rolls":"0","stock_meters":"0"},
        ]))
