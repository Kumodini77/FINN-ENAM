"""Tests for metric-name ambiguity resolution in app.services.numeric_answer
(Phase 3B Task 1). None of these fixtures are tied to a real company - the point
is that the resolution logic is generic: any table with two rows that both match
a bare metric alias (e.g. "Reported X" / "Adjusted X", "Gross X" / "Net X",
"Standalone X" / "Consolidated X") must never silently pick the first one."""

from app.services.numeric_answer import extract_numeric_answer


def test_bare_metric_with_two_qualified_rows_is_flagged_ambiguous_not_guessed():
    text = (
        "P&L (Rs cr) Q1FY26 Q2FY26\n"
        "Reported PAT: 100 | 120\n"
        "Adjusted PAT: 90 | 110\n"
    )
    ans = extract_numeric_answer("What was PAT in Q2 FY26?", text)
    assert ans is not None
    assert ans.ambiguous_metric_selection is True
    assert set(ans.metric_alternatives) == {"Reported PAT", "Adjusted PAT"}
    assert ans.value == ""


def test_question_naming_one_qualifier_resolves_to_that_row():
    text = (
        "P&L (Rs cr) Q1FY26 Q2FY26\n"
        "Reported PAT: 100 | 120\n"
        "Adjusted PAT: 90 | 110\n"
    )
    reported = extract_numeric_answer("What was Reported PAT in Q2 FY26?", text)
    assert reported is not None and not reported.ambiguous_metric_selection
    assert reported.metric_label == "Reported PAT" and reported.value == "120"

    adjusted = extract_numeric_answer("What was Adjusted PAT in Q2 FY26?", text)
    assert adjusted is not None and not adjusted.ambiguous_metric_selection
    assert adjusted.metric_label == "Adjusted PAT" and adjusted.value == "110"


def test_gross_vs_net_revenue_rows_are_ambiguous_for_a_bare_revenue_question():
    text = (
        "P&L (Rs cr) Q1FY26 Q2FY26\n"
        "Gross Revenue: 500 | 550\n"
        "Net Revenue: 480 | 520\n"
    )
    ans = extract_numeric_answer("What was the revenue in Q2 FY26?", text)
    assert ans is not None and ans.ambiguous_metric_selection is True
    assert set(ans.metric_alternatives) == {"Gross Revenue", "Net Revenue"}


def test_gross_revenue_question_resolves_unambiguously():
    text = (
        "P&L (Rs cr) Q1FY26 Q2FY26\n"
        "Gross Revenue: 500 | 550\n"
        "Net Revenue: 480 | 520\n"
    )
    ans = extract_numeric_answer("What was gross revenue in Q2 FY26?", text)
    assert ans is not None and not ans.ambiguous_metric_selection
    assert ans.metric_label == "Gross Revenue" and ans.value == "550"


def test_standalone_vs_consolidated_is_ambiguous_without_a_qualifier():
    text = (
        "P&L (Rs cr) Q1FY26 Q2FY26\n"
        "Standalone EBITDA: 200 | 220\n"
        "Consolidated EBITDA: 250 | 270\n"
    )
    ans = extract_numeric_answer("What was EBITDA in Q2 FY26?", text)
    assert ans is not None and ans.ambiguous_metric_selection is True
    assert set(ans.metric_alternatives) == {"Standalone EBITDA", "Consolidated EBITDA"}

    consolidated = extract_numeric_answer("What was consolidated EBITDA in Q2 FY26?", text)
    assert consolidated is not None and not consolidated.ambiguous_metric_selection
    assert consolidated.value == "270"


def test_a_single_matching_row_is_never_treated_as_ambiguous():
    text = "P&L (Rs cr) Q1FY26 Q2FY26\nReported PAT: 100 | 120\n"
    ans = extract_numeric_answer("What was PAT in Q2 FY26?", text)
    assert ans is not None and not ans.ambiguous_metric_selection
    assert ans.value == "120"


def test_exact_verbatim_label_in_question_wins_even_if_another_row_shares_a_word():
    text = (
        "P&L (Rs cr) Q1FY26 Q2FY26\n"
        "Reported PAT: 100 | 120\n"
        "Adjusted PAT: 90 | 110\n"
        "PAT Margin: 10.0 | 11.0\n"
    )
    ans = extract_numeric_answer("What was the Reported PAT in Q2 FY26?", text)
    assert ans is not None and not ans.ambiguous_metric_selection
    assert ans.metric_label == "Reported PAT" and ans.value == "120"
