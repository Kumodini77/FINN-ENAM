from pydantic import BaseModel


class DocumentCoverageOut(BaseModel):
    doc_type: str
    reporting_period: str | None
    ingestion_status: str


class ResearchReadinessOut(BaseModel):
    ticker: str
    company_name: str | None
    is_known_company: bool
    is_portfolio_member: bool
    has_retrievable_documents: bool
    documents: list[DocumentCoverageOut]
    status: str
    message: str
