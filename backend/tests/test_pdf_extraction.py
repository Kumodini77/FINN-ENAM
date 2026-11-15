"""Real pdfplumber extraction tests against the genuine HDFC Q1 FY27 earnings
presentation PDF (no mocking - a real file, read with the real library). Page 4's
ground truth was hand-verified against the visible PDF during this session's
earlier live design review; it is kept as a permanent regression fixture."""

from pathlib import Path

import pytest

import re

from app.services.pdf_extraction import ProseBlock, UnparsedBlock, extract_pages, normalize_numeric_value

_WORD_RE = re.compile(r"[A-Za-z]{3,}")

HDFC_PDF = Path(__file__).parent.parent.parent / "scripts" / "spikes" / "fundamentals_access_spike" / "documents" / "hdfcbank_earnings_presentation.pdf"

# Ground truth for page 4's P&L table, hand-verified against the visible PDF.
EXPECTED_HEADER = "P&L (₹ bn) Q1 FY26 Q4 FY26 Q1 FY27 QoQ YoY"
EXPECTED_ROWS = [
    ("Net interest income", ["314.4", "330.8", "335.3", "1.4%", "6.7%"]),
    ("Non-interest income", ["217.3", "132.0", "128.2", "(2.9%)", "(41.0%)"]),
    ("Net revenue", ["531.7", "462.8", "463.6", "0.2%", "(12.8%)"]),
    ("Operating expenses", ["174.3", "184.8", "181.9", "(1.6%)", "4.3%"]),
    ("Provisions", ["144.4", "26.1", "30.6", "17.2%", "(78.8%)"]),
    ("Profit before tax", ["212.9", "251.9", "251.1", "(0.3%)", "17.9%"]),
    ("Profit after tax", ["181.6", "192.2", "190.6", "(0.8%)", "5.0%"]),
    ("Profit after tax (Adjusted)*", ["173.7", "192.2", "190.6", "(0.8%)", "9.8%"]),
]


@pytest.fixture(scope="module")
def pages():
    if not HDFC_PDF.exists():
        pytest.skip(f"Real HDFC PDF fixture not present at {HDFC_PDF}")
    return extract_pages(str(HDFC_PDF))


def test_pdf_has_36_pages(pages):
    assert len(pages) == 36


def test_page4_table_header_matches_ground_truth(pages):
    page4 = pages[3]
    tables = [b for b in page4.blocks if b.kind == "table_row_group"]
    assert len(tables) == 1
    assert tables[0].header_line == EXPECTED_HEADER


def test_page4_table_has_all_eight_rows(pages):
    page4 = pages[3]
    table = [b for b in page4.blocks if b.kind == "table_row_group"][0]
    assert len(table.rows) == 8
    assert [r.label for r in table.rows] == [label for label, _ in EXPECTED_ROWS]


def test_page4_all_forty_values_match_ground_truth_normalized(pages):
    """Normalized comparison (parentheses -> negative, '%' stripped) - not a
    misleading byte-exact string comparison."""
    page4 = pages[3]
    table = [b for b in page4.blocks if b.kind == "table_row_group"][0]
    for row, (expected_label, expected_values) in zip(table.rows, EXPECTED_ROWS):
        assert row.label == expected_label
        assert len(row.values) == len(expected_values) == 5
        for actual, expected in zip(row.values, expected_values):
            assert normalize_numeric_value(actual) == pytest.approx(normalize_numeric_value(expected))


def test_page1_cover_is_prose_negative_control(pages):
    page1 = pages[0]
    assert all(b.kind == "prose" for b in page1.blocks)
    assert not any(b.kind == "table_row_group" for b in page1.blocks)


def test_page12_rotated_chart_text_is_not_force_parsed_into_a_table(pages):
    """page 12 contains rotated chart-axis text that pdfplumber extracts as
    garbled, character-interleaved nonsense, plus two short genuinely-numeric lines
    under a bare footnote-marker line ('^') - neither should ever become a
    confident table_row_group."""
    page12 = pages[11]
    assert not any(b.kind == "table_row_group" for b in page12.blocks)
    assert any(b.kind == "table_unparsed" for b in page12.blocks)


def test_unparsed_blocks_require_manual_review_semantically():
    """pdf_extraction itself doesn't set needs_manual_review (that's chunking's
    job), but every UnparsedBlock must carry a real, non-empty reason - never a
    silent, unexplained refusal to parse."""
    from app.services.pdf_extraction import UnparsedBlock

    block = UnparsedBlock(page_number=1, text="27% 29%", reason="numeric-only lines with no row labels")
    assert block.reason
    assert block.kind == "table_unparsed"


def test_normalize_numeric_value_handles_parens_and_percent():
    assert normalize_numeric_value("(2.9%)") == -2.9
    assert normalize_numeric_value("314.4") == 314.4
    assert normalize_numeric_value("1,234.5") == 1234.5


# --- Regression: page 17's rotated NPA-chart text must never surface as unflagged
# prose (live-reported bug - a "gross/net NPA" question returned this garbled text
# as if it were reliable evidence). Ground truth hand-verified against the visible
# PDF: page 17 is a "Resilient asset quality" slide with a rotated bar-chart axis
# (quarter + GNPA/NNPA % labels drawn as rotated glyphs) that pdfplumber's
# extract_text() misorders into character-interleaved nonsense, plus several
# isolated chart-value fragments (e.g. "1.2% 1.1%") with no row-label context.


def test_page17_garbled_axis_text_is_never_classified_as_plain_prose(pages):
    page17 = pages[16]
    assert not any(b.kind == "table_row_group" for b in page17.blocks)
    for block in page17.blocks:
        if block.kind != "prose":
            continue
        lines = [l for l in block.text.split("\n") if l.strip()]
        no_word_lines = sum(1 for l in lines if not _WORD_RE.search(l))
        assert not (len(lines) >= 2 and no_word_lines / len(lines) > 0.5), (
            f"A prose block on page 17 is mostly word-less lines - looks like the "
            f"garbled-axis regression reappeared: {block.text!r}"
        )


def test_page17_garbled_axis_run_is_flagged_table_unparsed_with_manual_review(pages):
    page17 = pages[16]
    unparsed_texts = [b.text for b in page17.blocks if b.kind == "table_unparsed"]
    assert unparsed_texts, "page 17 should produce at least one table_unparsed block from its rotated chart"
    # The specific garbled run reported live: real fragments pulled straight from
    # pdfplumber's actual (mis-ordered) output for this page - not fabricated.
    combined = "\n".join(unparsed_texts)
    for fragment in ["N N P A", "1 . 4", "1 . 2"]:
        assert fragment in combined, f"expected garbled fragment {fragment!r} to be captured in an UnparsedBlock, not lost"


def test_page17_isolated_chart_percentages_without_row_labels_are_flagged(pages):
    """Short standalone chart-value lines (e.g. "1.2% 1.1%", "0.7% 0.7%") have no
    row-label context at all and must never be treated as reliable prose either."""
    page17 = pages[16]
    unparsed_texts = [b.text for b in page17.blocks if b.kind == "table_unparsed"]
    assert any("1.2% 1.1%" in t for t in unparsed_texts)
    assert any("0.7% 0.7%" in t for t in unparsed_texts)


def test_no_page_in_the_real_document_has_a_residual_garbled_prose_block(pages):
    """Whole-document sweep: after the fix, zero prose blocks anywhere should be
    dominated by word-less lines - the failure mode must be fully closed, not just
    patched for page 17 specifically."""
    offenders = []
    for page in pages:
        for block in page.blocks:
            if block.kind != "prose":
                continue
            lines = [l for l in block.text.split("\n") if l.strip()]
            if len(lines) < 2:
                continue
            no_word_lines = sum(1 for l in lines if not _WORD_RE.search(l))
            if no_word_lines / len(lines) > 0.6:
                offenders.append((page.page_number, block.text[:80]))
    assert offenders == [], f"residual garbled prose blocks found: {offenders}"


# --- Representative broken-text unit tests (synthetic, generic - not HDFC/NPA-specific) ---


def test_rotated_axis_style_fragments_are_flagged_not_treated_as_prose():
    """Synthetic reproduction of the general failure class: short, word-less,
    character-interleaved fragments (as pdfplumber produces for rotated text)."""
    from app.services.pdf_extraction import _extract_blocks_from_text

    raw_text = "1 . 2\nJ\n%\nu n\n'2\n5\nReal heading text here\nNormal prose sentence follows."
    blocks = _extract_blocks_from_text(raw_text, page_number=1)
    kinds = [b.kind for b in blocks]
    assert "table_unparsed" in kinds
    unparsed = [b for b in blocks if b.kind == "table_unparsed"][0]
    assert isinstance(unparsed, UnparsedBlock)
    assert unparsed.reason
    prose_blocks = [b for b in blocks if b.kind == "prose"]
    assert any("Real heading text here" in b.text for b in prose_blocks)
    assert any("Normal prose sentence follows." in b.text for b in prose_blocks)


def test_a_single_isolated_short_line_is_not_falsely_flagged():
    """One stray short/word-less line alone (not a sustained run) is not strong
    enough evidence of garbled text - avoids over-flagging an incidental artifact
    like a lone page-footer digit."""
    from app.services.pdf_extraction import _extract_blocks_from_text

    raw_text = "This is an ordinary sentence.\n4\nAnother ordinary sentence follows here."
    blocks = _extract_blocks_from_text(raw_text, page_number=1)
    assert not any(b.kind == "table_unparsed" for b in blocks)
    assert all(isinstance(b, ProseBlock) for b in blocks)


def test_real_table_rows_are_unaffected_by_the_garbled_text_detector():
    """A genuine data row/table must still be classified normally - the new
    detector only ever applies to lines that already failed the data-row and
    numeric-only-line checks."""
    from app.services.pdf_extraction import _extract_blocks_from_text

    raw_text = "Metric Q1 FY26 Q1 FY27\nRevenue 100.0 110.0\nProfit 20.0 25.0"
    blocks = _extract_blocks_from_text(raw_text, page_number=1)
    assert any(b.kind == "table_row_group" for b in blocks)
    assert not any(b.kind == "table_unparsed" for b in blocks)
