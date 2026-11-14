"""Tests for the new alert transparency enrichment (GET /api/alerts) - existing
alert evaluation/dedup/config logic is untouched; this only covers the new
read-time transparency computation."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.announcement import Alert, AlertTriggerType, Announcement, AnnouncementCategory
from app.repositories.alerts import AlertRepository
from app.repositories.announcements import AnnouncementRepository
from app.repositories.financial_metrics import FinancialMetricRepository
from app.repositories.json_store import JsonListStore

client = TestClient(app)


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    alert_repo = AlertRepository(store=JsonListStore(str(tmp_path), "alerts.json"))
    ann_repo = AnnouncementRepository(store=JsonListStore(str(tmp_path), "announcements.json"))

    announcement = Announcement.model_validate(
        dict(
            id="a1", company_ticker="HDFCBANK", filed_at=datetime.now(timezone.utc),
            title="Results for the quarter ended June 30, 2026", category=AnnouncementCategory.RESULTS,
            original_source_url="https://x.invalid/a1.pdf", ingested_at=datetime.now(timezone.utc),
        )
    )
    ann_repo.add(announcement)

    material_alert = Alert(
        id="al1", company_ticker="HDFCBANK", trigger_type=AlertTriggerType.MATERIAL_ANNOUNCEMENT,
        source_announcement_id="a1", payload={"title": announcement.title}, triggered_at=datetime.now(timezone.utc),
    )
    volume_alert = Alert(
        id="al2", company_ticker="HDFCBANK", trigger_type=AlertTriggerType.VOLUME_SPIKE,
        payload={"volume_multiple": 3.2}, triggered_at=datetime.now(timezone.utc),
    )
    alert_repo.add(material_alert)
    alert_repo.add(volume_alert)

    monkeypatch.setattr("app.api.alerts.AlertRepository", lambda: alert_repo)
    monkeypatch.setattr("app.api.alerts.AnnouncementRepository", lambda: ann_repo)
    monkeypatch.setattr("app.api.alerts.FinancialMetricRepository", FinancialMetricRepository)
    return {"alert_repo": alert_repo, "ann_repo": ann_repo}


def test_material_announcement_alert_is_marked_primary_disclosure(seeded):
    resp = client.get("/api/alerts")
    assert resp.status_code == 200
    by_id = {a["id"]: a for a in resp.json()}
    assert by_id["al1"]["transparency"]["is_primary_disclosure"] is True
    assert by_id["al1"]["transparency"]["priority_rationale"]


def test_material_announcement_without_financial_metrics_says_so_honestly(seeded):
    resp = client.get("/api/alerts")
    by_id = {a["id"]: a for a in resp.json()}
    assert by_id["al1"]["transparency"]["has_numerical_evidence"] is False
    assert "No financial_metrics" in by_id["al1"]["transparency"]["evidence_note"]


def test_market_data_alert_is_not_marked_a_primary_disclosure(seeded):
    resp = client.get("/api/alerts")
    by_id = {a["id"]: a for a in resp.json()}
    assert by_id["al2"]["transparency"]["is_primary_disclosure"] is False
    assert "market" in by_id["al2"]["transparency"]["evidence_note"].lower()


def test_existing_alert_fields_are_unchanged(seeded):
    resp = client.get("/api/alerts")
    by_id = {a["id"]: a for a in resp.json()}
    assert by_id["al1"]["company_ticker"] == "HDFCBANK"
    assert by_id["al1"]["trigger_type"] == "material_announcement"
    assert by_id["al1"]["source_announcement_id"] == "a1"
