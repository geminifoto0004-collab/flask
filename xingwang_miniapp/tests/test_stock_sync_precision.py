"""Access numeric totals: binary-float tails are rounded to TiDB DECIMAL(18,3)."""
from decimal import Decimal
import pytest
from xingwang_miniapp import stock_sync_api as mod

def payload(rows):
    return {"schema":"xw-stock-v1","complete_snapshot":True,
            "expected_count":len(rows),"rows":rows}

def test_float_tails_round_to_millimeter():
    rows=[{"sku":"12-225-1","stock_rolls":"10.000000000001","stock_meters":"12.300000000004"},
          {"sku":"12-225-2","stock_rolls":"0","stock_meters":"-9.999999999999"},
          {"sku":"12-225-3","stock_rolls":None,"stock_meters":None},
          {"sku":"12-225-4","stock_rolls":"1.2345","stock_meters":"-1.2345"}]
    data=mod._validate(payload(rows))
    assert data["12-225-1"] == ("12-225",Decimal("10.000"),Decimal("12.300"))
    assert data["12-225-2"] == ("12-225",Decimal("0.000"),Decimal("-10.000"))
    assert data["12-225-3"] == ("12-225",None,None)
    assert data["12-225-4"] == ("12-225",Decimal("1.235"),Decimal("-1.235"))

def test_invalid_data_remains_rejected():
    for bad in ("NaN","Infinity","INVALID",True):
        with pytest.raises(ValueError):
            mod._validate(payload([{"sku":"A-1","stock_rolls":bad,"stock_meters":None}]))
    with pytest.raises(ValueError, match="Missing stock quantity field"):
        mod._validate(payload([{"sku":"A-1","stock_rolls":"1"}]))
    with pytest.raises(ValueError, match="Out-of-range"):
        mod._validate(payload([{"sku":"A-1","stock_rolls":"1000000000000000","stock_meters":0}]))
