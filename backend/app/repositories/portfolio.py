"""Portfolio membership: which companies Push monitors - a SEPARATE concept from
the company registry (which companies FINN knows about at all, app.core.companies
+ the `companies` table) and from document availability (app.repositories.documents).
A company can be registered without being in the portfolio, and vice versa is
meaningless (you can't track a company that doesn't exist) - add_ticker() always
resolves/registers the company first.

Backed by migrations/001_init.sql's `portfolio` table (user_id, company_id) - that
table has existed since Phase 1 but nothing ever read or wrote it; Push
(app/api/digest.py, app/api/events.py) read a hardcoded Python list instead. This
repository is what makes "adding or removing a portfolio company must not require
code changes" actually true.

Bootstrap: the FIRST time this repository is read and finds nothing stored yet (a
brand new Supabase project, or a fresh JSON-fallback install), it seeds real,
mutable portfolio rows from app.core.companies.PORTFOLIO once, so the demo still
starts with its original company set out of the box - every read/write after that
operates purely on the stored data, never on the Python constant again.
"""

from datetime import datetime, timezone

from app.core.companies import PORTFOLIO
from app.core.config import get_settings
from app.core.db import get_supabase_client, storage_backend_name
from app.core.exceptions import CompanyLookupError
from app.repositories.app_user import get_app_user_id
from app.repositories.company_lookup import get_company_id, get_or_register_company_id, get_ticker
from app.repositories.json_store import JsonListStore
from app.services.company_resolution import ResolvedCompany, resolve_company


class PortfolioRepository:
    def __init__(self, store: JsonListStore | None = None):
        settings = get_settings()
        self._force_json = store is not None
        self._store = store or JsonListStore(settings.data_dir, "portfolio.json")

    def _backend(self) -> str:
        if self._force_json:
            return "json_fallback"
        return storage_backend_name()

    def _bootstrap_if_empty_supabase(self, user_id: str) -> None:
        client = get_supabase_client()
        resp = client.table("portfolio").select("company_id").eq("user_id", user_id).limit(1).execute()
        if resp.data:
            return  # already has real data - never reseed over an intentionally-emptied portfolio
        for seed in PORTFOLIO:
            company_id = get_or_register_company_id(seed.ticker)
            client.table("portfolio").upsert(
                {"user_id": user_id, "company_id": company_id}, on_conflict="user_id,company_id", ignore_duplicates=True
            ).execute()

    def list_tickers(self) -> set[str]:
        if self._backend() == "supabase":
            user_id = get_app_user_id()
            self._bootstrap_if_empty_supabase(user_id)
            client = get_supabase_client()
            resp = client.table("portfolio").select("company_id").eq("user_id", user_id).execute()
            tickers = {get_ticker(row["company_id"]) for row in (resp.data or [])}
            tickers.discard(None)
            return tickers  # type: ignore[return-value]

        rows = self._store.read_all()
        if not rows:
            now = datetime.now(timezone.utc).isoformat()
            rows = [
                {"ticker": seed.ticker, "name": seed.name, "exchange": seed.exchange, "sector": seed.sector, "added_at": now}
                for seed in PORTFOLIO
            ]
            self._store.replace_all(rows)
        return {r["ticker"] for r in rows}

    def list_companies(self) -> list[dict]:
        """Like list_tickers() but with display metadata (name/exchange/sector) -
        used by the GET /api/portfolio response. Supabase: joins against the
        `companies` table companies.id already has; fallback: the portfolio rows
        already carry their own copy of this metadata from add_ticker()."""
        if self._backend() == "supabase":
            user_id = get_app_user_id()
            self._bootstrap_if_empty_supabase(user_id)
            client = get_supabase_client()
            resp = client.table("portfolio").select("company_id").eq("user_id", user_id).execute()
            company_ids = [row["company_id"] for row in (resp.data or [])]
            if not company_ids:
                return []
            companies_resp = client.table("companies").select("id,ticker,name,exchange,sector").execute()
            by_id = {c["id"]: c for c in (companies_resp.data or [])}
            return [
                {"ticker": c["ticker"], "name": c["name"], "exchange": c["exchange"], "sector": c.get("sector")}
                for cid in company_ids
                if (c := by_id.get(cid)) is not None
            ]

        rows = self._store.read_all()
        if not rows:
            self.list_tickers()  # triggers the fallback bootstrap
            rows = self._store.read_all()
        return [{"ticker": r["ticker"], "name": r.get("name"), "exchange": r.get("exchange"), "sector": r.get("sector")} for r in rows]

    def add_ticker(self, ticker: str, verify=None) -> ResolvedCompany:
        """Validates the ticker against real company data (resolve_company - seed
        registry or live yfinance metadata, never fabricated) before adding it.
        Raises CompanyLookupError for an invalid/unverifiable ticker - never adds
        a company FINN can't actually confirm exists."""
        resolved = resolve_company(ticker, verify=verify)

        if self._backend() == "supabase":
            company_id = get_or_register_company_id(resolved.ticker)
            user_id = get_app_user_id()
            client = get_supabase_client()
            client.table("portfolio").upsert(
                {"user_id": user_id, "company_id": company_id}, on_conflict="user_id,company_id", ignore_duplicates=True
            ).execute()
        else:
            rows = self._store.read_all()
            if not any(r.get("ticker") == resolved.ticker for r in rows):
                rows.append(
                    {
                        "ticker": resolved.ticker, "name": resolved.name, "exchange": resolved.exchange,
                        "sector": resolved.sector, "added_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                self._store.replace_all(rows)
        return resolved

    def remove_ticker(self, ticker: str) -> bool:
        """Returns True if the ticker was actually a member and was removed, False
        if it wasn't in the portfolio to begin with - lets the API return a clean
        404 rather than a silent no-op."""
        ticker = ticker.strip().upper()
        if self._backend() == "supabase":
            company_id = get_company_id(ticker)
            if company_id is None:
                return False
            user_id = get_app_user_id()
            client = get_supabase_client()
            resp = client.table("portfolio").delete().eq("user_id", user_id).eq("company_id", company_id).execute()
            return bool(resp.data)

        rows = self._store.read_all()
        remaining = [r for r in rows if r.get("ticker") != ticker]
        removed = len(remaining) != len(rows)
        self._store.replace_all(remaining)
        return removed


__all__ = ["PortfolioRepository", "CompanyLookupError"]
