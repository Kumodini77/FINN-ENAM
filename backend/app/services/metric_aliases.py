"""Financial metric name/abbreviation aliases, used to match a question's wording
against a table row's actual label (e.g. "NII" <-> "Net interest income") without
hardcoding any ticker-specific logic - these are generic accounting terms that
generalize to any company's filings, per requirements.md Section 3.

Not exhaustive; extend as real documents surface more line-item names. Every alias
list's canonical key is the form most commonly seen as a literal row label in Indian
company filings, so matching a row label against these keys needs only a normalized
substring check (see normalize_label below), not fuzzy matching.
"""

import re

# canonical_label -> [abbreviations/synonyms a user might type]
METRIC_ALIASES: dict[str, list[str]] = {
    "net interest income": ["nii", "net interest income"],
    "non-interest income": ["other income", "non interest income", "fee income"],
    "net revenue": ["revenue", "total revenue", "total income", "net sales", "sales", "turnover", "topline", "top line"],
    "operating expenses": ["opex", "operating expenses", "operating cost"],
    "provisions": ["provisions", "provisioning", "credit cost"],
    "profit before tax": ["pbt", "profit before tax"],
    "profit after tax": ["pat", "net profit", "profit after tax", "net income", "bottom line", "bottomline"],
    "ebitda": ["ebitda", "operating profit"],
    "gross profit": ["gross profit", "gross margin"],
    "total assets": ["total assets", "balance sheet size"],
    "total liabilities": ["total liabilities"],
    "total debt": ["total debt", "borrowings", "net debt"],
    "cash flow from operations": ["operating cash flow", "cfo", "cash flow from operations"],
    "capital expenditure": ["capex", "capital expenditure", "capital spending"],
    "deposits": ["deposits", "total deposits", "casa"],
    "net interest margin": ["nim", "net interest margin"],
    "gross npa": ["gross npa", "gnpa", "gross non-performing assets", "gross non performing assets"],
    "net npa": ["net npa", "nnpa", "net non-performing assets", "net non performing assets"],
    "earnings per share": ["eps", "earnings per share"],
}

_WORD_RE = re.compile(r"[a-z0-9&]+")


def normalize_label(text: str) -> str:
    """Lowercases and strips punctuation to bare words, so "Profit after tax
    (Adjusted)*" and "profit after tax" both normalize to a form containing
    "profit after tax" as a substring."""
    return " ".join(_WORD_RE.findall(text.lower()))


def canonical_metrics_for_text(text: str) -> set[str]:
    """Every canonical metric whose alias appears in `text` (question or row
    label), normalized. A question mentioning "NII" and a row labeled "Net
    interest income" both resolve to the same canonical key, so they can be
    matched against each other without string equality."""
    normalized = normalize_label(text)
    matched = set()
    for canonical, aliases in METRIC_ALIASES.items():
        for alias in aliases:
            if normalize_label(alias) in normalized:
                matched.add(canonical)
                break
    return matched


def expand_aliases(text: str) -> str:
    """Appends every canonical metric name matched in `text` to itself - used to
    enrich both a table row's embedding text and (symmetrically) a query's
    embedding text with the same vocabulary, so "NII" and "net interest income"
    land closer together in embedding space than they otherwise would."""
    canonicals = canonical_metrics_for_text(text)
    if not canonicals:
        return text
    return f"{text} ({'; '.join(sorted(canonicals))})"
