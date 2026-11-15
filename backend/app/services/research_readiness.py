"""Reports, for any ticker, the four separate facts Task 4's architecture
separation requires FINN to never conflate:
  1. Is this a known/registrable company at all (company registry)?
  2. Is it a portfolio member (Push monitoring target)?
  3. Does it have indexed primary-source documents (document availability)?
  4. Can Pull actually retrieve from it right now?

This never gates Pull itself (app.services.hybrid_retrieval doesn't call this) -
it exists purely to give an honest, structured answer to "can I research this
company and why/why not" rather than making a caller infer it from a raw
CompanyLookupError or an empty evidence list.
"""

from dataclasses import dataclass, field

from app.core.exceptions import CompanyLookupError
from app.models.document import IngestionStatus
from app.repositories.documents import DocumentRepository
from app.repositories.portfolio import PortfolioRepository
from app.services.company_resolution import resolve_company

STATUS_INVALID_TICKER = "invalid_ticker"
STATUS_KNOWN_NO_DOCUMENTS = "known_no_documents"
STATUS_DOCUMENTS_NOT_RETRIEVABLE = "documents_not_retrievable"
STATUS_READY = "ready"


@dataclass
class DocumentCoverageSummary:
    doc_type: str
    reporting_period: str | None
    ingestion_status: str


@dataclass
class ResearchReadiness:
    ticker: str
    company_name: str | None
    is_known_company: bool
    is_portfolio_member: bool
    has_retrievable_documents: bool
    documents: list[DocumentCoverageSummary] = field(default_factory=list)
    status: str = STATUS_INVALID_TICKER
    message: str = ""


def check_research_readiness(
    ticker: str,
    *,
    portfolio_repo: PortfolioRepository | None = None,
    document_repo: DocumentRepository | None = None,
    verify=None,
) -> ResearchReadiness:
    portfolio_repo = portfolio_repo or PortfolioRepository()
    document_repo = document_repo or DocumentRepository()

    try:
        resolved = resolve_company(ticker, verify=verify)
    except CompanyLookupError as e:
        return ResearchReadiness(
            ticker=ticker.strip().upper(), company_name=None, is_known_company=False, is_portfolio_member=False,
            has_retrievable_documents=False, status=STATUS_INVALID_TICKER,
            message=f"'{ticker.strip().upper()}' could not be verified as a real, currently-listed NSE equity: {e.message}",
        )

    is_portfolio_member = resolved.ticker in portfolio_repo.list_tickers()
    all_documents = document_repo.list_documents_for_ticker(resolved.ticker)
    completed = [d for d in all_documents if d.ingestion_status == IngestionStatus.COMPLETED]
    summaries = [
        DocumentCoverageSummary(doc_type=d.doc_type.value, reporting_period=d.reporting_period, ingestion_status=d.ingestion_status.value)
        for d in all_documents
    ]

    if completed:
        status = STATUS_READY
        message = f"{len(completed)} completed document(s) available - Pull retrieval is ready for this company."
    elif all_documents:
        status = STATUS_DOCUMENTS_NOT_RETRIEVABLE
        message = (
            f"{len(all_documents)} document(s) are on record for this company, but none have completed ingestion "
            "(pending/in-progress/failed) - none are currently retrievable by Pull."
        )
    else:
        status = STATUS_KNOWN_NO_DOCUMENTS
        message = "Company is recognized, but no documents have been ingested yet - ingest at least one to enable Pull."

    return ResearchReadiness(
        ticker=resolved.ticker, company_name=resolved.name, is_known_company=True,
        is_portfolio_member=is_portfolio_member, has_retrievable_documents=bool(completed),
        documents=summaries, status=status, message=message,
    )
