"""Phase 12C Part 2 — announcement discovery adapter + job tests. No live
network calls: the adapter's HTTP client is mocked. The real, live-verified
parse (an actual fetch of screener.in's TCS announcements feed, confirmed
during this phase's development) is documented in
docs/FINN_ANNOUNCEMENT_COVERAGE.md, not re-fetched here.
"""

from datetime import datetime, timezone

import httpx
import pytest

from app.jobs.announcement_discovery import run_announcement_discovery
from app.repositories.announcements import AnnouncementRepository
from app.repositories.document_sources import DocumentSourceRepository
from app.repositories.job_runs import FAILED, SUCCESS, JobRunRepository
from app.repositories.json_store import JsonListStore
from app.repositories.portfolio import PortfolioRepository
from app.services.announcement_discovery.screener_announcement_adapter import ScreenerAnnouncementAdapter

COMPANY_PAGE_WITH_ID = """
<html><head><title>Tata Consultancy Services Ltd share price | About TCS</title></head>
<body><button data-url="/concalls/add-3365/">x</button></body></html>
"""

ANNOUNCEMENTS_HTML = """
<ul class="list-links">
  <li class="overflow-wrap-anywhere">
    <a href="https://www.bseindia.com/pdf/results_q2fy27.pdf" target="_blank">
      Board approves Q2 FY27 results
      <div class="ink-600 smaller"><time datetime="2026-11-09T16:59:25+05:30">9 Nov</time> - Revenue grew 8% YoY.</div>
    </a>
  </li>
  <li class="overflow-wrap-anywhere">
    <a href="https://www.bseindia.com/pdf/press_release.pdf" target="_blank">
      Press Release - New partnership announced
      <div class="ink-600 smaller"><time datetime="2026-11-04T11:00:53+05:30">4 Nov</time> - Strategic tie-up with a cloud provider.</div>
    </a>
  </li>
</ul>
"""


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    def __init__(self, responses: dict[str, _FakeResponse]):
        self.responses = responses

    def get(self, url: str) -> _FakeResponse:
        return self.responses.get(url, _FakeResponse(404))

    def close(self):
        pass


COMPANY_URL = "https://www.screener.in/company/TCS/consolidated/"
ANN_URL = "https://www.screener.in/announcements/recent/3365/"


class TestScreenerAnnouncementAdapter:
    def test_discovers_announcements_with_identity_verified(self):
        client = _FakeClient({COMPANY_URL: _FakeResponse(200, COMPANY_PAGE_WITH_ID), ANN_URL: _FakeResponse(200, ANNOUNCEMENTS_HTML)})
        adapter = ScreenerAnnouncementAdapter(client=client)

        result = adapter.check("TCS", "Tata Consultancy Services Ltd")

        assert result.ok is True
        assert result.identity_verified is True
        assert len(result.announcements) == 2
        titles = {a.title for a in result.announcements}
        assert "Board approves Q2 FY27 results" in titles
        first = next(a for a in result.announcements if a.title == "Board approves Q2 FY27 results")
        assert first.filed_at == datetime(2026, 11, 9, 16, 59, 25, tzinfo=first.filed_at.tzinfo)
        assert "Revenue grew 8% YoY" in first.one_line_summary

    def test_wrong_company_identity_is_rejected(self):
        wrong_page = COMPANY_PAGE_WITH_ID.replace("Tata Consultancy Services Ltd", "Infosys Ltd")
        client = _FakeClient({COMPANY_URL: _FakeResponse(200, wrong_page)})
        adapter = ScreenerAnnouncementAdapter(client=client)
        result = adapter.check("TCS", "Tata Consultancy Services Ltd")
        assert result.identity_verified is False
        assert result.announcements == []

    def test_timeout_is_a_clean_failure(self):
        class _TimeoutClient:
            def get(self, url):
                raise httpx.TimeoutException("timed out")

            def close(self):
                pass

        adapter = ScreenerAnnouncementAdapter(client=_TimeoutClient())
        result = adapter.check("TCS", "Tata Consultancy Services Ltd")
        assert result.ok is False
        assert "Timed out" in result.error

    def test_missing_company_id_is_reported_not_guessed(self):
        page_without_id = """<html><head><title>Tata Consultancy Services Ltd</title></head><body>no id here</body></html>"""
        client = _FakeClient({COMPANY_URL: _FakeResponse(200, page_without_id)})
        adapter = ScreenerAnnouncementAdapter(client=client)
        result = adapter.check("TCS", "Tata Consultancy Services Ltd")
        assert result.ok is False
        assert result.identity_verified is True
        assert "internal company id" in result.error


@pytest.fixture
def repos(tmp_path):
    data_dir = str(tmp_path)
    job_repo = JobRunRepository(store=JsonListStore(data_dir, "job_runs.json"))
    source_repo = DocumentSourceRepository(store=JsonListStore(data_dir, "document_sources.json"))
    portfolio_repo = PortfolioRepository(store=JsonListStore(data_dir, "portfolio.json"))
    announcement_repo = AnnouncementRepository(store=JsonListStore(data_dir, "announcements.json"))
    return job_repo, source_repo, portfolio_repo, announcement_repo


def _seed_portfolio(portfolio_repo, tickers):
    rows = [{"ticker": t, "name": t, "exchange": "NSE", "sector": "Test", "added_at": datetime.now(timezone.utc).isoformat()} for t in tickers]
    portfolio_repo._store.replace_all(rows)


class FakeAdapter:
    def __init__(self, results_by_ticker=None):
        self.results_by_ticker = results_by_ticker or {}

    def check(self, ticker, *_a, **_kw):
        from app.services.announcement_discovery.types import AnnouncementSourceCheckResult

        return self.results_by_ticker.get(ticker, AnnouncementSourceCheckResult(ticker=ticker, source_name="screener_announcements", ok=True, identity_verified=True))


def _ann(ticker, title="Board approves results", url="https://x.com/a.pdf", filed_at=None):
    from app.services.announcement_discovery.types import DiscoveredAnnouncement

    return DiscoveredAnnouncement(
        company_ticker=ticker, title=title, filed_at=filed_at or datetime(2026, 11, 9, tzinfo=timezone.utc),
        source_url=url, document_url=url, one_line_summary="A summary.", source_name="screener_announcements",
        discovery_timestamp=datetime.now(timezone.utc), identity_verified=True,
    )


class TestAnnouncementDiscoveryJob:
    def test_new_announcement_is_imported_and_classified(self, repos, monkeypatch):
        job_repo, source_repo, portfolio_repo, announcement_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        from app.services.announcement_discovery.types import AnnouncementSourceCheckResult

        adapter = FakeAdapter({"TCS": AnnouncementSourceCheckResult(ticker="TCS", source_name="screener_announcements", ok=True, identity_verified=True, announcements=[_ann("TCS", title="Board approves Q2 FY27 results")])})
        monkeypatch.setattr("app.jobs.announcement_discovery.import_announcement", lambda payload: _fake_import_result(True))

        result = run_announcement_discovery(triggered_by="manual", job_repo=job_repo, source_repo=source_repo, portfolio_repo=portfolio_repo, adapter=adapter)

        assert result["status"] == SUCCESS
        assert result["results"]["TCS"]["imported"] == 1
        checkpoint = source_repo.get("TCS", "screener_announcements")
        assert checkpoint.health == "healthy"

    def test_duplicate_announcement_is_not_reimported(self, repos, monkeypatch):
        job_repo, source_repo, portfolio_repo, announcement_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        from app.services.announcement_discovery.types import AnnouncementSourceCheckResult

        adapter = FakeAdapter({"TCS": AnnouncementSourceCheckResult(ticker="TCS", source_name="screener_announcements", ok=True, identity_verified=True, announcements=[_ann("TCS")])})
        monkeypatch.setattr("app.jobs.announcement_discovery.import_announcement", lambda payload: _fake_import_result(False))

        result = run_announcement_discovery(triggered_by="manual", job_repo=job_repo, source_repo=source_repo, portfolio_repo=portfolio_repo, adapter=adapter)
        assert result["results"]["TCS"]["imported"] == 0
        assert result["results"]["TCS"]["duplicates"] == 1

    def test_unverified_identity_imports_nothing(self, repos):
        job_repo, source_repo, portfolio_repo, announcement_repo = repos
        _seed_portfolio(portfolio_repo, ["TMPV"])
        from app.services.announcement_discovery.types import AnnouncementSourceCheckResult

        adapter = FakeAdapter({"TMPV": AnnouncementSourceCheckResult(ticker="TMPV", source_name="screener_announcements", ok=True, identity_verified=False, error="identity mismatch")})
        result = run_announcement_discovery(triggered_by="manual", job_repo=job_repo, source_repo=source_repo, portfolio_repo=portfolio_repo, adapter=adapter)
        assert result["results"]["TMPV"]["imported"] == 0
        assert result["results"]["TMPV"]["status"] == "failed"

    def test_one_company_source_failure_does_not_block_another(self, repos, monkeypatch):
        job_repo, source_repo, portfolio_repo, announcement_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS", "BROKEN"])
        from app.services.announcement_discovery.types import AnnouncementSourceCheckResult

        adapter = FakeAdapter(
            {
                "TCS": AnnouncementSourceCheckResult(ticker="TCS", source_name="screener_announcements", ok=True, identity_verified=True, announcements=[_ann("TCS")]),
                "BROKEN": AnnouncementSourceCheckResult(ticker="BROKEN", source_name="screener_announcements", ok=False, error="connection refused"),
            }
        )
        monkeypatch.setattr("app.jobs.announcement_discovery.import_announcement", lambda payload: _fake_import_result(True))
        result = run_announcement_discovery(triggered_by="manual", job_repo=job_repo, source_repo=source_repo, portfolio_repo=portfolio_repo, adapter=adapter)
        assert result["results"]["TCS"]["imported"] == 1
        assert result["results"]["BROKEN"]["status"] == "failed"
        assert result["status"] == "partial"

    def test_duplicate_run_prevention(self, repos):
        job_repo, source_repo, portfolio_repo, announcement_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        job_repo.start_run("announcement_discovery", "manual")
        result = run_announcement_discovery(triggered_by="manual", job_repo=job_repo, source_repo=source_repo, portfolio_repo=portfolio_repo, adapter=FakeAdapter())
        assert result.get("skipped") is True

    def test_adhoc_companies_never_appear(self, repos):
        job_repo, source_repo, portfolio_repo, announcement_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        result = run_announcement_discovery(triggered_by="manual", job_repo=job_repo, source_repo=source_repo, portfolio_repo=portfolio_repo, adapter=FakeAdapter())
        assert "ETERNAL" not in result["results"]
        assert list(result["results"].keys()) == ["TCS"]


def _fake_import_result(created: bool):
    from app.models.announcement import AnnouncementCategory

    return type(
        "R", (), {
            "created": created, "category": AnnouncementCategory.RESULTS, "priority": "high",
            "priority_score": 90.0, "announcement_id": "ann-1", "message": "ok",
        },
    )()
