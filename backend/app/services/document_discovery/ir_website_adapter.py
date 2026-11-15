"""Generic official-investor-relations-website adapter — priority tier 1 in the
source ranking (official IR site > official results page > official repo >
screener.in > other). Built this phase as a REUSABLE adapter (same interface as
ScreenerSourceAdapter), but deliberately not run against all 20 companies live:
unlike screener.in's uniform, ticker-based URL scheme, every company's IR site has
its own layout, and discovering/validating 20 real sites' bot-posture and link
structure reliably is exactly the kind of per-source uncertainty this phase's own
instruction ("prioritise reliable automatic coverage over pretending every source
is accessible") says not to paper over with guesses.

Usage: give it a company's own `investor_relations_url` (real, verifiable data,
never fabricated — see app.core.companies' documented pattern for how ticker/
sector/yfinance_symbol are seeded as DATA, not logic). This module contains zero
per-company branching; the SAME code crawls any seed URL given to it.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.document_discovery.screener_adapter import USER_AGENT, _identity_matches
from app.services.document_discovery.types import DiscoveredCandidate, SourceCheckResult

logger = logging.getLogger("finn.services.document_discovery.ir_website")

SOURCE_NAME = "ir_website"
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_LINKS_PER_PAGE = 200  # politeness/safety bound, not a coverage target

_DOC_TYPE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("annual_report", ("annual report", "integrated report", "annual-report")),
    ("concall_transcript", ("transcript", "concall", "earnings call")),
    (
        "investor_presentation",
        (
            "investor presentation", "earnings presentation", "results presentation", "fact sheet", "ppt",
            # Standalone "financial results" filings have no dedicated doc_type in
            # the schema (only 3 exist — see app.models.document.DocType) and are
            # filed as investor_presentation by established convention elsewhere
            # in this codebase's real ingested documents.
            "financial-results", "financial results", "financial-result",
        ),
    ),
]


def _classify_doc_type(text: str) -> str | None:
    lowered = text.lower()
    for doc_type, keywords in _DOC_TYPE_KEYWORDS:
        if any(k in lowered for k in keywords):
            return doc_type
    return None


_YEAR_RE = re.compile(r"(20\d{2})")


def _best_effort_period(text: str) -> str | None:
    """Only ever extracts an EXPLICIT year/quarter token already present in the
    link text or filename — never infers one from position or ordering, same
    non-fabrication rule app.services.numeric_answer already enforces for table
    data."""
    match = re.search(r"Q([1-4])\s*FY\s*(\d{2,4})", text, re.IGNORECASE)
    if match:
        q, yy = match.group(1), match.group(2)
        yy = yy[-2:]
        return f"Q{q}FY{yy}"
    year_match = _YEAR_RE.search(text)
    if year_match:
        return f"FY{year_match.group(1)[-2:]}"
    return None


class IRWebsiteSourceAdapter:
    source_name = SOURCE_NAME

    def __init__(self, client: httpx.Client | None = None, timeout: float = REQUEST_TIMEOUT_SECONDS):
        self._client = client
        self._timeout = timeout

    def _get(self, url: str) -> httpx.Response:
        client = self._client or httpx.Client(follow_redirects=True, timeout=self._timeout, headers={"User-Agent": USER_AGENT})
        try:
            return client.get(url)
        finally:
            if self._client is None:
                client.close()

    def check(self, ticker: str, expected_company_name: str, seed_url: str | None) -> SourceCheckResult:
        ticker = ticker.strip().upper()
        if not seed_url:
            return SourceCheckResult(
                ticker=ticker, source_name=SOURCE_NAME, ok=False,
                error="No verified investor_relations_url configured for this company — skipped rather than guessed.",
            )

        try:
            resp = self._get(seed_url)
        except httpx.TimeoutException:
            return SourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=False, error=f"Timed out fetching {seed_url}")
        except httpx.HTTPError as exc:
            return SourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=False, error=f"HTTP error fetching {seed_url}: {exc}")

        if resp.status_code != 200:
            return SourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=False, checked_url=seed_url, error=f"{seed_url} returned HTTP {resp.status_code}")

        return self._parse(ticker, seed_url, resp.text, expected_company_name)

    def _parse(self, ticker: str, page_url: str, html: str, expected_company_name: str) -> SourceCheckResult:
        soup = BeautifulSoup(html, "lxml")
        title_el = soup.find("title")
        page_title = (title_el.get_text() if title_el else "") + " " + soup.get_text()[:2000]

        identity_verified = _identity_matches(page_title, expected_company_name)
        if not identity_verified:
            return SourceCheckResult(
                ticker=ticker, source_name=SOURCE_NAME, ok=True, identity_verified=False, checked_url=page_url,
                error=f"Page found but company identity could not be confirmed against {expected_company_name!r} on {page_url}.",
            )

        now = datetime.now(timezone.utc)
        candidates: list[DiscoveredCandidate] = []
        links = soup.find_all("a", href=True)[:MAX_LINKS_PER_PAGE]
        for link in links:
            href = link["href"]
            if not href.lower().endswith(".pdf"):
                continue
            absolute_url = urljoin(page_url, href)
            if not self._same_registrable_domain(page_url, absolute_url):
                # A PDF hosted off the IR site's own domain (e.g. a BSE mirror) is
                # plausible but not auto-trusted by THIS adapter — screener.in's
                # adapter already covers that case with its own identity check.
                continue

            link_text = link.get_text(strip=True) or absolute_url.rsplit("/", 1)[-1]
            doc_type = _classify_doc_type(link_text) or _classify_doc_type(absolute_url)
            if doc_type is None:
                continue

            candidates.append(
                DiscoveredCandidate(
                    company_ticker=ticker, doc_type=doc_type, title=link_text, source_url=absolute_url,
                    source_name=SOURCE_NAME, reporting_period=_best_effort_period(link_text) or _best_effort_period(absolute_url),
                    original_filename=absolute_url.rsplit("/", 1)[-1], discovery_timestamp=now, identity_verified=True,
                    confidence_notes=[f"Discovered via official IR site crawl ({page_url})."],
                )
            )

        return SourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=True, identity_verified=True, checked_url=page_url, candidates=candidates)

    @staticmethod
    def _same_registrable_domain(a: str, b: str) -> bool:
        def host(u: str) -> str:
            netloc = urlparse(u).netloc.lower()
            parts = netloc.split(".")
            return ".".join(parts[-2:]) if len(parts) >= 2 else netloc

        return host(a) == host(b)


__all__ = ["IRWebsiteSourceAdapter", "SOURCE_NAME"]
