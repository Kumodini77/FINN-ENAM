"""Phase 12B — orchestration tests for app.jobs.document_discovery.
run_document_discovery(). Adapters, embedding provider, and the downloader are
all injected fakes — no live network calls, no real PDF downloads, no real
embedding model load, exactly like Phase 12A's market-data job tests.

The genuine, live, end-to-end proof (real screener.in discovery -> real
download -> real ingestion -> real Pull retrieval, for TCS, against the live
Supabase project) is documented with its actual results in
docs/FINN_PHASE_12B_REPORT.md, not re-run here.
"""

from datetime import datetime, timezone

import pytest

from app.jobs.document_discovery import DownloadError, run_document_discovery
from app.models.document import DocumentChunk
from app.repositories.document_review_queue import ReviewQueueRepository
from app.repositories.document_sources import DocumentSourceRepository
from app.repositories.documents import DocumentRepository
from app.repositories.job_runs import FAILED, PARTIAL, SUCCESS, JobRunRepository
from app.repositories.json_store import JsonListStore
from app.repositories.portfolio import PortfolioRepository
from app.services.document_discovery.types import DiscoveredCandidate, SourceCheckResult

PDF_BYTES = b"%PDF-1.4\n%fake but valid header\n%%EOF"


class FakeEmbeddingProvider:
    model_name = "fake-model"
    model_revision = "v1"

    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeAdapter:
    """Stands in for both ScreenerSourceAdapter and IRWebsiteSourceAdapter —
    both expose a `.check(...)` the job calls positionally/by-kwarg-compatible
    way; this fake just returns whatever SourceCheckResult the test configured
    for that ticker."""

    def __init__(self, results_by_ticker: dict[str, SourceCheckResult] | None = None, source_name="screener"):
        self.results_by_ticker = results_by_ticker or {}
        self.source_name = source_name
        self.calls: list[str] = []

    def check(self, ticker, *_args, **_kwargs):
        self.calls.append(ticker)
        if ticker in self.results_by_ticker:
            return self.results_by_ticker[ticker]
        return SourceCheckResult(ticker=ticker, source_name=self.source_name, ok=True, identity_verified=True, candidates=[])


def _candidate(ticker, doc_type="concall_transcript", title="T", url="https://x.com/doc.pdf", period="OCT2026", identity_verified=True):
    return DiscoveredCandidate(
        company_ticker=ticker, doc_type=doc_type, title=title, source_url=url, source_name="screener",
        reporting_period=period, discovery_timestamp=datetime.now(timezone.utc), identity_verified=identity_verified,
    )


@pytest.fixture
def repos(tmp_path):
    data_dir = str(tmp_path)
    job_repo = JobRunRepository(store=JsonListStore(data_dir, "job_runs.json"))
    document_repo = DocumentRepository(store=JsonListStore(data_dir, "documents.json"), chunk_store=JsonListStore(data_dir, "document_chunks.json"))
    source_repo = DocumentSourceRepository(store=JsonListStore(data_dir, "document_sources.json"))
    review_repo = ReviewQueueRepository(store=JsonListStore(data_dir, "document_review_queue.json"))
    portfolio_repo = PortfolioRepository(store=JsonListStore(data_dir, "portfolio.json"))
    return job_repo, document_repo, source_repo, review_repo, portfolio_repo


def _seed_portfolio(portfolio_repo, tickers):
    rows = [{"ticker": t, "name": t, "exchange": "NSE", "sector": "Test", "added_at": datetime.now(timezone.utc).isoformat()} for t in tickers]
    portfolio_repo._store.replace_all(rows)


def _fake_downloader_factory(path_for_url: dict[str, str] | None = None, default_path: str | None = None):
    def _downloader(url):
        if path_for_url and url in path_for_url:
            return path_for_url[url]
        if default_path:
            return default_path
        raise DownloadError(f"no fake file configured for {url}")

    return _downloader


def _write_fake_pdf(tmp_path, name="fake.pdf") -> str:
    path = tmp_path / name
    path.write_bytes(PDF_BYTES)
    return str(path)


class TestSuccessfulDiscoveryAndIngestion:
    def test_new_candidate_is_downloaded_and_ingested(self, repos, tmp_path, monkeypatch):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        candidate = _candidate("TCS")
        screener = FakeAdapter({"TCS": SourceCheckResult(ticker="TCS", source_name="screener", ok=True, identity_verified=True, candidates=[candidate])})
        ir = FakeAdapter(source_name="ir_website")

        pdf_path = _write_fake_pdf(tmp_path)
        monkeypatch.setattr("app.jobs.document_discovery._is_valid_pdf", lambda path: True)
        monkeypatch.setattr(
            "app.jobs.document_discovery.ingest_document",
            lambda **kwargs: type("R", (), {"document": type("D", (), {"id": "doc-1"})(), "chunk_count": 3, "reused": False})(),
        )
        monkeypatch.setattr("app.repositories.company_lookup.get_or_register_company_id", lambda t: "company-tcs")
        monkeypatch.setattr("app.jobs.document_discovery.get_or_register_company_id", lambda t: "company-tcs")

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=screener, ir_adapter=ir, embedding_provider=FakeEmbeddingProvider(),
            downloader=_fake_downloader_factory(default_path=pdf_path),
        )

        assert result["status"] == SUCCESS
        assert result["results"]["TCS"]["ingested"] == 1
        checkpoint = source_repo.get("TCS", "screener")
        assert checkpoint is not None
        assert checkpoint.health == "healthy"


class TestIncorrectCompanyIdentity:
    def test_unverified_identity_is_queued_not_ingested(self, repos, tmp_path):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        candidate = _candidate("TCS", identity_verified=False)
        screener = FakeAdapter({"TCS": SourceCheckResult(ticker="TCS", source_name="screener", ok=True, identity_verified=True, candidates=[candidate])})

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=screener, ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(),
        )

        assert result["results"]["TCS"]["ingested"] == 0
        assert result["results"]["TCS"]["queued_for_review"] == 1
        pending = review_repo.list_pending()
        assert len(pending) == 1
        assert pending[0].company_ticker == "TCS"


class TestTmpvTmcvSeparation:
    def test_tmpv_and_tmcv_discovery_never_cross_contaminate(self, repos):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TMPV"])
        # Simulate the adapter correctly rejecting a page that doesn't match
        # TMPV's own name (e.g. if it mistakenly hit a TMCV page).
        bad_result = SourceCheckResult(ticker="TMPV", source_name="screener", ok=True, identity_verified=False, error="identity mismatch")
        screener = FakeAdapter({"TMPV": bad_result})

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=screener, ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(),
        )
        assert result["results"]["TMPV"]["ingested"] == 0
        assert result["results"]["TMPV"]["discovered"] == 0


class TestDuplicates:
    def test_duplicate_source_url_is_skipped(self, repos, tmp_path):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        existing_url = "https://x.com/already-have.pdf"
        document_repo._store.append(
            {
                "id": "existing-doc", "company_id": "c1", "company_ticker": "TCS", "doc_type": "concall_transcript",
                "reporting_period": "JUL2026", "original_source_url": existing_url, "source": "manual_seed",
                "file_path": None, "fetched_at": datetime.now(timezone.utc).isoformat(), "file_sha256": "abc",
                "ingestion_status": "completed", "ingestion_error": None, "ingested_at": datetime.now(timezone.utc).isoformat(),
                "ingestion_claimed_at": None,
            }
        )
        candidate = _candidate("TCS", url=existing_url, period="SOMETHINGELSE")
        screener = FakeAdapter({"TCS": SourceCheckResult(ticker="TCS", source_name="screener", ok=True, identity_verified=True, candidates=[candidate])})

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=screener, ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(),
        )
        assert result["results"]["TCS"]["ingested"] == 0
        assert result["results"]["TCS"]["duplicates_skipped"] == 1

    def test_duplicate_reporting_period_across_different_urls_is_skipped(self, repos, tmp_path):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        document_repo._store.append(
            {
                "id": "existing-doc", "company_id": "c1", "company_ticker": "TCS", "doc_type": "concall_transcript",
                "reporting_period": "OCT2026", "original_source_url": "https://host-a.com/t.pdf", "source": "manual_seed",
                "file_path": None, "fetched_at": datetime.now(timezone.utc).isoformat(), "file_sha256": "abc",
                "ingestion_status": "completed", "ingestion_error": None, "ingested_at": datetime.now(timezone.utc).isoformat(),
                "ingestion_claimed_at": None,
            }
        )
        # Same (doc_type, reporting_period) as the above, but a DIFFERENT URL —
        # e.g. the same real-world transcript mirrored on BSE and on tcs.com.
        candidate = _candidate("TCS", url="https://host-b.com/t.pdf", period="OCT2026")
        screener = FakeAdapter({"TCS": SourceCheckResult(ticker="TCS", source_name="screener", ok=True, identity_verified=True, candidates=[candidate])})

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=screener, ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(),
        )
        assert result["results"]["TCS"]["duplicates_skipped"] == 1
        assert result["results"]["TCS"]["ingested"] == 0


class TestInvalidPdfsAndFailedDownloads:
    def test_invalid_pdf_is_not_marked_ingested(self, repos, tmp_path, monkeypatch):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        candidate = _candidate("TCS")
        screener = FakeAdapter({"TCS": SourceCheckResult(ticker="TCS", source_name="screener", ok=True, identity_verified=True, candidates=[candidate])})
        monkeypatch.setattr("app.jobs.document_discovery.get_or_register_company_id", lambda t: "company-tcs")

        not_a_pdf = tmp_path / "not_a_pdf.pdf"
        not_a_pdf.write_bytes(b"this is not a real pdf file")

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=screener, ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(default_path=str(not_a_pdf)),
        )
        assert result["results"]["TCS"]["ingested"] == 0
        assert len(result["results"]["TCS"]["ingest_failures"]) == 1

    def test_failed_download_is_recorded_as_a_failure_not_a_crash(self, repos, monkeypatch):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        candidate = _candidate("TCS")
        screener = FakeAdapter({"TCS": SourceCheckResult(ticker="TCS", source_name="screener", ok=True, identity_verified=True, candidates=[candidate])})
        monkeypatch.setattr("app.jobs.document_discovery.get_or_register_company_id", lambda t: "company-tcs")

        def broken_downloader(url):
            raise DownloadError("connection reset")

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=screener, ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=broken_downloader,
        )
        assert result["results"]["TCS"]["ingested"] == 0
        assert "connection reset" in result["results"]["TCS"]["ingest_failures"][0]["error"]


class TestPartialCompanyFailures:
    def test_one_company_source_failure_does_not_block_another(self, repos, tmp_path, monkeypatch):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS", "BROKEN"])
        good_candidate = _candidate("TCS")
        screener = FakeAdapter(
            {
                "TCS": SourceCheckResult(ticker="TCS", source_name="screener", ok=True, identity_verified=True, candidates=[good_candidate]),
                "BROKEN": SourceCheckResult(ticker="BROKEN", source_name="screener", ok=False, error="connection refused"),
            }
        )
        pdf_path = _write_fake_pdf(tmp_path)
        monkeypatch.setattr("app.jobs.document_discovery._is_valid_pdf", lambda path: True)
        monkeypatch.setattr(
            "app.jobs.document_discovery.ingest_document",
            lambda **kwargs: type("R", (), {"document": type("D", (), {"id": "doc-1"})(), "chunk_count": 3, "reused": False})(),
        )
        monkeypatch.setattr("app.jobs.document_discovery.get_or_register_company_id", lambda t: f"company-{t}")

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=screener, ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(default_path=pdf_path),
        )
        assert result["status"] == PARTIAL
        assert result["results"]["TCS"]["ingested"] == 1
        assert result["results"]["BROKEN"]["status"] == "failed"


class TestDuplicateRunPrevention:
    def test_second_concurrent_run_is_skipped(self, repos):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        job_repo.start_run("document_discovery", "manual")

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=FakeAdapter(), ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(),
        )
        assert result.get("skipped") is True


class TestCrashRecovery:
    def test_stale_running_row_is_reclaimed_before_a_new_run_starts(self, repos):
        from datetime import timedelta

        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        run = job_repo.start_run("document_discovery", "scheduler")
        stale = job_repo.get(run.id)
        stale.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=900)
        stale.claimed_at = stale.heartbeat_at
        job_repo._write_row(stale)

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=FakeAdapter(), ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(),
        )
        assert result.get("skipped") is not True
        assert result["status"] == SUCCESS


class TestExistingDocumentPreservation:
    def test_existing_documents_are_never_touched_by_a_run_with_no_new_candidates(self, repos):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        existing_row = {
            "id": "existing-doc", "company_id": "c1", "company_ticker": "TCS", "doc_type": "concall_transcript",
            "reporting_period": "JUL2026", "original_source_url": "https://x.com/t.pdf", "source": "manual_seed",
            "file_path": None, "fetched_at": datetime.now(timezone.utc).isoformat(), "file_sha256": "abc",
            "ingestion_status": "completed", "ingestion_error": None, "ingested_at": datetime.now(timezone.utc).isoformat(),
            "ingestion_claimed_at": None,
        }
        document_repo._store.append(dict(existing_row))

        run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=FakeAdapter(), ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(),
        )

        docs_after = document_repo.list_documents_for_ticker("TCS")
        assert len(docs_after) == 1
        assert docs_after[0].id == "existing-doc"
        assert docs_after[0].ingestion_status.value == "completed"


class TestAdHocSeparation:
    def test_adhoc_companies_never_appear_in_results(self, repos):
        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])  # ETERNAL (a real ad-hoc company) deliberately NOT seeded here

        result = run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=FakeAdapter(), ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(),
        )
        assert "ETERNAL" not in result["results"]
        assert list(result["results"].keys()) == ["TCS"]


class TestResearchReadinessReflectsNewDocuments:
    def test_readiness_updates_automatically_after_a_successful_ingest(self, repos, tmp_path, monkeypatch):
        from app.services.research_readiness import check_research_readiness

        job_repo, document_repo, source_repo, review_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        candidate = _candidate("TCS")
        screener = FakeAdapter({"TCS": SourceCheckResult(ticker="TCS", source_name="screener", ok=True, identity_verified=True, candidates=[candidate])})
        pdf_path = _write_fake_pdf(tmp_path)

        monkeypatch.setattr("app.jobs.document_discovery._is_valid_pdf", lambda path: True)

        def fake_ingest(**kwargs):
            document_repo._store.append(
                {
                    "id": "doc-new", "company_id": "company-tcs", "company_ticker": "TCS", "doc_type": kwargs["doc_type"].value,
                    "reporting_period": kwargs["reporting_period"], "original_source_url": kwargs["original_source_url"],
                    "source": "manual_seed", "file_path": None, "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "file_sha256": "newhash", "ingestion_status": "completed", "ingestion_error": None,
                    "ingested_at": datetime.now(timezone.utc).isoformat(), "ingestion_claimed_at": None,
                }
            )
            return type("R", (), {"document": type("D", (), {"id": "doc-new"})(), "chunk_count": 5, "reused": False})()

        monkeypatch.setattr("app.jobs.document_discovery.ingest_document", fake_ingest)
        monkeypatch.setattr("app.jobs.document_discovery.get_or_register_company_id", lambda t: "company-tcs")

        before = check_research_readiness("TCS", portfolio_repo=portfolio_repo, document_repo=document_repo, verify=lambda t: True)
        assert before.status == "known_no_documents"

        run_document_discovery(
            triggered_by="manual", job_repo=job_repo, document_repo=document_repo, source_repo=source_repo, review_repo=review_repo,
            portfolio_repo=portfolio_repo, screener_adapter=screener, ir_adapter=FakeAdapter(source_name="ir_website"),
            embedding_provider=FakeEmbeddingProvider(), downloader=_fake_downloader_factory(default_path=pdf_path),
        )

        after = check_research_readiness("TCS", portfolio_repo=portfolio_repo, document_repo=document_repo, verify=lambda t: True)
        assert after.status == "ready"
        assert after.has_retrievable_documents is True
