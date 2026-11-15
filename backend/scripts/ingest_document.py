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
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.exceptions import DocumentAlreadyClaimedError, DocumentExistingConflictError, DocumentMetadataConflictError
from app.models.document import DocType
from app.repositories.company_lookup import get_or_register_company_id
from app.repositories.documents import DocumentRepository
from app.services.embeddings import get_embedding_provider
from app.services.ingestion import IngestionError, ingest_document


@dataclass
class OneDocumentOutcome:
    """Structured result of a single-document ingestion attempt - used by both
    this CLI's main() and scripts/ingest_documents_batch.py, so the real
    validate -> resolve-ticker -> ingest sequence (and its exact exception
    handling) exists in exactly one place."""

    status: str  # "success" | "reused" | "conflict" | "failed"
    message: str
    document_id: str | None = None
    chunk_count: int | None = None


def ingest_one_document(
    *, pdf_path: str, ticker: str, doc_type: str, reporting_period: str | None, source_url: str
) -> OneDocumentOutcome:
    """The reusable core of a single document's ingestion: file validation,
    ticker resolution (auto-registers via verified yfinance metadata if the
    ticker isn't already a known company - never fabricated), and the ingest
    call itself. Never raises - every outcome, including a failure, comes back
    as a OneDocumentOutcome so a caller looping over many documents/companies
    can continue past one failure without a try/except of its own."""
    path = Path(pdf_path)
    if not path.is_file():
        return OneDocumentOutcome(status="failed", message=f"file not found: {path}")
    if path.suffix.lower() != ".pdf":
        return OneDocumentOutcome(status="failed", message=f"only .pdf files are supported, got: {path}")
    if path.stat().st_size == 0:
        return OneDocumentOutcome(status="failed", message=f"file is empty: {path}")

    try:
        company_id = get_or_register_company_id(ticker)
    except Exception as e:
        return OneDocumentOutcome(status="failed", message=f"could not resolve ticker '{ticker}': {e}")

    repo = DocumentRepository()
    provider = get_embedding_provider()

    try:
        result = ingest_document(
            file_path=str(path),
            company_id=company_id,
            company_ticker=ticker.strip().upper(),
            doc_type=doc_type,
            reporting_period=reporting_period,
            original_source_url=source_url,
            repo=repo,
            embedding_provider=provider,
        )
    except (DocumentMetadataConflictError, DocumentExistingConflictError, DocumentAlreadyClaimedError) as e:
        return OneDocumentOutcome(status="conflict", message=e.message)
    except IngestionError as e:
        return OneDocumentOutcome(status="failed", message=str(e))

    return OneDocumentOutcome(
        status="reused" if result.reused else "success",
        message="already ingested (reused existing completed document)" if result.reused else "ingested successfully",
        document_id=result.document.id,
        chunk_count=result.chunk_count,
    )


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
    print("FINN document ingestion")
    print(f"  file:              {args.pdf}")
    print(f"  ticker:            {args.ticker}")
    print(f"  doc_type:          {args.doc_type}")
    print(f"  reporting_period:  {args.reporting_period or '(none)'}")
    print(f"  source_url:        {args.source_url}")
    if args.title:
        print(f"  title:             {args.title}")

    outcome = ingest_one_document(
        pdf_path=args.pdf, ticker=args.ticker, doc_type=args.doc_type,
        reporting_period=args.reporting_period, source_url=args.source_url,
    )

    print()
    if outcome.status == "failed":
        print(f"FAILED: {outcome.message}")
        sys.exit(3)
    if outcome.status == "conflict":
        print(f"CONFLICT: {outcome.message}")
        sys.exit(2)
    print("ALREADY INGESTED (reused existing completed document)" if outcome.status == "reused" else "SUCCESS")
    print(f"  document_id: {outcome.document_id}")
    print(f"  chunks:      {outcome.chunk_count}")


if __name__ == "__main__":
    main()
