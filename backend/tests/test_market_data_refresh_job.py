"""Phase 12A — tests for the scheduled EOD market-data refresh job. All market-data
fetches are mocked (no live yfinance calls in ordinary unit tests, per the phase's
own instruction); a separate live-call integration check is documented, not run
here, in docs/FINN_PHASE_12A_REPORT.md.

Everything is exercised against the JSON-fallback repositories (via tmp_path) —
this tests the real job logic, retry wrapper, and durable job-run tracking without
needing a Supabase project, exactly like the rest of this test suite's repository
unit tests.
"""

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from app.jobs.market_data_refresh import run_market_data_refresh
from app.repositories.job_runs import FAILED, PARTIAL, RUNNING, SUCCESS, JobRun, JobRunRepository
from app.repositories.json_store import JsonListStore
from app.repositories.portfolio import PortfolioRepository
from app.repositories.prices import PricesRepository
from app.services.market_data import IST


def _bar_df(trade_dates: list[date], close: float = 100.0, volume: int = 1_000_000) -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp(d, tz=IST) for d in trade_dates])
    return pd.DataFrame(
        {
            "Open": [close] * len(trade_dates),
            "High": [close * 1.01] * len(trade_dates),
            "Low": [close * 0.99] * len(trade_dates),
            "Close": [close] * len(trade_dates),
            "Volume": [volume] * len(trade_dates),
        },
        index=index,
    )


@pytest.fixture
def repos(tmp_path):
    data_dir = str(tmp_path)
    job_repo = JobRunRepository(store=JsonListStore(data_dir, "job_runs.json"))
    prices_repo = PricesRepository(store=JsonListStore(data_dir, "prices.json"))
    portfolio_repo = PortfolioRepository(store=JsonListStore(data_dir, "portfolio.json"))
    return job_repo, prices_repo, portfolio_repo


def _seed_portfolio(portfolio_repo: PortfolioRepository, tickers: list[str]) -> None:
    rows = [
        {"ticker": t, "name": t, "exchange": "NSE", "sector": "Test", "added_at": datetime.now(timezone.utc).isoformat()}
        for t in tickers
    ]
    portfolio_repo._store.replace_all(rows)


class TestSuccessfulRefresh:
    def test_all_portfolio_tickers_refreshed_and_stored(self, repos, monkeypatch):
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS", "INFY"])
        monkeypatch.setattr(
            "app.jobs.market_data_refresh.fetch_history",
            lambda symbol, period="5d": _bar_df([date(2026, 11, 13)]),
        )

        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)

        assert result["status"] == SUCCESS
        assert result["results"]["TCS"]["status"] == "success"
        assert result["results"]["INFY"]["status"] == "success"
        assert prices_repo.get_latest_trade_date("TCS") == date(2026, 11, 13)
        assert result["records_affected"] == 2

    def test_uses_live_portfolio_repository_not_a_hardcoded_list(self, repos, monkeypatch):
        """A ticker that is NOT in app.core.companies' seed list at all must still be
        refreshed if the live PortfolioRepository says it's a member — this is what
        'read tickers from PortfolioRepository, never hardcode' actually proves."""
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["SOMEFUTURETICKER"])
        monkeypatch.setattr(
            "app.jobs.market_data_refresh.fetch_history",
            lambda symbol, period="5d": _bar_df([date(2026, 11, 13)]),
        )

        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)
        assert "SOMEFUTURETICKER" in result["results"]
        assert result["results"]["SOMEFUTURETICKER"]["status"] == "success"

    def test_adhoc_companies_are_never_refreshed(self, repos, monkeypatch):
        """ETERNAL is a real ad-hoc research company (app.core.companies.AD_HOC_RESEARCH)
        but is NOT seeded into the portfolio store here — it must not appear in the
        job's results at all."""
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        monkeypatch.setattr(
            "app.jobs.market_data_refresh.fetch_history",
            lambda symbol, period="5d": _bar_df([date(2026, 11, 13)]),
        )

        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)
        assert "ETERNAL" not in result["results"]
        assert list(result["results"].keys()) == ["TCS"]


class TestPartialFailure:
    def test_one_company_failing_does_not_block_the_others(self, repos, monkeypatch):
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS", "BROKEN", "INFY"])

        def fake_fetch(symbol, period="5d"):
            if "BROKEN" in symbol:
                raise RuntimeError("upstream exploded")
            return _bar_df([date(2026, 11, 13)])

        monkeypatch.setattr("app.jobs.market_data_refresh.fetch_history", fake_fetch)

        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)

        assert result["status"] == PARTIAL
        assert result["results"]["TCS"]["status"] == "success"
        assert result["results"]["INFY"]["status"] == "success"
        assert result["results"]["BROKEN"]["status"] == "failed"
        assert "upstream exploded" in result["results"]["BROKEN"]["error"]


class TestEmptyAndMalformedResponses:
    def test_empty_dataframe_is_a_failure_not_a_crash(self, repos, monkeypatch):
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        monkeypatch.setattr("app.jobs.market_data_refresh.fetch_history", lambda symbol, period="5d": pd.DataFrame())

        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)
        assert result["status"] == FAILED
        assert result["results"]["TCS"]["status"] == "failed"
        assert "No data" in result["results"]["TCS"]["error"]

    def test_malformed_rows_are_never_stored(self, repos, monkeypatch):
        """A NaN close (a real observed yfinance glitch pattern) must be rejected,
        not silently stored as a fabricated number."""
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        bad = _bar_df([date(2026, 11, 13)])
        bad.loc[bad.index[0], "Close"] = float("nan")
        monkeypatch.setattr("app.jobs.market_data_refresh.fetch_history", lambda symbol, period="5d": bad)

        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)
        assert result["results"]["TCS"]["status"] == "failed"
        assert "malformed" in result["results"]["TCS"]["error"].lower()
        assert prices_repo.get_latest_trade_date("TCS") is None


class TestDuplicateRunPrevention:
    def test_second_concurrent_run_is_skipped_not_duplicated(self, repos, monkeypatch):
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        job_repo.start_run("market_data_refresh", "manual")  # simulate an in-flight run

        monkeypatch.setattr("app.jobs.market_data_refresh.fetch_history", lambda symbol, period="5d": _bar_df([date(2026, 11, 13)]))
        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)

        assert result.get("skipped") is True
        assert prices_repo.get_latest_trade_date("TCS") is None  # the skipped call did no work


class TestRetryBehaviour:
    def test_transient_failures_are_retried_then_succeed(self, repos, monkeypatch):
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])

        calls = {"count": 0}

        def flaky_fetch(symbol, period="5d"):
            calls["count"] += 1
            if calls["count"] < 3:
                raise ConnectionError("transient network blip")
            return _bar_df([date(2026, 11, 13)])

        monkeypatch.setattr("app.jobs.market_data_refresh.fetch_history", flaky_fetch)
        monkeypatch.setattr("app.services.job_runner.time.sleep", lambda *_: None)  # don't actually wait in tests

        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)

        assert result["results"]["TCS"]["status"] == "success"
        assert result["results"]["TCS"]["attempts"] == 3
        assert calls["count"] == 3

    def test_exhausting_retries_records_the_last_error(self, repos, monkeypatch):
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        monkeypatch.setattr(
            "app.jobs.market_data_refresh.fetch_history",
            lambda symbol, period="5d": (_ for _ in ()).throw(ConnectionError("still down")),
        )
        monkeypatch.setattr("app.services.job_runner.time.sleep", lambda *_: None)

        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)
        assert result["results"]["TCS"]["status"] == "failed"
        assert result["results"]["TCS"]["attempts"] == 3  # max_retries=2 => 3 total attempts
        assert "still down" in result["results"]["TCS"]["error"]


class TestWorkerRestartRecovery:
    def test_stale_running_row_is_reclaimed_and_a_new_run_can_start(self, repos, monkeypatch):
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])

        run = job_repo.start_run("market_data_refresh", "scheduler")
        stale_run = job_repo.get(run.id)
        stale_run.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=900)
        stale_run.claimed_at = stale_run.heartbeat_at
        job_repo._write_row(stale_run)  # simulate a crashed worker's last-written state

        assert job_repo.is_active("market_data_refresh") is False
        reclaimed = job_repo.get(run.id)
        assert reclaimed.status == FAILED
        assert "crashed or was restarted" in reclaimed.error_message

        monkeypatch.setattr("app.jobs.market_data_refresh.fetch_history", lambda symbol, period="5d": _bar_df([date(2026, 11, 13)]))
        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)
        assert result["status"] == SUCCESS

    def test_recent_running_row_is_not_reclaimed(self, repos):
        job_repo, _, _ = repos
        job_repo.start_run("market_data_refresh", "scheduler")
        assert job_repo.is_active("market_data_refresh") is True


class TestWeekendAndHolidayHandling:
    def test_no_new_closed_bar_is_up_to_date_not_a_failure(self, repos, monkeypatch):
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        prices_repo.upsert_bar(
            __import__("app.repositories.prices", fromlist=["EodBar"]).EodBar(
                company_ticker="TCS", trade_date=date(2026, 11, 13), open=100, high=101, low=99, close=100, volume=1_000_000
            )
        )
        # Provider's "latest" closed bar is the SAME date we already have stored —
        # exactly what a Saturday/Sunday/market-holiday refresh attempt looks like.
        monkeypatch.setattr("app.jobs.market_data_refresh.fetch_history", lambda symbol, period="5d": _bar_df([date(2026, 11, 13)]))

        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)
        assert result["status"] == SUCCESS
        assert result["results"]["TCS"]["status"] == "up_to_date"
        assert result["results"]["TCS"]["rows_stored"] == 0


class TestTimezoneCorrectness:
    def test_a_bar_dated_today_in_ist_is_excluded_as_provisional(self, repos, monkeypatch):
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        import pandas as _pd

        from app.services.market_data import _today_ist

        today = _today_ist()
        df = _bar_df([date(2026, 11, 13)])
        # Append today's (still-open-session) bar — must be excluded from storage.
        today_row = pd.DataFrame({"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [500]}, index=[today])
        df = _pd.concat([df, today_row])
        monkeypatch.setattr("app.jobs.market_data_refresh.fetch_history", lambda symbol, period="5d": df)

        result = run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)
        assert result["results"]["TCS"]["status"] == "success"
        assert result["results"]["TCS"]["trade_date"] == "2026-11-13"  # not today


class TestHistoricalDataPreservation:
    def test_a_later_bad_run_never_overwrites_previously_stored_good_data(self, repos, monkeypatch):
        job_repo, prices_repo, portfolio_repo = repos
        _seed_portfolio(portfolio_repo, ["TCS"])
        monkeypatch.setattr("app.jobs.market_data_refresh.fetch_history", lambda symbol, period="5d": _bar_df([date(2026, 11, 13)]))
        run_market_data_refresh(triggered_by="manual", job_repo=job_repo, prices_repo=prices_repo, portfolio_repo=portfolio_repo)
        assert prices_repo.get_latest_trade_date("TCS") == date(2026, 11, 13)

        job_repo2 = JobRunRepository(store=job_repo._store)
        monkeypatch.setattr("app.jobs.market_data_refresh.fetch_history", lambda symbol, period="5d": pd.DataFrame())
        run_market_data_refresh(triggered_by="manual", job_repo=job_repo2, prices_repo=prices_repo, portfolio_repo=portfolio_repo)

        assert prices_repo.get_latest_trade_date("TCS") == date(2026, 11, 13)  # untouched
