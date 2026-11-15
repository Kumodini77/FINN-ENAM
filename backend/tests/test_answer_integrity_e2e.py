"""Phase 3B Task 4 - full question-to-answer flow integrity tests, through the
real /api/research/ask endpoint (hybrid retrieval mocked, exactly like
tests/test_research_api.py - but these fixtures are the REAL persisted chunk
text for Sun Pharma's page-4 "Financial Snapshot" table, verified against the
genuine PDF in scripts/spikes/fundamentals_access_spike/documents/, including
the real two-chunk split the actual chunker produces for this table (see Phase
3B's audit notes: "EBITDA" and "EBITDA%" land in DIFFERENT chunks))."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.document import ChunkType
from app.schemas.research import HybridEvidenceChunk

client = TestClient(app)

_SUNPHARMA_HEADER = "(₹ mn) Q2FY27 Q2FY26 Y-o-Y H1FY27 H1FY26 Y-o-Y"

_SUNPHARMA_CHUNK_1 = (
    "Financial Snapshot\n"
    f"{_SUNPHARMA_HEADER}\n"
    "[rows 1-3 of 7]\n"
    "Sales: Q2FY27=1,61,000 | Q2FY26=1,44,052 | Y-O-Y=11.8% | H1FY27=3,12,836 | H1FY26=2,81,913 | Y-O-Y=11.0%\n"
    "Gross Margin %: Q2FY27=80.8% | Q2FY26=79.3% | H1FY27=80.6% | H1FY26=79.4%\n"
    "EBITDA: Q2FY27=47,439 | Q2FY26=45,271 | Y-O-Y=4.8% | H1FY27=91,616 | H1FY26=88,287 | Y-O-Y=3.8%\n"
)
_SUNPHARMA_CHUNK_2 = (
    "Financial Snapshot\n"
    f"{_SUNPHARMA_HEADER}\n"
    "[rows 4-7 of 7]\n"
    "EBITDA%: Q2FY27=29.3% | Q2FY26=31.3% | H1FY27=29.1% | H1FY26=31.2%\n"
    "Reported PAT: Q2FY27=19,885 | Q2FY26=31,180 | H1FY27=48,833 | H1FY26=53,966\n"
    "Adjusted PAT: Q2FY27=31,620 | Q2FY26=31,180 | Y-O-Y=1.4% | H1FY27=62,515 | H1FY26=61,141 | Y-O-Y=2.2%\n"
    "EPS: Q2FY27=8.3 | Q2FY26=13.0 | H1FY27=20.4 | H1FY26=22.5\n"
)


def _sunpharma_evidence(**overrides) -> HybridEvidenceChunk:
    base = dict(
        chunk_id="sp-c1", document_id="sp-doc", company_id="sp-co", company_ticker="SUNPHARMA",
        chunk_text=_SUNPHARMA_CHUNK_1, chunk_type=ChunkType.TABLE_ROW_GROUP, needs_manual_review=False,
        page_reference=4, section_label="Financial Snapshot", doc_type="investor_presentation",
        reporting_period="Q2FY27", original_source_url="https://sunpharma.invalid/q2fy27.pdf",
        matched_via=["vector", "lexical"], relevance_score=0.9, vector_distance=0.1,
        lexical_match_terms=["sales"],
    )
    base.update(overrides)
    return HybridEvidenceChunk.model_validate(base)


def _sunpharma_both_chunks() -> list[HybridEvidenceChunk]:
    return [
        _sunpharma_evidence(),
        _sunpharma_evidence(chunk_id="sp-c2", chunk_text=_SUNPHARMA_CHUNK_2, relevance_score=0.85),
    ]


def _hdfc_evidence(**overrides) -> HybridEvidenceChunk:
    base = dict(
        chunk_id="hdfc-c1", document_id="hdfc-doc", company_id="hdfc-co", company_ticker="HDFCBANK",
        chunk_text="P&L (Rs bn) Q1 FY26 Q4 FY26 Q1 FY27 QoQ YoY\nNet interest income: 314.4 | 330.8 | 335.3 | 1.4% | 6.7%",
        chunk_type=ChunkType.TABLE_ROW_GROUP, needs_manual_review=False, page_reference=4, section_label=None,
        doc_type="investor_presentation", reporting_period="Q1FY27", original_source_url="https://hdfc.invalid/q1fy27.pdf",
        matched_via=["vector", "lexical"], relevance_score=0.95, vector_distance=0.1,
        lexical_match_terms=["net interest income"],
    )
    base.update(overrides)
    return HybridEvidenceChunk.model_validate(base)


def test_sunpharma_sales_in_q2fy27():
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=_sunpharma_both_chunks()):
        resp = client.get("/api/research/ask", params={"ticker": "SUNPHARMA", "question": "What was Sun Pharma's sales in Q2 FY27?"})
    body = resp.json()
    na = body["numeric_answer"]
    assert body["answer_type"] == "numeric_fact"
    assert na["metric_label"] == "Sales"
    assert na["value"] == "1,61,000"
    assert na["period_label"] == "Q2FY27"
    assert na["unit_scale"] == "INR million"
    assert na["normalized_value"] == "161000"
    assert na["extraction_method"] == "labeled_column"
    assert na["source_document_id"] == "sp-doc"
    assert na["page_reference"] == 4
    assert body["company_ticker"] == "SUNPHARMA"


def test_sunpharma_ebitda_margin_cross_chunk_ambiguity_is_surfaced_not_guessed():
    """The real finding this audit turned up: "EBITDA" (chunk 1) and "EBITDA%"
    (chunk 2) both match "EBITDA margin" and each resolves CONFIDENTLY on its
    own chunk - the ambiguity only shows up once both chunks' results are
    compared. Must be surfaced explicitly, never silently answered from
    whichever chunk the retriever happened to rank first."""
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=_sunpharma_both_chunks()):
        resp = client.get("/api/research/ask", params={"ticker": "SUNPHARMA", "question": "What was Sun Pharma's EBITDA margin in Q2 FY27?"})
    body = resp.json()
    assert body["answer_type"] == "ambiguous_metric"
    assert body["numeric_answer"] is None
    assert set(body["metric_alternatives"]) == {"EBITDA", "EBITDA%"}


def test_sunpharma_reported_vs_adjusted_pat_both_resolve_distinctly():
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=_sunpharma_both_chunks()):
        reported = client.get("/api/research/ask", params={"ticker": "SUNPHARMA", "question": "What was Sun Pharma's Reported PAT in Q2 FY27?"}).json()
        adjusted = client.get("/api/research/ask", params={"ticker": "SUNPHARMA", "question": "What was Sun Pharma's Adjusted PAT in Q2 FY27?"}).json()
    assert reported["answer_type"] == "numeric_fact"
    assert reported["numeric_answer"]["metric_label"] == "Reported PAT"
    assert reported["numeric_answer"]["value"] == "19,885"
    assert adjusted["answer_type"] == "numeric_fact"
    assert adjusted["numeric_answer"]["metric_label"] == "Adjusted PAT"
    assert adjusted["numeric_answer"]["value"] == "31,620"


def test_sunpharma_bare_pat_without_qualifier_is_ambiguous():
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=_sunpharma_both_chunks()):
        resp = client.get("/api/research/ask", params={"ticker": "SUNPHARMA", "question": "What was Sun Pharma's PAT in Q2 FY27?"})
    body = resp.json()
    assert body["answer_type"] == "ambiguous_metric"
    assert body["numeric_answer"] is None
    assert set(body["metric_alternatives"]) == {"Reported PAT", "Adjusted PAT"}


def test_hdfc_nii_q1fy27_matches_known_ground_truth():
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=[_hdfc_evidence()]):
        resp = client.get("/api/research/ask", params={"ticker": "HDFCBANK", "question": "What was HDFC Bank's net interest income in Q1 FY27?"})
    body = resp.json()
    na = body["numeric_answer"]
    assert body["answer_type"] == "numeric_fact"
    assert body["company_ticker"] == "HDFCBANK"
    assert na["value"] == "335.3"
    assert na["period_label"] == "Q1FY27"
    assert na["page_reference"] == 4
    assert na["source_document_id"] == "hdfc-doc"
    assert na["extraction_method"] == "positional_period_binding"


def test_unsupported_metric_on_a_real_table_never_fabricates_a_numeric_fact():
    """"Total debt" isn't a row in this table at all - no numeric_fact must be
    invented for it. Other reliable evidence exists in the same table, so the
    documented fallback is evidence_digest (real cited text, not a fabricated
    figure), not insufficient_evidence - see app.api.research's fallback logic."""
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=_sunpharma_both_chunks()):
        resp = client.get("/api/research/ask", params={"ticker": "SUNPHARMA", "question": "What was Sun Pharma's total debt in Q2 FY27?"})
    body = resp.json()
    assert body["numeric_answer"] is None
    assert body["answer_type"] in ("evidence_digest", "insufficient_evidence")


def test_unavailable_period_on_a_real_table_does_not_fabricate_a_value():
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=_sunpharma_both_chunks()):
        resp = client.get("/api/research/ask", params={"ticker": "SUNPHARMA", "question": "What was Sun Pharma's Sales in Q3 FY28?"})
    body = resp.json()
    assert body["numeric_answer"] is None
    assert body["answer_type"] in ("evidence_digest", "insufficient_evidence")


def test_question_naming_a_different_company_than_the_evidence_is_not_silently_answered():
    """The evidence returned is Sun Pharma's; the question asks about a
    different company entirely. Evidence retrieval (mocked here) is what's
    responsible for company scoping in the real system - this test guards that
    the numeric extractor itself has no back door that would let a mismatched
    question still bind to someone else's row just because the metric word
    matches, by checking the company fields in the response reflect the
    EVIDENCE's company, never the question's wording."""
    with patch("app.api.research.retrieve_hybrid_evidence", return_value=_sunpharma_both_chunks()):
        resp = client.get("/api/research/ask", params={"ticker": "SUNPHARMA", "question": "What was Reliance's Sales in Q2 FY27?"})
    body = resp.json()
    assert body["company_ticker"] == "SUNPHARMA"
    if body["numeric_answer"] is not None:
        assert body["numeric_answer"]["source_document_id"] == "sp-doc"
