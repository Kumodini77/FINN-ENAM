"""Token-aware chunking of pdf_extraction's per-page blocks into DocumentChunk-shaped
records, ready for embedding and storage.

Hard rules (migrations/007's chunk_type/needs_manual_review, and Correction 3/4 of the
ingestion design review):
  - Soft target 180-220 tokens, hard limit strictly < 256 (MiniLM's max_seq_length) -
    every token count below comes from the actual embedding provider's tokenizer
    (EmbeddingProvider.count_tokens), never an approximation.
  - A chunk never spans two PDF pages.
  - A table_row_group chunk always repeats its complete header text.
  - A chunk that would exceed the hard limit is never silently truncated or dropped -
    either split into clearly-labeled sub-chunks (prose: sentence/paragraph
    boundaries; an over-long single table row: explicit column-range sub-chunks) or,
    if that is impossible, this module raises ChunkingError rather than losing
    information silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.embeddings.base import EmbeddingProvider
from app.services.pdf_extraction import Block, PageExtraction, ProseBlock, TableBlock, UnparsedBlock

SOFT_TARGET_MIN_TOKENS = 180
SOFT_TARGET_MAX_TOKENS = 220
HARD_LIMIT_TOKENS = 256

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class ChunkingError(Exception):
    """Raised when a piece of content cannot be represented within HARD_LIMIT_TOKENS
    by any splitting strategy this module knows - e.g. a single label token alone
    (with no values to drop) still exceeds the hard limit. Never silently truncated."""


@dataclass
class Chunk:
    page_number: int
    text: str
    chunk_type: str  # "prose" | "table_row_group" | "table_unparsed"
    needs_manual_review: bool
    section_label: str | None = None


def _split_prose_to_fit(text: str, provider: EmbeddingProvider) -> list[str]:
    """Greedily packs sentences into pieces targeting the soft window, never
    exceeding HARD_LIMIT_TOKENS. A single sentence that alone exceeds the hard limit
    is split further on whitespace (never silently truncated: all words are kept,
    just spread across more pieces)."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    if not sentences:
        return []

    pieces: list[str] = []
    current: list[str] = []

    def current_text() -> str:
        return " ".join(current)

    def flush() -> None:
        if current:
            pieces.append(current_text())
            current.clear()

    for sentence in sentences:
        if provider.count_tokens(sentence) > HARD_LIMIT_TOKENS:
            flush()
            pieces.extend(_split_words_to_fit(sentence, provider))
            continue
        candidate = current_text() + (" " if current else "") + sentence
        if current and provider.count_tokens(candidate) > HARD_LIMIT_TOKENS:
            flush()
            current.append(sentence)
        else:
            current.append(sentence)
            if provider.count_tokens(current_text()) >= SOFT_TARGET_MIN_TOKENS:
                flush()
    flush()
    return pieces


def _split_words_to_fit(text: str, provider: EmbeddingProvider) -> list[str]:
    words = text.split()
    if not words:
        return []
    pieces: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        if current and provider.count_tokens(candidate) > HARD_LIMIT_TOKENS:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        pieces.append(" ".join(current))
    for piece in pieces:
        if provider.count_tokens(piece) > HARD_LIMIT_TOKENS:
            raise ChunkingError(
                f"A single word/token sequence could not be fit under the {HARD_LIMIT_TOKENS}-token "
                "hard limit even alone - refusing to truncate it silently."
            )
    return pieces


# " | " (not ",") separates values: Indian-format numbers routinely embed
# commas of their own (lakh/crore grouping, e.g. "1,61,000"), so a comma
# separator would be ambiguous between "end of this value" and "thousands
# grouping within this value". " | " never appears inside a numeric token.
_VALUE_SEP = " | "


def _format_row(row) -> str:
    # column_labels is only set when the table's header had optional/sparse
    # columns (see app.services.pdf_extraction._reconcile_sparse_columns) - in
    # that case this specific row may have fewer values than the full header,
    # so each value is rendered against its OWN column's label rather than
    # relying on positional order against the full header line, which would be
    # ambiguous (or wrong) for a shortened row.
    if row.column_labels is not None:
        pairs = _VALUE_SEP.join(f"{label}={value}" for label, value in zip(row.column_labels, row.values))
        return f"{row.label}: {pairs}"
    return f"{row.label}: {_VALUE_SEP.join(row.values)}"


def _format_table_row_group(header_line: str, title: str | None, rows_subset, start: int, end: int, total: int) -> str:
    prefix = f"{title}\n" if title else ""
    body = "\n".join(_format_row(r) for r in rows_subset)
    if start == 0 and end == total:
        return f"{prefix}{header_line}\n{body}"
    return f"{prefix}{header_line}\n[rows {start + 1}-{end} of {total}]\n{body}"


def _chunk_table_block(block: TableBlock, provider: EmbeddingProvider) -> list[Chunk]:
    """Repeats the complete header in every emitted chunk. Rows are grouped greedily
    to stay within the hard limit; a single row (header + one row) that still exceeds
    the hard limit is split into explicitly labeled column-range sub-chunks rather
    than being dropped or truncated."""
    chunks: list[Chunk] = []
    total = len(block.rows)
    group: list = []
    group_start = 0

    def flush(end_idx: int) -> None:
        nonlocal group, group_start
        if not group:
            return
        text = _format_table_row_group(block.header_line, block.title, group, group_start, end_idx, total)
        chunks.append(Chunk(page_number=block.page_number, text=text, chunk_type="table_row_group", needs_manual_review=False))
        group = []

    for idx, row in enumerate(block.rows):
        candidate_text = _format_table_row_group(block.header_line, block.title, group + [row], group_start, idx + 1, total)
        if group and provider.count_tokens(candidate_text) > HARD_LIMIT_TOKENS:
            flush(idx)
            group_start = idx
        group.append(row)
        solo_text = _format_table_row_group(block.header_line, block.title, [row], idx, idx + 1, total)
        if provider.count_tokens(solo_text) > HARD_LIMIT_TOKENS:
            # Even a single row doesn't fit alongside the header - split the row's
            # own values into labeled column-range sub-chunks instead of dropping any.
            group = group[:-1]
            flush(idx)
            chunks.extend(_chunk_oversized_row(block, row, idx, provider))
            group_start = idx + 1

    flush(total)
    return chunks


def _chunk_oversized_row(block: TableBlock, row, row_index: int, provider: EmbeddingProvider) -> list[Chunk]:
    values = row.values
    if len(values) <= 1:
        raise ChunkingError(
            f"Table row '{row.label}' on page {block.page_number} exceeds the token hard limit even with a "
            "single value - no safe sub-chunking strategy available; refusing to truncate it silently."
        )
    mid = len(values) // 2
    sub_ranges = [(0, mid), (mid, len(values))]
    chunks: list[Chunk] = []
    for start, end in sub_ranges:
        subset_values = values[start:end]
        prefix = f"{block.title}\n" if block.title else ""
        if row.column_labels is not None:
            subset_labels = row.column_labels[start:end]
            rendered = _VALUE_SEP.join(f"{label}={value}" for label, value in zip(subset_labels, subset_values))
        else:
            rendered = _VALUE_SEP.join(subset_values)
        text = (
            f"{prefix}{block.header_line}\n[row {row_index + 1}, columns {start + 1}-{end} of {len(values)}]\n"
            f"{row.label}: {rendered}"
        )
        if provider.count_tokens(text) > HARD_LIMIT_TOKENS:
            raise ChunkingError(
                f"Table row '{row.label}' on page {block.page_number} could not be split into a column range "
                f"that fits the {HARD_LIMIT_TOKENS}-token hard limit - refusing to truncate it silently."
            )
        chunks.append(Chunk(page_number=block.page_number, text=text, chunk_type="table_row_group", needs_manual_review=False))
    return chunks


def _chunk_unparsed_block(block: UnparsedBlock, provider: EmbeddingProvider) -> list[Chunk]:
    pieces = _split_prose_to_fit(block.text, provider) if provider.count_tokens(block.text) > HARD_LIMIT_TOKENS else [block.text]
    return [
        Chunk(page_number=block.page_number, text=piece, chunk_type="table_unparsed", needs_manual_review=True)
        for piece in pieces
        if piece.strip()
    ]


def _chunk_prose_block(block: ProseBlock, provider: EmbeddingProvider) -> list[Chunk]:
    text = block.text.strip()
    if not text:
        return []
    if provider.count_tokens(text) <= HARD_LIMIT_TOKENS:
        return [Chunk(page_number=block.page_number, text=text, chunk_type="prose", needs_manual_review=False)]
    pieces = _split_prose_to_fit(text, provider)
    return [Chunk(page_number=block.page_number, text=p, chunk_type="prose", needs_manual_review=False) for p in pieces if p.strip()]


def chunk_block(block: Block, provider: EmbeddingProvider) -> list[Chunk]:
    if isinstance(block, ProseBlock):
        return _chunk_prose_block(block, provider)
    if isinstance(block, TableBlock):
        return _chunk_table_block(block, provider)
    if isinstance(block, UnparsedBlock):
        return _chunk_unparsed_block(block, provider)
    raise TypeError(f"Unknown block type: {type(block)!r}")


def chunk_page(page: PageExtraction, provider: EmbeddingProvider) -> list[Chunk]:
    """Chunks a single page's blocks. A chunk never spans two pages because this
    only ever operates on one page's blocks at a time - the caller (chunk_document)
    never merges chunks across pages."""
    chunks: list[Chunk] = []
    for block in page.blocks:
        chunks.extend(chunk_block(block, provider))
    for chunk in chunks:
        count = provider.count_tokens(chunk.text)
        if count > HARD_LIMIT_TOKENS:
            raise ChunkingError(
                f"Generated chunk on page {chunk.page_number} has {count} tokens, exceeding the "
                f"{HARD_LIMIT_TOKENS}-token hard limit - refusing to return it."
            )
    return chunks


def chunk_document(pages: list[PageExtraction], provider: EmbeddingProvider) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in pages:
        chunks.extend(chunk_page(page, provider))
    return chunks
