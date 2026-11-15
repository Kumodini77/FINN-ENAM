"""Document and document_chunk persistence for the RAG ingestion pipeline.

Supabase-only for now: migrations/007 (ingestion-tracking columns) and
migrations/008 (completed-document-only retrieval) are not yet applied, so this
repository's Supabase branch describes the TARGET schema, not a currently-reachable
one - callers must not run it against a live project until those migrations are
approved and applied. The JSON-fallback branch mirrors the same contract (dedup,
atomic claim, chunk cleanup) so unit tests and ingestion-pipeline tests exercise the
exact same semantics without a database.

Four-case conflict matrix for a candidate (file_sha256, company_id, doc_type,
reporting_period):
  1. Same hash, same metadata        -> reuse the existing document, not a new insert.
  2. Same hash, different metadata   -> DocumentMetadataConflictError (same bytes
                                         already filed under a different identity).
  3. Different hash, same metadata   -> DocumentExistingConflictError (a different
                                         file already occupies that identity).
  4. Neither                         -> fresh insert.
The two underlying unique constraints (file_sha256 partial-unique, and the existing
(company_id, doc_type, reporting_period) unique from 001_init.sql) are the final
race-proof backstop if two concurrent callers reach case 4 for the same input at once.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from postgrest import APIError

from app.core.config import get_settings
from app.core.db import get_supabase_client, storage_backend_name
from app.core.exceptions import DocumentAlreadyClaimedError, DocumentExistingConflictError, DocumentMetadataConflictError
from app.models.document import Document, DocumentChunk, IngestionStatus
from app.repositories.company_lookup import get_company_id, get_ticker
from app.repositories.json_store import JsonListStore

logger = logging.getLogger("finn.repositories.documents")

_UNIQUE_VIOLATION = "23505"
_CLAIMABLE_STATUSES = (IngestionStatus.PENDING.value, IngestionStatus.FAILED.value)
DEFAULT_STALE_CLAIM_MINUTES = 60


def new_document_id() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_db_payload(document: Document) -> dict:
    """The documents table (migrations/001_init.sql) has company_id (uuid FK), not
    company_ticker - same translation pattern as app.repositories.announcements."""
    payload = document.model_dump(mode="json")
    payload.pop("company_ticker", None)
    return payload


def _from_db_row(row: dict) -> Document:
    data = dict(row)
    data["company_ticker"] = get_ticker(row["company_id"]) or row["company_id"]
    return Document.model_validate(data)


class DocumentRepository:
    def __init__(self, store: JsonListStore | None = None, chunk_store: JsonListStore | None = None):
        settings = get_settings()
        self._force_json = store is not None
        self._store = store or JsonListStore(settings.data_dir, "documents.json")
        self._chunk_store = chunk_store or JsonListStore(settings.data_dir, "document_chunks.json")

    def _backend(self) -> str:
        if self._force_json:
            return "json_fallback"
        return storage_backend_name()

    # --- lookups -----------------------------------------------------------------

    def get_by_id(self, document_id: str) -> Document | None:
        if self._backend() == "supabase":
            client = get_supabase_client()
            resp = client.table("documents").select("*").eq("id", document_id).limit(1).execute()
            rows = resp.data or []
            return _from_db_row(rows[0]) if rows else None
        for row in self._store.read_all():
            if row.get("id") == document_id:
                return Document.model_validate(row)
        return None

    def find_by_sha256(self, file_sha256: str) -> Document | None:
        if self._backend() == "supabase":
            client = get_supabase_client()
            resp = client.table("documents").select("*").eq("file_sha256", file_sha256).limit(1).execute()
            rows = resp.data or []
            return _from_db_row(rows[0]) if rows else None
        for row in self._store.read_all():
            if row.get("file_sha256") == file_sha256:
                return Document.model_validate(row)
        return None

    def find_by_metadata(self, company_id: str, doc_type: str, reporting_period: str | None) -> Document | None:
        if self._backend() == "supabase":
            client = get_supabase_client()
            query = client.table("documents").select("*").eq("company_id", company_id).eq("doc_type", doc_type)
            query = query.eq("reporting_period", reporting_period) if reporting_period is not None else query
            resp = query.limit(1).execute()
            rows = resp.data or []
            return _from_db_row(rows[0]) if rows else None
        for row in self._store.read_all():
            if (
                row.get("company_id") == company_id
                and row.get("doc_type") == doc_type
                and row.get("reporting_period") == reporting_period
            ):
                return Document.model_validate(row)
        return None

    def list_documents_for_ticker(self, company_ticker: str) -> list[Document]:
        """Every document on record for this ticker, any ingestion_status - the
        caller (e.g. research-readiness checks) decides what to do with
        pending/failed vs completed; this never filters that itself, so it stays a
        single source of truth for "what do we have," not "what's usable."""
        ticker = company_ticker.strip().upper()
        if self._backend() == "supabase":
            company_id = get_company_id(ticker)
            if company_id is None:
                return []
            client = get_supabase_client()
            resp = client.table("documents").select("*").eq("company_id", company_id).execute()
            return [_from_db_row(r) for r in (resp.data or [])]
        return [Document.model_validate(r) for r in self._store.read_all() if r.get("company_ticker") == ticker]

    # --- creation / dedup ----------------------------------------------------------

    def resolve_or_create(self, document: Document) -> tuple[Document, bool]:
        """Applies the four-case conflict matrix and returns (record, created).
        `document.file_sha256` must be set."""
        if not document.file_sha256:
            raise ValueError("resolve_or_create requires document.file_sha256 to be set")

        by_hash = self.find_by_sha256(document.file_sha256)
        by_metadata = self.find_by_metadata(document.company_id, document.doc_type.value, document.reporting_period)

        if by_hash is not None:
            same_metadata = (
                by_hash.company_id == document.company_id
                and by_hash.doc_type == document.doc_type
                and by_hash.reporting_period == document.reporting_period
            )
            if same_metadata:
                return by_hash, False  # case 1: reuse
            raise DocumentMetadataConflictError(
                f"File with sha256={document.file_sha256} already exists as document {by_hash.id} "
                f"under different metadata ({by_hash.company_id}/{by_hash.doc_type}/{by_hash.reporting_period})."
            )  # case 2

        if by_metadata is not None:
            raise DocumentExistingConflictError(
                f"A document already exists for company_id={document.company_id}, "
                f"doc_type={document.doc_type.value}, reporting_period={document.reporting_period} "
                f"(document {by_metadata.id}) with a different file_sha256."
            )  # case 3

        return self._insert(document), True  # case 4

    def _insert(self, document: Document) -> Document:
        if self._backend() == "supabase":
            client = get_supabase_client()
            try:
                client.table("documents").insert(_to_db_payload(document)).execute()
            except APIError as e:
                if e.code == _UNIQUE_VIOLATION:
                    # Lost a race to a concurrent insert for the same hash or metadata key.
                    existing = self.find_by_sha256(document.file_sha256) or self.find_by_metadata(
                        document.company_id, document.doc_type.value, document.reporting_period
                    )
                    if existing is not None:
                        return existing
                raise
        else:
            self._store.append(document.model_dump(mode="json"))
        return document

    # --- atomic claim / state transitions -------------------------------------------

    def claim_for_ingestion(self, document_id: str) -> Document:
        """Atomically moves a document from pending/failed into 'extracting', the
        concurrency-safe mechanism: a conditional UPDATE ... WHERE ingestion_status
        IN ('pending','failed') - the matched row itself is the lock, not an
        application-level one. Raises DocumentAlreadyClaimedError if no row matched
        (already claimed by another worker, or already completed)."""
        now = now_utc()
        payload = {
            "ingestion_status": IngestionStatus.EXTRACTING.value,
            "ingestion_claimed_at": now.isoformat(),
            "ingestion_error": None,
        }
        if self._backend() == "supabase":
            client = get_supabase_client()
            resp = (
                client.table("documents")
                .update(payload)
                .eq("id", document_id)
                .in_("ingestion_status", list(_CLAIMABLE_STATUSES))
                .execute()
            )
            rows = resp.data or []
            if not rows:
                raise DocumentAlreadyClaimedError(f"Document {document_id} could not be claimed (not pending/failed).")
            return _from_db_row(rows[0])

        records = self._store.read_all()
        for row in records:
            if row.get("id") == document_id and row.get("ingestion_status") in _CLAIMABLE_STATUSES:
                row.update(payload)
                self._store.replace_all(records)
                return Document.model_validate(row)
        raise DocumentAlreadyClaimedError(f"Document {document_id} could not be claimed (not pending/failed).")

    def update_status(self, document_id: str, **fields) -> None:
        """Direct, unconditional status update - used for intra-pipeline transitions
        (extracting -> chunking -> embedding -> completed) after the document has
        already been claimed by this worker, never to move a document OUT of
        pending/failed (claim_for_ingestion is the only path for that)."""
        payload = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in fields.items()}
        if self._backend() == "supabase":
            client = get_supabase_client()
            client.table("documents").update(payload).eq("id", document_id).execute()
        else:
            records = self._store.read_all()
            for row in records:
                if row.get("id") == document_id:
                    row.update(payload)
            self._store.replace_all(records)

    def mark_completed(self, document_id: str) -> None:
        self.update_status(document_id, ingestion_status=IngestionStatus.COMPLETED.value, ingested_at=now_utc())

    def mark_failed(self, document_id: str, error_message: str) -> None:
        """Marks the document failed and deletes any chunks persisted for it so far.
        LIMITATION (documented, not fixed): over supabase-py's REST interface, the
        status update and the chunk delete are two separate HTTP calls, not one
        atomic transaction - a crash between them could leave the document marked
        'failed' with stale chunks still present. delete_chunks_for_document() is
        scoped to the exact document_id and is itself idempotent/safely re-runnable
        (deleting an already-empty set is a no-op), so a retry of mark_failed (or a
        later recovery pass) converges to the correct end state even after such a
        crash - but the two steps are not atomic as written. A dedicated Postgres
        RPC wrapping both in one transaction would close this gap; see the readiness
        report for why that is proposed separately rather than folded into
        migrations 007/008."""
        self.delete_chunks_for_document(document_id)
        self.update_status(document_id, ingestion_status=IngestionStatus.FAILED.value, ingestion_error=error_message)

    # --- chunks --------------------------------------------------------------------

    def insert_chunks(self, chunks: list[DocumentChunk]) -> None:
        if not chunks:
            return
        payloads = [c.model_dump(mode="json") for c in chunks]
        if self._backend() == "supabase":
            client = get_supabase_client()
            client.table("document_chunks").insert(payloads).execute()
        else:
            for payload in payloads:
                self._chunk_store.append(payload)

    def get_chunks_for_document(self, document_id: str) -> list[DocumentChunk]:
        if self._backend() == "supabase":
            client = get_supabase_client()
            resp = client.table("document_chunks").select("*").eq("document_id", document_id).execute()
            return [DocumentChunk.model_validate(r) for r in (resp.data or [])]
        return [
            DocumentChunk.model_validate(r) for r in self._chunk_store.read_all() if r.get("document_id") == document_id
        ]

    def search_chunks_by_keywords(self, company_id: str, terms: list[str], limit: int = 20) -> list[dict]:
        """Case-insensitive substring match over document_chunks.text for ANY of
        `terms`, restricted to this company AND to documents with
        ingestion_status == 'completed' - the same two guarantees
        match_document_chunks (migrations/006/008) enforces for vector search,
        reproduced here over plain REST/JSON reads rather than a new SQL
        function, since the existing documents/document_chunks tables already
        carry everything this needs (CLAUDE.md: don't over-engineer the data
        plumbing). Returns rows pre-joined with citation metadata, shaped like
        the match_document_chunks RPC's own rows (minus distance/similarity,
        which only a real vector comparison can produce) so callers can treat
        both sources uniformly.

        Not full-text search (no stemming/ranking) - a deliberate, documented
        simplification for this prototype's data volume; see the readiness
        report for when a real tsvector/GIN-indexed SQL function would earn its
        complexity.
        """
        if not terms:
            return []
        normalized_terms = [t.lower() for t in terms if t.strip()]
        if not normalized_terms:
            return []

        if self._backend() == "supabase":
            client = get_supabase_client()
            completed_resp = (
                client.table("documents").select("*").eq("company_id", company_id).eq("ingestion_status", "completed").execute()
            )
            completed_docs = {d["id"]: d for d in (completed_resp.data or [])}
            if not completed_docs:
                return []
            matched_chunks: dict[str, dict] = {}
            for term in normalized_terms:
                resp = client.table("document_chunks").select("*").eq("company_id", company_id).ilike("text", f"%{term}%").execute()
                for row in resp.data or []:
                    if row["document_id"] in completed_docs:
                        matched_chunks.setdefault(row["id"], row)
        else:
            completed_docs = {
                d["id"]: d for d in self._store.read_all()
                if d.get("company_id") == company_id and d.get("ingestion_status") == "completed"
            }
            if not completed_docs:
                return []
            matched_chunks = {}
            for row in self._chunk_store.read_all():
                if row.get("company_id") != company_id or row.get("document_id") not in completed_docs:
                    continue
                text_lower = (row.get("text") or "").lower()
                if any(term in text_lower for term in normalized_terms):
                    matched_chunks.setdefault(row["id"], row)

        results = []
        for row in list(matched_chunks.values())[:limit]:
            doc = completed_docs[row["document_id"]]
            ticker = doc.get("company_ticker") or get_ticker(doc["company_id"]) or doc["company_id"]
            results.append(
                {
                    "chunk_id": row["id"],
                    "document_id": row["document_id"],
                    "company_id": row["company_id"],
                    "company_ticker": ticker,
                    "chunk_text": row.get("text"),
                    "chunk_type": row.get("chunk_type", "prose"),
                    "needs_manual_review": row.get("needs_manual_review", False),
                    "page_reference": row.get("page_reference"),
                    "section_label": row.get("section_label"),
                    "doc_type": doc.get("doc_type"),
                    "reporting_period": doc.get("reporting_period"),
                    "original_source_url": doc.get("original_source_url"),
                }
            )
        return results

    def delete_chunks_for_document(self, document_id: str) -> int:
        """Scoped to the exact document_id - never a broader delete. Returns the
        number of chunks removed."""
        if self._backend() == "supabase":
            client = get_supabase_client()
            resp = client.table("document_chunks").delete().eq("document_id", document_id).execute()
            return len(resp.data or [])
        records = self._chunk_store.read_all()
        remaining = [r for r in records if r.get("document_id") != document_id]
        removed = len(records) - len(remaining)
        self._chunk_store.replace_all(remaining)
        return removed

    # --- crash recovery --------------------------------------------------------------

    def find_stale_claims(self, stale_minutes: int = DEFAULT_STALE_CLAIM_MINUTES) -> list[Document]:
        """Documents stuck in a non-terminal status (extracting/chunking/embedding)
        whose ingestion_claimed_at is older than `stale_minutes` - candidates for
        recovery. Never includes 'completed' or 'pending' documents."""
        non_terminal = (IngestionStatus.EXTRACTING.value, IngestionStatus.CHUNKING.value, IngestionStatus.EMBEDDING.value)
        cutoff = now_utc() - timedelta(minutes=stale_minutes)

        if self._backend() == "supabase":
            client = get_supabase_client()
            resp = client.table("documents").select("*").in_("ingestion_status", list(non_terminal)).execute()
            rows = resp.data or []
        else:
            rows = [r for r in self._store.read_all() if r.get("ingestion_status") in non_terminal]

        stale: list[Document] = []
        for row in rows:
            claimed_at = row.get("ingestion_claimed_at")
            if not claimed_at:
                continue
            claimed_dt = datetime.fromisoformat(claimed_at) if isinstance(claimed_at, str) else claimed_at
            if claimed_dt.tzinfo is None:
                claimed_dt = claimed_dt.replace(tzinfo=timezone.utc)
            if claimed_dt < cutoff:
                stale.append(_from_db_row(row) if self._backend() == "supabase" else Document.model_validate(row))
        return stale
