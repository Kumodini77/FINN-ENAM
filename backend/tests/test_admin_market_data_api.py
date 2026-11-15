"""Phase 12A — the operator-facing admin endpoints: auth gating and the
duplicate-run guard surfaced as a real HTTP 409, not just at the job-function
level (already covered in test_market_data_refresh_job.py)."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _force_json_fallback_for_job_runs(tmp_path, monkeypatch):
    """These tests must not touch the live Supabase project — migration 010
    (the new ingestion_jobs columns) is written but deliberately NOT applied
    there yet, per this repo's established practice of treating a migration as
    a reviewed proposal until a human runs it (see docs/migration-runbook.md,
    and 007/008's own 'PROPOSED — NOT YET APPLIED' headers). Forcing JSON
    fallback here is what 'no live external calls in ordinary unit tests' means
    for this endpoint."""
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    monkeypatch.setattr("app.repositories.job_runs.storage_backend_name", lambda: "json_fallback")


def test_refresh_endpoint_refuses_when_no_token_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_api_token", None)
    resp = client.post("/api/admin/market-data/refresh")
    assert resp.status_code == 503


def test_refresh_endpoint_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_api_token", "secret123")
    resp = client.post("/api/admin/market-data/refresh", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


def test_status_endpoint_requires_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_api_token", "secret123")
    resp = client.get("/api/admin/market-data/status")
    assert resp.status_code == 401

    resp_ok = client.get("/api/admin/market-data/status", headers={"X-Admin-Token": "secret123"})
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert body["job_type"] == "market_data_refresh"
    assert "currently_running" in body


def test_refresh_endpoint_returns_409_when_a_run_is_already_active(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_api_token", "secret123")
    from app.repositories.job_runs import JobRunRepository

    JobRunRepository().start_run("market_data_refresh", "manual")
    try:
        resp = client.post("/api/admin/market-data/refresh", headers={"X-Admin-Token": "secret123"})
        assert resp.status_code == 409
    finally:
        # Clean up: mark the fake in-flight run terminal so it doesn't bleed into
        # other tests sharing the same (JSON-fallback or Supabase) storage backend.
        repo = JobRunRepository()
        latest = repo.get_latest("market_data_refresh")
        if latest and latest.status == "running":
            repo.complete_run(latest.id, status="failed", result_summary={}, error_message="test cleanup")
