"""Verified investor-relations seed URLs — DATA, not logic (same category as
app.core.companies' ticker/yfinance_symbol seeds), used only by
IRWebsiteSourceAdapter to know where to start crawling a company's own site.

Deliberately INCOMPLETE: populated only with URLs actually confirmed reachable
during Phase 12B's audit, not guessed or filled in for every portfolio ticker.
A ticker with no entry here simply means the IR-website adapter has nothing to
crawl for that company yet (it reports this honestly — see
IRWebsiteSourceAdapter.check — rather than skipping the gap silently). Adding a
verified URL for another company is a pure data change, requiring no code change
to the adapter itself — this is what "generalizes, never hardcoded" means for a
source that fundamentally needs a starting point.
"""

INVESTOR_RELATIONS_URLS: dict[str, str] = {
    # Confirmed reachable (HTTP 200, title matches company name) during this
    # phase's audit. Not re-verified on every app startup — see
    # FINN_DOCUMENT_COVERAGE.md for the verification date.
    "HDFCBANK": "https://www.hdfcbank.com/personal/about-us/investor-relations",
}


def get_investor_relations_url(ticker: str) -> str | None:
    return INVESTOR_RELATIONS_URLS.get(ticker.strip().upper())


__all__ = ["INVESTOR_RELATIONS_URLS", "get_investor_relations_url"]
