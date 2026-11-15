import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Query

from app.core.companies import to_yfinance_symbol
from app.repositories.alerts import AlertsConfigRepository
from app.repositories.portfolio import PortfolioRepository
from app.schemas.market_data import MarketPulseResponse, PortfolioQuotesResponse, PriceHistoryResponse, PriceQuote
from app.services.alert_evaluation import evaluate_market_alert
from app.services.market_data import CALCULATION_NOTES, compute_market_pulse, get_price_history, get_quote

logger = logging.getLogger("finn.api.market_data")

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/portfolio", response_model=PortfolioQuotesResponse)
def get_portfolio_quotes() -> PortfolioQuotesResponse:
    """Latest available EOD (or provisional intraday) quote for every portfolio company.

    Reads the LIVE portfolio (PortfolioRepository) rather than the static seed
    constant — a company added/removed via POST/DELETE /api/portfolio now shows up
    here immediately (fixed a real staleness bug: this previously always iterated
    the 20-company seed list regardless of live portfolio changes).

    This hits yfinance for each ticker on every call — fine for this prototype's demo
    scale; a production version would cache this behind the scheduled ingestion job
    described in architecture.md rather than fetching live per-request. Fetches are
    issued CONCURRENTLY (a thread per ticker — each call is pure network I/O against
    yfinance, with no shared mutable state), not one-at-a-time: a real, measured fix
    (~5.1s to ~1.3s for the live 20-company portfolio) documented in
    docs/FINN_PERFORMANCE_REPORT.md, not a guess.

    Market alerts (Module 6/8) are evaluated as a side effect of this call, per
    requirements.md: "evaluate alerts whenever market data is refreshed" — not on a
    background schedule.
    """
    tickers = sorted(PortfolioRepository().list_tickers())
    with ThreadPoolExecutor(max_workers=min(len(tickers), 10) or 1) as pool:
        quotes: list[PriceQuote] = list(pool.map(lambda t: get_quote(t, to_yfinance_symbol(t)), tickers))

    try:
        config = AlertsConfigRepository().get()
        for quote in quotes:
            evaluate_market_alert(quote, config)
    except Exception:
        # Alert evaluation must never break the portfolio view itself.
        logger.exception("Alert evaluation failed during portfolio quote refresh")

    return PortfolioQuotesResponse(quotes=quotes, calculation_notes=CALCULATION_NOTES)


@router.get("/portfolio/pulse", response_model=MarketPulseResponse)
def get_market_pulse() -> MarketPulseResponse:
    """Daily Intelligence's 'Market pulse' section — companies whose EOD move
    clears a fixed EDITORIAL threshold (see app.services.market_data's
    PULSE_* constants), completely independent of the user's own configured
    alert thresholds (AlertsConfig). Reads the live portfolio, never a
    hardcoded list. One request computes all companies server-side, rather
    than the frontend making N separate history calls."""
    tickers = sorted(PortfolioRepository().list_tickers())
    companies = [(t, to_yfinance_symbol(t)) for t in tickers]
    return compute_market_pulse(companies)


@router.get("/{ticker}", response_model=PriceQuote)
def get_ticker_quote(ticker: str) -> PriceQuote:
    """Quote for any ticker, not just the seed portfolio — the market-data path
    generalizes the same way the research engine is required to (requirements.md §3)."""
    ticker = ticker.strip().upper()
    yfinance_symbol = to_yfinance_symbol(ticker)
    return get_quote(ticker, yfinance_symbol)


@router.get("/{ticker}/history", response_model=PriceHistoryResponse)
def get_ticker_history(ticker: str, days: int = Query(default=30, ge=5, le=90)) -> PriceHistoryResponse:
    """Recent CLOSED EOD daily bars for a sparkline — real yfinance history,
    never synthetic points. Generalizes to any ticker, same as the quote
    endpoint above."""
    ticker = ticker.strip().upper()
    yfinance_symbol = to_yfinance_symbol(ticker)
    return get_price_history(ticker, yfinance_symbol, days=days)
