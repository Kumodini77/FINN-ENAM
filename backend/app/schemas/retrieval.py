"""Pydantic validation for match_document_chunks RPC rows.

Every field here mirrors a real column the RPC actually returns - nothing invented.
This is the boundary that turns a raw Supabase RPC response into something the rest
of FINN can trust.

chunk_type/needs_manual_review are migrations/008 additions (not yet applied/live -
migrations/006 is still the live function). Both are given defaults so a row coming
back from the CURRENTLY LIVE 006 function (which has neither column) still validates
cleanly - this model supports both the pre-008 and post-008 shapes, so retrieval
doesn't have to change again the moment 008 is applied.
"""

from pydantic import BaseModel

from app.models.document import ChunkType


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    company_id: str
    company_ticker: str
    chunk_text: str
    page_reference: int | None
    section_label: str | None
    doc_type: str
    reporting_period: str | None
    original_source_url: str
    distance: float
    similarity: float

    # --- migrations/008 additions (defaulted for 006-shaped rows, see module docstring) ---
    chunk_type: ChunkType = ChunkType.PROSE
    needs_manual_review: bool = False

    @property
    def is_reliable_structured_evidence(self) -> bool:
        """False whenever this chunk's structure could not be confidently
        determined (chunk_type == TABLE_UNPARSED) or needs_manual_review is set for
        any other reason. Any future research/synthesis layer over Pull evidence
        must branch on this (or needs_manual_review directly) rather than treating
        every returned chunk as equally reliable structured data - a
        table_unparsed chunk is raw extracted text, not confirmed row/column
        structure, even though it still carries real citation metadata."""
        return self.chunk_type != ChunkType.TABLE_UNPARSED and not self.needs_manual_review


class RetrievalResult(BaseModel):
    """What app.services.retrieval.retrieve_relevant_chunks() returns: the ranked
    evidence for one (company, question) pair. Ranking itself happened inside
    Postgres (match_document_chunks' ORDER BY) — chunks here are already in that
    order and must not be re-sorted in Python."""

    company_ticker: str
    company_id: str
    question: str
    chunks: list[RetrievedChunk]
