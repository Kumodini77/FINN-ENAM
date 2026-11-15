# FINN Deployment Checklist

Written 2026-11-15. **FINN is not currently deployed anywhere** — confirmed
in Phase 12A/12B/12C's own audits (`docs/submission-checklist.md`'s earlier
record: "Not deployed anywhere. No external account created."). This
checklist is what an operator needs to do to actually stand FINN up — it is
not a claim that any of it has been done. No paid service is required
anywhere in this checklist; none should be added without a separate,
explicit decision.

## 1. Database (Supabase)

Already applied and confirmed live (verified today by direct query):
- `001_init.sql` through `006` and `007_document_ingestion_tracking.sql` —
  confirmed applied (`documents.file_sha256`/`ingestion_status`/`ingested_at`
  are real, populated columns on the live project).

**Not yet applied — must be run manually via the Supabase SQL Editor**
(this repo's established practice; never run automatically):
- `migrations/010_market_data_job_tracking.sql` (Phase 12A — widens
  `ingestion_jobs` for job-run tracking). Confirmed still unapplied today:
  a live write attempt fails with `PGRST204: Could not find the
  'claimed_at' column of 'ingestion_jobs'`.
- `migrations/011_document_discovery_tracking.sql` (Phase 12B — new
  `document_sources`/`document_review_queue` tables).

**Until both are applied**: the EOD market-data refresh, document
discovery, and announcement discovery jobs all work correctly against the
**JSON-fallback store** (fully tested — see each phase's test suite) but
their **job-tracking/duplicate-run-prevention layer will fail against
Supabase**. The underlying discovery/ingestion/import logic for documents
and announcements does NOT depend on 010/011 — only the job-run bookkeeping
does (confirmed live today: discovery + `import_announcement()` ran
successfully against Supabase directly, bypassing `JobRunRepository`, for
exactly this reason).

Also unresolved, not part of this phase: `008_retrieval_completed_documents_only.sql`
and `009_proposed_atomic_failure_cleanup_rpc.sql`'s actual live-applied
status was not re-verified this phase — check before relying on their
behavior.

## 2. Required environment variables (backend)

From `backend/.env.example`, grouped by what breaks without them:

| Variable | Required for | Default if unset |
|---|---|---|
| `SUPABASE_URL` / `SUPABASE_KEY` | Any persistence beyond local JSON files | falls back to JSON-file storage in `DATA_DIR` |
| `ANTHROPIC_API_KEY` | LLM-assisted announcement classification (optional — rule-based classification works without it) | rule-based only |
| `ADMIN_API_TOKEN` | **Every `/api/admin/*` route** (market-data refresh, document discovery, announcement discovery — trigger + status) | all admin routes return 503 |
| `ENABLE_MARKET_DATA_SCHEDULER` | in-process EOD refresh scheduling | `false` |
| `ENABLE_DOCUMENT_DISCOVERY_SCHEDULER` | in-process document discovery scheduling | `false` |
| `ENABLE_ANNOUNCEMENT_DISCOVERY_SCHEDULER` | in-process announcement discovery scheduling | `false` |
| `MARKET_DATA_REFRESH_CRON` / `DOCUMENT_DISCOVERY_CRON` / `ANNOUNCEMENT_DISCOVERY_CRON` | cron timing for the above, Asia/Kolkata | 18:00 / 19:30 / 17:00 IST Mon–Fri |
| `CORS_ALLOW_ORIGINS` (code default, not currently an env var) | frontend origin allow-list | hardcoded to `localhost:3000`/`127.0.0.1:3000` in `app/core/config.py` — **must be changed to the real deployed frontend origin before going live**, or the frontend will get CORS errors against a deployed backend |

## 3. Scheduler / worker deployment — read before assuming any cron is active

Three jobs now exist (Phase 12A market-data, 12B documents, 12C
announcements), each with the same two options, already built:

1. **In-process APScheduler** (`app/services/scheduler.py`), started from
   `app/main.py`'s startup hook only when the matching `ENABLE_*_SCHEDULER`
   flag is true. **Not durable**: on any host where the web process can
   idle/sleep/restart (common on free/low tiers), a scheduled firing while
   the process is down is simply missed. Zero extra infrastructure, so it's
   the default fallback, not the recommended production path.
2. **External cron → standalone script** (recommended):
   `scripts/run_market_data_refresh.py`, `scripts/run_document_discovery.py`,
   `scripts/run_announcement_discovery.py`. Each runs
   `PYTHONPATH=. .venv/bin/python scripts/run_<job>.py`, exits 0 on
   success/partial, 1 on failure/crash — suitable for any external
   scheduler (a Render Cron Job, a GitHub Actions scheduled workflow, any
   host cron) that doesn't depend on the web process's uptime.

**If deploying on Render specifically**: a Render Cron Job is a *separate
service type* from the web service, configured via the Render dashboard or
a `render.yaml` this repo does not currently have — creating one requires
an operator with deployment access and was not done as part of this phase
(no such access/account exists in this environment, and standing
instructions forbid changing deployment infrastructure without approval).

**Do not enable any `ENABLE_*_SCHEDULER` flag and call the job "scheduled in
production" without also confirming the process actually stays up across
the scheduled time** — that confirmation has not been performed, because
nothing is deployed yet.

## 4. API configuration

- Backend start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
  (standard FastAPI/Render pattern; no `Procfile` currently checked in —
  add one, or set this as the service's start command directly, if
  deploying on a platform that needs it explicit).
- API prefix: `/api` (`settings.api_prefix`).
- Health check: `GET /api/health` — returns `supabase_configured`,
  `storage_backend` (`"supabase"` vs `"json_fallback"`, computed from a
  real connectivity check, not just env-var presence), and
  `llm_configured`. Use this as the platform's health-check URL.

## 5. Frontend build/deploy

- Build: `npm run build` (Next.js 16, Turbopack).
- Start: `npm run start`.
- Required env var: `NEXT_PUBLIC_API_BASE_URL` — must point at the
  deployed backend's `/api` base, not `http://127.0.0.1:8000/api` (the
  local-dev default baked into `lib/api.ts`).

## 6. CORS

`app/core/config.py`'s `cors_allow_origins` is a Python list literal
(`["http://localhost:3000", "http://127.0.0.1:3000"]`), not currently an
environment variable. **Before deploying, this must be edited in code** (or
converted to read from an env var — a small, safe change, not done this
phase since it wasn't reported as broken yet) to include the real deployed
frontend origin, or every request from the deployed frontend will be
rejected by the browser.

## 7. Secrets handling

- `SUPABASE_KEY`, `ANTHROPIC_API_KEY`, `ADMIN_API_TOKEN` must be set via the
  hosting platform's secret/env store, never committed. `.env.example`
  documents every variable with empty values; `.env` (gitignored, per
  existing project convention) is for local dev only.
- `ADMIN_API_TOKEN` should be a real, high-entropy secret — it is the ONLY
  gate on the trigger/status endpoints for all three background jobs.

## 8. Logging

`app/core/logging.py` configures a single stdout stream handler
(`%(asctime)s %(levelname)s %(name)s :: %(message)s`), level from
`LOG_LEVEL` (default `INFO`). This is container/platform-log-friendly
as-is (no file-based logging to lose on restart) — no changes needed for
most PaaS deployments, which capture stdout automatically.

## 9. Restart recovery

Verified by Phase 12A/12B/12C's own tests (not just claimed): a crashed
worker's `running` job-run row is reclaimed as `failed` once its heartbeat
is >10 minutes stale (`JobRunRepository.reclaim_stale_running`), so a
restart can never permanently block a job type from running again. This is
tested for all three jobs' JSON-fallback path; it will also work against
Supabase once migration 010 is applied (same code path, same table).

## 10. Pre-launch checklist (operator action items)

- [ ] Apply migrations 010 and 011 via the Supabase SQL Editor.
- [ ] Set `ADMIN_API_TOKEN` to a real secret.
- [ ] Update `cors_allow_origins` (or make it env-driven) for the real
      frontend origin.
- [ ] Set `NEXT_PUBLIC_API_BASE_URL` on the frontend deployment.
- [ ] Decide on in-process vs. external-cron scheduling for each of the
      three jobs; if external, provision that cron resource (requires
      deployment-platform access this environment does not have).
- [ ] Re-run the full backend test suite against the target environment
      once deployed, before relying on it.
- [ ] Do not enable a scheduler flag and assume it fires — verify one real
      scheduled execution actually happened, post-deploy.
