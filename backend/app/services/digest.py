"""Daily digest assembly (requirements.md Module 7).

Builds a filtered, prioritized view over announcements for a time window. Sorting and
collapsing logic lives here so it's independently testable from the API layer; the
API route (app/api/digest.py) is a thin wrapper around this.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models.announcement import Announcement, AnnouncementCategory, PriorityLevel
from app.repositories.announcements import AnnouncementRepository
from app.services.priority import is_routine


@dataclass
class DigestItem:
    announcement: Announcement
    collapsed: bool


@dataclass
class DigestResult:
    window_start: datetime
    window_end: datetime
    items: list[DigestItem]
    total_count: int
    collapsed_count: int


def resolve_window(
    window_hours: int | None,
    start: datetime | None,
    end: datetime | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Explicit start/end wins; otherwise a rolling window of `window_hours` ending now.
    Defaults to 24h per requirements.md, with a documented 7-day (168h) shortcut."""
    now = now or datetime.now(timezone.utc)
    if start is not None and end is not None:
        return start, end
    hours = window_hours if window_hours is not None else 24
    return now - timedelta(hours=hours), now


def build_digest(
    tickers: set[str],
    window_start: datetime,
    window_end: datetime,
    categories: set[AnnouncementCategory] | None = None,
    repo: AnnouncementRepository | None = None,
) -> DigestResult:
    repo = repo or AnnouncementRepository()
    candidates = repo.list_for_tickers(tickers)

    def in_window(a: Announcement) -> bool:
        filed_at = a.filed_at if a.filed_at.tzinfo else a.filed_at.replace(tzinfo=timezone.utc)
        return window_start <= filed_at <= window_end

    filtered = [a for a in candidates if in_window(a)]
    if categories:
        filtered = [a for a in filtered if a.category in categories]

    # Priority sorting: high -> medium -> low, then most recent first within each tier.
    priority_order = {PriorityLevel.HIGH: 0, PriorityLevel.MEDIUM: 1, PriorityLevel.LOW: 2}
    filtered.sort(key=lambda a: (priority_order[a.priority], -a.filed_at.timestamp()))

    items = [DigestItem(announcement=a, collapsed=is_routine(a.category, a.priority)) for a in filtered]
    collapsed_count = sum(1 for i in items if i.collapsed)

    return DigestResult(
        window_start=window_start,
        window_end=window_end,
        items=items,
        total_count=len(items),
        collapsed_count=collapsed_count,
    )
