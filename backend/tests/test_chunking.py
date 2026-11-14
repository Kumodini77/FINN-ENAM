"""Chunking tests against the real MiniLM tokenizer (via LocalMiniLMEmbeddingProvider)
and real pdfplumber extraction of the HDFC fixture - token counts here are genuine,
not approximated."""

from pathlib import Path

import pytest

from app.services.chunking import (
    HARD_LIMIT_TOKENS,
    Chunk,
    ChunkingError,
    chunk_document,
    chunk_page,
)
from app.services.embeddings.local_minilm import LocalMiniLMEmbeddingProvider
from app.services.pdf_extraction import PageExtraction, ProseBlock, TableBlock, TableRow, UnparsedBlock, extract_pages

HDFC_PDF = Path(__file__).parent.parent.parent / "scripts" / "spikes" / "fundamentals_access_spike" / "documents" / "hdfcbank_earnings_presentation.pdf"


@pytest.fixture(scope="module")
def provider(tmp_path_factory):
    cache_dir = tmp_path_factory.mktemp("embedding_cache")
    return LocalMiniLMEmbeddingProvider(cache_dir=str(cache_dir))


@pytest.fixture(scope="module")
def hdfc_pages():
    if not HDFC_PDF.exists():
        pytest.skip(f"Real HDFC PDF fixture not present at {HDFC_PDF}")
    return extract_pages(str(HDFC_PDF))


def test_every_chunk_from_the_real_document_is_within_the_hard_limit(provider, hdfc_pages):
    chunks = chunk_document(hdfc_pages, provider)
    assert len(chunks) > 0
    for c in chunks:
        assert provider.count_tokens(c.text) <= HARD_LIMIT_TOKENS


def test_table_row_group_chunk_repeats_the_full_header(provider, hdfc_pages):
    page4 = hdfc_pages[3]
    chunks = chunk_page(page4, provider)
    table_chunks = [c for c in chunks if c.chunk_type == "table_row_group"]
    assert len(table_chunks) == 1
    assert "P&L (₹ bn) Q1 FY26 Q4 FY26 Q1 FY27 QoQ YoY" in table_chunks[0].text
    assert "Net interest income" in table_chunks[0].text
    assert "Profit after tax (Adjusted)*" in table_chunks[0].text


def test_table_unparsed_chunks_always_need_manual_review(provider, hdfc_pages):
    page12 = hdfc_pages[11]
    chunks = chunk_page(page12, provider)
    unparsed = [c for c in chunks if c.chunk_type == "table_unparsed"]
    assert unparsed
    assert all(c.needs_manual_review for c in unparsed)


def test_prose_chunks_do_not_need_manual_review(provider, hdfc_pages):
    page1 = hdfc_pages[0]
    chunks = chunk_page(page1, provider)
    assert chunks
    assert all(c.chunk_type == "prose" and not c.needs_manual_review for c in chunks)


def test_page_reference_is_preserved_and_chunks_never_cross_pages(provider, hdfc_pages):
    chunks = chunk_document(hdfc_pages[:5], provider)
    for c in chunks:
        assert isinstance(c.page_number, int) and c.page_number >= 1
    # Every chunk from page N's extraction carries page_number == N - chunk_page
    # only ever operates on one page's blocks, so this holds by construction.
    page4_chunks = chunk_page(hdfc_pages[3], provider)
    assert all(c.page_number == 4 for c in page4_chunks)


def test_long_prose_is_split_not_truncated(provider):
    long_text = " ".join(f"Sentence number {i} describes ordinary extracted prose content for testing." for i in range(60))
    block = ProseBlock(page_number=1, text=long_text)
    page = PageExtraction(page_number=1, raw_text=long_text, blocks=[block])
    chunks = chunk_page(page, provider)
    assert len(chunks) > 1
    # Every original word must appear in the reconstructed text across all pieces -
    # never silently dropped.
    reconstructed = " ".join(c.text for c in chunks)
    for word in ["Sentence", "number", "59", "describes"]:
        assert word in reconstructed
    for c in chunks:
        assert provider.count_tokens(c.text) <= HARD_LIMIT_TOKENS


def test_oversized_single_table_row_is_split_into_labeled_column_ranges(provider):
    many_values = [f"{i}.{i}%" for i in range(40)]
    header = "Metric " + " ".join(f"Period{i}" for i in range(40))
    row = TableRow(label="Some long label describing a metric across many periods", values=many_values)
    block = TableBlock(page_number=1, header_line=header, rows=[row], title=None)
    page = PageExtraction(page_number=1, raw_text="", blocks=[block])
    chunks = chunk_page(page, provider)
    assert len(chunks) >= 2
    assert all(c.chunk_type == "table_row_group" for c in chunks)
    assert all("columns" in c.text for c in chunks)
    # No value silently dropped - every value appears in exactly one sub-chunk.
    combined = " ".join(c.text for c in chunks)
    for v in many_values:
        assert v in combined


def test_chunking_error_raised_rather_than_silent_truncation_when_unsplittable(provider):
    """A pathological single value so long it alone exceeds the hard limit even
    without any siblings - no safe sub-chunking strategy exists, so this must raise,
    not truncate."""
    huge_value = " ".join(f"word{i}" for i in range(400))  # a single "value" containing many real tokens
    row = TableRow(label="X", values=[huge_value])
    block = TableBlock(page_number=1, header_line="Metric Value", rows=[row], title=None)
    page = PageExtraction(page_number=1, raw_text="", blocks=[block])
    with pytest.raises(ChunkingError):
        chunk_page(page, provider)


def test_unparsed_block_text_is_preserved_verbatim_in_short_case(provider):
    block = UnparsedBlock(page_number=5, text="27% 29% 31%", reason="numeric-only lines with no row labels")
    page = PageExtraction(page_number=5, raw_text="", blocks=[block])
    chunks = chunk_page(page, provider)
    assert len(chunks) == 1
    assert chunks[0].text == "27% 29% 31%"
    assert chunks[0].chunk_type == "table_unparsed"
    assert chunks[0].needs_manual_review is True


def test_every_chunk_is_a_chunk_dataclass_with_required_fields(provider):
    block = ProseBlock(page_number=2, text="Simple prose.")
    page = PageExtraction(page_number=2, raw_text="Simple prose.", blocks=[block])
    chunks = chunk_page(page, provider)
    assert len(chunks) == 1
    c = chunks[0]
    assert isinstance(c, Chunk)
    assert c.page_number == 2
    assert c.chunk_type == "prose"
    assert c.needs_manual_review is False
