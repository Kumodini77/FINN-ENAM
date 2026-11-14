"""Rule-based query-intent classification for Pull questions (no LLM - deterministic
and free, consistent with how app.services.classification's rule tier works for
Push). A question can match more than one intent; retrieval uses the full set to
decide what to weight (e.g. NUMERICAL boosts table_row_group chunks and exact
metric-alias matches; GUIDANCE boosts chunks containing forward-looking language).

Generalizes to any company/question - every rule here is about question PHRASING,
never a specific ticker or document.
"""

from enum import Enum

from app.services.metric_aliases import canonical_metrics_for_text


class QueryIntent(str, Enum):
    NUMERICAL = "numerical_financial"
    TREND_COMPARISON = "trend_comparison"
    GUIDANCE = "management_guidance"
    STRATEGY = "business_strategy"
    RISK = "risk"
    SEGMENT_KPI = "segment_operational_kpi"
    PEER_COMPARISON = "peer_sector_comparison"


_NUMERICAL_MARKERS = ["what was", "what is", "how much", "figure", "value", "number", "amount"]
_TREND_MARKERS = ["qoq", "yoy", "quarter over quarter", "year over year", "change in", "trend", "growth", "decline", "increase", "decrease", "compare", "comparison", "versus", " vs "]
_GUIDANCE_MARKERS = ["guidance", "outlook", "target", "expect", "forecast", "management said", "commitment", "plan to", "going forward"]
_STRATEGY_MARKERS = ["strategy", "why did", "why has", "why is", "reason for", "driver", "business model", "expansion plan"]
_RISK_MARKERS = ["risk", "concern", "exposure", "litigation", "regulatory", "headwind", "challenge"]
_SEGMENT_MARKERS = ["segment", "kpi", "operational metric", "volume", "capacity utilization", "same-store", "unit economics"]
_PEER_MARKERS = ["peer", "competitor", "versus its peers", "industry average", "sector", "compared to other"]


def classify_query_intent(question: str) -> set[QueryIntent]:
    text = question.lower()
    intents: set[QueryIntent] = set()

    has_metric_mention = bool(canonical_metrics_for_text(question))
    if has_metric_mention and any(m in text for m in _NUMERICAL_MARKERS):
        intents.add(QueryIntent.NUMERICAL)
    if any(m in text for m in _TREND_MARKERS):
        intents.add(QueryIntent.TREND_COMPARISON)
    if any(m in text for m in _GUIDANCE_MARKERS):
        intents.add(QueryIntent.GUIDANCE)
    if any(m in text for m in _STRATEGY_MARKERS):
        intents.add(QueryIntent.STRATEGY)
    if any(m in text for m in _RISK_MARKERS):
        intents.add(QueryIntent.RISK)
    if any(m in text for m in _SEGMENT_MARKERS):
        intents.add(QueryIntent.SEGMENT_KPI)
    if any(m in text for m in _PEER_MARKERS):
        intents.add(QueryIntent.PEER_COMPARISON)

    # A bare metric mention with no other marker ("net interest income Q1 FY27")
    # is still a numerical lookup, not an unclassified question.
    if not intents and has_metric_mention:
        intents.add(QueryIntent.NUMERICAL)

    return intents
