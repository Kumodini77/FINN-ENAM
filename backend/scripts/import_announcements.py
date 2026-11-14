#!/usr/bin/env python3
"""Reusable manual filing ingestion CLI (requirements.md Module 2).

Usage:
    cd backend
    .venv/bin/python scripts/import_announcements.py path/to/your_filings.json

The input file is a JSON list of objects matching AnnouncementImportRequest
(see backend/scripts/announcement_import_template.json for the exact shape and
backend/app/schemas/announcement_import.py for field docs). Any object with a
"_comment" key is skipped, so the template file can be copied and edited in place.

This calls the import service directly (no running server required) and prints a
per-item result, including which ones were skipped as duplicates.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas.announcement_import import AnnouncementImportRequest
from app.services.announcement_import import UnknownTickerError, import_announcement


def main(file_path: str) -> None:
    data = json.loads(Path(file_path).read_text())
    if not isinstance(data, list):
        print("Input file must contain a JSON list of filing objects.")
        sys.exit(1)

    created, duplicates, errors = 0, 0, 0
    for i, item in enumerate(data):
        if "_comment" in item:
            continue
        try:
            payload = AnnouncementImportRequest.model_validate(item)
            result = import_announcement(payload)
            if result.created:
                created += 1
                print(f"[{i}] CREATED  {payload.ticker} — {payload.title[:60]} -> {result.category.value} / {result.priority}")
            else:
                duplicates += 1
                print(f"[{i}] DUPLICATE {payload.ticker} — {payload.title[:60]} (already imported)")
        except UnknownTickerError as e:
            errors += 1
            print(f"[{i}] ERROR — {e.message}")
        except Exception as e:
            errors += 1
            print(f"[{i}] ERROR — {type(e).__name__}: {e}")

    print(f"\nDone. created={created} duplicates={duplicates} errors={errors}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-filings.json>")
        sys.exit(1)
    main(sys.argv[1])
