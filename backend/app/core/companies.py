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


PORTFOLIO: list[CompanySeed] = [
    CompanySeed("RELIANCE", "Reliance Industries Ltd", "NSE", "Energy / Conglomerate", "RELIANCE.NS", True),
    CompanySeed("HDFCBANK", "HDFC Bank Ltd", "NSE", "Banking", "HDFCBANK.NS", True),
    CompanySeed("ICICIBANK", "ICICI Bank Ltd", "NSE", "Banking", "ICICIBANK.NS", True),
    CompanySeed("SBIN", "State Bank of India", "NSE", "Banking", "SBIN.NS", True),
    CompanySeed("TCS", "Tata Consultancy Services Ltd", "NSE", "IT Services", "TCS.NS", True),
    CompanySeed("INFY", "Infosys Ltd", "NSE", "IT Services", "INFY.NS", True),
    CompanySeed("BHARTIARTL", "Bharti Airtel Ltd", "NSE", "Telecom", "BHARTIARTL.NS", True),
    CompanySeed("ITC", "ITC Ltd", "NSE", "FMCG", "ITC.NS", True),
    CompanySeed("HINDUNILVR", "Hindustan Unilever Ltd", "NSE", "FMCG", "HINDUNILVR.NS", True),
    CompanySeed("LT", "Larsen & Toubro Ltd", "NSE", "Infrastructure / Engineering", "LT.NS", True),
    CompanySeed("TATAMOTORS", "Tata Motors Ltd", "NSE", "Automobile", "TATAMOTORS.NS", True),
    CompanySeed("MARUTI", "Maruti Suzuki India Ltd", "NSE", "Automobile", "MARUTI.NS", True),
    CompanySeed("SUNPHARMA", "Sun Pharmaceutical Industries Ltd", "NSE", "Pharmaceuticals", "SUNPHARMA.NS", True),
    CompanySeed("NTPC", "NTPC Ltd", "NSE", "Power / Utilities", "NTPC.NS", True),
    CompanySeed("TATASTEEL", "Tata Steel Ltd", "NSE", "Metals & Mining", "TATASTEEL.NS", True),
]

AD_HOC_RESEARCH: list[CompanySeed] = [
    CompanySeed("TRENT", "Trent Ltd", "NSE", "Retail", "TRENT.NS", False),
    CompanySeed("BEL", "Bharat Electronics Ltd", "NSE", "Defence / Electronics", "BEL.NS", False),
    CompanySeed("DMART", "Avenue Supermarts Ltd (DMart)", "NSE", "Retail", "DMART.NS", False),
    CompanySeed("VBL", "Varun Beverages Ltd", "NSE", "Beverages / FMCG", "VBL.NS", False),
]

ALL_SEED_COMPANIES: list[CompanySeed] = PORTFOLIO + AD_HOC_RESEARCH

_BY_TICKER: dict[str, CompanySeed] = {c.ticker: c for c in ALL_SEED_COMPANIES}


def get_seed_company(ticker: str) -> CompanySeed | None:
    return _BY_TICKER.get(ticker.upper())


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
    return f"{ticker.upper()}{suffix}"
