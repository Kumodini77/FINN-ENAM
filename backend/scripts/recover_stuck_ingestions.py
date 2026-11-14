#!/usr/bin/env python3
"""Finds documents stuck mid-ingestion (status extracting/chunking/embedding with a
stale ingestion_claimed_at - a crashed worker never finished) and marks them failed
so a normal retry can claim them again.

Default is DRY RUN - prints what it would do and changes nothing. Pass --apply to
actually mutate records, and you will be asked for an additional explicit
confirmation before any destructive cleanup happens. Never touches 'completed'
documents, and never touches a document whose claim is still fresh (within the
stale-threshold window) - only a genuinely stuck document is ever affected, and every
mutation is scoped to that exact document's id (and its chunks' document_id).

Usage:
    cd backend
    .venv/bin/python scripts/recover_stuck_ingestions.py                 # dry run
    .venv/bin/python scripts/recover_stuck_ingestions.py --apply         # apply (asks to confirm)
    .venv/bin/python scripts/recover_stuck_ingestions.py --apply --stale-minutes 90
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.repositories.documents import DEFAULT_STALE_CLAIM_MINUTES, DocumentRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually mark documents failed and clean up their chunks")
    parser.add_argument("--stale-minutes", type=int, default=DEFAULT_STALE_CLAIM_MINUTES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo = DocumentRepository()
    stale = repo.find_stale_claims(stale_minutes=args.stale_minutes)

    if not stale:
        print(f"No stuck ingestions found (stale threshold: {args.stale_minutes} minutes).")
        return

    print(f"Found {len(stale)} document(s) stuck mid-ingestion (stale threshold: {args.stale_minutes} minutes):")
    for doc in stale:
        chunks = repo.get_chunks_for_document(doc.id)
        print(
            f"  - {doc.id}  ticker={doc.company_ticker}  doc_type={doc.doc_type.value}  "
            f"status={doc.ingestion_status.value}  claimed_at={doc.ingestion_claimed_at}  "
            f"existing_chunks={len(chunks)}"
        )

    if not args.apply:
        print()
        print("DRY RUN - no changes made. Re-run with --apply to mark these failed and clean up their chunks.")
        return

    print()
    confirm = input(
        f"Type 'yes' to mark these {len(stale)} document(s) FAILED and delete their partial chunks: "
    ).strip()
    if confirm != "yes":
        print("Aborted - no changes made.")
        return

    recovered, failed_to_recover = [], []
    for doc in stale:
        try:
            repo.mark_failed(doc.id, f"Recovered from a stale claim (claimed_at={doc.ingestion_claimed_at}, crashed worker).")
            print(f"  marked failed: {doc.id}")
            recovered.append(doc.id)
        except Exception as e:
            # One document's recovery failing (e.g. a transient Supabase error)
            # must not abort recovery of the others, and must not be silently
            # swallowed either - report it and keep going.
            print(f"  ERROR recovering {doc.id}: {e}")
            failed_to_recover.append(doc.id)

    print()
    print(f"Done. {len(recovered)} of {len(stale)} document(s) marked failed and ready for a normal retry.")
    if failed_to_recover:
        print(f"  {len(failed_to_recover)} document(s) could NOT be recovered: {', '.join(failed_to_recover)}")
        print("  Re-run this script to retry them.")


if __name__ == "__main__":
    main()
