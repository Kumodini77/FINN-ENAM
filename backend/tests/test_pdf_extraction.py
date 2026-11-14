"""Real pdfplumber extraction tests against the genuine HDFC Q1 FY27 earnings
presentation PDF (no mocking - a real file, read with the real library). Page 4's
ground truth was hand-verified against the visible PDF during this session's
earlier live design review; it is kept as a permanent regression fixture."""

from pathlib import Path

import pytest

from app.services.pdf_extraction import extract_pages, normalize_numeric_value

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
