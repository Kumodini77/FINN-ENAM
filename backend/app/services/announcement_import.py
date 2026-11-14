"""Manual filing ingestion (requirements.md Module 2).

This is the ONLY way announcements enter FINN right now — there is no live NSE/BSE
scraper (docs/filing-access-spike.md established that direct automated access is
blocked). A human curates each record from a real, primary-source filing and submits
it here; nothing in this module invents or guesses filing content.
"""

from datetime import timezone
from typing import Callable

import logging

from app.core.exceptions import CompanyLookupError, FinnError
from app.models.announcement import Announcement, ClassificationMethod
from app.repositories.alerts import AlertRepository, AlertsConfigRepository
from app.repositories.announcements import AnnouncementRepository, new_announcement_id, now_utc
from app.schemas.announcement_import import AnnouncementImportRequest, AnnouncementImportResult
from app.services.alert_evaluation import evaluate_announcement_alert
from app.services.classification import classify_announcement
from app.services.company_resolution import resolve_company
from app.services.priority import compute_priority
from app.services.why_it_matters import generate_why_it_matters

logger = logging.getLogger("finn.services.announcement_import")


class UnknownTickerError(FinnError):
    status_code = 422
    code = "unknown_ticker"


def import_announcement(
    payload: AnnouncementImportRequest,
    repo: AnnouncementRepository | None = None,
    alert_repo: AlertRepository | None = None,
    alerts_config_repo: AlertsConfigRepository | None = None,
    resolve: Callable[[str], object] | None = None,
) -> AnnouncementImportResult:
    """`resolve` is injectable purely for tests — it overrides how an unseeded
    ticker's metadata gets verified, so exercising that path never needs a real
    network call unless a test wants one. Production code never passes it."""
    try:
        company = resolve_company(payload.ticker, verify=resolve)
    except CompanyLookupError as e:
        raise UnknownTickerError(
            f"'{payload.ticker}' is not in the company registry (GET /api/companies) "
            f"and could not be verified as a real, currently-listed equity ({e.message}). "
            "Check for a typo, or add it manually if you believe this is wrong."
        )

    filed_at = payload.filed_at
    if filed_at.tzinfo is None:
        filed_at = filed_at.replace(tzinfo=timezone.utc)

    if payload.category is not None:
        category = payload.category
        confidence = 1.0
        method = ClassificationMethod.MANUAL
        evidence: list[str] = ["category supplied directly at import time"]
    else:
        result = classify_announcement(payload.title, payload.extracted_text)
        category = result.category
        confidence = result.confidence
        method = result.method
        evidence = result.evidence

    priority_result = compute_priority(category, filed_at)

    # one_line_summary, when present, is a literal excerpt of the filing's own text
    # (never model-generated) — kept short enough to scan in a digest card.
    one_line_summary = (payload.extracted_text or "").strip()[:200] or None

    announcement = Announcement(
        id=new_announcement_id(),
        company_ticker=company.ticker,
        filed_at=filed_at,
        title=payload.title,
        category=category,
        category_confidence=confidence,
        classification_method=method,
        classification_evidence=evidence,
        priority=priority_result.level,
        priority_score=priority_result.score,
        why_it_matters=generate_why_it_matters(category, priority_result.level),
        one_line_summary=one_line_summary,
        is_material=priority_result.level.value in ("high", "medium"),
        original_source_url=payload.original_source_url,
        document_url=payload.document_url,
        extracted_text=payload.extracted_text,
        source=payload.source,
        verification_status=payload.verification_status,
        seeded_by=payload.seeded_by,
        ingested_at=now_utc(),
    )

    repo = repo or AnnouncementRepository()
    record, created = repo.add(announcement)

    if created:
        try:
            config = (alerts_config_repo or AlertsConfigRepository()).get()
            evaluate_announcement_alert(record, config, repo=alert_repo or AlertRepository())
        except Exception:
            # Alert evaluation must never block a successful import.
            logger.exception("Alert evaluation failed during announcement import for %s", record.id)

    return AnnouncementImportResult(
        announcement_id=record.id,
        created=created,
        category=record.category,
        priority=record.priority.value,
        priority_score=record.priority_score,
        message="Imported." if created else "Duplicate of an existing record (same company + source URL) — not re-inserted.",
    )
