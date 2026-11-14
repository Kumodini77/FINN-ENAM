"""Unit tests for app.services.ingestion - mocked storage (JSON-fallback
DocumentRepository under tmp_path) and a fake embedding provider, so this suite
stays fast. Does not exercise real PDF extraction (see test_pdf_extraction.py /
test_chunking.py for that) or a live Supabase round trip."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import DocumentAlreadyClaimedError
from app.models.document import IngestionStatus
from app.repositories.documents import DocumentRepository
from app.repositories.json_store import JsonListStore
from app.services.chunking import Chunk
from app.services.embeddings.errors import EmbeddingModelUnavailableError
from app.services.ingestion import IngestionError, compute_file_sha256, ingest_document
from app.services.pdf_extraction import PageExtraction, ProseBlock


@pytest.fixture
def repo(tmp_path):
    return DocumentRepository(
        store=JsonListStore(str(tmp_path), "documents.json"),
        chunk_store=JsonListStore(str(tmp_path), "document_chunks.json"),
    )


@pytest.fixture
def fake_pdf(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"%PDF-1.4 fake content for hashing purposes only")
    return str(path)


def _fake_provider():
    provider = MagicMock()
    provider.model_name = "fake-model"
    provider.model_revision = "fake-rev"
    provider.embed.side_effect = lambda texts: [[0.1] * 4 for _ in texts]
    provider.count_tokens.side_effect = lambda text: len(text.split())
    return provider


def test_compute_file_sha256_is_deterministic(fake_pdf):
    assert compute_file_sha256(fake_pdf) == compute_file_sha256(fake_pdf)


def test_missing_file_raises_ingestion_error_before_touching_the_repository(repo, tmp_path):
    provider = _fake_provider()
    with pytest.raises(IngestionError):
        ingest_document(
            file_path=str(tmp_path / "does_not_exist.pdf"),
            company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
            repo=repo, embedding_provider=provider,
        )


def test_non_pdf_extension_is_rejected(repo, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    provider = _fake_provider()
    with pytest.raises(IngestionError):
        ingest_document(
            file_path=str(path), company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
            repo=repo, embedding_provider=provider,
        )


def test_successful_ingestion_marks_document_completed_and_persists_chunks(repo, fake_pdf):
    provider = _fake_provider()
    page = PageExtraction(page_number=1, raw_text="Some prose.", blocks=[ProseBlock(page_number=1, text="Some prose.")])
    with patch("app.services.ingestion.extract_pages", return_value=[page]):
        result = ingest_document(
            file_path=fake_pdf, company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
            repo=repo, embedding_provider=provider,
        )
    assert result.document.ingestion_status == IngestionStatus.COMPLETED
    assert result.chunk_count == 1
    chunks = repo.get_chunks_for_document(result.document.id)
    assert len(chunks) == 1
    assert chunks[0].embedding_model == "fake-model"
    assert chunks[0].embedding_model_revision == "fake-rev"


def test_extraction_failure_marks_document_failed_and_cleans_up_chunks(repo, fake_pdf):
    from app.services.pdf_extraction import PdfExtractionError

    provider = _fake_provider()
    with patch("app.services.ingestion.extract_pages", side_effect=PdfExtractionError("corrupt pdf")):
        with pytest.raises(IngestionError):
            ingest_document(
                file_path=fake_pdf, company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
                reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
                repo=repo, embedding_provider=provider,
            )
    # The candidate document was created+claimed before extraction ran - verify it
    # landed in FAILED, not left stuck mid-pipeline.
    docs = repo._store.read_all()
    assert len(docs) == 1
    assert docs[0]["ingestion_status"] == IngestionStatus.FAILED.value
    assert "corrupt pdf" in docs[0]["ingestion_error"]
    assert repo._chunk_store.read_all() == []


def test_embedding_failure_marks_document_failed(repo, fake_pdf):
    provider = _fake_provider()
    provider.embed.side_effect = EmbeddingModelUnavailableError("model unavailable")
    page = PageExtraction(page_number=1, raw_text="Some prose.", blocks=[ProseBlock(page_number=1, text="Some prose.")])
    with patch("app.services.ingestion.extract_pages", return_value=[page]):
        with pytest.raises(IngestionError):
            ingest_document(
                file_path=fake_pdf, company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
                reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
                repo=repo, embedding_provider=provider,
            )
    docs = repo._store.read_all()
    assert docs[0]["ingestion_status"] == IngestionStatus.FAILED.value


def test_no_chunks_produced_is_a_failure_not_a_silent_empty_success(repo, fake_pdf):
    provider = _fake_provider()
    page = PageExtraction(page_number=1, raw_text="", blocks=[])
    with patch("app.services.ingestion.extract_pages", return_value=[page]):
        with pytest.raises(IngestionError):
            ingest_document(
                file_path=fake_pdf, company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
                reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
                repo=repo, embedding_provider=provider,
            )
    docs = repo._store.read_all()
    assert docs[0]["ingestion_status"] == IngestionStatus.FAILED.value


def test_reingesting_an_already_completed_document_is_a_clean_no_op(repo, fake_pdf):
    provider = _fake_provider()
    page = PageExtraction(page_number=1, raw_text="Some prose.", blocks=[ProseBlock(page_number=1, text="Some prose.")])
    with patch("app.services.ingestion.extract_pages", return_value=[page]):
        first = ingest_document(
            file_path=fake_pdf, company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
            repo=repo, embedding_provider=provider,
        )
        second = ingest_document(
            file_path=fake_pdf, company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
            repo=repo, embedding_provider=provider,
        )
    assert second.document.id == first.document.id
    assert second.chunk_count == first.chunk_count


def test_lost_completion_acknowledgment_does_not_overwrite_a_truly_completed_document(repo, fake_pdf):
    """Simulates mark_completed() actually succeeding server-side but the client
    never seeing the success (e.g. a dropped response) - the generic exception
    handler must re-check real status and report success, not mark a genuinely
    completed document failed and delete its just-persisted chunks."""
    provider = _fake_provider()
    page = PageExtraction(page_number=1, raw_text="Some prose.", blocks=[ProseBlock(page_number=1, text="Some prose.")])
    real_mark_completed = repo.mark_completed

    def flaky_mark_completed(document_id):
        real_mark_completed(document_id)  # the write genuinely succeeds...
        raise ConnectionError("simulated dropped response after a successful write")

    with patch.object(repo, "mark_completed", side_effect=flaky_mark_completed), \
         patch("app.services.ingestion.extract_pages", return_value=[page]):
        result = ingest_document(
            file_path=fake_pdf, company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
            repo=repo, embedding_provider=provider,
        )  # must NOT raise

    assert result.document.ingestion_status == IngestionStatus.COMPLETED
    assert result.chunk_count == 1
    # And the chunk must still be there - not deleted by a false "failed" cleanup.
    assert len(repo.get_chunks_for_document(result.document.id)) == 1


def test_concurrent_ingestion_attempt_on_an_in_progress_document_raises_already_claimed(repo, fake_pdf):
    provider = _fake_provider()
    doc, _ = repo.resolve_or_create(
        __import__("app.models.document", fromlist=["Document"]).Document.model_validate(
            dict(
                id="doc-x", company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
                reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
                fetched_at=datetime.now(timezone.utc), file_sha256=compute_file_sha256(fake_pdf),
            )
        )
    )
    repo.claim_for_ingestion(doc.id)  # simulate another worker already claimed it
    with pytest.raises(DocumentAlreadyClaimedError):
        ingest_document(
            file_path=fake_pdf, company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
            repo=repo, embedding_provider=provider,
        )
