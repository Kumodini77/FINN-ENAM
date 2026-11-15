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
    resolved = resolve_company("COALINDIA")
    assert resolved.is_seed_portfolio is False


def test_unseeded_valid_ticker_resolves_via_the_verifier():
    def _pnb_verifier(_ticker):
        return {
            "name": "Punjab National Bank",
            "exchange": "NSE",
            "sector": "Banking",
            "yfinance_symbol": "PNB.NS",
        }

    resolved = resolve_company("PNB", verify=_pnb_verifier)
    assert resolved.ticker == "PNB"
    assert resolved.name == "Punjab National Bank"
    assert resolved.exchange == "NSE"
    assert resolved.yfinance_symbol == "PNB.NS"
    assert resolved.is_seed_portfolio is False  # never silently enrolled in the portfolio


def test_unverifiable_ticker_raises_company_lookup_error():
    def _failing_verifier(_ticker):
        raise CompanyLookupError("not a real ticker")

    with pytest.raises(CompanyLookupError):
        resolve_company("ZZZZINVALID", verify=_failing_verifier)


def test_ticker_variations_resolve_identically_seeded():
    """Case/whitespace variants of a seeded ticker must resolve to the exact same
    normalized ticker - no duplicate/mismatched registration path."""
    tickers = {resolve_company(v).ticker for v in ["RELIANCE", "reliance", " RELIANCE", "RELIANCE ", " reliance "]}
    assert tickers == {"RELIANCE"}


def test_ticker_variations_resolve_identically_unseeded():
    def _pnb_verifier(_ticker):
        return {"name": "Punjab National Bank", "exchange": "NSE", "sector": None, "yfinance_symbol": "PNB.NS"}

    tickers = {resolve_company(v, verify=_pnb_verifier).ticker for v in ["PNB", "pnb", " PNB ", "Pnb"]}
    assert tickers == {"PNB"}


def test_resolving_an_unseeded_ticker_never_mutates_the_static_registries():
    portfolio_before = list(PORTFOLIO)
    ad_hoc_before = list(AD_HOC_RESEARCH)

    def _pnb_verifier(_ticker):
        return {"name": "Punjab National Bank", "exchange": "NSE", "sector": None, "yfinance_symbol": "PNB.NS"}

    resolve_company("PNB", verify=_pnb_verifier)

    assert PORTFOLIO == portfolio_before
    assert AD_HOC_RESEARCH == ad_hoc_before
