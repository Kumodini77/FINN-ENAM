import pytest

from app.models.announcement import AnnouncementCategory, ClassificationMethod
from app.services.classification import classify_announcement, rule_based_classify

# One representative, realistic title per category — phrased the way an actual
# NSE/BSE exchange filing title reads (several mirror real titles observed in the
# Phase 0/0B spikes, e.g. "Earnings Call Transcript", "Regulation 30 (LODR)").
SAMPLE_TITLES = [
    (AnnouncementCategory.RESULTS, "Outcome of Board Meeting - Unaudited Financial Results for the quarter ended September 30"),
    (AnnouncementCategory.MA, "Announcement under Regulation 30 - Acquisition of 51% stake in a subsidiary"),
    (AnnouncementCategory.FUND_RAISE, "Intimation of Qualified Institutional Placement (QIP) of equity shares"),
    (AnnouncementCategory.MANAGEMENT_CHANGE, "Resignation of Chief Financial Officer and appointment of new CFO"),
    (AnnouncementCategory.LITIGATION, "Receipt of show cause notice from regulatory authority"),
    (AnnouncementCategory.INSIDER_TRADING, "Disclosure under SAST Regulations - acquisition of shares by promoter"),
    (AnnouncementCategory.EARNINGS_CALL, "Transcript of the Q2 FY26 Earnings Call Conference Call"),
    (AnnouncementCategory.INVESTOR_MEETINGS, "Schedule of analyst meet and investor meeting"),
    (AnnouncementCategory.CREDIT_RATING, "CRISIL Rating Reaffirmation for long term bank facilities"),
    (AnnouncementCategory.DIVIDEND, "Intimation of Record Date for payment of dividend"),
    (AnnouncementCategory.BONUS_SPLIT, "Board approves bonus issue of equity shares in ratio 1:1"),
    (AnnouncementCategory.CAPEX, "Board approves capital expenditure for new plant capacity expansion"),
    (AnnouncementCategory.PRESS_RELEASE, "Press Release - Company announces new product launch and order win"),
    (AnnouncementCategory.POSTAL_BALLOT, "Notice of Postal Ballot for approval of shareholders"),
    (AnnouncementCategory.AGM_EGM, "Notice of Annual General Meeting (AGM) of the Company"),
    (AnnouncementCategory.PLEDGING, "Disclosure of pledge of shares by promoter group"),
]


@pytest.mark.parametrize("expected_category,title", SAMPLE_TITLES)
def test_rule_based_classification_matches_expected_category(expected_category, title):
    result = rule_based_classify(title)
    assert result.category == expected_category
    assert result.confidence >= 0.9
    assert result.evidence  # must cite what matched


def test_unrecognizable_title_falls_back_to_unclassified():
    result = rule_based_classify("ESOP allotment compliance certificate for the month")
    assert result.category == AnnouncementCategory.UNCLASSIFIED
    assert result.confidence < 0.6


def test_classify_announcement_without_llm_key_uses_rule_based_for_clear_case():
    result = classify_announcement("Intimation of Record Date for payment of dividend")
    assert result.category == AnnouncementCategory.DIVIDEND
    assert result.method == ClassificationMethod.RULE_BASED


def test_classify_announcement_without_llm_key_falls_back_cleanly_for_ambiguous_case():
    # No ANTHROPIC_API_KEY configured in the test environment -> must not raise,
    # must not require a paid call, must land on a safe fallback.
    result = classify_announcement("General intimation regarding compliance matters")
    assert result.category == AnnouncementCategory.UNCLASSIFIED
    assert result.method == ClassificationMethod.FALLBACK_UNCLASSIFIED
