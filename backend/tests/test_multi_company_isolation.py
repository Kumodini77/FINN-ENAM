"""Explicit multi-company regression tests (Phase 1, Task 4): two genuinely
distinct companies' documents/chunks coexisting in the SAME store, verifying
retrieval, document repository lookups, and ticker resolution never leak across
company boundaries - and that ticker-variation (case/whitespace) can't create a
duplicate company or misroute a lookup.
"""

from datetime import datetime, timezone

import pytest

from app.models.document import Document, DocumentChunk
from app.repositories.company_lookup import get_company_id, invalidate_cache
from app.repositories.documents import DocumentRepository, new_document_id, now_utc
from app.repositories.json_store import JsonListStore
from app.services import retrieval
from tests.fakes.fake_supabase import FakeSupabaseClient, patch_supabase_backend

COMPANY_A_ID = "11111111-1111-1111-1111-111111111111"
COMPANY_B_ID = "22222222-2222-2222-2222-222222222222"


# --- JSON-fallback: two companies' documents/chunks coexisting ----------------------


@pytest.fixture
def repo(tmp_path):
    return DocumentRepository(
        store=JsonListStore(str(tmp_path), "documents.json"),
        chunk_store=JsonListStore(str(tmp_path), "document_chunks.json"),
    )


def _doc(company_id, ticker, doc_id, sha256_byte) -> Document:
    return Document.model_validate(
        dict(
            id=doc_id, company_id=company_id, company_ticker=ticker, doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url=f"https://x.invalid/{ticker}.pdf",
            fetched_at=datetime.now(timezone.utc), file_sha256=sha256_byte * 64,
        )
    )


def test_two_companies_documents_do_not_collide_on_dedup_keys(repo):
    """Same doc_type/reporting_period, DIFFERENT companies and DIFFERENT file
    content - must both succeed as fresh inserts, not be mistaken for the same
    document via the (doc_type, reporting_period) half of the uniqueness key."""
    doc_a, created_a = repo.resolve_or_create(_doc(COMPANY_A_ID, "RELIANCE", "doc-a", "a"))
    doc_b, created_b = repo.resolve_or_create(_doc(COMPANY_B_ID, "TCS", "doc-b", "b"))
    assert created_a is True
    assert created_b is True
    assert doc_a.id != doc_b.id
    assert doc_a.company_id != doc_b.company_id


def test_chunks_for_one_company_are_never_returned_for_another(repo):
    doc_a, _ = repo.resolve_or_create(_doc(COMPANY_A_ID, "RELIANCE", "doc-a", "a"))
    doc_b, _ = repo.resolve_or_create(_doc(COMPANY_B_ID, "TCS", "doc-b", "b"))
    repo.insert_chunks([
        DocumentChunk(id="c-a", document_id=doc_a.id, company_id=COMPANY_A_ID, chunk_index=0, text="Reliance revenue grew.", created_at=now_utc()),
        DocumentChunk(id="c-b", document_id=doc_b.id, company_id=COMPANY_B_ID, chunk_index=0, text="TCS revenue grew.", created_at=now_utc()),
    ])
    a_chunks = repo.get_chunks_for_document(doc_a.id)
    b_chunks = repo.get_chunks_for_document(doc_b.id)
    assert {c.id for c in a_chunks} == {"c-a"}
    assert {c.id for c in b_chunks} == {"c-b"}


def test_lexical_search_is_scoped_to_the_requested_company_only(repo):
    """Both companies' documents mention "revenue" - the search must never
    return the other company's chunk even though the keyword matches both."""
    doc_a, _ = repo.resolve_or_create(_doc(COMPANY_A_ID, "RELIANCE", "doc-a", "a"))
    doc_b, _ = repo.resolve_or_create(_doc(COMPANY_B_ID, "TCS", "doc-b", "b"))
    repo.claim_for_ingestion(doc_a.id)
    repo.mark_completed(doc_a.id)
    repo.claim_for_ingestion(doc_b.id)
    repo.mark_completed(doc_b.id)
    repo.insert_chunks([
        DocumentChunk(id="c-a", document_id=doc_a.id, company_id=COMPANY_A_ID, chunk_index=0, text="revenue grew strongly", created_at=now_utc()),
        DocumentChunk(id="c-b", document_id=doc_b.id, company_id=COMPANY_B_ID, chunk_index=0, text="revenue grew strongly", created_at=now_utc()),
    ])

    results_a = repo.search_chunks_by_keywords(COMPANY_A_ID, ["revenue"])
    results_b = repo.search_chunks_by_keywords(COMPANY_B_ID, ["revenue"])

    assert {r["chunk_id"] for r in results_a} == {"c-a"}
    assert {r["chunk_id"] for r in results_b} == {"c-b"}


def test_deleting_one_companys_document_chunks_never_touches_the_others(repo):
    doc_a, _ = repo.resolve_or_create(_doc(COMPANY_A_ID, "RELIANCE", "doc-a", "a"))
    doc_b, _ = repo.resolve_or_create(_doc(COMPANY_B_ID, "TCS", "doc-b", "b"))
    repo.insert_chunks([
        DocumentChunk(id="c-a", document_id=doc_a.id, company_id=COMPANY_A_ID, chunk_index=0, text="x", created_at=now_utc()),
        DocumentChunk(id="c-b", document_id=doc_b.id, company_id=COMPANY_B_ID, chunk_index=0, text="y", created_at=now_utc()),
    ])
    repo.delete_chunks_for_document(doc_a.id)
    assert repo.get_chunks_for_document(doc_a.id) == []
    assert len(repo.get_chunks_for_document(doc_b.id)) == 1


def test_one_companys_failed_ingestion_does_not_affect_the_other(repo):
    doc_a, _ = repo.resolve_or_create(_doc(COMPANY_A_ID, "RELIANCE", "doc-a", "a"))
    doc_b, _ = repo.resolve_or_create(_doc(COMPANY_B_ID, "TCS", "doc-b", "b"))
    repo.claim_for_ingestion(doc_a.id)
    repo.claim_for_ingestion(doc_b.id)
    repo.insert_chunks([DocumentChunk(id="c-b", document_id=doc_b.id, company_id=COMPANY_B_ID, chunk_index=0, text="y", created_at=now_utc())])

    repo.mark_failed(doc_a.id, "simulated extraction failure")

    assert repo.get_by_id(doc_a.id).ingestion_status.value == "failed"
    reloaded_b = repo.get_by_id(doc_b.id)
    assert reloaded_b.ingestion_status.value == "extracting"  # untouched - still mid-pipeline, not failed
    assert len(repo.get_chunks_for_document(doc_b.id)) == 1  # untouched


# --- Supabase (fake client): vector RPC isolation + ticker-variation dedup ---------


def test_cross_company_vector_retrieval_cannot_leak_via_a_malformed_company_id(monkeypatch):
    """Even if the RPC were somehow seeded with a row for another company (it
    never should be - this just proves the service layer doesn't add a second
    leak path), retrieve_relevant_chunks always passes the RESOLVED company_id
    for the ticker asked about, not anything derived from question text."""
    client = FakeSupabaseClient()
    client.tables["companies"] = [
        {"id": COMPANY_A_ID, "ticker": "RELIANCE"},
        {"id": COMPANY_B_ID, "ticker": "TCS"},
    ]
    client.rpc_results["match_document_chunks"] = []
    provider = type("P", (), {"name": "fake", "embed": lambda self, texts: [[0.1] * 384 for _ in texts]})()
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: provider)

    with patch_supabase_backend(client):
        retrieval.retrieve_relevant_chunks("RELIANCE", "What was TCS's revenue?")  # ticker says RELIANCE, question mentions TCS
        fn_name, params = client.rpc_calls[-1]
        assert params["filter_company_id"] == COMPANY_A_ID  # scoped by the TICKER argument, never by question text


def test_duplicate_ticker_variations_resolve_to_the_same_company_id():
    """Case and whitespace variants of the same ticker must resolve to the
    SAME company_id, never silently create/match a different row."""
    client = FakeSupabaseClient()
    client.tables["companies"] = [{"id": COMPANY_A_ID, "ticker": "RELIANCE"}]
    with patch_supabase_backend(client):
        invalidate_cache()
        ids = {get_company_id(v) for v in ["RELIANCE", "reliance", " RELIANCE", "RELIANCE ", " reliance "]}
    assert ids == {COMPANY_A_ID}
