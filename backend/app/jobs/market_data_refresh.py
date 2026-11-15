"""Phase 12A — scheduled EOD market-data refresh for the frozen portfolio.

Reads tickers from the live PortfolioRepository (never a hardcoded list — a
portfolio add/remove must not require a code change, same principle
app.repositories.portfolio already documents), fetches each one's recent history
via the existing app.services.market_data.fetch_history, validates it, and persists
only genuine CLOSED_EOD bars via app.repositories.prices. Ad-hoc research companies
(app.core.companies.AD_HOC_RESEARCH) are never touched by this job — Push stays
scoped to the portfolio, per the standing instruction that ad-hoc Pull targets are
a separate concept from portfolio Push.

One call = one batch run, tracked end-to-end in JobRunRepository so duplicate runs
(scheduler + a manual trigger landing at the same time) are prevented and a crashed
run can be recovered from on the next attempt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.core.companies import to_yfinance_symbol
from app.repositories.company_lookup import get_or_register_company_id
from app.repositories.job_runs import JobAlreadyRunningError, JobRunRepository
from app.repositories.portfolio import PortfolioRepository
from app.repositories.prices import EodBar, PricesRepository
from app.services.job_runner import run_with_retry
from app.services.market_data import IST, _today_ist, fetch_history

logger = logging.getLogger("finn.jobs.market_data_refresh")

JOB_TYPE = "market_data_refresh"

PER_TICKER_MAX_RETRIES = 2
PER_TICKER_TIMEOUT_SECONDS = 20
FETCH_PERIOD = "5d"  # enough to catch the latest closed bar plus a short backfill gap


@dataclass
class CompanyOutcome:
    status: str  # "success" | "up_to_date" | "failed"
    trade_date: str | None = None
    rows_stored: int = 0
    error: str | None = None
    attempts: int = 1


def _company_id_if_supabase(ticker: str, prices_repo: PricesRepository) -> str | None:
    if prices_repo.backend != "supabase":
        return None
    return get_or_register_company_id(ticker)


def _refresh_one_ticker(ticker: str, prices_repo: PricesRepository) -> CompanyOutcome:
    yfinance_symbol = to_yfinance_symbol(ticker)

    outcome = run_with_retry(
        lambda: fetch_history(yfinance_symbol, period=FETCH_PERIOD),
        max_retries=PER_TICKER_MAX_RETRIES,
        timeout_seconds=PER_TICKER_TIMEOUT_SECONDS,
    )
    if not outcome.succeeded:
        return CompanyOutcome(status="failed", error=str(outcome.last_error), attempts=outcome.attempts)

    hist = outcome.value
    if hist is None or hist.empty:
        return CompanyOutcome(status="failed", error="No data returned by provider.", attempts=outcome.attempts)

    hist = hist.sort_index()
    today = _today_ist()
    is_today = hist.index.tz_convert(IST).normalize() == today
    closed = hist.loc[~is_today]

    if closed.empty:
        return CompanyOutcome(
            status="failed",
            error="Response contained only a provisional/intraday bar — no finalized EOD data available yet.",
            attempts=outcome.attempts,
        )

    company_id = _company_id_if_supabase(ticker, prices_repo)
    stored_latest = prices_repo.get_latest_trade_date(ticker, company_id=company_id)

    rows_stored = 0
    malformed_skipped = 0
    latest_stored_date: date | None = None

    for idx, row in closed.iterrows():
        trade_date = idx.tz_convert(IST).date()
        if stored_latest is not None and trade_date <= stored_latest:
            continue  # already have this day or an earlier one — never overwrite good history

        close_val, open_val, high_val, low_val, vol_val = row["Close"], row["Open"], row["High"], row["Low"], row["Volume"]
        if any(pd.isna(v) for v in (close_val, open_val, high_val, low_val, vol_val)) or close_val <= 0 or vol_val < 0:
            malformed_skipped += 1
            logger.warning("market_data_refresh: skipping malformed bar for %s on %s", ticker, trade_date)
            continue

        prices_repo.upsert_bar(
            EodBar(
                company_ticker=ticker,
                trade_date=trade_date,
                open=float(open_val),
                high=float(high_val),
                low=float(low_val),
                close=float(close_val),
                volume=int(vol_val),
                source="live",
            ),
            company_id=company_id,
        )
        rows_stored += 1
        latest_stored_date = trade_date if latest_stored_date is None else max(latest_stored_date, trade_date)

    if rows_stored > 0:
        return CompanyOutcome(status="success", trade_date=latest_stored_date.isoformat(), rows_stored=rows_stored, attempts=outcome.attempts)

    if malformed_skipped > 0:
        return CompanyOutcome(
            status="failed",
            error=f"{malformed_skipped} new bar(s) returned but all were malformed (NaN/negative/non-positive close) — none stored.",
            attempts=outcome.attempts,
        )

    # No new rows at all, nothing malformed: the provider's latest closed bar is
    # already what we have stored (weekend/holiday/no new session) — success, not
    # a failure.
    return CompanyOutcome(status="up_to_date", trade_date=stored_latest.isoformat() if stored_latest else None, attempts=outcome.attempts)


def run_market_data_refresh(
    triggered_by: str = "scheduler",
    *,
    job_repo: JobRunRepository | None = None,
    prices_repo: PricesRepository | None = None,
    portfolio_repo: PortfolioRepository | None = None,
) -> dict:
    """Entry point for the scheduler, the manual admin endpoint, and the standalone
    CLI script — all three call exactly this function so there is only one place
    the actual refresh logic lives."""
    job_repo = job_repo or JobRunRepository()
    prices_repo = prices_repo or PricesRepository()
    portfolio_repo = portfolio_repo or PortfolioRepository()

    try:
        run = job_repo.start_run(JOB_TYPE, triggered_by, max_retries=PER_TICKER_MAX_RETRIES, timeout_seconds=PER_TICKER_TIMEOUT_SECONDS)
    except JobAlreadyRunningError as exc:
        return {"skipped": True, "reason": str(exc)}

    tickers = sorted(portfolio_repo.list_tickers())
    results: dict[str, dict] = {}
    records_affected = 0

    try:
        for ticker in tickers:
            try:
                outcome = _refresh_one_ticker(ticker, prices_repo)
            except Exception as exc:  # noqa: BLE001 - one company's unexpected failure must not stop the rest
                logger.exception("market_data_refresh: unexpected error refreshing %s", ticker)
                outcome = CompanyOutcome(status="failed", error=str(exc))

            results[ticker] = {
                "status": outcome.status,
                "trade_date": outcome.trade_date,
                "rows_stored": outcome.rows_stored,
                "error": outcome.error,
                "attempts": outcome.attempts,
            }
            records_affected += outcome.rows_stored
            job_repo.heartbeat(run.id)

        statuses = {r["status"] for r in results.values()}
        if not tickers:
            final_status, error_message = "success", None
        elif statuses <= {"success", "up_to_date"}:
            final_status, error_message = "success", None
        elif statuses == {"failed"}:
            final_status, error_message = "failed", "All companies failed — see result_summary for per-company errors."
        else:
            final_status, error_message = "partial", "Some companies failed — see result_summary for details."

        failed = [t for t, r in results.items() if r["status"] == "failed"]
        log = f"Refreshed {len(tickers)} portfolio ticker(s). Failed: {failed or 'none'}."

        job_repo.complete_run(
            run.id, status=final_status, result_summary=results, error_message=error_message, log=log, records_affected=records_affected,
        )
        return {"run_id": run.id, "status": final_status, "results": results, "records_affected": records_affected}

    except Exception as exc:  # noqa: BLE001 - must still close out the run row, never leave it stuck 'running'
        logger.exception("market_data_refresh: job crashed")
        job_repo.complete_run(run.id, status="failed", result_summary=results, error_message=str(exc), log="Job crashed before completing.")
        raise


__all__ = ["run_market_data_refresh", "JOB_TYPE"]
