"""Phase 12B — scheduled automatic document discovery for the frozen portfolio.

Mirrors Phase 12A's market_data_refresh.py shape exactly (same JobRunRepository,
same run_with_retry, same "one call = one batch run, one company's failure never
blocks the others" structure) — reusing the Phase 12A foundation rather than
building a second job framework, per this phase's own instruction.

Pipeline per company: adapters discover candidates -> triage (dedup against
existing documents, identity/confidence gating, backfill limits) -> accepted
candidates are downloaded and run through the EXISTING ingestion pipeline
(app.services.ingestion.ingest_document) unchanged. Ambiguous candidates go to
the review queue instead of being ingested. Ad-hoc research companies are never
touched (same PortfolioRepository-only scoping as Phase 12A).
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field

import httpx

from app.core.companies import get_seed_company
from app.core.config import get_settings
from app.core.exceptions import CompanyLookupError, DocumentAlreadyClaimedError, DocumentExistingConflictError, DocumentMetadataConflictError
from app.models.document import DocType
from app.repositories.company_lookup import get_or_register_company_id
from app.repositories.document_review_queue import ReviewQueueRepository
from app.repositories.document_sources import BLOCKED, DEGRADED, HEALTHY, DocumentSourceRepository
from app.repositories.documents import DocumentRepository
from app.repositories.job_runs import JobAlreadyRunningError, JobRunRepository
from app.repositories.portfolio import PortfolioRepository
from app.services.company_resolution import resolve_company
from app.services.document_discovery.ir_website_adapter import IRWebsiteSourceAdapter
from app.services.document_discovery.screener_adapter import ScreenerSourceAdapter
from app.services.document_discovery.types import DiscoveredCandidate, SourceCheckResult
from app.services.embeddings import get_embedding_provider
from app.services.ingestion import IngestionError, ingest_document

logger = logging.getLogger("finn.jobs.document_discovery")

JOB_TYPE = "document_discovery"
VALID_DOC_TYPES = {d.value for d in DocType}
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
PER_SOURCE_TIMEOUT_SECONDS = 20


class DownloadError(Exception):
    pass


def _default_downloader(url: str) -> str:
    """Downloads `url` to a temp .pdf file and returns its path. Raises
    DownloadError on any failure (timeout, non-200, wrong content). Real network
    I/O — tests inject a fake downloader instead of exercising this."""
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=30.0, headers={"User-Agent": "FINNResearchBot/1.0"}) as resp:
            if resp.status_code != 200:
                raise DownloadError(f"{url} returned HTTP {resp.status_code}")
            fd, path = tempfile.mkstemp(suffix=".pdf")
            total = 0
            try:
                with os.fdopen(fd, "wb") as f:
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            raise DownloadError(f"{url} exceeded the {MAX_DOWNLOAD_BYTES}-byte download limit.")
                        f.write(chunk)
            except Exception:
                os.unlink(path)
                raise
            return path
    except httpx.HTTPError as exc:
        raise DownloadError(f"Failed to download {url}: {exc}") from exc


def _is_valid_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            header = f.read(5)
        return header.startswith(b"%PDF-") and os.path.getsize(path) > 0
    except OSError:
        return False


@dataclass
class CompanyDiscoveryOutcome:
    status: str  # "success" | "partial" | "failed"
    discovered: int = 0
    accepted: int = 0
    ingested: int = 0
    duplicates_skipped: int = 0
    queued_for_review: int = 0
    ingest_failures: list[dict] = field(default_factory=list)
    source_errors: list[str] = field(default_factory=list)


def _resolve_company_name(ticker: str) -> str | None:
    seed = get_seed_company(ticker)
    if seed is not None:
        return seed.name
    try:
        return resolve_company(ticker).name
    except CompanyLookupError:
        return None


def _record_source_checkpoint(source_repo: DocumentSourceRepository, result: SourceCheckResult) -> None:
    if result.ok and result.identity_verified:
        health = HEALTHY
    elif result.ok and not result.identity_verified:
        health = DEGRADED  # page reachable, but we don't trust what's on it yet
    else:
        health = DEGRADED
    top_candidate = result.candidates[0] if result.candidates else None
    source_repo.record_check(
        result.ticker, result.source_name, ok=result.ok, source_url=result.checked_url, health=health,
        error_message=result.error, discovered_title=top_candidate.title if top_candidate else None,
        discovered_url=top_candidate.source_url if top_candidate else None,
    )


def _triage_candidates(
    ticker: str, candidates: list[DiscoveredCandidate], document_repo: DocumentRepository, review_repo: ReviewQueueRepository, max_new_docs: int,
) -> tuple[list[DiscoveredCandidate], int, int]:
    """Returns (accepted, duplicates_skipped_count, queued_for_review_count).
    Never re-queues/re-ingests something already on file — checked by exact
    source URL AND by (doc_type, reporting_period) identity, per the phase's
    incremental-discovery requirement."""
    existing = document_repo.list_documents_for_ticker(ticker)
    existing_urls = {d.original_source_url for d in existing}
    existing_keys = {(d.doc_type.value, d.reporting_period) for d in existing}

    # Transcripts/presentations first (the "four-quarter comparison" priority),
    # annual reports after — within each group, keep the adapter's own order
    # (screener and the IR adapter both naturally list the most recent first).
    ordered = sorted(candidates, key=lambda c: 0 if c.doc_type in ("concall_transcript", "investor_presentation") else 1)

    accepted: list[DiscoveredCandidate] = []
    duplicates = 0
    queued = 0
    seen_keys_this_run: set[tuple[str, str | None]] = set()

    for candidate in ordered:
        if candidate.source_url in existing_urls:
            duplicates += 1
            continue
        key = (candidate.doc_type, candidate.reporting_period)
        if key in existing_keys or key in seen_keys_this_run:
            duplicates += 1
            continue
        if candidate.doc_type not in VALID_DOC_TYPES:
            review_repo.add(candidate, reason=f"Unrecognized doc_type {candidate.doc_type!r}.")
            queued += 1
            continue
        if not candidate.identity_verified:
            review_repo.add(candidate, reason="Source identity could not be confirmed for this company.")
            queued += 1
            continue
        if len(accepted) >= max_new_docs:
            continue  # deferred to a future run, not an error — dedup makes this safe to retry
        accepted.append(candidate)
        seen_keys_this_run.add(key)

    return accepted, duplicates, queued


def _ingest_candidate(
    candidate: DiscoveredCandidate, company_id: str, document_repo: DocumentRepository, embedding_provider, downloader,
) -> str:
    """Returns the resulting document_id. Raises on failure — caller records it
    per-candidate without stopping the rest of the company's batch."""
    try:
        local_path = downloader(candidate.source_url)
    except DownloadError as exc:
        raise IngestionError(str(exc)) from exc

    try:
        if not _is_valid_pdf(local_path):
            raise IngestionError(f"Downloaded file from {candidate.source_url} is not a valid PDF.")
        result = ingest_document(
            file_path=local_path, company_id=company_id, company_ticker=candidate.company_ticker,
            doc_type=DocType(candidate.doc_type), reporting_period=candidate.reporting_period,
            original_source_url=candidate.source_url, repo=document_repo, embedding_provider=embedding_provider,
        )
        return result.document.id
    except (DocumentExistingConflictError, DocumentMetadataConflictError, DocumentAlreadyClaimedError) as exc:
        # Another run/worker already has this identity or hash — not a real
        # failure, just confirmation that triage's dedup check (itself a plain
        # read, not a lock) lost a narrow race. Safe to treat as "already covered."
        logger.info("document_discovery: %s already resolved elsewhere: %s", candidate.source_url, exc)
        raise
    finally:
        if os.path.exists(local_path):
            os.unlink(local_path)


def _discover_for_company(
    ticker: str, document_repo: DocumentRepository, source_repo: DocumentSourceRepository, review_repo: ReviewQueueRepository,
    screener_adapter: ScreenerSourceAdapter, ir_adapter: IRWebsiteSourceAdapter, embedding_provider, downloader, max_new_docs: int,
) -> CompanyDiscoveryOutcome:
    company_name = _resolve_company_name(ticker)
    if company_name is None:
        return CompanyDiscoveryOutcome(status="failed", source_errors=[f"Could not resolve a verified company name for {ticker!r} — refusing to guess identity."])

    source_errors: list[str] = []
    all_candidates: list[DiscoveredCandidate] = []

    try:
        screener_result = screener_adapter.check(ticker, company_name)
    except Exception as exc:  # noqa: BLE001 - adapter network/parse failures must not crash the batch
        screener_result = SourceCheckResult(ticker=ticker, source_name="screener", ok=False, error=str(exc))
    _record_source_checkpoint(source_repo, screener_result)
    if screener_result.ok and screener_result.identity_verified:
        all_candidates.extend(screener_result.candidates)
    else:
        source_errors.append(f"screener: {screener_result.error}")

    from app.core.investor_relations_seeds import get_investor_relations_url

    seed_url = get_investor_relations_url(ticker)
    try:
        ir_result = ir_adapter.check(ticker, company_name, seed_url)
    except Exception as exc:  # noqa: BLE001
        ir_result = SourceCheckResult(ticker=ticker, source_name="ir_website", ok=False, error=str(exc))
    _record_source_checkpoint(source_repo, ir_result)
    if ir_result.ok and ir_result.identity_verified:
        all_candidates.extend(ir_result.candidates)
    elif seed_url is not None:  # only a real error if a source was actually configured
        source_errors.append(f"ir_website: {ir_result.error}")

    if not all_candidates:
        status = "failed" if source_errors else "success"  # no new candidates isn't a failure by itself
        return CompanyDiscoveryOutcome(status=status, discovered=0, source_errors=source_errors)

    accepted, duplicates, queued = _triage_candidates(ticker, all_candidates, document_repo, review_repo, max_new_docs)

    ingested = 0
    ingest_failures: list[dict] = []
    company_id = get_or_register_company_id(ticker) if accepted else None
    for candidate in accepted:
        try:
            document_id = _ingest_candidate(candidate, company_id, document_repo, embedding_provider, downloader)
            ingested += 1
            source_repo.record_check(
                ticker, candidate.source_name, ok=True, health=HEALTHY, processed_document_id=document_id,
                discovered_title=candidate.title, discovered_url=candidate.source_url,
            )
        except (DocumentExistingConflictError, DocumentMetadataConflictError, DocumentAlreadyClaimedError):
            duplicates += 1
        except Exception as exc:  # noqa: BLE001 - one bad candidate must not stop the rest
            logger.warning("document_discovery: failed to ingest %s for %s: %s", candidate.source_url, ticker, exc)
            ingest_failures.append({"title": candidate.title, "source_url": candidate.source_url, "error": str(exc)})

    if ingest_failures and ingested == 0 and not source_errors:
        status = "failed"
    elif ingest_failures or source_errors:
        status = "partial" if (ingested or not source_errors) else "failed"
    else:
        status = "success"

    return CompanyDiscoveryOutcome(
        status=status, discovered=len(all_candidates), accepted=len(accepted), ingested=ingested,
        duplicates_skipped=duplicates, queued_for_review=queued, ingest_failures=ingest_failures, source_errors=source_errors,
    )


def run_document_discovery(
    triggered_by: str = "scheduler",
    *,
    job_repo: JobRunRepository | None = None,
    document_repo: DocumentRepository | None = None,
    source_repo: DocumentSourceRepository | None = None,
    review_repo: ReviewQueueRepository | None = None,
    portfolio_repo: PortfolioRepository | None = None,
    screener_adapter: ScreenerSourceAdapter | None = None,
    ir_adapter: IRWebsiteSourceAdapter | None = None,
    embedding_provider=None,
    downloader=None,
) -> dict:
    job_repo = job_repo or JobRunRepository()
    document_repo = document_repo or DocumentRepository()
    source_repo = source_repo or DocumentSourceRepository()
    review_repo = review_repo or ReviewQueueRepository()
    portfolio_repo = portfolio_repo or PortfolioRepository()
    screener_adapter = screener_adapter or ScreenerSourceAdapter()
    ir_adapter = ir_adapter or IRWebsiteSourceAdapter()
    embedding_provider = embedding_provider or get_embedding_provider()
    downloader = downloader or _default_downloader

    try:
        run = job_repo.start_run(JOB_TYPE, triggered_by, max_retries=2, timeout_seconds=60)
    except JobAlreadyRunningError as exc:
        return {"skipped": True, "reason": str(exc)}

    settings = get_settings()
    max_new_docs = settings.document_discovery_max_new_docs_per_company
    tickers = sorted(portfolio_repo.list_tickers())
    results: dict[str, dict] = {}

    try:
        for ticker in tickers:
            try:
                outcome = _discover_for_company(
                    ticker, document_repo, source_repo, review_repo, screener_adapter, ir_adapter, embedding_provider, downloader, max_new_docs,
                )
            except Exception as exc:  # noqa: BLE001 - one company's unexpected failure must not stop the rest
                logger.exception("document_discovery: unexpected error for %s", ticker)
                outcome = CompanyDiscoveryOutcome(status="failed", source_errors=[str(exc)])

            results[ticker] = {
                "status": outcome.status, "discovered": outcome.discovered, "accepted": outcome.accepted,
                "ingested": outcome.ingested, "duplicates_skipped": outcome.duplicates_skipped,
                "queued_for_review": outcome.queued_for_review, "ingest_failures": outcome.ingest_failures,
                "errors": outcome.source_errors,
            }
            job_repo.heartbeat(run.id)

        statuses = {r["status"] for r in results.values()}
        if not tickers:
            final_status, error_message = "success", None
        elif statuses <= {"success"}:
            final_status, error_message = "success", None
        elif statuses == {"failed"}:
            final_status, error_message = "failed", "All companies failed — see result_summary for per-company errors."
        else:
            final_status, error_message = "partial", "Some companies had failures or ambiguous candidates — see result_summary."

        total_ingested = sum(r["ingested"] for r in results.values())
        job_repo.complete_run(
            run.id, status=final_status, result_summary=results, error_message=error_message,
            log=f"Checked {len(tickers)} ticker(s); ingested {total_ingested} new document(s).", records_affected=total_ingested,
        )
        return {"run_id": run.id, "status": final_status, "results": results, "records_affected": total_ingested}

    except Exception as exc:  # noqa: BLE001 - must still close out the run row
        logger.exception("document_discovery: job crashed")
        job_repo.complete_run(run.id, status="failed", result_summary=results, error_message=str(exc), log="Job crashed before completing.")
        raise


__all__ = ["run_document_discovery", "JOB_TYPE", "DownloadError"]
