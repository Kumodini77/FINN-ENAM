from datetime import datetime

from pydantic import BaseModel

from app.models.announcement import AnnouncementCategory, PriorityLevel


class DigestItemOut(BaseModel):
    id: str
    company_ticker: str
    title: str
    category: AnnouncementCategory
    priority: PriorityLevel
    priority_score: float
    one_line_summary: str | None
    why_it_matters: str | None
    filed_at: datetime
    """When the filing was published, per the exchange."""
    ingested_at: datetime
    """When FINN imported it — distinct from filed_at, per requirements.md Module 7."""
    original_source_url: str
    document_url: str | None
    verification_status: str
    source: str
    collapsed: bool


class DigestResponse(BaseModel):
    window_start: datetime
    window_end: datetime
    total_count: int
    collapsed_count: int
    items: list[DigestItemOut]
