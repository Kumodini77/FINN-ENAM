"""Announcement persistence.

Backend selection: Supabase when configured AND reachable (verified via a real query,
not just the presence of env vars — see app/core/db.py); otherwise a JSON-file store
under <data_dir>/announcements.json. Both backends enforce the same dedup rule, so
callers never need to know which one is active.

Dedup rule (per requirements.md Module 1 — "stable identifiers or source URL and
company combination"): a new announcement is a duplicate of an existing one if they
share the same (company_ticker, original_source_url). This is checked in Python here
so it applies identically whether or not Supabase's own unique index (003_phase2_additions.sql)
is in play.
"""

import logging
import uuid
from datetime import datetime, timezone

from postgrest import APIError

from app.core.config import get_settings
from app.core.db import get_supabase_client, storage_backend_name
from app.models.announcement import Announcement
from app.repositories.company_lookup import get_company_id, get_or_register_company_id, get_ticker
from app.repositories.json_store import JsonListStore

logger = logging.getLogger("finn.repositories.announcements")

_UNIQUE_VIOLATION = "23505"


def _to_db_payload(announcement: Announcement, company_id: str) -> dict:
    """The announcements table has company_id (uuid FK), not company_ticker, and no
    ingested_at/extracted_text columns (migrations/001_init.sql + 003) — translate
    the model's shape into the real schema's shape."""
    payload = announcement.model_dump(mode="json")
    payload.pop("company_ticker", None)
    payload.pop("ingested_at", None)
    payload.pop("extracted_text", None)
    payload["company_id"] = company_id
    return payload


def _from_db_row(row: dict) -> Announcement:
    data = dict(row)
    data["company_ticker"] = get_ticker(row["company_id"]) or row["company_id"]
    data.setdefault("ingested_at", row.get("created_at"))
    return Announcement.model_validate(data)


class AnnouncementRepository:
    def __init__(self, store: JsonListStore | None = None):
        settings = get_settings()
        # An explicitly-injected store means "force JSON-fallback isolation" (every
        # test in this suite relies on this) — without this, a repository
        # constructed with a test-only tmp_path store would still silently talk to
        # a real, live-configured Supabase project, which is exactly the kind of
        # test-pollution bug Phase 2 already fixed once for alert evaluation.
        self._force_json = store is not None
        self._store = store or JsonListStore(settings.data_dir, "announcements.json")

    def _backend(self) -> str:
        if self._force_json:
            return "json_fallback"
        return storage_backend_name()

    def find_duplicate(self, company_ticker: str, original_source_url: str) -> Announcement | None:
        if self._backend() == "supabase":
            company_id = get_company_id(company_ticker)
            if company_id is None:
                # Never registered yet -> there is no possible existing announcement
                # for it. Avoids querying with a company_id that doesn't exist.
                return None
            client = get_supabase_client()
            resp = (
                client.table("announcements")
                .select("*")
                .eq("company_id", company_id)
                .eq("original_source_url", original_source_url)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return _from_db_row(rows[0]) if rows else None

        for row in self._store.read_all():
            if row.get("company_ticker") == company_ticker and row.get("original_source_url") == original_source_url:
                return Announcement.model_validate(row)
        return None

    def add(self, announcement: Announcement) -> tuple[Announcement, bool]:
        """Returns (record, created). If a duplicate exists, returns the EXISTING
        record with created=False rather than inserting a second copy."""
        existing = self.find_duplicate(announcement.company_ticker, announcement.original_source_url)
        if existing is not None:
            logger.info(
                "Duplicate announcement skipped: %s / %s", announcement.company_ticker, announcement.original_source_url
            )
            return existing, False

        if self._backend() == "supabase":
            company_id = get_or_register_company_id(announcement.company_ticker)
            client = get_supabase_client()
            payload = _to_db_payload(announcement, company_id)
            try:
                client.table("announcements").insert(payload).execute()
            except APIError as e:
                if e.code == _UNIQUE_VIOLATION:
                    # Lost a race to a concurrent insert of the same
                    # (company, original_source_url) — treat as a duplicate, not
                    # an unexplained 500.
                    existing = self.find_duplicate(announcement.company_ticker, announcement.original_source_url)
                    if existing is not None:
                        return existing, False
                raise
        else:
            self._store.append(announcement.model_dump(mode="json"))

        return announcement, True

    def list_all(self) -> list[Announcement]:
        if self._backend() == "supabase":
            client = get_supabase_client()
            resp = client.table("announcements").select("*").execute()
            return [_from_db_row(r) for r in (resp.data or [])]
        return [Announcement.model_validate(r) for r in self._store.read_all()]

    def list_for_tickers(self, tickers: set[str]) -> list[Announcement]:
        return [a for a in self.list_all() if a.company_ticker in tickers]


def new_announcement_id() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
