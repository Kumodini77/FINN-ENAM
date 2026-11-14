"""Market anomaly detection (requirements.md Module 6) — built ON TOP of
app/services/market_data.py's PriceQuote, without modifying that module (it already
has its own Phase 1 test coverage and is working).

Anomaly checks only ever run against CLOSED_EOD bars. A provisional/in-session bar's
volume is a partial-day snapshot (see market_data.py's own docstring, verified against
live data in Phase 1) — comparing it to a full-day average would produce false
positives, so provisional quotes never trigger an anomaly here, no matter how their
numbers look.
"""

from dataclasses import dataclass

from app.models.announcement import AlertsConfig
from app.schemas.market_data import PriceQuote, SessionStatus


@dataclass
class AnomalyResult:
    is_volume_spike: bool
    is_price_move: bool
    reasons: list[str]


def detect_anomalies(quote: PriceQuote, config: AlertsConfig) -> AnomalyResult:
    reasons: list[str] = []

    if not quote.data_available or quote.session_status != SessionStatus.CLOSED_EOD:
        # Covers: no data, AND provisional/in-session bars — both are excluded from
        # final anomaly calculations by design (see module docstring).
        return AnomalyResult(is_volume_spike=False, is_price_move=False, reasons=[])

    is_volume_spike = quote.volume_multiple is not None and quote.volume_multiple >= config.volume_spike_multiple
    if is_volume_spike:
        reasons.append(
            f"volume {quote.volume_multiple:.2f}x its {quote.avg_volume_window_days}-day average "
            f"(threshold: {config.volume_spike_multiple}x)"
        )

    is_price_move = quote.daily_change_pct is not None and abs(quote.daily_change_pct) >= config.price_move_pct
    if is_price_move:
        reasons.append(f"price moved {quote.daily_change_pct:+.2f}% today (threshold: ±{config.price_move_pct}%)")

    return AnomalyResult(is_volume_spike=is_volume_spike, is_price_move=is_price_move, reasons=reasons)
