from pydantic import BaseModel, Field


class CompanyOut(BaseModel):
    ticker: str
    name: str
    exchange: str
    sector: str
    yfinance_symbol: str
    is_seed_portfolio: bool


class CompanyListResponse(BaseModel):
    companies: list[CompanyOut]
    count: int = Field(description="Number of companies returned")
