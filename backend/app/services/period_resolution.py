"""Generic (non-ticker-specific) resolution of reporting-period mentions, used to
bind a specific table column to the period a question actually asked about.

Indian fiscal year convention assumed here (standard for NSE-listed companies, and
the convention HDFC's own deck uses - "Q1 FY27" = Apr-Jun 2026): FY<N> ends in March
of calendar year <N>, so a quarter is labeled by the fiscal year it falls INSIDE,
not the calendar year it starts in.
"""

import re

_QUARTER_FY_RE = re.compile(r"Q([1-4])\s*FY\s*(\d{2,4})", re.IGNORECASE)
_HALF_FY_RE = re.compile(r"H([12])\s*FY\s*(\d{2,4})", re.IGNORECASE)
_FY_ONLY_RE = re.compile(r"FY\s*(\d{2,4})(?:-\d{2,4})?", re.IGNORECASE)
# Hyphenated ("Y-o-Y") and plain ("YoY") forms both appear in real Indian
# financial decks - both are the same "delta/comparison" column kind, generic
# across any company's table, never specific to one document's formatting.
_DELTA_RE = re.compile(r"\bQ-?o-?Q\b|\bY-?o-?Y\b|\bH-?o-?H\b", re.IGNORECASE)
_PERIOD_RE_COMBINED = re.compile(
    f"({_QUARTER_FY_RE.pattern})|({_HALF_FY_RE.pattern})|({_FY_ONLY_RE.pattern})", re.IGNORECASE
)

_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_YEAR_RE = re.compile(
    r"\b(" + "|".join(_MONTH_NAMES.keys()) + r")\.?\s+(?:\d{1,2},?\s+)?(\d{4})\b", re.IGNORECASE
)

# Some decks (e.g. Wipro's) write a quarter as "Q2'27" or "Q2'27" (curly quote)
# instead of "Q2 FY27" - same meaning, different shorthand, generic across any
# company using this convention. Expanded to the canonical "Q<n> FY<yy>" form
# up front so every existing pattern/caller below works unchanged.
_QUARTER_APOSTROPHE_RE = re.compile(r"Q([1-4])\s*['’]\s*(\d{2})\b")

# Some decks (e.g. Tata Steel's) write the quarter NUMBER before the letter
# "Q" - "2QFY27" meaning "Q2 FY27" - rather than after it. A real, narrow
# convention, not company-specific (several companies use this reversed
# order). The negative lookbehind (?<!\d) stops a stray match from grabbing
# the wrong digit out of a longer number immediately before it (e.g. a
# hypothetical "12QFY27" must never be read as quarter "2").
_REVERSED_QUARTER_FY_RE = re.compile(r"(?<!\d)([1-4])Q\s*FY\s*(\d{2,4})", re.IGNORECASE)


def _expand_period_shorthand(text: str) -> str:
    text = _QUARTER_APOSTROPHE_RE.sub(r"Q\1 FY\2", text)
    text = _REVERSED_QUARTER_FY_RE.sub(r"Q\1 FY\2", text)
    return text


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
    header_line = _expand_period_shorthand(header_line)
    combined_pattern = re.compile(
        f"({_QUARTER_FY_RE.pattern})|({_HALF_FY_RE.pattern})|({_FY_ONLY_RE.pattern})|({_DELTA_RE.pattern})",
        re.IGNORECASE,
    )
    labels = []
    for match in combined_pattern.finditer(header_line):
        labels.append(_normalize(match.group(0)))
    return labels


def parse_header_columns(header_line: str) -> list[tuple[str, str]]:
    """Like extract_period_labels_from_header, but also classifies each column as
    "period" (a real reporting period - quarter, half-year, or FY) or "delta" (a
    comparison column - YoY/QoQ/HoH, however hyphenated). Used to reconcile a row
    whose value count is SHORTER than the header's: if the shortfall exactly
    equals the number of "delta" columns, those specific columns (identified by
    their own label text in the header, not guessed from the count alone) are the
    ones this row omits - see app.services.pdf_extraction's sparse-column
    reconciliation. Generic: applies to any table with this structure, not keyed
    to one document."""
    header_line = _expand_period_shorthand(header_line)
    ordered: list[tuple[str, str]] = []
    for m in re.finditer(f"({_PERIOD_RE_COMBINED.pattern})|({_DELTA_RE.pattern})", header_line, re.IGNORECASE):
        text = _normalize(m.group(0))
        kind = "delta" if _DELTA_RE.fullmatch(m.group(0).strip()) else "period"
        ordered.append((text, kind))
    return ordered


def resolve_period_mention(question: str) -> str | None:
    """Best-effort extraction of the period the question is asking about, normalized
    to the same "Q<n>FY<yy>" form extract_period_labels_from_header produces.
    Returns None if no period is mentioned (the question is period-agnostic)."""
    question = _expand_period_shorthand(question)
    direct = _QUARTER_FY_RE.search(question)
    if direct:
        quarter, fy = direct.group(1), direct.group(2)
        fy_short = fy[-2:] if len(fy) > 2 else fy
        return _normalize(f"Q{quarter}FY{fy_short}")

    half = _HALF_FY_RE.search(question)
    if half:
        half_num, fy = half.group(1), half.group(2)
        fy_short = fy[-2:] if len(fy) > 2 else fy
        return _normalize(f"H{half_num}FY{fy_short}")

    fy_only = _FY_ONLY_RE.search(question)
    if fy_only:
        fy = fy_only.group(1)
        fy_short = fy[-2:] if len(fy) > 2 else fy
        return _normalize(f"FY{fy_short}")

    month_year = _MONTH_YEAR_RE.search(question)
    if month_year:
        month = _MONTH_NAMES[month_year.group(1).lower()]
        year = int(month_year.group(2))
        quarter = _quarter_for_month(month)
        fy_end_year = _fy_end_year_for(month, year)
        return _normalize(f"Q{quarter}FY{str(fy_end_year)[-2:]}")

    return None
