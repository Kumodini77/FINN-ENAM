"""In-process data models for the RAG document corpus (annual reports, concall
transcripts, investor presentations) and their embedded chunks.

These mirror backend/migrations/001_init.sql (documents, document_chunks) plus the
additive ingestion-tracking/embedding-provenance/chunk-classification columns
proposed in 007_document_ingestion_tracking.sql, field-for-field. They are the shape
used by both storage backends (Supabase and the JSON-file fallback — see
app/repositories/), so switching backends later doesn't change anything above this
layer.

Nothing here should be constructed until migrations 007 (and, for retrieval,
008) are actually applied — these models describe columns that do not exist in the
live database yet.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class DocType(str, Enum):
    ANNUAL_REPORT = "annual_report"
    CONCALL_TRANSCRIPT = "concall_transcript"
    INVESTOR_PRESENTATION = "investor_presentation"


class SourceType(str, Enum):
    """Mirrors app.models.announcement.SourceType / migrations' shared
    data_source_type enum — every document row says which path produced it."""

    LIVE = "live"
    CACHED = "cached"
    MANUAL_SEED = "manual_seed"


class IngestionStatus(str, Enum):
    """migrations/007_document_ingestion_tracking.sql's documents.ingestion_status.
    A worker may only move a document OUT of PENDING or FAILED via the repository's
    atomic claim (a conditional UPDATE ... WHERE ingestion_status IN ('pending',
    'failed')) - never by constructing/assigning this enum value directly."""

    PENDING = "pending"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"


class ChunkType(str, Enum):
    """migrations/007_document_ingestion_tracking.sql's document_chunks.chunk_type.

    PROSE: ordinary extracted text.
    TABLE_ROW_GROUP: confidently parsed into rows/columns; the chunk's own header
        row is repeated in chunk_text alongside its data row(s).
    TABLE_UNPARSED: looked table-like (e.g. numeric-heavy, or chart-adjacent text
        pdfplumber's reading order garbled) but could NOT be confidently structured
        into rows/columns. Raw extracted text is preserved verbatim in chunk_text -
        never invented structure. Always paired with needs_manual_review=True
        (enforced by a database check constraint, not just application convention).
    """

    PROSE = "prose"
    TABLE_ROW_GROUP = "table_row_group"
    TABLE_UNPARSED = "table_unparsed"


class Document(BaseModel):
    id: str
    company_id: str
    company_ticker: str
    """Not a real column on `documents` (which stores company_id, a uuid FK) - see
    Announcement's identical pattern: resolved via app.repositories.company_lookup
    at the repository boundary so every layer above it keeps working in tickers."""
    doc_type: DocType
    reporting_period: str | None = None
    period_end_date: date | None = None
    original_source_url: str
    discovered_via: str | None = None
    source: SourceType = SourceType.MANUAL_SEED
    file_path: str | None = None
    page_count: int | None = None
    publication_date: date | None = None
    fetched_at: datetime

    # --- migrations/007 additions ---
    file_sha256: str | None = None
    """SHA-256 of the actual source file bytes. The content-based idempotency key -
    see app/repositories/documents.py's four-case conflict logic (reuse / metadata
    conflict / existing-document conflict / fresh insert), never a raw DB constraint
    violation surfaced directly to a caller."""
    ingestion_status: IngestionStatus = IngestionStatus.PENDING
    ingestion_error: str | None = None
    """Set only when ingestion_status == FAILED. The real, sanitized error message -
    never fabricated, cleared when a retry successfully re-claims this document."""
    ingested_at: datetime | None = None
    ingestion_claimed_at: datetime | None = None
    """Set on every successful atomic claim. A non-terminal status whose claim
    timestamp is older than the recovery script's stale threshold (60 minutes by
    default) indicates a crashed worker."""


class DocumentChunk(BaseModel):
    id: str
    document_id: str
    company_id: str
    """Denormalized for retrieval pre-filtering (same as the live schema) - the
    repository/ingestion pipeline must always set this to the SAME value as the
    parent document's company_id; migrations/006+008's match_document_chunks RPC
    independently re-verifies this agreement at query time rather than trusting it."""
    chunk_index: int
    text: str
    page_reference: int | None = None
    """The real 1-based PDF page number this chunk came from. Never crosses a page
    boundary - a chunk's text is always drawn from exactly one page."""
    section_label: str | None = None
    embedding: list[float] | None = None
    """None until the embedding stage completes. When set, must be exactly 384
    dimensions (LocalMiniLMEmbeddingProvider.dimension) - enforced by the live
    vector(384) column type itself (migrations/005), not re-checked here."""
    created_at: datetime

    # --- migrations/007 additions ---
    embedding_model: str | None = None
    """The embedding provider's model_name property (e.g.
    "sentence-transformers/all-MiniLM-L6-v2") - never derived by splitting
    provider.name. Required (by a database check constraint) whenever embedding is
    set."""
    embedding_model_revision: str | None = None
    """The embedding provider's model_revision property (e.g. the pinned HF commit
    SHA) - never derived by splitting provider.name. Required (by a database check
    constraint) whenever embedding is set."""
    chunk_type: ChunkType = ChunkType.PROSE
    needs_manual_review: bool = False
    """Always True when chunk_type == TABLE_UNPARSED (enforced by a database check
    constraint). May be set True for other low-confidence extractions in the
    future. app.services.retrieval must surface this to callers, not hide it -
    FINN's Pull-side synthesis is expected to treat such evidence differently
    (or exclude it) rather than presenting it as equally reliable structured data."""


__all__ = [
    "ChunkType",
    "Document",
    "DocumentChunk",
    "DocType",
    "IngestionStatus",
    "SourceType",
]
