"""Alert evaluation (requirements.md Module 8).

Evaluated on-demand — "whenever market data is refreshed or a filing is imported",
exactly as specified, NOT continuously. There is no background scheduler in this
prototype; this module is called synchronously from the market-data and
announcement-import endpoints. This is deliberate and documented, not a shortcut:
the prototype uses EOD market data and manually imported filings, never claiming
continuous real-time monitoring.
"""

import uuid
from datetime import datetime, timezone

from app.models.announcement import Alert, AlertsConfig, AlertTriggerType, Announcement
from app.repositories.alerts import AlertRepository
from app.schemas.market_data import PriceQuote
from app.services.anomaly import detect_anomalies


def evaluate_market_alert(quote: PriceQuote, config: AlertsConfig, repo: AlertRepository | None = None) -> list[Alert]:
    repo = repo or AlertRepository()
    anomaly = detect_anomalies(quote, config)
    created_alerts: list[Alert] = []

    if anomaly.is_volume_spike:
        alert = Alert(
            id=str(uuid.uuid4()),
            company_ticker=quote.ticker,
            trigger_type=AlertTriggerType.VOLUME_SPIKE,
            trade_date=quote.as_of_date,
            payload={"volume_multiple": quote.volume_multiple, "reason": anomaly.reasons[0] if anomaly.reasons else None},
            triggered_at=datetime.now(timezone.utc),
        )
        _, created = repo.add(alert)
        if created:
            created_alerts.append(alert)

    if anomaly.is_price_move:
        alert = Alert(
            id=str(uuid.uuid4()),
            company_ticker=quote.ticker,
            trigger_type=AlertTriggerType.PRICE_MOVE,
            trade_date=quote.as_of_date,
            payload={"daily_change_pct": quote.daily_change_pct},
            triggered_at=datetime.now(timezone.utc),
        )
        _, created = repo.add(alert)
        if created:
            created_alerts.append(alert)

    return created_alerts


def evaluate_announcement_alert(
    announcement: Announcement, config: AlertsConfig, repo: AlertRepository | None = None
) -> Alert | None:
    if announcement.category not in config.alert_categories:
        return None
    if not announcement.is_material:
        return None

    repo = repo or AlertRepository()
    alert = Alert(
        id=str(uuid.uuid4()),
        company_ticker=announcement.company_ticker,
        trigger_type=AlertTriggerType.MATERIAL_ANNOUNCEMENT,
        source_announcement_id=announcement.id,
        payload={"title": announcement.title, "category": announcement.category.value, "priority": announcement.priority.value},
        triggered_at=datetime.now(timezone.utc),
    )
    record, created = repo.add(alert)
    return record if created else None
