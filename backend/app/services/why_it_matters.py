"""Generates the investor-facing "why it matters" line for an announcement.

Deterministic and template-based, not an LLM call — keeps Module 2 import cost-free
per filing (requirements.md explicitly asks not to require a paid call for every
filing). This text is FINN's INTERPRETATION, not a fact from the filing — the API and
frontend must always render it in a visually distinct place from `title` (the filing's
own words), never merged into the same field.
"""

from app.models.announcement import AnnouncementCategory, PriorityLevel

_TEMPLATES: dict[AnnouncementCategory, str] = {
    AnnouncementCategory.RESULTS: "Quarterly/annual results typically move the stock the most of any filing type — check the headline numbers and QoQ/YoY trend.",
    AnnouncementCategory.MA: "M&A activity can materially change the company's scale, strategy, or balance sheet risk.",
    AnnouncementCategory.MANAGEMENT_CHANGE: "A change at the top can signal a strategy shift or instability — worth checking who's coming in and why the previous person left.",
    AnnouncementCategory.FUND_RAISE: "Raising capital can dilute existing shareholders or add leverage, depending on the instrument used.",
    AnnouncementCategory.LITIGATION: "Legal/regulatory exposure can carry a financial or reputational cost not yet reflected in the numbers.",
    AnnouncementCategory.INSIDER_TRADING: "Promoter buying/selling their own shares is sometimes read as a signal of their own confidence (or lack of it).",
    AnnouncementCategory.CREDIT_RATING: "A rating change affects the company's borrowing cost and can signal a shift in perceived credit risk.",
    AnnouncementCategory.PLEDGING: "Heavy promoter share pledging is a leverage/risk signal worth monitoring over time.",
    AnnouncementCategory.DIVIDEND: "A declared dividend and its record date affect near-term shareholder cash flow.",
    AnnouncementCategory.BONUS_SPLIT: "Share count changes without cash moving — relevant to per-share metrics, not company value.",
    AnnouncementCategory.CAPEX: "New capacity spend signals a growth bet — worth tracking against stated capacity/revenue guidance.",
    AnnouncementCategory.EARNINGS_CALL: "The concall is where management's tone and forward guidance usually surface, ahead of the next quarter's numbers.",
    AnnouncementCategory.INVESTOR_MEETINGS: "Routine investor-relations activity — rarely moves the stock on its own.",
    AnnouncementCategory.AGM_EGM: "Procedural shareholder-meeting notice — relevant mainly if a specific resolution is contentious.",
    AnnouncementCategory.POSTAL_BALLOT: "Procedural shareholder vote — relevant mainly if a specific resolution is contentious.",
    AnnouncementCategory.PRESS_RELEASE: "General news — relevance varies widely; skim for anything that changes the investment thesis.",
    AnnouncementCategory.UNCLASSIFIED: "Routine or low-relevance filing — collapsed by default; expand only if you want the full list.",
}


def generate_why_it_matters(category: AnnouncementCategory, priority: PriorityLevel) -> str:
    base = _TEMPLATES.get(category, _TEMPLATES[AnnouncementCategory.UNCLASSIFIED])
    if priority == PriorityLevel.LOW and category != AnnouncementCategory.UNCLASSIFIED:
        return f"{base} (Flagged low priority here due to its age or routine nature.)"
    return base
