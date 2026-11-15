# FINN Backend — Northflank Deployment Audit

Written 2026-11-16. Read-only audit plus the minimum safe code changes
needed to make the backend deployable — no destructive action, no migration
applied, no live data touched, no secret values written anywhere in this
repo or this report.

## 1. Dockerfile

**Did not exist before this audit.** Created `backend/Dockerfile` and
`backend/.dockerignore`.

- Base image: `python:3.14-slim-bookworm` — matches the exact interpreter
  this project runs on (`python --version` in the dev venv → 3.14.7), not an
  arbitrary older LTS. Before choosing it, every direct dependency
  (sentence-transformers, torch, pdfplumber, pydantic, pandas, pillow,
  supabase) was checked against PyPI's published wheel list for this
  interpreter — each either ships a `cp314` wheel (torch 2.15.0, pandas
  3.1.1, pillow 13.0.0) or a universal/pure-Python wheel (sentence-
  transformers, pdfplumber, pydantic). This was verified, not assumed.
- `libgomp1` is installed via apt — torch's OpenMP runtime dependency,
  missing by default on slim Debian images, a well-known real failure mode
  ("libgomp.so.1: cannot open shared object file") if omitted.
- The embedding model (`sentence-transformers/all-MiniLM-L6-v2`, pinned to
  the exact revision `app/services/embeddings/local_minilm.py` already
  pins) is downloaded **at build time**, using the identical call the app
  makes at runtime — so the container never needs outbound access to
  huggingface.co in production, and the first real request doesn't pay a
  multi-second cold download.
- **Not verified**: the image was not actually built in this environment —
  Docker Desktop's CLI is installed here but its daemon is not running, and
  starting it was outside this audit's scope. The Dockerfile's correctness
  rests on the wheel-availability check above and on matching the known-
  working dependency set in `requirements.txt`, not on a completed local
  build. **This is the single most important thing to verify before
  trusting this deployment** — build it once, locally or on Northflank, and
  confirm success before relying on it.

## 2. Startup command and PORT binding

`Dockerfile`'s `CMD` is:
```
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```
Shell form, deliberately, so `${PORT}` is expanded by the shell at container
start — Northflank (like most PaaS hosts) injects `$PORT` and expects the
process to bind to it, not to a value baked into the image. `0.0.0.0` is
required; `app/main.py` itself never reads `PORT` or binds anything — that
is correctly uvicorn's/the container's job, not application code's.

## 3. Health endpoint

`GET /api/health` (`app/api/health.py`) has **no auth dependency** and is
registered before any middleware that could block it. Confirmed by reading
the route directly — it is a plain `@router.get("/health")` with no
`Depends(...)`. Suitable as Northflank's health-check URL.

## 4. Environment variables — complete checklist

| Variable | Required? | Purpose |
|---|---|---|
| `SUPABASE_URL` | Yes (for a real deployment) | Supabase project URL. Without it, every repository falls back to ephemeral JSON files in `DATA_DIR` — fine for a demo, wrong for production. |
| `SUPABASE_KEY` | Yes | **Must be the service_role key, not anon.** `migrations/006`'s grants on `match_document_chunks` are issued to `service_role` only; writes to several tables also assume this. Treat as a secret — never commit, never log. |
| `CORS_ALLOW_ORIGINS` | Yes, for the Vercel frontend to work | JSON array of allowed origins, e.g. `["https://finn-enam-rho.vercel.app"]`. Defaults to localhost-only. **A real parsing bug was found and fixed during this audit** (see §10) — an unset or blank value is now safely treated as the default rather than crashing the app. |
| `ADMIN_API_TOKEN` | Recommended | Gates every `/api/admin/*` route (job triggers/status). Unset → those routes return 503 (safe default, not open). |
| `ANTHROPIC_API_KEY` | Optional | Only used for LLM-assisted announcement classification; rule-based classification works without it. |
| `LOG_LEVEL` | Optional | Default `INFO`. |
| `DATA_DIR` | Optional | Default `data`; the Dockerfile sets it to `/app/data`. Ephemeral — not a substitute for Supabase. |
| `MARKET_DATA_EOD_WINDOW_DAYS` | Optional | Default 20. |
| `CLASSIFICATION_LLM_CONFIDENCE_THRESHOLD`, `DEFAULT_VOLUME_SPIKE_MULTIPLE`, `DEFAULT_PRICE_MOVE_PCT`, `DEFAULT_DIGEST_WINDOW_HOURS` | Optional | Tuning defaults; sensible out of the box. |
| `EMBEDDING_PROVIDER` | Optional | Default `local_minilm` — no paid API, no key needed. |
| `ENABLE_MARKET_DATA_SCHEDULER`, `ENABLE_DOCUMENT_DISCOVERY_SCHEDULER`, `ENABLE_ANNOUNCEMENT_DISCOVERY_SCHEDULER` | Optional, **recommended `false`** | In-process APScheduler toggles — see §9. |
| `MARKET_DATA_REFRESH_CRON`, `DOCUMENT_DISCOVERY_CRON`, `ANNOUNCEMENT_DISCOVERY_CRON` | Optional | Only matter if the corresponding scheduler is enabled. |
| `DOCUMENT_DISCOVERY_MAX_NEW_DOCS_PER_COMPANY`, `DOCUMENT_DISCOVERY_LOOKBACK_QUARTERS` | Optional | Discovery backfill tuning. |
| `PORT` | Set by Northflank automatically | Not a FINN setting — consumed directly by the Dockerfile's `CMD`. |

No value for any of the above is disclosed in this report or committed anywhere in the repository.

## 5. Supabase URL and service-role key usage

Confirmed by reading `app/core/db.py`: `get_supabase_client()` creates one
client from `SUPABASE_URL`/`SUPABASE_KEY` and never distinguishes a
separate anon key — the single key supplied must be the service role key.
`storage_backend_name()` only reports `"supabase"` after an actual
read-only query against the `companies` table succeeds — a misconfigured
or wrong-privilege key fails safe into the JSON fallback rather than
crashing, but silently serving ephemeral local data in production is its
own real risk (see §10, operational note).

## 6. CORS configuration

Was hardcoded to `localhost:3000`/`127.0.0.1:3000` — the deployed Vercel
frontend (`https://finn-enam-rho.vercel.app`) would have been blocked by
the browser. Already configurable via `CORS_ALLOW_ORIGINS` through
pydantic-settings' normal env parsing, **except** a genuine bug (found and
fixed this audit — see §10): an unset-but-present-empty env var crashed
the app at startup instead of falling back to the default. Set
`CORS_ALLOW_ORIGINS=["https://finn-enam-rho.vercel.app","http://localhost:3000"]`
on Northflank.

## 7. PDF processing and embedding model requirements

`requirements.txt` already includes `pdfplumber==0.11.10` (pinned) and
`sentence-transformers` (unpinned). No system packages beyond `libgomp1`
(for torch) were found to be required by any import path exercised by the
test suite. The embedding model is pre-baked into the Docker image at
build time (§1) specifically so this isn't a runtime dependency on
Hugging Face availability.

## 8. Migrations 010 and 011

Checked live, read-only, against the real Supabase project (no write
attempted):
- **Migration 010** (`market_data_job_tracking` — widens `ingestion_jobs`
  with `claimed_at` and other job-run-tracking columns): **confirmed NOT
  applied.** A live `select claimed_at from ingestion_jobs` fails with
  `column ingestion_jobs.claimed_at does not exist`.
- **Migration 011** (`document_discovery_tracking` — new `document_sources`/
  `document_review_queue` tables): **confirmed NOT applied.** A live query
  fails with `Could not find the table 'public.document_sources'`.

Both are additive-only SQL files already written and reviewed
(`backend/migrations/010_*.sql`, `011_*.sql`). Per this project's own
established practice, they must be applied manually via the Supabase SQL
Editor by a human with access to that project — not automatically, not by
this audit, not by any deploy script.

**Practical effect until applied**: the EOD market-data refresh, document
discovery, and announcement discovery jobs all work correctly against the
JSON-fallback store (fully covered by the test suite), but their
job-run-tracking layer (duplicate-run prevention, crash recovery) will
fail if run against the live Supabase project until migration 010 is
applied; document/announcement source-health tracking and the review
queue will fail until migration 011 is applied. The underlying
discovery/ingestion logic itself does not depend on either migration.

## 9. Scheduled job reliability on Northflank

Three jobs exist (`scripts/run_market_data_refresh.py`,
`run_document_discovery.py`, `run_announcement_discovery.py`), each a
plain script exiting 0/1, built specifically for this situation. The
in-process APScheduler (`ENABLE_*_SCHEDULER` flags) is **not** recommended
as the primary mechanism on Northflank: a scaled-to-zero or restarted
service silently misses any scheduled firing while the process is down.

**Recommended Northflank setup**: deploy the web service from this
Dockerfile as normal, and separately configure Northflank's native
**scheduled Jobs** (a distinct resource type from a long-running Service)
to run the same image with its command overridden to
`python scripts/run_market_data_refresh.py` (and the other two), on their
respective cron schedules. This reuses one image for both the API and the
three jobs — no second Dockerfile needed. This was not configured as part
of this audit (it requires Northflank project/dashboard access this
environment does not have) and should not be considered done until an
operator sets it up and confirms one real scheduled firing.

## 10. A real bug found and fixed during this audit

`cors_allow_origins` is a `list[str]` Pydantic Settings field.
pydantic-settings decodes any env var for a list-typed field as JSON
**before** any `field_validator` runs. An env var set to an empty string
(an easy, realistic platform-config mistake — e.g. a Northflank env var
created but left blank) raised `SettingsError` and crashed the entire
application at import time, before a single request could be served.
Reproduced directly (not assumed), then fixed using pydantic-settings'
`NoDecode` annotation plus a validator that treats a blank string as "use
the default origins" and a non-blank string as a real JSON array to parse.
4 new tests added (`tests/test_config.py`) covering unset, blank, and
populated cases.

## 11. Other missing production configuration — none found beyond the above

- `requirements.txt` has mostly unpinned versions (only `pdfplumber` is
  pinned). Not a blocker — the wheel-availability check in §1 confirms
  current versions install cleanly — but worth pinning for long-term
  reproducibility. **Not changed this audit**, since doing so broadly
  without rebuilding and re-testing against every pin would itself be a
  risk, not a safety improvement, under this audit's "only necessary
  changes" instruction.
- No `Procfile` or `render.yaml`/`northflank.json` exists or was added —
  Northflank is configured via its own dashboard/API using the Dockerfile
  directly; no additional manifest file is required for a Dockerfile-based
  service.

## Files changed

- `backend/Dockerfile` — new.
- `backend/.dockerignore` — new.
- `backend/app/core/config.py` — `cors_allow_origins` now uses `NoDecode` +
  a validator; fixes the blank-env-var crash. No other field changed, no
  default value changed.
- `backend/.env.example` — documents `CORS_ALLOW_ORIGINS` and clarifies
  `SUPABASE_KEY` must be the service-role key. No secret values added.
- `backend/tests/test_config.py` — new, 4 tests.
- `docs/FINN_NORTHFLANK_DEPLOYMENT_AUDIT.md` — this report.

## Test results

```
535 passed, 0 failed
```
(531 pre-existing + 4 new, full `pytest -q` run after all changes.)

## Outstanding blockers

1. **The Docker image has not actually been built or run** in this
   environment (no running Docker daemon available here) — confirm a real
   `docker build` succeeds before deploying.
2. **Migrations 010 and 011 are not applied** to the live Supabase
   project — required before the job-tracking/source-health features work
   against it (the core API, Push, and Pull paths do not depend on either).
3. **`SUPABASE_KEY`, `CORS_ALLOW_ORIGINS`, and `ADMIN_API_TOKEN` must be
   set on Northflank** — none of these exist as defaults suitable for
   production.
4. **No scheduled job has been configured on Northflank** — the scripts
   exist and are tested against the JSON-fallback store; nothing triggers
   them automatically yet.

## Is the backend ready to deploy?

**Not yet, but it is close and the blockers are concrete, not open-ended.**
The code, Dockerfile, and environment-variable story are in place and
tested (535 passing tests, a real crash bug found and fixed). What remains
is operational, not architectural: build and run the image at least once
to confirm it actually starts, apply the two pending migrations, set the
three environment variables above on Northflank, and configure the
scheduled jobs. Until those four things happen, this report does not claim
the deployment is complete.
