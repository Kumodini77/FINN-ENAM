from dataclasses import asdict

from fastapi import APIRouter

from app.core.companies import ALL_SEED_COMPANIES, get_seed_company, to_yfinance_symbol
from app.repositories.portfolio import PortfolioRepository
from app.schemas.company import CompanyListResponse, CompanyOut
from app.schemas.research_readiness import ResearchReadinessOut
from app.services.research_readiness import check_research_readiness

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


def _portfolio_companies_live() -> list[CompanyOut]:
    """Reads the ACTUAL live portfolio (PortfolioRepository — add/remove via
    POST/DELETE /api/portfolio writes here), not the static PORTFOLIO seed
    constant. A row seeded from the constant and a row added later by a user
    both come back correctly; is_seed_portfolio reflects whether this ticker
    was actually part of the original seed list, not whether it's currently
    tracked (every row returned here IS currently tracked, by definition)."""
    rows = PortfolioRepository().list_companies()
    out = []
    for row in rows:
        ticker = row["ticker"]
        seed = get_seed_company(ticker)
        out.append(
            CompanyOut(
                ticker=ticker,
                name=row.get("name") or (seed.name if seed else ticker),
                exchange=row.get("exchange") or (seed.exchange if seed else "NSE"),
                sector=row.get("sector") or (seed.sector if seed else "Unknown"),
                yfinance_symbol=seed.yfinance_symbol if seed else to_yfinance_symbol(ticker),
                is_seed_portfolio=seed.is_seed_portfolio if seed else False,
            )
        )
    return out


@router.get("", response_model=CompanyListResponse)
def list_companies(portfolio_only: bool = False) -> CompanyListResponse:
    companies = _portfolio_companies_live() if portfolio_only else [_to_out(c) for c in ALL_SEED_COMPANIES]
    return CompanyListResponse(companies=companies, count=len(companies))


@router.get("/{ticker}/research-readiness", response_model=ResearchReadinessOut)
def research_readiness(ticker: str) -> ResearchReadinessOut:
    """Reports, for ANY ticker (registered or not, portfolio or ad-hoc), whether
    Pull can actually retrieve from it right now and why/why not - never a gate
    on Pull itself, just an honest status check. See app/services/research_readiness.py
    for the four concepts this keeps explicitly separate."""
    readiness = check_research_readiness(ticker)
    return ResearchReadinessOut(
        ticker=readiness.ticker, company_name=readiness.company_name, is_known_company=readiness.is_known_company,
        is_portfolio_member=readiness.is_portfolio_member, has_retrievable_documents=readiness.has_retrievable_documents,
        documents=[asdict(d) for d in readiness.documents], status=readiness.status, message=readiness.message,
    )
