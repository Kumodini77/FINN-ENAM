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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pdfplumber

_NUMERIC_TOKEN_RE = re.compile(r"^\(?-?[\d,]+(\.\d+)?%?\)?$")
_MIN_TRAILING_NUMERIC_FOR_DATA_ROW = 2
_MIN_ROWS_FOR_CONFIDENT_TABLE = 2
_MAX_TITLE_CONTEXT_LINES = 2


def _is_numeric_token(token: str) -> bool:
    return bool(_NUMERIC_TOKEN_RE.match(token))


def _trailing_numeric_count(tokens: list[str]) -> int:
    count = 0
    for tok in reversed(tokens):
        if _is_numeric_token(tok):
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


def _extract_blocks_from_text(raw_text: str, page_number: int) -> list[Block]:
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

                if len(col_counts) == 1 and header_usable:
                    if prose_buffer and prose_buffer[-1].strip() == header_line:
                        prose_buffer.pop()
                    flush_prose()
                    rows = [TableRow(label=label, values=values) for _, label, values in run]
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
                        reason = "row pattern matched but trailing column counts were inconsistent across rows"
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
                blocks = _extract_blocks_from_text(raw_text, page_number)
                pages.append(PageExtraction(page_number=page_number, raw_text=raw_text, blocks=blocks))
        return pages
    except PdfExtractionError:
        raise
    except Exception as e:
        raise PdfExtractionError(f"Could not extract text from '{pdf_path}': {e}") from e
