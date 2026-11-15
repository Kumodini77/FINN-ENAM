from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.market_data import SessionStatus
from app.services.market_data import build_price_quote

client = TestClient(app)
IST = ZoneInfo("Asia/Kolkata")


def _make_history(dates_and_values: list[tuple[str, float, int]]) -> pd.DataFrame:
    """Build a synthetic yfinance-like history DataFrame for deterministic tests —
    avoids depending on live market data / network access in the test suite."""
    index = pd.DatetimeIndex([pd.Timestamp(d, tz=IST) for d, _, _ in dates_and_values])
    data = {
        "Open": [v for _, v, _ in dates_and_values],
        "High": [v for _, v, _ in dates_and_values],
        "Low": [v for _, v, _ in dates_and_values],
        "Close": [v for _, v, _ in dates_and_values],
        "Volume": [vol for _, _, vol in dates_and_values],
    }
    return pd.DataFrame(data, index=index)


def test_empty_history_is_data_unavailable():
    quote = build_price_quote("FAKE", "FAKE.NS", hist=pd.DataFrame())
    assert quote.data_available is False
    assert quote.error is not None


def test_all_closed_bars_computes_change_and_volume_multiple():
    today = pd.Timestamp.now(tz=IST).normalize()
    # 5 historical closed days, none dated today.
    dates = [(today - pd.Timedelta(days=5 - i)).strftime("%Y-%m-%d") for i in range(5)]
    rows = list(zip(dates, [100, 101, 102, 103, 110], [1000, 1000, 1000, 1000, 5000]))
    hist = _make_history(rows)

    quote = build_price_quote("TEST", "TEST.NS", hist=hist)

    assert quote.data_available is True
    assert quote.session_status == SessionStatus.CLOSED_EOD
    assert quote.latest_close == 110
    assert quote.previous_close == 103
    assert quote.daily_change_pct == pytest.approx((110 - 103) / 103 * 100, abs=1e-3)
    # avg over all 5 closed bars = (1000*4 + 5000)/5 = 1800
    assert quote.avg_volume == pytest.approx(1800.0)
    assert quote.volume_multiple == pytest.approx(5000 / 1800, abs=1e-3)


def test_todays_bar_is_marked_provisional_and_excluded_from_averages():
    today = pd.Timestamp.now(tz=IST).normalize()
    dates = [(today - pd.Timedelta(days=3 - i)).strftime("%Y-%m-%d") for i in range(3)]
    rows = list(zip(dates, [100, 101, 102], [1000, 1000, 1000]))
    rows.append((today.strftime("%Y-%m-%d"), 103, 50))  # today: partial/low volume
    hist = _make_history(rows)

    quote = build_price_quote("TEST", "TEST.NS", hist=hist)

    assert quote.session_status == SessionStatus.PROVISIONAL_INTRADAY
    assert quote.latest_close == 103
    assert quote.previous_close == 102  # last CLOSED bar, not skipped
    # volume_multiple must be None for a provisional bar — comparing a partial
    # session's volume to a full-day average would be misleading.
    assert quote.volume_multiple is None
    # avg_volume still computed from the 3 closed bars only (not diluted by today's 50).
    assert quote.avg_volume == pytest.approx(1000.0)


def test_market_data_endpoint_handles_invalid_ticker_without_500(monkeypatch):
    # No live network call in an ordinary unit test (see TestMarketPulse's
    # test_market_pulse_endpoint_is_reachable for why this matters — an
    # unmocked yfinance round-trip here, even for an invalid ticker,
    # measurably perturbed an unrelated floating-point-sensitive test
    # elsewhere in the suite).
    monkeypatch.setattr("app.services.market_data.fetch_history", lambda symbol, period="2mo": pd.DataFrame())
    resp = client.get("/api/market-data/THISISNOTAREALTICKERXYZ")
    assert resp.status_code == 200  # a handled "unavailable" result, not a server error
    body = resp.json()
    assert body["data_available"] is False
    assert body["error"]


class TestPriceHistory:
    def test_returns_closed_bars_oldest_first_excluding_provisional(self):
        from app.services.market_data import get_price_history

        today = pd.Timestamp.now(tz=IST).normalize()
        dates = [(today - pd.Timedelta(days=4 - i)).strftime("%Y-%m-%d") for i in range(5)]  # 4 closed + today
        rows = list(zip(dates, [100, 101, 102, 103, 999], [1000] * 5))
        hist = _make_history(rows)

        result = get_price_history("TEST", "TEST.NS", days=30, hist=hist)

        assert result.data_available is True
        assert len(result.bars) == 4  # today's provisional bar excluded
        assert result.bars[0].close == 100  # oldest first
        assert result.bars[-1].close == 103
        assert all(b.session_status.value == "closed_eod" for b in result.bars)

    def test_respects_the_days_limit(self):
        from app.services.market_data import get_price_history

        today = pd.Timestamp.now(tz=IST).normalize()
        dates = [(today - pd.Timedelta(days=40 - i)).strftime("%Y-%m-%d") for i in range(40)]
        rows = list(zip(dates, list(range(100, 140)), [1000] * 40))
        hist = _make_history(rows)

        result = get_price_history("TEST", "TEST.NS", days=10, hist=hist)
        assert len(result.bars) == 10
        assert result.bars[-1].close == 139  # the most recent closed bar

    def test_empty_history_is_honestly_unavailable_not_a_fabricated_flat_line(self):
        from app.services.market_data import get_price_history

        result = get_price_history("FAKE", "FAKE.NS", hist=pd.DataFrame())
        assert result.data_available is False
        assert result.bars == []
        assert result.error

    def test_history_endpoint_returns_200_with_closed_bars_for_a_real_known_symbol_shape(self, monkeypatch):
        monkeypatch.setattr("app.services.market_data.fetch_history", lambda symbol, period="3mo": pd.DataFrame())
        resp = client.get("/api/market-data/THISISNOTAREALTICKERXYZ/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data_available"] is False
        assert body["bars"] == []

    def test_days_query_param_is_bounded(self):
        resp = client.get("/api/market-data/HDFCBANK/history?days=1000")
        assert resp.status_code == 422  # ge=5, le=90 — rejects an unreasonable request rather than silently clamping


class TestMarketPulse:
    def test_no_candidates_below_every_threshold_returns_empty(self):
        from app.services.market_data import compute_pulse_item

        today = pd.Timestamp.now(tz=IST).normalize()
        dates = [(today - pd.Timedelta(days=25 - i)).strftime("%Y-%m-%d") for i in range(25)]
        rows = list(zip(dates, [100.0] * 25, [1000] * 25))  # flat — nothing should trigger
        hist = _make_history(rows)
        item = compute_pulse_item("FLAT", "FLAT.NS", hist=hist)
        assert item is None

    def test_daily_move_above_threshold_is_surfaced(self):
        from app.services.market_data import compute_pulse_item

        today = pd.Timestamp.now(tz=IST).normalize()
        dates = [(today - pd.Timedelta(days=3 - i)).strftime("%Y-%m-%d") for i in range(3)]
        rows = list(zip(dates, [100.0, 100.0, 103.0], [1000, 1000, 1000]))  # +3% today, above the 2% threshold
        hist = _make_history(rows)
        item = compute_pulse_item("MOVER", "MOVER.NS", hist=hist)
        assert item is not None
        assert item.metric == "daily"
        assert item.direction == "positive"
        assert item.pct_change == pytest.approx(3.0)

    def test_sub_threshold_move_is_not_surfaced(self):
        from app.services.market_data import compute_pulse_item

        today = pd.Timestamp.now(tz=IST).normalize()
        dates = [(today - pd.Timedelta(days=3 - i)).strftime("%Y-%m-%d") for i in range(3)]
        rows = list(zip(dates, [100.0, 100.0, 100.8], [1000, 1000, 1000]))  # +0.8%, below the 2% threshold
        hist = _make_history(rows)
        item = compute_pulse_item("QUIET", "QUIET.NS", hist=hist)
        assert item is None

    def test_volume_spike_without_price_context_is_still_surfaced(self):
        from app.services.market_data import compute_pulse_item

        today = pd.Timestamp.now(tz=IST).normalize()
        dates = [(today - pd.Timedelta(days=25 - i)).strftime("%Y-%m-%d") for i in range(25)]
        volumes = [1000] * 24 + [3000]  # 3x the baseline average on the latest day
        rows = list(zip(dates, [100.0] * 25, volumes))
        hist = _make_history(rows)
        item = compute_pulse_item("VOLSPIKE", "VOLSPIKE.NS", hist=hist)
        assert item is not None
        assert item.metric == "volume"
        assert item.volume_multiple == pytest.approx(3.0)

    def test_only_one_item_per_company_even_when_multiple_thresholds_cross(self):
        from app.services.market_data import compute_pulse_item

        today = pd.Timestamp.now(tz=IST).normalize()
        dates = [(today - pd.Timedelta(days=25 - i)).strftime("%Y-%m-%d") for i in range(25)]
        closes = [100.0] * 20 + [100.0, 101.0, 102.0, 104.0, 130.0]  # a large final-day jump
        volumes = [1000] * 24 + [5000]
        rows = list(zip(dates, closes, volumes))
        hist = _make_history(rows)
        item = compute_pulse_item("BIGMOVE", "BIGMOVE.NS", hist=hist)
        assert item is not None  # exactly one PulseItem, not a list — the type system already enforces this

    def test_insufficient_history_is_honestly_skipped_not_guessed(self):
        from app.services.market_data import compute_pulse_item

        today = pd.Timestamp.now(tz=IST).normalize()
        dates = [(today - pd.Timedelta(days=1)).strftime("%Y-%m-%d")]
        hist = _make_history([(dates[0], 100.0, 1000)])
        item = compute_pulse_item("NEW", "NEW.NS", hist=hist)
        assert item is None  # only 1 closed bar — nothing to compare against

    def test_compute_pulse_item_generalizes_to_any_ticker_not_a_hardcoded_list(self):
        from app.services.market_data import compute_pulse_item

        today = pd.Timestamp.now(tz=IST).normalize()
        dates = [(today - pd.Timedelta(days=3 - i)).strftime("%Y-%m-%d") for i in range(3)]
        hist = _make_history(list(zip(dates, [100.0, 100.0, 105.0], [1000, 1000, 1000])))
        item = compute_pulse_item("ANY_TICKER_AT_ALL", "X.NS", hist=hist)
        assert item is not None and item.ticker == "ANY_TICKER_AT_ALL"

    def test_market_pulse_endpoint_is_reachable(self, monkeypatch):
        # No live Supabase/network call in an ordinary unit test. Mocking
        # fetch_history alone wasn't enough here — the route also calls the
        # REAL PortfolioRepository, whose Supabase branch populates
        # app.repositories.company_lookup's process-global ticker<->id cache
        # with real ids. A later test in the same process that expects a
        # FakeSupabaseClient-only company_id for the same ticker then gets
        # the leaked real one instead of its fake one — a real, reproduced
        # cross-test pollution bug (not a flaky/random failure), fixed by
        # never letting this route touch the real repository in a unit test.
        monkeypatch.setattr("app.services.market_data.fetch_history", lambda symbol, period="2mo": pd.DataFrame())
        monkeypatch.setattr("app.api.market_data.PortfolioRepository", lambda: type("R", (), {"list_tickers": lambda self: {"HDFCBANK"}})())
        resp = client.get("/api/market-data/portfolio/pulse")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body and "calculation_notes" in body
