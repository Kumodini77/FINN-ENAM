from datetime import datetime, timedelta, timezone

from app.models.announcement import AnnouncementCategory, PriorityLevel
from app.services.priority import compute_priority, is_routine, recency_decay


def test_fresh_results_is_high_priority():
    now = datetime.now(timezone.utc)
    result = compute_priority(AnnouncementCategory.RESULTS, filed_at=now, now=now)
    assert result.level == PriorityLevel.HIGH
    assert result.score == 1.0


def test_fresh_unclassified_is_low_priority():
    now = datetime.now(timezone.utc)
    result = compute_priority(AnnouncementCategory.UNCLASSIFIED, filed_at=now, now=now)
    assert result.level == PriorityLevel.LOW


def test_week_old_results_still_outranks_fresh_unclassified():
    now = datetime.now(timezone.utc)
    old_results = compute_priority(AnnouncementCategory.RESULTS, filed_at=now - timedelta(days=7), now=now)
    fresh_unclassified = compute_priority(AnnouncementCategory.UNCLASSIFIED, filed_at=now, now=now)
    assert old_results.score > fresh_unclassified.score


def test_recency_decay_is_monotonically_non_increasing_with_age():
    now = datetime.now(timezone.utc)
    ages_hours = [0, 12, 24, 48, 96, 168, 240]
    decays = [recency_decay(now - timedelta(hours=h), now=now) for h in ages_hours]
    assert decays == sorted(decays, reverse=True)


def test_recency_decay_floors_at_0_4_beyond_a_week():
    now = datetime.now(timezone.utc)
    assert recency_decay(now - timedelta(days=30), now=now) == 0.4


def test_is_routine_matches_low_priority_only():
    now = datetime.now(timezone.utc)
    low = compute_priority(AnnouncementCategory.UNCLASSIFIED, filed_at=now, now=now)
    high = compute_priority(AnnouncementCategory.RESULTS, filed_at=now, now=now)
    assert is_routine(AnnouncementCategory.UNCLASSIFIED, low.level) is True
    assert is_routine(AnnouncementCategory.RESULTS, high.level) is False


def test_rationale_is_human_readable_and_cites_inputs():
    now = datetime.now(timezone.utc)
    result = compute_priority(AnnouncementCategory.DIVIDEND, filed_at=now, now=now)
    assert "dividend" in result.rationale
    assert "weight=" in result.rationale
    assert "recency_decay=" in result.rationale
