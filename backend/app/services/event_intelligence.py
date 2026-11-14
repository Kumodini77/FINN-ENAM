"""'What changed?' intelligence for a grouped Event (app.services.event_grouping) -
built entirely on top of the EXISTING, already-tested financial comparison logic
(app.services.financial_extraction.compare_period) and the existing
FinancialMetricRepository. No new comparison math, no duplicate QoQ/YoY logic.

Only produces a financial comparison when financial_metrics actually exist for
this ticker+period - if nothing was imported (the common case right now, since
financial_metrics import is a separate manual step from announcement import),
this returns no financial changes rather than fabricating any.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.announcement import AnnouncementCategory, FinancialMetric
from app.repositories.financial_metrics import FinancialMetricRepository
from app.services.event_grouping import Event
from app.services.financial_extraction import PeriodComparison, compare_period
from app.services.why_it_matters import generate_why_it_matters

_METRIC_FIELDS = ["revenue", "ebitda", "pbt", "pat"]
_METRIC_LABELS = {"revenue": "Revenue", "ebitda": "EBITDA", "pbt": "Profit before tax", "pat": "Profit after tax"}


@dataclass
class FinancialChange:
    metric: str
    label: str
    latest_value: float | None  # "Reported financial fact"
    comparison_value: float | None  # "Reported financial fact" (the other period)
    qoq_pct: float | None  # "Calculated comparison"
    yoy_pct: float | None  # "Calculated comparison"
    direction: str  # "positive" | "negative" | "not_available" | "not_comparable"
    unit: str
    currency: str
    basis: str
    comparison_period: str | None
    not_comparable_reason: str | None = None


@dataclass
class EventIntelligence:
    financial_changes: list[FinancialChange]
    basis_mismatch_warnings: list[str]
    why_it_matters: str
    missing_information: list[str]


def _direction(pct: float | None) -> str:
    if pct is None:
        return "not_available"
    if pct > 0:
        return "positive"
    if pct < 0:
        return "negative"
    return "not_available"  # exactly 0% - no movement to characterize as a direction


def _build_financial_changes(metric: FinancialMetric, comparison: PeriodComparison) -> list[FinancialChange]:
    changes = []
    for field_name in _METRIC_FIELDS:
        latest_value = getattr(metric, field_name)
        qoq_pct = getattr(comparison, f"{field_name}_qoq_pct")
        yoy_pct = getattr(comparison, f"{field_name}_yoy_pct")
        prev_q = comparison.previous_quarter
        comparison_value = getattr(prev_q, field_name) if prev_q else None

        reason = None
        direction = _direction(yoy_pct if yoy_pct is not None else qoq_pct)
        if latest_value is None:
            direction = "not_available"
            reason = "Not available — this metric was not reported/imported for this period."
        elif comparison.basis_mismatch_warnings and comparison_value is None and prev_q is None:
            pass  # no prior period at all yet - direction stays not_available, no misleading % shown

        changes.append(
            FinancialChange(
                metric=field_name, label=_METRIC_LABELS[field_name], latest_value=latest_value,
                comparison_value=comparison_value, qoq_pct=qoq_pct, yoy_pct=yoy_pct, direction=direction,
                unit=metric.unit, currency=metric.currency, basis=metric.basis.value,
                comparison_period=prev_q.period if prev_q else None, not_comparable_reason=reason,
            )
        )
    return changes


def _what_changed_sentence(changes: list[FinancialChange]) -> str | None:
    """A specific, numbers-grounded sentence - never a generic template reused
    across every company. Returns None if nothing is actually comparable yet."""
    comparable = [c for c in changes if c.yoy_pct is not None or c.qoq_pct is not None]
    if not comparable:
        return None

    parts = []
    for c in comparable:
        pct = c.yoy_pct if c.yoy_pct is not None else c.qoq_pct
        basis_label = "YoY" if c.yoy_pct is not None else "QoQ"
        verb = "grew" if pct > 0 else "declined" if pct < 0 else "was flat"
        parts.append(f"{c.label} {verb} {abs(pct):.1f}% {basis_label}")

    sentence = "; ".join(parts) + "."

    revenue = next((c for c in comparable if c.metric == "revenue"), None)
    pat = next((c for c in comparable if c.metric == "pat"), None)
    if revenue and pat and revenue.direction == "positive" and pat.direction == "negative":
        sentence += " Revenue grew while profit after tax declined — investors may want to examine whether rising costs or one-off items reduced profitability."
    elif revenue and pat and revenue.direction == "negative" and pat.direction == "positive":
        sentence += " Profit after tax improved despite lower revenue — worth checking whether this came from cost control or a non-operating item."

    return sentence


def build_event_intelligence(event: Event, metric_repo: FinancialMetricRepository | None = None) -> EventIntelligence:
    metric_repo = metric_repo or FinancialMetricRepository()
    missing: list[str] = []
    changes: list[FinancialChange] = []
    basis_warnings: list[str] = []

    base_explanation = generate_why_it_matters(event.event_category, event.announcements[0].priority)

    if event.reporting_period is None:
        return EventIntelligence(
            financial_changes=[], basis_mismatch_warnings=[], why_it_matters=base_explanation, missing_information=[]
        )

    all_metrics = metric_repo.list_for_ticker(event.company_ticker)
    metric = next((m for m in all_metrics if m.period == event.reporting_period), None)

    if metric is None:
        missing.append(
            f"No financial_metrics have been imported for {event.company_ticker} {event.reporting_period} yet - "
            "'what changed' financial comparison is not available for this event."
        )
        return EventIntelligence(
            financial_changes=[], basis_mismatch_warnings=[], why_it_matters=base_explanation, missing_information=missing
        )

    comparison = compare_period(metric, all_metrics)
    changes = _build_financial_changes(metric, comparison)
    basis_warnings = comparison.basis_mismatch_warnings

    if comparison.previous_quarter is None:
        missing.append(f"No prior-quarter financial_metrics on record for {event.company_ticker} - QoQ comparison unavailable.")
    if comparison.same_quarter_last_year is None:
        missing.append(f"No same-quarter-last-year financial_metrics on record for {event.company_ticker} - YoY comparison unavailable.")

    what_changed = _what_changed_sentence(changes)
    explanation = base_explanation if what_changed is None else f"{base_explanation} {what_changed}"

    return EventIntelligence(
        financial_changes=changes, basis_mismatch_warnings=basis_warnings, why_it_matters=explanation,
        missing_information=missing,
    )
