# FINN — Implementation Roadmap (proposed)

Status: planning only. No phase below has started. Deadline: 15 November 2026.

Ordering principle: de-risk the unverified/highest-risk pieces first (NSE/BSE access, extraction quality), per architecture.md §7-8, rather than building UI against assumed-working data.

---

## Phase 0 — Spike / verification (no product code)

**Goal:** resolve the architecture's open risk items before committing to the full build.

- Verify yfinance actually returns clean EOD data for a sample of 5-10 NSE/BSE tickers.
- Verify what NSE/BSE filing access actually looks like in practice (API, scrape, or third-party aggregator) for a small sample of companies — this is the #1 architecture risk.
- Verify screener.in page structure: confirm annual report + concall transcript links are reliably scrapable, for 2-3 sample companies.
- Decide LLM provider(s) and embedding model based on free-tier availability and the two-tier routing plan.

**Exit criteria:** we know, concretely, whether each of the three data sources is viable as planned, or whether a fallback (e.g. a smaller manually-seeded announcement set) is needed for the demo.

**Testing:** manual — run small scripts against real tickers, inspect output by hand. No automated tests needed yet.

---

## Phase 1 — Project foundation ✅ DONE

- Company registry (15 portfolio + 4 ad-hoc), FastAPI skeleton, market-data service (yfinance, closed-EOD-vs-provisional-intraday distinction, verified live), Next.js frontend shell with a working Portfolio page. Database migrations written (not applied — no Supabase project provisioned). 89 backend tests at end of Phase 1 scope.

---

## Phase 2 — Push engine ✅ DONE (Supabase persistence verified in a follow-up pass)

Built as ten modules (requirements tracked as Modules 1–10 in the Phase 2 build conversation), each tested before the next started:

1. **Announcement data model + persistence** — Pydantic models matching the schema; a repository layer that uses Supabase when configured AND reachable, falling back to a JSON-file store (`backend/data/*.json`) otherwise. `GET /api/health`'s `storage_backend` field reports whichever is actually active, verified by a real round-trip query, never assumed. A follow-up integration pass connected a real Supabase project, found and fixed a genuine schema mismatch (ticker vs. company_id, missing columns, non-uuid primary keys — see `docs/database-schema.md` and `backend/migrations/004_phase2_schema_fixes.sql`), and added a mocked test suite covering the translation layer plus a one-time live smoke test. Dedup enforced in Python on (company, original_source_url), backed by a real unique index on the Supabase side.
2. **Manual filing import** — `POST /api/announcements/import` (+ `/import/batch`), a CLI (`backend/scripts/import_announcements.py`), and a minimal frontend form (`/admin/import`). No NSE/BSE scraper was built — `docs/filing-access-spike.md`'s finding (both exchanges block non-browser clients site-wide) stands. **The real data store ships empty**: no fabricated filings were seeded; an import template documents the expected shape.
3. **Classification** — hybrid: a keyword rule table covering all 17 categories runs first (free, deterministic); an optional Anthropic call only fires for genuinely ambiguous titles and only if `ANTHROPIC_API_KEY` is set (it isn't, in this environment — classification runs rule-based-only, with a safe `unclassified` fallback, never blocking on a missing key).
4. **Priority engine** — `category_weight × recency_decay`, documented formula, fixed thresholds for high/medium/low, fully unit-tested including monotonic recency decay.
5. **Results extraction** — QoQ/YoY computed deterministically from human-transcribed `financial_metrics` rows (not automated PDF parsing — no reliable automated extraction pipeline exists given the filing-access findings); basis/currency/unit mismatches are detected and block the comparison rather than silently mixing bases.
6. **Market anomaly detection** — built on top of (not inside) the Phase 1 `market_data` service; provisional/intraday bars are always excluded from anomaly checks, confirmed by test.
7. **Daily digest** — `GET /api/digest`, window-configurable (24h default, 7-day shortcut, explicit start/end), category-filterable, priority-sorted, routine items collapsed.
8. **Alert system** — volume-spike and price-move alerts (configurable thresholds, defaults 2× / ±5%) plus material-announcement alerts (configurable category list), evaluated as a side effect of `GET /api/market-data/portfolio` and `POST /api/announcements/import` — not on a schedule, matching "no continuous real-time monitoring" exactly.
9. **Frontend** — Daily Intelligence (time-window selector, priority/category badges, collapsible routine section, original-filing links, loading/empty states), Alerts (triggered list + threshold/category config form), Portfolio (extended with anomaly indicator dots + latest-announcement line), Admin import page.
10. **Testing** — 89 backend tests total (up from Phase 1's baseline), covering all 17 categories, dedup, priority math, date filtering, digest sorting, configurable thresholds, provisional-bar exclusion, QoQ/YoY, alert dedup, and 9 full API-integration tests through `TestClient`.

**Not built in Phase 2** (explicitly out of scope per the brief's phasing, or deferred):
- Management-change LinkedIn/bio enrichment (brief's Push example) — not requested in the Phase 2 scope given to the build; a reasonable next addition, same pattern as `why_it_matters` generation.
- Automated PDF-based financial extraction — `financial_metrics` is populated by human-transcribed values at import time, per the filing-access findings.
- A background scheduler — alert evaluation is request-triggered, by design.

**Supabase wiring — verified end-to-end in a follow-up pass:** connected a real Supabase project, ran migrations 001-003 live, and found (via a real insert/read-back/delete test, not assumed) a genuine schema mismatch between the repositories and the live schema. Fixed by adding a ticker↔company_id and demo-user-id translation layer (`backend/app/repositories/{company_lookup,app_user}.py`) and a new additive migration, `004_phase2_schema_fixes.sql` (written, reviewed, not yet applied — see `backend/migrations/README.md`). A mocked test suite now covers the translation logic, duplicate-key race handling, and the unknown-ticker registration path (generalizing beyond the 19 seeded companies, per requirements.md §3) without touching the live database in CI. One live round-trip smoke test was run manually to confirm the fix; a second pass is needed once migration 004 is applied to re-verify end-to-end. Known from this pass: an earlier, now-fixed test-isolation bug briefly caused test runs to write synthetic rows into the live `announcements`/`financial_metrics` tables — flagged in `docs/database-schema.md`, cleanup pending confirmation.

---

## Phase 3 — RAG corpus (fundamentals ingestion)

**Depends on:** Phase 0B (`docs/fundamentals-access-spike.md`), which confirmed screener.in is a reliable discovery/index layer but most of the documents it links to (BSE-hosted) are blocked, and company IR sites are hit-or-miss per company (HDFC Bank worked, TCS didn't). Independent of Phase 1-2 work (can run in parallel if capacity allows).

- `fundamentals_fetcher`: given a ticker, pull annual report + concall transcript links from screener.in, attempt the real document download, and fall back to a manually-seeded document (hand-collected, same pattern as the Phase 0 announcements fallback) when the automated attempt fails. Extract text from whichever document lands, by either path.
- Chunking strategy (size/overlap TBD during implementation) + embedding → `chunks` table.
- Lazy-trigger: if a Pull request comes in for a ticker with no existing `documents`, run this fetcher synchronously/on-demand before proceeding.

**Testing:** verify chunk retrieval quality manually — run a known factual query against a company's embedded chunks and confirm the right section comes back.

---

## Phase 4 — Pull: research synthesis

**Depends on:** Phase 3.

- RAG retrieval + strong-LLM synthesis, with primary-source-only system prompt and mandatory citation to `chunk_id`/section.
- Implement, in priority order (per architecture.md §8): guidance-vs-actual (last 4 quarters), business snapshot, financial snapshot; remaining 5 menu items as stretch.
- `POST /research/{ticker}?type=` endpoint; cache results in `research_outputs`.
- Guardrail check: a lightweight pass that flags any synthesized claim not traceable to a retrieved chunk (even a simple heuristic is better than none, given this is an explicit requirement).

**Testing:** manual review of generated outputs against the actual source documents for 3-5 companies — specifically checking for hallucinated claims not present in the primary sources (this is the single most important quality gate per the brief's "no AI slop" + primary-source-only requirements).

---

## Phase 5 — Pull frontend

**Depends on:** Phase 4.

- Mobile-first per-company research view, reachable from the Push feed (tap a company → research view) and via direct ticker search (for arbitrary/ad-hoc NSE tickers).
- Render each Pull output type with citations visible/tappable (supports the "ground truth, no slop" bar).

**Testing:** manual, on a phone-width viewport, for both portfolio and ad-hoc companies, including at least one ticker not in either demo set (proving generalization, per requirements.md §3).

---

## Phase 6 — Polish, deployment, submission prep

- Deploy frontend (e.g. Vercel) + backend (e.g. Render/Fly.io) + confirm Supabase is on a reachable tier.
- Final pass on "no AI slop" bar: density, collapsing of routine noise, visual design consistency.
- Prepare AI build-history export (this Claude Code session / others used).
- Write the covering note: what was built, trade-offs, what was deliberately left out, next steps.
- Final check: does the deployed link work on an actual phone, cold, with no prior state?

---

## Dependency summary

```
Phase 0 (spike, done) ──┬──> Phase 1 (foundation, done) ──> Phase 2 (Push engine, done)
                         └──> Phase 3 (RAG corpus, not started) ──> Phase 4 (Pull synthesis) ──> Phase 5 (Pull UI)

Phase 2 + Phase 5 ──> Phase 6 (polish + submit)
```

## Cut-line if time runs short

Per "thin-but-working beats broad-but-broken," if deadline pressure forces cuts in the remaining (Pull-side) work, cut in this order (last listed = cut first):
1. Stretch Pull menu items (bull/bear, cash quality, balance sheet) beyond the top 3.
2. ~~Triggered alerts on announcement categories beyond EOD anomaly~~ — done in Phase 2, both types shipped.
3. Management-change bio enrichment — already deferred out of Phase 2; stays deferred.
4. Breadth of portfolio (demo with fewer than 15-20 if ingestion time runs out) — but never cut the *generalization* requirement (arbitrary ticker support) since that's explicitly tested by ENAM.
