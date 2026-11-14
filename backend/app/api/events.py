"""Event-centric Push view: groups related announcements (app.services.event_grouping),
enriches with 'what changed' financial comparison (app.services.event_intelligence,
built entirely on the existing compare_period logic) and a Research-ready link
(app.services.research_prompts). Reuses app.services.digest.resolve_window and
app.services.priority.compute_priority rather than re-implementing window/priority
logic - this is a second VIEW over the same announcement data GET /api/digest
already serves, not a second pipeline.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.core.companies import PORTFOLIO
from app.models.announcement import AnnouncementCategory
from app.repositories.announcements import AnnouncementRepository
from app.schemas.events import EventOut, EventsResponse, FinancialChangeOut, ResearchLinkOut, SourceDocumentOut
from app.services.digest import resolve_window
from app.services.event_grouping import group_announcements_into_events
from app.services.event_intelligence import build_event_intelligence
from app.services.priority import compute_priority
from app.services.research_prompts import suggested_question_for_event

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=EventsResponse)
def get_events(
    window_hours: int | None = Query(default=None, description="Default 24. Pass 168 for a 7-day window."),
    start: datetime | None = None,
    end: datetime | None = None,
    categories: list[AnnouncementCategory] | None = Query(default=None),
) -> EventsResponse:
    tickers = {c.ticker for c in PORTFOLIO}
    window_start, window_end = resolve_window(window_hours, start, end)
    category_set = set(categories) if categories else None

    repo = AnnouncementRepository()
    candidates = repo.list_for_tickers(tickers)

    def in_window(a) -> bool:
        filed_at = a.filed_at if a.filed_at.tzinfo else a.filed_at.replace(tzinfo=timezone.utc)
        return window_start <= filed_at <= window_end

    filtered = [a for a in candidates if in_window(a)]
    if category_set:
        filtered = [a for a in filtered if a.category in category_set]

    events = group_announcements_into_events(filtered)
    events.sort(key=lambda e: e.event_date, reverse=True)

    out = []
    for event in events:
        intelligence = build_event_intelligence(event)
        priority_result = compute_priority(event.event_category, event.event_date)
        out.append(
            EventOut(
                company_ticker=event.company_ticker, event_category=event.event_category, event_date=event.event_date,
                reporting_period=event.reporting_period, priority=priority_result.level,
                priority_rationale=priority_result.rationale, why_it_matters=intelligence.why_it_matters,
                financial_changes=[FinancialChangeOut(**vars(c)) for c in intelligence.financial_changes],
                basis_mismatch_warnings=intelligence.basis_mismatch_warnings,
                missing_information=intelligence.missing_information,
                source_documents=[SourceDocumentOut(**vars(d)) for d in event.source_documents],
                research_link=ResearchLinkOut(
                    ticker=event.company_ticker,
                    suggested_question=suggested_question_for_event(event.event_category, event.reporting_period),
                ),
            )
        )

    return EventsResponse(
        window_start=window_start, window_end=window_end, events=out, total_announcements=len(filtered)
    )
