from fastapi import Request
from fastapi.responses import JSONResponse


class FinnError(Exception):
    """Base class for FINN application errors that should map to a clean HTTP response."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class CompanyNotFoundError(FinnError):
    status_code = 404
    code = "company_not_found"


class CompanyLookupError(FinnError):
    """Raised when a ticker outside the seeded registry can't be verified against a
    real metadata source (yfinance) well enough to safely register it in the
    `companies` table. Distinguished from CompanyNotFoundError: that one means "not
    in our static Python registry"; this one means "we tried to look it up for real
    and couldn't confirm it's a valid NSE equity" — never a fabricated guess.
    """

    status_code = 422
    code = "company_lookup_failed"


class MarketDataUnavailableError(FinnError):
    """Raised when a data source (e.g. yfinance) returns no usable data for a ticker.

    Distinguished from a generic 500: this is an expected, handled outcome (a ticker
    with no data today, a delisted symbol, a transient upstream gap) — not a bug.
    """

    status_code = 502
    code = "market_data_unavailable"


class RetrievalUnavailableError(FinnError):
    """Raised when vector retrieval is attempted without Supabase actually connected.

    match_document_chunks (migrations/006) only exists in Supabase/Postgres — the
    JSON-fallback store has no vector search equivalent, so retrieval cannot silently
    degrade to it the way other repositories do.
    """

    status_code = 503
    code = "retrieval_unavailable"


class DocumentMetadataConflictError(FinnError):
    """Same file_sha256 as an existing document, but different (company_id, doc_type,
    reporting_period) metadata - the same bytes are being filed under a different
    identity. Refuses the write rather than silently reusing or overwriting either
    record, since this is a human-fixable data problem, not an expected outcome."""

    status_code = 409
    code = "document_metadata_conflict"


class DocumentExistingConflictError(FinnError):
    """A document already exists for this (company_id, doc_type, reporting_period),
    but with a DIFFERENT file_sha256 - a different file is being filed under an
    identity that's already taken. Never silently overwrites the existing document."""

    status_code = 409
    code = "document_existing_conflict"


class DocumentAlreadyClaimedError(FinnError):
    """The document could not be atomically claimed for ingestion - its
    ingestion_status is already something other than 'pending'/'failed' (another
    worker is processing it, or it already completed)."""

    status_code = 409
    code = "document_already_claimed"


class RetrievalQueryError(FinnError):
    """Wraps a postgrest.APIError raised by the match_document_chunks RPC itself
    (e.g. its own NULL/invalid-input guards, or a malformed company_id) into a clean
    HTTP response rather than leaking a raw Postgres error message."""

    status_code = 400
    code = "retrieval_query_failed"


async def finn_error_handler(request: Request, exc: FinnError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Last-resort handler: never leak a raw traceback to the client.
    import logging

    logging.getLogger("finn.errors").exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "An unexpected error occurred."}},
    )
