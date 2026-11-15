"""End-to-end API tests through FastAPI's TestClient. Each test points the app's
storage at an isolated tmp_path by overriding DATA_DIR and clearing the cached
Settings singleton, so these never touch backend/data/ (the real app's storage)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)


def _recent_iso() -> str:
    """A timestamp safely in the past relative to real wall-clock time, so it never
    accidentally lands outside a 'last 24 hours' digest window due to test/request
    timing (a hardcoded future-looking literal caused exactly this once)."""
    return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Also blank out any configured Supabase credentials for the duration of these
    # tests: this fixture's whole point is "never touch the real app's storage",
    # and a live Supabase project is just as real a storage backend as
    # backend/data/ is. Setting to "" (not delenv) matters: pydantic-settings
    # falls back to backend/.env's own value for a var that's merely absent from
    # the process environment, so delenv alone would NOT suppress a real value
    # already present in .env — only an explicit empty-string override does.
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_import_then_appears_in_digest():
    import_resp = client.post(
        "/api/announcements/import",
        json={
            "ticker": "RELIANCE",
            "title": "Outcome of Board Meeting - Unaudited Financial Results for the quarter",
            "filed_at": _recent_iso(),
            "original_source_url": "https://example.com/api-test-results",
        },
    )
    assert import_resp.status_code == 200
    body = import_resp.json()
    assert body["created"] is True
    assert body["category"] == "results"

    digest_resp = client.get("/api/digest", params={"window_hours": 24})
    assert digest_resp.status_code == 200
    digest = digest_resp.json()
    titles = [i["title"] for i in digest["items"]]
    assert "Outcome of Board Meeting - Unaudited Financial Results for the quarter" in titles


def test_duplicate_import_via_api_is_rejected():
    payload = {
        "ticker": "TCS",
        "title": "Some filing",
        "filed_at": _recent_iso(),
        "original_source_url": "https://example.com/api-dup-test",
    }
    first = client.post("/api/announcements/import", json=payload)
    second = client.post("/api/announcements/import", json=payload)
    assert first.json()["created"] is True
    assert second.json()["created"] is False


def test_import_unknown_ticker_returns_422(monkeypatch):
    # "NOTREAL" is outside the seed registry, so this now also exercises the
    # unseeded-ticker verification path — mock yfinance so the test never depends
    # on a live network call, and so it deterministically looks unverifiable (the
    # real NOTREAL.NS also returns this shape, confirmed earlier in this build).
    monkeypatch.setattr("yfinance.Ticker", lambda *_a, **_k: MagicMock(info={}))
    resp = client.post(
        "/api/announcements/import",
        json={
            "ticker": "NOTREAL",
            "title": "x",
            "filed_at": _recent_iso(),
            "original_source_url": "https://example.com/x",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unknown_ticker"


def test_batch_import_reports_counts(monkeypatch):
    monkeypatch.setattr("yfinance.Ticker", lambda *_a, **_k: MagicMock(info={}))
    resp = client.post(
        "/api/announcements/import/batch",
        json=[
            {
                "ticker": "INFY",
                "title": "Filing A",
                "filed_at": _recent_iso(),
                "original_source_url": "https://example.com/batch-a",
            },
            {
                "ticker": "INFY",
                "title": "Filing A",
                "filed_at": _recent_iso(),
                "original_source_url": "https://example.com/batch-a",
            },
            {
                "ticker": "NOTREAL",
                "title": "Filing C",
                "filed_at": _recent_iso(),
                "original_source_url": "https://example.com/batch-c",
            },
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created_count"] == 1
    assert body["duplicate_count"] == 1
    assert body["error_count"] == 1


def test_alerts_config_round_trip():
    update_resp = client.put(
        "/api/alerts/config",
        json={
            "volume_spike_multiple": 3.0,
            "price_move_pct": 7.5,
            "digest_window_hours": 48,
            "alert_categories": ["results", "dividend"],
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["volume_spike_multiple"] == 3.0

    get_resp = client.get("/api/alerts/config")
    assert get_resp.status_code == 200
    assert get_resp.json()["price_move_pct"] == 7.5
    assert get_resp.json()["alert_categories"] == ["results", "dividend"]


def test_digest_category_filter_via_api():
    client.post(
        "/api/announcements/import",
        json={
            "ticker": "SBIN",
            "title": "Intimation of Record Date for payment of dividend",
            "filed_at": _recent_iso(),
            "original_source_url": "https://example.com/sbin-dividend",
        },
    )
    client.post(
        "/api/announcements/import",
        json={
            "ticker": "SBIN",
            "title": "Outcome of Board Meeting - Unaudited Financial Results",
            "filed_at": _recent_iso(),
            "original_source_url": "https://example.com/sbin-results",
        },
    )

    resp = client.get("/api/digest", params={"window_hours": 24, "categories": ["dividend"]})
    body = resp.json()
    assert all(item["category"] == "dividend" for item in body["items"])


def test_digest_custom_date_range_via_api_accepts_bare_dates():
    """A bare date string (what an HTML date input sends) must not 500 - this is
    the real bug a naive/aware datetime comparison would otherwise hit."""
    resp = client.get("/api/digest", params={"start": "2026-01-01", "end": "2026-01-31"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == len(body["items"])  # internally consistent, not asserting a specific count


def test_digest_custom_date_range_rejects_start_after_end_via_api():
    resp = client.get("/api/digest", params={"start": "2026-02-01", "end": "2026-01-01"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_date_range"


def test_events_custom_date_range_via_api_accepts_bare_dates():
    resp = client.get("/api/events", params={"start": "2026-01-01", "end": "2026-01-31"})
    assert resp.status_code == 200


def test_events_custom_date_range_rejects_start_after_end_via_api():
    resp = client.get("/api/events", params={"start": "2026-02-01", "end": "2026-01-01"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_date_range"


def test_financials_results_comparison_empty_for_unimported_ticker():
    resp = client.get("/api/financials/WIPRO/results-comparison")
    assert resp.status_code == 200
    assert resp.json() == []


def test_financials_import_and_comparison():
    client.post(
        "/api/financials/import",
        json={"ticker": "RELIANCE", "period": "Q1FY26", "basis": "standalone", "revenue": 1000, "pat": 90},
    )
    client.post(
        "/api/financials/import",
        json={"ticker": "RELIANCE", "period": "Q2FY26", "basis": "standalone", "revenue": 1100, "pat": 100},
    )
    resp = client.get("/api/financials/RELIANCE/results-comparison")
    assert resp.status_code == 200
    body = resp.json()
    q2 = next(p for p in body if p["period"] == "Q2FY26")
    assert q2["revenue"]["qoq_pct"] == pytest.approx(10.0)


def test_financials_import_accepts_a_valid_unseeded_ticker(monkeypatch):
    """WIPRO is outside the 15+4 seed registry — this must still succeed once it's
    verifiable as a real NSE equity (requirements.md Section 3 generalization)."""
    monkeypatch.setattr(
        "yfinance.Ticker",
        lambda *_a, **_k: MagicMock(info={"quoteType": "EQUITY", "longName": "Wipro Limited", "exchange": "NSI", "sector": "Technology"}),
    )
    resp = client.post(
        "/api/financials/import",
        json={"ticker": "WIPRO", "period": "Q3FY26", "basis": "standalone", "revenue": 500},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] is True


def test_financials_import_rejects_an_invalid_ticker(monkeypatch):
    monkeypatch.setattr("yfinance.Ticker", lambda *_a, **_k: MagicMock(info={}))
    resp = client.post(
        "/api/financials/import",
        json={"ticker": "ZZZZINVALID", "period": "Q1FY26", "basis": "standalone", "revenue": 500},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "company_not_found"


def test_health_reports_storage_backend_and_llm_status():
    resp = client.get("/api/health")
    body = resp.json()
    assert body["storage_backend"] == "json_fallback"  # no Supabase configured in this environment
    assert "llm_configured" in body
