"""Deterministic (non-LLM) extraction of a single reported figure from a
table_row_group chunk, for NUMERICAL-intent Pull questions.

No generation model is involved - this is pattern matching over already-extracted,
already-cited table text, never an invented number. If the metric or period can't be
confidently bound to exactly one value, this returns None rather than guessing, and
the caller must fall back to an "insufficient evidence" / "ambiguous" response
instead of fabricating a figure.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.services.metric_aliases import canonical_metrics_for_text, normalize_label
from app.services.period_resolution import extract_period_labels_from_header, resolve_period_mention
from app.services.unit_scale import extract_unit_scale_from_header

# A row rendered by app.services.chunking._format_row for a table with
# optional/sparse columns carries its OWN column label on every value
# ("Q2FY27=80.8%"), rather than relying on positional alignment against the
# full header - this row may have fewer values than the header has columns,
# so positional zip() would silently mis-bind. Detected generically by shape,
# not tied to any specific table/company.
_LABELED_VALUE_RE = re.compile(r"^[A-Za-z0-9\-]+=.+$")

# A plain numeric token, optionally Indian/international-comma-grouped, negative
# (leading "-" or accounting-style parentheses), but NOT a percentage (its scale
# is "%", not the header's unit_scale, so normalizing it the same way would
# misrepresent it as a currency amount).
_PLAIN_NUMBER_RE = re.compile(r"^\(?-?[\d,]+(\.\d+)?\)?$")


@dataclass
class NumericAnswer:
    metric_label: str  # the row label exactly as it appeared in the source
    period_label: str | None  # the resolved period, if one could be bound
    value: str  # the raw value token exactly as extracted - never reformatted
    header_line: str
    all_values_for_row: list[str]  # the full row, for context/verification
    ambiguous_period_binding: bool
    """True when the header's period tokens could not be confidently paired 1:1
    with the row's values (e.g. a header without clean 'Q<n> FY<yy>' tokens) - the
    caller must present `all_values_for_row` as-is rather than claiming `value`
    alone answers a period-specific question."""
    extraction_method: str
    """Which binding strategy produced `value` - "labeled_column", "positional_single_column",
    "positional_period_binding", "ambiguous_full_row" (period couldn't be bound), or
    "ambiguous_metric_selection" (more than one row matched the question's metric and
    none could be picked out as the one the question meant)."""
    unit_scale: str | None = None  # e.g. "INR million" - from the header's own notation, never guessed
    normalized_value: str | None = None  # Indian comma-grouping stripped from a plain number; None if not a plain number (e.g. a "%")
    ambiguous_metric_selection: bool = False
    metric_alternatives: list[str] = field(default_factory=list)
    """Populated only when ambiguous_metric_selection is True - the row labels that all
    matched the question's metric wording but couldn't be told apart (e.g. "Reported
    PAT" and "Adjusted PAT" when the question just says "PAT"). The caller must surface
    these as explicit choices, never silently pick one."""


def _row_label_matches_question_metric(row_label: str, question: str) -> bool:
    question_metrics = canonical_metrics_for_text(question)
    row_metrics = canonical_metrics_for_text(row_label)
    return bool(question_metrics & row_metrics)


def _select_unambiguous_row(question: str, matching_rows: list[tuple[str, str]]) -> tuple[str, str] | None:
    """`matching_rows` all canonically matched the question's metric wording (e.g.
    both "Reported PAT" and "Adjusted PAT" match a question mentioning "PAT") - this
    picks out the ONE the question actually meant, generically, with no company- or
    metric-specific special-casing:

    Precedence 1 (exact label match): the row's own label, verbatim, appears as a
    phrase in the question (e.g. the question literally says "Reported PAT") - the
    most explicit signal available.

    Precedence 2 (distinguishing synonym/qualifier word): among the matching rows'
    labels, the words they do NOT all share in common (e.g. "Reported" vs. "Adjusted"
    - "PAT" is common to both, so it doesn't count) - if exactly one row's distinct
    words overlap with the question's words, that row is what was meant.

    Returns None (never guesses) if no single row can be confidently distinguished."""
    q_norm = normalize_label(question)

    exact = [(label, rest) for label, rest in matching_rows if normalize_label(label) in q_norm]
    if len(exact) == 1:
        return exact[0]
    candidates = exact if len(exact) > 1 else matching_rows

    label_word_sets = [set(normalize_label(label).split()) for label, _ in candidates]
    common_words = set.intersection(*label_word_sets) if label_word_sets else set()
    q_words = set(q_norm.split())
    distinguished = [
        (label, rest)
        for (label, rest), words in zip(candidates, label_word_sets)
        if (words - common_words) & q_words
    ]
    if len(distinguished) == 1:
        return distinguished[0]
    return None


def resolve_cross_chunk_metric_ambiguity(
    question: str, candidates: list[NumericAnswer]
) -> NumericAnswer | list[str] | None:
    """A table that spans multiple persisted chunks (see app.services.chunking -
    a long table is split into several table_row_group chunks, each repeating the
    header) can put two DIFFERENT rows the question's wording matches into
    DIFFERENT chunks (e.g. a real Sun Pharma case: "EBITDA" and "EBITDA%" ended up
    in separate chunks because the table didn't fit one). Each chunk's own
    extract_numeric_answer() call only ever sees ITS rows, so it resolves
    confidently on its own - the ambiguity only becomes visible once results from
    multiple chunks are compared. Call this across every chunk's successful,
    unambiguous NumericAnswer for the SAME question before trusting any one of
    them: returns the single NumericAnswer to use if there's truly only one
    candidate metric (or the question's wording disambiguates between several),
    or the sorted list of alternative metric labels if it's still genuinely
    ambiguous across chunks - never silently picks whichever chunk ranked first."""
    if not candidates:
        return None
    distinct_labels = sorted({c.metric_label for c in candidates})
    if len(distinct_labels) == 1:
        return candidates[0]
    selected = _select_unambiguous_row(question, [(c.metric_label, "") for c in candidates])
    if selected is None:
        return distinct_labels
    chosen_label = selected[0]
    return next(c for c in candidates if c.metric_label == chosen_label)


def _normalized_value(raw: str) -> str | None:
    """A plain currency figure's displayed digits with grouping commas removed
    and accounting-style parentheses turned into a leading "-" (e.g. "(1,234)"
    -> "-1234") - never applied to a percentage (see _applicable_unit_scale) or
    anything that isn't unambiguously a single plain number."""
    stripped = raw.strip()
    if not _PLAIN_NUMBER_RE.match(stripped):
        return None
    negative = stripped.startswith("(") and stripped.endswith(")")
    digits = stripped.strip("()").replace(",", "")
    return f"-{digits}" if negative and not digits.startswith("-") else digits


def _applicable_unit_scale(value: str, header_unit_scale: str | None) -> str | None:
    """The header's currency scale (e.g. "INR million") applies ONLY to a plain
    currency figure - never to a percentage (a margin/growth % is not "80.8
    million" of anything), and never when no single value was actually picked
    (an empty/ambiguous result shouldn't imply any particular row's unit)."""
    if not value or value.strip().endswith("%"):
        return None
    return header_unit_scale


def _safe_period_mapping(labels: list[str], values: list[str]) -> dict[str, str]:
    """Builds a label->value mapping, but DROPS (never silently resolves via
    last-write-wins) any label that repeats - e.g. a real header where the same
    delta label ("Y-o-Y") appears twice for two different comparisons (Sun
    Pharma's quarter-vs-quarter AND half-vs-half columns both say "Y-o-Y"), or a
    genuine document/parsing error repeating a period token. A `dict(zip(...))`
    would otherwise silently keep only the LAST occurrence's value under that
    name. Dropping the colliding key(s) (rather than invalidating the whole
    mapping) still lets every OTHER, uniquely-labeled column - e.g. "Q2FY27" -
    bind correctly; a lookup for the dropped (ambiguous) label simply won't be
    found, which is the same as not being able to confidently answer for it."""
    counts = Counter(labels)
    return {label: value for label, value in zip(labels, values) if counts[label] == 1}


def extract_numeric_answer(question: str, chunk_text: str, header_line: str | None = None) -> NumericAnswer | None:
    """`chunk_text` is a persisted table_row_group chunk's raw text (header line
    followed by one "label: v1, v2, ..." line per row, as produced by
    app.services.chunking). Returns the first row whose label canonically matches a
    metric named in the question, with its value bound to the question's period if
    one was stated and the header's periods line up 1:1 with the row's values."""
    lines = [l for l in chunk_text.split("\n") if l.strip()]
    if not lines:
        return None

    if header_line is None:
        # The real persisted format may prepend a title line before the actual
        # column-header line (see app.services.chunking._format_table_row_group) -
        # pick whichever pre-data line has the most recognizable period tokens,
        # not blindly the first line.
        pre_data_lines = []
        for line in lines:
            if ":" in line:
                break
            pre_data_lines.append(line)
        header = max(pre_data_lines, key=lambda l: len(extract_period_labels_from_header(l)), default=lines[0])
    else:
        header = header_line

    unit_scale = extract_unit_scale_from_header(header)

    all_rows: list[tuple[str, str]] = []
    for line in lines[1:]:
        if ":" not in line:
            continue
        label, _, rest = line.partition(":")
        all_rows.append((label.strip(), rest))

    matching_rows = [(l, r) for l, r in all_rows if _row_label_matches_question_metric(l, question)]
    if not matching_rows:
        return None

    if len(matching_rows) > 1:
        selected = _select_unambiguous_row(question, matching_rows)
        if selected is None:
            return NumericAnswer(
                metric_label=" / ".join(l for l, _ in matching_rows), period_label=None, value="",
                header_line=header, all_values_for_row=[], ambiguous_period_binding=True,
                extraction_method="ambiguous_metric_selection", unit_scale=None,
                ambiguous_metric_selection=True, metric_alternatives=[l for l, _ in matching_rows],
            )
        matching_rows = [selected]

    for label, rest in matching_rows:
        # "|" (not ",") separates values - see app.services.chunking._VALUE_SEP:
        # Indian-format numbers embed commas of their own (e.g. "1,61,000").
        raw_values = [v.strip() for v in rest.split("|") if v.strip()]
        if not raw_values:
            continue

        requested_period = resolve_period_mention(question)

        if all(_LABELED_VALUE_RE.match(v) for v in raw_values):
            # This row carries its own per-value column labels (a sparse row
            # from a table with optional columns) - bind directly from those
            # labels rather than the full header's position-based labels,
            # which would overcount columns this row doesn't have.
            labeled_pairs = [tuple(v.split("=", 1)) for v in raw_values]
            values = [v for _, v in labeled_pairs]
            row_labels = [lbl for lbl, _ in labeled_pairs]
            period_to_value = _safe_period_mapping(row_labels, values)
            if requested_period and requested_period in period_to_value:
                picked = period_to_value[requested_period]
                return NumericAnswer(
                    metric_label=label, period_label=requested_period,
                    value=picked, header_line=header,
                    all_values_for_row=values, ambiguous_period_binding=False,
                    extraction_method="labeled_column", unit_scale=_applicable_unit_scale(picked, unit_scale),
                    normalized_value=_normalized_value(picked),
                )
            if not requested_period and len(values) == 1:
                return NumericAnswer(
                    metric_label=label, period_label=labeled_pairs[0][0], value=values[0],
                    header_line=header, all_values_for_row=values, ambiguous_period_binding=False,
                    extraction_method="labeled_column", unit_scale=_applicable_unit_scale(values[0], unit_scale),
                    normalized_value=_normalized_value(values[0]),
                )
            fallback_value = values[0] if len(values) == 1 else ""
            return NumericAnswer(
                metric_label=label, period_label=None, value=fallback_value,
                header_line=header, all_values_for_row=values, ambiguous_period_binding=True,
                extraction_method="ambiguous_full_row", unit_scale=_applicable_unit_scale(fallback_value, unit_scale),
            )

        values = raw_values
        period_labels = extract_period_labels_from_header(header)

        if len(period_labels) == len(values):
            period_to_value = _safe_period_mapping(period_labels, values)
            if requested_period and requested_period in period_to_value:
                picked = period_to_value[requested_period]
                return NumericAnswer(
                    metric_label=label, period_label=requested_period,
                    value=picked, header_line=header,
                    all_values_for_row=values, ambiguous_period_binding=False,
                    extraction_method="positional_period_binding", unit_scale=_applicable_unit_scale(picked, unit_scale),
                    normalized_value=_normalized_value(picked),
                )
            if not requested_period and len(values) == 1:
                return NumericAnswer(
                    metric_label=label, period_label=period_labels[0], value=values[0],
                    header_line=header, all_values_for_row=values, ambiguous_period_binding=False,
                    extraction_method="positional_single_column", unit_scale=_applicable_unit_scale(values[0], unit_scale),
                    normalized_value=_normalized_value(values[0]),
                )
            # A period was asked for but isn't one of this row's columns, OR no
            # period was asked for and there are multiple columns to choose from -
            # either way, picking one would be a guess. Return the full row,
            # flagged ambiguous, rather than silently picking one value.
            fallback_value = values[0] if len(values) == 1 else ""
            return NumericAnswer(
                metric_label=label, period_label=None, value=fallback_value,
                header_line=header, all_values_for_row=values, ambiguous_period_binding=True,
                extraction_method="ambiguous_full_row", unit_scale=_applicable_unit_scale(fallback_value, unit_scale),
            )

        # Header periods don't line up 1:1 with the row's values - can't bind any
        # single value to a specific period with confidence.
        return NumericAnswer(
            metric_label=label, period_label=None, value="", header_line=header,
            all_values_for_row=values, ambiguous_period_binding=True,
            extraction_method="ambiguous_full_row", unit_scale=None,
        )

    return None
