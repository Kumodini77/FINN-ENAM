"""Announcement classification — hybrid rule-based + optional LLM, per requirements.md
Module 3. Rule-based runs first and is free; the LLM is only consulted for genuinely
ambiguous titles, and only if an API key is configured. No filing requires a paid call.

Keyword lists are derived directly from the category definitions in
docs/requirements.md §5 / the ENAM reference doc — not invented.
"""

import logging
import re
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.models.announcement import AnnouncementCategory, ClassificationMethod

logger = logging.getLogger("finn.classification")


@dataclass
class ClassificationResult:
    category: AnnouncementCategory
    confidence: float
    method: ClassificationMethod
    evidence: list[str] = field(default_factory=list)


# Ordered: earlier entries win on a tie, so more specific categories are listed before
# more general ones (e.g. "earnings_call" before "results", since a concall notice
# often also mentions "results").
_RULES: list[tuple[AnnouncementCategory, list[str]]] = [
    (AnnouncementCategory.EARNINGS_CALL, ["earnings call", "concall", "conference call", "analyst call", "investor call", "transcript of the", "recording of the"]),
    (AnnouncementCategory.MANAGEMENT_CHANGE, ["resign", "appoint", "ceasing to be", "cessation of", "retirement of", "appointment of", "new chief", "managing director", "whole-time director", "director has resigned", "cfo", "chief financial officer", "chief executive officer"]),
    # Listed before M&A: "acquisition of shares by promoter" also contains the word
    # "acquisition", which would otherwise be caught by M&A's broader keyword first.
    (AnnouncementCategory.INSIDER_TRADING, ["insider trading", "promoter has sold", "promoter has purchased", "disclosure under sast", "sast regulations", "acquisition of shares by promoter"]),
    (AnnouncementCategory.MA, ["acquisition of a subsidiary", "acquisition of stake", "stake in a subsidiary", "merger", "amalgamation", "demerger", "joint venture", "jv agreement", "stake sale", "divest", "slump sale"]),
    (AnnouncementCategory.FUND_RAISE, ["rights issue", "qualified institutional placement", " qip", "preferential allotment", "buyback", "commercial paper", "non-convertible debenture", "ncd issue", "raise funds", "fund raising", "fund raise"]),
    (AnnouncementCategory.LITIGATION, ["lawsuit", "litigation", "court order", "tribunal", "penalty", "show cause notice", "insolvency", "nclt", "winding up", "regulatory order", "show-cause"]),
    (AnnouncementCategory.CREDIT_RATING, ["credit rating", "rating agency", "crisil", "icra", "care ratings", "rating action", "rating reaffirm", "rating upgrade", "rating downgrade"]),
    (AnnouncementCategory.DIVIDEND, ["dividend", "record date for dividend"]),
    (AnnouncementCategory.BONUS_SPLIT, ["bonus issue", "stock split", "sub-division of shares", "subdivision of equity shares"]),
    (AnnouncementCategory.CAPEX, ["capital expenditure", "capacity expansion", "new plant", "greenfield", "brownfield expansion", "capex"]),
    (AnnouncementCategory.POSTAL_BALLOT, ["postal ballot"]),
    (AnnouncementCategory.AGM_EGM, ["annual general meeting", "extraordinary general meeting", "agm notice", "egm notice", " agm ", " egm "]),
    (AnnouncementCategory.PLEDGING, ["pledge of shares", "pledged shares", "release of pledge", "invocation of pledge"]),
    (AnnouncementCategory.INVESTOR_MEETINGS, ["investor meeting", "analyst meet", "institutional investor", "investor conference"]),
    (AnnouncementCategory.RESULTS, ["quarterly results", "financial results", "board meeting", "unaudited financial", "audited financial", "results for the quarter", "annual report"]),
    (AnnouncementCategory.PRESS_RELEASE, ["press release", "order win", "new product launch", "partnership announcement", "clarification on", "media report"]),
]

_HIGH_CONFIDENCE = 0.9
_LOW_CONFIDENCE = 0.3


def rule_based_classify(title: str, extracted_text: str | None = None) -> ClassificationResult:
    haystack = f"{title} {extracted_text or ''}".lower()
    for category, keywords in _RULES:
        matched = [kw for kw in keywords if kw in haystack]
        if matched:
            return ClassificationResult(
                category=category,
                confidence=_HIGH_CONFIDENCE,
                method=ClassificationMethod.RULE_BASED,
                evidence=matched,
            )
    return ClassificationResult(
        category=AnnouncementCategory.UNCLASSIFIED,
        confidence=_LOW_CONFIDENCE,
        method=ClassificationMethod.RULE_BASED,
        evidence=[],
    )


def llm_classify(title: str, extracted_text: str | None = None) -> ClassificationResult | None:
    """Only called for ambiguous cases, and only if an API key is configured. Returns
    None (not an exception) on any failure, so a flaky/misconfigured LLM never blocks
    an import — the caller falls back to the rule-based result."""
    settings = get_settings()
    if not settings.llm_configured:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        categories = ", ".join(c.value for c in AnnouncementCategory)
        prompt = (
            "Classify this Indian stock exchange corporate announcement into exactly one of "
            f"these categories: {categories}.\n\n"
            f"Title: {title}\n"
            f"{('Excerpt: ' + extracted_text[:1000]) if extracted_text else ''}\n\n"
            "Respond with only the category name, nothing else."
        )
        response = client.messages.create(
            model="claude-haiku-5-5",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        match = re.sub(r"[^a-zA-Z_&]", "", raw)
        for category in AnnouncementCategory:
            if category.value.replace("&", "").lower() in match.lower():
                return ClassificationResult(
                    category=category,
                    confidence=0.75,
                    method=ClassificationMethod.LLM,
                    evidence=[f"llm_raw_response={raw}"],
                )
        return None
    except Exception:
        logger.exception("LLM classification failed; falling back to rule-based result")
        return None


def classify_announcement(title: str, extracted_text: str | None = None) -> ClassificationResult:
    settings = get_settings()
    rule_result = rule_based_classify(title, extracted_text)

    if rule_result.confidence >= settings.classification_llm_confidence_threshold:
        return rule_result

    llm_result = llm_classify(title, extracted_text)
    if llm_result is not None:
        return llm_result

    return ClassificationResult(
        category=AnnouncementCategory.UNCLASSIFIED,
        confidence=rule_result.confidence,
        method=ClassificationMethod.FALLBACK_UNCLASSIFIED,
        evidence=rule_result.evidence,
    )
