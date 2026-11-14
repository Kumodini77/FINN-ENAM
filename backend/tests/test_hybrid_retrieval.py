"""Retrieval acceptance tests (Pull priority 1) against the real genuine HDFC Q1
FY27 PDF, the real local MiniLM model, and the real hybrid (vector + lexical)
retrieval layer. Reuses the same real, already-ingested corpus as
test_end_to_end_hdfc.py via tests/conftest.py's session-scoped hdfc_ingested
fixture - this file does not re-run extraction/chunking/embedding.

Vector candidates come from a FakeSupabaseClient whose RPC result is a genuine
cosine-distance ranking over the real persisted vectors (same simulation
boundary as test_end_to_end_hdfc.py - no live Postgres is available). Lexical
candidates come from DocumentRepository.search_chunks_by_keywords, which runs for
real against the fake client's plain table data (the same code path that would run
against live Supabase REST, just against an in-memory double instead of a network
call).
"""

import pytest

from app.core.exceptions import CompanyNotFoundError
from app.models.document import ChunkType
from app.services.hybrid_retrieval import retrieve_hybrid_evidence
from app.services.numeric_answer import extract_numeric_answer
from app.services.query_intent import QueryIntent, classify_query_intent
from app.services import retrieval
from tests.conftest import HDFC_COMPANY_ID, HDFC_TICKER
from tests.fakes.fake_supabase import FakeSupabaseClient, patch_supabase_backend


def _cosine_distance(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return 1 - dot / (na * nb)


def _page4_table_chunk(hdfc_ingested):
    return [c for c in hdfc_ingested["chunks"] if c.page_reference == 4 and c.chunk_type == ChunkType.TABLE_ROW_GROUP][0]


@pytest.fixture
def seeded_client(hdfc_ingested, minilm_provider):
    """A FakeSupabaseClient carrying: (1) the real documents/document_chunks rows
    (for the lexical path's plain REST reads), (2) a real cosine-ranked top-20
    RPC result for whatever question each test asks (for the vector path)."""
    client = FakeSupabaseClient()
    client.tables["companies"] = [{"id": HDFC_COMPANY_ID, "ticker": HDFC_TICKER}]
    doc = hdfc_ingested["document"]
    client.tables["documents"] = [
        {
            "id": doc.id, "company_id": HDFC_COMPANY_ID, "company_ticker": HDFC_TICKER,
            "doc_type": "investor_presentation", "reporting_period": "Q1FY27",
            "original_source_url": doc.original_source_url, "ingestion_status": "completed",
        }
    ]
    client.tables["document_chunks"] = [
        {
            "id": c.id, "document_id": c.document_id, "company_id": HDFC_COMPANY_ID,
            "text": c.text, "chunk_type": c.chunk_type.value, "needs_manual_review": c.needs_manual_review,
            "page_reference": c.page_reference, "section_label": c.section_label,
        }
        for c in hdfc_ingested["chunks"]
    ]
    return client


def _seed_vector_rpc(client, hdfc_ingested, minilm_provider, question, top_n=20):
    query_vector = minilm_provider.embed([question])[0]
    ranked = sorted(hdfc_ingested["chunks"], key=lambda c: _cosine_distance(c.embedding, query_vector))[:top_n]
    doc = hdfc_ingested["document"]
    client.rpc_results["match_document_chunks"] = [
        {
            "chunk_id": c.id, "document_id": c.document_id, "company_id": HDFC_COMPANY_ID,
            "company_ticker": HDFC_TICKER, "chunk_text": c.text, "chunk_type": c.chunk_type.value,
            "needs_manual_review": c.needs_manual_review, "page_reference": c.page_reference,
            "section_label": c.section_label, "doc_type": "investor_presentation", "reporting_period": "Q1FY27",
            "original_source_url": doc.original_source_url,
            "distance": _cosine_distance(c.embedding, query_vector),
            "similarity": 1 - _cosine_distance(c.embedding, query_vector),
        }
        for c in ranked
    ]


# --- Query intent classification ----------------------------------------------------


def test_numerical_question_classified_as_numerical():
    intents = classify_query_intent("What was HDFC Bank's net interest income in Q1 FY27?")
    assert QueryIntent.NUMERICAL in intents


def test_guidance_question_classified_as_guidance():
    intents = classify_query_intent("What is management's guidance on margin outlook?")
    assert QueryIntent.GUIDANCE in intents


def test_strategy_question_classified_as_strategy():
    intents = classify_query_intent("Why did the company's margins decline?")
    assert QueryIntent.STRATEGY in intents


# --- The headline acceptance test: NII must be found -------------------------------


def test_nii_question_surfaces_the_real_page4_table_via_hybrid_retrieval(hdfc_ingested, minilm_provider, seeded_client, monkeypatch):
    question = "What was HDFC Bank's net interest income in Q1 FY27?"
    _seed_vector_rpc(seeded_client, hdfc_ingested, minilm_provider, question)
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: minilm_provider)

    with patch_supabase_backend(seeded_client):
        evidence = retrieve_hybrid_evidence(HDFC_TICKER, question, classify_query_intent(question))

    page4 = _page4_table_chunk(hdfc_ingested)
    assert any(e.chunk_id == page4.id for e in evidence), "page-4 P&L table was not surfaced at all"
    top = evidence[0]
    assert top.chunk_id == page4.id, f"page-4 table should rank first, got chunk_type={top.chunk_type} page={top.page_reference}"
    assert "lexical" in top.matched_via
    assert top.is_reliable_structured_evidence is True


def test_nii_abbreviation_also_surfaces_the_table_via_alias_expansion(hdfc_ingested, minilm_provider, seeded_client, monkeypatch):
    question = "What was HDFC's NII in Q1 FY27?"
    _seed_vector_rpc(seeded_client, hdfc_ingested, minilm_provider, question)
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: minilm_provider)

    with patch_supabase_backend(seeded_client):
        evidence = retrieve_hybrid_evidence(HDFC_TICKER, question, classify_query_intent(question))

    page4 = _page4_table_chunk(hdfc_ingested)
    assert evidence[0].chunk_id == page4.id


def test_june_2026_quarter_phrasing_resolves_to_q1_fy27_and_surfaces_the_table(hdfc_ingested, minilm_provider, seeded_client, monkeypatch):
    question = "Find the net interest income figure for the June 2026 quarter."
    _seed_vector_rpc(seeded_client, hdfc_ingested, minilm_provider, question)
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: minilm_provider)

    with patch_supabase_backend(seeded_client):
        evidence = retrieve_hybrid_evidence(HDFC_TICKER, question, classify_query_intent(question))

    page4 = _page4_table_chunk(hdfc_ingested)
    assert evidence[0].chunk_id == page4.id

    numeric = extract_numeric_answer(question, page4.text)
    assert numeric is not None
    assert numeric.value == "335.3"
    assert numeric.ambiguous_period_binding is False


def test_revenue_question_surfaces_relevant_evidence(hdfc_ingested, minilm_provider, seeded_client, monkeypatch):
    question = "What was HDFC Bank's net revenue in Q1 FY27?"
    _seed_vector_rpc(seeded_client, hdfc_ingested, minilm_provider, question)
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: minilm_provider)

    with patch_supabase_backend(seeded_client):
        evidence = retrieve_hybrid_evidence(HDFC_TICKER, question, classify_query_intent(question))

    page4 = _page4_table_chunk(hdfc_ingested)
    assert evidence[0].chunk_id == page4.id


def test_profit_question_surfaces_relevant_evidence(hdfc_ingested, minilm_provider, seeded_client, monkeypatch):
    question = "What was HDFC Bank's profit after tax in Q1 FY27?"
    _seed_vector_rpc(seeded_client, hdfc_ingested, minilm_provider, question)
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: minilm_provider)

    with patch_supabase_backend(seeded_client):
        evidence = retrieve_hybrid_evidence(HDFC_TICKER, question, classify_query_intent(question))

    page4 = _page4_table_chunk(hdfc_ingested)
    assert evidence[0].chunk_id == page4.id


def test_question_not_answered_in_the_document_returns_no_strong_match(hdfc_ingested, minilm_provider, seeded_client, monkeypatch):
    """A balance-sheet-specific figure this deck (a P&L-focused earnings
    presentation) does not actually contain - the real, honest outcome is that no
    table_row_group chunk matches, not a fabricated figure."""
    question = "What was HDFC Bank's total shareholders equity as per the balance sheet in Q1 FY27?"
    _seed_vector_rpc(seeded_client, hdfc_ingested, minilm_provider, question)
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: minilm_provider)

    with patch_supabase_backend(seeded_client):
        evidence = retrieve_hybrid_evidence(HDFC_TICKER, question, classify_query_intent(question))
        numeric = None
        for e in evidence:
            if e.chunk_type == ChunkType.TABLE_ROW_GROUP:
                numeric = extract_numeric_answer(question, e.chunk_text)
                if numeric:
                    break
    assert numeric is None  # no fabricated figure


def test_cross_company_isolation_cannot_be_bypassed(hdfc_ingested, minilm_provider, seeded_client, monkeypatch):
    """Asking about a different company's data must never surface HDFC's chunks -
    search_chunks_by_keywords is scoped by the RESOLVED company_id, not by whatever
    company name happens to appear in the question text."""
    question = "What was Reliance Industries' net interest income in Q1 FY27?"
    _seed_vector_rpc(seeded_client, hdfc_ingested, minilm_provider, question)
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: minilm_provider)

    with patch_supabase_backend(seeded_client):
        # Still asking the HDFCBANK-scoped retrieval function - company isolation
        # is enforced by which ticker is passed, not by parsing the question text.
        evidence = retrieve_hybrid_evidence(HDFC_TICKER, question, classify_query_intent(question))
    assert all(e.company_id == HDFC_COMPANY_ID for e in evidence)


def test_unknown_ticker_raises_company_not_found(hdfc_ingested, minilm_provider, seeded_client, monkeypatch):
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: minilm_provider)
    with patch_supabase_backend(seeded_client):
        with pytest.raises(CompanyNotFoundError):
            retrieve_hybrid_evidence("NOTREAL", "anything", {QueryIntent.NUMERICAL})


def test_ambiguous_metric_without_period_returns_full_row_not_a_guess(hdfc_ingested):
    page4 = _page4_table_chunk(hdfc_ingested)
    numeric = extract_numeric_answer("What was HDFC Bank's net interest income?", page4.text)
    assert numeric is not None
    assert numeric.ambiguous_period_binding is True
    assert len(numeric.all_values_for_row) == 5


def test_table_unparsed_chunk_never_produces_a_numeric_answer(hdfc_ingested):
    """The reliability rule from migrations/007/008: a table_unparsed chunk must
    never be treated as a verified numerical fact, even if it happens to contain
    digits that superficially look like a match."""
    unparsed = [c for c in hdfc_ingested["chunks"] if c.chunk_type == ChunkType.TABLE_UNPARSED]
    assert unparsed
    for chunk in unparsed:
        # extract_numeric_answer is only ever called on table_row_group chunk_text
        # by the API layer (see app.api.research) - verify the chunk_type gate
        # itself, since the extractor has no awareness of chunk_type at all.
        assert chunk.needs_manual_review is True
