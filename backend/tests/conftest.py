"""Shared fixtures for the real-HDFC-PDF test suites (test_end_to_end_hdfc.py,
test_hybrid_retrieval.py) - session-scoped so the real model load + real 36-page
extraction + real embedding of ~200 chunks happens exactly once per test run, not
once per test file."""

from pathlib import Path

import pytest

from app.models.document import Document, DocumentChunk
from app.repositories.documents import DocumentRepository, new_document_id, now_utc
from app.repositories.json_store import JsonListStore
from app.services.chunking import chunk_document
from app.services.embeddings.local_minilm import LocalMiniLMEmbeddingProvider
from app.services.ingestion import compute_file_sha256
from app.services.pdf_extraction import extract_pages

HDFC_PDF = Path(__file__).parent.parent.parent / "scripts" / "spikes" / "fundamentals_access_spike" / "documents" / "hdfcbank_earnings_presentation.pdf"
HDFC_TICKER = "HDFCBANK"
HDFC_COMPANY_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(scope="session")
def minilm_provider(tmp_path_factory):
    if not HDFC_PDF.exists():
        pytest.skip(f"Real HDFC PDF fixture not present at {HDFC_PDF}")
    cache_dir = tmp_path_factory.mktemp("shared_embedding_cache")
    return LocalMiniLMEmbeddingProvider(cache_dir=str(cache_dir))


@pytest.fixture(scope="session")
def hdfc_ingested(tmp_path_factory, minilm_provider):
    data_dir = tmp_path_factory.mktemp("shared_hdfc_storage")
    repo = DocumentRepository(
        store=JsonListStore(str(data_dir), "documents.json"),
        chunk_store=JsonListStore(str(data_dir), "document_chunks.json"),
    )

    file_sha256 = compute_file_sha256(str(HDFC_PDF))
    candidate = Document(
        id=new_document_id(), company_id=HDFC_COMPANY_ID, company_ticker=HDFC_TICKER,
        doc_type="investor_presentation", reporting_period="Q1FY27",
        original_source_url="https://www.hdfc.bank.in/content/dam/hdfcbankpws/in/en/pdf/about-us/financial-results/2026-2027/quarter-1/q1fy27-earnings-presentation.pdf",
        source="manual_seed", file_path=str(HDFC_PDF), fetched_at=now_utc(), file_sha256=file_sha256,
    )
    document, created = repo.resolve_or_create(candidate)
    claimed = repo.claim_for_ingestion(document.id)

    pages = extract_pages(str(HDFC_PDF))
    chunks = chunk_document(pages, minilm_provider)
    vectors = minilm_provider.embed([c.text for c in chunks])

    document_chunks = [
        DocumentChunk(
            id=new_document_id(), document_id=claimed.id, company_id=HDFC_COMPANY_ID, chunk_index=idx,
            text=chunk.text, page_reference=chunk.page_number, embedding=vector, created_at=now_utc(),
            embedding_model=minilm_provider.model_name, embedding_model_revision=minilm_provider.model_revision,
            chunk_type=chunk.chunk_type, needs_manual_review=chunk.needs_manual_review,
        )
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    repo.insert_chunks(document_chunks)
    repo.mark_completed(claimed.id)

    return {
        "repo": repo, "document": repo.get_by_id(claimed.id), "pages": pages,
        "chunks": repo.get_chunks_for_document(claimed.id), "file_sha256": file_sha256,
    }
