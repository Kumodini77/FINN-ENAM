"""Unit tests for app.services.event_grouping - plain Python, no mocking needed
(operates on already-fetched Announcement objects, not a repository)."""

from datetime import datetime, timezone

from app.models.announcement import Announcement, AnnouncementCategory
from app.services.event_grouping import group_announcements_into_events

COMPANY = "HDFCBANK"


def _ann(**overrides) -> Announcement:
    base = dict(
        id="a1", company_ticker=COMPANY, filed_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        title="Unaudited Financial Results for the quarter ended June 30, 2026",
        category=AnnouncementCategory.RESULTS, original_source_url="https://x.invalid/a1.pdf",
        ingested_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return Announcement.model_validate(base)


def test_results_and_concall_for_same_quarter_are_grouped_into_one_event():
    results = _ann(id="a1", title="Unaudited Financial Results for the quarter ended June 30, 2026", category=AnnouncementCategory.RESULTS)
    concall = _ann(
        id="a2", title="Transcript of earnings call for Q1 FY27", category=AnnouncementCategory.EARNINGS_CALL,
        filed_at=datetime(2026, 7, 20, tzinfo=timezone.utc), original_source_url="https://x.invalid/a2.pdf",
    )
    events = group_announcements_into_events([results, concall])
    assert len(events) == 1
    event = events[0]
    assert event.reporting_period == "Q1FY27"
    assert {d.announcement_id for d in event.source_documents} == {"a1", "a2"}
    assert event.event_category == AnnouncementCategory.RESULTS  # RESULTS wins over EARNINGS_CALL
    assert event.event_date == results.filed_at  # earliest member


def test_different_quarters_remain_separate_events():
    q1 = _ann(id="a1", title="Results for the quarter ended June 30, 2026")
    q2 = _ann(id="a2", title="Results for the quarter ended September 30, 2026", filed_at=datetime(2026, 10, 18, tzinfo=timezone.utc))
    events = group_announcements_into_events([q1, q2])
    assert len(events) == 2
    assert {e.reporting_period for e in events} == {"Q1FY27", "Q2FY27"}


def test_unrelated_announcement_categories_are_never_grouped_even_same_date():
    results = _ann(id="a1", category=AnnouncementCategory.RESULTS)
    dividend = _ann(id="a2", title="Dividend declared", category=AnnouncementCategory.DIVIDEND)
    events = group_announcements_into_events([results, dividend])
    assert len(events) == 2  # same company, same date - still NOT merged (different category family)


def test_unresolvable_period_never_merges_with_anything():
    vague = _ann(id="a1", title="Financial results announced", category=AnnouncementCategory.RESULTS)
    clear = _ann(id="a2", title="Results for the quarter ended June 30, 2026", category=AnnouncementCategory.RESULTS)
    events = group_announcements_into_events([vague, clear])
    assert len(events) == 2
    assert any(e.reporting_period is None for e in events)


def test_no_announcement_is_ever_dropped():
    anns = [_ann(id=f"a{i}", title=f"Dividend {i}", category=AnnouncementCategory.DIVIDEND) for i in range(5)]
    events = group_announcements_into_events(anns)
    assert sum(len(e.announcements) for e in events) == 5
    all_ids = {d.announcement_id for e in events for d in e.source_documents}
    assert all_ids == {a.id for a in anns}


def test_different_companies_never_grouped_even_with_same_period():
    hdfc = _ann(id="a1", company_ticker="HDFCBANK", title="Results for the quarter ended June 30, 2026")
    reliance = _ann(id="a2", company_ticker="RELIANCE", title="Results for the quarter ended June 30, 2026")
    events = group_announcements_into_events([hdfc, reliance])
    assert len(events) == 2
    assert {e.company_ticker for e in events} == {"HDFCBANK", "RELIANCE"}
