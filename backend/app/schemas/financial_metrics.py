from datetime import date

from pydantic import BaseModel, Field

from app.models.announcement import ExtractionSource, FinancialBasis


class FinancialMetricImportRequest(BaseModel):
    ticker: str
    period: str = Field(description="Format: Q<1-4>FY<yy>, e.g. Q2FY26")
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
    extraction_confidence: float | None = Field(
        default=None, description="1.0 for a human-transcribed value read directly from the filing; lower if estimated."
    )
    extraction_source: ExtractionSource = ExtractionSource.MANUAL_SEED
    announcement_id: str | None = None


class MetricValue(BaseModel):
    value: float | None
    qoq_pct: float | None
    yoy_pct: float | None


class ResultsComparisonResponse(BaseModel):
    ticker: str
    period: str
    basis: FinancialBasis
    currency: str
    unit: str
    revenue: MetricValue
    ebitda: MetricValue
    pbt: MetricValue
    pat: MetricValue
    source_document_url: str | None
    source_page_number: int | None
    extraction_confidence: float | None
    warnings: list[str]
