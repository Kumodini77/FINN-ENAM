"""End-to-end document ingestion: validate -> hash -> dedup -> claim -> extract ->
classify -> chunk -> embed -> persist -> complete, with failure cleanup.

A document is marked 'completed' only if every page extracted without raising, every
generated chunk passed its token-limit validation, and every chunk was embedded and
persisted successfully - a partial failure anywhere leaves the document 'failed' with
its chunks cleaned up, never silently 'completed' with missing evidence.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import DocumentAlreadyClaimedError
from app.models.document import Document, DocumentChunk, IngestionStatus
from app.repositories.documents import DocumentRepository, new_document_id, now_utc
from app.services.chunking import ChunkingError, chunk_document
from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.errors import EmbeddingModelUnavailableError
from app.services.pdf_extraction import PdfExtractionError, extract_pages

logger = logging.getLogger("finn.services.ingestion")


class IngestionError(Exception):
    """A clean, already-persisted-as-failed error from the ingestion pipeline. The
    original cause is chained via `__cause__`."""


@dataclass
class IngestionResult:
    document: Document
    chunk_count: int
    reused: bool = False
    """True when this call found an already-completed document for the same
    content (same file_sha256 + same metadata) and returned it as-is rather than
    running the pipeline again - lets a caller (e.g. the CLI) report "already
    ingested" distinctly from a fresh run, without re-deriving that from status
    alone."""


def compute_file_sha256(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _safe_mark_failed(repo: DocumentRepository, document_id: str, error_message: str) -> None:
    """Guards against a narrow but real ambiguous-acknowledgment race: if
    repo.mark_completed() actually succeeded server-side but the client never
    received/processed that success (e.g. a dropped response after a genuine write),
    the code below would otherwise land in the generic exception handler and call
    this with a document that is, in truth, already completed. Overwriting that
    would delete real, successfully-persisted chunks and mark a finished document
    'failed' for no reason. Re-reads the document's actual current status first and
    does nothing if it is already COMPLETED."""
    current = repo.get_by_id(document_id)
    if current is not None and current.ingestion_status == IngestionStatus.COMPLETED:
        logger.warning(
            "Document %s is already COMPLETED despite an error being raised after that point "
            "(likely a lost success acknowledgment) - leaving it completed, not marking it failed.",
            document_id,
        )
        return
    repo.mark_failed(document_id, error_message)


def _validate_input_file(file_path: str) -> None:
    path = Path(file_path)
    if not path.is_file():
        raise IngestionError(f"File not found: {file_path}")
    if path.suffix.lower() != ".pdf":
        raise IngestionError(f"Only .pdf files are supported, got: {file_path}")
    if path.stat().st_size == 0:
        raise IngestionError(f"File is empty: {file_path}")


def ingest_document(
    *,
    file_path: str,
    company_id: str,
    company_ticker: str,
    doc_type,
    reporting_period: str | None,
    original_source_url: str,
    repo: DocumentRepository,
    embedding_provider: EmbeddingProvider,
) -> IngestionResult:
    """Runs the full pipeline for one PDF. Raises IngestionError on any failure
    after the document has been created/claimed (the document itself is left in
    'failed' status with its chunks cleaned up); raises the repository's own
    conflict/claim exceptions (DocumentMetadataConflictError,
    DocumentExistingConflictError, DocumentAlreadyClaimedError) unchanged if the
    pipeline never got as far as claiming a document to work on."""
    _validate_input_file(file_path)

    file_sha256 = compute_file_sha256(file_path)
    candidate = Document(
        id=new_document_id(),
        company_id=company_id,
        company_ticker=company_ticker,
        doc_type=doc_type,
        reporting_period=reporting_period,
        original_source_url=original_source_url,
        source="manual_seed",
        file_path=file_path,
        fetched_at=now_utc(),
        file_sha256=file_sha256,
    )
    document, created = repo.resolve_or_create(candidate)

    if not created and document.ingestion_status == IngestionStatus.COMPLETED:
        logger.info("Document %s already completed; skipping re-ingestion.", document.id)
        chunks = repo.get_chunks_for_document(document.id)
        return IngestionResult(document=document, chunk_count=len(chunks), reused=True)

    claimed = repo.claim_for_ingestion(document.id)  # raises DocumentAlreadyClaimedError if not pending/failed

    try:
        repo.update_status(claimed.id, ingestion_status=IngestionStatus.EXTRACTING.value)
        pages = extract_pages(file_path)

        repo.update_status(claimed.id, ingestion_status=IngestionStatus.CHUNKING.value)
        chunks = chunk_document(pages, embedding_provider)
        if not chunks:
            raise IngestionError(f"No chunks were produced from {file_path} - refusing to mark it completed.")

        repo.update_status(claimed.id, ingestion_status=IngestionStatus.EMBEDDING.value)
        vectors = embedding_provider.embed([c.text for c in chunks])
        if len(vectors) != len(chunks):
            raise IngestionError(
                f"Embedding provider returned {len(vectors)} vectors for {len(chunks)} chunks - refusing to persist a mismatched set."
            )

        document_chunks = [
            DocumentChunk(
                id=new_document_id(),
                document_id=claimed.id,
                company_id=company_id,
                chunk_index=idx,
                text=chunk.text,
                page_reference=chunk.page_number,
                section_label=chunk.section_label,
                embedding=vector,
                created_at=now_utc(),
                embedding_model=embedding_provider.model_name,
                embedding_model_revision=embedding_provider.model_revision,
                chunk_type=chunk.chunk_type,
                needs_manual_review=chunk.needs_manual_review,
            )
            for idx, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]
        repo.insert_chunks(document_chunks)
        repo.mark_completed(claimed.id)
        return IngestionResult(document=repo.get_by_id(claimed.id), chunk_count=len(document_chunks))

    except (PdfExtractionError, ChunkingError, EmbeddingModelUnavailableError, IngestionError) as e:
        error_message = str(e)
        current = repo.get_by_id(claimed.id)
        if current is not None and current.ingestion_status == IngestionStatus.COMPLETED:
            # The error happened after completion actually succeeded server-side
            # (e.g. mark_completed()'s own response was lost) - see
            # _safe_mark_failed's docstring. Report the real, already-persisted
            # result instead of a fabricated failure.
            chunks = repo.get_chunks_for_document(claimed.id)
            return IngestionResult(document=current, chunk_count=len(chunks))
        _safe_mark_failed(repo, claimed.id, error_message)
        raise IngestionError(f"Ingestion failed for document {claimed.id}: {error_message}") from e
    except Exception as e:
        # Any other unexpected failure still must not leave the document stuck
        # mid-pipeline with no explanation - mark failed with a real message, never
        # a fabricated "succeeded".
        logger.exception("Unexpected error ingesting document %s", claimed.id)
        current = repo.get_by_id(claimed.id)
        if current is not None and current.ingestion_status == IngestionStatus.COMPLETED:
            chunks = repo.get_chunks_for_document(claimed.id)
            return IngestionResult(document=current, chunk_count=len(chunks))
        _safe_mark_failed(repo, claimed.id, f"Unexpected error: {e}")
        raise IngestionError(f"Ingestion failed for document {claimed.id}: {e}") from e
