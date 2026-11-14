from fastapi import APIRouter

from app.repositories.announcements import AnnouncementRepository
from app.schemas.announcement_import import (
    AnnouncementImportBatchResult,
    AnnouncementImportRequest,
    AnnouncementImportResult,
)
from app.services.announcement_import import UnknownTickerError, import_announcement

router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.post("/import", response_model=AnnouncementImportResult)
def import_single(payload: AnnouncementImportRequest) -> AnnouncementImportResult:
    """Manual filing ingestion — see docs/filing-access-spike.md for why this exists
    instead of a live NSE/BSE scraper. One real, primary-source filing per call."""
    return import_announcement(payload)


@router.post("/import/batch", response_model=AnnouncementImportBatchResult)
def import_batch(payloads: list[AnnouncementImportRequest]) -> AnnouncementImportBatchResult:
    results: list[AnnouncementImportResult] = []
    errors: list[str] = []
    repo = AnnouncementRepository()

    for i, payload in enumerate(payloads):
        try:
            results.append(import_announcement(payload, repo=repo))
        except UnknownTickerError as e:
            errors.append(f"item[{i}] ({payload.ticker}): {e.message}")

    created = sum(1 for r in results if r.created)
    duplicates = sum(1 for r in results if not r.created)
    return AnnouncementImportBatchResult(
        results=results,
        created_count=created,
        duplicate_count=duplicates,
        error_count=len(errors),
        errors=errors,
    )
