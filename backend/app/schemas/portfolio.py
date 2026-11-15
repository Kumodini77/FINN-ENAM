from pydantic import BaseModel


class PortfolioCompanyOut(BaseModel):
    ticker: str
    name: str
    exchange: str
    sector: str | None


class PortfolioListResponse(BaseModel):
    companies: list[PortfolioCompanyOut]
    count: int


class PortfolioAddRequest(BaseModel):
    ticker: str
