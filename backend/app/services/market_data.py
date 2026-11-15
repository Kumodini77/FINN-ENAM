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
from app.schemas.market_data import DailyBar, MarketPulseResponse, PriceQuote, PriceHistoryResponse, PulseItem, SessionStatus

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


def get_price_history(ticker: str, yfinance_symbol: str, days: int = 30, hist: pd.DataFrame | None = None) -> PriceHistoryResponse:
    """CLOSED EOD daily bars for a sparkline/small chart — the last `days`
    closed trading sessions, oldest first. Reuses fetch_history (the exact
    same real yfinance call build_price_quote already uses) rather than a
    second data path; never fabricates a bar for a day with no real data
    (a provisional/intraday "today" row is excluded the same way
    build_price_quote excludes it from its own averages)."""
    if hist is None:
        hist = fetch_history(yfinance_symbol, period="3mo")

    if hist is None or hist.empty:
        return PriceHistoryResponse(ticker=ticker, data_available=False, error="No data returned by yfinance for this symbol.")

    hist = hist.sort_index()
    today = _today_ist()
    is_today = hist.index.tz_convert(IST).normalize() == today
    closed = hist.loc[~is_today]

    if closed.empty:
        return PriceHistoryResponse(ticker=ticker, data_available=False, error="No closed EOD bars available yet.")

    window = closed.tail(max(days, 1))
    bars = [
        DailyBar(
            trade_date=idx.tz_convert(IST).date(), open=round(float(row["Open"]), 4), high=round(float(row["High"]), 4),
            low=round(float(row["Low"]), 4), close=round(float(row["Close"]), 4), volume=int(row["Volume"]),
            session_status=SessionStatus.CLOSED_EOD,
        )
        for idx, row in window.iterrows()
    ]
    return PriceHistoryResponse(ticker=ticker, data_available=True, bars=bars)


# Editorial thresholds for "Market pulse" (Daily Intelligence) — fixed,
# documented constants, NEVER the user's own configured alert thresholds
# (AlertsConfig.volume_spike_multiple / price_move_pct). A 1.5% move can be
# "interesting enough" to surface here while being well under a user's 3%
# alert threshold — that distinction is the whole point of this function;
# see docs/FINN_DAILY_INTELLIGENCE_UPGRADE.md.
PULSE_DAILY_PCT_THRESHOLD = 2.0
PULSE_FIVE_SESSION_PCT_THRESHOLD = 5.0
PULSE_TWENTY_SESSION_PCT_THRESHOLD = 10.0
PULSE_VOLUME_MULTIPLE_THRESHOLD = 1.5


def _pct_change(latest: float, earlier: float) -> float | None:
    if not earlier:
        return None
    return round((latest - earlier) / earlier * 100, 2)


def compute_pulse_item(ticker: str, yfinance_symbol: str, hist: pd.DataFrame | None = None) -> PulseItem | None:
    """One company's editorial 'is this interesting enough to surface' check —
    never the user's own alert thresholds. Picks at most ONE reason per
    company (the one whose magnitude most exceeds its own threshold, as a
    ratio) so a company never gets duplicate pulse cards. Returns None if
    nothing crosses any threshold, or if there isn't enough real history to
    judge — never fabricates a signal from insufficient data."""
    if hist is None:
        hist = fetch_history(yfinance_symbol, period="2mo")
    if hist is None or hist.empty:
        return None

    hist = hist.sort_index()
    today = _today_ist()
    is_today = hist.index.tz_convert(IST).normalize() == today
    closed = hist.loc[~is_today]
    if len(closed) < 2:
        return None

    closes = closed["Close"].tolist()
    volumes = closed["Volume"].tolist()
    latest_close = float(closes[-1])
    observation_date = closed.index[-1].tz_convert(IST).date()

    candidates: list[tuple[float, PulseItem]] = []  # (severity_ratio, item)

    daily_pct = _pct_change(latest_close, float(closes[-2]))
    if daily_pct is not None and abs(daily_pct) >= PULSE_DAILY_PCT_THRESHOLD:
        candidates.append(
            (
                abs(daily_pct) / PULSE_DAILY_PCT_THRESHOLD,
                PulseItem(
                    ticker=ticker, metric="daily", pct_change=daily_pct, direction="positive" if daily_pct > 0 else "negative",
                    observation_date=observation_date, latest_close=latest_close,
                    note=f"{'Up' if daily_pct > 0 else 'Down'} {abs(daily_pct):.1f}% today.",
                ),
            )
        )

    if len(closes) >= 6:
        five_pct = _pct_change(latest_close, float(closes[-6]))
        if five_pct is not None and abs(five_pct) >= PULSE_FIVE_SESSION_PCT_THRESHOLD:
            candidates.append(
                (
                    abs(five_pct) / PULSE_FIVE_SESSION_PCT_THRESHOLD,
                    PulseItem(
                        ticker=ticker, metric="five_session", pct_change=five_pct, direction="positive" if five_pct > 0 else "negative",
                        observation_date=observation_date, latest_close=latest_close,
                        note=f"{'Up' if five_pct > 0 else 'Down'} {abs(five_pct):.1f}% over the last 5 sessions.",
                    ),
                )
            )

    if len(closes) >= 21:
        twenty_pct = _pct_change(latest_close, float(closes[-21]))
        if twenty_pct is not None and abs(twenty_pct) >= PULSE_TWENTY_SESSION_PCT_THRESHOLD:
            candidates.append(
                (
                    abs(twenty_pct) / PULSE_TWENTY_SESSION_PCT_THRESHOLD,
                    PulseItem(
                        ticker=ticker, metric="twenty_session", pct_change=twenty_pct, direction="positive" if twenty_pct > 0 else "negative",
                        observation_date=observation_date, latest_close=latest_close,
                        note=f"{'Up' if twenty_pct > 0 else 'Down'} {abs(twenty_pct):.1f}% over the last 20 sessions.",
                    ),
                )
            )

    if len(volumes) >= 6:
        baseline_volumes = volumes[-21:-1] if len(volumes) >= 21 else volumes[:-1]
        avg_volume = sum(baseline_volumes) / len(baseline_volumes) if baseline_volumes else 0
        if avg_volume:
            multiple = volumes[-1] / avg_volume
            if multiple >= PULSE_VOLUME_MULTIPLE_THRESHOLD:
                candidates.append(
                    (
                        multiple / PULSE_VOLUME_MULTIPLE_THRESHOLD,
                        PulseItem(
                            ticker=ticker, metric="volume", volume_multiple=round(multiple, 2), direction="positive" if daily_pct and daily_pct > 0 else "negative",
                            observation_date=observation_date, latest_close=latest_close,
                            note=f"Volume {multiple:.1f}× its recent average.",
                        ),
                    )
                )

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


def compute_market_pulse(companies: list[tuple[str, str]]) -> MarketPulseResponse:
    """`companies` is [(ticker, yfinance_symbol), ...] — reads live portfolio
    membership, never a hardcoded ticker list (callers pass that in)."""
    items = [item for ticker, symbol in companies if (item := compute_pulse_item(ticker, symbol)) is not None]
    items.sort(key=lambda i: abs(i.pct_change or i.volume_multiple or 0), reverse=True)
    notes = (
        f"Market pulse surfaces a company when its daily move is >= {PULSE_DAILY_PCT_THRESHOLD}%, its 5-session move is "
        f">= {PULSE_FIVE_SESSION_PCT_THRESHOLD}%, its 20-session move is >= {PULSE_TWENTY_SESSION_PCT_THRESHOLD}%, or its "
        f"volume is >= {PULSE_VOLUME_MULTIPLE_THRESHOLD}x its recent average — fixed editorial thresholds, not your "
        "configured alert thresholds (see Alerts). All figures are EOD, never real-time."
    )
    return MarketPulseResponse(items=items, calculation_notes=notes, as_of=datetime.now(timezone.utc))


CALCULATION_NOTES = (
    "Daily % change compares the two most recent CLOSED end-of-day bars "
    "(latest_close vs. previous_close); it never uses a still-in-progress session's "
    "price as the 'latest' close. Average volume and volume multiple use a rolling "
    f"{get_settings().market_data_eod_window_days}-trading-day window of CLOSED bars only. "
    "While NSE is open, today's bar is labeled 'provisional_intraday' and is shown "
    "separately rather than folded into these calculations, since its volume is a "
    "partial-session snapshot, not a finished day's total."
)
