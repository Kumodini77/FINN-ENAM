"""Screener.in announcement adapter — Phase 12C Part 2's primary source,
chosen for the same reasons Phase 12B chose screener.in for documents (see
app.services.document_discovery.screener_adapter's module docstring):
NSE/BSE's own announcement pages/API return 301/403 in this environment
(verified live during this phase), while screener.in's per-company
announcements feed is reachable and ticker-generalizable.

How it works: screener's company page embeds an internal numeric company id
(e.g. `/concalls/add-3365/` for TCS) that its AJAX announcements endpoint
needs (`/announcements/recent/{id}/`) — this adapter extracts that id from
the same consolidated-company page the document adapter already fetches,
then calls the announcements endpoint. Every announcement found links
directly to the real, company/exchange-hosted filing PDF (bseindia.com) —
screener is the index, never the attributed source.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from app.services.announcement_discovery.types import AnnouncementSourceCheckResult, DiscoveredAnnouncement
from app.services.document_discovery.screener_adapter import BASE_URL, USER_AGENT, _identity_matches

logger = logging.getLogger("finn.services.announcement_discovery.screener")

SOURCE_NAME = "screener_announcements"
REQUEST_TIMEOUT_SECONDS = 20.0
_COMPANY_ID_RE = re.compile(r"/concalls/add-(\d+)/")


class ScreenerAnnouncementAdapter:
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

    def check(self, ticker: str, expected_company_name: str) -> AnnouncementSourceCheckResult:
        ticker = ticker.strip().upper()
        company_url = f"{BASE_URL}/company/{ticker}/consolidated/"
        try:
            resp = self._get(company_url)
        except httpx.TimeoutException:
            return AnnouncementSourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=False, error=f"Timed out fetching {company_url}")
        except httpx.HTTPError as exc:
            return AnnouncementSourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=False, error=f"HTTP error fetching {company_url}: {exc}")

        if resp.status_code != 200:
            return AnnouncementSourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=False, checked_url=company_url, error=f"{company_url} returned HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "lxml")
        title_el = soup.find("title")
        page_title = title_el.get_text() if title_el else ""
        if not _identity_matches(page_title, expected_company_name):
            return AnnouncementSourceCheckResult(
                ticker=ticker, source_name=SOURCE_NAME, ok=True, identity_verified=False, checked_url=company_url,
                error=f"Page found but company identity could not be confirmed (expected {expected_company_name!r}, page title {page_title!r}).",
            )

        match = _COMPANY_ID_RE.search(resp.text)
        if not match:
            return AnnouncementSourceCheckResult(
                ticker=ticker, source_name=SOURCE_NAME, ok=False, identity_verified=True, checked_url=company_url,
                error="Could not find screener's internal company id on the page — its page structure may have changed.",
            )
        company_id = match.group(1)

        ann_url = f"{BASE_URL}/announcements/recent/{company_id}/"
        try:
            ann_resp = self._get(ann_url)
        except httpx.HTTPError as exc:
            return AnnouncementSourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=False, identity_verified=True, checked_url=ann_url, error=str(exc))
        if ann_resp.status_code != 200:
            return AnnouncementSourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=False, identity_verified=True, checked_url=ann_url, error=f"{ann_url} returned HTTP {ann_resp.status_code}")

        announcements = self._parse_announcements(ann_resp.text, ticker, ann_url)
        return AnnouncementSourceCheckResult(ticker=ticker, source_name=SOURCE_NAME, ok=True, identity_verified=True, checked_url=ann_url, announcements=announcements)

    def _parse_announcements(self, html: str, ticker: str, page_url: str) -> list[DiscoveredAnnouncement]:
        soup = BeautifulSoup(html, "lxml")
        now = datetime.now(timezone.utc)
        out: list[DiscoveredAnnouncement] = []

        for li in soup.find_all("li"):
            a = li.find("a", href=True)
            if a is None:
                continue
            href = a["href"]
            if not href.lower().endswith(".pdf"):
                continue

            time_el = a.find("time")
            if time_el is None or not time_el.get("datetime"):
                continue  # no reliable published timestamp — skip rather than guess one
            try:
                filed_at = datetime.fromisoformat(time_el["datetime"])
            except ValueError:
                continue

            title_parts = [s for s in a.find_all(string=True, recursive=False) if s.strip()]
            title = title_parts[0].strip() if title_parts else None
            if not title:
                continue

            summary_div = a.find("div")
            one_line_summary = None
            if summary_div is not None:
                div_text = summary_div.get_text(strip=True)
                time_text = time_el.get_text(strip=True)
                remainder = div_text[len(time_text):].lstrip(" -–").strip()
                one_line_summary = remainder or None

            out.append(
                DiscoveredAnnouncement(
                    company_ticker=ticker, title=title, filed_at=filed_at, source_url=href, document_url=href,
                    one_line_summary=one_line_summary, source_name=SOURCE_NAME, discovery_timestamp=now, identity_verified=True,
                )
            )
        return out


__all__ = ["ScreenerAnnouncementAdapter", "SOURCE_NAME"]
