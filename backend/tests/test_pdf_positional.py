"""Phase 8 - regression tests for app.services.pdf_positional, the
position-aware (word-coordinate) header-reconstruction prototype. Every
fixture below is extracted LIVE from the real local PDFs (not synthetic) -
these are the two deliberately difficult documents Phase 7 identified as
needing position data, plus HDFC/Sun Pharma as a sanity check that the same
positional approach doesn't produce a WORSE or different answer than the
existing, already-correct plain-text path for the simple cases it already
handles."""

import re

from app.services.pdf_positional import (
    extract_page_words,
    group_words_into_lines,
    reconstruct_column_periods,
)

LT_PDF = "/Users/kumodini/FINN-ENAM/scripts/spikes/fundamentals_access_spike/documents/lt_q2fy27_consolidated_results.pdf"
ICICI_PDF = "/Users/kumodini/FINN-ENAM/scripts/spikes/fundamentals_access_spike/documents/icicibank_q2fy27_investor_presentation.pdf"
HDFC_PDF = "/Users/kumodini/FINN-ENAM/scripts/spikes/fundamentals_access_spike/documents/hdfcbank_earnings_presentation.pdf"

_NUM_RE = re.compile(r"^\(?-?[\d,]+(\.\d+)?%?\)?$")


def _is_numeric(text: str) -> bool:
    return bool(_NUM_RE.match(text))


def _find_data_row(lines: list, marker: str) -> int:
    for i, line in enumerate(lines):
        if marker in " ".join(w.text for w in line):
            return i
    raise AssertionError(f"no line contains {marker!r}")


def _anchors_and_values(lines: list, row_idx: int) -> tuple[list[float], list[str]]:
    numeric_words = [w for w in lines[row_idx] if _is_numeric(w.text)]
    return [w.center_x for w in numeric_words], [w.text for w in numeric_words]


def test_lt_regulation33_merged_header_spans_three_quarter_columns():
    """The real failure Phase 7 diagnosed: "Quarter ended" visually spans 3
    columns (current quarter, prior quarter, year-ago quarter) with no
    column-count hint in the plain text at all. Position data must recover
    all 6 real columns correctly."""
    words = extract_page_words(LT_PDF, 9)
    lines = group_words_into_lines(words)
    row_idx = _find_data_row(lines, "Revenue from operations")
    anchors, values = _anchors_and_values(lines, row_idx)
    assert values == ["78749.94", "67941.74", "67983.53", "146691.68", "131662.45", "285874.36"]
    header_lines = lines[row_idx - 6 : row_idx]
    periods = reconstruct_column_periods(header_lines, anchors)
    assert periods == ["Q2FY27", "Q1FY27", "Q2FY26", "H1FY27", "H1FY26", "FY26"]


def test_icici_dash_shorthand_header_with_standalone_fy_column():
    """The real failure Phase 7 diagnosed: a 3-line header with mismatched
    token counts (6 shorthand tokens on one line, a single lone "FY2026" on
    another) plus a genuinely real 7th (standalone full-year) column with NO
    quarter/half label at all on the shorthand line - the hardest real case
    found. The QoQ growth% delta column must correctly stay unresolved."""
    words = extract_page_words(ICICI_PDF, 46)
    lines = group_words_into_lines(words)
    row_idx = _find_data_row(lines, "Operating profit")
    anchors, values = _anchors_and_values(lines, row_idx)
    assert values == ["826.96", "199.74", "412.91", "226.04", "240.10", "466.14", "20.2%"]
    header_lines = lines[row_idx - 3 : row_idx]
    periods = reconstruct_column_periods(header_lines, anchors)
    assert periods == ["FY26", "Q2FY26", "H1FY26", "Q1FY27", "Q2FY27", "H1FY27", None]


def test_hdfc_simple_header_is_not_made_worse_by_positional_reconstruction():
    """HDFC's header ("P&L (Rs bn) Q1 FY26 Q4 FY26 Q1 FY27 QoQ YoY") is a
    SINGLE line that the existing plain-text path already resolves
    correctly. The positional path is not wired into the live pipeline for
    this document, but must not silently produce an incompatible or wrong
    result if ever pointed at it - a sanity check, not a regression gate on
    the live pipeline itself."""
    words = extract_page_words(HDFC_PDF, 4)
    lines = group_words_into_lines(words)
    row_idx = _find_data_row(lines, "Net interest income")
    anchors, values = _anchors_and_values(lines, row_idx)
    assert "335.3" in values  # the known ground-truth Q1 FY27 NII figure
    header_lines = lines[row_idx - 1 : row_idx]
    periods = reconstruct_column_periods(header_lines, anchors)
    # HDFC's "Q1 FY26" (space-separated) is a THIRD header convention this
    # prototype doesn't target (only spelled-out "Quarter ended <date>" and
    # dash-shorthand "Q1-<year>" are implemented) - the existing plain-text
    # path already handles this document correctly in production, so the
    # only thing this sanity check requires is that the positional path
    # fails SAFELY (no resolved period at all) rather than producing a
    # wrong one.
    assert all(p is None for p in periods)


def test_delta_column_never_mistaken_for_a_period_column():
    """Both real fixtures above already prove this in context (the QoQ/growth
    columns correctly return None) - this isolates the guarantee as its own
    assertion so a future change can't silently regress it without a
    dedicated test failing."""
    words = extract_page_words(ICICI_PDF, 46)
    lines = group_words_into_lines(words)
    row_idx = _find_data_row(lines, "Operating profit")
    anchors, _ = _anchors_and_values(lines, row_idx)
    header_lines = lines[row_idx - 3 : row_idx]
    periods = reconstruct_column_periods(header_lines, anchors)
    assert periods[-1] is None  # the "Q2-o-Q2 growth" delta column


def test_indian_comma_grouped_values_pass_through_the_anchor_extraction_unaltered():
    """The numeric-token regex used to derive anchors must not be fooled by
    Indian digit grouping (e.g. "1,61,000") into treating it as multiple
    separate numbers."""
    assert _is_numeric("1,61,000")
    assert _is_numeric("(1,234.56)")
    assert not _is_numeric("Reviewed")


def test_delta_columns_get_a_clean_canonical_label_not_raw_text():
    """A real finding (Wipro): a delta column's combined text can carry a
    stray unrelated word (a unit annotation line with no pattern of its own,
    swept in as an ungrouped word) - using that raw text as the label would
    corrupt the "label=value" chunk-rendering format every downstream
    consumer assumes. The label must always be a clean, single token."""
    from app.services.pdf_positional import reconstruct_column_kinds, WordBox

    # Synthetic but realistic: a delta group whose combined text (across
    # several header lines) picked up a stray fragment.
    line = [WordBox("Q2-o-Q2", 100, 140, 0, 10), WordBox("growth", 145, 180, 0, 10)]
    stray_line = [WordBox("million)", 150, 190, 10, 20)]
    kinds = reconstruct_column_kinds([line, stray_line], [160.0])
    assert len(kinds) == 1
    kind, label = kinds[0]
    assert kind == "delta"
    assert re.fullmatch(r"[A-Za-z]+", label)
