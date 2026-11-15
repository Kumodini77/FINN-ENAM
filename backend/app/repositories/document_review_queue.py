"""Review queue for ambiguous discovery candidates — Phase 12B. A candidate lands
here instead of being auto-ingested whenever its source identity could not be
confirmed, its document type/period is unclear, or it collides ambiguously with
an existing document. A human (or a future, separate approval step) decides from
here; nothing in this queue is ever auto-ingested by the discovery job itself.

Backed by a NEW table (`document_review_queue`) proposed in migrations/011 — see
app.repositories.document_sources's module docstring for the same "not yet
applied, JSON-fallback is what's actually tested" status.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.db import get_supabase_client, storage_backend_name
from app.repositories.json_store import JsonListStore
from app.services.document_discovery.types import DiscoveredCandidate

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ReviewQueueEntry:
    id: str
    company_ticker: str
    doc_type: str
    title: str
    source_url: str
    source_name: str
    reporting_period: str | None
    reason: str
    status: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "ReviewQueueEntry":
        created = row.get("created_at")
        return cls(
            id=row["id"], company_ticker=row["company_ticker"], doc_type=row["doc_type"], title=row["title"],
            source_url=row["source_url"], source_name=row["source_name"], reporting_period=row.get("reporting_period"),
            reason=row["reason"], status=row.get("status", PENDING),
            created_at=created if isinstance(created, datetime) else datetime.fromisoformat(str(created)),
        )

    def to_row(self) -> dict:
        return {
            "id": self.id, "company_ticker": self.company_ticker, "doc_type": self.doc_type, "title": self.title,
            "source_url": self.source_url, "source_name": self.source_name, "reporting_period": self.reporting_period,
            "reason": self.reason, "status": self.status, "created_at": self.created_at.isoformat(),
        }


class ReviewQueueRepository:
    def __init__(self, store: JsonListStore | None = None):
        settings = get_settings()
        self._force_json = store is not None
        self._store = store or JsonListStore(settings.data_dir, "document_review_queue.json")

    @property
    def backend(self) -> str:
        if self._force_json:
            return "json_fallback"
        return storage_backend_name()

    def add(self, candidate: DiscoveredCandidate, reason: str) -> ReviewQueueEntry:
        entry = ReviewQueueEntry(
            id=str(uuid.uuid4()), company_ticker=candidate.company_ticker, doc_type=candidate.doc_type,
            title=candidate.title, source_url=candidate.source_url, source_name=candidate.source_name,
            reporting_period=candidate.reporting_period, reason=reason, status=PENDING, created_at=_now(),
        )
        if self.backend == "supabase":
            client = get_supabase_client()
            client.table("document_review_queue").upsert(entry.to_row(), on_conflict="source_url").execute()
            return entry
        rows = self._store.read_all()
        if any(r.get("source_url") == entry.source_url and r.get("status") == PENDING for r in rows):
            return entry  # already queued — don't duplicate the same candidate every run
        rows.append(entry.to_row())
        self._store.replace_all(rows)
        return entry

    def list_pending(self) -> list[ReviewQueueEntry]:
        if self.backend == "supabase":
            client = get_supabase_client()
            rows = client.table("document_review_queue").select("*").eq("status", PENDING).execute().data or []
        else:
            rows = [r for r in self._store.read_all() if r.get("status") == PENDING]
        return [ReviewQueueEntry.from_row(r) for r in rows]

    def set_status(self, entry_id: str, status: str) -> None:
        if self.backend == "supabase":
            client = get_supabase_client()
            client.table("document_review_queue").update({"status": status}).eq("id", entry_id).execute()
            return
        rows = self._store.read_all()
        for r in rows:
            if r.get("id") == entry_id:
                r["status"] = status
        self._store.replace_all(rows)


__all__ = ["ReviewQueueRepository", "ReviewQueueEntry", "PENDING", "APPROVED", "REJECTED"]
