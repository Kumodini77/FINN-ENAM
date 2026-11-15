"""Phase 12C Part 2 — scheduled automatic announcement discovery for the
frozen portfolio.

Same shape as Phase 12A's market_data_refresh.py and Phase 12B's
document_discovery.py: one JobRunRepository batch run, run_with_retry per
unit of work, one company's failure never blocking another. No second
scheduler or job framework was created for this.

Classification, priority scoring, "why it matters", and alert evaluation are
ALL reused unchanged from app.services.announcement_import.import_announcement
— the same function the existing manual-import admin flow already uses. This
job's only new responsibility is finding candidates and handing them to that
function; it adds zero new classification/priority logic.

Source health is tracked via app.repositories.document_sources.DocumentSourceRepository
(source_name="screener_announcements") — reused as-is rather than building a
second per-source checkpoint table, since the concept (per-ticker, per-source
check timestamps/health) is identical to Phase 12B's document-source tracking.
"""

from __future__ import annotations

import logging

from app.core.companies import get_seed_company
from app.core.exceptions import CompanyLookupError
from app.models.announcement import SourceType, VerificationStatus
from app.repositories.document_sources import DEGRADED, HEALTHY, DocumentSourceRepository
from app.repositories.job_runs import JobAlreadyRunningError, JobRunRepository
from app.repositories.portfolio import PortfolioRepository
from app.schemas.announcement_import import AnnouncementImportRequest
from app.services.announcement_discovery.screener_announcement_adapter import ScreenerAnnouncementAdapter
from app.services.announcement_discovery.types import AnnouncementSourceCheckResult, DiscoveredAnnouncement
from app.services.announcement_import import import_announcement
from app.services.company_resolution import resolve_company

logger = logging.getLogger("finn.jobs.announcement_discovery")

JOB_TYPE = "announcement_discovery"


def _resolve_company_name(ticker: str) -> str | None:
    seed = get_seed_company(ticker)
    if seed is not None:
        return seed.name
    try:
        return resolve_company(ticker).name
    except CompanyLookupError:
        return None


def _record_checkpoint(source_repo: DocumentSourceRepository, result: AnnouncementSourceCheckResult) -> None:
    health = HEALTHY if (result.ok and result.identity_verified) else DEGRADED
    top = result.announcements[0] if result.announcements else None
    source_repo.record_check(
        result.ticker, result.source_name, ok=result.ok, source_url=result.checked_url, health=health,
        error_message=result.error, discovered_title=top.title if top else None, discovered_url=top.source_url if top else None,
    )


def _import_candidate(candidate: DiscoveredAnnouncement) -> dict:
    payload = AnnouncementImportRequest(
        ticker=candidate.company_ticker, title=candidate.title, filed_at=candidate.filed_at,
        original_source_url=candidate.source_url, document_url=candidate.document_url,
        extracted_text=candidate.one_line_summary, source=SourceType.LIVE, verification_status=VerificationStatus.UNVERIFIED,
        seeded_by=f"announcement_discovery:{candidate.source_name}",
    )
    result = import_announcement(payload)
    return {"created": result.created, "category": result.category.value, "priority": result.priority, "announcement_id": result.announcement_id}


def _discover_for_company(ticker: str, adapter: ScreenerAnnouncementAdapter, source_repo: DocumentSourceRepository) -> dict:
    company_name = _resolve_company_name(ticker)
    if company_name is None:
        return {"status": "failed", "error": f"Could not resolve a verified company name for {ticker!r}.", "discovered": 0, "imported": 0, "duplicates": 0}

    try:
        result = adapter.check(ticker, company_name)
    except Exception as exc:  # noqa: BLE001 - adapter failures must not crash the batch
        result = AnnouncementSourceCheckResult(ticker=ticker, source_name=adapter.source_name, ok=False, error=str(exc))

    _record_checkpoint(source_repo, result)

    if not result.ok or not result.identity_verified:
        return {"status": "failed", "error": result.error, "discovered": 0, "imported": 0, "duplicates": 0}

    imported = 0
    duplicates = 0
    import_errors: list[str] = []
    for candidate in result.announcements:
        try:
            outcome = _import_candidate(candidate)
            if outcome["created"]:
                imported += 1
            else:
                duplicates += 1
        except Exception as exc:  # noqa: BLE001 - one bad candidate must not stop the rest
            logger.warning("announcement_discovery: failed to import %r for %s: %s", candidate.title, ticker, exc)
            import_errors.append(str(exc))

    status = "success" if not import_errors else ("partial" if imported or duplicates else "failed")
    return {"status": status, "discovered": len(result.announcements), "imported": imported, "duplicates": duplicates, "errors": import_errors}


def run_announcement_discovery(
    triggered_by: str = "scheduler",
    *,
    job_repo: JobRunRepository | None = None,
    source_repo: DocumentSourceRepository | None = None,
    portfolio_repo: PortfolioRepository | None = None,
    adapter: ScreenerAnnouncementAdapter | None = None,
) -> dict:
    job_repo = job_repo or JobRunRepository()
    source_repo = source_repo or DocumentSourceRepository()
    portfolio_repo = portfolio_repo or PortfolioRepository()
    adapter = adapter or ScreenerAnnouncementAdapter()

    try:
        run = job_repo.start_run(JOB_TYPE, triggered_by, max_retries=2, timeout_seconds=60)
    except JobAlreadyRunningError as exc:
        return {"skipped": True, "reason": str(exc)}

    tickers = sorted(portfolio_repo.list_tickers())
    results: dict[str, dict] = {}

    try:
        for ticker in tickers:
            try:
                results[ticker] = _discover_for_company(ticker, adapter, source_repo)
            except Exception as exc:  # noqa: BLE001
                logger.exception("announcement_discovery: unexpected error for %s", ticker)
                results[ticker] = {"status": "failed", "error": str(exc), "discovered": 0, "imported": 0, "duplicates": 0}
            job_repo.heartbeat(run.id)

        statuses = {r["status"] for r in results.values()}
        if not tickers or statuses <= {"success"}:
            final_status, error_message = "success", None
        elif statuses == {"failed"}:
            final_status, error_message = "failed", "All companies failed — see result_summary."
        else:
            final_status, error_message = "partial", "Some companies had failures — see result_summary."

        total_imported = sum(r.get("imported", 0) for r in results.values())
        job_repo.complete_run(
            run.id, status=final_status, result_summary=results, error_message=error_message,
            log=f"Checked {len(tickers)} ticker(s); imported {total_imported} new announcement(s).", records_affected=total_imported,
        )
        return {"run_id": run.id, "status": final_status, "results": results, "records_affected": total_imported}

    except Exception as exc:  # noqa: BLE001
        logger.exception("announcement_discovery: job crashed")
        job_repo.complete_run(run.id, status="failed", result_summary=results, error_message=str(exc), log="Job crashed before completing.")
        raise


__all__ = ["run_announcement_discovery", "JOB_TYPE"]
