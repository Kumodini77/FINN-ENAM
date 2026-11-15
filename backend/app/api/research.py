"""Pull research endpoint: hybrid (vector + lexical) evidence retrieval, query-intent
routing, and deterministic numeric-answer extraction. There is NO answer-generation
model configured in this build (see app.services.classification's optional Anthropic
call - that exists only for Push's filing-category classification, not for Pull
synthesis) - this endpoint never fabricates prose analysis. For a NUMERICAL-intent
question it returns an exact, cited figure extracted deterministically from a real
table row; otherwise it returns the ranked, cited evidence chunks themselves
("evidence digest"), honestly labeled as retrieval output, not AI-generated
analysis.
"""

from fastapi import APIRouter, Query

from app.core.exceptions import CompanyNotFoundError
from app.models.document import ChunkType
from app.schemas.research import HybridEvidenceChunk, NumericAnswerOut, ResearchAskResponse
from app.services.hybrid_retrieval import retrieve_hybrid_evidence
from app.services.numeric_answer import extract_numeric_answer, resolve_cross_chunk_metric_ambiguity
from app.services.query_intent import QueryIntent, classify_query_intent

router = APIRouter(prefix="/research", tags=["research"])

_GENERATION_NOTE = (
    "No answer-generation (LLM) model is configured in this build. This response is "
    "deterministic retrieval and pattern-matched extraction over your own company "
    "documents - not AI-synthesized analysis."
)

_INSUFFICIENT_EVIDENCE_REASON_NO_CHUNKS = (
    "No chunk from a completed document for this company matched the question well "
    "enough to be shown as evidence."
)
_INSUFFICIENT_EVIDENCE_REASON_NO_RELIABLE_NUMERIC = (
    "A numerical answer was requested, but no reliably-structured (table_row_group, "
    "not flagged for manual review) table row matching this metric and period was found."
)


@router.get("/ask", response_model=ResearchAskResponse)
def ask(
    ticker: str,
    question: str = Query(..., min_length=3),
    top_k: int = Query(default=5, ge=1, le=20),
) -> ResearchAskResponse:
    intents = classify_query_intent(question)

    try:
        evidence_internal = retrieve_hybrid_evidence(ticker, question, intents, top_k=top_k)
    except CompanyNotFoundError:
        raise

    company_id = evidence_internal[0].company_id if evidence_internal else None
    company_ticker = evidence_internal[0].company_ticker if evidence_internal else ticker.strip().upper()

    if not evidence_internal:
        return ResearchAskResponse(
            company_ticker=company_ticker, company_id=company_id or "", question=question,
            intents=[i.value for i in intents], answer_type="insufficient_evidence",
            evidence=[], insufficient_evidence_reason=_INSUFFICIENT_EVIDENCE_REASON_NO_CHUNKS,
            generation_note=_GENERATION_NOTE,
        )

    numeric_answer = None
    metric_alternatives: list[str] | None = None
    if QueryIntent.NUMERICAL in intents:
        # A long table can be split across several persisted chunks (see
        # app.services.chunking), each repeating the header - two DIFFERENT rows
        # the question's wording matches (e.g. "EBITDA" and "EBITDA%") can end up
        # in DIFFERENT chunks, each resolving confidently on its own with no idea
        # the other exists. So every reliable chunk is scanned and its candidate
        # kept - never just the first one found - before deciding.
        confident_candidates: list[tuple[object, object]] = []  # (evidence, NumericAnswer)
        for e in evidence_internal:
            if e.chunk_type != ChunkType.TABLE_ROW_GROUP or e.needs_manual_review:
                continue  # never extract a "verified" figure from unreliable evidence
            extracted = extract_numeric_answer(question, e.chunk_text)
            if not extracted:
                continue
            if extracted.ambiguous_metric_selection:
                # Several rows in THIS chunk's table matched the question's wording
                # and none could be told apart (e.g. "Reported PAT" vs "Adjusted PAT"
                # for a bare "PAT" question) - remember it, but keep looking: a
                # later, different chunk might still resolve unambiguously.
                if metric_alternatives is None:
                    metric_alternatives = extracted.metric_alternatives
                continue
            if not extracted.ambiguous_period_binding:
                confident_candidates.append((e, extracted))

        if confident_candidates:
            resolved = resolve_cross_chunk_metric_ambiguity(question, [c[1] for c in confident_candidates])
            if isinstance(resolved, list):
                # Cross-chunk metric ambiguity: more than one chunk confidently
                # matched a DIFFERENT row for this question's wording.
                metric_alternatives = resolved
            elif resolved is not None:
                e = next(ev for ev, extracted in confident_candidates if extracted is resolved)
                numeric_answer = NumericAnswerOut(
                    metric_label=resolved.metric_label, period_label=resolved.period_label,
                    value=resolved.value, all_values_for_row=resolved.all_values_for_row,
                    ambiguous_period_binding=resolved.ambiguous_period_binding, header_line=resolved.header_line,
                    source_chunk_id=e.chunk_id, source_document_id=e.document_id,
                    page_reference=e.page_reference, original_source_url=e.original_source_url,
                    reporting_period=e.reporting_period, extraction_method=resolved.extraction_method,
                    unit_scale=resolved.unit_scale, normalized_value=resolved.normalized_value,
                )

    if numeric_answer is not None:
        answer_type = "numeric_fact"
        insufficient_reason = None
    elif metric_alternatives is not None:
        # Surface the ambiguity explicitly rather than silently answering for one
        # interpretation or burying it in an undifferentiated evidence digest.
        answer_type = "ambiguous_metric"
        insufficient_reason = None
    elif QueryIntent.NUMERICAL in intents:
        # No cleanly-extractable structured figure - but if at least one piece of
        # RELIABLE evidence exists (e.g. a plain prose sentence that states the
        # figure directly, even though the formal table itself couldn't be
        # confidently structured - a real case found testing a second company's
        # genuine document), that's evidence_digest, not "insufficient evidence":
        # the user can read the real number in context, we just didn't extract it
        # into a verified structured field. Only "insufficient_evidence" when
        # nothing reliable was found at all.
        if any(e.is_reliable_structured_evidence for e in evidence_internal):
            answer_type = "evidence_digest"
            insufficient_reason = None
        else:
            answer_type = "insufficient_evidence"
            insufficient_reason = _INSUFFICIENT_EVIDENCE_REASON_NO_RELIABLE_NUMERIC
    else:
        answer_type = "evidence_digest"
        insufficient_reason = None

    return ResearchAskResponse(
        company_ticker=company_ticker, company_id=company_id, question=question,
        intents=[i.value for i in intents], answer_type=answer_type, numeric_answer=numeric_answer,
        evidence=[HybridEvidenceChunk.model_validate(e.model_dump()) for e in evidence_internal],
        insufficient_evidence_reason=insufficient_reason, metric_alternatives=metric_alternatives,
        generation_note=_GENERATION_NOTE,
    )
