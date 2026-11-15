# FINN Phase 12B Report — Automatic Company Document Discovery and Ingestion

Written 2026-11-15. Implemented and tested, not just designed. Read
`docs/FINN_DOCUMENT_COVERAGE.md` (the audit + live verification results) and
`docs/FINN_DOCUMENT_SOURCE_REGISTRY.md` (what each adapter is) alongside this
report.

## 1. What was implemented

### Reusable source adapters
- **`ScreenerSourceAdapter`** (`app/services/document_discovery/screener_adapter.py`)
  — real, generalizable (works for any ticker, zero per-company config),
  verified live against all 20 portfolio companies. Confirms company identity
  via full-token-containment against the page title (hardened mid-phase after
  a test caught it almost confusing TMPV with TMCV under a looser threshold —
  see §5).
- **`IRWebsiteSourceAdapter`** (`app/services/document_discovery/ir_website_adapter.py`)
  — real, generic HTML crawler for a company's own IR site, given a verified
  seed URL. One seed verified this phase (HDFCBANK); the adapter code itself
  has zero per-company logic.

### Discovery job — reusing Phase 12A's foundation, not a second framework
- **`app/jobs/document_discovery.py`** — `run_document_discovery()`: same
  shape as Phase 12A's `run_market_data_refresh()` — one `JobRunRepository`
  batch run, `run_with_retry`-style resilience, one company's failure never
  blocking another, duplicate-run prevention, crash recovery via the same
  stale-heartbeat reclaim mechanism. **No second scheduler or job framework
  was created.**
- **Triage before any download**: dedup by exact source URL AND by
  `(doc_type, reporting_period)` against existing documents — catches both
  "we've seen this exact link before" and "two different hosts mirror the
  same real filing" (observed live: TCS's Jul-2026 transcript is mirrored on
  both bseindia.com and tcs.com). Backfill is bounded
  (`document_discovery_max_new_docs_per_company`, default 6) and prioritizes
  transcripts/presentations over annual reports, per the "four-quarter
  comparison" need in the brief.
- **Ambiguous candidates never auto-ingest** — anything with unconfirmed
  identity or an unrecognized doc_type goes to `ReviewQueueRepository`
  instead.
- **Ingestion reuses the existing pipeline unchanged** —
  `app.services.ingestion.ingest_document()` is called exactly as-is; this
  phase added zero new logic to extraction, chunking, embedding, or the
  numeric-fact/period-integrity protections.

### Durable source tracking (never an in-memory dict)
- **`DocumentSourceRepository`** (`app/repositories/document_sources.py`):
  per-(ticker, source) checkpoint — last checked, last successful check,
  last discovered document, health (`healthy`/`degraded`/`blocked`/`unknown`),
  error message.
- **`ReviewQueueRepository`** (`app/repositories/document_review_queue.py`):
  pending/approved/rejected candidates, never auto-ingested.
- Both backed by two NEW tables proposed in
  **`migrations/011_document_discovery_tracking.sql`** — purely additive,
  **written and reviewed, not applied** (same established practice as
  migrations 007–010; this agent has no DDL access via the Supabase REST
  client in any case). JSON-fallback is what every test in this phase
  actually exercises.

### Admin surface, scheduling — reusing Phase 12A's conventions exactly
- `POST /api/admin/document-discovery/run` (409 on an already-active run),
  `GET /api/admin/document-discovery/status`,
  `GET /api/admin/document-discovery/review-queue` (read-only) — all gated
  by the same `X-Admin-Token` convention as Phase 12A's market-data admin
  routes, 503 when unconfigured.
- `app/services/scheduler.py` extended (not duplicated) to optionally also
  schedule document discovery (`ENABLE_DOCUMENT_DISCOVERY_SCHEDULER`,
  `DOCUMENT_DISCOVERY_CRON`, default 19:30 IST Mon–Fri, after the market-data
  slot). Same off-by-default, external-cron-recommended honesty as Phase 12A
  — see `docs/FINN_PHASE_12A_REPORT.md` §4, which applies unchanged here:
  **FINN is still not deployed anywhere**, so no production scheduling claim
  is made.
- `scripts/run_document_discovery.py` — standalone CLI, same pattern as
  Phase 12A's market-data script.

## 2. Companies successfully checked / documents discovered

Live-verified today against the real screener.in site for **all 20
portfolio companies** (not a sample) — see the full table in
`docs/FINN_DOCUMENT_COVERAGE.md`:
- **20/20** reachable, identity-verified.
- Candidate counts ranged from 28 (TRENT) to 157 (M&M) real annual-report +
  concall-transcript + investor-presentation links per company.
- **7/20 portfolio companies had zero existing documents** before this phase
  (BAJFINANCE, INFY, TMPV, CIPLA, HINDUNILVR, BHARTIARTL, POWERGRID) — all 7
  are confirmed discoverable; none have been backfilled yet (see §7 "Not
  done this phase" — a full 20-company backfill run was deliberately not
  executed automatically, to avoid an uncontrolled bulk live-scrape during
  this session; see honesty note below).

## 3. The real end-to-end proof (not simulated)

Performed live, once, against **TCS** (chosen because it had zero prior
documents — genuine new coverage, not a duplicate):
1. Discovery: `ScreenerSourceAdapter.check("TCS", "Tata Consultancy Services Ltd")` → 71 real candidates, identity verified.
2. Download: the most recent concall transcript, 723 KB, valid PDF, from `bseindia.com`.
3. Ingestion: through the unmodified `ingest_document()` pipeline, against the **live Supabase project** → document `d2ad3364-39cc-422b-831c-18cb261b0f8c`, 74 chunks, `ingestion_status = completed`.
4. Research readiness: `check_research_readiness("TCS")` → `"ready"`, confirmed to update automatically with **zero code changes** (it has always derived its answer live from `DocumentRepository`).
5. Pull retrieval: `DocumentRepository.search_chunks_by_keywords()` against the new document returned real matching chunks (TCV, AI revenue, segment commentary) — genuinely searchable, not just stored.

This is the one real, officially-sourced, end-to-end workflow the acceptance
criteria require. It was **not** repeated for all 20 companies live during
this phase (see §7) — that would be a full, uncontrolled backfill across the
whole portfolio in one sitting, which the phase's own "do not indiscriminately
download entire document archives" and "prioritise coverage gaps first, with
configurable limits" instructions argue against doing all at once, outside a
deliberate, monitored, incrementally-scheduled run.

## 4. Documents rejected or sent for review

None were rejected during the real live check (all 20 companies passed
identity verification) — this reflects screener.in's reliability for this
portfolio, not an absence of the review-queue mechanism, which is fully
built and tested (`TestIncorrectCompanyIdentity` in
`tests/test_document_discovery_job.py` exercises it directly with a
synthetic failed-identity case, since a real one didn't occur today).

## 5. A real bug found and fixed during this phase

The identity-matching heuristic was originally a 60%-token-overlap check.
A test deliberately modeled the TMPV/TMCV confusion risk this phase's brief
explicitly warns about ("Tata Motors **Passenger** Vehicles Ltd" vs. a
hypothetical "Tata Motors **Commercial** Vehicles Ltd" page) and caught that
60% overlap (3 of 4 shared words) wrongly passed. Fixed to require full
token containment — re-verified against the real TCS, TMPV, and HDFC Bank
page titles to confirm the stricter rule doesn't produce false negatives for
genuine matches. See `app/services/document_discovery/screener_adapter.py`'s
`_identity_matches` docstring.

## 6. Tests and results

New test files:
- `tests/test_document_discovery_adapters.py` — 8 tests: screener discovery,
  wrong-company-identity rejection, TMPV/TMCV non-confusion, timeout/404
  handling, IR-adapter no-seed-URL honesty, domain-restricted PDF discovery,
  off-domain link rejection.
- `tests/test_document_discovery_job.py` — 13 tests: successful
  discovery+ingestion, live-PortfolioRepository usage, ad-hoc exclusion,
  incorrect identity routing to review, TMPV/TMCV separation at the job
  level, duplicate URL and duplicate-period dedup, invalid PDF rejection,
  failed download handling, partial company failure isolation, duplicate-run
  prevention, crash recovery, existing-document preservation, and
  research-readiness auto-update after a real ingest.

All mocked — no live network calls in the automated suite (the one real,
live check in §3 was a manual verification, documented with its actual
output, not part of `pytest`).

```
508 passed in 60.37s
```
Full existing suite (487, per the Phase 12A baseline) **plus the 21 new
tests**, zero regressions, confirmed by a full `pytest -q` run.

**A genuine flakiness was found and fixed during this phase, not swept
under the rug**: two of the new tests made an unmocked, real network call
(`get_or_register_company_id("TCS")`, a legitimate Supabase lookup) before a
later, unrelated test file's embedding-based ranking assertions ran. This
real network call measurably perturbed CPU/thread scheduling enough to flip
a near-tied cosine-similarity ranking in `test_hybrid_retrieval.py` between
two very close candidate chunks — reproduced deliberately (adding the same
probe call to `tests/conftest.py` triggered the identical failure, then
removed again) to confirm the root cause before fixing it. Fixed by mocking
that call in the two affected tests, per this phase's own "no live external
calls in ordinary unit tests" instruction, which should have been applied
there from the start.

## 7. What was NOT done this phase (honestly)

- **No full 20-company backfill was run.** Only TCS was actually ingested
  live. The other 6 zero-coverage companies (BAJFINANCE, INFY, TMPV, CIPLA,
  HINDUNILVR, BHARTIARTL, POWERGRID) are confirmed discoverable but not yet
  backfilled — running the real job against all of them is a deliberate,
  monitorable next action (via the admin trigger or the CLI script), not
  bundled into this report as if it already happened.
- **Migration 011 is not applied.** The JSON-fallback source-tracking path
  is fully tested; the Supabase-backed path requires a human to run the
  migration via the Supabase SQL Editor first (same process as migrations
  007–010).
- **The IR-website adapter has only one verified seed URL.** Extending it to
  more companies is a pure data change (`investor_relations_seeds.py`), not
  attempted broadly this phase to avoid guessing at 19 real companies' site
  structures/bot postures without verification.
- **No production scheduling is active** — FINN is still not deployed
  anywhere (per Phase 12A's own finding, unchanged).

## 8. Manual setup still required
1. Apply `migrations/011_document_discovery_tracking.sql` via the Supabase
   SQL Editor (same procedure as 007–010).
2. Set `ADMIN_API_TOKEN` to use the new admin endpoints (shared with Phase
   12A's).
3. Decide whether/when to run a full backfill across the remaining 6
   zero-coverage companies — recommended via the manual admin trigger first
   (to watch results), not blindly scheduled.
4. Verify and add more `investor_relations_seeds.py` entries over time, if
   the IR-website adapter (tier 1) is to become more than a one-company
   proof.

## 9. Recommended next implementation phase
Run the real discovery+ingestion job (via the admin trigger, watched) against
the 6 remaining zero-coverage companies one at a time, verifying each one's
result before moving to the next — closing the honest gap this phase's audit
found, using the infrastructure this phase built, without a second
uncontrolled bulk operation.
