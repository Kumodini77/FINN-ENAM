"""Shared types for announcement-source adapters (Phase 12C Part 2) — the
announcement-side counterpart to app.services.document_discovery.types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DiscoveredAnnouncement:
    company_ticker: str
    title: str
    filed_at: datetime
    source_url: str
    source_name: str
    document_url: str | None = None
    one_line_summary: str | None = None
    discovery_timestamp: datetime | None = None
    identity_verified: bool = False


@dataclass
class AnnouncementSourceCheckResult:
    ticker: str
    source_name: str
    ok: bool
    announcements: list[DiscoveredAnnouncement] = field(default_factory=list)
    error: str | None = None
    identity_verified: bool = False
    checked_url: str | None = None


__all__ = ["DiscoveredAnnouncement", "AnnouncementSourceCheckResult"]
