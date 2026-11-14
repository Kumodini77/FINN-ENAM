"""Generic (non-ticker-specific) resolution of reporting-period mentions, used to
bind a specific table column to the period a question actually asked about.

Indian fiscal year convention assumed here (standard for NSE-listed companies, and
the convention HDFC's own deck uses - "Q1 FY27" = Apr-Jun 2026): FY<N> ends in March
of calendar year <N>, so a quarter is labeled by the fiscal year it falls INSIDE,
not the calendar year it starts in.
"""

import re

_QUARTER_FY_RE = re.compile(r"Q([1-4])\s*FY\s*(\d{2,4})", re.IGNORECASE)
_FY_ONLY_RE = re.compile(r"FY\s*(\d{2,4})(?:-\d{2,4})?", re.IGNORECASE)
_DELTA_RE = re.compile(r"\bQoQ\b|\bYoY\b", re.IGNORECASE)

_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_YEAR_RE = re.compile(
    r"\b(" + "|".join(_MONTH_NAMES.keys()) + r")\.?\s+(?:\d{1,2},?\s+)?(\d{4})\b", re.IGNORECASE
)


def _normalize(label: str) -> str:
    return re.sub(r"\s+", "", label).upper()


def _quarter_for_month(month: int) -> int:
    return {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[month]


def _fy_end_year_for(month: int, calendar_year: int) -> int:
    # Apr-Dec of calendar_year falls inside the fiscal year ending March of
    # calendar_year + 1; Jan-Mar falls inside the fiscal year ending that same
    # calendar_year.
    return calendar_year + 1 if month >= 4 else calendar_year


def extract_period_labels_from_header(header_line: str) -> list[str]:
    """Every period-like token in a table header, IN ORDER OF APPEARANCE, e.g.
    "P&L (Rs bn) Q1 FY26 Q4 FY26 Q1 FY27 QoQ YoY" -> ["Q1FY26","Q4FY26","Q1FY27","QOQ","YOY"].
    Generic regex, not keyed to any specific document's wording."""
    combined_pattern = re.compile(
        f"({_QUARTER_FY_RE.pattern})|({_DELTA_RE.pattern})", re.IGNORECASE
    )
    labels = []
    for match in combined_pattern.finditer(header_line):
        labels.append(_normalize(match.group(0)))
    return labels


def resolve_period_mention(question: str) -> str | None:
    """Best-effort extraction of the period the question is asking about, normalized
    to the same "Q<n>FY<yy>" form extract_period_labels_from_header produces.
    Returns None if no period is mentioned (the question is period-agnostic)."""
    direct = _QUARTER_FY_RE.search(question)
    if direct:
        quarter, fy = direct.group(1), direct.group(2)
        fy_short = fy[-2:] if len(fy) > 2 else fy
        return _normalize(f"Q{quarter}FY{fy_short}")

    month_year = _MONTH_YEAR_RE.search(question)
    if month_year:
        month = _MONTH_NAMES[month_year.group(1).lower()]
        year = int(month_year.group(2))
        quarter = _quarter_for_month(month)
        fy_end_year = _fy_end_year_for(month, year)
        return _normalize(f"Q{quarter}FY{str(fy_end_year)[-2:]}")

    return None
