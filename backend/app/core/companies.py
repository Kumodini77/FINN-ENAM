"""Static seed registry for the demo portfolio + ad-hoc research companies.

This is DATA, not logic: every company here is just an entry describing name,
ticker, exchange and sector. No company-specific research/parsing/extraction
logic exists anywhere in the codebase — the Pull/Push engines must work for
any NSE ticker, per requirements.md §3. This list only seeds what the demo
portfolio and ad-hoc research set contain; it never gates what a research
request can be made against (see api/research.py).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CompanySeed:
    ticker: str  # NSE symbol, e.g. "RELIANCE"
    name: str
    exchange: str  # "NSE"
    sector: str
    yfinance_symbol: str  # e.g. "RELIANCE.NS"
    is_seed_portfolio: bool


# Default/bootstrap seed only (app/repositories/portfolio.py's PortfolioRepository
# seeds real, mutable portfolio-membership data from this list the FIRST time it's
# read and finds nothing stored yet - after that, add/remove operate on the real
# `portfolio` table (Supabase) / portfolio.json (fallback), never on this constant.
# This list is never read directly by Push (digest/events) - see portfolio.py.
PORTFOLIO: list[CompanySeed] = [
    CompanySeed("HDFCBANK", "HDFC Bank Ltd", "NSE", "Banking", "HDFCBANK.NS", True),
    CompanySeed("ICICIBANK", "ICICI Bank Ltd", "NSE", "Banking", "ICICIBANK.NS", True),
    CompanySeed("SBIN", "State Bank of India", "NSE", "Banking", "SBIN.NS", True),
    CompanySeed("BAJFINANCE", "Bajaj Finance Ltd", "NSE", "NBFC / Financial Services", "BAJFINANCE.NS", True),
    CompanySeed("TCS", "Tata Consultancy Services Ltd", "NSE", "IT Services", "TCS.NS", True),
    CompanySeed("INFY", "Infosys Ltd", "NSE", "IT Services", "INFY.NS", True),
    CompanySeed("WIPRO", "Wipro Ltd", "NSE", "IT Services", "WIPRO.NS", True),
    CompanySeed("RELIANCE", "Reliance Industries Ltd", "NSE", "Energy / Conglomerate", "RELIANCE.NS", True),
    # Phase 11B/11C: NSE renamed "Tata Motors Ltd" (ticker TATAMOTORS) to "Tata
    # Motors Passenger Vehicles Ltd" (ticker TMPV) effective 2025-10-24, as part
    # of a real demerger that also separately listed the commercial-vehicle arm
    # as TMCV - confirmed live via yfinance (TATAMOTORS.NS now returns no data;
    # TMPV.NS and TMCV.NS both resolve). TMPV is the direct legal/ticker
    # successor and is seeded here; TMCV is a genuinely different listed entity
    # and is deliberately NOT seeded in either list (see module docstring - Pull
    # can still research it ad hoc via live ticker verification, just like any
    # other NSE ticker). The old TATAMOTORS ticker is NOT aliased to TMPV here -
    # it stays absent from this seed list, so a reference to it resolves (if at
    # all) only via live yfinance verification of the now-delisted symbol, never
    # by silently substituting TMPV's data under the old name.
    CompanySeed("TMPV", "Tata Motors Passenger Vehicles Ltd", "NSE", "Automobile", "TMPV.NS", True),
    CompanySeed("M&M", "Mahindra & Mahindra Ltd", "NSE", "Automobile", "M&M.NS", True),
    CompanySeed("SUNPHARMA", "Sun Pharmaceutical Industries Ltd", "NSE", "Pharmaceuticals", "SUNPHARMA.NS", True),
    CompanySeed("CIPLA", "Cipla Ltd", "NSE", "Pharmaceuticals", "CIPLA.NS", True),
    CompanySeed("HINDUNILVR", "Hindustan Unilever Ltd", "NSE", "FMCG", "HINDUNILVR.NS", True),
    CompanySeed("ITC", "ITC Ltd", "NSE", "FMCG", "ITC.NS", True),
    CompanySeed("BHARTIARTL", "Bharti Airtel Ltd", "NSE", "Telecom", "BHARTIARTL.NS", True),
    CompanySeed("TATASTEEL", "Tata Steel Ltd", "NSE", "Metals & Mining", "TATASTEEL.NS", True),
    CompanySeed("LT", "Larsen & Toubro Ltd", "NSE", "Infrastructure / Engineering", "LT.NS", True),
    # Phase 11B/11C: replaced NTPC - its investor-relations site returned a
    # durable, host-wide bot-protection block across repeated attempts in
    # separate phases, with no document ever successfully acquired. NTPC
    # itself remains a real, valid NSE ticker (market data works fine) and is
    # simply no longer a portfolio member; it is not aliased or blocked.
    CompanySeed("POWERGRID", "Power Grid Corporation of India Ltd", "NSE", "Power / Utilities", "POWERGRID.NS", True),
    CompanySeed("TRENT", "Trent Ltd", "NSE", "Retail", "TRENT.NS", True),
    CompanySeed("LICI", "Life Insurance Corporation of India", "NSE", "Insurance", "LICI.NS", True),
]

# Pre-validated example tickers for ad-hoc Pull research outside the portfolio -
# illustrative convenience, never a gate: Pull (app/services/hybrid_retrieval.py,
# app/repositories/company_lookup.py) already resolves ANY valid NSE ticker, seeded
# or not, via real yfinance verification.
AD_HOC_RESEARCH: list[CompanySeed] = [
    CompanySeed("ETERNAL", "Eternal Ltd (Zomato)", "NSE", "Internet / Food Delivery", "ETERNAL.NS", False),
    CompanySeed("ADANIPORTS", "Adani Ports and Special Economic Zone Ltd", "NSE", "Infrastructure / Logistics", "ADANIPORTS.NS", False),
    CompanySeed("COALINDIA", "Coal India Ltd", "NSE", "Mining / Energy", "COALINDIA.NS", False),
    CompanySeed("DIXON", "Dixon Technologies (India) Ltd", "NSE", "Electronics Manufacturing", "DIXON.NS", False),
    CompanySeed("DRREDDY", "Dr. Reddy's Laboratories Ltd", "NSE", "Pharmaceuticals", "DRREDDY.NS", False),
]

ALL_SEED_COMPANIES: list[CompanySeed] = PORTFOLIO + AD_HOC_RESEARCH

_BY_TICKER: dict[str, CompanySeed] = {c.ticker: c for c in ALL_SEED_COMPANIES}


def get_seed_company(ticker: str) -> CompanySeed | None:
    return _BY_TICKER.get(ticker.strip().upper())


def to_yfinance_symbol(ticker: str, exchange: str = "NSE") -> str:
    """Map a bare NSE/BSE ticker to its yfinance symbol.

    Works for ANY ticker, not just the seed list — this is what keeps the
    research engine generalizable (requirements.md §3). The seed list above
    is only used to pre-populate the demo portfolio/ad-hoc pages.
    """
    seed = get_seed_company(ticker)
    if seed:
        return seed.yfinance_symbol
    suffix = ".NS" if exchange.upper() == "NSE" else ".BO"
    return f"{ticker.strip().upper()}{suffix}"
