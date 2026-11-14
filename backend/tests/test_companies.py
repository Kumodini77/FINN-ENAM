from fastapi.testclient import TestClient

from app.core.companies import ALL_SEED_COMPANIES, PORTFOLIO, get_seed_company, to_yfinance_symbol
from app.main import app

client = TestClient(app)


def test_portfolio_has_15_companies():
    assert len(PORTFOLIO) == 15


def test_ad_hoc_plus_portfolio_totals_19():
    assert len(ALL_SEED_COMPANIES) == 19


def test_no_duplicate_tickers():
    tickers = [c.ticker for c in ALL_SEED_COMPANIES]
    assert len(tickers) == len(set(tickers))


def test_get_seed_company_known_ticker():
    c = get_seed_company("reliance")  # case-insensitive
    assert c is not None
    assert c.ticker == "RELIANCE"
    assert c.yfinance_symbol == "RELIANCE.NS"


def test_get_seed_company_unknown_ticker_returns_none():
    assert get_seed_company("NOTREAL") is None


def test_to_yfinance_symbol_generalizes_beyond_seed_list():
    # This is the core "must generalize to any NSE ticker" requirement.
    assert to_yfinance_symbol("WIPRO") == "WIPRO.NS"
    assert to_yfinance_symbol("SOMECODE", exchange="BSE") == "SOMECODE.BO"


def test_companies_endpoint_returns_full_list():
    resp = client.get("/api/companies")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 19
    assert len(body["companies"]) == 19


def test_companies_endpoint_portfolio_only_filter():
    resp = client.get("/api/companies?portfolio_only=true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 15
    assert all(c["is_seed_portfolio"] for c in body["companies"])
