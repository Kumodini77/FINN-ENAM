from datetime import datetime

from fastapi import APIRouter, Query

from app.core.companies import PORTFOLIO
from app.models.announcement import AnnouncementCategory
from app.schemas.digest import DigestItemOut, DigestResponse
from app.services.digest import build_digest, resolve_window

router = APIRouter(prefix="/digest", tags=["digest"])


@router.get("", response_model=DigestResponse)
def get_digest(
    window_hours: int | None = Query(default=None, description="Default 24. Pass 168 for a 7-day window."),
    start: datetime | None = None,
    end: datetime | None = None,
    categories: list[AnnouncementCategory] | None = Query(default=None),
) -> DigestResponse:
    tickers = {c.ticker for c in PORTFOLIO}
    window_start, window_end = resolve_window(window_hours, start, end)
    category_set = set(categories) if categories else None

    result = build_digest(tickers, window_start, window_end, categories=category_set)

    items = [
        DigestItemOut(
            id=item.announcement.id,
            company_ticker=item.announcement.company_ticker,
            title=item.announcement.title,
            category=item.announcement.category,
            priority=item.announcement.priority,
            priority_score=item.announcement.priority_score,
            one_line_summary=item.announcement.one_line_summary,
            why_it_matters=item.announcement.why_it_matters,
            filed_at=item.announcement.filed_at,
            ingested_at=item.announcement.ingested_at,
            original_source_url=item.announcement.original_source_url,
            document_url=item.announcement.document_url,
            verification_status=item.announcement.verification_status.value,
            source=item.announcement.source.value,
            collapsed=item.collapsed,
        )
        for item in result.items
    ]

    return DigestResponse(
        window_start=result.window_start,
        window_end=result.window_end,
        total_count=result.total_count,
        collapsed_count=result.collapsed_count,
        items=items,
    )
