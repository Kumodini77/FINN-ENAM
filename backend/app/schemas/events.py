from datetime import datetime

from pydantic import BaseModel

from app.models.announcement import AnnouncementCategory, PriorityLevel


class SourceDocumentOut(BaseModel):
    announcement_id: str
    title: str
    category: AnnouncementCategory
    filed_at: datetime
    original_source_url: str
    document_url: str | None


class FinancialChangeOut(BaseModel):
    metric: str
    label: str
    latest_value: float | None  # reported fact; None -> "Not available", never 0
    comparison_value: float | None  # reported fact (previous quarter)
    qoq_pct: float | None  # calculated
    yoy_pct: float | None  # calculated
    direction: str  # "positive" | "negative" | "not_available" | "not_comparable"
    unit: str
    currency: str
    basis: str
    comparison_period: str | None
    not_comparable_reason: str | None


class ResearchLinkOut(BaseModel):
    ticker: str
    suggested_question: str


class EventOut(BaseModel):
    company_ticker: str
    event_category: AnnouncementCategory
    event_date: datetime
    reporting_period: str | None
    priority: PriorityLevel
    """The highest priority among the event's grouped source announcements."""
    priority_rationale: str
    why_it_matters: str
    financial_changes: list[FinancialChangeOut]
    basis_mismatch_warnings: list[str]
    missing_information: list[str]
    source_documents: list[SourceDocumentOut]
    research_link: ResearchLinkOut


class EventsResponse(BaseModel):
    window_start: datetime
    window_end: datetime
    events: list[EventOut]
    total_announcements: int
    """Count of individual source announcements folded into `events` - always >=
    len(events), confirming nothing was silently dropped during grouping."""
