from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import CompanyLookupError
from app.repositories import company_lookup
from tests.fakes.fake_supabase import FakeSupabaseClient


@pytest.fixture(autouse=True)
def _reset_cache():
    company_lookup.invalidate_cache()
    yield
    company_lookup.invalidate_cache()


def _client_with_companies(rows: list[dict]) -> FakeSupabaseClient:
    client = FakeSupabaseClient()
    client.tables["companies"] = [dict(r) for r in rows]
    return client


def _mock_yfinance(info: dict):
    mock_ticker = MagicMock()
    mock_ticker.info = info
    return patch("yfinance.Ticker", return_value=mock_ticker)


# --- cache hit / miss -------------------------------------------------------


def test_cache_hit_does_not_requery_the_database():
    client = _client_with_companies([{"id": "c1", "ticker": "RELIANCE"}])
    with patch.object(company_lookup, "get_supabase_client", return_value=client):
        assert company_lookup.get_company_id("RELIANCE") == "c1"
        # If a second call re-queried, this would make the row disappear.
        client.tables["companies"] = []
        assert company_lookup.get_company_id("RELIANCE") == "c1"


def test_cache_miss_for_unregistered_ticker_returns_none_without_registering():
    client = _client_with_companies([])
    with patch.object(company_lookup, "get_supabase_client", return_value=client):
        assert company_lookup.get_company_id("NOTSEEDED") is None
        assert client.tables["companies"] == []


def test_reverse_lookup_id_to_ticker():
    client = _client_with_companies([{"id": "c1", "ticker": "RELIANCE"}])
    with patch.object(company_lookup, "get_supabase_client", return_value=client):
        assert company_lookup.get_ticker("c1") == "RELIANCE"


def test_newly_added_company_is_visible_without_needing_invalidation():
    """There is no negative caching: a ticker that was never found before always
    triggers a fresh read, so a company registered by another process becomes
    visible on the very next lookup, with no stale "not found" ever cached."""
    client = _client_with_companies([{"id": "c1", "ticker": "RELIANCE"}])
    with patch.object(company_lookup, "get_supabase_client", return_value=client):
        assert company_lookup.get_company_id("TCS") is None
        client.tables["companies"].append({"id": "c2", "ticker": "TCS"})
        assert company_lookup.get_company_id("TCS") == "c2"


def test_invalidate_cache_clears_a_previously_resolved_entry():
    client = _client_with_companies([{"id": "c1", "ticker": "RELIANCE"}])
    with patch.object(company_lookup, "get_supabase_client", return_value=client):
        assert company_lookup.get_company_id("RELIANCE") == "c1"
        client.tables["companies"] = []  # simulate the row disappearing live
        assert company_lookup.get_company_id("RELIANCE") == "c1"  # still cached
        company_lookup.invalidate_cache()
        assert company_lookup.get_company_id("RELIANCE") is None  # now re-reads


# --- unknown-ticker registration path --------------------------------------


def test_unknown_valid_ticker_is_verified_and_registered():
    client = _client_with_companies([])
    with (
        patch.object(company_lookup, "get_supabase_client", return_value=client),
        _mock_yfinance({"quoteType": "EQUITY", "longName": "Wipro Limited", "exchange": "NSI", "sector": "Technology"}),
    ):
        company_id = company_lookup.get_or_register_company_id("WIPRO")
        assert company_id is not None
        rows = client.tables["companies"]
        assert len(rows) == 1
        assert rows[0]["ticker"] == "WIPRO"
        assert rows[0]["name"] == "Wipro Limited"
        assert rows[0]["exchange"] == "NSE"  # normalized from yfinance's "NSI"
        assert rows[0]["sector"] == "Technology"
        assert rows[0]["is_seed_portfolio"] is False


def test_already_registered_ticker_is_not_re_verified_or_duplicated():
    client = _client_with_companies([{"id": "existing-id", "ticker": "WIPRO"}])
    with (
        patch.object(company_lookup, "get_supabase_client", return_value=client),
        _mock_yfinance({}) as mock_yf,
    ):
        company_id = company_lookup.get_or_register_company_id("WIPRO")
        assert company_id == "existing-id"
        assert len(client.tables["companies"]) == 1
        mock_yf.assert_not_called()  # already known -> no metadata lookup needed


def test_invalid_ticker_is_rejected_and_never_registered():
    client = _client_with_companies([])
    # The real, observed yfinance shape for an invalid/delisted ticker: a near-empty
    # info dict with no longName/quoteType (confirmed live against "ZZZZINVALID.NS").
    with (
        patch.object(company_lookup, "get_supabase_client", return_value=client),
        _mock_yfinance({"trailingPegRatio": None}),
    ):
        with pytest.raises(CompanyLookupError):
            company_lookup.get_or_register_company_id("ZZZZINVALID")
        assert client.tables["companies"] == []


def test_non_equity_quote_type_is_rejected():
    client = _client_with_companies([])
    with (
        patch.object(company_lookup, "get_supabase_client", return_value=client),
        _mock_yfinance({"quoteType": "ETF", "longName": "Some Fund", "exchange": "NSI"}),
    ):
        with pytest.raises(CompanyLookupError):
            company_lookup.get_or_register_company_id("SOMEEFT")
        assert client.tables["companies"] == []


def test_missing_company_name_is_rejected_rather_than_guessed():
    client = _client_with_companies([])
    with (
        patch.object(company_lookup, "get_supabase_client", return_value=client),
        _mock_yfinance({"quoteType": "EQUITY", "exchange": "NSI"}),  # no longName/shortName
    ):
        with pytest.raises(CompanyLookupError):
            company_lookup.get_or_register_company_id("NONAME")
        assert client.tables["companies"] == []


def test_unrecognized_exchange_code_is_rejected_rather_than_guessed():
    client = _client_with_companies([])
    with (
        patch.object(company_lookup, "get_supabase_client", return_value=client),
        _mock_yfinance({"quoteType": "EQUITY", "longName": "Foo Corp", "exchange": "NYQ"}),
    ):
        with pytest.raises(CompanyLookupError):
            company_lookup.get_or_register_company_id("FOO")
        assert client.tables["companies"] == []


def test_yfinance_failure_raises_lookup_error_not_a_fabricated_row():
    client = _client_with_companies([])
    with (
        patch.object(company_lookup, "get_supabase_client", return_value=client),
        patch("yfinance.Ticker", side_effect=RuntimeError("network down")),
    ):
        with pytest.raises(CompanyLookupError):
            company_lookup.get_or_register_company_id("ANYTHING")
        assert client.tables["companies"] == []
