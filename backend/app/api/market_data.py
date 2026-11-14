import logging

from fastapi import APIRouter

from app.core.companies import PORTFOLIO, get_seed_company, to_yfinance_symbol
from app.repositories.alerts import AlertsConfigRepository
from app.schemas.market_data import PortfolioQuotesResponse, PriceQuote
from app.services.alert_evaluation import evaluate_market_alert
from app.services.market_data import CALCULATION_NOTES, get_quote

logger = logging.getLogger("finn.api.market_data")

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/portfolio", response_model=PortfolioQuotesResponse)
def get_portfolio_quotes() -> PortfolioQuotesResponse:
    """Latest available EOD (or provisional intraday) quote for every portfolio company.

    This hits yfinance for each ticker on every call — fine for a prototype's demo
    scale (15 tickers); a production version would cache this behind the scheduled
    ingestion job described in architecture.md rather than fetching live per-request.

    Market alerts (Module 6/8) are evaluated as a side effect of this call, per
    requirements.md: "evaluate alerts whenever market data is refreshed" — not on a
    background schedule.
    """
    quotes: list[PriceQuote] = [get_quote(c.ticker, c.yfinance_symbol) for c in PORTFOLIO]

    try:
        config = AlertsConfigRepository().get()
        for quote in quotes:
            evaluate_market_alert(quote, config)
    except Exception:
        # Alert evaluation must never break the portfolio view itself.
        logger.exception("Alert evaluation failed during portfolio quote refresh")

    return PortfolioQuotesResponse(quotes=quotes, calculation_notes=CALCULATION_NOTES)


@router.get("/{ticker}", response_model=PriceQuote)
def get_ticker_quote(ticker: str) -> PriceQuote:
    """Quote for any ticker, not just the seed portfolio — the market-data path
    generalizes the same way the research engine is required to (requirements.md §3)."""
    yfinance_symbol = to_yfinance_symbol(ticker)
    return get_quote(ticker.upper(), yfinance_symbol)
