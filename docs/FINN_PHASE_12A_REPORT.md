# FINN Phase 12A Report — Reliable Automation Foundation + Scheduled Market-Data Refresh

Written 2026-11-15. This phase was implemented and tested, not just designed —
see test results below. Read `docs/FINN_AUTOMATION_FOUNDATION.md` first for the
pre-implementation audit this report builds on.

## 1. What was implemented

### A reusable job-execution foundation
- **`backend/app/repositories/job_runs.py`** — `JobRunRepository`: durable
  run tracking (pending/running/success/partial/failed), duplicate-run
  prevention (`is_active`/`start_run` raising `JobAlreadyRunningError`),
  crash recovery (`reclaim_stale_running` — a `running` row whose heartbeat is
  >10 minutes old is marked `failed` so a new run isn't blocked forever),
  and `get_latest`/`get_last_successful` for operational visibility. Backed
  by the existing (previously unused) `ingestion_jobs` table, widened
  additively by migration 010.
- **`backend/app/services/job_runner.py`** — `run_with_retry`: bounded
  exponential backoff (configurable retries/base delay) plus a hard
  per-attempt timeout enforced via a worker thread (needed because
  `yfinance`'s calls are synchronous). Generic — takes any zero-arg callable,
  not market-data-specific.

Both pieces are written to be reused by a future document-discovery,
announcement-monitoring, or alert-evaluation job without modification — only
a new `job_type` string and a new unit-of-work function are needed.

### The first automated workflow: scheduled EOD market-data refresh
- **`backend/app/repositories/prices.py`** — `PricesRepository`: stores
  validated `CLOSED_EOD` bars only, upserted idempotently on
  (ticker/company, trade_date) into the existing (previously unused)
  `prices` table. Never overwrites an existing date with a different
  value and never stores a provisional/intraday bar.
- **`backend/app/jobs/market_data_refresh.py`** — `run_market_data_refresh()`:
  reads tickers from the live `PortfolioRepository` (never a hardcoded
  list — verified by a test using a ticker that exists in no seed list at
  all), fetches each via the existing, unmodified
  `app.services.market_data.fetch_history`, validates every bar, retries
  transient failures, and records a per-ticker outcome
  (`success` / `up_to_date` / `failed`) into the run's `result_summary`.
  A weekend/holiday (provider's latest closed bar already matches what's
  stored) is `up_to_date` — a success, not a failure. One company failing
  never stops the other 19. The five ad-hoc research companies are never
  touched (verified by a test).
- **Admin surface — `backend/app/api/admin.py`**:
  `POST /api/admin/market-data/refresh` (manual trigger, returns **409** if
  a run is already active) and `GET /api/admin/market-data/status` (latest
  run, last successful run, per-company results, whether a run is active
  now). Both require an `X-Admin-Token` header matched against
  `ADMIN_API_TOKEN`; with no token configured, both routes return **503**
  rather than being open.
- **Scheduling — two paths, documented honestly (see §4)**:
  - `backend/app/services/scheduler.py` + a FastAPI startup hook in
    `app/main.py`: an in-process APScheduler, **off by default**
    (`ENABLE_MARKET_DATA_SCHEDULER=false`), cron-configurable
    (`MARKET_DATA_REFRESH_CRON`, default `0 18 * * 1-5`, Asia/Kolkata — 18:00
    IST Mon–Fri, well after NSE's 15:30 IST close).
  - `backend/scripts/run_market_data_refresh.py`: a standalone script that
    calls the exact same `run_market_data_refresh()` function, meant to be
    triggered by an **external** scheduler (a Render Cron Job, GitHub
    Actions scheduled workflow, host cron, etc.) — the actually-recommended
    production path, for reasons explained in §4.

### Migration
- **`backend/migrations/010_market_data_job_tracking.sql`** — purely
  additive (new columns + a widened check constraint + two new indexes on
  the existing `ingestion_jobs` table). No column dropped, no row touched,
  no other table modified. Follows the exact guarded,
  verify-before-assuming pattern migration 007 established (raises instead
  of silently proceeding if an existing column/constraint doesn't match
  what's expected).
  **Status: written and reviewed, not yet applied** — consistent with this
  project's own established practice (migrations 007–009 are explicitly
  marked "PROPOSED — NOT YET APPLIED" / "for review"; `docs/migration-runbook.md`
  documents that migrations are applied by a human via the Supabase SQL
  Editor, never executed automatically). The Supabase REST client this
  codebase otherwise uses cannot run arbitrary DDL (`ALTER TABLE`) in any
  case. **You must run migration 010 in the Supabase SQL Editor before the
  Supabase-backed path of this phase's job/admin endpoints will work** — see
  §6 "Manual setup still required."

## 2. Architecture and scheduling method
```
scheduler (in-process, optional)  ─┐
external cron → run_market_data_refresh.py ─┤→ run_market_data_refresh()
admin endpoint (manual trigger)   ─┘              │
                                                   ├→ PortfolioRepository.list_tickers()
                                                   ├→ JobRunRepository (dup-run guard, durable state)
                                                   ├→ market_data.fetch_history() [unmodified] + run_with_retry()
                                                   └→ PricesRepository.upsert_bar() [idempotent]
```
All three triggers converge on one function, so there is exactly one place
the refresh logic lives — the admin endpoint, the scheduler, and the CLI
script cannot drift out of sync with each other.

## 3. How to run and configure it

**Locally / manually:**
```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/run_market_data_refresh.py
```
**Via the admin API** (requires `ADMIN_API_TOKEN` set in the environment):
```bash
curl -X POST http://localhost:8000/api/admin/market-data/refresh -H "X-Admin-Token: $ADMIN_API_TOKEN"
curl http://localhost:8000/api/admin/market-data/status -H "X-Admin-Token: $ADMIN_API_TOKEN"
```
**Config (environment variables, all optional with safe defaults):**
- `ADMIN_API_TOKEN` — unset by default; admin routes are refused (503) until set.
- `ENABLE_MARKET_DATA_SCHEDULER` — `false` by default.
- `MARKET_DATA_REFRESH_CRON` — `"0 18 * * 1-5"` (Asia/Kolkata) by default.

## 4. Actual deployment requirements — read before assuming this runs itself
Per `FINN_AUTOMATION_FOUNDATION.md` §2, **FINN is not currently deployed
anywhere** (confirmed from `docs/submission-checklist.md`'s own prior
record). This phase therefore could not verify a real production scheduling
path, and does not claim to have done so. What's actually true:
- The in-process APScheduler (if enabled) only fires while that specific
  process is running. On any host where the web process can idle, sleep, or
  restart between deploys (common on free/low-tier PaaS), a scheduled firing
  while the process happens to be down is simply **missed** — this is not a
  bug to "fix" so much as an inherent property of in-process scheduling, which
  is exactly why it's off by default and documented as a fallback, not the
  primary mechanism.
- The **recommended** path is `scripts/run_market_data_refresh.py` triggered
  by a scheduler external to the web process — e.g. a Render Cron Job (a
  separate service type from the web service, configured in the Render
  dashboard or a `render.yaml` this repo does not currently have), or any
  other host-level cron. **Setting this up requires an operator with
  deployment access — I did not create any external account or cron
  resource, per the standing instruction not to change deployment
  infrastructure without approval, and because no such access/account
  exists in this environment.**
- Migration 010 must be applied via the Supabase SQL Editor before the
  Supabase-backed storage path works at all (see §1 and §6).

## 5. Test results
New tests added:
- `backend/tests/test_market_data_refresh_job.py` — 14 tests: successful
  refresh, live-`PortfolioRepository`-not-hardcoded, ad-hoc exclusion,
  partial failure, empty/malformed responses, duplicate-run prevention,
  retry (transient-then-success, and exhausted-retries), worker-restart
  recovery (stale vs. fresh `running` row), weekend/holiday handling,
  timezone correctness (a same-IST-day bar is excluded as provisional), and
  historical-data preservation (a later bad run never overwrites a
  previously stored good bar).
- `backend/tests/test_admin_market_data_api.py` — 4 tests: refusal with no
  token configured (503), wrong token (401), status requires token, and the
  409 duplicate-run response at the HTTP layer.

All new tests run against the JSON-fallback repositories (via `tmp_path`)
with `market_data.fetch_history` mocked — **no live external calls in these
tests**, per the phase's own instruction. (A live yfinance call against a
handful of real tickers was exercised manually during Phase 1/this session's
earlier work on `market_data.py` itself, not re-run here.)

```
487 passed in 60.84s
```
This is the **full existing suite plus the 18 new tests** (previous
documented baseline: 469 passed) — **zero regressions**, confirmed by a full
`pytest -q` run after all changes.

## 6. Manual setup still required
1. **Apply migration 010** in the Supabase SQL Editor (same procedure as
   migrations 007–009 per `docs/migration-runbook.md`). Until this is done,
   the JSON-fallback path works fully (as tested), but the live Supabase
   `ingestion_jobs`/`prices` tables will reject writes with the new columns.
2. **Set `ADMIN_API_TOKEN`** in the deployment environment to actually use
   the manual-trigger/status endpoints (they refuse all requests until set).
3. **Set up an external scheduled trigger** for
   `scripts/run_market_data_refresh.py` once FINN is actually deployed
   somewhere (see §4) — this was not created, since no deployment exists
   yet and creating hosting/cron infrastructure is outside this phase's
   remit without an explicit, separate decision.
4. (Optional) set `ENABLE_MARKET_DATA_SCHEDULER=true` as a same-process
   fallback once a deployment exists — understanding its limitation in §4.

## 7. Known limitations
- The in-process scheduler path cannot be relied on alone for production
  (§4) — by design, not oversight.
- `GET /api/market-data/portfolio` (the existing live-quotes endpoint) still
  reads the static `PORTFOLIO` seed list rather than `PortfolioRepository`
  (a pre-existing inconsistency noted in the audit, not fixed this phase —
  out of today's requested scope).
- `prices` only stores OHLCV + session_status; derived stats (daily % change,
  rolling average volume, volume multiple) remain request-time calculations
  in `market_data.py`, unchanged — this phase does not yet wire the live
  quotes endpoint to read from the new stored history instead of always
  re-fetching from yfinance. That wiring (switching `/api/market-data/*` to
  prefer stored data with a live fallback) is a natural, separate next step,
  not attempted here to keep this phase's blast radius to "add the job,"
  not "change how the existing read path behaves."
- Per-attempt timeout uses a Python thread (`ThreadPoolExecutor`), which can
  leave an abandoned thread running in the background if a `yfinance` call
  truly hangs past the timeout (Python cannot forcibly kill a thread) — it
  cannot leak into a *second* concurrent fetch for the same ticker because
  the job processes tickers sequentially, but a pathological hang could
  slow down process shutdown. Acceptable for this phase's scale (20
  tickers, 20s timeout each); worth revisiting if the job grows
  significantly larger.

## 8. Recommended next implementation phase
Wire `GET /api/market-data/portfolio` and `GET /api/market-data/{ticker}` to
read from the new `prices` table first (falling back to a live `yfinance`
call only when no stored data exists yet), so the scheduled refresh actually
reduces live API calls on the hot path — right now the job and the existing
read endpoint are two independent paths to the same data. This is the
natural, low-risk continuation of this phase (same tables, same
repositories, no new infrastructure) and was intentionally left for a
separate phase rather than bundled in here, per the instruction to keep this
phase focused on one complete workflow.
