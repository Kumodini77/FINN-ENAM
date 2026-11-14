"""Market data service — EOD price/volume via yfinance.

Design notes (from Phase 1 real testing against RELIANCE.NS / HDFCBANK.NS / INFY.NS):

1. yfinance's `history()` includes a row for the CURRENT day even while NSE is still
   trading. That row's volume is a partial-session snapshot (observed ~10x lower than a
   closed day's volume when fetched shortly after market open) — it is NOT a finished
   EOD bar. Treating it as one would make "unusual volume" alerts and daily % change
   numbers misleading. So: a day's bar counts as CLOSED_EOD only if it is strictly
   before today in NSE's own local date (Asia/Kolkata), where "today" is evaluated in
   that same timezone. The latest bar, if it matches today's date, is labeled
   PROVISIONAL_INTRADAY and excluded from averages/comparisons by default.
2. An invalid/delisted ticker returns an EMPTY DataFrame from yfinance (confirmed by
   test), not an exception — handled as a clean "data not available" result rather than
   a 500.
3. Average volume and daily % change are computed only over CLOSED_EOD bars, so a
   mid-session fetch never silently corrupts the baseline.
"""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from app.core.config import get_settings
from app.schemas.market_data import PriceQuote, SessionStatus

logger = logging.getLogger("finn.market_data")

IST = ZoneInfo("Asia/Kolkata")


def _today_ist() -> "pd.Timestamp":
    return pd.Timestamp.now(tz=IST).normalize()


def fetch_history(yfinance_symbol: str, period: str = "2mo") -> pd.DataFrame:
    """Fetch raw EOD history. Returns an empty DataFrame (not an exception) when
    the ticker has no data — this is a real, observed yfinance behavior for
    invalid/delisted symbols, not an edge case we're guessing about."""
    try:
        ticker = yf.Ticker(yfinance_symbol)
        hist = ticker.history(period=period, interval="1d")
        return hist
    except Exception:
        logger.exception("yfinance request failed for %s", yfinance_symbol)
        return pd.DataFrame()


def build_price_quote(ticker: str, yfinance_symbol: str, hist: pd.DataFrame | None = None) -> PriceQuote:
    settings = get_settings()
    fetched_at = datetime.now(timezone.utc)

    if hist is None:
        hist = fetch_history(yfinance_symbol)

    if hist is None or hist.empty:
        return PriceQuote(
            ticker=ticker,
            yfinance_symbol=yfinance_symbol,
            data_available=False,
            fetched_at=fetched_at,
            error="No data returned by yfinance for this symbol (possibly invalid, delisted, or a transient upstream gap).",
        )

    hist = hist.sort_index()
    today = _today_ist()

    # Split into closed EOD bars vs. a possible provisional bar for "today".
    is_today = hist.index.tz_convert(IST).normalize() == today
    closed = hist.loc[~is_today]
    provisional = hist.loc[is_today]

    if closed.empty and provisional.empty:
        return PriceQuote(
            ticker=ticker,
            yfinance_symbol=yfinance_symbol,
            data_available=False,
            fetched_at=fetched_at,
            error="History returned but contained no usable rows.",
        )

    window = settings.market_data_eod_window_days
    closed_window = closed.tail(window)
    avg_volume = float(closed_window["Volume"].mean()) if not closed_window.empty else None

    if not provisional.empty:
        # Market is open / today's bar is not finalized yet.
        latest_row = provisional.iloc[-1]
        as_of_date = provisional.index[-1].tz_convert(IST).date()
        session_status = SessionStatus.PROVISIONAL_INTRADAY
        previous_close = float(closed.iloc[-1]["Close"]) if not closed.empty else None
    else:
        latest_row = closed.iloc[-1]
        as_of_date = closed.index[-1].tz_convert(IST).date()
        session_status = SessionStatus.CLOSED_EOD
        previous_close = float(closed.iloc[-2]["Close"]) if len(closed) >= 2 else None

    latest_close = float(latest_row["Close"])
    latest_volume = int(latest_row["Volume"])

    daily_change_pct = None
    if previous_close:
        daily_change_pct = round((latest_close - previous_close) / previous_close * 100, 4)

    volume_multiple = None
    if session_status == SessionStatus.CLOSED_EOD and avg_volume:
        volume_multiple = round(latest_volume / avg_volume, 4)

    return PriceQuote(
        ticker=ticker,
        yfinance_symbol=yfinance_symbol,
        data_available=True,
        as_of_date=as_of_date,
        session_status=session_status,
        latest_close=round(latest_close, 4),
        previous_close=round(previous_close, 4) if previous_close else None,
        daily_change_pct=daily_change_pct,
        latest_volume=latest_volume,
        avg_volume_window_days=window,
        avg_volume=round(avg_volume, 2) if avg_volume else None,
        volume_multiple=volume_multiple,
        fetched_at=fetched_at,
    )


def get_quote(ticker: str, yfinance_symbol: str) -> PriceQuote:
    return build_price_quote(ticker, yfinance_symbol)


CALCULATION_NOTES = (
    "Daily % change compares the two most recent CLOSED end-of-day bars "
    "(latest_close vs. previous_close); it never uses a still-in-progress session's "
    "price as the 'latest' close. Average volume and volume multiple use a rolling "
    f"{get_settings().market_data_eod_window_days}-trading-day window of CLOSED bars only. "
    "While NSE is open, today's bar is labeled 'provisional_intraday' and is shown "
    "separately rather than folded into these calculations, since its volume is a "
    "partial-session snapshot, not a finished day's total."
)
