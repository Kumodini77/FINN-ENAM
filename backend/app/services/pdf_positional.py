"""Position-aware (word-coordinate) table header reconstruction - Phase 8.

Generalises to ANY document using this structure, not keyed to any specific
company. Built because Phase 7 proved the plain-text extraction
(app.services.pdf_extraction, which uses page.extract_text()) genuinely cannot
recover which columns a merged header phrase ("Quarter ended") spans, since
plain text discards word positions. pdfplumber (already the library in use)
exposes word-level bounding boxes via page.extract_words() - this module uses
those coordinates to do what text alone cannot.

CORE ALGORITHM (validated against two real, deliberately difficult documents -
L&T's 6-column "Quarter ended / Six months ended / Year ended" spelled-out
merged header, and ICICI Bank's 7-column "Q2- / H1- / Q1- ..." dash-shorthand
header with a standalone full-year column and mismatched line-to-line token
counts):

1. The DATA ROW's own numeric-value x-positions are the ground-truth column
   anchors (never guessed: the row that must be bound IS the row that defines
   the columns).
2. Each header line's words are clustered into GROUPS by recognized
   structural pattern (a period-length phrase, a date, a bare year, a
   review-status annotation) - not by a generic horizontal-gap threshold,
   which a real finding proved unsafe (two adjacent date-columns can sit
   closer together than two words within one phrase elsewhere on the same
   page).
3. For each anchor, the nearest GROUP (by horizontal center distance) is its
   candidate label on that line - letting one merged phrase answer for every
   anchor it genuinely spans, each independently nearest-matched.
4. Two real, opposite failure modes were found and both are guarded against:
   - A genuine merged span (L&T) puts anchors at very different relative
     distances from the SAME group, which a naive "distance ratio" check
     would have rejected as excessive - solved by checking whether the
     anchor count divides evenly by the candidate-group count (>1 group):
     an even split is the structural signature of uniform spanning, so
     every anchor keeps its nearest group.
   - A standalone column with NO label on a given line (ICICI's full-year
     column, which has no quarter/half prefix at all on the shorthand line)
     will otherwise borrow a neighbouring column's nearest group - solved,
     for the uneven-split case, by comparing each claim's distance against
     the BEST distance any anchor achieves to that same group, and
     dropping claims many times worse (a rival anchor's rightful group
     being wrongly borrowed, not a real shared span).
5. Groups assigned to the SAME anchor, across multiple header lines, are
   joined in top-to-bottom order into that column's full label text, then
   resolved to a period via a phrase/shorthand-aware resolver that picks the
   period LENGTH from the phrase or shorthand itself (never from column
   count) and the specific period from the date or year.

If an anchor's combined label doesn't resolve (e.g. a delta/growth column,
correctly never mistaken for a period) the column is left unresolved (None) -
callers must treat this as a reason to keep the existing table_unparsed /
evidence_digest fallback, never to guess.

STAGE: this module is a validated, standalone Stage 1 prototype (Phase 8). It
is NOT yet wired into app.services.pdf_extraction's ingestion pipeline - see
the Phase 8 report for the Stage 2 integration this still requires and why it
was deliberately deferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pdfplumber

from app.services.period_resolution import _MONTH_NAMES, _fy_end_year_for, _quarter_for_month

_LABEL_COLUMN_MARGIN = 0.5  # fraction of the first inter-anchor gap treated as "left of column 1"
_DATE_RE = re.compile(
    r"\b(" + "|".join(_MONTH_NAMES.keys()) + r")\.?\s+(\d{1,2}),?\s*(\d{4})?\b", re.IGNORECASE
)


@dataclass(frozen=True)
class WordBox:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2


def extract_page_words(pdf_path: str, page_number: int) -> list[WordBox]:
    """`page_number` is 1-indexed, matching app.services.pdf_extraction's convention."""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_number - 1]
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    return [WordBox(w["text"], w["x0"], w["x1"], w["top"], w["bottom"]) for w in words]


def group_words_into_lines(words: list[WordBox], tolerance: float = 3.0) -> list[list[WordBox]]:
    """Groups words into physical lines by vertical (`top`) proximity, not text
    order. `tolerance` points is generous enough for normal font-size jitter
    within one printed line but far smaller than the gap between two actual
    lines in these documents (typically >=10pt)."""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w.top, w.x0))
    lines: list[list[WordBox]] = [[ordered[0]]]
    for w in ordered[1:]:
        if abs(w.top - lines[-1][-1].top) <= tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w.x0)
    return lines


@dataclass(frozen=True)
class WordGroup:
    text: str
    center_x: float


# The bounded, generic vocabulary SEBI LODR Regulation 33 (and equivalent
# investor-presentation conventions) uses for a period-LENGTH header phrase -
# not a company-specific list, a regulatory/reporting-convention one. A
# horizontal-gap heuristic was tried first and rejected: real inter-column
# gaps (e.g. two adjacent "September 30," date columns, ~7pt apart) can be
# SMALLER than the gap between words inside one phrase elsewhere on the same
# page, so a single fixed threshold cannot safely tell "same phrase" from
# "adjacent column" in every document. Recognized-pattern matching (this
# phrase vocabulary, a date regex, a bare-year regex, a bracket/plain
# review-status regex) is used instead, so each group's identity comes from
# what it structurally IS, not how close it happens to sit to its neighbour.
_PERIOD_PHRASE_RE = re.compile(
    r"\b(quarter|three months|six months|half year|nine months|year)\s+ended\b", re.IGNORECASE
)
_BARE_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
_REVIEW_STATUS_RE = re.compile(r"\[?\b(reviewed|audited|unaudited)\b\]?", re.IGNORECASE)
_GROUP_PATTERNS = (_PERIOD_PHRASE_RE, _DATE_RE, _BARE_YEAR_RE, _REVIEW_STATUS_RE)


def _cluster_line_into_groups(line: list[WordBox]) -> list[WordGroup]:
    """Finds every recognized structural pattern (period-length phrase, date,
    bare year, review-status annotation) in this line's joined text and turns
    each match into one WordGroup spanning exactly the words that matched -
    never a generic gap-based guess. Any word matched by nothing becomes its
    own single-word group (nothing is silently dropped)."""
    if not line:
        return []
    text = " ".join(w.text for w in line)
    # char offset -> word index, so a regex match's span maps back to words
    offsets: list[int] = []
    pos = 0
    for w in line:
        offsets.append(pos)
        pos += len(w.text) + 1  # +1 for the joining space

    matches: list[tuple[int, int]] = []  # (start, end) char spans, non-overlapping
    for pattern in _GROUP_PATTERNS:
        for m in pattern.finditer(text):
            if not any(s < m.end() and m.start() < e for s, e in matches):
                matches.append((m.start(), m.end()))
    matches.sort()

    def _word_index_for_char(pos: int) -> int:
        # Clamps a char offset that lands in the joining space between two
        # words (a regex match can end exactly there, e.g. trailing "\s*"
        # with no following digit) to the nearest word that contains it.
        best = 0
        for i, off in enumerate(offsets):
            if off <= pos:
                best = i
            else:
                break
        return best

    def word_range_for_span(start: int, end: int) -> tuple[int, int]:
        return _word_index_for_char(start), _word_index_for_char(end - 1)

    groups: list[WordGroup] = []
    covered = [False] * len(line)
    for start, end in matches:
        first, last = word_range_for_span(start, end)
        words = line[first : last + 1]
        groups.append(WordGroup(text=text[start:end], center_x=(words[0].x0 + words[-1].x1) / 2))
        for i in range(first, last + 1):
            covered[i] = True
    for i, w in enumerate(line):
        if not covered[i]:
            groups.append(WordGroup(text=w.text, center_x=w.center_x))
    groups.sort(key=lambda g: g.center_x)
    return groups


def _min_x_for_label_region(anchors: list[float]) -> float:
    gap = (anchors[1] - anchors[0]) if len(anchors) > 1 else 40
    return anchors[0] - _LABEL_COLUMN_MARGIN * gap


_RIVAL_CLAIM_FACTOR = 4.0


def assign_words_to_anchors(line: list[WordBox], anchors: list[float]) -> dict[int, list[WordBox]]:
    """For EACH anchor (data column), finds the nearest PHRASE GROUP on this
    header line and assigns it to that anchor - never the reverse (nearest
    anchor per word), which would let a single merged phrase bind to only one
    of the several columns it visually spans. Multiple anchors legitimately
    sharing the same nearest group IS the correct, intended outcome for a
    genuinely merged header (L&T's "Quarter ended" validly spans 3 anchors
    this way, confirmed against the real document).

    Real finding this guards against (ICICI Bank's P&L, which has a
    standalone full-year column with no quarter/half phrase on this line at
    all): a group can also be the WEAK, spurious "nearest" for an anchor it
    doesn't really belong to, while being the clear, close match for a
    different, rival anchor. Distinguishing a genuine shared span from a
    spurious borrow can't use a single global distance cutoff (a real span
    can legitimately sit much farther from a far-flung member than a
    spurious match sits from its false claimant) - instead, for each group,
    every claiming anchor's distance is compared to the BEST (smallest)
    distance any anchor achieves to that SAME group. A claim many times
    worse than that best is a rival anchor's rightful group being wrongly
    borrowed, not a real shared span, and is dropped."""
    groups = _cluster_line_into_groups(line)
    assignment: dict[int, list[WordBox]] = {i: [] for i in range(len(anchors))}
    if not groups:
        return assignment
    min_x = _min_x_for_label_region(anchors)
    candidates = [g for g in groups if g.center_x >= min_x]
    if not candidates:
        return assignment

    nearest_per_anchor = [min(candidates, key=lambda g: abs(g.center_x - a)) for a in anchors]
    distances = [abs(nearest_per_anchor[i].center_x - a) for i, a in enumerate(anchors)]

    # Real finding: relative-distance alone cannot tell "a group genuinely
    # spans several anchors" (L&T's "Quarter ended" validly spans 3, each a
    # different multiple of the nearest member's distance) apart from "one
    # anchor's label is simply missing on this line and borrows its
    # neighbour's" (ICICI's standalone full-year column) - both produce the
    # SAME relative-distance signature. What DOES distinguish them: when
    # every anchor divides evenly into equal-sized groups of columns per
    # label (6 anchors / 3 groups = exactly 2 each), that is the structural
    # signature of genuine uniform spanning; an uneven ratio (7 anchors / 6
    # groups) means at least one anchor has no real label here, not that
    # groups spill unevenly across neighbours - so only in the uneven case is
    # the rival-claim distance check applied.
    uniform_spanning = len(candidates) > 1 and len(anchors) % len(candidates) == 0
    if uniform_spanning:
        for i, anchor in enumerate(anchors):
            assignment[i] = [WordBox(nearest_per_anchor[i].text, 0, 0, 0, 0)]
        return assignment

    best_distance_per_group: dict[int, float] = {}
    for g, d in zip(nearest_per_anchor, distances):
        key = id(g)
        best_distance_per_group[key] = min(best_distance_per_group.get(key, d), d)

    for i, anchor in enumerate(anchors):
        nearest, d = nearest_per_anchor[i], distances[i]
        best_for_group = best_distance_per_group[id(nearest)]
        if d <= max(best_for_group * _RIVAL_CLAIM_FACTOR, 1.0):
            assignment[i] = [WordBox(nearest.text, 0, 0, 0, 0)]
    return assignment


_QUARTER_DASH_RE = re.compile(r"\bQ([1-4])-")
_HALF_DASH_RE = re.compile(r"\bH([12])-")
_BARE_FY_RE = re.compile(r"\b(19|20)\d{2}\b")


def _resolve_period_for_column(phrase_and_date_text: str) -> str | None:
    """Resolves a column's combined header text to a period label, using the
    PHRASE/SHORTHAND to pick the period LENGTH and the date/year to pick the
    specific period - never guessing the length from column count.

    Two real header conventions are supported, found on two different
    genuine documents:
    1. Spelled-out: "Quarter ended September 30, 2026" (L&T) - phrase word
       ("quarter"/"half"/"year") + a month-name date.
    2. Dash-shorthand: "Q2- 2026" / "H1- 2026" (ICICI Bank) - the quarter or
       half NUMBER is already explicit, so no month-name lookup is needed; a
       bare year with NEITHER shorthand present (ICICI's standalone "FY2026"
       full-year column) resolves directly to that FY."""
    text_lower = phrase_and_date_text.lower()

    quarter_dash = _QUARTER_DASH_RE.search(phrase_and_date_text)
    half_dash = _HALF_DASH_RE.search(phrase_and_date_text)
    if quarter_dash or half_dash:
        year_match = _BARE_FY_RE.search(phrase_and_date_text)
        if not year_match:
            return None
        year = int(year_match.group(0))
        if quarter_dash:
            return f"Q{quarter_dash.group(1)}FY{str(year)[-2:]}"
        return f"H{half_dash.group(1)}FY{str(year)[-2:]}"

    date_match = _DATE_RE.search(phrase_and_date_text)
    if date_match:
        month = _MONTH_NAMES[date_match.group(1).lower()]
        year_str = date_match.group(3)
        if year_str:
            year = int(year_str)
            fy_end_year = _fy_end_year_for(month, year)
            fy_short = str(fy_end_year)[-2:]
            if "quarter" in text_lower:
                q = _quarter_for_month(month)
                return f"Q{q}FY{fy_short}"
            if "half" in text_lower or "six month" in text_lower or "6 month" in text_lower:
                h = 1 if month in (4, 5, 6, 7, 8, 9) else 2
                return f"H{h}FY{fy_short}"
            if "year" in text_lower:
                return f"FY{fy_short}"
        return None

    # No quarter/half shorthand, no phrase+date - a BARE year alone (e.g.
    # ICICI's standalone "FY2026" full-year column) means that fiscal year,
    # but ONLY when nothing else on this column's label suggests otherwise
    # (no "quarter"/"half"/"month" word that would mean a month-name date was
    # expected but missing - safer to return None than guess in that case).
    if not any(w in text_lower for w in ("quarter", "half", "month")):
        bare_year = _BARE_FY_RE.search(phrase_and_date_text)
        if bare_year:
            return f"FY{bare_year.group(0)[-2:]}"
    return None


_POSITIONAL_DELTA_RE = re.compile(r"\bQ-?o-?Q\b|\bY-?o-?Y\b|\bH-?o-?H\b|\bgrowth\b", re.IGNORECASE)


def reconstruct_column_periods(
    header_lines: list[list[WordBox]], anchors: list[float]
) -> list[str | None]:
    """`header_lines` are candidate header lines (word-grouped, in top-to-bottom
    order) ABOVE a data row whose numeric-value x-centers are `anchors`.
    Returns one period label (or None if unresolved) per anchor - never a
    guess, only ever a label this function could actually justify from the
    combined, positionally-assigned text."""
    combined: list[list[str]] = [[] for _ in anchors]
    for line in header_lines:
        assignment = assign_words_to_anchors(line, anchors)
        for idx, words in assignment.items():
            if words:
                combined[idx].append(" ".join(w.text for w in words))
    results: list[str | None] = []
    for parts in combined:
        text = " ".join(parts)
        results.append(_resolve_period_for_column(text))
    return results


def reconstruct_column_kinds(
    header_lines: list[list[WordBox]], anchors: list[float]
) -> list[tuple[str, str] | None]:
    """Like reconstruct_column_periods, but a column recognized as a DELTA
    (QoQ/YoY/growth - never a reporting period, see
    app.services.period_resolution's own _DELTA_RE) is reported as such
    explicitly, rather than indistinguishable from a genuinely unresolved
    column. Returns, per anchor, either ("period", label), ("delta", label),
    or None (truly unresolved - callers must treat this as reason to reject
    the whole table, never partially fill it in)."""
    combined: list[list[str]] = [[] for _ in anchors]
    for line in header_lines:
        assignment = assign_words_to_anchors(line, anchors)
        for idx, words in assignment.items():
            if words:
                combined[idx].append(" ".join(w.text for w in words))
    results: list[tuple[str, str] | None] = []
    for parts in combined:
        text = " ".join(parts)
        period = _resolve_period_for_column(text)
        if period is not None:
            results.append(("period", period))
        elif (delta_match := _POSITIONAL_DELTA_RE.search(text)) is not None:
            # A clean, canonical placeholder - never the raw combined text,
            # which can carry stray unrelated words (a real finding: a unit
            # annotation line with no pattern of its own can still get swept
            # in as an ungrouped word) that would corrupt the "label=value"
            # format every downstream consumer of column_labels assumes.
            canonical = re.sub(r"[^A-Za-z]", "", delta_match.group(0)).upper() or "DELTA"
            results.append(("delta", canonical))
        else:
            results.append(None)
    return results
