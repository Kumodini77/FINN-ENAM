#!/usr/bin/env python
"""Standalone entry point for Phase 12C's announcement discovery job — same
external-cron recommendation as scripts/run_market_data_refresh.py and
scripts/run_document_discovery.py.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/run_announcement_discovery.py
"""

import json
import sys

from app.jobs.announcement_discovery import run_announcement_discovery


def main() -> int:
    result = run_announcement_discovery(triggered_by="scheduler")
    print(json.dumps(result, indent=2, default=str))
    if result.get("skipped"):
        return 0
    return 0 if result.get("status") in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
