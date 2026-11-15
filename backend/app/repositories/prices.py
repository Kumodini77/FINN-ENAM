"""Persisted EOD price bars — backed by migrations/001_init.sql's `prices` table
(Supabase) or prices.json (fallback). That table has existed since Phase 1 but
nothing ever read or wrote it (app.services.market_data fetches live from yfinance
on every request and never stores anything) — this is what Phase 12A's scheduled
refresh job actually writes to, the same pattern app.repositories.portfolio
documents for the `portfolio` table.

Stores only raw, validated CLOSED_EOD bars (never a provisional/intraday bar — the
scheduled refresh runs after market close specifically so every bar it sees is
final). Derived stats (daily % change, rolling average volume, volume multiple)
stay request-time calculations in app.services.market_data, exactly as before —
this repository is intentionally just a bar store, not a second place those
calculations could drift out of sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from app.core.config import get_settings
from app.core.db import get_supabase_client, storage_backend_name
from app.repositories.json_store import JsonListStore


@dataclass(frozen=True)
class EodBar:
    company_ticker: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str = "live"
    fetched_at: datetime | None = None


class PricesRepository:
    def __init__(self, store: JsonListStore | None = None):
        settings = get_settings()
        self._force_json = store is not None
        self._store = store or JsonListStore(settings.data_dir, "prices.json")

    def _backend(self) -> str:
        if self._force_json:
            return "json_fallback"
        return storage_backend_name()

    @property
    def backend(self) -> str:
        """Public read of which backend THIS instance is actually using — the job
        must check this, not the bare module-level storage_backend_name(), so a
        test-injected JSON-fallback repository is honored rather than silently
        overridden by whatever the ambient environment happens to have configured."""
        return self._backend()

    def upsert_bar(self, bar: EodBar, company_id: str | None = None) -> None:
        """Idempotent on (ticker/company, trade_date) — re-running the refresh job
        for an already-stored date updates that one row in place rather than
        duplicating it, and never touches any other date's row (so a bad later
        fetch can't silently corrupt earlier, already-good history)."""
        fetched_at = bar.fetched_at or datetime.now(timezone.utc)
        trade_date_str = bar.trade_date.isoformat()

        if self._backend() == "supabase":
            if company_id is None:
                raise ValueError("company_id is required when writing to Supabase")
            client = get_supabase_client()
            client.table("prices").upsert(
                {
                    "company_id": company_id,
                    "trade_date": trade_date_str,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "session_status": "closed_eod",
                    "source": bar.source,
                    "fetched_at": fetched_at.isoformat(),
                },
                on_conflict="company_id,trade_date",
            ).execute()
            return

        rows = self._store.read_all()
        rows = [r for r in rows if not (r.get("company_ticker") == bar.company_ticker and r.get("trade_date") == trade_date_str)]
        rows.append(
            {
                "company_ticker": bar.company_ticker,
                "trade_date": trade_date_str,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "session_status": "closed_eod",
                "source": bar.source,
                "fetched_at": fetched_at.isoformat(),
            }
        )
        self._store.replace_all(rows)

    def get_latest_trade_date(self, company_ticker: str, company_id: str | None = None) -> date | None:
        if self._backend() == "supabase":
            if company_id is None:
                return None
            client = get_supabase_client()
            resp = (
                client.table("prices")
                .select("trade_date")
                .eq("company_id", company_id)
                .order("trade_date", desc=True)
                .limit(1)
                .execute()
            )
            if not resp.data:
                return None
            return date.fromisoformat(str(resp.data[0]["trade_date"]))

        rows = [r for r in self._store.read_all() if r.get("company_ticker") == company_ticker]
        if not rows:
            return None
        latest = max(r["trade_date"] for r in rows)
        return date.fromisoformat(latest)

    def list_bars(self, company_ticker: str, company_id: str | None = None) -> list[dict]:
        """Test/inspection helper — not used by the hot request path."""
        if self._backend() == "supabase":
            if company_id is None:
                return []
            client = get_supabase_client()
            resp = client.table("prices").select("*").eq("company_id", company_id).execute()
            return resp.data or []
        return [r for r in self._store.read_all() if r.get("company_ticker") == company_ticker]


__all__ = ["PricesRepository", "EodBar"]
