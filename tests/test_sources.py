import pytest

from app.services import find_account_ids, load_account_portfolio, resolve_model_id
from app.sources import load_sources
from app.sources.positions_agent import parse_positions, parse_number

CONFIG = {
    "ticker_asset_class": {"VXUS": "Intl Equity", "BND": "US Bonds"},
    "sec_type_asset_class": {"Annuity": "US Bonds", "Money Market": "Cash"},
    "default_asset_class": "US Equity",
}
HEADER = "Ticker,Cusip,Sec Type,Qty,Custodian Quantity,PM Price,Market Value\n"


@pytest.fixture
def sources():
    return load_sources("config/sources.json")


@pytest.mark.parametrize("raw, expected", [("$1,234.50", 1234.5), ("+12", 12), ("(123)", -123), ("", 0), (None, 0)])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


def test_blank_ticker_uses_cusip():
    text = HEADER + ',12345A678,Annuity,1,,,"$120,000.00"\n'
    [p] = parse_positions(text, "A1", CONFIG)
    assert p.ticker == "12345A678" and p.asset_class == "US Bonds" and p.price == 120_000


def test_missing_price_uses_market_value_over_quantity():
    text = HEADER + 'VTI,922908769,ETF,10,,,"$3,000.00"\n'
    [p] = parse_positions(text, "A1", CONFIG)
    assert p.price == 300 and p.asset_class == "US Equity"


def test_blank_qty_uses_custodian_quantity_and_skips_blank_rows():
    text = HEADER + "SPAXX,,Money Market,,50,$1.00,$50.00\n,,,,,,\nVXUS,,ETF,0,,$65,$0\n"
    positions = parse_positions(text, "A1", CONFIG)
    assert [(p.ticker, p.quantity, p.asset_class) for p in positions] == [("SPAXX", 50, "Cash")]


def test_ticker_override_beats_sec_type():
    text = HEADER + "BND,,ETF,10,,$73,$730\n"
    [p] = parse_positions(text, "A1", CONFIG)
    assert p.asset_class == "US Bonds"


def test_missing_columns_raise():
    with pytest.raises(ValueError, match=r"Not an A360 Positions file; missing columns: \['Qty', 'Cusip'\]"):
        parse_positions("Ticker,Market Value\nVTI,100\n", "A1", CONFIG)


def test_default_a360_file_loads(sources):
    positions = sources["positions"].get_positions("A2001")
    assert {p.ticker for p in positions} >= {"VTI", "SHV", "12345A678"}


def test_resolve_model_id_by_id_or_name(sources):
    s = sources["sales"]
    assert resolve_model_id(s, "Conservative 40/60") == "CON-40-60"
    assert resolve_model_id(s, "mod-60-40") == "MOD-60-40"
    with pytest.raises(KeyError):
        resolve_model_id(s, "nope")


def test_find_account_ids(sources):
    assert find_account_ids(sources, "smith") == ["A1001"]
    assert set(find_account_ids(sources, "all")) == {"A1001", "A1002", "A1003", "A2001"}
    assert find_account_ids(sources, "nobody") == []


def test_load_account_portfolio_weights_sum_to_one(sources):
    pf = load_account_portfolio(sources, "A1001")
    assert sum(pf.current_weights.values()) == pytest.approx(1.0)
    assert pf.model.model_id == "MOD-60-40"
    with pytest.raises(KeyError):
        load_account_portfolio(sources, "ZZZ")
