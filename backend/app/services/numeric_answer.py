"""Deterministic (non-LLM) extraction of a single reported figure from a
table_row_group chunk, for NUMERICAL-intent Pull questions.

No generation model is involved - this is pattern matching over already-extracted,
already-cited table text, never an invented number. If the metric or period can't be
confidently bound to exactly one value, this returns None rather than guessing, and
the caller must fall back to an "insufficient evidence" / "ambiguous" response
instead of fabricating a figure.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.metric_aliases import canonical_metrics_for_text
from app.services.period_resolution import extract_period_labels_from_header, resolve_period_mention


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


def _row_label_matches_question_metric(row_label: str, question: str) -> bool:
    question_metrics = canonical_metrics_for_text(question)
    row_metrics = canonical_metrics_for_text(row_label)
    return bool(question_metrics & row_metrics)


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

    for line in lines[1:]:
        if ":" not in line:
            continue
        label, _, rest = line.partition(":")
        label = label.strip()
        if not _row_label_matches_question_metric(label, question):
            continue

        values = [v.strip() for v in rest.split(",") if v.strip()]
        if not values:
            continue

        period_labels = extract_period_labels_from_header(header)
        requested_period = resolve_period_mention(question)

        if len(period_labels) == len(values):
            period_to_value = dict(zip(period_labels, values))
            if requested_period and requested_period in period_to_value:
                return NumericAnswer(
                    metric_label=label, period_label=requested_period,
                    value=period_to_value[requested_period], header_line=header,
                    all_values_for_row=values, ambiguous_period_binding=False,
                )
            if not requested_period and len(values) == 1:
                return NumericAnswer(
                    metric_label=label, period_label=period_labels[0], value=values[0],
                    header_line=header, all_values_for_row=values, ambiguous_period_binding=False,
                )
            # A period was asked for but isn't one of this row's columns, OR no
            # period was asked for and there are multiple columns to choose from -
            # either way, picking one would be a guess. Return the full row,
            # flagged ambiguous, rather than silently picking one value.
            return NumericAnswer(
                metric_label=label, period_label=None, value=values[0] if len(values) == 1 else "",
                header_line=header, all_values_for_row=values, ambiguous_period_binding=True,
            )

        # Header periods don't line up 1:1 with the row's values - can't bind any
        # single value to a specific period with confidence.
        return NumericAnswer(
            metric_label=label, period_label=None, value="", header_line=header,
            all_values_for_row=values, ambiguous_period_binding=True,
        )

    return None
