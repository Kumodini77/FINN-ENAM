from fastapi import APIRouter

from app.core.companies import ALL_SEED_COMPANIES, PORTFOLIO
from app.schemas.company import CompanyListResponse, CompanyOut

router = APIRouter(prefix="/companies", tags=["companies"])


def _to_out(seed) -> CompanyOut:
    return CompanyOut(
        ticker=seed.ticker,
        name=seed.name,
        exchange=seed.exchange,
        sector=seed.sector,
        yfinance_symbol=seed.yfinance_symbol,
        is_seed_portfolio=seed.is_seed_portfolio,
    )


@router.get("", response_model=CompanyListResponse)
def list_companies(portfolio_only: bool = False) -> CompanyListResponse:
    source = PORTFOLIO if portfolio_only else ALL_SEED_COMPANIES
    companies = [_to_out(c) for c in source]
    return CompanyListResponse(companies=companies, count=len(companies))
