from datetime import date, datetime, timezone

from app.models.announcement import AlertsConfig, Announcement, AnnouncementCategory, PriorityLevel
from app.repositories.alerts import AlertRepository
from app.repositories.json_store import JsonListStore
from app.schemas.market_data import PriceQuote, SessionStatus
from app.services.alert_evaluation import evaluate_announcement_alert, evaluate_market_alert


def _repo(tmp_path):
    return AlertRepository(store=JsonListStore(str(tmp_path), "alerts.json"))


def _config(**overrides):
    base = dict(volume_spike_multiple=2.0, price_move_pct=5.0, updated_at=datetime.now(timezone.utc))
    base.update(overrides)
    return AlertsConfig(**base)


def _quote(volume_multiple=2.5, daily_change_pct=1.0, as_of_date=date(2026, 11, 13)):
    return PriceQuote(
        ticker="RELIANCE",
        yfinance_symbol="RELIANCE.NS",
        data_available=True,
        as_of_date=as_of_date,
        session_status=SessionStatus.CLOSED_EOD,
        latest_close=100,
        daily_change_pct=daily_change_pct,
        latest_volume=1000,
        avg_volume_window_days=20,
        avg_volume=400,
        volume_multiple=volume_multiple,
        fetched_at=datetime.now(timezone.utc),
    )


def test_volume_spike_creates_an_alert(tmp_path):
    repo = _repo(tmp_path)
    alerts = evaluate_market_alert(_quote(volume_multiple=3.0), _config(), repo=repo)
    assert len(alerts) == 1
    assert alerts[0].trigger_type.value == "volume_spike"


def test_same_company_date_type_is_not_alerted_twice(tmp_path):
    repo = _repo(tmp_path)
    evaluate_market_alert(_quote(volume_multiple=3.0), _config(), repo=repo)
    second_run = evaluate_market_alert(_quote(volume_multiple=3.5), _config(), repo=repo)  # re-evaluated later same day
    assert second_run == []
    assert len(repo.list_all()) == 1


def test_different_trading_date_creates_a_new_alert(tmp_path):
    repo = _repo(tmp_path)
    evaluate_market_alert(_quote(volume_multiple=3.0, as_of_date=date(2026, 11, 13)), _config(), repo=repo)
    next_day = evaluate_market_alert(_quote(volume_multiple=3.0, as_of_date=date(2026, 11, 14)), _config(), repo=repo)
    assert len(next_day) == 1
    assert len(repo.list_all()) == 2


def test_no_alert_below_threshold(tmp_path):
    repo = _repo(tmp_path)
    alerts = evaluate_market_alert(_quote(volume_multiple=1.1, daily_change_pct=0.5), _config(), repo=repo)
    assert alerts == []


def test_announcement_alert_only_for_configured_categories(tmp_path):
    repo = _repo(tmp_path)
    announcement = Announcement(
        id="ann-1",
        company_ticker="RELIANCE",
        filed_at=datetime.now(timezone.utc),
        title="Dividend declared",
        category=AnnouncementCategory.DIVIDEND,
        priority=PriorityLevel.MEDIUM,
        is_material=True,
        original_source_url="https://example.com/x",
        ingested_at=datetime.now(timezone.utc),
    )
    config = _config(alert_categories=[AnnouncementCategory.RESULTS])  # dividend not selected
    alert = evaluate_announcement_alert(announcement, config, repo=repo)
    assert alert is None


def test_announcement_alert_fires_for_configured_material_category(tmp_path):
    repo = _repo(tmp_path)
    announcement = Announcement(
        id="ann-2",
        company_ticker="RELIANCE",
        filed_at=datetime.now(timezone.utc),
        title="Results announced",
        category=AnnouncementCategory.RESULTS,
        priority=PriorityLevel.HIGH,
        is_material=True,
        original_source_url="https://example.com/y",
        ingested_at=datetime.now(timezone.utc),
    )
    config = _config(alert_categories=[AnnouncementCategory.RESULTS])
    alert = evaluate_announcement_alert(announcement, config, repo=repo)
    assert alert is not None
    assert alert.trigger_type.value == "material_announcement"


def test_announcement_alert_does_not_duplicate_for_same_source(tmp_path):
    repo = _repo(tmp_path)
    announcement = Announcement(
        id="ann-3",
        company_ticker="RELIANCE",
        filed_at=datetime.now(timezone.utc),
        title="Results announced",
        category=AnnouncementCategory.RESULTS,
        priority=PriorityLevel.HIGH,
        is_material=True,
        original_source_url="https://example.com/z",
        ingested_at=datetime.now(timezone.utc),
    )
    config = _config(alert_categories=[AnnouncementCategory.RESULTS])
    first = evaluate_announcement_alert(announcement, config, repo=repo)
    second = evaluate_announcement_alert(announcement, config, repo=repo)
    assert first is not None
    assert second is None
