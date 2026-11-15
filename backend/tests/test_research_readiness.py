"""Explicit tests for all six ENAM Task-5 validation scenarios, using
app.services.research_readiness.check_research_readiness() against isolated
JSON-fallback repositories (real logic, no live Supabase)."""

from datetime import datetime, timezone

import pytest

from app.models.document import Document
from app.repositories.documents import DocumentRepository
from app.repositories.json_store import JsonListStore
from app.repositories.portfolio import PortfolioRepository
from app.services.research_readiness import (
    STATUS_DOCUMENTS_NOT_RETRIEVABLE,
    STATUS_INVALID_TICKER,
    STATUS_KNOWN_NO_DOCUMENTS,
    STATUS_READY,
    check_research_readiness,
)


@pytest.fixture
def portfolio_repo(tmp_path):
    return PortfolioRepository(store=JsonListStore(str(tmp_path), "portfolio.json"))


@pytest.fixture
def document_repo(tmp_path):
    return DocumentRepository(
        store=JsonListStore(str(tmp_path), "documents.json"),
        chunk_store=JsonListStore(str(tmp_path), "document_chunks.json"),
    )


def _completed_doc(ticker, repo) -> Document:
    doc = Document.model_validate(
        dict(
            id=f"doc-{ticker}", company_id=ticker, company_ticker=ticker, doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url=f"https://x.invalid/{ticker}.pdf",
            fetched_at=datetime.now(timezone.utc), file_sha256="a" * 64,
        )
    )
    created, _ = repo.resolve_or_create(doc)
    repo.claim_for_ingestion(created.id)
    repo.mark_completed(created.id)
    return created


# 1. A portfolio company that has indexed documents.
def test_portfolio_company_with_indexed_documents_is_ready(portfolio_repo, document_repo):
    portfolio_repo.list_tickers()  # bootstrap - HDFCBANK is in the default seed list
    _completed_doc("HDFCBANK", document_repo)

    readiness = check_research_readiness("HDFCBANK", portfolio_repo=portfolio_repo, document_repo=document_repo)

    assert readiness.is_known_company is True
    assert readiness.is_portfolio_member is True
    assert readiness.has_retrievable_documents is True
    assert readiness.status == STATUS_READY


# 2. A portfolio company with no indexed documents.
def test_portfolio_company_without_documents_is_known_but_not_ready(portfolio_repo, document_repo):
    portfolio_repo.list_tickers()  # bootstrap - SBIN is in the default seed list, no documents ingested

    readiness = check_research_readiness("SBIN", portfolio_repo=portfolio_repo, document_repo=document_repo)

    assert readiness.is_known_company is True
    assert readiness.is_portfolio_member is True
    assert readiness.has_retrievable_documents is False
    assert readiness.status == STATUS_KNOWN_NO_DOCUMENTS


# 3. An ad-hoc company outside the portfolio with indexed documents.
def test_ad_hoc_company_outside_portfolio_with_documents_is_ready(portfolio_repo, document_repo):
    portfolio_repo.list_tickers()  # bootstrap - COALINDIA is deliberately NOT in PORTFOLIO
    _completed_doc("COALINDIA", document_repo)

    readiness = check_research_readiness("COALINDIA", portfolio_repo=portfolio_repo, document_repo=document_repo)

    assert readiness.is_known_company is True  # it's a seeded ad-hoc company
    assert readiness.is_portfolio_member is False  # NOT in the portfolio
    assert readiness.has_retrievable_documents is True  # but still fully researchable


# 4. An unknown but valid NSE ticker (not in either seed list, verified live).
def test_unknown_but_valid_ticker_is_known_after_verification_no_documents_yet(portfolio_repo, document_repo):
    portfolio_repo.list_tickers()

    def _verify(_ticker):
        return {"name": "Punjab National Bank", "exchange": "NSE", "sector": "Banking", "yfinance_symbol": "PNB.NS"}

    readiness = check_research_readiness("PNB", portfolio_repo=portfolio_repo, document_repo=document_repo, verify=_verify)

    assert readiness.is_known_company is True  # resolved via real (mocked) verification, not seeded
    assert readiness.is_portfolio_member is False
    assert readiness.has_retrievable_documents is False
    assert readiness.status == STATUS_KNOWN_NO_DOCUMENTS


# 5. An invalid ticker.
def test_invalid_ticker_is_reported_honestly_not_fabricated(portfolio_repo, document_repo):
    def _failing_verify(_ticker):
        from app.core.exceptions import CompanyLookupError

        raise CompanyLookupError("could not verify as a real, currently-listed equity")

    readiness = check_research_readiness("ZZZZINVALID", portfolio_repo=portfolio_repo, document_repo=document_repo, verify=_failing_verify)

    assert readiness.is_known_company is False
    assert readiness.is_portfolio_member is False
    assert readiness.has_retrievable_documents is False
    assert readiness.status == STATUS_INVALID_TICKER
    assert readiness.message  # a real, non-empty explanation, never silent


# 6. A company whose documents cannot currently be retrieved (exist but not completed).
def test_company_with_only_non_completed_documents_is_not_retrievable(portfolio_repo, document_repo):
    portfolio_repo.list_tickers()
    doc = Document.model_validate(
        dict(
            id="doc-tcs", company_id="TCS", company_ticker="TCS", doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url="https://x.invalid/tcs.pdf",
            fetched_at=datetime.now(timezone.utc), file_sha256="b" * 64,
        )
    )
    created, _ = document_repo.resolve_or_create(doc)
    document_repo.claim_for_ingestion(created.id)  # claimed but never completed - stuck/failed

    readiness = check_research_readiness("TCS", portfolio_repo=portfolio_repo, document_repo=document_repo)

    assert readiness.is_known_company is True
    assert readiness.has_retrievable_documents is False
    assert readiness.status == STATUS_DOCUMENTS_NOT_RETRIEVABLE
    assert len(readiness.documents) == 1
    assert readiness.documents[0].ingestion_status == "extracting"
