#!/usr/bin/env python
"""Standalone entry point for Phase 12B's document discovery job — the same
"external cron, not the in-process scheduler alone" recommendation as
scripts/run_market_data_refresh.py (see docs/FINN_PHASE_12A_REPORT.md §4).

Usage:
    PYTHONPATH=. .venv/bin/python scripts/run_document_discovery.py
"""

import json
import sys

from app.jobs.document_discovery import run_document_discovery


def main() -> int:
    result = run_document_discovery(triggered_by="scheduler")
    print(json.dumps(result, indent=2, default=str))
    if result.get("skipped"):
        return 0
    return 0 if result.get("status") in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
