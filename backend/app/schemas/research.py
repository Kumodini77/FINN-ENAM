"""Schemas for the hybrid-retrieval Pull endpoint (app.services.hybrid_retrieval,
app.api.research). Deliberately separate from app.schemas.retrieval.RetrievedChunk:
that one mirrors the match_document_chunks RPC's row shape exactly; this one adds
the "why was this chunk selected" transparency fields a pure vector-RPC row can't
carry (matched_via, relevance_score, lexical_match_terms)."""

from pydantic import BaseModel

from app.models.document import ChunkType


class HybridEvidenceChunk(BaseModel):
    chunk_id: str
    document_id: str
    company_id: str
    company_ticker: str
    chunk_text: str
    chunk_type: ChunkType
    needs_manual_review: bool
    page_reference: int | None
    section_label: str | None
    doc_type: str | None
    reporting_period: str | None
    original_source_url: str | None

    matched_via: list[str]  # any of "vector", "lexical"
    relevance_score: float  # 0-1, combined signal - see hybrid_retrieval for the formula
    vector_distance: float | None = None
    lexical_match_terms: list[str] = []

    @property
    def is_reliable_structured_evidence(self) -> bool:
        return self.chunk_type != ChunkType.TABLE_UNPARSED and not self.needs_manual_review


class NumericAnswerOut(BaseModel):
    metric_label: str
    period_label: str | None
    value: str
    all_values_for_row: list[str]
    ambiguous_period_binding: bool
    header_line: str
    source_chunk_id: str
    source_document_id: str
    page_reference: int | None
    original_source_url: str | None
    reporting_period: str | None
    extraction_method: str
    unit_scale: str | None = None
    normalized_value: str | None = None


class ResearchAskResponse(BaseModel):
    company_ticker: str
    company_id: str
    question: str
    intents: list[str]
    answer_type: str  # "numeric_fact" | "evidence_digest" | "insufficient_evidence" | "ambiguous_metric"
    numeric_answer: NumericAnswerOut | None = None
    evidence: list[HybridEvidenceChunk]
    insufficient_evidence_reason: str | None = None
    sources_checked: list[str] | None = None
    """Populated only when answer_type is "insufficient_evidence": which sources
    were actually looked at before concluding there was nothing usable, so the
    caller never has to guess whether FINN tried."""
    suggested_alternative: str | None = None
    """Populated only when answer_type is "insufficient_evidence" and a company
    has no ingested documents but real market data exists for it - a concrete
    question Pull CAN answer right now, instead of a dead end."""
    metric_alternatives: list[str] | None = None
    """Populated only when answer_type is "ambiguous_metric": the row labels the
    question's wording matched without being able to tell which one was meant (e.g.
    "Reported PAT" and "Adjusted PAT" for a question that just says "PAT") - the
    caller should ask the user to pick one rather than guessing."""
    generation_note: str
    """Always present, always honest: states plainly that no LLM-based answer
    generation is configured in this build, so `evidence`/`numeric_answer` are
    deterministic retrieval/extraction results, not AI-synthesized prose."""
