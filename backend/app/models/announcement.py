"""In-process data models for announcements, financial metrics, and alerts.

These mirror backend/migrations/001_init.sql + 003_phase2_additions.sql field-for-field.
They are the shape used by both storage backends (Supabase and the JSON-file fallback —
see app/repositories/), so switching backends later doesn't change anything above this layer.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class AnnouncementCategory(str, Enum):
    RESULTS = "results"
    MA = "M&A"
    FUND_RAISE = "fund_raise"
    MANAGEMENT_CHANGE = "management_change"
    LITIGATION = "litigation"
    INSIDER_TRADING = "insider_trading"
    EARNINGS_CALL = "earnings_call"
    INVESTOR_MEETINGS = "investor_meetings"
    CREDIT_RATING = "credit_rating"
    DIVIDEND = "dividend"
    BONUS_SPLIT = "bonus_split"
    CAPEX = "capex"
    PRESS_RELEASE = "press_release"
    POSTAL_BALLOT = "postal_ballot"
    AGM_EGM = "agm_egm"
    PLEDGING = "pledging"
    UNCLASSIFIED = "unclassified"


class SourceType(str, Enum):
    LIVE = "live"
    CACHED = "cached"
    MANUAL_SEED = "manual_seed"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    """A human confirmed this record against the actual primary-source filing."""
    UNVERIFIED = "unverified"
    """Imported but not yet cross-checked against the original filing."""


class ClassificationMethod(str, Enum):
    RULE_BASED = "rule_based"
    LLM = "llm"
    FALLBACK_UNCLASSIFIED = "fallback_unclassified"
    MANUAL = "manual"
    """Category was supplied directly at import time, not inferred."""


class PriorityLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Announcement(BaseModel):
    id: str
    company_ticker: str
    filed_at: datetime
    title: str
    category: AnnouncementCategory = AnnouncementCategory.UNCLASSIFIED
    category_confidence: float | None = None
    classification_method: ClassificationMethod = ClassificationMethod.FALLBACK_UNCLASSIFIED
    classification_evidence: list[str] = Field(default_factory=list)
    one_line_summary: str | None = None
    why_it_matters: str | None = None
    """AI-generated interpretation — kept in a separate field from `title` (the filing's
    own fact) so the UI can visibly distinguish what the filing says from what FINN infers."""
    priority: PriorityLevel = PriorityLevel.LOW
    priority_score: float = 0.0
    is_material: bool = False
    original_source_url: str
    document_url: str | None = None
    extracted_text: str | None = None
    source: SourceType = SourceType.MANUAL_SEED
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    seeded_by: str | None = None
    ingested_at: datetime


class FinancialBasis(str, Enum):
    STANDALONE = "standalone"
    CONSOLIDATED = "consolidated"


class ExtractionSource(str, Enum):
    FILING = "filing"
    SCREENER = "screener"
    MANUAL_SEED = "manual_seed"


class FinancialMetric(BaseModel):
    id: str
    company_ticker: str
    announcement_id: str | None = None
    period: str  # e.g. "Q2FY26"
    period_end_date: date | None = None
    basis: FinancialBasis = FinancialBasis.STANDALONE
    revenue: float | None = None
    ebitda: float | None = None
    pbt: float | None = None
    pat: float | None = None
    currency: str = "INR"
    unit: str = "crore"
    source_document_url: str | None = None
    source_page_number: int | None = None
    extraction_confidence: float | None = None
    extraction_source: ExtractionSource = ExtractionSource.MANUAL_SEED
    created_at: datetime


class AlertTriggerType(str, Enum):
    VOLUME_SPIKE = "volume_spike"
    PRICE_MOVE = "price_move"
    MATERIAL_ANNOUNCEMENT = "material_announcement"


class Alert(BaseModel):
    id: str
    company_ticker: str
    trigger_type: AlertTriggerType
    source_announcement_id: str | None = None
    trade_date: date | None = None
    payload: dict = Field(default_factory=dict)
    triggered_at: datetime
    seen_at: datetime | None = None


class AlertsConfig(BaseModel):
    user_id: str = "default"
    volume_spike_multiple: float = 2.0
    price_move_pct: float = 5.0
    digest_window_hours: int = 24
    alert_categories: list[AnnouncementCategory] = Field(
        default_factory=lambda: [
            AnnouncementCategory.RESULTS,
            AnnouncementCategory.MA,
            AnnouncementCategory.MANAGEMENT_CHANGE,
            AnnouncementCategory.LITIGATION,
            AnnouncementCategory.CREDIT_RATING,
        ]
    )
    updated_at: datetime
