#!/usr/bin/env python
"""Standalone entry point for the EOD market-data refresh job — the recommended
production trigger (see docs/FINN_PHASE_12A_REPORT.md): point an externally-managed
scheduler (e.g. a Render Cron Job, a GitHub Actions scheduled workflow, or any host
cron) at this script instead of relying solely on the in-process APScheduler, since
a one-off process invocation runs and exits regardless of whether the main web
process happens to be up at the scheduled time.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/run_market_data_refresh.py

Exit code is 0 for "success" or "partial" (so an operator can see partial failures
without the cron infrastructure itself alerting on every imperfect run), and 1 for
"failed" or a crash, so the outer scheduler's own failure/alerting does fire when
the whole batch genuinely failed.
"""

import json
import sys

from app.jobs.market_data_refresh import run_market_data_refresh


def main() -> int:
    result = run_market_data_refresh(triggered_by="scheduler")
    print(json.dumps(result, indent=2, default=str))
    if result.get("skipped"):
        return 0
    return 0 if result.get("status") in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
