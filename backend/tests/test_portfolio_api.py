"""API-level tests for /api/portfolio and GET /api/companies/{ticker}/research-readiness."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import CompanyLookupError
from app.main import app
from app.services.company_resolution import ResolvedCompany

client = TestClient(app)


def _fake_repo(tickers=None, companies=None):
    repo = MagicMock()
    repo.list_tickers.return_value = tickers or {"HDFCBANK"}
    repo.list_companies.return_value = companies or [{"ticker": "HDFCBANK", "name": "HDFC Bank Ltd", "exchange": "NSE", "sector": "Banking"}]
    return repo


def test_list_portfolio_returns_companies_and_count():
    with patch("app.api.portfolio.PortfolioRepository", return_value=_fake_repo()):
        resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["companies"][0]["ticker"] == "HDFCBANK"


def test_add_valid_ticker_to_portfolio_returns_201():
    fake_repo = _fake_repo()
    fake_repo.add_ticker.return_value = ResolvedCompany(
        ticker="WIPRO", name="Wipro Ltd", exchange="NSE", sector="IT Services", yfinance_symbol="WIPRO.NS", is_seed_portfolio=True
    )
    with patch("app.api.portfolio.PortfolioRepository", return_value=fake_repo):
        resp = client.post("/api/portfolio", json={"ticker": "WIPRO"})
    assert resp.status_code == 201
    assert resp.json()["ticker"] == "WIPRO"


def test_add_invalid_ticker_returns_422_not_fabricated():
    fake_repo = _fake_repo()
    fake_repo.add_ticker.side_effect = CompanyLookupError("not a real NSE equity")
    with patch("app.api.portfolio.PortfolioRepository", return_value=fake_repo):
        resp = client.post("/api/portfolio", json={"ticker": "ZZZZINVALID"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "company_lookup_failed"


def test_remove_existing_portfolio_member_returns_204():
    fake_repo = _fake_repo()
    fake_repo.remove_ticker.return_value = True
    with patch("app.api.portfolio.PortfolioRepository", return_value=fake_repo):
        resp = client.delete("/api/portfolio/HDFCBANK")
    assert resp.status_code == 204


def test_remove_non_member_returns_404():
    fake_repo = _fake_repo()
    fake_repo.remove_ticker.return_value = False
    with patch("app.api.portfolio.PortfolioRepository", return_value=fake_repo):
        resp = client.delete("/api/portfolio/NOTAMEMBER")
    assert resp.status_code == 404


def test_research_readiness_endpoint_reports_real_status():
    from app.services.research_readiness import STATUS_READY, ResearchReadiness

    fake_readiness = ResearchReadiness(
        ticker="HDFCBANK", company_name="HDFC Bank Ltd", is_known_company=True, is_portfolio_member=True,
        has_retrievable_documents=True, documents=[], status=STATUS_READY, message="1 completed document(s) available.",
    )
    with patch("app.api.companies.check_research_readiness", return_value=fake_readiness):
        resp = client.get("/api/companies/HDFCBANK/research-readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["is_portfolio_member"] is True
    assert body["has_retrievable_documents"] is True
