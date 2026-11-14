"""Unit tests for app.services.retrieval - mocked Supabase RPC and a fake embedding
provider, so this suite stays fast and network/model-free. Live, non-mocked
verification against the real Supabase RPC and the real local model is a separate,
explicitly-run integration check (not part of the default test suite) - see the
PHASE 2 live verification report for that.
"""

from unittest.mock import MagicMock

import pytest
from postgrest import APIError

from app.core.exceptions import CompanyNotFoundError, RetrievalQueryError, RetrievalUnavailableError
from app.services import retrieval
from tests.fakes.fake_supabase import FakeSupabaseClient, patch_supabase_backend

COMPANY_ID = "11111111-1111-1111-1111-111111111111"


def _fake_provider(vector=None):
    provider = MagicMock()
    provider.name = "sentence-transformers/all-MiniLM-L6-v2@1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    provider.embed.side_effect = lambda texts: [vector or [0.1] * 384 for _ in texts]
    return provider


def _client_with_company(ticker=COMPANY_ID):
    client = FakeSupabaseClient()
    client.tables["companies"] = [{"id": COMPANY_ID, "ticker": "RELIANCE"}]
    return client


def _row(**overrides):
    row = {
        "chunk_id": "c1",
        "document_id": "d1",
        "company_id": COMPANY_ID,
        "company_ticker": "RELIANCE",
        "chunk_text": "Revenue grew 15% YoY.",
        "page_reference": 4,
        "section_label": "MD&A",
        "doc_type": "annual_report",
        "reporting_period": "FY2025-26",
        "original_source_url": "https://example.invalid/ar.pdf",
        "distance": 0.2,
        "similarity": 0.8,
    }
    row.update(overrides)
    return row


def test_resolves_ticker_and_passes_the_real_company_id_to_the_rpc(monkeypatch):
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = [_row()]
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks("reliance", "What was revenue growth?")
    assert result.company_id == COMPANY_ID
    assert result.company_ticker == "RELIANCE"
    fn_name, params = client.rpc_calls[0]
    assert fn_name == "match_document_chunks"
    assert params["filter_company_id"] == COMPANY_ID


def test_unknown_ticker_raises_company_not_found_without_calling_the_rpc(monkeypatch):
    client = _client_with_company()
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        with pytest.raises(CompanyNotFoundError):
            retrieval.retrieve_relevant_chunks("NOTREAL", "anything")
    assert client.rpc_calls == []


def test_json_fallback_backend_raises_retrieval_unavailable_not_a_silent_degrade(monkeypatch):
    client = _client_with_company()
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        import app.services.retrieval as mod

        mod_backend = MagicMock(return_value="json_fallback")
        monkeypatch.setattr(mod, "storage_backend_name", mod_backend)
        with pytest.raises(RetrievalUnavailableError):
            retrieval.retrieve_relevant_chunks("RELIANCE", "anything")


def test_query_embedding_is_generated_with_the_configured_provider_and_sent_to_the_rpc(monkeypatch):
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = []
    vector = [0.42] * 384
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider(vector))
    with patch_supabase_backend(client):
        retrieval.retrieve_relevant_chunks("RELIANCE", "What was revenue growth?")
    _, params = client.rpc_calls[0]
    assert params["query_embedding"] == vector


def test_match_count_omitted_by_default_so_the_rpc_applies_its_own_default(monkeypatch):
    """match_count=None (the service's default) must OMIT the key entirely, not
    send an explicit None - migrations/006 rejects an explicit NULL."""
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = []
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        retrieval.retrieve_relevant_chunks("RELIANCE", "anything")
    _, params = client.rpc_calls[0]
    assert "match_count" not in params


def test_explicit_match_count_is_passed_through(monkeypatch):
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = []
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        retrieval.retrieve_relevant_chunks("RELIANCE", "anything", match_count=3)
    _, params = client.rpc_calls[0]
    assert params["match_count"] == 3


def test_returned_rows_are_validated_into_schema_and_preserve_rpc_order(monkeypatch):
    """Ranking happened inside Postgres - this just validates shape, it must not
    re-sort anything."""
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = [
        _row(chunk_id="first", distance=0.1),
        _row(chunk_id="second", distance=0.5),
    ]
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks("RELIANCE", "anything")
    assert [c.chunk_id for c in result.chunks] == ["first", "second"]
    assert result.chunks[0].distance == 0.1


def test_empty_rpc_result_is_a_clean_empty_list_not_an_error(monkeypatch):
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = []
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks("RELIANCE", "anything")
    assert result.chunks == []


def test_rpc_api_error_is_wrapped_not_leaked_raw(monkeypatch):
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = APIError(
        {"message": "match_document_chunks: filter_company_id is required and cannot be NULL", "code": "P0001", "hint": None, "details": None}
    )
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        with pytest.raises(RetrievalQueryError):
            retrieval.retrieve_relevant_chunks("RELIANCE", "anything")


def test_row_without_chunk_type_columns_still_validates_backward_compat(monkeypatch):
    """A row shaped like the CURRENTLY LIVE migration 006 (no chunk_type/
    needs_manual_review columns at all) must still validate cleanly - this is the
    exact shape the live RPC returns today, before migration 008 is applied."""
    client = _client_with_company()
    row = _row()
    assert "chunk_type" not in row and "needs_manual_review" not in row
    client.rpc_results["match_document_chunks"] = [row]
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks("RELIANCE", "anything")
    chunk = result.chunks[0]
    assert chunk.chunk_type == "prose"
    assert chunk.needs_manual_review is False
    assert chunk.is_reliable_structured_evidence is True


def test_prose_chunk_is_reliable_structured_evidence(monkeypatch):
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = [_row(chunk_type="prose", needs_manual_review=False)]
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks("RELIANCE", "anything")
    assert result.chunks[0].is_reliable_structured_evidence is True


def test_table_row_group_chunk_is_reliable_structured_evidence(monkeypatch):
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = [_row(chunk_type="table_row_group", needs_manual_review=False)]
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks("RELIANCE", "anything")
    chunk = result.chunks[0]
    assert chunk.chunk_type == "table_row_group"
    assert chunk.is_reliable_structured_evidence is True


def test_table_unparsed_chunk_is_visibly_distinguishable_and_never_reliable(monkeypatch):
    """The research layer must never mistake a table_unparsed chunk for verified
    structured evidence, even if needs_manual_review were somehow False - chunk_type
    == table_unparsed alone is enough to mark it unreliable."""
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = [_row(chunk_type="table_unparsed", needs_manual_review=True)]
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks("RELIANCE", "anything")
    chunk = result.chunks[0]
    assert chunk.chunk_type == "table_unparsed"
    assert chunk.needs_manual_review is True
    assert chunk.is_reliable_structured_evidence is False


def test_needs_manual_review_true_is_never_reliable_regardless_of_chunk_type(monkeypatch):
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = [_row(chunk_type="prose", needs_manual_review=True)]
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks("RELIANCE", "anything")
    assert result.chunks[0].is_reliable_structured_evidence is False


def test_company_isolation_and_ranking_order_unaffected_by_new_fields(monkeypatch):
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = [
        _row(chunk_id="first", distance=0.1, chunk_type="table_row_group", needs_manual_review=False),
        _row(chunk_id="second", distance=0.5, chunk_type="table_unparsed", needs_manual_review=True),
    ]
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks("RELIANCE", "anything")
    assert [c.chunk_id for c in result.chunks] == ["first", "second"]
    assert result.company_id == COMPANY_ID
    fn_name, params = client.rpc_calls[0]
    assert params["filter_company_id"] == COMPANY_ID


def test_citation_metadata_fields_round_trip_into_the_schema(monkeypatch):
    client = _client_with_company()
    client.rpc_results["match_document_chunks"] = [
        _row(page_reference=7, section_label="Dividend Policy", original_source_url="https://example.invalid/x.pdf")
    ]
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: _fake_provider())
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks("RELIANCE", "anything")
    chunk = result.chunks[0]
    assert chunk.page_reference == 7
    assert chunk.section_label == "Dividend Policy"
    assert chunk.original_source_url == "https://example.invalid/x.pdf"
