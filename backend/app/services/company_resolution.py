"""Shared ticker resolution for every endpoint that accepts a ticker from the user
(announcement import, financial metric import) — one place that decides whether a
company is supported, instead of each caller hardcoding its own allow-list.

Resolution order:
1. The static seed registry (app/core/companies.py) — the 15 portfolio + 4 ad-hoc
   companies this demo was built around. Preserves the portfolio/ad-hoc distinction
   exactly as before: nothing here ever changes PORTFOLIO or AD_HOC_RESEARCH.
2. If not seeded, a real metadata check via yfinance (requirements.md Section 3 —
   "the research engine must generalize to any NSE ticker, not just the chosen
   portfolio"). A company resolved this way is always is_seed_portfolio=False and
   is never added to PORTFOLIO — resolving it for one import does not enroll it in
   anyone's portfolio.

Either step can fail (ticker genuinely doesn't exist, or can't be verified as an
NSE equity) — that failure is CompanyLookupError, which callers map to whatever
HTTP error their existing contract already used (never a fabricated company).
"""

from dataclasses import dataclass
from typing import Callable

from app.core.companies import get_seed_company
from app.core.exceptions import CompanyLookupError


@dataclass(frozen=True)
class ResolvedCompany:
    ticker: str
    name: str
    exchange: str
    sector: str | None
    yfinance_symbol: str
    is_seed_portfolio: bool


def _default_verifier(ticker: str) -> dict:
    from app.repositories.company_lookup import verify_ticker_metadata

    return verify_ticker_metadata(ticker)


def resolve_company(ticker: str, verify: Callable[[str], dict] | None = None) -> ResolvedCompany:
    """Resolves any ticker — seeded or not — to a ResolvedCompany, or raises
    CompanyLookupError if it's neither seeded nor verifiable. `verify` is injectable
    purely for tests, so exercising the unseeded path never requires a real network
    call unless the caller wants one."""
    seed = get_seed_company(ticker)
    if seed is not None:
        return ResolvedCompany(
            ticker=seed.ticker,
            name=seed.name,
            exchange=seed.exchange,
            sector=seed.sector,
            yfinance_symbol=seed.yfinance_symbol,
            is_seed_portfolio=seed.is_seed_portfolio,
        )

    verify = verify or _default_verifier
    metadata = verify(ticker)
    return ResolvedCompany(
        ticker=ticker.upper(),
        name=metadata["name"],
        exchange=metadata["exchange"],
        sector=metadata.get("sector"),
        yfinance_symbol=metadata["yfinance_symbol"],
        is_seed_portfolio=False,
    )


__all__ = ["ResolvedCompany", "resolve_company", "CompanyLookupError"]
