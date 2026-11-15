from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import InvalidDateRangeError
from app.models.announcement import Announcement, AnnouncementCategory, PriorityLevel
from app.repositories.announcements import AnnouncementRepository, new_announcement_id
from app.repositories.json_store import JsonListStore
from app.services.digest import build_digest, resolve_window


def _announcement(ticker, title, filed_at, category, priority):
    return Announcement(
        id=new_announcement_id(),
        company_ticker=ticker,
        filed_at=filed_at,
        title=title,
        category=category,
        priority=priority,
        original_source_url=f"https://example.com/{new_announcement_id()}",
        ingested_at=datetime.now(timezone.utc),
    )


def _repo(tmp_path):
    return AnnouncementRepository(store=JsonListStore(str(tmp_path), "announcements.json"))


def test_resolve_window_defaults_to_24_hours():
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    start, end = resolve_window(window_hours=None, start=None, end=None, now=now)
    assert end == now
    assert start == now - timedelta(hours=24)


def test_resolve_window_supports_7_day_shortcut():
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    start, end = resolve_window(window_hours=168, start=None, end=None, now=now)
    assert start == now - timedelta(days=7)


def test_resolve_window_explicit_start_end_overrides_window_hours():
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    custom_start = now - timedelta(days=30)
    start, end = resolve_window(window_hours=24, start=custom_start, end=now, now=now)
    assert start == custom_start


# --- Custom date-range filter: boundaries, invalid ranges, timezone handling ---


def test_resolve_window_normalizes_naive_start_and_end_to_utc():
    """A bare date like "2026-07-01" from an HTML date input parses to a
    timezone-NAIVE datetime - this must not crash when later compared against
    timezone-AWARE announcement.filed_at values (the real bug this guards)."""
    naive_start = datetime(2026, 7, 1)
    naive_end = datetime(2026, 7, 2)
    start, end = resolve_window(window_hours=None, start=naive_start, end=naive_end)
    assert start.tzinfo is not None and end.tzinfo is not None
    assert start == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 2, tzinfo=timezone.utc)


def test_resolve_window_rejects_start_after_end():
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(InvalidDateRangeError):
        resolve_window(window_hours=None, start=now, end=now - timedelta(days=1))


def test_resolve_window_allows_start_equal_to_end():
    """A single-day range (same start/end instant) is a valid edge case, not an error."""
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    start, end = resolve_window(window_hours=None, start=now, end=now)
    assert start == end == now


def test_custom_range_includes_items_exactly_on_the_boundary(tmp_path):
    """An announcement filed exactly at window_start or window_end must be
    included - the comparison is inclusive on both ends."""
    repo = _repo(tmp_path)
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 2, 23, 59, 59, 999000, tzinfo=timezone.utc)
    repo.add(_announcement("RELIANCE", "Exactly at start", start, AnnouncementCategory.RESULTS, PriorityLevel.HIGH))
    repo.add(_announcement("RELIANCE", "Exactly at end", end, AnnouncementCategory.RESULTS, PriorityLevel.HIGH))
    repo.add(_announcement("RELIANCE", "Just before start", start - timedelta(seconds=1), AnnouncementCategory.RESULTS, PriorityLevel.HIGH))
    repo.add(_announcement("RELIANCE", "Just after end", end + timedelta(seconds=1), AnnouncementCategory.RESULTS, PriorityLevel.HIGH))

    result = build_digest({"RELIANCE"}, start, end, repo=repo)

    titles = {item.announcement.title for item in result.items}
    assert titles == {"Exactly at start", "Exactly at end"}


def test_custom_range_with_no_matching_announcements_is_a_clean_empty_result(tmp_path):
    repo = _repo(tmp_path)
    repo.add(_announcement("RELIANCE", "Unrelated date", datetime(2020, 1, 1, tzinfo=timezone.utc), AnnouncementCategory.RESULTS, PriorityLevel.HIGH))
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, tzinfo=timezone.utc)

    result = build_digest({"RELIANCE"}, start, end, repo=repo)

    assert result.total_count == 0
    assert result.items == []


def test_digest_excludes_items_outside_the_window(tmp_path):
    repo = _repo(tmp_path)
    now = datetime.now(timezone.utc)
    repo.add(_announcement("RELIANCE", "In window", now - timedelta(hours=2), AnnouncementCategory.RESULTS, PriorityLevel.HIGH))
    repo.add(_announcement("RELIANCE", "Out of window", now - timedelta(days=10), AnnouncementCategory.RESULTS, PriorityLevel.HIGH))

    start, end = resolve_window(24, None, None, now=now)
    result = build_digest({"RELIANCE"}, start, end, repo=repo)

    assert result.total_count == 1
    assert result.items[0].announcement.title == "In window"


def test_digest_excludes_other_companies_not_in_scope(tmp_path):
    repo = _repo(tmp_path)
    now = datetime.now(timezone.utc)
    repo.add(_announcement("RELIANCE", "Mine", now, AnnouncementCategory.RESULTS, PriorityLevel.HIGH))
    repo.add(_announcement("TCS", "Not mine", now, AnnouncementCategory.RESULTS, PriorityLevel.HIGH))

    start, end = resolve_window(24, None, None, now=now)
    result = build_digest({"RELIANCE"}, start, end, repo=repo)

    assert result.total_count == 1
    assert result.items[0].announcement.company_ticker == "RELIANCE"


def test_digest_sorts_by_priority_then_recency(tmp_path):
    repo = _repo(tmp_path)
    now = datetime.now(timezone.utc)
    low = _announcement("RELIANCE", "Low, newest", now, AnnouncementCategory.UNCLASSIFIED, PriorityLevel.LOW)
    high_older = _announcement("RELIANCE", "High, older", now - timedelta(hours=5), AnnouncementCategory.RESULTS, PriorityLevel.HIGH)
    high_newer = _announcement("RELIANCE", "High, newer", now - timedelta(hours=1), AnnouncementCategory.MA, PriorityLevel.HIGH)
    for a in [low, high_older, high_newer]:
        repo.add(a)

    start, end = resolve_window(24, None, None, now=now)
    result = build_digest({"RELIANCE"}, start, end, repo=repo)
    titles = [i.announcement.title for i in result.items]

    assert titles == ["High, newer", "High, older", "Low, newest"]


def test_digest_category_filter(tmp_path):
    repo = _repo(tmp_path)
    now = datetime.now(timezone.utc)
    repo.add(_announcement("RELIANCE", "Results filing", now, AnnouncementCategory.RESULTS, PriorityLevel.HIGH))
    repo.add(_announcement("RELIANCE", "Dividend filing", now, AnnouncementCategory.DIVIDEND, PriorityLevel.MEDIUM))

    start, end = resolve_window(24, None, None, now=now)
    result = build_digest({"RELIANCE"}, start, end, categories={AnnouncementCategory.RESULTS}, repo=repo)

    assert result.total_count == 1
    assert result.items[0].announcement.category == AnnouncementCategory.RESULTS


def test_low_priority_items_are_collapsed_by_default(tmp_path):
    repo = _repo(tmp_path)
    now = datetime.now(timezone.utc)
    repo.add(_announcement("RELIANCE", "Routine filing", now, AnnouncementCategory.UNCLASSIFIED, PriorityLevel.LOW))
    repo.add(_announcement("RELIANCE", "Results filing", now, AnnouncementCategory.RESULTS, PriorityLevel.HIGH))

    start, end = resolve_window(24, None, None, now=now)
    result = build_digest({"RELIANCE"}, start, end, repo=repo)

    assert result.collapsed_count == 1
    collapsed_items = [i for i in result.items if i.collapsed]
    assert collapsed_items[0].announcement.title == "Routine filing"
