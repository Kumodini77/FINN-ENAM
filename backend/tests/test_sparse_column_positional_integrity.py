"""Phase 3B Task 2 - positional-integrity audit tests for sparse-column
reconciliation and the underlying row-splitting heuristic. These target exactly
the failure modes the audit called out: a missing optional column at the end, a
missing value in the MIDDLE of a row, two candidate mappings with identical
value counts, a row with a valid count that still can't be mapped reliably, and
repeated/similar period labels in the header. None of these are tied to a real
company - they exercise generic structural rules."""

from app.services.chunking import _format_table_row_group
from app.services.numeric_answer import extract_numeric_answer
from app.services.pdf_extraction import TableBlock, _extract_blocks_from_text


def _only_table_block(raw_text: str) -> TableBlock:
    blocks = _extract_blocks_from_text(raw_text, page_number=1)
    tables = [b for b in blocks if b.kind == "table_row_group"]
    assert len(tables) == 1, f"expected exactly one table_row_group, got: {blocks}"
    return tables[0]


def test_optional_delta_column_missing_at_the_end_binds_correctly():
    raw_text = (
        "P&L (Rs cr) Q1FY26 Q2FY26 YoY\n"
        "EBITDA 100 110 10.0%\n"
        "PAT 50 55\n"
    )
    table = _only_table_block(raw_text)
    pat = next(r for r in table.rows if r.label == "PAT")
    assert pat.values == ["50", "55"]
    assert pat.column_labels == ["Q1FY26", "Q2FY26"]


def test_missing_value_in_the_middle_of_a_row_never_shifts_later_values():
    """A real positional-integrity bug found during this audit: a middle "NA"
    stopped the trailing-numeric scan early, swallowing the real value before it
    into the row's label and shifting every value after it into the wrong
    column. Must now bind EVERY column correctly, including the missing one."""
    raw_text = (
        "P&L (Rs cr) Q1FY26 Q2FY26 Q3FY26\n"
        "Sales NA 110 120\n"
        "EBITDA 10 20 30\n"
    )
    table = _only_table_block(raw_text)
    sales = next(r for r in table.rows if r.label == "Sales")
    assert sales.values == ["NA", "110", "120"]
    text = _format_table_row_group(table.header_line, table.title, [sales], 0, 1, 1)
    ans = extract_numeric_answer("What was Sales in Q2 FY26?", text)
    assert ans is not None and ans.value == "110"  # NOT the Q1 slot's "NA" or a shifted value
    ans3 = extract_numeric_answer("What was Sales in Q3 FY26?", text)
    assert ans3 is not None and ans3.value == "120"


def test_missing_middle_value_with_optional_delta_column_still_binds_correctly():
    raw_text = (
        "P&L (Rs cr) Q1FY26 Q2FY26 YoY\n"
        "Sales NA 110 5.0%\n"
        "EBITDA 10 20 30.0%\n"
    )
    table = _only_table_block(raw_text)
    sales = next(r for r in table.rows if r.label == "Sales")
    # This row reports ALL THREE header columns (Q1 missing, Q2 present, YoY
    # present) - it must NOT be mistaken for a sparse (period-only) row just
    # because its raw value count happens to match len(period_labels).
    assert sales.values == ["NA", "110", "5.0%"]
    assert sales.column_labels is None  # full-width row, not sparse-reconciled
    text = _format_table_row_group(table.header_line, table.title, [sales], 0, 1, 1)
    ans = extract_numeric_answer("What was Sales in Q2 FY26?", text)
    assert ans is not None and ans.value == "110"  # the real Q2 value, not Q1's "NA" or the YoY%


def test_repeated_period_label_in_header_is_never_silently_resolved():
    """A header with the same period token twice (accidental duplication, or a
    parsing artifact) must not let dict(zip(...)) silently drop one column's
    value - that would present a confidently-wrong figure under the WRONG
    period's name."""
    text = "P&L (Rs cr) Q1FY26 Q1FY26 Q2FY26\nSales: 100 | 999 | 120\n"
    ans = extract_numeric_answer("What was Sales in Q1 FY26?", text)
    assert ans is not None
    assert ans.ambiguous_period_binding is True
    assert ans.value == ""


def test_repeated_period_label_on_a_sparse_labeled_row_is_also_rejected():
    text = "P&L (Rs cr) Q1FY26 Q1FY26 Q2FY26\nSales: Q1FY26=100 | Q1FY26=999 | Q2FY26=120\n"
    ans = extract_numeric_answer("What was Sales in Q1 FY26?", text)
    assert ans is not None
    assert ans.ambiguous_period_binding is True
    assert ans.value == ""


def test_row_whose_count_fits_no_defensible_shape_is_rejected_not_guessed():
    """A row with a value count that matches NEITHER the full column width NOR
    the period-only width has no defensible mapping - reject the whole table."""
    raw_text = (
        "P&L (Rs cr) Q1FY26 Q2FY26 YoY Q3FY26 YoY\n"
        "Sales 100 110 10.0% 120 20.0%\n"
        "EBITDA 10 20 30\n"  # 3 values: full=5, period-only=3 -> matches period-only, fine
        "PAT 1 2 3 4\n"  # 4 values: neither 5 nor 3 -> must bail the WHOLE table
    )
    blocks = _extract_blocks_from_text(raw_text, page_number=1)
    assert not any(b.kind == "table_row_group" for b in blocks)
    assert any(b.kind == "table_unparsed" for b in blocks)


def test_indian_comma_grouped_numbers_remain_intact_through_sparse_binding():
    raw_text = (
        "Financial Snapshot (Rs mn) Q2FY27 Q2FY26 YoY\n"
        "Sales 1,61,000 1,44,052 11.8%\n"
        "Margin % 29.3% 31.3%\n"
    )
    table = _only_table_block(raw_text)
    margin = next(r for r in table.rows if r.label == "Margin %")
    assert margin.values == ["29.3%", "31.3%"]
    sales = next(r for r in table.rows if r.label == "Sales")
    assert sales.values == ["1,61,000", "1,44,052", "11.8%"]
