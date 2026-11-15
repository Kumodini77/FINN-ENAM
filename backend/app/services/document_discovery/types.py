"""Shared types for every document-source adapter (Phase 12B). Kept adapter-
agnostic so a future IR-website adapter, a BSE-archive adapter, etc. all produce
the same shape the discovery job and review queue already know how to handle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DiscoveredCandidate:
    """One possible document, found but NOT yet downloaded or ingested.

    `identity_verified` is the adapter's own claim that it confirmed the page/
    source it read actually belongs to `company_ticker` (e.g. the page's title
    contains the company's registered name) — NOT a claim about the document
    content. A candidate with identity_verified=False must never be
    auto-ingested; it belongs in the review queue (see app.jobs.document_discovery).
    """

    company_ticker: str
    doc_type: str  # one of app.models.document.DocType's values
    title: str
    source_url: str
    source_name: str  # e.g. "screener" — which adapter found this
    reporting_period: str | None = None
    publication_date: str | None = None  # ISO date, only when genuinely known
    original_filename: str | None = None
    discovery_timestamp: datetime | None = None
    identity_verified: bool = False
    confidence_notes: list[str] = field(default_factory=list)


@dataclass
class SourceCheckResult:
    """What one adapter run for one company produced — used both to feed the
    discovery job and to persist into DocumentSourceRepository."""

    ticker: str
    source_name: str
    ok: bool
    candidates: list[DiscoveredCandidate] = field(default_factory=list)
    error: str | None = None
    identity_verified: bool = False
    checked_url: str | None = None


__all__ = ["DiscoveredCandidate", "SourceCheckResult"]
