"""Generic PDF text/table extraction for the RAG ingestion pipeline.

Generalises to any NSE filing/transcript/presentation PDF (requirements.md Section 3
- "never hard-code ticker-specific logic") - every pattern here is structural (trailing
numeric tokens, column-count consistency, line adjacency), not keyed to any specific
company, template, or exact wording.

pdfplumber's own extract_tables() was tried first and rejected for this document
style: HDFC's Q1 FY27 presentation renders tables via colour-fill row banding, not
vector ruling lines, so extract_tables() (and its text/text, text/lines, lines/text
strategy variants) returns zero tables or structurally wrong output on the exact page
this module's regression fixture is drawn from. What follows is a line-pattern
heuristic over page.extract_text() instead: a "data row" is a label followed by two or
more trailing numeric/percent tokens; a confident table is >=2 consecutive data rows
with the SAME trailing-numeric-token count, whose immediately preceding line is not
itself a data row (that preceding line becomes the header). Anything that looks
numeric-heavy without forming a confident table (column-count disagreement, or a run of
label-less all-numeric lines - typical of a rotated/garbled chart axis) is preserved
verbatim as TABLE_UNPARSED with needs_manual_review=True, never force-structured.

SPARSE OPTIONAL-COLUMN RECONCILIATION (added after a real finding on a second
company's genuine document - Sun Pharma's "Financial Snapshot" table has two
"Y-o-Y" delta columns that are populated for some metrics (Sales, EBITDA,
Adjusted PAT) but deliberately omitted for others (Gross Margin %, EBITDA%,
Reported PAT, EPS), so the table's rows do NOT all share one column count, which
the original heuristic treated as an unconditional table_unparsed signal). When
column counts disagree, the header is parsed into typed columns (period vs.
delta - see app.services.period_resolution.parse_header_columns) before giving
up: if a short row's value count exactly equals the number of PERIOD columns
(i.e. it's missing precisely the delta columns, identified by their own header
label text, never guessed from the count alone), its values are bound to those
specific period columns and the table is still emitted as a confident
table_row_group, with each row's TableRow.column_labels recording exactly which
header column each value belongs to. Any row that doesn't cleanly match either
the full column count or the period-only count still bails the whole run to
TABLE_UNPARSED, unchanged from before - this reconciliation only ever narrows
what is accepted, it never weakens the existing all-or-nothing safety check.

GARBLED-TEXT DETECTION (separate from the table heuristic above): pdfplumber's
page.extract_text() assumes horizontal reading order from character bounding boxes.
When a page contains ROTATED or vertically-stacked glyphs (e.g. a chart's rotated axis
labels mixing a percentage with a quarter label, like "1.25% Jun'25"), this assumption
breaks down and produces character-interleaved nonsense - short, word-salad lines like
"1 . 4", "J", "u n", "'2" - that match neither the table-row pattern nor the
numeric-only-line pattern (they mix stray letters with numeric fragments), so without a
dedicated check they would silently fall through as ordinary PROSE, untagged and
treated as equally reliable as real sentences. A run of >=2 consecutive lines
containing no recognizable word (no run of 3+ letters) is instead captured verbatim as
TABLE_UNPARSED with needs_manual_review=True - this is a text-extraction-quality
signal, not a table-shape signal, but shares the same "preserve raw text, flag for
review, never force-structure or silently trust" contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pdfplumber

from app.services.period_resolution import parse_header_columns

# Real finding (ICICI Bank's P&L, a generic formatting convention, not
# company-specific): a negative percentage can be written with the "%" OUTSIDE
# the closing parenthesis - "(1.7)%" - not just "(1.7%)" or a bare "1.7%".
# Both parenthesis/percent orderings are accepted (exactly one "%" at most,
# never "%%") - a trailing "%" is still optional either way, never required.
_NUMERIC_TOKEN_RE = re.compile(r"^\(?-?[\d,]+(\.\d+)?(%\)?|\)%?)?$")
# The finite, generic vocabulary Indian financial tables use for "not reported
# this period" - never company- or metric-specific. _MIN_TRAILING_NUMERIC_FOR_DATA_ROW
# (below) still requires >=2 trailing value-like tokens before a line counts as
# a data row at all, so a single stray "-" at the end of an ordinary prose line
# is not, by itself, enough to misclassify that line as table data.
_MISSING_VALUE_RE = re.compile(r"^(n\.?/?a\.?|nm|nil|-{1,2})$", re.IGNORECASE)
_MIN_TRAILING_NUMERIC_FOR_DATA_ROW = 2
_MIN_ROWS_FOR_CONFIDENT_TABLE = 2
_MAX_TITLE_CONTEXT_LINES = 2
_MIN_GARBLED_FRAGMENT_RUN = 2


def _is_numeric_token(token: str) -> bool:
    return bool(_NUMERIC_TOKEN_RE.match(token))


def _is_value_or_missing_marker_token(token: str) -> bool:
    """A trailing "data" token is either a real numeric/percent value, or a
    recognized missing-value placeholder (NA, N/A, -, NM, nil). Treating these as
    a token - never silently dropping them - keeps a row's value COUNT and
    POSITION intact relative to the header. Without this, a placeholder cell in
    the MIDDLE of a row (e.g. "Sales NA 110 5.0%" - Q1's value missing) would
    stop the trailing-numeric scan early, swallow the real value before it into
    the row's label, and silently shift every value after it into the WRONG
    header column (see _reconcile_sparse_columns) - a real finding from Phase 3B's
    positional-integrity audit, not specific to any document."""
    return _is_numeric_token(token) or bool(_MISSING_VALUE_RE.match(token))


def _trailing_numeric_count(tokens: list[str]) -> int:
    count = 0
    for tok in reversed(tokens):
        if _is_value_or_missing_marker_token(tok):
            count += 1
        else:
            break
    return count


def _split_label_and_values(line: str) -> tuple[str, list[str]] | None:
    """A "data row": a non-empty label followed by >=2 trailing numeric tokens.
    Returns None for anything else (prose, headers, label-less numeric runs)."""
    tokens = line.split()
    n = _trailing_numeric_count(tokens)
    if n < _MIN_TRAILING_NUMERIC_FOR_DATA_ROW:
        return None
    label_tokens = tokens[: len(tokens) - n]
    if not label_tokens:
        return None
    return " ".join(label_tokens), tokens[len(tokens) - n :]


def _header_looks_valid(header_line: str) -> bool:
    """A real table header (even an abbreviated one) always carries readable column
    labels - e.g. "Q1 FY26" or "(Rs bn)". A lone footnote marker like "^" or "#",
    picked up only because it happens to be the preceding non-blank line, is not a
    header and must not turn an otherwise-consistent row run into a false-positive
    table (observed on a presentation page where two genuine data rows sit directly
    beneath a footnote-marker line rather than a real column header)."""
    alnum = re.sub(r"[^A-Za-z0-9]", "", header_line)
    return len(alnum) >= 3 and any(c.isalpha() for c in alnum)


def _is_numeric_only_line(line: str) -> bool:
    tokens = line.split()
    return len(tokens) >= 2 and all(_is_numeric_token(t) for t in tokens)


_PROSE_WORD_RE = re.compile(r"[A-Za-z]{3,}")


def _is_prose_like_line(line: str) -> bool:
    """A line counts as genuine prose only if it contains at least one real word
    (a run of 3+ letters, e.g. "Resilient", "Gross", "RISK"). This is the
    detector for pdfplumber's reading-order failure on ROTATED/vertically-stacked
    glyphs (typical of chart axis labels drawn as rotated text): when
    page.extract_text() misorders such characters, it produces lines like
    "1 . 4", "J", "u n", "'2" - fragments with no recognizable word at all. Real
    prose, even a short sentence, essentially never produces a run of lines this
    short with no multi-letter word; genuine standalone short lines (a lone page
    number, a bullet symbol) are rare and isolated, not sustained runs - the
    caller only acts on a RUN of such lines, not a single occurrence, to avoid
    over-flagging an incidental short line."""
    return bool(_PROSE_WORD_RE.search(line))


def normalize_numeric_value(raw: str) -> float:
    """Parentheses -> negative, trailing '%' and thousands-commas stripped. Used only
    for comparing extracted values against ground truth in tests - never to reinterpret
    what gets persisted, which stays the original string token."""
    s = raw.strip()
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").rstrip("%").replace(",", "")
    value = float(s)
    return -value if negative else value


@dataclass
class TableRow:
    label: str
    values: list[str]
    column_labels: list[str] | None = None
    """Set only when this row's values were bound via sparse-column
    reconciliation (see module docstring) - the exact header column (by its own
    label text, e.g. "Q2FY27") each entry in `values` corresponds to, in the
    same order. None for the common case (a row whose value count matches every
    other row's in the table) - callers (chunking/numeric_answer) fall back to
    positional/regex-based header parsing in that case, unchanged from before."""


@dataclass
class ProseBlock:
    kind: str = field(default="prose", init=False)
    page_number: int
    text: str


@dataclass
class TableBlock:
    kind: str = field(default="table_row_group", init=False)
    page_number: int
    header_line: str
    rows: list[TableRow]
    title: str | None = None


@dataclass
class UnparsedBlock:
    """Text that looked table-like but could not be confidently structured. Raw text
    is preserved verbatim - never force-parsed into fabricated rows/columns."""

    kind: str = field(default="table_unparsed", init=False)
    page_number: int
    text: str
    reason: str


Block = ProseBlock | TableBlock | UnparsedBlock


@dataclass
class PageExtraction:
    page_number: int
    raw_text: str
    blocks: list[Block]


class PdfExtractionError(Exception):
    """Raised when the PDF itself can't be opened/read. Never raised for ambiguous
    content - that becomes an UnparsedBlock instead, not an error."""


def _reconcile_sparse_columns(
    header_line: str, run: list[tuple[int, str, list[str]]]
) -> list[TableRow] | None:
    """Attempts to bind every row in `run` to the header's own typed columns
    (period vs. delta - see module docstring) when row value-counts disagree.
    Returns None (never guesses) unless EVERY row's value count equals either the
    full column count or exactly the period-only count - a single row that fits
    neither leaves the whole table unreconciled, same as before this existed."""
    header_columns = parse_header_columns(header_line)
    if not header_columns:
        return None

    full_labels = [label for label, _ in header_columns]
    period_labels = [label for label, kind in header_columns if kind == "period"]
    if len(period_labels) == len(full_labels):
        return None  # no delta columns to reconcile against - nothing to do here

    rows: list[TableRow] = []
    for _, label, values in run:
        if len(values) == len(full_labels):
            rows.append(TableRow(label=label, values=values, column_labels=full_labels))
        elif len(values) == len(period_labels):
            rows.append(TableRow(label=label, values=values, column_labels=period_labels))
        else:
            return None  # doesn't fit either shape - refuse to guess, bail entirely
    return rows


def _reconcile_via_positional_extraction(
    pdf_path: str, page_number: int, run: list[tuple[int, str, list[str]]]
) -> list[TableRow] | None:
    """Phase 9 production integration of app.services.pdf_positional's
    validated Stage 1 prototype: when this page's PLAIN TEXT doesn't give a
    usable header (a merged, multi-line SEBI Regulation 33-style header, or a
    header whose text happens to carry no resolvable period at all - both
    real findings), re-reads this SAME page's words WITH coordinates and
    tries to reconstruct each column's true identity positionally.

    Deliberately conservative, matching the prototype's own validated
    guarantees: returns None (never guesses, never partially fills in a
    table) unless EVERY row in `run`, independently, gets a FULLY TYPED
    column set - every single column either a resolved reporting period or
    an explicitly recognized delta/growth column, never a blank unknown -
    whose length matches that row's own value count exactly. A row whose
    label can't even be located in the positional word-lines (e.g. a label
    split oddly by the text vs. word extraction) also aborts the whole
    table, rather than silently reconciling only some rows."""
    try:
        from app.services.pdf_positional import (
            extract_page_words,
            group_words_into_lines,
            reconstruct_column_kinds,
        )

        words = extract_page_words(pdf_path, page_number)
    except Exception:
        return None
    word_lines = group_words_into_lines(words)

    def _find_row_idx(label: str) -> int | None:
        return next((i for i, wl in enumerate(word_lines) if label in " ".join(w.text for w in wl)), None)

    def _looks_like_data_row(wl: list) -> bool:
        trailing = 0
        for w in reversed(wl):
            if _is_numeric_token(w.text):
                trailing += 1
            else:
                break
        # Mirrors _split_label_and_values's own "non-empty label" requirement
        # - a real finding: a pure year line ("2026 2026 2025 2026 2025
        # 2026", every token numeric) otherwise looks exactly like a
        # confident data row by trailing-count alone, wrongly stopping the
        # backward walk before it ever reaches the true header.
        return _MIN_TRAILING_NUMERIC_FOR_DATA_ROW <= trailing < len(wl)

    first_row_idx = _find_row_idx(run[0][1])
    if first_row_idx is None:
        return None
    # The header lines are found ONCE, directly above the run's FIRST row -
    # every row in the run shares the SAME header block. Two real findings
    # shaped this: (1) recomputing per-row made the lookback window "slide"
    # forward as row_idx increased, eventually dropping the true header
    # entirely and picking up the PREVIOUS data row instead; (2) walking back
    # a fixed number of lines can cross into an unrelated DATA ROW for a
    # different metric that simply didn't qualify for the same run (its own
    # numeric values can then pollute a column's combined text) - so the
    # backward walk stops the moment it hits anything that itself looks like
    # a data row (label + >=2 trailing numeric tokens), the same stopping
    # rule the existing text-based header search already uses.
    header_lines: list[list] = []
    for idx in range(first_row_idx - 1, max(-1, first_row_idx - 7), -1):
        if idx < 0 or _looks_like_data_row(word_lines[idx]):
            break
        header_lines.insert(0, word_lines[idx])

    rows: list[TableRow] = []
    for _, label, values in run:
        row_idx = _find_row_idx(label)
        if row_idx is None:
            return None
        numeric_words = [w for w in word_lines[row_idx] if _is_numeric_token(w.text)]
        if len(numeric_words) != len(values):
            return None
        # A real finding (ICICI): right-aligned numbers of differing digit
        # width can have centers drift several points between rows in the
        # "same" column (e.g. "199.74" vs "9.10"), occasionally enough to
        # cross the rival-claim ratio threshold for one row's column. Using
        # the right EDGE instead was tried and rejected: header text isn't
        # right-aligned the same way, so it introduces a systematic
        # center-vs-edge offset that made EVERY row wrong instead of just
        # one - worse, not better. Centers remain the anchor; the resulting
        # occasional duplicate-label case (two anchors both nearest the same
        # group) is already handled safely elsewhere - app.services.
        # numeric_answer's _safe_period_mapping drops a colliding label
        # entirely rather than guessing which value it belongs to.
        anchors = [w.center_x for w in numeric_words]
        kinds = reconstruct_column_kinds(header_lines, anchors)
        if any(k is None for k in kinds):
            return None  # some column genuinely unresolved - refuse the whole table, never partial
        labels = [text for _, text in kinds]
        # A real finding (Wipro): unrelated text on another header line (a
        # unit annotation like "( Rs million)", sitting on its own line with
        # no period/delta pattern of its own) can still get swept into a
        # column's combined text as an ungrouped stray word. The downstream
        # "label=value" chunk rendering (app.services.chunking) and its
        # parser (app.services.numeric_answer) both assume a column label is
        # a single clean token - a label containing "=", "|", spaces or
        # parentheses would corrupt that format rather than just failing to
        # resolve, which is worse than refusing. Validated here, not
        # silently fixed: reject the whole table if any label isn't clean.
        if any(not re.fullmatch(r"[A-Za-z0-9\-]+", lbl) for lbl in labels):
            return None
        rows.append(TableRow(label=label, values=values, column_labels=labels))
    return rows


def _title_context(lines: list[str], header_idx: int) -> str | None:
    title_lines: list[str] = []
    k = header_idx - 1
    while k >= 0 and len(title_lines) < _MAX_TITLE_CONTEXT_LINES:
        candidate = lines[k].strip()
        if not candidate or _split_label_and_values(candidate) is not None:
            break
        title_lines.insert(0, candidate)
        k -= 1
    return " / ".join(title_lines) if title_lines else None


def _extract_blocks_from_text(raw_text: str, page_number: int, pdf_path: str | None = None) -> list[Block]:
    lines = raw_text.split("\n")
    n = len(lines)
    blocks: list[Block] = []
    prose_buffer: list[str] = []

    def flush_prose() -> None:
        if prose_buffer:
            text = "\n".join(prose_buffer).strip()
            if text:
                blocks.append(ProseBlock(page_number=page_number, text=text))
            prose_buffer.clear()

    i = 0
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        parsed = _split_label_and_values(line)
        if parsed is not None:
            run: list[tuple[int, str, list[str]]] = [(i, parsed[0], parsed[1])]
            j = i + 1
            while j < n:
                nxt = lines[j].strip()
                if not nxt:
                    break
                p2 = _split_label_and_values(nxt)
                if p2 is None:
                    break
                run.append((j, p2[0], p2[1]))
                j += 1

            if len(run) >= _MIN_ROWS_FOR_CONFIDENT_TABLE:
                col_counts = {len(values) for _, _, values in run}
                header_idx = run[0][0] - 1
                header_line = lines[header_idx].strip() if header_idx >= 0 else ""
                header_is_itself_a_row = bool(header_line) and _split_label_and_values(header_line) is not None
                header_usable = header_line and not header_is_itself_a_row and _header_looks_valid(header_line)

                sparse_rows: list[TableRow] | None = None
                if len(col_counts) != 1 and header_usable:
                    sparse_rows = _reconcile_sparse_columns(header_line, run)

                # Phase 9: the text-based header above gave either no usable
                # period information at all, or a count that doesn't match
                # this run's own value counts - both real findings (a merged
                # multi-line Regulation 33 header, or a header line that
                # simply carries no period text). Only in THAT case - never
                # when the text-based header already looks right - try
                # reconstructing columns from word positions instead (see
                # app.services.pdf_positional). This can only ever ADD a
                # typed column_labels set where the text path had none or was
                # about to fail; it never overrides an already-working
                # text-based result.
                if sparse_rows is None and pdf_path is not None and header_usable:
                    # A real finding (Wipro): the period/delta tokens can sit
                    # on a TITLE line above header_line (e.g. "Q2'27 ... QoQ
                    # Growth YoY Growth" one line up from "( Rs million)",
                    # the immediate header_line) - app.services.numeric_answer
                    # already searches title-and-header together for exactly
                    # this reason (see its own header-line selection), so the
                    # trigger here must too, or it will wrongly treat an
                    # already-working document as needing positional help.
                    candidate_lines = [header_line]
                    title = _title_context(lines, header_idx)
                    if title:
                        candidate_lines.append(title)
                    text_header_matches_run = any(
                        len(parse_header_columns(cl)) in col_counts for cl in candidate_lines
                    )
                    if not text_header_matches_run:
                        sparse_rows = _reconcile_via_positional_extraction(pdf_path, page_number, run)

                if (len(col_counts) == 1 and header_usable and sparse_rows is None) or sparse_rows is not None:
                    if prose_buffer and prose_buffer[-1].strip() == header_line:
                        prose_buffer.pop()
                    flush_prose()
                    rows = sparse_rows or [TableRow(label=label, values=values) for _, label, values in run]
                    blocks.append(
                        TableBlock(
                            page_number=page_number,
                            header_line=header_line,
                            rows=rows,
                            title=_title_context(lines, header_idx),
                        )
                    )
                else:
                    flush_prose()
                    start_idx = run[0][0] if (header_is_itself_a_row or not header_line) else header_idx
                    raw_block = "\n".join(l for l in lines[start_idx:j] if l.strip())
                    if len(col_counts) != 1:
                        reason = (
                            "row pattern matched but trailing column counts were inconsistent across rows, and "
                            "they could not be reconciled against the header's own period/delta columns"
                        )
                    elif header_is_itself_a_row or not header_line:
                        reason = "no usable header line (preceding line was itself a data row, or page start)"
                    else:
                        reason = "preceding line does not look like a real column header (too short/not descriptive)"
                    blocks.append(UnparsedBlock(page_number=page_number, text=raw_block, reason=reason))
                i = j
                continue
            # Exactly one matching line is not strong enough evidence of a real table.
            prose_buffer.append(lines[i])
            i += 1
            continue

        if _is_numeric_only_line(line):
            run_start = i
            j = i
            while j < n:
                nxt = lines[j].strip()
                if nxt and _is_numeric_only_line(nxt):
                    j += 1
                    continue
                break
            flush_prose()
            raw_block = "\n".join(l for l in lines[run_start:j] if l.strip())
            blocks.append(
                UnparsedBlock(
                    page_number=page_number,
                    text=raw_block,
                    reason="numeric-only lines with no row labels - likely chart/axis data, not confirmed as a table",
                )
            )
            i = j
            continue

        if not _is_prose_like_line(line):
            run_start = i
            j = i
            while j < n:
                nxt = lines[j].strip()
                if nxt and not _is_prose_like_line(nxt) and _split_label_and_values(nxt) is None and not _is_numeric_only_line(nxt):
                    j += 1
                    continue
                break
            if j - run_start >= _MIN_GARBLED_FRAGMENT_RUN:
                flush_prose()
                raw_block = "\n".join(l for l in lines[run_start:j] if l.strip())
                blocks.append(
                    UnparsedBlock(
                        page_number=page_number,
                        text=raw_block,
                        reason=(
                            "no recognizable word in this run of lines - likely rotated/garbled chart-axis "
                            "text misordered by PDF text extraction, not continuous prose"
                        ),
                    )
                )
                i = j
                continue
            # A single isolated non-prose-like line isn't strong enough evidence of
            # garbled chart text on its own - keep it as prose rather than flagging
            # one stray short line (e.g. a lone page-footer artifact).

        prose_buffer.append(lines[i])
        i += 1

    flush_prose()
    return blocks


def extract_pages(pdf_path: str) -> list[PageExtraction]:
    """Opens `pdf_path` and returns one PageExtraction per page, 1-based page_number.
    Raises PdfExtractionError if the file can't be opened/read - never returns a
    partial result silently."""
    try:
        pages: list[PageExtraction] = []
        with pdfplumber.open(pdf_path) as pdf:
            for index, page in enumerate(pdf.pages):
                page_number = index + 1
                raw_text = page.extract_text() or ""
                blocks = _extract_blocks_from_text(raw_text, page_number, pdf_path=pdf_path)
                pages.append(PageExtraction(page_number=page_number, raw_text=raw_text, blocks=blocks))
        return pages
    except PdfExtractionError:
        raise
    except Exception as e:
        raise PdfExtractionError(f"Could not extract text from '{pdf_path}': {e}") from e
