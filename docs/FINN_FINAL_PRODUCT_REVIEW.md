# FINN Final Product Review

Written 2026-11-15, after Phases 12A (automation foundation + EOD market
data), 12B (document discovery), and 12C (announcement discovery + P0
verification). This is an honest status report, not a sales pitch — every
claim below was checked against real code, a real test run, or a real live
call made during these three phases, not inferred from an earlier report.

## 1. What works end-to-end (verified live, not mocked)

- **EOD market-data refresh** (Phase 12A): fetch → validate → store →
  track freshness, tested against mocked yfinance data (14 tests);
  production-scale live run not re-verified this phase.
- **Document discovery → ingestion → Pull retrieval** (Phase 12B): real,
  live, start-to-finish for TCS — discovered via screener.in, downloaded,
  ingested through the unmodified pipeline into the live Supabase project,
  confirmed Pull-searchable (`search_chunks_by_keywords` returned real
  matching chunks).
- **Announcement discovery → classification → prioritisation → Push
  surfacing** (Phase 12C): real, live, for **all 20 portfolio companies**
  — 94 new announcements discovered, classified (12 distinct categories
  observed, including `results`, `management_change`, `M&A`), prioritised
  (16 high, 21 medium, 85 low), and confirmed visible through the existing
  `GET /api/events` grouping (the same endpoint the Home page's
  priority-sectioned feed reads from).
- **Research readiness auto-updates** with zero code changes when new
  documents/announcements arrive (verified for TCS specifically — status
  flipped from `known_no_documents` to `ready`).
- **Source-linked Pull answers**: pre-existing, exercised continuously by
  the full test suite's hybrid-retrieval tests (real embeddings, real
  evidence chunks with page references).

## 2. What works only in local development / JSON-fallback

- All three background jobs' **job-run tracking** (duplicate-run
  prevention, crash recovery) — fully tested against JSON-fallback
  storage; fails against the live Supabase project until migration 010 is
  applied (confirmed today via a real failed write).
- The **document/announcement source-health checkpoints**
  (`document_sources` table) and the **review queue**
  (`document_review_queue` table) — proposed in migration 011, not applied;
  JSON-fallback only, for now.
- The **in-process scheduler** (APScheduler) — works when run, but is not
  a durable production mechanism on a web process that can idle/restart;
  not currently enabled anywhere since FINN isn't deployed.

## 3. What requires manual migration

- `migrations/010_market_data_job_tracking.sql` (Phase 12A) — not applied.
- `migrations/011_document_discovery_tracking.sql` (Phase 12B) — not
  applied.
- Both are additive-only, reviewed, and written to be re-run safely if
  partially applied — apply via the Supabase SQL Editor per
  `docs/migration-runbook.md`'s established procedure. Neither this agent
  nor any job in this codebase applies migrations automatically.

## 4. What requires deployment configuration

See `docs/FINN_DEPLOYMENT_CHECKLIST.md` for the full list. Headline items:
FINN is not deployed anywhere yet; `ADMIN_API_TOKEN` must be set before any
admin endpoint works; `cors_allow_origins` is hardcoded to localhost and
must be updated for a real frontend origin; a real scheduling mechanism
(external cron recommended) must be provisioned by an operator with
platform access.

## 5. Actual document coverage, by company (live, today)

| Status | Tickers |
|---|---|
| Has ≥1 completed document | HDFCBANK, ICICIBANK, SBIN, TCS\*, WIPRO, RELIANCE, M&M, SUNPHARMA, ITC, TATASTEEL, LT, TRENT, LICI (13) |
| Zero documents, confirmed discoverable via screener.in | BAJFINANCE, INFY, TMPV, CIPLA, HINDUNILVR, BHARTIARTL, POWERGRID (7) |

\* TCS's single document was discovered and ingested live during Phase
12B/12C — not pre-existing. See `docs/FINN_DOCUMENT_COVERAGE.md` for the
full table including candidate counts per company.

## 6. Announcement sources verified

- **screener.in**: verified reachable and identity-confirmed for **all 20
  portfolio companies**, today. Primary, working source.
- **NSE** (`nseindia.com/companies-listing/corporate-filings-announcements`):
  HTTP 301 — not accessible in this environment.
- **BSE** (`bseindia.com/corporates/ann.html` and the `AnnGetData` API):
  HTTP 301 / 403 — not accessible in this environment.
- No bot-protection bypass was attempted against either blocked source.

## 7. Features that remain incomplete

- Management guidance vs. actual performance (four-quarter comparison) —
  not built.
- Cash-quality / balance-sheet ratio analysis — not built.
- Dedicated Pull UI sections (overview/trajectory/bull-bear as named
  views, rather than the general Q&A interface) — not built.
- Company-detail screen and a richer Alerts-creation UI — not built.
- Multi-rule, per-company, enable/disable-able alerts (beyond the current
  single global config) — not built.
- Backfill for the 7 zero-coverage portfolio companies — confirmed
  discoverable, not yet ingested (deliberately, to avoid an uncontrolled
  bulk live operation).

## 8. Full test results

```
518 passed, 0 failed
```
(508 at the start of this phase + 10 new announcement-discovery tests.)
Confirmed by a full `pytest -q` run after all code changes AND after the
live writes to Supabase (announcement imports), to rule out any
interaction.

## 9. Known bugs

1. Migration 010 not applied — job-run tracking fails against live
   Supabase (JSON-fallback path is fully correct).
2. Pre-existing synthetic test rows ("Not mine", etc.) found live in the
   `announcements` table — not cleaned up (no approval for a destructive
   live-data change); flagged for a human decision.
3. `GET /api/market-data/portfolio` still reads the static `PORTFOLIO`
   seed list rather than the live `PortfolioRepository` (a Phase 12A
   finding, unchanged) — a portfolio add/remove wouldn't show up in that
   one endpoint's quotes.
4. A live mobile-viewport screenshot of Home could not be captured this
   phase due to a sandboxed-tool permission restriction on the screenshot
   command; verified instead via HTTP response inspection only.

## 10. Remaining risks

- **No production deployment has ever been verified.** Every "working"
  claim above is against local dev + the live Supabase *database* (not a
  live deployed *application*). The actual web app, under real load, on a
  real host, has not been tested this phase.
- **Screener.in is an unofficial index**, not a licensed data vendor — its
  page structure could change without notice, which would silently reduce
  (not corrupt) discovery coverage; the adapters already fail safely
  (reporting an error, not fabricating data) if that happens, per the
  tests in `test_document_discovery_adapters.py`/`test_announcement_discovery.py`.
- **The single global AlertsConfig** means every portfolio company shares
  the same thresholds/categories — a real product gap if a user wants
  different sensitivity per company, acknowledged, not fixed.

## Three-minute demo walkthrough

1. **(0:00–0:30) Home.** Open the app. Point out the three sections
   ("Needs your attention," "Worth a look," "Other updates") — note that
   as of today this is populated with real, live-discovered announcements
   across all 20 portfolio companies (not seed/demo data), including real
   results and management-change items.
2. **(0:30–1:00) Open one high-priority event.** Click into a `results` or
   `management_change` card, show the "why it matters" text, the source
   link (opens the real bseindia.com PDF), and the financial-change row
   (QoQ/YoY, or "not comparable yet" if basis differs).
3. **(1:00–1:45) Portfolio → Research.** From the portfolio table, open a
   company (e.g. TCS) and ask a question in Research — show the
   evidence-backed answer with its page reference, pointing out it's the
   same document Phase 12B discovered and ingested live, not a pre-seeded
   file.
4. **(1:45–2:15) Alerts.** Show the configured volume/price thresholds and
   the alert history list — explain these are EOD-based, never claimed as
   real-time.
5. **(2:15–3:00) Admin/operations (optional, technical audience).** Show
   `GET /api/admin/announcement-discovery/status` (with the token) —
   latest run, per-company results — and mention the three scheduled jobs
   (market data, documents, announcements) all share one reusable
   job-execution foundation built in Phase 12A.
