"""Phase 3B Task 3 - unit/scale normalization audit tests. Covers Indian and
international number formats, percentages, negatives, and missing/unstated
units. Generic - no company-specific fixtures."""

from app.services.numeric_answer import extract_numeric_answer
from app.services.unit_scale import extract_unit_scale_from_header


def test_all_supported_indian_scale_spellings_are_recognized():
    assert extract_unit_scale_from_header("(Rs mn)") == "INR million"
    assert extract_unit_scale_from_header("(Rs. million)") == "INR million"
    assert extract_unit_scale_from_header("(₹ bn)") == "INR billion"
    assert extract_unit_scale_from_header("(INR billion)") == "INR billion"
    assert extract_unit_scale_from_header("(Rs cr)") == "INR crore"
    assert extract_unit_scale_from_header("(₹ crore)") == "INR crore"
    assert extract_unit_scale_from_header("(Rs lakh)") == "INR lakh"
    assert extract_unit_scale_from_header("(Rs lac)") == "INR lakh"
    assert extract_unit_scale_from_header("(Rs '000)") == "INR thousand"


def test_unstated_unit_is_none_never_guessed():
    assert extract_unit_scale_from_header("Metric Q1FY26 Q2FY26") is None
    assert extract_unit_scale_from_header("(EPS in Rs) Q1FY26 Q2FY26") is None


def test_percentage_value_never_carries_the_header_currency_scale():
    text = "(Rs cr) Q1FY26 Q2FY26\nGross Margin %: Q1FY26=10.0% | Q2FY26=11.0%\n"
    ans = extract_numeric_answer("What was gross margin in Q2 FY26?", text)
    assert ans is not None
    assert ans.value == "11.0%"
    assert ans.unit_scale is None
    assert ans.normalized_value is None


def test_plain_currency_value_carries_the_header_scale():
    text = "(Rs cr) Q1FY26 Q2FY26\nSales: Q1FY26=100 | Q2FY26=120\n"
    ans = extract_numeric_answer("What was Sales in Q2 FY26?", text)
    assert ans is not None
    assert ans.value == "120"
    assert ans.unit_scale == "INR crore"
    assert ans.normalized_value == "120"


def test_negative_parenthesised_value_normalizes_but_keeps_raw_value_intact():
    text = "(Rs cr) Q1FY26 Q2FY26\nPAT: Q1FY26=(10) | Q2FY26=(12)\n"
    ans = extract_numeric_answer("What was PAT in Q2 FY26?", text)
    assert ans is not None
    assert ans.value == "(12)"  # raw, displayed value untouched
    assert ans.normalized_value == "-12"
    assert ans.unit_scale == "INR crore"


def test_indian_comma_grouping_normalizes_to_a_plain_digit_string():
    text = "(Rs mn) Q1FY26 Q2FY26\nSales: Q1FY26=1,44,052 | Q2FY26=1,61,000\n"
    ans = extract_numeric_answer("What was Sales in Q2 FY26?", text)
    assert ans is not None
    assert ans.value == "1,61,000"
    assert ans.normalized_value == "161000"


def test_international_comma_grouping_also_normalizes_correctly():
    text = "(Rs mn) Q1FY26 Q2FY26\nSales: Q1FY26=144,052 | Q2FY26=161,000\n"
    ans = extract_numeric_answer("What was Sales in Q2 FY26?", text)
    assert ans is not None
    assert ans.value == "161,000"
    assert ans.normalized_value == "161000"


def test_ambiguous_binding_never_attaches_a_unit_scale_to_an_unresolved_value():
    text = "(Rs cr) Q1FY26 Q1FY26 Q2FY26\nSales: 100 | 999 | 120\n"
    ans = extract_numeric_answer("What was Sales in Q1 FY26?", text)
    assert ans is not None and ans.ambiguous_period_binding
    assert ans.unit_scale is None


def test_a_unit_stated_in_one_tables_header_is_not_applied_to_a_different_header_without_one():
    with_unit = "(Rs cr) Q1FY26 Q2FY26\nSales: Q1FY26=100 | Q2FY26=120\n"
    without_unit = "Metric Q1FY26 Q2FY26\nSales: Q1FY26=100 | Q2FY26=120\n"
    ans_with = extract_numeric_answer("What was Sales in Q2 FY26?", with_unit)
    ans_without = extract_numeric_answer("What was Sales in Q2 FY26?", without_unit)
    assert ans_with is not None and ans_with.unit_scale == "INR crore"
    assert ans_without is not None and ans_without.unit_scale is None


def test_apostrophe_quarter_shorthand_resolves_like_q_fy_form():
    """Real finding from a genuine Wipro document: its header uses "Q2'27"
    instead of "Q2 FY27" - a different but equally real shorthand, not specific
    to Wipro (several companies use it)."""
    text = "Q2'27 (Rs mn) QoQ Growth YoY Growth\nIT Services Revenue: 246,670 | 0.9% | 9.0%\n"
    ans = extract_numeric_answer("What was IT Services Revenue in Q2 FY27?", text)
    assert ans is not None and ans.value == "246,670" and not ans.ambiguous_period_binding
