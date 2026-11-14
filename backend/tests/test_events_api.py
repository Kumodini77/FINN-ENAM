"""API-level tests for GET /api/events - uses the JSON-fallback AnnouncementRepository
(real grouping/intelligence logic, isolated storage) via dependency injection at the
module level, consistent with test_api_integration.py's pattern."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.announcement import Announcement, AnnouncementCategory
from app.repositories.announcements import AnnouncementRepository
from app.repositories.json_store import JsonListStore

client = TestClient(app)


@pytest.fixture
def seeded_announcements(tmp_path, monkeypatch):
    store = JsonListStore(str(tmp_path), "announcements.json")
    repo = AnnouncementRepository(store=store)

    results = Announcement.model_validate(
        dict(
            id="a1", company_ticker="HDFCBANK", filed_at=datetime.now(timezone.utc),
            title="Results for the quarter ended June 30, 2026", category=AnnouncementCategory.RESULTS,
            original_source_url="https://x.invalid/a1.pdf", ingested_at=datetime.now(timezone.utc),
            priority="high",
        )
    )
    concall = Announcement.model_validate(
        dict(
            id="a2", company_ticker="HDFCBANK", filed_at=datetime.now(timezone.utc),
            title="Transcript of earnings call for Q1 FY27", category=AnnouncementCategory.EARNINGS_CALL,
            original_source_url="https://x.invalid/a2.pdf", ingested_at=datetime.now(timezone.utc),
        )
    )
    repo.add(results)
    repo.add(concall)

    from app.core.companies import PORTFOLIO

    monkeypatch.setattr("app.api.events.PORTFOLIO", [c for c in PORTFOLIO if c.ticker == "HDFCBANK"] or PORTFOLIO)
    monkeypatch.setattr("app.api.events.AnnouncementRepository", lambda: repo)
    return repo


def test_grouped_event_includes_both_source_documents(seeded_announcements):
    resp = client.get("/api/events", params={"window_hours": 24 * 365})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_announcements"] == 2
    assert len(body["events"]) == 1
    event = body["events"][0]
    assert {d["announcement_id"] for d in event["source_documents"]} == {"a1", "a2"}
    assert event["reporting_period"] == "Q1FY27"


def test_event_has_a_research_link_with_suggested_question(seeded_announcements):
    resp = client.get("/api/events", params={"window_hours": 24 * 365})
    event = resp.json()["events"][0]
    assert event["research_link"]["ticker"] == "HDFCBANK"
    assert "revenue" in event["research_link"]["suggested_question"].lower()


def test_no_financial_metrics_means_no_fabricated_financial_changes(seeded_announcements):
    resp = client.get("/api/events", params={"window_hours": 24 * 365})
    event = resp.json()["events"][0]
    assert event["financial_changes"] == []
    assert event["missing_information"]  # honestly flagged
