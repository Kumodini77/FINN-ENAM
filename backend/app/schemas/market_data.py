from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """Whether a given day's bar is a finalized end-of-day record or a partial,
    still-in-progress session. See services/market_data.py for how this is derived —
    yfinance returns a row for "today" even while NSE is still trading, and that row's
    volume is not comparable to a closed day's volume.
    """

    CLOSED_EOD = "closed_eod"
    PROVISIONAL_INTRADAY = "provisional_intraday"


class DailyBar(BaseModel):
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    session_status: SessionStatus


class PriceQuote(BaseModel):
    ticker: str
    yfinance_symbol: str
    data_available: bool
    as_of_date: date | None = None
    session_status: SessionStatus | None = None
    latest_close: float | None = None
    previous_close: float | None = None
    daily_change_pct: float | None = Field(
        default=None,
        description="(latest_close - previous_close) / previous_close * 100, using the two most recent CLOSED EOD bars.",
    )
    latest_volume: int | None = None
    avg_volume_window_days: int | None = None
    avg_volume: float | None = Field(
        default=None, description="Rolling average volume over avg_volume_window_days closed trading days, excluding any provisional bar."
    )
    volume_multiple: float | None = Field(
        default=None, description="latest_volume / avg_volume — only meaningful when latest bar is a closed EOD bar."
    )
    fetched_at: datetime
    error: str | None = Field(default=None, description="Set when data_available is False, explaining why.")


class PortfolioQuotesResponse(BaseModel):
    quotes: list[PriceQuote]
    calculation_notes: str = Field(
        description="Human-readable note on the windows/methodology used, per requirements to document calculations."
    )
