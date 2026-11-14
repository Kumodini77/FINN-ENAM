"""Unit tests for app.repositories.documents - mocked Supabase (FakeSupabaseClient)
and real JSON-fallback storage via tmp_path, so this suite stays fast and
network/database-free. Describes the TARGET schema (migrations/007/008 not yet
applied) - these tests validate the repository's own logic, not a live round trip."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import DocumentAlreadyClaimedError, DocumentExistingConflictError, DocumentMetadataConflictError
from app.models.document import ChunkType, Document, DocumentChunk, IngestionStatus
from app.repositories.documents import DocumentRepository
from app.repositories.json_store import JsonListStore
from tests.fakes.fake_supabase import FakeSupabaseClient, patch_supabase_backend

COMPANY_ID = "11111111-1111-1111-1111-111111111111"
OTHER_COMPANY_ID = "22222222-2222-2222-2222-222222222222"


def _doc(**overrides) -> Document:
    base = dict(
        id="doc-1",
        company_id=COMPANY_ID,
        company_ticker="RELIANCE",
        doc_type="annual_report",
        reporting_period="FY2025-26",
        original_source_url="https://example.invalid/ar.pdf",
        fetched_at=datetime.now(timezone.utc),
        file_sha256="a" * 64,
    )
    base.update(overrides)
    return Document.model_validate(base)


# --- JSON fallback -----------------------------------------------------------------


@pytest.fixture
def json_repo(tmp_path):
    return DocumentRepository(
        store=JsonListStore(str(tmp_path), "documents.json"),
        chunk_store=JsonListStore(str(tmp_path), "document_chunks.json"),
    )


def test_fresh_insert_when_neither_hash_nor_metadata_exist(json_repo):
    doc, created = json_repo.resolve_or_create(_doc())
    assert created is True
    assert json_repo.get_by_id(doc.id) is not None


def test_same_hash_same_metadata_reuses_existing_document(json_repo):
    first, _ = json_repo.resolve_or_create(_doc())
    second, created = json_repo.resolve_or_create(_doc(id="doc-2"))  # same hash+metadata, different candidate id
    assert created is False
    assert second.id == first.id


def test_same_hash_different_metadata_raises_metadata_conflict(json_repo):
    json_repo.resolve_or_create(_doc())
    with pytest.raises(DocumentMetadataConflictError):
        json_repo.resolve_or_create(_doc(id="doc-2", reporting_period="FY2026-27"))


def test_different_hash_same_metadata_raises_existing_conflict(json_repo):
    json_repo.resolve_or_create(_doc())
    with pytest.raises(DocumentExistingConflictError):
        json_repo.resolve_or_create(_doc(id="doc-2", file_sha256="b" * 64))


def test_never_overwrites_a_different_existing_document_on_metadata_match(json_repo):
    original, _ = json_repo.resolve_or_create(_doc())
    try:
        json_repo.resolve_or_create(_doc(id="doc-2", file_sha256="b" * 64))
    except DocumentExistingConflictError:
        pass
    reloaded = json_repo.get_by_id(original.id)
    assert reloaded.file_sha256 == original.file_sha256


def test_atomic_claim_moves_pending_document_to_extracting(json_repo):
    doc, _ = json_repo.resolve_or_create(_doc())
    claimed = json_repo.claim_for_ingestion(doc.id)
    assert claimed.ingestion_status == IngestionStatus.EXTRACTING
    assert claimed.ingestion_claimed_at is not None


def test_claiming_an_already_claimed_document_raises(json_repo):
    doc, _ = json_repo.resolve_or_create(_doc())
    json_repo.claim_for_ingestion(doc.id)
    with pytest.raises(DocumentAlreadyClaimedError):
        json_repo.claim_for_ingestion(doc.id)


def test_claiming_a_completed_document_raises(json_repo):
    doc, _ = json_repo.resolve_or_create(_doc())
    json_repo.claim_for_ingestion(doc.id)
    json_repo.mark_completed(doc.id)
    with pytest.raises(DocumentAlreadyClaimedError):
        json_repo.claim_for_ingestion(doc.id)


def test_failed_document_can_be_reclaimed(json_repo):
    doc, _ = json_repo.resolve_or_create(_doc())
    json_repo.claim_for_ingestion(doc.id)
    json_repo.mark_failed(doc.id, "simulated failure")
    reclaimed = json_repo.claim_for_ingestion(doc.id)
    assert reclaimed.ingestion_status == IngestionStatus.EXTRACTING


def test_mark_failed_cleans_up_only_this_documents_chunks(json_repo):
    doc_a, _ = json_repo.resolve_or_create(_doc())
    doc_b, _ = json_repo.resolve_or_create(_doc(id="doc-2", file_sha256="b" * 64, reporting_period="FY2026-27"))
    json_repo.insert_chunks(
        [
            DocumentChunk(id="c1", document_id=doc_a.id, company_id=COMPANY_ID, chunk_index=0, text="a", created_at=datetime.now(timezone.utc)),
            DocumentChunk(id="c2", document_id=doc_b.id, company_id=COMPANY_ID, chunk_index=0, text="b", created_at=datetime.now(timezone.utc)),
        ]
    )
    json_repo.mark_failed(doc_a.id, "boom")
    assert json_repo.get_chunks_for_document(doc_a.id) == []
    assert len(json_repo.get_chunks_for_document(doc_b.id)) == 1


def test_mark_failed_sets_error_message_and_status(json_repo):
    doc, _ = json_repo.resolve_or_create(_doc())
    json_repo.claim_for_ingestion(doc.id)
    json_repo.mark_failed(doc.id, "pdf extraction crashed")
    reloaded = json_repo.get_by_id(doc.id)
    assert reloaded.ingestion_status == IngestionStatus.FAILED
    assert reloaded.ingestion_error == "pdf extraction crashed"


def test_mark_completed_sets_status_and_ingested_at(json_repo):
    doc, _ = json_repo.resolve_or_create(_doc())
    json_repo.claim_for_ingestion(doc.id)
    json_repo.mark_completed(doc.id)
    reloaded = json_repo.get_by_id(doc.id)
    assert reloaded.ingestion_status == IngestionStatus.COMPLETED
    assert reloaded.ingested_at is not None


def test_find_stale_claims_only_returns_non_terminal_documents_past_the_threshold(json_repo):
    doc, _ = json_repo.resolve_or_create(_doc())
    json_repo.claim_for_ingestion(doc.id)
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
    json_repo.update_status(doc.id, ingestion_claimed_at=stale_time)
    stale = json_repo.find_stale_claims(stale_minutes=60)
    assert len(stale) == 1
    assert stale[0].id == doc.id


def test_find_stale_claims_excludes_recently_claimed_documents(json_repo):
    doc, _ = json_repo.resolve_or_create(_doc())
    json_repo.claim_for_ingestion(doc.id)  # claimed "now"
    stale = json_repo.find_stale_claims(stale_minutes=60)
    assert stale == []


def test_find_stale_claims_excludes_completed_documents(json_repo):
    doc, _ = json_repo.resolve_or_create(_doc())
    json_repo.claim_for_ingestion(doc.id)
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
    json_repo.update_status(doc.id, ingestion_claimed_at=stale_time, ingestion_status=IngestionStatus.COMPLETED.value)
    stale = json_repo.find_stale_claims(stale_minutes=60)
    assert stale == []


def test_insert_and_retrieve_chunks_round_trip(json_repo):
    doc, _ = json_repo.resolve_or_create(_doc())
    chunk = DocumentChunk(
        id="c1", document_id=doc.id, company_id=COMPANY_ID, chunk_index=0, text="Revenue grew.",
        created_at=datetime.now(timezone.utc), chunk_type=ChunkType.PROSE,
    )
    json_repo.insert_chunks([chunk])
    retrieved = json_repo.get_chunks_for_document(doc.id)
    assert len(retrieved) == 1
    assert retrieved[0].text == "Revenue grew."


# --- Supabase (fake client) ---------------------------------------------------------


def _fake_client_with_company():
    client = FakeSupabaseClient()
    client.tables["companies"] = [{"id": COMPANY_ID, "ticker": "RELIANCE"}]
    return client


def test_supabase_strips_company_ticker_before_insert_and_resolves_it_on_read():
    client = _fake_client_with_company()
    repo = DocumentRepository()
    with patch_supabase_backend(client):
        doc, created = repo.resolve_or_create(_doc())
        assert created is True
        inserted_row = client.tables["documents"][0]
        assert "company_ticker" not in inserted_row
        reloaded = repo.get_by_id(doc.id)
        assert reloaded.company_ticker == "RELIANCE"


def test_supabase_atomic_claim_uses_conditional_update_with_in_filter():
    client = _fake_client_with_company()
    repo = DocumentRepository()
    with patch_supabase_backend(client):
        doc, _ = repo.resolve_or_create(_doc())
        claimed = repo.claim_for_ingestion(doc.id)
        assert claimed.ingestion_status == IngestionStatus.EXTRACTING
        with pytest.raises(DocumentAlreadyClaimedError):
            repo.claim_for_ingestion(doc.id)


def test_supabase_same_hash_same_metadata_reuses_without_a_second_insert():
    client = _fake_client_with_company()
    repo = DocumentRepository()
    with patch_supabase_backend(client):
        repo.resolve_or_create(_doc())
        repo.resolve_or_create(_doc(id="doc-2"))
        assert len(client.tables["documents"]) == 1
