"""Ticker <-> companies.id (uuid) resolution for the Supabase persistence layer.

Only exercised when storage_backend_name() == "supabase" — the JSON fallback store
keys everything by company_ticker directly and never needs this translation. Keeping
the translation at this layer means every Pydantic model, API schema, and service
above the repositories keeps using company_ticker exactly as before (the Phase 2
contract is unchanged).

Generalization (requirements.md Section 3 — "the research engine must generalize to
any NSE ticker, not just the chosen portfolio"): get_or_register_company_id() can
register a company that isn't one of the 19 seeded rows, but only after verifying
real metadata via yfinance. It never fabricates a name, exchange, or sector — an
unverifiable ticker raises CompanyLookupError instead of guessing.
"""

import logging
import threading

from app.core.companies import to_yfinance_symbol
from app.core.db import get_supabase_client
from app.core.exceptions import CompanyLookupError

logger = logging.getLogger("finn.repositories.company_lookup")

_lock = threading.Lock()
_ticker_to_id: dict[str, str] = {}
_id_to_ticker: dict[str, str] = {}

# yfinance's own exchange code for NSE-listed equities, observed directly against a
# live, non-seeded ticker (WIPRO.NS -> exchange="NSI") during this build. Any other
# code is treated as "can't verify this is NSE" rather than guessed.
_YFINANCE_NSE_EXCHANGE_CODES = {"NSI"}


def _load_cache() -> None:
    client = get_supabase_client()
    resp = client.table("companies").select("id,ticker").execute()
    with _lock:
        for row in resp.data or []:
            _ticker_to_id[row["ticker"]] = row["id"]
            _id_to_ticker[row["id"]] = row["ticker"]


def invalidate_cache() -> None:
    """Drops the in-process cache so the next lookup re-reads the companies table.
    Needed if a company row is added or changed by something other than this
    module's own writes (e.g. a manual edit in the Supabase dashboard)."""
    with _lock:
        _ticker_to_id.clear()
        _id_to_ticker.clear()


def get_company_id(ticker: str) -> str | None:
    """Cache-only lookup. Returns None if the ticker has no companies row yet —
    callers that want to auto-register an unseen ticker should use
    get_or_register_company_id() instead."""
    ticker = ticker.upper()
    if ticker not in _ticker_to_id:
        _load_cache()
    return _ticker_to_id.get(ticker)


def get_ticker(company_id: str) -> str | None:
    """Reverse lookup, used when translating a raw Supabase row (which carries
    company_id) back into the ticker-based Pydantic model shape."""
    if company_id not in _id_to_ticker:
        _load_cache()
    return _id_to_ticker.get(company_id)


def verify_ticker_metadata(ticker: str) -> dict:
    """Looks up real, verifiable metadata for `ticker` via yfinance. Raises
    CompanyLookupError rather than inventing anything if it can't be confirmed as a
    real NSE-listed equity. Pure lookup — does not touch the database, so it works
    regardless of which storage backend is active; app/services/company_resolution.py
    is the shared entry point other modules should call instead of this directly."""
    import yfinance as yf

    yfinance_symbol = to_yfinance_symbol(ticker)
    try:
        info = yf.Ticker(yfinance_symbol).info
    except Exception:
        logger.exception("yfinance metadata lookup failed for %s", ticker)
        raise CompanyLookupError(f"Could not verify '{ticker}' — metadata lookup failed.")

    quote_type = info.get("quoteType")
    name = info.get("longName") or info.get("shortName")
    exchange_code = info.get("exchange")

    if quote_type != "EQUITY" or not name:
        raise CompanyLookupError(
            f"Could not verify '{ticker}' as a valid, currently-listed equity; "
            "refusing to register it without confirmed metadata."
        )
    if exchange_code not in _YFINANCE_NSE_EXCHANGE_CODES:
        raise CompanyLookupError(
            f"'{ticker}' did not resolve to a recognized NSE exchange code "
            f"(got {exchange_code!r}); refusing to guess which exchange it's on."
        )

    return {
        "ticker": ticker,
        "name": name,
        "exchange": "NSE",
        "sector": info.get("sector"),
        "yfinance_symbol": yfinance_symbol,
        "is_seed_portfolio": False,
    }


def get_or_register_company_id(ticker: str) -> str:
    """Resolves ticker -> company_id, auto-registering a verified new company row if
    one doesn't exist yet. Raises CompanyLookupError (never fabricates a row) if the
    ticker can't be verified. Registration is atomic at the database level
    (on_conflict="ticker", ignore_duplicates=True), so two concurrent calls for the
    same brand-new ticker can't create duplicate companies rows."""
    ticker = ticker.upper()
    existing = get_company_id(ticker)
    if existing is not None:
        return existing

    row = verify_ticker_metadata(ticker)
    client = get_supabase_client()
    client.table("companies").upsert(row, on_conflict="ticker", ignore_duplicates=True).execute()

    resp = client.table("companies").select("id").eq("ticker", ticker).limit(1).execute()
    if not resp.data:
        raise CompanyLookupError(f"Failed to register '{ticker}' in the companies table.")

    company_id = resp.data[0]["id"]
    with _lock:
        _ticker_to_id[ticker] = company_id
        _id_to_ticker[company_id] = ticker
    return company_id
