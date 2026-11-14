"""QoQ/YoY computation over financial_metrics rows (requirements.md Module 5).

All arithmetic here is plain, deterministic Python — no LLM involvement, and no value
is ever invented: a missing metric stays null, and a missing comparison period
produces a null % change rather than a guess. The only non-trivial logic is period
arithmetic (figuring out "the previous quarter" and "the same quarter last year" from
a string like "Q2FY26") and enforcing that QoQ/YoY never compares across different
`basis` (standalone vs. consolidated) or different `unit`/`currency`.
"""

import re
from dataclasses import dataclass

from app.models.announcement import FinancialMetric

_PERIOD_RE = re.compile(r"^Q([1-4])FY(\d{2})$")


class InvalidPeriodFormat(ValueError):
    pass


def _parse_period(period: str) -> tuple[int, int]:
    match = _PERIOD_RE.match(period.strip())
    if not match:
        raise InvalidPeriodFormat(f"Expected format 'Q<1-4>FY<yy>', got: {period!r}")
    quarter = int(match.group(1))
    fy = int(match.group(2))
    return quarter, fy


def _format_period(quarter: int, fy: int) -> str:
    return f"Q{quarter}FY{fy:02d}"


def previous_quarter_period(period: str) -> str:
    quarter, fy = _parse_period(period)
    if quarter == 1:
        return _format_period(4, fy - 1)
    return _format_period(quarter - 1, fy)


def same_quarter_last_year_period(period: str) -> str:
    quarter, fy = _parse_period(period)
    return _format_period(quarter, fy - 1)


@dataclass
class PeriodComparison:
    current: FinancialMetric
    previous_quarter: FinancialMetric | None
    same_quarter_last_year: FinancialMetric | None
    revenue_qoq_pct: float | None
    revenue_yoy_pct: float | None
    ebitda_qoq_pct: float | None
    ebitda_yoy_pct: float | None
    pbt_qoq_pct: float | None
    pbt_yoy_pct: float | None
    pat_qoq_pct: float | None
    pat_yoy_pct: float | None
    basis_mismatch_warnings: list[str]


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 4)


def _comparable(a: FinancialMetric, b: FinancialMetric) -> tuple[bool, str | None]:
    if a.basis != b.basis:
        return False, f"basis mismatch: {a.period} is {a.basis.value}, {b.period} is {b.basis.value}"
    if a.currency != b.currency:
        return False, f"currency mismatch: {a.currency} vs {b.currency}"
    if a.unit != b.unit:
        return False, f"unit mismatch: {a.unit} vs {b.unit}"
    return True, None


def compare_period(current: FinancialMetric, all_metrics: list[FinancialMetric]) -> PeriodComparison:
    by_period_and_basis = {(m.period, m.basis): m for m in all_metrics}

    prev_q_period = previous_quarter_period(current.period)
    yoy_period = same_quarter_last_year_period(current.period)

    previous_quarter = by_period_and_basis.get((prev_q_period, current.basis))
    same_quarter_last_year = by_period_and_basis.get((yoy_period, current.basis))

    warnings: list[str] = []

    def safe_pct(metric_name: str, other: FinancialMetric | None) -> float | None:
        if other is None:
            return None
        ok, reason = _comparable(current, other)
        if not ok:
            warnings.append(reason)
            return None
        return _pct_change(getattr(current, metric_name), getattr(other, metric_name))

    return PeriodComparison(
        current=current,
        previous_quarter=previous_quarter,
        same_quarter_last_year=same_quarter_last_year,
        revenue_qoq_pct=safe_pct("revenue", previous_quarter),
        revenue_yoy_pct=safe_pct("revenue", same_quarter_last_year),
        ebitda_qoq_pct=safe_pct("ebitda", previous_quarter),
        ebitda_yoy_pct=safe_pct("ebitda", same_quarter_last_year),
        pbt_qoq_pct=safe_pct("pbt", previous_quarter),
        pbt_yoy_pct=safe_pct("pbt", same_quarter_last_year),
        pat_qoq_pct=safe_pct("pat", previous_quarter),
        pat_yoy_pct=safe_pct("pat", same_quarter_last_year),
        basis_mismatch_warnings=list(dict.fromkeys(warnings)),  # dedupe, preserve order
    )
