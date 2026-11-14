from datetime import datetime

from pydantic import BaseModel, Field

from app.models.announcement import AnnouncementCategory, SourceType, VerificationStatus


class AnnouncementImportRequest(BaseModel):
    ticker: str = Field(description="Must match a company in the registry (GET /api/companies).")
    title: str
    filed_at: datetime
    original_source_url: str = Field(description="The exchange/screener page where this filing is listed.")
    document_url: str | None = Field(default=None, description="Direct link to the filing PDF, if available.")
    extracted_text: str | None = Field(default=None, description="Optional excerpt, used to improve classification.")
    category: AnnouncementCategory | None = Field(
        default=None, description="Supply directly to skip auto-classification (method recorded as 'manual')."
    )
    source: SourceType = SourceType.MANUAL_SEED
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    seeded_by: str | None = Field(default=None, description="Who/what curated this record, for traceability.")


class AnnouncementImportResult(BaseModel):
    announcement_id: str
    created: bool
    category: AnnouncementCategory
    priority: str
    priority_score: float
    message: str


class AnnouncementImportBatchResult(BaseModel):
    results: list[AnnouncementImportResult]
    created_count: int
    duplicate_count: int
    error_count: int
    errors: list[str]
