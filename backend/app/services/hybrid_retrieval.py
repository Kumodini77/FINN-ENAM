"""Hybrid (vector + lexical) evidence retrieval for Pull, built to fix the
observed failure mode: a real table_row_group chunk containing the exact asked-for
figure ranked 26th of 203 by cosine similarity alone, behind short, irrelevant
prose. Vector similarity is retained (it is the only signal that generalizes to
paraphrased/semantic questions), but it is no longer the ONLY path a chunk can be
found through - an independent keyword/metric-alias search (over the SAME
company-scoped, completed-documents-only data match_document_chunks enforces, see
app.repositories.documents.search_chunks_by_keywords) can surface a chunk
regardless of its vector rank, directly satisfying "a relevant result must not be
excluded simply because its vector similarity ranks below 20".

Company isolation and completed-document filtering are enforced independently by
BOTH paths (the vector RPC's own WHERE clause, and search_chunks_by_keywords' own
company_id + ingestion_status checks) - neither path trusts the other to have done
it.
"""

from __future__ import annotations

import re

from app.core.db import storage_backend_name
from app.core.exceptions import RetrievalUnavailableError
from app.models.document import ChunkType
from app.repositories.company_lookup import get_company_id
from app.repositories.documents import DocumentRepository
from app.schemas.research import HybridEvidenceChunk
from app.services import retrieval as vector_retrieval
from app.services.metric_aliases import canonical_metrics_for_text
from app.services.query_intent import QueryIntent

_STOPWORDS = {
    "the", "a", "an", "is", "was", "were", "what", "which", "how", "did", "do", "does",
    "in", "of", "for", "to", "and", "or", "its", "it's", "company's", "bank's", "this",
}
_WORD_RE = re.compile(r"[a-z0-9%]+")

_VECTOR_CANDIDATE_POOL = 20  # the RPC's own hard cap (migrations/006/008) - not raised
_LEXICAL_MATCH_BOOST = 0.6
_BOTH_SIGNALS_BONUS = 0.15
_NUMERICAL_TABLE_BOOST = 0.25
_NUMERICAL_UNPARSED_PENALTY = 0.4
_MANUAL_REVIEW_PENALTY = 0.2


def _distinctive_terms(question: str) -> list[str]:
    """Question words minus stopwords - a simple, deterministic keyword set, not a
    learned/fuzzy extractor."""
    words = _WORD_RE.findall(question.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 2]


def _dedupe(terms: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def _primary_terms_for(question: str) -> list[str]:
    """Metric-alias terms (e.g. "net interest income", "nii") - specific enough
    that finding one verbatim in a chunk is real evidence the chunk answers the
    question, not just that it's about the same company/document."""
    terms: list[str] = []
    for canonical in canonical_metrics_for_text(question):
        terms.append(canonical)
        terms.extend(_direct_aliases_for(canonical))
    return _dedupe(terms)


def _search_terms_for(question: str) -> list[str]:
    """Primary (metric-alias) terms plus the question's own distinctive words, for
    CASTING THE SEARCH NET WIDE (what search_chunks_by_keywords queries for) - a
    non-metric keyword question (e.g. about a product name) still needs something
    to search on. Ranking, however, only credits primary-term matches (see
    _score) - a generic word repeated in every page's footer (e.g. the company
    name itself) must not look like real evidence on its own."""
    return _dedupe(_primary_terms_for(question) + _distinctive_terms(question))


def _direct_aliases_for(canonical: str) -> list[str]:
    from app.services.metric_aliases import METRIC_ALIASES

    return METRIC_ALIASES.get(canonical, [])


def _score(
    *,
    matched_via: set[str],
    vector_distance: float | None,
    chunk_type: ChunkType,
    needs_manual_review: bool,
    intents: set[QueryIntent],
) -> float:
    vector_score = max(0.0, 1 - vector_distance) if vector_distance is not None else 0.0
    lexical_score = _LEXICAL_MATCH_BOOST if "lexical" in matched_via else 0.0

    is_numerical = QueryIntent.NUMERICAL in intents
    if is_numerical and chunk_type != ChunkType.TABLE_ROW_GROUP and "lexical" in matched_via:
        # A numerical question asks for a reported figure, which only lives in
        # structured table evidence - a bare keyword match in ordinary prose (e.g.
        # a chart's axis legend repeating the same metric name with no figures
        # attached) is real evidence the term is discussed here, but far weaker
        # evidence that THIS chunk actually answers the question, so it must not
        # compete on equal footing with an actual table row.
        lexical_score *= 0.5

    score = max(vector_score, lexical_score)
    if len(matched_via) > 1:
        score += _BOTH_SIGNALS_BONUS

    if is_numerical:
        if chunk_type == ChunkType.TABLE_ROW_GROUP:
            score += _NUMERICAL_TABLE_BOOST
        elif chunk_type == ChunkType.TABLE_UNPARSED:
            score -= _NUMERICAL_UNPARSED_PENALTY

    if needs_manual_review:
        score -= _MANUAL_REVIEW_PENALTY

    return max(0.0, min(1.0, score))


def retrieve_hybrid_evidence(
    company_ticker: str,
    question: str,
    intents: set[QueryIntent],
    *,
    repo: DocumentRepository | None = None,
    top_k: int = 5,
) -> list[HybridEvidenceChunk]:
    """Raises CompanyNotFoundError if the ticker is unknown (same as
    app.services.retrieval). Never raises RetrievalUnavailableError - if vector
    search isn't available (JSON-fallback backend), proceeds lexical-only rather
    than refusing outright, since the lexical path works on either backend."""
    repo = repo or DocumentRepository()
    ticker = company_ticker.strip().upper()
    # get_company_id() is Supabase-only (it resolves a real companies.id uuid FK);
    # calling it when the backend isn't Supabase would crash on a None client, not
    # raise a clean error. The JSON-fallback DocumentRepository has no such FK
    # concept - it key-matches on whatever string was stored, so the ticker itself
    # is used as company_id there, consistently with how JSON-fallback documents
    # are written (see app.repositories.documents).
    company_id = get_company_id(ticker) if storage_backend_name() == "supabase" else ticker

    vector_rows: dict[str, dict] = {}
    try:
        vector_result = vector_retrieval.retrieve_relevant_chunks(ticker, question, match_count=_VECTOR_CANDIDATE_POOL)
        for c in vector_result.chunks:
            vector_rows[c.chunk_id] = {
                "document_id": c.document_id, "company_id": c.company_id, "company_ticker": c.company_ticker,
                "chunk_text": c.chunk_text, "chunk_type": c.chunk_type, "needs_manual_review": c.needs_manual_review,
                "page_reference": c.page_reference, "section_label": c.section_label, "doc_type": c.doc_type,
                "reporting_period": c.reporting_period, "original_source_url": c.original_source_url,
                "distance": c.distance,
            }
        company_id = vector_result.company_id
    except RetrievalUnavailableError:
        pass  # lexical-only fallback below

    if company_id is None:
        from app.core.exceptions import CompanyNotFoundError

        raise CompanyNotFoundError(f"Unknown ticker '{ticker}' — no companies row found.")

    primary_terms = _primary_terms_for(question)
    search_terms = _search_terms_for(question)
    lexical_rows_raw = repo.search_chunks_by_keywords(company_id, search_terms, limit=_VECTOR_CANDIDATE_POOL)
    lexical_rows = {r["chunk_id"]: r for r in lexical_rows_raw}

    all_ids = sorted(set(vector_rows) | set(lexical_rows))  # sorted: deterministic merge order, no tie-break flakiness
    merged: list[HybridEvidenceChunk] = []
    for chunk_id in all_ids:
        v = vector_rows.get(chunk_id)
        l = lexical_rows.get(chunk_id)
        source = v or l

        matched_terms = [t for t in search_terms if t.lower() in source["chunk_text"].lower()] if l is not None else []
        matched_primary_terms = [t for t in matched_terms if t in primary_terms]

        matched_via = set()
        if v is not None:
            matched_via.add("vector")
        if matched_primary_terms:
            # Only a specific metric-alias match counts as a real lexical signal -
            # a hit on a generic word (company name, "net", "income" alone) that
            # appears on every page is search-net-casting, not evidence this
            # particular chunk answers the question (see _search_terms_for).
            matched_via.add("lexical")

        chunk_type = ChunkType(source["chunk_type"]) if isinstance(source["chunk_type"], str) else source["chunk_type"]

        score = _score(
            matched_via=matched_via,
            vector_distance=v["distance"] if v else None,
            chunk_type=chunk_type,
            needs_manual_review=source["needs_manual_review"],
            intents=intents,
        )
        merged.append(
            HybridEvidenceChunk(
                chunk_id=chunk_id, document_id=source["document_id"], company_id=source["company_id"],
                company_ticker=source["company_ticker"], chunk_text=source["chunk_text"], chunk_type=chunk_type,
                needs_manual_review=source["needs_manual_review"], page_reference=source["page_reference"],
                section_label=source["section_label"], doc_type=source["doc_type"],
                reporting_period=source["reporting_period"], original_source_url=source["original_source_url"],
                matched_via=sorted(matched_via), relevance_score=score,
                vector_distance=v["distance"] if v else None, lexical_match_terms=matched_terms,
            )
        )

    merged.sort(key=lambda c: (_rank_tier(c.chunk_type, c.matched_via, intents), c.relevance_score), reverse=True)
    return merged[:top_k]


def _rank_tier(chunk_type: ChunkType, matched_via: list[str], intents: set[QueryIntent]) -> int:
    """A hard priority tier, applied BEFORE relevance_score as the primary sort
    key - a numerical question's reported figure only lives in a structured table
    row, so a table_row_group chunk with a real metric match must outrank ANY
    prose chunk regardless of vector similarity, not merely score a bit higher
    (an additive bonus alone was not enough to overcome a short, highly
    vector-similar prose chunk that happens to repeat the same metric name in a
    chart legend - this tiering is the actual fix)."""
    if QueryIntent.NUMERICAL not in intents:
        return 0
    if chunk_type == ChunkType.TABLE_ROW_GROUP:
        return 2 if "lexical" in matched_via else 1
    if chunk_type == ChunkType.TABLE_UNPARSED:
        return -1
    return 0
