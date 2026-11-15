"""Unit tests for app.repositories.portfolio.PortfolioRepository - JSON-fallback
(real logic, isolated storage). Confirms portfolio membership is real, mutable,
stored data - not the static app.core.companies.PORTFOLIO constant - and that
adding/removing requires no code change."""

import pytest

from app.core.companies import PORTFOLIO
from app.core.exceptions import CompanyLookupError
from app.repositories.json_store import JsonListStore
from app.repositories.portfolio import PortfolioRepository


@pytest.fixture
def repo(tmp_path):
    return PortfolioRepository(store=JsonListStore(str(tmp_path), "portfolio.json"))


def _fake_verify(name="Wipro Limited", exchange="NSE", sector="Technology", yfinance_symbol="WIPRO.NS"):
    return lambda ticker: {"name": name, "exchange": exchange, "sector": sector, "yfinance_symbol": yfinance_symbol}


def test_fresh_portfolio_bootstraps_from_the_static_seed_list(repo):
    tickers = repo.list_tickers()
    assert tickers == {c.ticker for c in PORTFOLIO}


def test_adding_an_unseeded_but_valid_ticker_requires_no_code_change(repo):
    repo.list_tickers()  # trigger bootstrap first, like a real first request would
    resolved = repo.add_ticker("WIPRO", verify=_fake_verify())
    assert resolved.ticker == "WIPRO"
    assert "WIPRO" in repo.list_tickers()


def test_adding_an_invalid_ticker_raises_and_does_not_add_it(repo):
    def _failing_verify(_t):
        raise CompanyLookupError("not a real ticker")

    with pytest.raises(CompanyLookupError):
        repo.add_ticker("ZZZZINVALID", verify=_failing_verify)
    assert "ZZZZINVALID" not in repo.list_tickers()


def test_adding_an_already_seeded_ticker_is_idempotent_not_duplicated(repo):
    repo.list_tickers()
    repo.add_ticker("HDFCBANK")  # already in the bootstrap seed list
    rows = repo._store.read_all()
    assert len([r for r in rows if r["ticker"] == "HDFCBANK"]) == 1


def test_removing_a_portfolio_member_returns_true_and_actually_removes_it(repo):
    repo.list_tickers()
    assert repo.remove_ticker("HDFCBANK") is True
    assert "HDFCBANK" not in repo.list_tickers()


def test_removing_a_ticker_not_in_the_portfolio_returns_false(repo):
    repo.list_tickers()
    assert repo.remove_ticker("NOTINPORTFOLIO") is False


def test_removed_ticker_does_not_silently_reappear_on_next_read(repo):
    """The empty-store bootstrap must only ever fire once, on a genuinely empty
    store - removing the last-ever-added item should not look 'empty' and
    re-seed from the static list."""
    repo.list_tickers()
    repo.remove_ticker("HDFCBANK")
    assert "HDFCBANK" not in repo.list_tickers()
    assert "HDFCBANK" not in repo.list_tickers()  # second read, still gone


def test_list_companies_returns_display_metadata_not_just_tickers(repo):
    companies = repo.list_companies()
    assert len(companies) == len(PORTFOLIO)
    hdfc = next(c for c in companies if c["ticker"] == "HDFCBANK")
    assert hdfc["name"] == "HDFC Bank Ltd"
    assert hdfc["exchange"] == "NSE"


def test_ticker_case_and_whitespace_variants_affect_the_same_portfolio_entry(repo):
    repo.list_tickers()
    repo.add_ticker(" wipro ", verify=_fake_verify())
    assert repo.remove_ticker("WIPRO") is True
