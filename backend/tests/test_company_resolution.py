"""Unit tests for the shared resolver (app/services/company_resolution.py) used by
both announcement import and financial metric import, so a ticker outside the 15+4
seed registry can still be supported when it's a real, verifiable NSE equity."""

import pytest

from app.core.companies import PORTFOLIO, AD_HOC_RESEARCH
from app.core.exceptions import CompanyLookupError
from app.services.company_resolution import resolve_company


def test_seeded_portfolio_ticker_resolves_without_calling_the_verifier():
    calls = []
    resolved = resolve_company("RELIANCE", verify=lambda t: calls.append(t))
    assert resolved.ticker == "RELIANCE"
    assert resolved.is_seed_portfolio is True
    assert calls == []  # never needed to verify - it's already seeded


def test_seeded_ad_hoc_ticker_resolves_as_non_portfolio():
    resolved = resolve_company("TRENT")
    assert resolved.is_seed_portfolio is False


def test_unseeded_valid_ticker_resolves_via_the_verifier():
    def _wipro_verifier(_ticker):
        return {
            "name": "Wipro Limited",
            "exchange": "NSE",
            "sector": "Technology",
            "yfinance_symbol": "WIPRO.NS",
        }

    resolved = resolve_company("WIPRO", verify=_wipro_verifier)
    assert resolved.ticker == "WIPRO"
    assert resolved.name == "Wipro Limited"
    assert resolved.exchange == "NSE"
    assert resolved.yfinance_symbol == "WIPRO.NS"
    assert resolved.is_seed_portfolio is False  # never silently enrolled in the portfolio


def test_unverifiable_ticker_raises_company_lookup_error():
    def _failing_verifier(_ticker):
        raise CompanyLookupError("not a real ticker")

    with pytest.raises(CompanyLookupError):
        resolve_company("ZZZZINVALID", verify=_failing_verifier)


def test_resolving_an_unseeded_ticker_never_mutates_the_static_registries():
    portfolio_before = list(PORTFOLIO)
    ad_hoc_before = list(AD_HOC_RESEARCH)

    def _wipro_verifier(_ticker):
        return {"name": "Wipro Limited", "exchange": "NSE", "sector": None, "yfinance_symbol": "WIPRO.NS"}

    resolve_company("WIPRO", verify=_wipro_verifier)

    assert PORTFOLIO == portfolio_before
    assert AD_HOC_RESEARCH == ad_hoc_before
