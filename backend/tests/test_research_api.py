"""API-level tests for GET /api/research/ask - hybrid retrieval and numeric
extraction mocked (real end-to-end behavior is covered by
tests/test_hybrid_retrieval.py against the genuine HDFC PDF); this file verifies
request/response wiring, status codes, and the explicit answer_type/generation_note
contract."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.exceptions import CompanyNotFoundError
from app.main import app
from app.models.document import ChunkType
from app.schemas.research import HybridEvidenceChunk

client = TestClient(app)


def _evidence_chunk(**overrides) -> HybridEvidenceChunk:
    base = dict(
        chunk_id="c1", document_id="d1", company_id="co1", company_ticker="HDFCBANK",
        chunk_text="P&L (Rs bn) Q1 FY26 Q4 FY26 Q1 FY27 QoQ YoY\nNet interest income: 314.4 | 330.8 | 335.3 | 1.4% | 6.7%",
        chunk_type=ChunkType.TABLE_ROW_GROUP, needs_manual_review=False, page_reference=4, section_label=None,
        doc_type="investor_presentation", reporting_period="Q1FY27", original_source_url="https://x.invalid/a.pdf",
        matched_via=["vector", "lexical"], relevance_score=0.95, vector_distance=0.1, lexical_match_terms=["net interest income"],
    )
    base.update(overrides)
    return HybridEvidenceChunk.model_validate(base)


def test_numerical_question_returns_numeric_fact_with_citation():
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=[_evidence_chunk()]):
        resp = client.get("/api/research/ask", params={"ticker": "HDFCBANK", "question": "What was HDFC Bank's net interest income in Q1 FY27?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer_type"] == "numeric_fact"
    assert body["numeric_answer"]["value"] == "335.3"
    assert body["numeric_answer"]["page_reference"] == 4
    assert body["numeric_answer"]["original_source_url"] == "https://x.invalid/a.pdf"
    assert "No answer-generation" in body["generation_note"]


def test_numerical_question_with_only_unreliable_evidence_returns_insufficient_evidence():
    unreliable = _evidence_chunk(chunk_type=ChunkType.TABLE_UNPARSED, needs_manual_review=True)
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=[unreliable]):
        resp = client.get("/api/research/ask", params={"ticker": "HDFCBANK", "question": "What was HDFC Bank's net interest income in Q1 FY27?"})
    body = resp.json()
    assert body["answer_type"] == "insufficient_evidence"
    assert body["numeric_answer"] is None
    assert "manual review" in body["insufficient_evidence_reason"] or "reliably-structured" in body["insufficient_evidence_reason"]


def test_no_evidence_at_all_returns_insufficient_evidence():
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=[]):
        resp = client.get("/api/research/ask", params={"ticker": "HDFCBANK", "question": "What happened to margins?"})
    body = resp.json()
    assert body["answer_type"] == "insufficient_evidence"
    assert body["evidence"] == []


def test_numerical_question_with_no_structured_fact_but_reliable_prose_falls_back_to_evidence_digest():
    """Real finding from testing a second company's genuine document: the formal
    table couldn't be confidently structured (inconsistent column counts), but a
    plain prose sentence elsewhere in the same deck states the figure directly.
    That's evidence_digest (real evidence, not extracted into a verified field),
    not insufficient_evidence (which would wrongly imply nothing useful was found)."""
    reliable_prose = _evidence_chunk(
        chunk_id="c-prose", chunk_type=ChunkType.PROSE, needs_manual_review=False,
        chunk_text="Q2FY27: Sales of Rs 161.0 bn, 11.8% growth over last year.",
        matched_via=["lexical"], relevance_score=0.6,
    )
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=[reliable_prose]):
        resp = client.get("/api/research/ask", params={"ticker": "SUNPHARMA", "question": "What was Sun Pharma's sales revenue in Q2 FY27?"})
    body = resp.json()
    assert body["answer_type"] == "evidence_digest"
    assert body["numeric_answer"] is None
    assert len(body["evidence"]) == 1


def test_non_numerical_question_returns_evidence_digest():
    prose = _evidence_chunk(
        chunk_id="c2", chunk_type=ChunkType.PROSE,
        chunk_text="Management highlighted continued margin pressure from rising deposit costs.",
        matched_via=["vector"], relevance_score=0.7,
    )
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=[prose]):
        resp = client.get("/api/research/ask", params={"ticker": "HDFCBANK", "question": "Why did margins decline?"})
    body = resp.json()
    assert body["answer_type"] == "evidence_digest"
    assert body["numeric_answer"] is None
    assert len(body["evidence"]) == 1


def test_unknown_ticker_returns_404():
    with patch("app.api.research.retrieve_hybrid_evidence", side_effect=CompanyNotFoundError("Unknown ticker 'NOTREAL'")):
        resp = client.get("/api/research/ask", params={"ticker": "NOTREAL", "question": "anything at all"})
    assert resp.status_code == 404


def test_question_too_short_is_rejected_with_422():
    resp = client.get("/api/research/ask", params={"ticker": "HDFCBANK", "question": "hi"})
    assert resp.status_code == 422


def test_table_unparsed_evidence_is_never_the_source_of_a_numeric_fact():
    """Even if a table_unparsed chunk happens to come back ranked first, the
    numeric extractor must skip it and look further down the evidence list."""
    unreliable = _evidence_chunk(chunk_type=ChunkType.TABLE_UNPARSED, needs_manual_review=True, relevance_score=0.9)
    reliable = _evidence_chunk(chunk_id="c3", relevance_score=0.5)
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=[unreliable, reliable]):
        resp = client.get("/api/research/ask", params={"ticker": "HDFCBANK", "question": "What was HDFC Bank's net interest income in Q1 FY27?"})
    body = resp.json()
    assert body["answer_type"] == "numeric_fact"
    assert body["numeric_answer"]["source_chunk_id"] == "c3"
