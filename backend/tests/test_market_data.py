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


def test_market_data_endpoint_handles_invalid_ticker_without_500():
    resp = client.get("/api/market-data/THISISNOTAREALTICKERXYZ")
    assert resp.status_code == 200  # a handled "unavailable" result, not a server error
    body = resp.json()
    assert body["data_available"] is False
    assert body["error"]
