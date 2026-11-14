"""Derived event grouping over existing announcements - no new table, no migration.

Groups related disclosures (e.g. a results announcement, an investor presentation,
and an earnings-call transcript filed for the same company and the same reporting
quarter) into one Event, while a company's unrelated announcements (dividend,
litigation, management change, ...) each remain their own singleton event.

Grouping requires BOTH:
  1. The same company_ticker.
  2. The same category "family" (results-like: RESULTS + EARNINGS_CALL - a results
     announcement and its concall transcript are the same reporting event; nothing
     else is ever merged with them).
  3. The SAME resolved reporting period, parsed deterministically from title +
     extracted_text via app.services.period_resolution (reused from Pull, not
     duplicated). If a period can't be confidently resolved for an announcement,
     it is never merged with anything - it becomes its own singleton event. Same
     date alone, or same category alone, is never sufficient to merge.

Nothing is discarded: every announcement that goes into an Event is listed in
`source_announcement_ids`/`source_documents`, preserving its own id and URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models.announcement import Announcement, AnnouncementCategory
from app.services.period_resolution import resolve_period_mention

_RESULTS_FAMILY = {AnnouncementCategory.RESULTS, AnnouncementCategory.EARNINGS_CALL}


@dataclass
class SourceDocument:
    announcement_id: str
    title: str
    category: AnnouncementCategory
    filed_at: datetime
    original_source_url: str
    document_url: str | None


@dataclass
class Event:
    company_ticker: str
    event_category: AnnouncementCategory
    """The grouped category - RESULTS if any member is RESULTS (the more
    specific/important of the two results-family categories), else the single
    member's own category."""
    event_date: datetime
    """The EARLIEST filed_at among the group's members - when the event first
    became known, not when the last supporting document arrived."""
    reporting_period: str | None
    announcements: list[Announcement]
    source_documents: list[SourceDocument] = field(default_factory=list)

    def __post_init__(self):
        if not self.source_documents:
            self.source_documents = [
                SourceDocument(
                    announcement_id=a.id, title=a.title, category=a.category, filed_at=a.filed_at,
                    original_source_url=a.original_source_url, document_url=a.document_url,
                )
                for a in self.announcements
            ]


def _group_key(a: Announcement) -> tuple[str, str, str] | None:
    """None means "do not group this with anything" (ambiguous period)."""
    if a.category not in _RESULTS_FAMILY:
        return None
    period = resolve_period_mention(f"{a.title} {a.extracted_text or ''}")
    if period is None:
        return None
    return (a.company_ticker, "results_family", period)


def group_announcements_into_events(announcements: list[Announcement]) -> list[Event]:
    groups: dict[tuple, list[Announcement]] = {}
    singletons: list[Announcement] = []

    for a in announcements:
        key = _group_key(a)
        if key is None:
            singletons.append(a)
        else:
            groups.setdefault(key, []).append(a)

    events: list[Event] = []
    for (ticker, _family, period), members in groups.items():
        members_sorted = sorted(members, key=lambda a: a.filed_at)
        category = (
            AnnouncementCategory.RESULTS
            if any(m.category == AnnouncementCategory.RESULTS for m in members)
            else members_sorted[0].category
        )
        events.append(
            Event(
                company_ticker=ticker, event_category=category, event_date=members_sorted[0].filed_at,
                reporting_period=period, announcements=members_sorted,
            )
        )

    for a in singletons:
        events.append(
            Event(
                company_ticker=a.company_ticker, event_category=a.category, event_date=a.filed_at,
                reporting_period=None, announcements=[a],
            )
        )

    return events
