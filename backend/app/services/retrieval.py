"""Vector retrieval over document_chunks via the match_document_chunks RPC
(migrations/006_vector_similarity_search_rpc.sql).

Ranking happens entirely inside Postgres — this module never computes or re-sorts
similarity in Python. Its only jobs are: resolve ticker -> company_id, embed the
question with the exact pinned local model, call the RPC with the right named
arguments, and validate what comes back.

This is retrieval only. It does not synthesize an answer, does not call an LLM, and
must not be mistaken for a complete Pull/RAG pipeline.
"""

import logging

from postgrest import APIError

from app.core.db import get_supabase_client, storage_backend_name
from app.core.exceptions import CompanyNotFoundError, RetrievalQueryError, RetrievalUnavailableError
from app.repositories.company_lookup import get_company_id
from app.schemas.retrieval import RetrievalResult, RetrievedChunk
from app.services.embeddings import get_embedding_provider

logger = logging.getLogger("finn.services.retrieval")

_RPC_NAME = "match_document_chunks"


def retrieve_relevant_chunks(company_ticker: str, question: str, match_count: int | None = None) -> RetrievalResult:
    """Retrieves the top-matching document_chunks for `question`, scoped to
    `company_ticker`, via the match_document_chunks RPC.

    `match_count=None` (the default) omits the argument from the RPC call entirely,
    so Postgres applies the function's own `default 5` — it is NOT the same as
    passing an explicit NULL, which migrations/006 deliberately rejects. Pass an
    explicit int to request a different count (capped at 20 server-side).

    Raises:
        CompanyNotFoundError: `company_ticker` has no row in `companies` yet.
        RetrievalUnavailableError: Supabase isn't the active backend — the
            JSON-fallback store has no vector search equivalent.
        RetrievalQueryError: the RPC itself rejected the call (e.g. a malformed
            company_id, or one of its own NULL/invalid-input guards).
    """
    if storage_backend_name() != "supabase":
        raise RetrievalUnavailableError(
            "Vector retrieval requires Supabase (match_document_chunks RPC); "
            "the JSON-fallback store has no equivalent."
        )

    ticker = company_ticker.strip().upper()
    company_id = get_company_id(ticker)
    if company_id is None:
        raise CompanyNotFoundError(f"Unknown ticker '{ticker}' — no companies row found.")

    provider = get_embedding_provider()
    query_embedding = provider.embed([question])[0]

    params: dict = {
        "query_embedding": query_embedding,
        "filter_company_id": company_id,
    }
    if match_count is not None:
        params["match_count"] = match_count

    client = get_supabase_client()
    try:
        resp = client.rpc(_RPC_NAME, params).execute()
    except APIError as e:
        logger.warning("match_document_chunks RPC rejected the call: %s", e.message)
        raise RetrievalQueryError(f"Vector retrieval query failed: {e.message}") from e

    rows = resp.data or []
    chunks = [RetrievedChunk.model_validate(row) for row in rows]

    return RetrievalResult(
        company_ticker=ticker,
        company_id=company_id,
        question=question,
        chunks=chunks,
    )
