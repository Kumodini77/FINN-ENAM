from fastapi import APIRouter

from app.models.announcement import AlertsConfig, AlertTriggerType
from app.repositories.alerts import AlertRepository, AlertsConfigRepository
from app.repositories.announcements import AnnouncementRepository
from app.repositories.financial_metrics import FinancialMetricRepository
from app.schemas.alerts import AlertOut, AlertsConfigIn, AlertsConfigOut, AlertTransparencyOut
from app.services.period_resolution import resolve_period_mention
from app.services.priority import compute_priority

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _transparency_for(alert, announcements_by_id: dict, metric_repo: FinancialMetricRepository) -> AlertTransparencyOut:
    if alert.trigger_type != AlertTriggerType.MATERIAL_ANNOUNCEMENT:
        return AlertTransparencyOut(
            is_primary_disclosure=False, has_numerical_evidence=True,
            evidence_note="Derived from market price/volume data, not a company disclosure.",
            priority_rationale=None,
        )

    announcement = announcements_by_id.get(alert.source_announcement_id)
    if announcement is None:
        return AlertTransparencyOut(
            is_primary_disclosure=True, has_numerical_evidence=False,
            evidence_note="Source announcement record could not be located.", priority_rationale=None,
        )

    period = resolve_period_mention(f"{announcement.title} {announcement.extracted_text or ''}")
    has_metric = False
    if period:
        has_metric = any(m.period == period for m in metric_repo.list_for_ticker(announcement.company_ticker))

    priority_result = compute_priority(announcement.category, announcement.filed_at)
    note = (
        "Linked financial_metrics are available for this period."
        if has_metric
        else "No financial_metrics imported yet for this announcement's period — evidence is the filing text only."
    )
    return AlertTransparencyOut(
        is_primary_disclosure=True, has_numerical_evidence=has_metric, evidence_note=note,
        priority_rationale=priority_result.rationale,
    )


@router.get("", response_model=list[AlertOut])
def list_alerts() -> list[AlertOut]:
    """Alerts already evaluated and stored — evaluation itself happens as a side
    effect of GET /api/market-data/portfolio and POST /api/announcements/import,
    per requirements.md Module 8 ("whenever market data is refreshed or a filing is
    imported"), not on a background schedule."""
    repo = AlertRepository()
    alerts = sorted(repo.list_all(), key=lambda a: a.triggered_at, reverse=True)

    announcements_by_id = {a.id: a for a in AnnouncementRepository().list_all()}
    metric_repo = FinancialMetricRepository()

    return [
        AlertOut(
            id=a.id,
            company_ticker=a.company_ticker,
            trigger_type=a.trigger_type.value,
            source_announcement_id=a.source_announcement_id,
            trade_date=a.trade_date,
            payload=a.payload,
            triggered_at=a.triggered_at,
            seen_at=a.seen_at,
            transparency=_transparency_for(a, announcements_by_id, metric_repo),
        )
        for a in alerts
    ]


@router.get("/config", response_model=AlertsConfigOut)
def get_alerts_config() -> AlertsConfigOut:
    config = AlertsConfigRepository().get()
    return AlertsConfigOut(**config.model_dump())


@router.put("/config", response_model=AlertsConfigOut)
def update_alerts_config(payload: AlertsConfigIn) -> AlertsConfigOut:
    repo = AlertsConfigRepository()
    existing = repo.get()
    updated = AlertsConfig(
        user_id=existing.user_id,
        volume_spike_multiple=payload.volume_spike_multiple,
        price_move_pct=payload.price_move_pct,
        digest_window_hours=payload.digest_window_hours,
        alert_categories=payload.alert_categories,
        updated_at=existing.updated_at,
    )
    saved = repo.save(updated)
    return AlertsConfigOut(**saved.model_dump())
