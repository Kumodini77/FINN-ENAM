"""Full local end-to-end ingestion + retrieval test against the genuine HDFC Q1 FY27
PDF and the real local MiniLM model (ingestion itself happens once, in
tests/conftest.py's session-scoped hdfc_ingested fixture, shared with
test_hybrid_retrieval.py). Storage is isolated under tmp_path (auto-cleaned by
pytest - nothing written outside it, nothing left behind), and retrieval is
exercised against the real app.services.retrieval.retrieve_relevant_chunks() code
path with a FakeSupabaseClient whose RPC result is computed by genuinely ranking
the real, just-persisted embeddings by real cosine distance in Python (there is no
live Postgres available to run the real match_document_chunks function against, so
the ORDER BY/LIMIT step - the one part of the real RPC that requires live pgvector
- is reproduced in Python over the same real vectors; everything else, including
real embedding generation for both the document and the query, is genuine).

No live Supabase connection, read, or write happens anywhere in this test.
"""

from app.models.document import ChunkType, IngestionStatus
from app.schemas.retrieval import RetrievedChunk
from app.services import retrieval
from app.services.chunking import HARD_LIMIT_TOKENS
from app.services.embeddings.local_minilm import DIMENSION
from app.services.ingestion import compute_file_sha256
from tests.conftest import HDFC_COMPANY_ID, HDFC_PDF, HDFC_TICKER
from tests.fakes.fake_supabase import FakeSupabaseClient, patch_supabase_backend


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return 1 - dot / (norm_a * norm_b)


def test_document_metadata_is_correct(hdfc_ingested):
    doc = hdfc_ingested["document"]
    assert doc.company_ticker == HDFC_TICKER
    assert doc.doc_type.value == "investor_presentation"
    assert doc.reporting_period == "Q1FY27"


def test_sha256_matches_independent_recomputation(hdfc_ingested):
    independent_hash = compute_file_sha256(str(HDFC_PDF))
    assert hdfc_ingested["document"].file_sha256 == independent_hash == hdfc_ingested["file_sha256"]


def test_all_36_pages_were_processed(hdfc_ingested):
    assert len(hdfc_ingested["pages"]) == 36


def test_hdfc_page4_table_is_fully_present_in_persisted_chunks(hdfc_ingested):
    page4_table_chunks = [c for c in hdfc_ingested["chunks"] if c.page_reference == 4 and c.chunk_type == ChunkType.TABLE_ROW_GROUP]
    assert len(page4_table_chunks) == 1
    text = page4_table_chunks[0].text
    assert "P&L (₹ bn) Q1 FY26 Q4 FY26 Q1 FY27 QoQ YoY" in text
    for label in [
        "Net interest income", "Non-interest income", "Net revenue", "Operating expenses",
        "Provisions", "Profit before tax", "Profit after tax", "Profit after tax (Adjusted)*",
    ]:
        assert label in text
    for value in ["314.4", "330.8", "335.3", "1.4%", "6.7%", "173.7", "9.8%"]:
        assert value in text


def test_page_references_are_1_based_and_present(hdfc_ingested):
    for c in hdfc_ingested["chunks"]:
        assert c.page_reference is not None
        assert 1 <= c.page_reference <= 36


def test_every_persisted_chunk_is_within_the_token_hard_limit(hdfc_ingested, minilm_provider):
    for c in hdfc_ingested["chunks"]:
        assert minilm_provider.count_tokens(c.text) <= HARD_LIMIT_TOKENS


def test_every_persisted_embedding_has_384_dimensions(hdfc_ingested):
    for c in hdfc_ingested["chunks"]:
        assert c.embedding is not None
        assert len(c.embedding) == DIMENSION


def test_every_persisted_chunk_carries_model_and_revision_provenance(hdfc_ingested, minilm_provider):
    for c in hdfc_ingested["chunks"]:
        assert c.embedding_model == minilm_provider.model_name
        assert c.embedding_model_revision == minilm_provider.model_revision


def test_document_status_is_completed(hdfc_ingested):
    assert hdfc_ingested["document"].ingestion_status == IngestionStatus.COMPLETED
    assert hdfc_ingested["document"].ingested_at is not None


def test_some_chunks_genuinely_need_manual_review(hdfc_ingested):
    """Confirms the manual-review signal from the rotated-chart/garbled pages
    actually survives all the way through to persisted storage - not lost or
    normalized away anywhere in the pipeline."""
    unparsed = [c for c in hdfc_ingested["chunks"] if c.chunk_type == ChunkType.TABLE_UNPARSED]
    assert unparsed
    assert all(c.needs_manual_review for c in unparsed)
    reliable_table = [c for c in hdfc_ingested["chunks"] if c.chunk_type == ChunkType.TABLE_ROW_GROUP]
    assert all(not c.needs_manual_review for c in reliable_table)


def test_retrieval_service_returns_genuinely_ranked_real_chunks(hdfc_ingested, minilm_provider, monkeypatch):
    """Exercises the real retrieve_relevant_chunks() code path end to end: real
    ticker resolution, real query embedding, and a real RetrievedChunk validation of
    rows ranked by genuine cosine distance over the real persisted vectors (the
    live-Postgres-only ORDER BY step is reproduced in Python here - see module
    docstring for exactly what is and isn't simulated).

    This test deliberately does NOT assert that the page-4 P&L table chunk is
    among the top results - see test_page4_table_chunk_rank_is_reported_honestly
    below for why, and the end-to-end report for the implication (now fixed at the
    hybrid-retrieval layer - see test_hybrid_retrieval.py)."""
    client = FakeSupabaseClient()
    client.tables["companies"] = [{"id": HDFC_COMPANY_ID, "ticker": HDFC_TICKER}]

    question = "What was HDFC Bank's net interest income in Q1 FY27?"
    query_vector = minilm_provider.embed([question])[0]

    ranked = sorted(hdfc_ingested["chunks"], key=lambda c: _cosine_distance(c.embedding, query_vector))[:5]
    expected_order = [c.id for c in ranked]
    client.rpc_results["match_document_chunks"] = [
        {
            "chunk_id": c.id,
            "document_id": c.document_id,
            "company_id": c.company_id,
            "company_ticker": HDFC_TICKER,
            "chunk_text": c.text,
            "chunk_type": c.chunk_type.value,
            "needs_manual_review": c.needs_manual_review,
            "page_reference": c.page_reference,
            "section_label": c.section_label,
            "doc_type": "investor_presentation",
            "reporting_period": "Q1FY27",
            "original_source_url": hdfc_ingested["document"].original_source_url,
            "distance": _cosine_distance(c.embedding, query_vector),
            "similarity": 1 - _cosine_distance(c.embedding, query_vector),
        }
        for c in ranked
    ]

    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: minilm_provider)
    with patch_supabase_backend(client):
        result = retrieval.retrieve_relevant_chunks(HDFC_TICKER, question)

    assert result.company_id == HDFC_COMPANY_ID
    assert len(result.chunks) == 5
    assert all(isinstance(c, RetrievedChunk) for c in result.chunks)
    # Order must be preserved exactly as the RPC returned it, never re-sorted here.
    assert [c.chunk_id for c in result.chunks] == expected_order
    for c in result.chunks:
        assert c.is_reliable_structured_evidence == (c.chunk_type != ChunkType.TABLE_UNPARSED and not c.needs_manual_review)


def test_page4_table_chunk_rank_is_reported_honestly(hdfc_ingested, minilm_provider, capsys):
    """Not a pass/fail quality gate - computes and prints where the real page-4
    P&L table_row_group chunk actually lands in a real cosine-distance ranking
    against a natural-language question, so this finding is visible in every test
    run rather than only in a one-off manual script. See the end-to-end report for
    the implication (chunk-format-vs-embedding-model mismatch for table content,
    now mitigated by hybrid retrieval - test_hybrid_retrieval.py)."""
    question = "What was HDFC Bank's net interest income in Q1 FY27?"
    query_vector = minilm_provider.embed([question])[0]
    ranked = sorted(hdfc_ingested["chunks"], key=lambda c: _cosine_distance(c.embedding, query_vector))
    page4_table = [c for c in hdfc_ingested["chunks"] if c.page_reference == 4 and c.chunk_type == ChunkType.TABLE_ROW_GROUP][0]
    rank = next(i for i, c in enumerate(ranked) if c.id == page4_table.id)
    print(f"\n[finding] page-4 P&L table chunk rank by real cosine distance ALONE: {rank + 1} of {len(ranked)}")
    assert rank >= 0  # always true - this test exists to surface the number above, not to gate on it
