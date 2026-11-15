# FINN Automation Foundation — Audit (Phase 12A)

Written 2026-11-15, before implementation. Findings below are from direct code
inspection and one live test run against this session's actual configured
Supabase project — not assumptions.

## 1. Does a scheduler or background worker already exist?
**No.** `grep`-ing the whole backend for scheduler/cron/background code turns up
only the *word* "background" inside `app/api/alerts.py`/`app/services/alert_evaluation.py`
(alerts evaluated as a side effect of a request, not on a schedule) and
`app/api/market_data.py` itself. No APScheduler, Celery, cron file, or worker
process exists anywhere in the repo before this phase.

## 2. How is the application deployed, and does scheduled execution survive restarts?
**Not currently deployed anywhere.** `docs/submission-checklist.md` (written in an
earlier phase) explicitly records: "Not deployed anywhere. No external account
created, no service made public, per your explicit instruction." No
`render.yaml`, `Procfile`, Dockerfile, or other deployment-infra file exists in
the repo. This matters directly for this phase's scheduling design: there is no
real production process today whose uptime an in-process scheduler could rely
on, and no deployment path to verify "survives restarts" against. The design
below is therefore built to be deployment-agnostic and is **not** claimed to be
verified in production — see `FINN_PHASE_12A_REPORT.md` §"Actual deployment
requirements".

## 3. How is market data currently fetched, stored, and exposed?
`app/services/market_data.py` calls `yfinance` **live, synchronously, on every
request** to `GET /api/market-data/portfolio` and `GET /api/market-data/{ticker}`.
Nothing is ever persisted. This is explicit in the route's own docstring:
"This hits yfinance for each ticker on every call — fine for a prototype's demo
scale... a production version would cache this behind the scheduled ingestion
job described in architecture.md rather than fetching live per-request." Phase
12A's job is exactly that scheduled ingestion job.

A `prices` table, and a generic `ingestion_jobs` audit table (with a
`job_type` check constraint that already listed `'price_fetch'`), have existed
in the schema since `migrations/001_init.sql` — but a direct grep of the
codebase confirms **neither table is read or written anywhere**. This is the
same "table exists since Phase 1, nothing ever used it" situation
`app/repositories/portfolio.py`'s own docstring documents for the `portfolio`
table. Phase 12A wires these two dormant tables up rather than creating
parallel ones, per the instruction to reuse existing components.

One related, pre-existing inconsistency worth flagging (not fixed this phase,
out of scope): `GET /api/market-data/portfolio` iterates the static
`app.core.companies.PORTFOLIO` constant, not the live `PortfolioRepository` —
so a portfolio add/remove wouldn't show up in that endpoint's quotes today.
The new scheduled job in this phase correctly reads from
`PortfolioRepository` as instructed; the pre-existing live-quotes endpoint's
own use of the static list is a separate, smaller gap left untouched to avoid
unrequested scope creep.

## 4. Manual vs. automatic refresh today
Entirely manual/implicit: a refresh only happens when a client calls the
portfolio-quotes endpoint. There is no background refresh of any kind.

## 5. Error, staleness, and duplicate-execution handling today
None exists, because no background execution exists yet. The live-request path
already has solid real-time error handling (`PriceQuote.data_available=False` +
`error` message, EOD-vs-provisional labeling) — this phase's job reuses the same
`market_data.fetch_history`/`SessionStatus` logic rather than reimplementing it,
and adds the job-level concerns (retry, timeout, duplicate-run prevention,
crash recovery) that a request-scoped call never needed.

## Conclusion driving the implementation
Reuse `app.services.market_data.fetch_history` as-is (no changes to its tested,
documented EOD/provisional-split logic). Add two small, additive pieces: a
durable job-run tracker (extending the existing, unused `ingestion_jobs` table)
and a price-bar store (writing to the existing, unused `prices` table) — both
with a JSON-fallback mirror for local/test use, matching every other repository
in this codebase. See `FINN_PHASE_12A_REPORT.md` for what was actually built.
