"""Unit tests for app.services.event_intelligence - uses the JSON-fallback
FinancialMetricRepository (real logic, isolated storage), reusing
app.services.financial_extraction's already-tested compare_period."""

from datetime import date, datetime, timezone

import pytest

from app.models.announcement import Announcement, AnnouncementCategory, FinancialMetric
from app.repositories.financial_metrics import FinancialMetricRepository
from app.repositories.json_store import JsonListStore
from app.services.event_grouping import Event
from app.services.event_intelligence import build_event_intelligence

COMPANY = "HDFCBANK"


@pytest.fixture
def metric_repo(tmp_path):
    return FinancialMetricRepository(store=JsonListStore(str(tmp_path), "financial_metrics.json"))


def _metric(period, revenue, pat, created_at=None) -> FinancialMetric:
    return FinancialMetric(
        id=f"m-{period}", company_ticker=COMPANY, period=period, revenue=revenue, pat=pat,
        created_at=created_at or datetime.now(timezone.utc),
    )


def _results_announcement() -> Announcement:
    return Announcement.model_validate(
        dict(
            id="a1", company_ticker=COMPANY, filed_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
            title="Results for the quarter ended June 30, 2026", category=AnnouncementCategory.RESULTS,
            original_source_url="https://x.invalid/a1.pdf", ingested_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        )
    )


def _event(reporting_period="Q1FY27") -> Event:
    return Event(
        company_ticker=COMPANY, event_category=AnnouncementCategory.RESULTS,
        event_date=datetime(2026, 7, 18, tzinfo=timezone.utc), reporting_period=reporting_period,
        announcements=[_results_announcement()],
    )


def test_no_financial_metrics_imported_yields_no_fabricated_changes(metric_repo):
    intelligence = build_event_intelligence(_event(), metric_repo)
    assert intelligence.financial_changes == []
    assert intelligence.missing_information  # honestly flagged, not silently empty


def test_metric_with_no_prior_period_shows_not_available_not_zero(metric_repo):
    metric_repo.upsert(_metric("Q1FY27", revenue=531.7, pat=181.6))
    intelligence = build_event_intelligence(_event(), metric_repo)
    revenue_change = next(c for c in intelligence.financial_changes if c.metric == "revenue")
    assert revenue_change.latest_value == 531.7
    assert revenue_change.qoq_pct is None
    assert revenue_change.yoy_pct is None
    assert revenue_change.direction == "not_available"
    assert "QoQ comparison unavailable" in " ".join(intelligence.missing_information)


def test_qoq_and_yoy_comparison_computed_correctly(metric_repo):
    metric_repo.upsert(_metric("Q4FY26", revenue=462.8, pat=192.2))
    metric_repo.upsert(_metric("Q1FY26", revenue=460.0, pat=170.0))
    metric_repo.upsert(_metric("Q1FY27", revenue=531.7, pat=181.6))
    intelligence = build_event_intelligence(_event(), metric_repo)
    revenue_change = next(c for c in intelligence.financial_changes if c.metric == "revenue")
    assert revenue_change.qoq_pct == pytest.approx((531.7 - 462.8) / 462.8 * 100, abs=0.01)
    assert revenue_change.yoy_pct == pytest.approx((531.7 - 460.0) / 460.0 * 100, abs=0.01)
    assert revenue_change.direction == "positive"


def test_missing_metric_field_is_not_available_never_zero(metric_repo):
    metric_repo.upsert(_metric("Q1FY27", revenue=531.7, pat=None))
    intelligence = build_event_intelligence(_event(), metric_repo)
    pat_change = next(c for c in intelligence.financial_changes if c.metric == "pat")
    assert pat_change.latest_value is None
    assert pat_change.direction == "not_available"


def test_why_it_matters_mentions_actual_computed_numbers_not_a_generic_template(metric_repo):
    metric_repo.upsert(_metric("Q4FY26", revenue=462.8, pat=192.2))
    metric_repo.upsert(_metric("Q1FY27", revenue=531.7, pat=181.6))
    intelligence = build_event_intelligence(_event(), metric_repo)
    assert "%" in intelligence.why_it_matters
    assert "Revenue" in intelligence.why_it_matters


def test_no_reporting_period_resolved_returns_base_explanation_only(metric_repo):
    intelligence = build_event_intelligence(_event(reporting_period=None), metric_repo)
    assert intelligence.financial_changes == []
    assert intelligence.missing_information == []
    assert intelligence.why_it_matters  # still the deterministic category-based explanation
