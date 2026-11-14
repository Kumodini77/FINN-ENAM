"""Explainable priority scoring for announcements — requirements.md Module 4.

Formula (documented, not hidden in code):

    priority_score = category_weight * recency_decay

- category_weight: a fixed, inspectable table (below) reflecting how significant an
  announcement TYPE typically is to an investor — not an AI judgment call, not a stock
  price prediction. results/M&A/management_change/fund_raise/litigation score highest;
  routine/compliance-flavored categories (press_release, investor_meetings, agm_egm,
  postal_ballot, pledging, unclassified) score lowest.
- recency_decay: 1.0 for an announcement filed within the last 24h, decaying linearly
  to 0.4 at 7 days old, floored at 0.4 beyond that — so a week-old "routine" filing
  never outranks a same-day "results" filing, but recency still matters within a tier.

priority_score is mapped to a level via fixed thresholds:
    >= 0.65  -> high
    >= 0.35  -> medium
    else     -> low

"Portfolio relevance" (requirements.md's third factor) is intentionally a constant
1.0 multiplier here: everything the priority engine sees already passed through the
portfolio filter upstream (the digest only includes portfolio companies), so there is
no additional relevance signal to apply at this stage. If ad-hoc/non-portfolio
announcements are ever mixed into the same feed, this is the place to add a
sub-1.0 multiplier for them.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.announcement import AnnouncementCategory, PriorityLevel

CATEGORY_WEIGHTS: dict[AnnouncementCategory, float] = {
    AnnouncementCategory.RESULTS: 1.0,
    AnnouncementCategory.MA: 1.0,
    AnnouncementCategory.MANAGEMENT_CHANGE: 0.9,
    AnnouncementCategory.FUND_RAISE: 0.85,
    AnnouncementCategory.LITIGATION: 0.8,
    AnnouncementCategory.CREDIT_RATING: 0.7,
    AnnouncementCategory.INSIDER_TRADING: 0.6,
    AnnouncementCategory.PLEDGING: 0.55,
    AnnouncementCategory.DIVIDEND: 0.5,
    AnnouncementCategory.BONUS_SPLIT: 0.5,
    AnnouncementCategory.CAPEX: 0.45,
    AnnouncementCategory.EARNINGS_CALL: 0.4,
    AnnouncementCategory.INVESTOR_MEETINGS: 0.25,
    AnnouncementCategory.AGM_EGM: 0.2,
    AnnouncementCategory.POSTAL_BALLOT: 0.2,
    AnnouncementCategory.PRESS_RELEASE: 0.3,
    AnnouncementCategory.UNCLASSIFIED: 0.1,
}

_RECENCY_FULL_WINDOW_HOURS = 24
_RECENCY_DECAY_END_HOURS = 24 * 7
_RECENCY_FLOOR = 0.4

_HIGH_THRESHOLD = 0.65
_MEDIUM_THRESHOLD = 0.35


@dataclass
class PriorityResult:
    level: PriorityLevel
    score: float
    category_weight: float
    recency_decay: float
    rationale: str


def recency_decay(filed_at: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if filed_at.tzinfo is None:
        filed_at = filed_at.replace(tzinfo=timezone.utc)
    age_hours = max((now - filed_at).total_seconds() / 3600, 0)

    if age_hours <= _RECENCY_FULL_WINDOW_HOURS:
        return 1.0
    if age_hours >= _RECENCY_DECAY_END_HOURS:
        return _RECENCY_FLOOR

    span = _RECENCY_DECAY_END_HOURS - _RECENCY_FULL_WINDOW_HOURS
    progress = (age_hours - _RECENCY_FULL_WINDOW_HOURS) / span
    return 1.0 - progress * (1.0 - _RECENCY_FLOOR)


def compute_priority(category: AnnouncementCategory, filed_at: datetime, now: datetime | None = None) -> PriorityResult:
    weight = CATEGORY_WEIGHTS.get(category, CATEGORY_WEIGHTS[AnnouncementCategory.UNCLASSIFIED])
    decay = recency_decay(filed_at, now)
    score = round(weight * decay, 4)

    if score >= _HIGH_THRESHOLD:
        level = PriorityLevel.HIGH
    elif score >= _MEDIUM_THRESHOLD:
        level = PriorityLevel.MEDIUM
    else:
        level = PriorityLevel.LOW

    rationale = (
        f"category '{category.value}' weight={weight:.2f}, recency_decay={decay:.2f} "
        f"-> score={score:.2f} -> {level.value}"
    )
    return PriorityResult(level=level, score=score, category_weight=weight, recency_decay=decay, rationale=rationale)


def is_routine(category: AnnouncementCategory, level: PriorityLevel) -> bool:
    """Used by the digest to decide what collapses by default (requirements.md Module 7)."""
    return level == PriorityLevel.LOW
