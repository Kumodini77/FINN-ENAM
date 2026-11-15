#!/usr/bin/env python3
"""Ingest multiple documents - across one or several companies - from a JSON
manifest, reusing the exact same single-document pipeline as
scripts/ingest_document.py (ingest_one_document()) for every entry. No separate
ingestion logic exists here.

One entry failing (a bad file, an unverifiable ticker, a conflict) never stops
the rest - each entry is attempted independently and the run ends with a full
summary. This is a reviewed, manifest-driven batch, not an automated/aggressive
scrape: every entry must name a real local file and a real source URL you
already have, exactly like the single-document CLI.

Usage:
    cd backend
    .venv/bin/python scripts/ingest_documents_batch.py path/to/manifest.json

Manifest shape (a JSON list; see scripts/ingest_manifest_template.json):
[
  {
    "pdf": "path/to/file.pdf",
    "ticker": "RELIANCE",
    "doc_type": "annual_report",
    "reporting_period": "FY2012-13",
    "source_url": "https://example.invalid/ar.pdf"
  },
  ...
]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.document import DocType
from scripts.ingest_document import ingest_one_document

_REQUIRED_FIELDS = {"pdf", "ticker", "doc_type", "source_url"}


def _validate_entry(entry: dict, index: int) -> str | None:
    """Returns an error message if the entry is malformed, else None."""
    missing = _REQUIRED_FIELDS - entry.keys()
    if missing:
        return f"entry {index}: missing required field(s): {', '.join(sorted(missing))}"
    if entry["doc_type"] not in [d.value for d in DocType]:
        return f"entry {index}: invalid doc_type '{entry['doc_type']}' (expected one of {[d.value for d in DocType]})"
    return None


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: ingest_documents_batch.py path/to/manifest.json")
        sys.exit(1)

    manifest_path = Path(sys.argv[1])
    if not manifest_path.is_file():
        print(f"ERROR: manifest not found: {manifest_path}")
        sys.exit(1)

    try:
        entries = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR: manifest is not valid JSON: {e}")
        sys.exit(1)

    if not isinstance(entries, list):
        print("ERROR: manifest must be a JSON list of entries.")
        sys.exit(1)

    print(f"FINN batch document ingestion - {len(entries)} entrie(s) in manifest")
    print()

    results = []
    for i, entry in enumerate(entries):
        if "_comment" in entry:
            continue
        validation_error = _validate_entry(entry, i)
        if validation_error:
            print(f"[{i}] SKIPPED - {validation_error}")
            results.append({"index": i, "status": "invalid_entry", "message": validation_error})
            continue

        print(f"[{i}] {entry['ticker']} — {entry['pdf']}")
        outcome = ingest_one_document(
            pdf_path=entry["pdf"],
            ticker=entry["ticker"],
            doc_type=entry["doc_type"],
            reporting_period=entry.get("reporting_period"),
            source_url=entry["source_url"],
        )
        print(f"    {outcome.status.upper()}: {outcome.message}")
        results.append(
            {
                "index": i, "ticker": entry["ticker"], "status": outcome.status, "message": outcome.message,
                "document_id": outcome.document_id, "chunk_count": outcome.chunk_count,
            }
        )

    print()
    print("=== Summary ===")
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")

    failed = [r for r in results if r["status"] in ("failed", "invalid_entry")]
    if failed:
        print()
        print("Failed/invalid entries:")
        for r in failed:
            print(f"  [{r['index']}] {r.get('ticker', '?')}: {r['message']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
