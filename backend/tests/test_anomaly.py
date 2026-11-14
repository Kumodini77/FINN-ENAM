from datetime import datetime, timezone

from app.models.announcement import AlertsConfig
from app.schemas.market_data import PriceQuote, SessionStatus
from app.services.anomaly import detect_anomalies


def _config(volume_multiple=2.0, price_pct=5.0):
    return AlertsConfig(volume_spike_multiple=volume_multiple, price_move_pct=price_pct, updated_at=datetime.now(timezone.utc))


def _quote(session_status=SessionStatus.CLOSED_EOD, volume_multiple=1.0, daily_change_pct=0.0, data_available=True):
    return PriceQuote(
        ticker="TEST",
        yfinance_symbol="TEST.NS",
        data_available=data_available,
        session_status=session_status,
        latest_close=100,
        daily_change_pct=daily_change_pct,
        latest_volume=1000,
        avg_volume_window_days=20,
        avg_volume=1000 / volume_multiple if volume_multiple else None,
        volume_multiple=volume_multiple,
        fetched_at=datetime.now(timezone.utc),
    )


def test_volume_spike_detected_above_threshold():
    result = detect_anomalies(_quote(volume_multiple=2.5), _config(volume_multiple=2.0))
    assert result.is_volume_spike is True
    assert result.reasons


def test_volume_spike_not_detected_below_threshold():
    result = detect_anomalies(_quote(volume_multiple=1.5), _config(volume_multiple=2.0))
    assert result.is_volume_spike is False


def test_price_move_detected_above_threshold_either_direction():
    up = detect_anomalies(_quote(daily_change_pct=6.0), _config(price_pct=5.0))
    down = detect_anomalies(_quote(daily_change_pct=-6.0), _config(price_pct=5.0))
    assert up.is_price_move is True
    assert down.is_price_move is True


def test_price_move_not_detected_within_threshold():
    result = detect_anomalies(_quote(daily_change_pct=3.0), _config(price_pct=5.0))
    assert result.is_price_move is False


def test_provisional_intraday_bar_never_triggers_anomaly_even_if_numbers_look_extreme():
    # Even an extreme-looking provisional bar must not fire — its volume isn't a
    # finished day's total (see market_data.py's verified finding on this).
    quote = _quote(session_status=SessionStatus.PROVISIONAL_INTRADAY, volume_multiple=10.0, daily_change_pct=20.0)
    result = detect_anomalies(quote, _config())
    assert result.is_volume_spike is False
    assert result.is_price_move is False
    assert result.reasons == []


def test_unavailable_data_never_triggers_anomaly():
    quote = _quote(data_available=False)
    result = detect_anomalies(quote, _config())
    assert result.is_volume_spike is False
    assert result.is_price_move is False


def test_thresholds_are_configurable():
    strict_config = _config(volume_multiple=1.2, price_pct=1.0)
    result = detect_anomalies(_quote(volume_multiple=1.3, daily_change_pct=1.5), strict_config)
    assert result.is_volume_spike is True
    assert result.is_price_move is True
