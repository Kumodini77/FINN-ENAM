# FINN Phase 12C Report — Push, Pull, UI and Deployment Readiness

Written 2026-11-15. This phase was scoped explicitly by its own P0/P1/P2
priority list (Part 10 of the request). Given the remaining time in this
session, work focused on **P0 item #1 (automatic announcement collection)**
— the one genuinely large, not-yet-built P0 gap — plus verification,
documentation, and honest gap-reporting for the rest of P0. P1/P2 items
(guidance-vs-actual, cash-quality analysis, a full company-detail UI
rebuild, a multi-rule alerts CRUD system, backfilling the remaining 6
zero-coverage companies) were **not** attempted, per the request's own
explicit instruction not to let the project expand indefinitely and to
deliver a reliable P0 experience over a partially-implemented everything.

## What was implemented this phase

### Part 2 — Automatic announcement monitoring (the main new build)
- `app/services/announcement_discovery/screener_announcement_adapter.py` —
  `ScreenerAnnouncementAdapter`: discovers a company's internal screener.in
  id from its existing company page, then parses
  `/announcements/recent/{id}/` for title, exact filed-at timestamp, a
  one-line summary, and the real exchange-hosted PDF link. Verified live
  against NSE (301), BSE's page (301) and API (403) — all blocked, same as
  the Phase 12B/filing-access-spike finding — and against screener.in
  (200, reachable) for **all 20 portfolio companies**.
- `app/jobs/announcement_discovery.py` — `run_announcement_discovery()`:
  same JobRunRepository/retry/crash-recovery shape as Phase 12A/12B's jobs.
  **Zero new classification/priority logic** — every discovered candidate
  is handed to the existing `app.services.announcement_import.import_announcement()`,
  reusing its classification (`classify_announcement`), priority scoring
  (`compute_priority`), "why it matters" generation, alert evaluation, and
  dedup (by company + source URL) unchanged.
- Admin endpoints (`POST/GET /api/admin/announcement-discovery/*`) and
  scheduler wiring, matching Phase 12A/12B's exact conventions (same
  `X-Admin-Token` gate, same cron-or-external-trigger honesty).
- **10 new tests**, all mocked (no live calls in the automated suite).

### Real, live verification (not simulated)
1. Live-checked all 20 portfolio companies against screener.in today —
   **20/20 reachable, identity-verified**.
2. Ran the real discovery + `import_announcement()` pipeline against the
   **live Supabase database** for all 20 companies —
   **94 genuinely new announcements imported**, 5 correctly deduped (TCS's,
   from an earlier manual check in this same phase), **0 failures**.
3. Confirmed via `GET /api/events` that these real announcements now flow
   through the existing classification → priority → event-grouping
   pipeline unchanged, surfacing real high-priority items (e.g. TMPV
   results, M&M board actions) alongside correctly-collapsed low-priority
   routine filings.
4. Full regression suite re-run after the live writes: **518 passed**
   (508 baseline + 10 new), zero regressions.

See `docs/FINN_ANNOUNCEMENT_COVERAGE.md` for the full per-company table and
classification breakdown.

## What was verified, not rebuilt (already working from earlier phases)

A deliberate audit, not an assumption, found these P0 items already
substantially implemented and did not need new code:

- **P0 #2 (Push classification/prioritisation)**: `EventItem.priority`,
  `PriorityBadge`, rule-based + optional-LLM classification, "why it
  matters" generation — all pre-existing and now exercised by real,
  freshly-discovered data (see above).
- **P0 #3 (Daily briefing)**: `EventsFeed`'s priority-sectioned Home view
  (built earlier this same long session, in the "Docs + safe polish" pass)
  already implements "Needs your attention / Worth a look / Other
  updates"; `EmptyState` already handles "nothing important happened."
- **P0 #4 (EOD alerts)**: `AlertsConfig` (user-defined volume/price
  thresholds, category allow-list), `evaluate_market_alert`/
  `evaluate_announcement_alert` (dedup via `AlertRepository.add()`,
  quarterly-results-triggered alerts via category+materiality), `GET
  /api/alerts` (history) all pre-existing and confirmed working. **Known
  limitation, not fixed this phase**: the config is a single global
  portfolio-wide object, not a set of individually enable/disable-able
  named rules with per-company scope — the brief's richer rules-UI vision
  (Part 3.3's "allow... enable and disable... portfolio-wide or selected
  company scope") is not fully built. Building a full rules CRUD system
  was judged P1-scale work, not a quick fix, and was deliberately not
  started.
- **P0 #5 (Results: Revenue/EBITDA/PBT/PAT, QoQ/YoY, standalone-vs-
  consolidated)**: `FinancialChange` already carries `basis`,
  `not_comparable_reason`, `comparison_period` — confirmed present in the
  schema and already surfaced in `EventCard`'s `ChangeRow` (e.g. "not
  comparable yet" when a basis mismatch is detected).
- **P0 #6 (source-linked Pull)**: `ResearchAskForm`, evidence chunks with
  `page_reference`/`original_source_url` — pre-existing, unchanged.
- **P0 #7 (mobile-friendly Home/Research)**: `Navigation.tsx`'s 4-tab
  mobile bar, `PageHeader`, responsive table degradation — pre-existing.
  A live browser screenshot at phone width was attempted this phase but
  blocked by a sandboxed-tool permission restriction; verified instead via
  a direct HTTP render check (200, no error boundary, correct DOM
  structure) — see "Known limitations" below for why this is a weaker
  check than a real screenshot.

## P1/P2 items explicitly not attempted this phase

Per Part 10's own priority list — these are real, acknowledged gaps, not
hidden:
- Four-quarter management guidance vs. actual performance (Part 4.4) — not
  built. This needs a new extraction concept (forward-looking statement
  detection + matching to later actuals) that was already flagged as
  multi-day work in `docs/FINN_IMPLEMENTATION_ROADMAP.md` from an earlier
  phase.
- Cash quality / balance-sheet analysis (Part 4.3) — not built.
- Full Pull research-overview/trajectory/bull-bear UI sections (Part
  4.1/4.2/4.5) — the underlying evidence engine supports the substance of
  these (as noted in the earlier gap analysis); dedicated UI views were not
  built this phase.
- Company-detail screen, full Alerts-creation UI, and the rest of Part 6's
  UI redesign — not built. The existing 4-screen app (Home/Portfolio/
  Research/Alerts) was not restructured.
- Backfilling documents for the 6 remaining zero-coverage companies (Part
  5) — not run this phase (Phase 12B's own report already flagged this as
  the natural next action, deliberately not bundled into an uncontrolled
  bulk operation).
- Migrations 010/011 were not applied (not this agent's call to make — see
  `docs/FINN_DEPLOYMENT_CHECKLIST.md`).

## Test results

```
518 passed (508 baseline + 10 new), 0 failed
```
Full `pytest -q` run, confirmed after the live announcement-import writes
to Supabase (to rule out any interaction between the new live data and
existing tests — none found, since every test uses JSON-fallback or mocked
repositories).

## Known bugs / issues found this phase

1. **Migration 010 still not applied live** — confirmed today via a direct
   failed write attempt (`PGRST204: Could not find the 'claimed_at'
   column`). This is a carry-over from Phase 12A, re-confirmed, not newly
   introduced.
2. **Pre-existing test-data pollution in the live `announcements` table** —
   rows with titles like "Not mine" and "Some ambiguous title that would
   otherwise be unclassified" exist in production, clearly leftover test
   fixtures from an earlier phase that ran against live Supabase without
   store isolation (before this session's current, stricter test-isolation
   convention was established). Not deleted this phase (no explicit
   approval for a destructive live-data change) — flagged here and in
   `docs/FINN_FINAL_PRODUCT_REVIEW.md` instead.
3. A live browser screenshot of the mobile Home view could not be captured
   (sandboxed tool permission denial on the screenshot command) — the page
   was verified via direct HTTP response inspection instead, which confirms
   correct server-rendered markup but not actual visual rendering/CSS.

## Recommended next phase
Given this phase closed the single largest P0 gap, the highest-leverage
next step is Part 4.4 (guidance vs. actual) — the brief calls it "one of
the most important challenge requirements" — using the now-larger real
announcement/document corpus this phase added across all 20 companies as
its input.
