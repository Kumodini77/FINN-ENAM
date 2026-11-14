from datetime import date, datetime

from pydantic import BaseModel

from app.models.announcement import AnnouncementCategory


class AlertsConfigIn(BaseModel):
    volume_spike_multiple: float
    price_move_pct: float
    digest_window_hours: int
    alert_categories: list[AnnouncementCategory]


class AlertsConfigOut(AlertsConfigIn):
    user_id: str
    updated_at: datetime


class AlertTransparencyOut(BaseModel):
    """Keeps 'how important is this' separate from 'how reliable is this evidence'
    - never collapsed into one opaque score. Computed at read time, not stored."""

    is_primary_disclosure: bool
    """True only for an alert sourced from the company's own filing
    (trigger_type == material_announcement); a volume/price alert is derived from
    market data, not a company disclosure."""
    has_numerical_evidence: bool
    evidence_note: str
    priority_rationale: str | None


class AlertOut(BaseModel):
    id: str
    company_ticker: str
    trigger_type: str
    source_announcement_id: str | None
    trade_date: date | None
    payload: dict
    triggered_at: datetime
    seen_at: datetime | None
    transparency: AlertTransparencyOut
