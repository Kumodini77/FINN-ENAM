"""Portfolio membership endpoints - separate from /api/companies (the full
registry, read-only). This is the API that makes "adding/removing a portfolio
company must not require code changes" real: it mutates PortfolioRepository's
stored data, not app.core.companies' Python constant.
"""

from fastapi import APIRouter

from app.core.exceptions import CompanyNotFoundError
from app.repositories.portfolio import PortfolioRepository
from app.schemas.portfolio import PortfolioAddRequest, PortfolioCompanyOut, PortfolioListResponse

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioListResponse)
def list_portfolio() -> PortfolioListResponse:
    companies = PortfolioRepository().list_companies()
    return PortfolioListResponse(
        companies=[PortfolioCompanyOut(**c) for c in companies], count=len(companies)
    )


@router.post("", response_model=PortfolioCompanyOut, status_code=201)
def add_to_portfolio(payload: PortfolioAddRequest) -> PortfolioCompanyOut:
    # CompanyLookupError (422) propagates to the global FinnError handler as-is -
    # an invalid/unverifiable ticker is never silently added.
    resolved = PortfolioRepository().add_ticker(payload.ticker)
    return PortfolioCompanyOut(ticker=resolved.ticker, name=resolved.name, exchange=resolved.exchange, sector=resolved.sector)


@router.delete("/{ticker}", status_code=204)
def remove_from_portfolio(ticker: str) -> None:
    removed = PortfolioRepository().remove_ticker(ticker)
    if not removed:
        raise CompanyNotFoundError(f"'{ticker.strip().upper()}' is not currently in the portfolio.")
