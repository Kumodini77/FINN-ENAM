"""Synthetic, cross-sector tests for the sparse/optional-column table reconciliation
added after a real finding on Sun Pharma's "Financial Snapshot" table (see the
module docstring in app.services.pdf_extraction). None of these fixtures are drawn
from a real company - they exercise the GENERIC structural rules (optional delta
columns, units, synonyms, negatives/percentages, ambiguous periods, tables that
must remain unparsed) so a fix proven only against Sun Pharma/HDFC doesn't
accidentally rely on something specific to either document."""

from app.services.chunking import _format_table_row_group
from app.services.numeric_answer import extract_numeric_answer
from app.services.pdf_extraction import TableBlock, _extract_blocks_from_text
from app.services.unit_scale import extract_unit_scale_from_header


def _only_table_block(raw_text: str) -> TableBlock:
    blocks = _extract_blocks_from_text(raw_text, page_number=1)
    tables = [b for b in blocks if b.kind == "table_row_group"]
    assert len(tables) == 1, f"expected exactly one table_row_group, got: {blocks}"
    return tables[0]


def test_optional_delta_columns_reconcile_against_period_only_rows():
    raw_text = (
        "Segment Revenue (Rs cr) FY24 FY25 YoY FY26 YoY\n"
        "Chemicals 100 110 10.0% 121 10.0%\n"
        "Textiles 50 55 50\n"
        "Logistics 20 22 10.0% 24 9.1%\n"
    )
    table = _only_table_block(raw_text)
    by_label = {r.label: r for r in table.rows}
    assert by_label["Chemicals"].column_labels == ["FY24", "FY25", "YOY", "FY26", "YOY"]
    assert by_label["Textiles"].column_labels == ["FY24", "FY25", "FY26"]
    assert by_label["Logistics"].column_labels == ["FY24", "FY25", "YOY", "FY26", "YOY"]


def test_row_whose_shortfall_does_not_match_either_shape_bails_the_whole_table():
    raw_text = (
        "Segment Revenue (Rs cr) FY24 FY25 YoY FY26 YoY\n"
        "Chemicals 100 110 10.0% 121 10.0%\n"
        "Textiles 50 55\n"  # 2 values: neither 5 (full) nor 3 (period-only)
        "Logistics 20 22 10.0% 24 9.1%\n"
    )
    blocks = _extract_blocks_from_text(raw_text, page_number=1)
    assert not any(b.kind == "table_row_group" for b in blocks)
    assert any(b.kind == "table_unparsed" for b in blocks)


def test_never_assigns_a_value_to_the_wrong_period_for_a_sparse_row():
    raw_text = (
        "Metric (Rs mn) Q1FY26 Q2FY26 YoY Q3FY26 YoY\n"
        "EBITDA 10 20 100.0% 30 50.0%\n"
        "PAT 5 6 7\n"
    )
    table = _only_table_block(raw_text)
    pat_row = next(r for r in table.rows if r.label == "PAT")
    assert pat_row.column_labels == ["Q1FY26", "Q2FY26", "Q3FY26"]
    text = _format_table_row_group(table.header_line, table.title, table.rows, 0, len(table.rows), len(table.rows))
    ans = extract_numeric_answer("What was the PAT in Q3 FY26?", text)
    assert ans is not None and ans.value == "7" and not ans.ambiguous_period_binding
    ans2 = extract_numeric_answer("What was the PAT in Q2 FY26?", text)
    assert ans2 is not None and ans2.value == "6" and not ans2.ambiguous_period_binding


def test_metric_synonym_resolves_regardless_of_sparse_columns():
    raw_text = (
        "P&L (Rs cr) Q1FY26 Q2FY26 YoY\n"
        "Net Sales 100 120 20.0%\n"
        "Other Income 5 6\n"
    )
    table = _only_table_block(raw_text)
    text = _format_table_row_group(table.header_line, table.title, table.rows, 0, len(table.rows), len(table.rows))
    ans = extract_numeric_answer("What was the turnover in Q2 FY26?", text)
    assert ans is not None and ans.value == "120"


def test_half_year_question_binds_against_a_sparse_half_year_column():
    raw_text = (
        "Financials (Rs mn) Q1FY27 Q2FY27 YoY H1FY27 H1FY26 YoY\n"
        "Net Sales 100 110 10.0% 210 190 10.5%\n"
        "Gross Margin % 10.0% 11.0% 10.5% 10.2%\n"
    )
    table = _only_table_block(raw_text)
    text = _format_table_row_group(table.header_line, table.title, table.rows, 0, len(table.rows), len(table.rows))
    ans = extract_numeric_answer("What was the gross margin in H1 FY26?", text)
    assert ans is not None and ans.value == "10.2%" and not ans.ambiguous_period_binding


def test_negative_parenthesised_and_percentage_values_pass_through_unaltered():
    raw_text = (
        "P&L (Rs cr) Q1FY26 Q2FY26 YoY\n"
        "PAT (10) (12) -20.0%\n"
        "EBITDA 5.0% 6.0%\n"
    )
    table = _only_table_block(raw_text)
    row = next(r for r in table.rows if r.label == "PAT")
    assert row.values == ["(10)", "(12)", "-20.0%"]
    text = _format_table_row_group(table.header_line, table.title, table.rows, 0, len(table.rows), len(table.rows))
    ans = extract_numeric_answer("What was the PAT in Q2 FY26?", text)
    assert ans is not None and ans.value == "(12)"


def test_indian_comma_grouped_values_round_trip_through_chunk_rendering():
    raw_text = (
        "Financial Snapshot (Rs mn) Q2FY27 Q2FY26 YoY\n"
        "Sales 1,61,000 1,44,052 11.8%\n"
        "Margin % 29.3% 31.3%\n"
    )
    table = _only_table_block(raw_text)
    text = _format_table_row_group(table.header_line, table.title, table.rows, 0, len(table.rows), len(table.rows))
    ans = extract_numeric_answer("What was Sales in Q2 FY27?", text)
    assert ans is not None
    assert ans.value == "1,61,000"
    assert ans.normalized_value == "161000"


def test_unit_scale_extracted_from_header_notation_only():
    assert extract_unit_scale_from_header("(Rs mn) Q1FY26 Q2FY26") == "INR million"
    assert extract_unit_scale_from_header("(₹ cr) Q1FY26 Q2FY26") == "INR crore"
    assert extract_unit_scale_from_header("Metric Q1FY26 Q2FY26") is None


def test_extraction_method_is_labeled_for_sparse_binding_and_positional_otherwise():
    sparse_text = (
        "P&L (Rs cr) Q1FY26 Q2FY26 YoY\n"
        "EBITDA 100 120 20.0%\n"
        "PAT 5 6\n"
    )
    table = _only_table_block(sparse_text)
    text = _format_table_row_group(table.header_line, table.title, table.rows, 0, len(table.rows), len(table.rows))
    ans = extract_numeric_answer("What was PAT in Q2 FY26?", text)
    assert ans is not None and ans.extraction_method == "labeled_column"

    uniform_text = "P&L (Rs cr) Q1FY26 Q2FY26\nEBITDA: 100 | 120"
    ans2 = extract_numeric_answer("What was EBITDA in Q2 FY26?", uniform_text)
    assert ans2 is not None and ans2.extraction_method == "positional_period_binding"


def test_a_sparse_row_with_no_period_requested_is_flagged_ambiguous_not_guessed():
    raw_text = (
        "P&L (Rs cr) Q1FY26 Q2FY26 YoY\n"
        "EBITDA 100 120 20.0%\n"
        "PAT 5 6\n"
    )
    table = _only_table_block(raw_text)
    pat_row = next(r for r in table.rows if r.label == "PAT")
    assert pat_row.column_labels == ["Q1FY26", "Q2FY26"]
    text = _format_table_row_group(table.header_line, table.title, [pat_row], 0, 1, 1)
    ans = extract_numeric_answer("What was PAT?", text)
    assert ans is not None and ans.ambiguous_period_binding
    assert set(ans.all_values_for_row) == {"5", "6"}


def test_table_with_no_header_period_tokens_still_bails_to_unparsed_or_ambiguous():
    raw_text = (
        "Some Metrics Table\n"
        "Chemicals 100 110 10.0% 121 10.0%\n"
        "Textiles 50 55\n"
        "Logistics 20 22 10.0% 24 9.1%\n"
    )
    blocks = _extract_blocks_from_text(raw_text, page_number=1)
    # No recognizable period/delta tokens in "Some Metrics Table" - reconciliation
    # must refuse (never guess at header columns that aren't there), so this stays
    # table_unparsed rather than being force-structured.
    assert not any(b.kind == "table_row_group" for b in blocks)
