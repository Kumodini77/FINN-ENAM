from datetime import datetime, timezone

import pytest

from app.models.announcement import AnnouncementCategory, ClassificationMethod
from app.repositories.alerts import AlertRepository, AlertsConfigRepository
from app.repositories.announcements import AnnouncementRepository
from app.repositories.json_store import JsonListStore
from app.schemas.announcement_import import AnnouncementImportRequest
from app.services.announcement_import import UnknownTickerError, import_announcement


def _repo(tmp_path):
    return AnnouncementRepository(store=JsonListStore(str(tmp_path), "announcements.json"))


def _alert_repo(tmp_path):
    # Isolated so import_announcement's side-effect alert evaluation never touches
    # backend/data/alerts.json during tests — this was a real bug (test pollution)
    # until these were wired through explicitly.
    return AlertRepository(store=JsonListStore(str(tmp_path), "alerts.json"))


def _alerts_config_repo(tmp_path):
    return AlertsConfigRepository(store=JsonListStore(str(tmp_path), "alerts_config.json"))


def _import(payload, tmp_path, repo=None):
    return import_announcement(
        payload,
        repo=repo or _repo(tmp_path),
        alert_repo=_alert_repo(tmp_path),
        alerts_config_repo=_alerts_config_repo(tmp_path),
    )


def _failing_verifier(_ticker):
    """Stands in for a real yfinance lookup that can't verify the ticker — used so
    this test never depends on a live network call."""
    from app.core.exceptions import CompanyLookupError

    raise CompanyLookupError("not a real ticker")


def test_import_rejects_unknown_ticker(tmp_path):
    payload = AnnouncementImportRequest(
        ticker="NOTINREGISTRY",
        title="Some filing",
        filed_at=datetime.now(timezone.utc),
        original_source_url="https://example.com/x",
    )
    with pytest.raises(UnknownTickerError):
        import_announcement(
            payload,
            repo=_repo(tmp_path),
            alert_repo=_alert_repo(tmp_path),
            alerts_config_repo=_alerts_config_repo(tmp_path),
            resolve=_failing_verifier,
        )


def test_import_registers_a_valid_unseeded_ticker(tmp_path):
    """A ticker outside the 15+4 seed registry (e.g. WIPRO) must still be
    importable when it can be verified as a real equity — requirements.md Section 3:
    the research/Push engine must generalize beyond the chosen demo set."""

    def _wipro_verifier(_ticker):
        return {
            "name": "Wipro Limited",
            "exchange": "NSE",
            "sector": "Technology",
            "yfinance_symbol": "WIPRO.NS",
        }

    payload = AnnouncementImportRequest(
        ticker="WIPRO",
        title="Some filing",
        filed_at=datetime.now(timezone.utc),
        original_source_url="https://example.com/wipro-unseeded-test",
    )
    result = import_announcement(
        payload,
        repo=_repo(tmp_path),
        alert_repo=_alert_repo(tmp_path),
        alerts_config_repo=_alerts_config_repo(tmp_path),
        resolve=_wipro_verifier,
    )
    assert result.created is True


def test_import_classifies_and_prioritizes_a_results_filing(tmp_path):
    payload = AnnouncementImportRequest(
        ticker="RELIANCE",
        title="Outcome of Board Meeting - Unaudited Financial Results for the quarter",
        filed_at=datetime.now(timezone.utc),
        original_source_url="https://www.bseindia.com/example-results",
    )
    result = _import(payload, tmp_path)
    assert result.created is True
    assert result.category == AnnouncementCategory.RESULTS
    assert result.priority == "high"


def test_import_with_explicit_category_skips_classification(tmp_path):
    payload = AnnouncementImportRequest(
        ticker="TCS",
        title="Some ambiguous title that would otherwise be unclassified",
        filed_at=datetime.now(timezone.utc),
        original_source_url="https://www.bseindia.com/example-manual",
        category=AnnouncementCategory.DIVIDEND,
    )
    result = _import(payload, tmp_path)
    assert result.category == AnnouncementCategory.DIVIDEND


def test_duplicate_import_is_not_created_twice(tmp_path):
    repo = _repo(tmp_path)
    payload = AnnouncementImportRequest(
        ticker="INFY",
        title="Board meeting intimation",
        filed_at=datetime.now(timezone.utc),
        original_source_url="https://www.bseindia.com/dup-example",
    )
    first = _import(payload, tmp_path, repo=repo)
    second = _import(payload, tmp_path, repo=repo)
    assert first.created is True
    assert second.created is False
    assert len(repo.list_all()) == 1


def test_why_it_matters_and_title_are_separate_fields(tmp_path):
    repo = _repo(tmp_path)
    payload = AnnouncementImportRequest(
        ticker="HDFCBANK",
        title="Intimation of Record Date for payment of dividend",
        filed_at=datetime.now(timezone.utc),
        original_source_url="https://www.bseindia.com/dividend-example",
    )
    _import(payload, tmp_path, repo=repo)
    record = repo.list_all()[0]
    assert record.title != record.why_it_matters
    assert record.why_it_matters is not None
