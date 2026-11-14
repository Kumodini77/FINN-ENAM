"""Reusable research entry points connecting Push (events) to Pull
(/api/research/ask) - deliberately a small fixed menu, not a free-form agent.

Pull is deterministic retrieval + extraction (see app.api.research's
generation_note) - every suggested question here is phrased as something that
genuine retrieved evidence can answer, never as a request for synthesis Pull
can't actually perform.
"""

from app.models.announcement import AnnouncementCategory

_RESULTS_FAMILY = {AnnouncementCategory.RESULTS, AnnouncementCategory.EARNINGS_CALL}

_CATEGORY_QUESTIONS: dict[AnnouncementCategory, str] = {
    AnnouncementCategory.CREDIT_RATING: "Explain the rating change, its stated rationale, and its implications based on the available company disclosure.",
    AnnouncementCategory.MANAGEMENT_CHANGE: "Explain the recent management change and any reasons the company has disclosed.",
    AnnouncementCategory.LITIGATION: "Explain the litigation or regulatory matter and its disclosed financial or reputational implications.",
    AnnouncementCategory.FUND_RAISE: "Explain the fund-raise, the instrument used, and its disclosed impact on the capital structure.",
    AnnouncementCategory.CAPEX: "Explain the capital expenditure plan and its disclosed scale, timeline, and funding.",
    AnnouncementCategory.MA: "Explain the M&A transaction and its disclosed strategic and financial rationale.",
}


def suggested_question_for_event(event_category: AnnouncementCategory, reporting_period: str | None) -> str:
    if event_category in _RESULTS_FAMILY:
        period_clause = f" for {reporting_period}" if reporting_period else ""
        return (
            f"Compare the latest reported revenue, profitability and key financial metrics{period_clause} "
            "with the previous quarter and the corresponding quarter last year."
        )
    return _CATEGORY_QUESTIONS.get(
        event_category, "Summarize this announcement using the company's own available documents."
    )


# Reusable prompts surfaced on the Research page itself (requirement 8) - a small
# fixed menu, ticker filled in by the caller. `needs_supporting_documents` is
# informational only (the frontend can show a note); the backend already returns
# an honest insufficient_evidence response if the needed document type doesn't exist.
REUSABLE_RESEARCH_PROMPTS = [
    {
        "label": "Review latest quarterly results",
        "question_template": "Summarize the latest reported revenue, profitability and key financial metrics.",
        "needs_supporting_documents": False,
    },
    {
        "label": "Compare financial performance with previous periods",
        "question_template": "Compare the latest reported revenue, profitability and key financial metrics with the previous quarter and the corresponding quarter last year.",
        "needs_supporting_documents": False,
    },
    {
        "label": "Examine cash-flow quality",
        "question_template": "What does the available disclosure show about operating cash flow relative to reported profit?",
        "needs_supporting_documents": False,
    },
    {
        "label": "Explain a recent material announcement",
        "question_template": "Explain the company's most recent material announcement and its disclosed implications.",
        "needs_supporting_documents": False,
    },
    {
        "label": "Find risks or unusual financial movements",
        "question_template": "What risks or unusual financial movements are disclosed in the available documents?",
        "needs_supporting_documents": False,
    },
    {
        "label": "Review management guidance",
        "question_template": "What guidance or forward-looking outlook has management disclosed, and how does it compare with actual results?",
        "needs_supporting_documents": True,
    },
]
