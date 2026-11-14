from datetime import datetime, timezone

import pytest

from app.models.announcement import FinancialBasis, FinancialMetric
from app.services.financial_extraction import (
    InvalidPeriodFormat,
    compare_period,
    previous_quarter_period,
    same_quarter_last_year_period,
)


def test_previous_quarter_period_within_same_fy():
    assert previous_quarter_period("Q2FY26") == "Q1FY26"


def test_previous_quarter_period_rolls_back_fiscal_year():
    assert previous_quarter_period("Q1FY26") == "Q4FY25"


def test_same_quarter_last_year_period():
    assert same_quarter_last_year_period("Q2FY26") == "Q2FY25"


def test_invalid_period_format_raises():
    with pytest.raises(InvalidPeriodFormat):
        previous_quarter_period("garbage")


def _metric(period, basis=FinancialBasis.STANDALONE, revenue=None, ebitda=None, pbt=None, pat=None, currency="INR", unit="crore"):
    return FinancialMetric(
        id=f"id-{period}-{basis.value}",
        company_ticker="RELIANCE",
        period=period,
        basis=basis,
        revenue=revenue,
        ebitda=ebitda,
        pbt=pbt,
        pat=pat,
        currency=currency,
        unit=unit,
        created_at=datetime.now(timezone.utc),
    )


def test_qoq_and_yoy_percentage_change_computed_correctly():
    current = _metric("Q2FY26", revenue=1100, ebitda=200, pbt=150, pat=100)
    prev_q = _metric("Q1FY26", revenue=1000, ebitda=180, pbt=140, pat=90)
    yoy = _metric("Q2FY25", revenue=1000, ebitda=160, pbt=120, pat=80)

    comparison = compare_period(current, [current, prev_q, yoy])

    assert comparison.revenue_qoq_pct == pytest.approx(10.0)
    assert comparison.revenue_yoy_pct == pytest.approx(10.0)
    assert comparison.pat_qoq_pct == pytest.approx((100 - 90) / 90 * 100)
    assert comparison.pat_yoy_pct == pytest.approx((100 - 80) / 80 * 100)


def test_missing_comparison_period_yields_null_not_a_guess():
    current = _metric("Q2FY26", revenue=1100)
    comparison = compare_period(current, [current])  # no prior periods available
    assert comparison.revenue_qoq_pct is None
    assert comparison.revenue_yoy_pct is None
    assert comparison.previous_quarter is None


def test_missing_metric_value_yields_null():
    current = _metric("Q2FY26", revenue=1100, ebitda=None)
    prev_q = _metric("Q1FY26", revenue=1000, ebitda=180)
    comparison = compare_period(current, [current, prev_q])
    assert comparison.revenue_qoq_pct is not None
    assert comparison.ebitda_qoq_pct is None  # current.ebitda is None


def test_basis_mismatch_is_never_compared_and_is_flagged():
    current = _metric("Q2FY26", basis=FinancialBasis.CONSOLIDATED, revenue=1100)
    prev_q_standalone = _metric("Q1FY26", basis=FinancialBasis.STANDALONE, revenue=1000)

    comparison = compare_period(current, [current, prev_q_standalone])

    # previous_quarter lookup is keyed by (period, basis) — a standalone row never
    # satisfies a consolidated current period's comparison.
    assert comparison.previous_quarter is None
    assert comparison.revenue_qoq_pct is None


def test_unit_mismatch_is_flagged_and_not_compared():
    current = _metric("Q2FY26", revenue=1100, unit="crore")
    prev_q_diff_unit = _metric("Q1FY26", revenue=100000, unit="lakh")
    # Force them into the same lookup bucket by giving them the same basis (default) —
    # the mismatch must be caught on unit, not basis.
    comparison = compare_period(current, [current, prev_q_diff_unit])
    assert comparison.revenue_qoq_pct is None
    assert any("unit mismatch" in w for w in comparison.basis_mismatch_warnings)
