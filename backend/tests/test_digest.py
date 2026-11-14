from datetime import datetime, timedelta, timezone

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
