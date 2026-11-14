#!/usr/bin/env python3
"""Ingest a single PDF (annual report / concall transcript / investor presentation)
into the RAG corpus: extract, classify, chunk, embed (local MiniLM), and persist.

Usage:
    cd backend
    .venv/bin/python scripts/ingest_document.py \\
        --pdf path/to/file.pdf \\
        --ticker RELIANCE \\
        --doc-type annual_report \\
        --reporting-period FY2025-26 \\
        --source-url https://example.invalid/ar.pdf \\
        --title "Reliance FY2025-26 Annual Report"

Requires migrations/007 and migrations/008 to already be applied against the
configured Supabase project (or runs against the JSON fallback store if Supabase
isn't configured/reachable). Does not bulk-ingest - exactly one PDF per invocation.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.exceptions import DocumentAlreadyClaimedError, DocumentExistingConflictError, DocumentMetadataConflictError
from app.models.document import DocType
from app.repositories.company_lookup import get_or_register_company_id
from app.repositories.documents import DocumentRepository
from app.services.embeddings import get_embedding_provider
from app.services.ingestion import IngestionError, ingest_document


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", required=True, help="Path to the source PDF file")
    parser.add_argument("--ticker", required=True, help="NSE ticker, e.g. RELIANCE")
    parser.add_argument("--doc-type", required=True, choices=[d.value for d in DocType])
    parser.add_argument("--reporting-period", default=None, help="e.g. FY2025-26 or Q1FY27")
    parser.add_argument("--source-url", required=True, help="Original URL the PDF was fetched from")
    parser.add_argument("--title", default=None, help="Human-readable title, shown only in this script's summary")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"ERROR: file not found: {pdf_path}")
        sys.exit(1)
    if pdf_path.suffix.lower() != ".pdf":
        print(f"ERROR: only .pdf files are supported, got: {pdf_path}")
        sys.exit(1)
    if pdf_path.stat().st_size == 0:
        print(f"ERROR: file is empty: {pdf_path}")
        sys.exit(1)

    print("FINN document ingestion")
    print(f"  file:              {pdf_path} ({pdf_path.stat().st_size:,} bytes)")
    print(f"  ticker:            {args.ticker}")
    print(f"  doc_type:          {args.doc_type}")
    print(f"  reporting_period:  {args.reporting_period or '(none)'}")
    print(f"  source_url:        {args.source_url}")
    if args.title:
        print(f"  title:             {args.title}")

    try:
        company_id = get_or_register_company_id(args.ticker)
    except Exception as e:
        print(f"ERROR: could not resolve ticker '{args.ticker}': {e}")
        sys.exit(1)

    repo = DocumentRepository()
    provider = get_embedding_provider()

    try:
        result = ingest_document(
            file_path=str(pdf_path),
            company_id=company_id,
            company_ticker=args.ticker.upper(),
            doc_type=args.doc_type,
            reporting_period=args.reporting_period,
            original_source_url=args.source_url,
            repo=repo,
            embedding_provider=provider,
        )
    except (DocumentMetadataConflictError, DocumentExistingConflictError, DocumentAlreadyClaimedError) as e:
        print(f"CONFLICT: {e.message}")
        sys.exit(2)
    except IngestionError as e:
        print(f"FAILED: {e}")
        sys.exit(3)

    print()
    print("ALREADY INGESTED (reused existing completed document)" if result.reused else "SUCCESS")
    print(f"  document_id: {result.document.id}")
    print(f"  status:      {result.document.ingestion_status.value}")
    print(f"  chunks:      {result.chunk_count}")


if __name__ == "__main__":
    main()
