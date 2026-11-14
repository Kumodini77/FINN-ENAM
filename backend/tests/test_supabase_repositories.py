"""Mocked integration tests for the Supabase branches of the three Phase 2
repositories — translation in both directions, duplicate-key handling, and
ownership scoping. Uses an in-memory FakeSupabaseClient (tests/fakes/fake_supabase.py)
so none of this touches a real database; the live round trip against the actual
Supabase project was verified separately and is not re-run here.
"""

import uuid
from datetime import date, datetime, timezone

import pytest

from app.models.announcement import (
    Alert,
    AlertTriggerType,
    Announcement,
    FinancialBasis,
    FinancialMetric,
)
from app.repositories import app_user, company_lookup
from app.repositories.alerts import AlertRepository, AlertsConfigRepository
from app.repositories.announcements import AnnouncementRepository
from app.repositories.financial_metrics import FinancialMetricRepository, _basis_value
from tests.fakes.fake_supabase import FakeSupabaseClient, patch_supabase_backend, unique_violation

RELIANCE_ID = "company-reliance"
DEMO_USER_ID = "user-demo"


@pytest.fixture(autouse=True)
def _reset_caches():
    company_lookup.invalidate_cache()
    app_user._reset_cache_for_tests()
    yield
    company_lookup.invalidate_cache()
    app_user._reset_cache_for_tests()


def _seeded_client() -> FakeSupabaseClient:
    client = FakeSupabaseClient()
    client.tables["companies"] = [{"id": RELIANCE_ID, "ticker": "RELIANCE"}]
    client.tables["users"] = [{"id": DEMO_USER_ID, "email": app_user.DEMO_USER_EMAIL}]
    return client


def _announcement(ticker="RELIANCE", url="https://example.com/a"):
    now = datetime.now(timezone.utc)
    return Announcement(
        id=str(uuid.uuid4()),
        company_ticker=ticker,
        filed_at=now,
        title="Test filing",
        original_source_url=url,
        ingested_at=now,
    )


def _metric(ticker="RELIANCE", period="Q1FY99", basis=FinancialBasis.STANDALONE, revenue=100.0):
    return FinancialMetric(
        id=str(uuid.uuid4()),
        company_ticker=ticker,
        period=period,
        basis=basis,
        revenue=revenue,
        created_at=datetime.now(timezone.utc),
    )


def _alert(ticker="RELIANCE", trigger=AlertTriggerType.PRICE_MOVE, trade_date=None, source_announcement_id=None):
    return Alert(
        id=str(uuid.uuid4()),
        company_ticker=ticker,
        trigger_type=trigger,
        trade_date=trade_date if trade_date is not None else (date(2026, 1, 1) if trigger != AlertTriggerType.MATERIAL_ANNOUNCEMENT else None),
        source_announcement_id=source_announcement_id,
        triggered_at=datetime.now(timezone.utc),
    )


# =============================================================================
# announcements: model <-> DB translation, duplicate-key handling
# =============================================================================


def test_announcement_write_translates_ticker_to_company_id_and_drops_non_columns():
    client = _seeded_client()
    with patch_supabase_backend(client):
        repo = AnnouncementRepository()
        _, created = repo.add(_announcement())
    assert created is True
    rows = client.tables["announcements"]
    assert len(rows) == 1
    assert rows[0]["company_id"] == RELIANCE_ID
    assert "company_ticker" not in rows[0]
    assert "ingested_at" not in rows[0]
    assert "extracted_text" not in rows[0]


def test_announcement_read_translates_company_id_back_to_ticker():
    client = _seeded_client()
    client.tables["announcements"] = [
        {
            "id": "ann-1",
            "company_id": RELIANCE_ID,
            "filed_at": datetime.now(timezone.utc).isoformat(),
            "title": "Existing filing",
            "category": "unclassified",
            "category_confidence": None,
            "one_line_summary": None,
            "is_material": False,
            "original_source_url": "https://example.com/existing",
            "source": "manual_seed",
            "seeded_by": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "document_url": None,
            "verification_status": "unverified",
            "why_it_matters": None,
            "priority": "low",
            "priority_score": 0.0,
            "classification_method": "manual",
            "classification_evidence": [],
        }
    ]
    with patch_supabase_backend(client):
        repo = AnnouncementRepository()
        rows = repo.list_all()
    assert len(rows) == 1
    assert rows[0].company_ticker == "RELIANCE"


def test_announcement_find_duplicate_skips_query_for_unregistered_ticker():
    client = FakeSupabaseClient()  # no companies seeded
    with patch_supabase_backend(client):
        repo = AnnouncementRepository()
        result = repo.find_duplicate("NEVERSEEDED", "https://example.com/x")
    assert result is None
    assert "announcements" not in client.tables  # never queried at all


def test_announcement_duplicate_insert_race_is_handled_gracefully():
    client = _seeded_client()
    client.raise_on_insert["announcements"] = unique_violation()
    existing_payload = _announcement(url="https://example.com/race").model_dump(mode="json")
    existing_payload.pop("company_ticker")
    existing_payload.pop("ingested_at")
    existing_payload.pop("extracted_text")
    existing_payload["company_id"] = RELIANCE_ID
    existing_payload["created_at"] = datetime.now(timezone.utc).isoformat()  # real DB rows always have this
    client.tables["announcements"] = [existing_payload]

    with patch_supabase_backend(client):
        repo = AnnouncementRepository()
        _, created = repo.add(_announcement(url="https://example.com/race"))

    assert created is False
    assert len(client.tables["announcements"]) == 1  # no second row was ever added


# =============================================================================
# financial_metrics: model <-> DB translation, basis normalization
# =============================================================================


def test_basis_value_normalizes_enum_for_postgrest_wire_serialization():
    """postgrest's .eq() calls plain str(value) on whatever isn't None/bool/dict/list
    (confirmed in the installed postgrest package). str(FinancialBasis.STANDALONE)
    is "FinancialBasis.STANDALONE", not "standalone" — _basis_value() must normalize
    before the value ever reaches .eq(), or every filtered query against a live
    database would silently match nothing."""
    assert _basis_value(FinancialBasis.STANDALONE) == "standalone"
    assert str(_basis_value(FinancialBasis.STANDALONE)) == "standalone"
    assert _basis_value("standalone") == "standalone"


def test_financial_metric_write_translates_ticker_to_company_id():
    client = _seeded_client()
    with patch_supabase_backend(client):
        repo = FinancialMetricRepository()
        _, created = repo.upsert(_metric())
    assert created is True
    rows = client.tables["financial_metrics"]
    assert len(rows) == 1
    assert rows[0]["company_id"] == RELIANCE_ID
    assert "company_ticker" not in rows[0]


def test_financial_metric_upsert_replaces_not_duplicates_on_conflict():
    client = _seeded_client()
    with patch_supabase_backend(client):
        repo = FinancialMetricRepository()
        repo.upsert(_metric(period="Q1FY99", revenue=100.0))
        _, created = repo.upsert(_metric(period="Q1FY99", revenue=200.0))
    assert created is False
    rows = client.tables["financial_metrics"]
    assert len(rows) == 1
    assert rows[0]["revenue"] == 200.0


def test_financial_metric_read_translates_company_id_back_to_ticker():
    client = _seeded_client()
    client.tables["financial_metrics"] = [
        {
            "id": str(uuid.uuid4()),
            "company_id": RELIANCE_ID,
            "announcement_id": None,
            "period": "Q1FY99",
            "period_end_date": None,
            "basis": "standalone",
            "revenue": 100.0,
            "ebitda": None,
            "pbt": None,
            "pat": None,
            "currency": "INR",
            "unit": "crore",
            "extraction_source": "manual_seed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_document_url": None,
            "source_page_number": None,
            "extraction_confidence": None,
        }
    ]
    with patch_supabase_backend(client):
        repo = FinancialMetricRepository()
        metrics = repo.list_for_ticker("RELIANCE")
    assert len(metrics) == 1
    assert metrics[0].company_ticker == "RELIANCE"


def test_financial_metric_find_existing_skips_query_for_unregistered_ticker():
    client = FakeSupabaseClient()
    with patch_supabase_backend(client):
        repo = FinancialMetricRepository()
        result = repo.find_existing("NEVERSEEDED", "Q1FY99", "standalone")
    assert result is None
    assert "financial_metrics" not in client.tables


# =============================================================================
# alerts / alerts_config: model <-> DB translation, ownership, dedup race safety
# =============================================================================


def test_alert_write_translates_ticker_and_injects_demo_user_id():
    client = _seeded_client()
    with patch_supabase_backend(client):
        repo = AlertRepository()
        _, created = repo.add(_alert())
    assert created is True
    rows = client.tables["alerts"]
    assert len(rows) == 1
    assert rows[0]["company_id"] == RELIANCE_ID
    assert rows[0]["user_id"] == DEMO_USER_ID
    assert "company_ticker" not in rows[0]


def test_alert_read_translates_company_id_back_to_ticker():
    client = _seeded_client()
    client.tables["alerts"] = [
        {
            "id": "a1",
            "company_id": RELIANCE_ID,
            "user_id": DEMO_USER_ID,
            "trigger_type": "price_move",
            "source_announcement_id": None,
            "trade_date": "2026-01-01",
            "payload": {},
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "seen_at": None,
        }
    ]
    with patch_supabase_backend(client):
        repo = AlertRepository()
        alerts = repo.list_all()
    assert len(alerts) == 1
    assert alerts[0].company_ticker == "RELIANCE"


def test_alert_listing_is_scoped_to_the_demo_user_not_global():
    client = _seeded_client()
    client.tables["alerts"] = [
        {
            "id": "a1",
            "company_id": RELIANCE_ID,
            "user_id": "some-other-user",
            "trigger_type": "price_move",
            "source_announcement_id": None,
            "trade_date": "2026-01-01",
            "payload": {},
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "seen_at": None,
        }
    ]
    with patch_supabase_backend(client):
        repo = AlertRepository()
        alerts = repo.list_all()
    assert alerts == []


def test_alert_exists_skips_query_for_unregistered_ticker():
    client = FakeSupabaseClient()
    with patch_supabase_backend(client):
        repo = AlertRepository()
        assert repo.exists("NEVERSEEDED", "price_move", date(2026, 1, 1), None) is False
    assert "alerts" not in client.tables


def test_alert_duplicate_insert_race_returns_idempotent_duplicate_result():
    client = _seeded_client()
    client.raise_on_insert["alerts"] = unique_violation()
    with patch_supabase_backend(client):
        repo = AlertRepository()
        _, created = repo.add(_alert())
    assert created is False
    assert client.tables.get("alerts", []) == []  # the failed insert left no row behind


def test_alerts_config_get_and_save_translate_default_label_to_real_user_id():
    client = _seeded_client()
    with patch_supabase_backend(client):
        repo = AlertsConfigRepository()
        cfg = repo.get()
        assert cfg.user_id == "default"  # public contract is unchanged

        cfg.volume_spike_multiple = 9.0
        repo.save(cfg)

        rows = client.tables["alerts_config"]
        assert len(rows) == 1
        assert rows[0]["user_id"] == DEMO_USER_ID  # the real uuid is what's stored

        reloaded = repo.get()
        assert reloaded.user_id == "default"
        assert reloaded.volume_spike_multiple == 9.0
