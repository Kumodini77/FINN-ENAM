"""Screener.in source adapter — Phase 12B's primary, actually-working discovery
adapter, chosen deliberately for this phase over a generic IR-website crawler:

1. Its URL scheme is purely ticker-based (`/company/{TICKER}/consolidated/`), so it
   generalizes to ANY NSE ticker with zero per-company configuration — unlike an
   official-IR-site crawler, which needs a per-company seed URL to even start (see
   `ir_website_adapter.py` for that reusable-but-seed-dependent alternative, built
   this phase but not populated with seed URLs beyond what's genuinely verified).
2. Every link it surfaces for annual reports and concalls points at a company- or
   exchange-hosted PDF (e.g. bseindia.com, or the company's own domain), not at
   screener.in itself — these are the same primary-source documents the existing
   ingestion pipeline already treats as authoritative, just discovered via an
   index rather than typed in by hand.
3. It was confirmed live and reachable from this environment during this phase
   (NSE/BSE's own sites return 403 here, consistent with
   docs/filing-access-spike.md's prior finding; screener.in returns 200).

Identity verification: screener's own <title> tag reliably contains the real
company name (verified against TCS and TMPV live) — this is checked against the
company's registered name before ANY candidate from a page is trusted, per the
rule that a document must never be attributed to a company solely because its
URL contained that company's ticker.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from app.services.document_discovery.types import DiscoveredCandidate, SourceCheckResult

logger = logging.getLogger("finn.services.document_discovery.screener")

SOURCE_NAME = "screener"
BASE_URL = "https://www.screener.in"
USER_AGENT = "FINNResearchBot/1.0 (+https://github.com/; automated document discovery for personal research use)"
REQUEST_TIMEOUT_SECONDS = 20.0

_GENERIC_NAME_WORDS = {
    "ltd", "limited", "pvt", "private", "company", "co", "inc", "the", "of", "and", "&",
}


def _normalize_name_tokens(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", name.lower())
    return {w for w in words if w not in _GENERIC_NAME_WORDS and len(w) > 1}


def _identity_matches(page_title: str, expected_company_name: str) -> bool:
    """EVERY meaningful word of the expected company name must appear in the
    page title — generic across any company name, never a per-ticker special
    case. Deliberately strict (full containment, not a partial-overlap ratio):
    a looser threshold was tried and found to wrongly accept "Tata Motors
    Commercial Vehicles Ltd" against a page that was actually "Tata Motors
    PASSENGER Vehicles Ltd" (TMPV), since the two names share 3 of 4 tokens —
    exactly the TMPV/TMCV confusion this adapter must never make. Full
    containment correctly rejects that case while still accepting real
    abbreviation/formatting differences (title text only ever ADDS extra
    words around the real name, like "share price | About TCS")."""
    expected_tokens = _normalize_name_tokens(expected_company_name)
    if not expected_tokens:
        return False
    title_tokens = _normalize_name_tokens(page_title)
    return expected_tokens <= title_tokens


_YEAR_RE = re.compile(r"(\d{4})")
_MONTH_YEAR_RE = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{4})\b")


def _annual_report_period(link_text: str) -> str | None:
    """'Annual Report 2026' -> 'FY26', by the standard Indian-market convention
    that an annual report labeled with calendar year Y covers the fiscal year
    ending March of that same year Y (documented assumption, not a guess about
    THIS specific company — see module docstring)."""
    match = _YEAR_RE.search(link_text)
    if not match:
        return None
    year = int(match.group(1))
    return f"FY{year % 100:02d}"


def _concall_period_label(month_year_text: str) -> str | None:
    """Screener's own period label for a concall row (e.g. 'Oct 2026'),
    normalized but NOT converted into a fiscal quarter — doing that would
    require guessing this company's exact reporting lag, which this adapter
    deliberately does not do (see module docstring + Phase 12B report). The
    actual fiscal period a transcript discusses is determined from the
    document's own content once ingested, by the existing period-resolution
    pipeline, independent of this label."""
    cleaned = month_year_text.strip()
    return re.sub(r"\s+", "", cleaned).upper() if cleaned else None


class ScreenerSourceAdapter:
    source_name = SOURCE_NAME

    def __init__(self, client: httpx.Client | None = None, timeout: float = REQUEST_TIMEOUT_SECONDS):
        self._client = client
        self._timeout = timeout
        self._owns_client = client is None

    def _get(self, url: str) -> httpx.Response:
        client = self._client or httpx.Client(follow_redirects=True, timeout=self._timeout, headers={"User-Agent": USER_AGENT})
        try:
            return client.get(url)
        finally:
            if self._owns_client and self._client is None:
                client.close()

    def check(self, ticker: str, expected_company_name: str) -> SourceCheckResult:
        ticker = ticker.strip().upper()
        urls_to_try = [f"{BASE_URL}/company/{ticker}/consolidated/", f"{BASE_URL}/company/{ticker}/"]

        last_error: str | None = None
        for url in urls_to_try:
            try:
                resp = self._get(url)
            except httpx.TimeoutException:
                last_error = f"Timed out fetching {url}"
                continue
            except httpx.HTTPError as exc:
                last_error = f"HTTP error fetching {url}: {exc}"
                continue

            if resp.status_code == 404:
                last_error = f"{url} returned 404"
                continue
            if resp.status_code != 200:
                last_error = f"{url} returned HTTP {resp.status_code}"
                continue

            return self._parse(ticker, url, resp.text, expected_company_name)

        return SourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=False, error=last_error or "No reachable screener.in page found.")

    def _parse(self, ticker: str, url: str, html: str, expected_company_name: str) -> SourceCheckResult:
        soup = BeautifulSoup(html, "lxml")
        title_el = soup.find("title")
        page_title = title_el.get_text() if title_el else ""

        if not _identity_matches(page_title, expected_company_name):
            logger.warning(
                "screener identity check failed for %s: expected %r, page title %r", ticker, expected_company_name, page_title
            )
            return SourceCheckResult(
                ticker=ticker, source_name=SOURCE_NAME, ok=True, identity_verified=False, checked_url=url,
                error=f"Page found but company identity could not be confirmed (expected {expected_company_name!r}, page title {page_title!r}).",
            )

        now = datetime.now(timezone.utc)
        candidates: list[DiscoveredCandidate] = []
        candidates.extend(self._parse_annual_reports(soup, ticker, url, now))
        candidates.extend(self._parse_concalls(soup, ticker, url, now))

        return SourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=True, identity_verified=True, checked_url=url, candidates=candidates)

    def _parse_annual_reports(self, soup: BeautifulSoup, ticker: str, page_url: str, now: datetime) -> list[DiscoveredCandidate]:
        out: list[DiscoveredCandidate] = []
        container = soup.find("div", class_=lambda c: c and "annual-reports" in c.split())
        if container is None:
            return out
        for link in container.find_all("a", href=True):
            href = link["href"]
            if not href.lower().endswith(".pdf"):
                continue
            title = link.get_text(strip=True)
            out.append(
                DiscoveredCandidate(
                    company_ticker=ticker, doc_type="annual_report", title=title or "Annual Report",
                    source_url=href, source_name=SOURCE_NAME, reporting_period=_annual_report_period(title),
                    original_filename=href.rsplit("/", 1)[-1], discovery_timestamp=now, identity_verified=True,
                    confidence_notes=[f"Discovered via screener.in annual-reports section ({page_url})."],
                )
            )
        return out

    def _parse_concalls(self, soup: BeautifulSoup, ticker: str, page_url: str, now: datetime) -> list[DiscoveredCandidate]:
        out: list[DiscoveredCandidate] = []
        container = soup.find("div", class_=lambda c: c and "concalls" in c.split())
        if container is None:
            return out

        for row in container.find_all("li"):
            period_el = row.find("div")
            period_label = period_el.get_text(strip=True) if period_el else None
            period = _concall_period_label(period_label) if period_label else None

            for link in row.find_all("a", href=True):
                href = link["href"]
                if not href.lower().endswith(".pdf"):
                    continue
                link_text = link.get_text(strip=True)
                link_title_attr = (link.get("title") or "").lower()

                if "transcript" in link_title_attr or "transcript" in link_text.lower():
                    doc_type, label = "concall_transcript", "Concall Transcript"
                elif link_text.strip().upper() == "PPT":
                    doc_type, label = "investor_presentation", "Earnings Call Presentation"
                else:
                    continue  # e.g. audio/video "REC" links — not a PDF document type we ingest

                title = f"{label} — {period_label}" if period_label else label
                out.append(
                    DiscoveredCandidate(
                        company_ticker=ticker, doc_type=doc_type, title=title, source_url=href, source_name=SOURCE_NAME,
                        reporting_period=period, original_filename=href.rsplit("/", 1)[-1], discovery_timestamp=now,
                        identity_verified=True,
                        confidence_notes=[
                            f"Discovered via screener.in concalls section ({page_url}).",
                            "reporting_period is screener's own concall-month label, not an inferred fiscal quarter "
                            "(see module docstring) — the document's actual period is resolved from its content once ingested.",
                        ],
                    )
                )
        return out


__all__ = ["ScreenerSourceAdapter", "SOURCE_NAME"]
