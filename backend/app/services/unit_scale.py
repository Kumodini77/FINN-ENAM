"""Generic (non-ticker-specific) extraction of the currency unit/scale a table
header states for itself (e.g. "(Rs bn)", "(₹ mn)", "(INR Crore)"). Never
inferred from a company's identity or sector - only read from the header text
that is actually present, so a header with no such notation yields None rather
than a guessed scale."""

import re

_UNIT_SCALE_RE = re.compile(
    r"(₹|Rs\.?|INR)\s*('000|000s|thousand|mn|million|bn|billion|cr|crore|lakh|lac)\b",
    re.IGNORECASE,
)

_SCALE_NAMES = {
    "'000": "thousand", "000s": "thousand", "thousand": "thousand",
    "mn": "million", "million": "million",
    "bn": "billion", "billion": "billion",
    "cr": "crore", "crore": "crore",
    "lakh": "lakh", "lac": "lakh",
}


def extract_unit_scale_from_header(header_line: str) -> str | None:
    """Returns a normalized "<currency> <scale>" label (e.g. "INR million"), or
    None if the header doesn't state one explicitly."""
    match = _UNIT_SCALE_RE.search(header_line)
    if not match:
        return None
    currency_raw, scale_raw = match.group(1), match.group(2)
    currency = "INR" if currency_raw.lower() in ("rs", "rs.", "inr", "₹") else currency_raw
    scale = _SCALE_NAMES.get(scale_raw.lower(), scale_raw.lower())
    return f"{currency} {scale}"
