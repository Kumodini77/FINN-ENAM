"""Per-company, per-source checkpoint tracking for Phase 12B's document discovery
— a durable store, never an in-memory dict, so a scheduler/worker restart never
loses "when did we last check this company's sources."

Backed by a NEW table (`document_sources`) proposed in
migrations/011_document_discovery_tracking.sql — NOT YET APPLIED to the live
Supabase project (see that migration's header and FINN_PHASE_12B_REPORT.md). The
Supabase branch below describes the target schema; the JSON-fallback branch is
fully real today and is what every test in this phase actually exercises, exactly
like app.repositories.prices/job_runs in Phase 12A before their own migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.db import get_supabase_client, storage_backend_name
from app.repositories.json_store import JsonListStore

HEALTHY = "healthy"
DEGRADED = "degraded"
BLOCKED = "blocked"
UNKNOWN = "unknown"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@dataclass
class SourceCheckpoint:
    company_ticker: str
    source_name: str
    source_url: str | None = None
    last_checked_at: datetime | None = None
    last_successful_check_at: datetime | None = None
    last_discovered_document_title: str | None = None
    last_discovered_document_url: str | None = None
    latest_processed_document_id: str | None = None
    health: str = UNKNOWN
    error_message: str | None = None
    next_eligible_check_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict) -> "SourceCheckpoint":
        def parse_dt(v):
            if v is None:
                return None
            return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))

        return cls(
            company_ticker=row["company_ticker"], source_name=row["source_name"], source_url=row.get("source_url"),
            last_checked_at=parse_dt(row.get("last_checked_at")), last_successful_check_at=parse_dt(row.get("last_successful_check_at")),
            last_discovered_document_title=row.get("last_discovered_document_title"),
            last_discovered_document_url=row.get("last_discovered_document_url"),
            latest_processed_document_id=row.get("latest_processed_document_id"), health=row.get("health", UNKNOWN),
            error_message=row.get("error_message"), next_eligible_check_at=parse_dt(row.get("next_eligible_check_at")),
        )

    def to_row(self) -> dict:
        return {
            "company_ticker": self.company_ticker, "source_name": self.source_name, "source_url": self.source_url,
            "last_checked_at": _iso(self.last_checked_at), "last_successful_check_at": _iso(self.last_successful_check_at),
            "last_discovered_document_title": self.last_discovered_document_title,
            "last_discovered_document_url": self.last_discovered_document_url,
            "latest_processed_document_id": self.latest_processed_document_id, "health": self.health,
            "error_message": self.error_message, "next_eligible_check_at": _iso(self.next_eligible_check_at),
        }


class DocumentSourceRepository:
    def __init__(self, store: JsonListStore | None = None):
        settings = get_settings()
        self._force_json = store is not None
        self._store = store or JsonListStore(settings.data_dir, "document_sources.json")

    @property
    def backend(self) -> str:
        if self._force_json:
            return "json_fallback"
        return storage_backend_name()

    def _all_rows(self) -> list[dict]:
        if self.backend == "supabase":
            client = get_supabase_client()
            return client.table("document_sources").select("*").execute().data or []
        return self._store.read_all()

    def record_check(
        self,
        ticker: str,
        source_name: str,
        *,
        ok: bool,
        source_url: str | None = None,
        discovered_title: str | None = None,
        discovered_url: str | None = None,
        processed_document_id: str | None = None,
        health: str = UNKNOWN,
        error_message: str | None = None,
        next_eligible_check_at: datetime | None = None,
    ) -> SourceCheckpoint:
        existing = self.get(ticker, source_name)
        now = _now()
        checkpoint = existing or SourceCheckpoint(company_ticker=ticker.strip().upper(), source_name=source_name)
        checkpoint.source_url = source_url or checkpoint.source_url
        checkpoint.last_checked_at = now
        if ok:
            checkpoint.last_successful_check_at = now
            checkpoint.error_message = None
        else:
            checkpoint.error_message = error_message
        if discovered_title:
            checkpoint.last_discovered_document_title = discovered_title
            checkpoint.last_discovered_document_url = discovered_url
        if processed_document_id:
            checkpoint.latest_processed_document_id = processed_document_id
        checkpoint.health = health
        checkpoint.next_eligible_check_at = next_eligible_check_at

        if self.backend == "supabase":
            client = get_supabase_client()
            client.table("document_sources").upsert(checkpoint.to_row(), on_conflict="company_ticker,source_name").execute()
            return checkpoint

        rows = self._store.read_all()
        rows = [r for r in rows if not (r.get("company_ticker") == checkpoint.company_ticker and r.get("source_name") == source_name)]
        rows.append(checkpoint.to_row())
        self._store.replace_all(rows)
        return checkpoint

    def get(self, ticker: str, source_name: str) -> SourceCheckpoint | None:
        ticker = ticker.strip().upper()
        for row in self._all_rows():
            if row.get("company_ticker") == ticker and row.get("source_name") == source_name:
                return SourceCheckpoint.from_row(row)
        return None

    def list_all(self) -> list[SourceCheckpoint]:
        return [SourceCheckpoint.from_row(r) for r in self._all_rows()]


__all__ = ["DocumentSourceRepository", "SourceCheckpoint", "HEALTHY", "DEGRADED", "BLOCKED", "UNKNOWN"]
