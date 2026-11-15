"""Operator-only endpoints for Phase 12A's background jobs.

Protected by a shared-secret header (X-Admin-Token) checked against
settings.admin_api_token — not by a user login, since FINN has no operator-auth
system yet. When the token isn't configured, every route here refuses with 503
rather than being silently open ("do not expose an unrestricted job-trigger
endpoint publicly").
"""

import logging

from fastapi import APIRouter, Header, HTTPException

from app.core.config import get_settings
from app.jobs.announcement_discovery import JOB_TYPE as ANNOUNCEMENT_DISCOVERY_JOB_TYPE, run_announcement_discovery
from app.jobs.document_discovery import JOB_TYPE as DOCUMENT_DISCOVERY_JOB_TYPE, run_document_discovery
from app.jobs.market_data_refresh import JOB_TYPE, run_market_data_refresh
from app.repositories.document_review_queue import ReviewQueueRepository
from app.repositories.job_runs import JobRunRepository

logger = logging.getLogger("finn.api.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(x_admin_token: str | None) -> None:
    settings = get_settings()
    if not settings.admin_api_token:
        raise HTTPException(status_code=503, detail="Admin endpoints are not configured on this deployment.")
    if x_admin_token != settings.admin_api_token:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token.")


def _serialize_run(run) -> dict | None:
    if run is None:
        return None
    return {
        "run_id": run.id, "status": run.status, "triggered_by": run.triggered_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "result_summary": run.result_summary, "error_message": run.error_message, "log": run.log,
    }


def _job_status(job_type: str) -> dict:
    repo = JobRunRepository()
    return {
        "job_type": job_type, "currently_running": repo.is_active(job_type),
        "latest_run": _serialize_run(repo.get_latest(job_type)),
        "last_successful_run": _serialize_run(repo.get_last_successful(job_type)),
    }


@router.post("/market-data/refresh")
def trigger_market_data_refresh(x_admin_token: str | None = Header(default=None)) -> dict:
    """Manually trigger the EOD market-data refresh job. Returns 409 if the
    scheduler (or a previous manual trigger) already has a run in progress —
    the actual duplicate-execution guard, shared with the scheduler via
    JobRunRepository."""
    _require_admin(x_admin_token)
    try:
        result = run_market_data_refresh(triggered_by="api")
    except Exception:
        logger.exception("Manual market-data refresh failed")
        raise HTTPException(status_code=500, detail="Refresh job failed — see server logs.")
    if result.get("skipped"):
        raise HTTPException(status_code=409, detail=result["reason"])
    return result


@router.get("/market-data/status")
def market_data_refresh_status(x_admin_token: str | None = Header(default=None)) -> dict:
    """Operational visibility: latest run, last successful run, per-company
    results, and whether a run is active right now."""
    _require_admin(x_admin_token)
    return _job_status(JOB_TYPE)


@router.post("/document-discovery/run")
def trigger_document_discovery(x_admin_token: str | None = Header(default=None)) -> dict:
    """Manually trigger document discovery for the portfolio. Returns 409 if a
    run (scheduled or manual) is already in progress."""
    _require_admin(x_admin_token)
    try:
        result = run_document_discovery(triggered_by="api")
    except Exception:
        logger.exception("Manual document discovery failed")
        raise HTTPException(status_code=500, detail="Discovery job failed — see server logs.")
    if result.get("skipped"):
        raise HTTPException(status_code=409, detail=result["reason"])
    return result


@router.get("/document-discovery/status")
def document_discovery_status(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_token)
    return _job_status(DOCUMENT_DISCOVERY_JOB_TYPE)


@router.get("/document-discovery/review-queue")
def document_discovery_review_queue(x_admin_token: str | None = Header(default=None)) -> dict:
    """Candidates the discovery job could not confidently auto-ingest —
    unconfirmed source identity or an ambiguous doc type/period. Read-only here;
    approving/rejecting an entry is a deliberate future step, not wired to any
    automatic ingestion action."""
    _require_admin(x_admin_token)
    entries = ReviewQueueRepository().list_pending()
    return {
        "count": len(entries),
        "entries": [
            {
                "id": e.id, "company_ticker": e.company_ticker, "doc_type": e.doc_type, "title": e.title,
                "source_url": e.source_url, "source_name": e.source_name, "reporting_period": e.reporting_period,
                "reason": e.reason, "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
    }


@router.post("/announcement-discovery/run")
def trigger_announcement_discovery(x_admin_token: str | None = Header(default=None)) -> dict:
    """Manually trigger announcement discovery for the portfolio. Returns 409
    if a run (scheduled or manual) is already in progress."""
    _require_admin(x_admin_token)
    try:
        result = run_announcement_discovery(triggered_by="api")
    except Exception:
        logger.exception("Manual announcement discovery failed")
        raise HTTPException(status_code=500, detail="Announcement discovery job failed — see server logs.")
    if result.get("skipped"):
        raise HTTPException(status_code=409, detail=result["reason"])
    return result


@router.get("/announcement-discovery/status")
def announcement_discovery_status(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_token)
    return _job_status(ANNOUNCEMENT_DISCOVERY_JOB_TYPE)
