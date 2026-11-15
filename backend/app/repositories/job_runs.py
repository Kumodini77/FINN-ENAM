"""Durable job-run tracking — the reusable half of Phase 12A's job-execution
foundation (the other half, bounded-retry execution, is app.services.job_runner).

Backed by migrations/010_market_data_job_tracking.sql's widened `ingestion_jobs`
table (Supabase) or job_runs.json (fallback). One row = one BATCH run of a given
job_type (e.g. one "refresh all 20 portfolio companies" run), not one row per
company — per-company outcomes live in that row's `result_summary` JSON, since the
company count is small and bounded (see migration's column comment).

This is deliberately generic: nothing here mentions market data. A future document-
discovery or alert-evaluation job can reuse this repository unchanged by passing its
own job_type string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import get_settings
from app.core.db import get_supabase_client, storage_backend_name
from app.repositories.json_store import JsonListStore

PENDING = "pending"
RUNNING = "running"
SUCCESS = "success"
PARTIAL = "partial"
FAILED = "failed"
TERMINAL_STATUSES = {SUCCESS, PARTIAL, FAILED}

# A "running" row whose heartbeat is older than this is assumed to belong to a
# crashed/killed worker (process restart, deploy, OOM) rather than one still making
# progress — see reclaim_stale_running(). Generous relative to a single EOD refresh
# (expected to take well under a minute for 20 tickers) so a merely-slow run is never
# mistaken for a dead one.
DEFAULT_STALE_AFTER_SECONDS = 600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@dataclass
class JobRun:
    id: str
    job_type: str
    status: str
    triggered_by: str
    started_at: datetime
    finished_at: datetime | None = None
    claimed_at: datetime | None = None
    heartbeat_at: datetime | None = None
    retry_count: int = 0
    max_retries: int = 2
    timeout_seconds: int = 300
    result_summary: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    log: str = ""
    company_id: str | None = None
    source: str = "live"
    records_affected: int = 0

    @classmethod
    def from_row(cls, row: dict) -> "JobRun":
        def parse_dt(v):
            if v is None:
                return None
            return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))

        return cls(
            id=row["id"],
            job_type=row["job_type"],
            status=row["status"],
            triggered_by=row.get("triggered_by", "manual"),
            started_at=parse_dt(row.get("started_at")) or _now(),
            finished_at=parse_dt(row.get("finished_at")),
            claimed_at=parse_dt(row.get("claimed_at")),
            heartbeat_at=parse_dt(row.get("heartbeat_at")),
            retry_count=row.get("retry_count", 0),
            max_retries=row.get("max_retries", 2),
            timeout_seconds=row.get("timeout_seconds", 300),
            result_summary=row.get("result_summary") or {},
            error_message=row.get("error_message"),
            log=row.get("log") or "",
            company_id=row.get("company_id"),
            source=row.get("source", "live"),
            records_affected=row.get("records_affected", 0),
        )

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "job_type": self.job_type,
            "status": self.status,
            "triggered_by": self.triggered_by,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "claimed_at": _iso(self.claimed_at),
            "heartbeat_at": _iso(self.heartbeat_at),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "result_summary": self.result_summary,
            "error_message": self.error_message,
            "log": self.log,
            "company_id": self.company_id,
            "source": self.source,
            "records_affected": self.records_affected,
        }


class JobAlreadyRunningError(Exception):
    """Raised by start_run() when an unexpired run of the same job_type is already
    pending/running — the actual duplicate-run-prevention mechanism."""


class JobRunRepository:
    def __init__(self, store: JsonListStore | None = None):
        settings = get_settings()
        self._force_json = store is not None
        self._store = store or JsonListStore(settings.data_dir, "job_runs.json")

    def _backend(self) -> str:
        if self._force_json:
            return "json_fallback"
        return storage_backend_name()

    # -- internal row access -------------------------------------------------
    def _all_rows(self) -> list[dict]:
        if self._backend() == "supabase":
            client = get_supabase_client()
            resp = client.table("ingestion_jobs").select("*").execute()
            return resp.data or []
        return self._store.read_all()

    def _write_row(self, run: JobRun) -> None:
        if self._backend() == "supabase":
            client = get_supabase_client()
            client.table("ingestion_jobs").upsert(run.to_row(), on_conflict="id").execute()
            return
        rows = self._store.read_all()
        rows = [r for r in rows if r.get("id") != run.id]
        rows.append(run.to_row())
        self._store.replace_all(rows)

    # -- crash recovery -------------------------------------------------------
    def reclaim_stale_running(self, job_type: str, stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS) -> list[str]:
        """Marks any 'running' row of this job_type whose heartbeat is older than
        the stale threshold as 'failed' (error_message explains why), so a genuinely
        crashed run can never block new runs forever. Returns the list of reclaimed
        run IDs. Safe to call before every start_run() attempt — a no-op when
        nothing is stale."""
        cutoff = _now() - timedelta(seconds=stale_after_seconds)
        reclaimed = []
        for row in self._all_rows():
            if row.get("job_type") != job_type or row.get("status") != RUNNING:
                continue
            run = JobRun.from_row(row)
            last_seen = run.heartbeat_at or run.claimed_at or run.started_at
            if last_seen is not None and last_seen < cutoff:
                run.status = FAILED
                run.finished_at = _now()
                run.error_message = (
                    f"Reclaimed as failed: no heartbeat since {last_seen.isoformat()} "
                    f"(> {stale_after_seconds}s) — the worker likely crashed or was restarted."
                )
                self._write_row(run)
                reclaimed.append(run.id)
        return reclaimed

    def is_active(self, job_type: str) -> bool:
        """True if a pending/running run of this job_type exists (after reclaiming
        any stale one first) — the check start_run() uses for duplicate-run
        prevention between the scheduler and the manual trigger."""
        self.reclaim_stale_running(job_type)
        return any(
            row.get("job_type") == job_type and row.get("status") in (PENDING, RUNNING)
            for row in self._all_rows()
        )

    # -- lifecycle -------------------------------------------------------------
    def start_run(self, job_type: str, triggered_by: str, *, max_retries: int = 2, timeout_seconds: int = 300) -> JobRun:
        import uuid

        if self.is_active(job_type):
            raise JobAlreadyRunningError(f"A {job_type} run is already pending or running.")

        now = _now()
        run = JobRun(
            id=str(uuid.uuid4()),
            job_type=job_type,
            status=RUNNING,
            triggered_by=triggered_by,
            started_at=now,
            claimed_at=now,
            heartbeat_at=now,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
        self._write_row(run)
        return run

    def heartbeat(self, run_id: str) -> None:
        run = self.get(run_id)
        if run is None or run.status != RUNNING:
            return
        run.heartbeat_at = _now()
        self._write_row(run)

    def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        result_summary: dict[str, Any],
        error_message: str | None = None,
        log: str = "",
        records_affected: int = 0,
    ) -> JobRun:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"complete_run requires a terminal status, got {status!r}")
        run = self.get(run_id)
        if run is None:
            raise KeyError(f"No job run with id {run_id}")
        run.status = status
        run.finished_at = _now()
        run.heartbeat_at = run.finished_at
        run.result_summary = result_summary
        run.error_message = error_message
        run.log = log
        run.records_affected = records_affected
        self._write_row(run)
        return run

    def get(self, run_id: str) -> JobRun | None:
        for row in self._all_rows():
            if row.get("id") == run_id:
                return JobRun.from_row(row)
        return None

    def get_latest(self, job_type: str) -> JobRun | None:
        rows = [r for r in self._all_rows() if r.get("job_type") == job_type]
        if not rows:
            return None
        rows.sort(key=lambda r: r.get("started_at") or "", reverse=True)
        return JobRun.from_row(rows[0])

    def get_last_successful(self, job_type: str) -> JobRun | None:
        rows = [
            r for r in self._all_rows()
            if r.get("job_type") == job_type and r.get("status") in (SUCCESS, PARTIAL)
        ]
        if not rows:
            return None
        rows.sort(key=lambda r: r.get("finished_at") or "", reverse=True)
        return JobRun.from_row(rows[0])


__all__ = ["JobRunRepository", "JobRun", "JobAlreadyRunningError", "PENDING", "RUNNING", "SUCCESS", "PARTIAL", "FAILED"]
