import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.exceptions import CompanyLookupError, CompanyNotFoundError
from app.models.announcement import FinancialMetric
from app.repositories.financial_metrics import FinancialMetricRepository
from app.schemas.financial_metrics import (
    FinancialMetricImportRequest,
    MetricValue,
    ResultsComparisonResponse,
)
from app.services.company_resolution import resolve_company
from app.services.financial_extraction import compare_period

router = APIRouter(prefix="/financials", tags=["financials"])


@router.post("/import")
def import_financial_metric(payload: FinancialMetricImportRequest) -> dict:
    try:
        company = resolve_company(payload.ticker)
    except CompanyLookupError as e:
        raise CompanyNotFoundError(
            f"'{payload.ticker}' is not in the company registry and could not be "
            f"verified as a real, currently-listed equity ({e.message})."
        )

    repo = FinancialMetricRepository()
    metric = FinancialMetric(
        id=str(uuid.uuid4()),
        company_ticker=company.ticker,
        announcement_id=payload.announcement_id,
        period=payload.period,
        period_end_date=payload.period_end_date,
        basis=payload.basis,
        revenue=payload.revenue,
        ebitda=payload.ebitda,
        pbt=payload.pbt,
        pat=payload.pat,
        currency=payload.currency,
        unit=payload.unit,
        source_document_url=payload.source_document_url,
        source_page_number=payload.source_page_number,
        extraction_confidence=payload.extraction_confidence,
        extraction_source=payload.extraction_source,
        created_at=datetime.now(timezone.utc),
    )
    _, created = repo.upsert(metric)
    return {"created": created, "ticker": metric.company_ticker, "period": metric.period, "basis": metric.basis.value}


@router.get("/{ticker}/results-comparison", response_model=list[ResultsComparisonResponse])
def results_comparison(ticker: str, basis: str | None = None) -> list[ResultsComparisonResponse]:
    """Every period on record for this ticker, each with QoQ/YoY computed against the
    others — deterministic, per docs/requirements.md Module 5. An empty list means no
    financial_metrics have been imported for this ticker yet (not an error)."""
    repo = FinancialMetricRepository()
    all_metrics = repo.list_for_ticker(ticker.upper(), basis=basis)

    responses = []
    for metric in sorted(all_metrics, key=lambda m: m.period):
        comparison = compare_period(metric, all_metrics)
        responses.append(
            ResultsComparisonResponse(
                ticker=metric.company_ticker,
                period=metric.period,
                basis=metric.basis,
                currency=metric.currency,
                unit=metric.unit,
                revenue=MetricValue(value=metric.revenue, qoq_pct=comparison.revenue_qoq_pct, yoy_pct=comparison.revenue_yoy_pct),
                ebitda=MetricValue(value=metric.ebitda, qoq_pct=comparison.ebitda_qoq_pct, yoy_pct=comparison.ebitda_yoy_pct),
                pbt=MetricValue(value=metric.pbt, qoq_pct=comparison.pbt_qoq_pct, yoy_pct=comparison.pbt_yoy_pct),
                pat=MetricValue(value=metric.pat, qoq_pct=comparison.pat_qoq_pct, yoy_pct=comparison.pat_yoy_pct),
                source_document_url=metric.source_document_url,
                source_page_number=metric.source_page_number,
                extraction_confidence=metric.extraction_confidence,
                warnings=comparison.basis_mismatch_warnings,
            )
        )
    return responses
