"""UUID corrections (Section C): financial_metrics.id and alerts.id must be real
uuid4 values, not human-readable composite strings — the live Supabase schema
types both columns as `uuid`, which rejects a string like
"RELIANCE-Q2FY26-standalone" outright. These tests exercise the actual production
code paths (not a reimplementation) with an isolated JSON store, so no real data
directory is touched.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app.api import financials as financials_api
from app.models.announcement import Announcement, AnnouncementCategory, AlertsConfig, PriorityLevel
from app.repositories.alerts import AlertRepository
from app.repositories.financial_metrics import FinancialMetricRepository
from app.repositories.json_store import JsonListStore
from app.schemas.financial_metrics import FinancialMetricImportRequest
from app.schemas.market_data import PriceQuote, SessionStatus
from app.services.alert_evaluation import evaluate_announcement_alert, evaluate_market_alert


def test_financial_metric_import_assigns_a_real_uuid_primary_key(tmp_path):
    store = JsonListStore(str(tmp_path), "financial_metrics.json")
    with patch.object(financials_api, "FinancialMetricRepository", return_value=FinancialMetricRepository(store=store)):
        result = financials_api.import_financial_metric(
            FinancialMetricImportRequest(ticker="RELIANCE", period="Q9FY99", revenue=1.0)
        )
    assert result["created"] is True
    saved = store.read_all()
    assert len(saved) == 1
    uuid.UUID(saved[0]["id"])  # raises ValueError if this is a composite string, not a uuid


def test_market_alert_ids_are_real_uuids_not_composite_strings(tmp_path):
    repo = AlertRepository(store=JsonListStore(str(tmp_path), "alerts.json"))
    config = AlertsConfig(volume_spike_multiple=2.0, price_move_pct=5.0, updated_at=datetime.now(timezone.utc))
    quote = PriceQuote(
        ticker="RELIANCE",
        yfinance_symbol="RELIANCE.NS",
        data_available=True,
        session_status=SessionStatus.CLOSED_EOD,
        latest_close=100,
        latest_volume=1000,
        avg_volume_window_days=20,
        avg_volume=400,
        volume_multiple=3.0,
        fetched_at=datetime.now(timezone.utc),
    )
    alerts = evaluate_market_alert(quote, config, repo=repo)
    assert len(alerts) == 1
    uuid.UUID(alerts[0].id)


def test_material_announcement_alert_id_is_a_real_uuid(tmp_path):
    repo = AlertRepository(store=JsonListStore(str(tmp_path), "alerts.json"))
    announcement = Announcement(
        id=str(uuid.uuid4()),
        company_ticker="RELIANCE",
        filed_at=datetime.now(timezone.utc),
        title="Results announced",
        category=AnnouncementCategory.RESULTS,
        priority=PriorityLevel.HIGH,
        is_material=True,
        original_source_url="https://example.com/uuid-test",
        ingested_at=datetime.now(timezone.utc),
    )
    config = AlertsConfig(
        alert_categories=[AnnouncementCategory.RESULTS],
        updated_at=datetime.now(timezone.utc),
    )
    alert = evaluate_announcement_alert(announcement, config, repo=repo)
    assert alert is not None
    uuid.UUID(alert.id)
