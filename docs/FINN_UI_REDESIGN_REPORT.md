# FINN UI/UX Redesign Report

Written 2026-11-15. This covers a coordinated redesign of Portfolio, Research,
Alerts, Home, and the shared design system (theming, tokens). Scope was large;
this report is honest about what was built, what was verified, and what was
deliberately not attempted, rather than claiming full coverage of every
sub-item in the original brief.

## 1. The "15 vs 20" portfolio-count bug — root cause and fix

**Root cause**: `app/portfolio/page.tsx`'s `PageHeader` subtitle contained the
literal hardcoded string `"15 tracked companies"` — a stale number written at
some earlier point and never updated as the portfolio grew to 20. It was
**not** a filtering, pagination, sector-grouping, or stale-data bug — the
underlying `/api/companies?portfolio_only=true` and `PortfolioRepository`
already correctly returned 20 (confirmed by a live query: `len(tickers) == 20`
with all 20 tickers present). The fix: removed the hardcoded number entirely;
the Portfolio page now reads and displays the live count from
`PortfolioTable`'s own fetched data (`{summary.total} tracked companies`),
never a static string.

**A second, related, real staleness bug was found and fixed while
investigating this**: `GET /api/companies?portfolio_only=true` and
`GET /api/market-data/portfolio` both iterated the **static** `PORTFOLIO` seed
constant rather than the live `PortfolioRepository` — meaning a company
added/removed via `POST`/`DELETE /api/portfolio` would never show up (or
disappear) from either endpoint, even though it happened to return the
correct count *today* only because no one has used those write endpoints yet
in this build. Both endpoints now read `PortfolioRepository().list_companies()`
/ `.list_tickers()` directly. Verified live: `GET /api/companies?portfolio_only=true`
still returns all 20 tickers, now via the live path. All 523 backend tests
pass after this change (no regressions).

## 2. Theme system

A full light/dark CSS-variable token system **already existed** in
`globals.css` (including an OS-preference media-query fallback) but had no
user-facing control. Added:
- `components/ThemeToggle.tsx` — sun/moon icon button (sun shown in dark mode,
  moon shown in light mode, per the spec), wired into both the desktop
  sidebar and the mobile header so it's never hidden on small screens.
- An inline script in `app/layout.tsx`'s `<head>` that reads
  `localStorage`/OS preference and sets `data-theme` **before paint** — no
  flash of the wrong theme.
- Persistence via `localStorage` (`finn-theme` key), wrapped in try/catch for
  private-browsing/blocked-storage environments.
- New design tokens: `--color-warning`/`--color-warning-soft` (amber,
  previously only available as raw hardcoded Tailwind `amber-*` classes in
  four components — all four migrated to the new token) and
  `--color-teal`/`--color-teal-soft` (the suggested secondary accent) and
  `--color-positive-soft`/`--color-negative-soft`, for both light and dark
  themes. The primary accent was deepened to a true forest green (`#0f3d33`)
  per the suggested palette.

## 3. Portfolio page — complete redesign

- **Search**: a top-of-page, always-visible input filtering by company name
  or ticker, case-insensitive, substring match, live as you type.
- **Filters**: All / Positive momentum / Needs attention / Limited data,
  plus a sector dropdown — all backed by real computed data, not arbitrary.
- **Sector grouping**: real `Company.sector` metadata (13 distinct real
  sectors across the 20 companies), collapsible via native `<details>`,
  each showing a live count.
- **Status categories** (`lib/portfolioStatus.ts`): `needs_attention` /
  `positive` / `stable` / `limited_data` — deterministic and explainable,
  built ONLY from two real backend signals: whether an EOD quote exists at
  all, and the priority/financial-change-direction of the company's most
  recent Push **event** (itself already computed by the existing, tested
  backend priority engine) — never from price-percentage movement alone,
  and never a fabricated score. Hovering a desktop row shows the exact
  reason; mobile cards show the same reasoning via the status badge + latest
  update line.
- **Mobile cards** replace the old compressed table on small screens:
  top row (name/ticker/sector/price), middle row (% change, volume, status),
  bottom row (sparkline, latest update). All of this is visible without
  horizontal scrolling or opening the company.
- **Sparklines** (`components/Sparkline.tsx`): a small inline-SVG line chart
  from real EOD closes (no chart library added — the project had none
  installed, and the brief said to avoid adding a large unnecessary
  dependency). Colored green/red by whether the *selected period's* last
  close is above or below its first (never colored by a single day's move).
  Shows "Not enough history" rather than a line when fewer than 5 real bars
  are available. Labeled "1M" implicitly via the 30-day default window.
- **Portfolio summary strip**: real counts (positive / needs attention /
  important updates / limited data) — explicitly NOT presented as
  profitability or returns, since no position/cost-basis data exists in this
  build.

### New backend endpoint required for sparklines
`GET /api/market-data/{ticker}/history?days=30` (`PriceHistoryResponse`,
`DailyBar[]`) — reuses the existing, already-tested `fetch_history()` call
`build_price_quote` already makes; excludes any provisional/intraday bar the
same way the existing quote logic does. 5 new backend tests, all passing.
Verified live against TCS: 30 real closed bars returned.

## 4. Research — insight-first restructuring

Rebuilt around a **"FINN's view"** card that always appears first, followed
by "Reported facts," a collapsed "View supporting documents and evidence"
section, and contextual "What should I check next?" follow-up chips
(clickable — they re-run the question through the same form).

**An explicit, documented scope decision**: the brief's example "FINN's view:
Mixed... Revenue has grown but margins weakened..." requires synthesizing a
qualitative Positive/Mixed/Cautious *verdict* from multiple financial
signals. The backend's Pull endpoint (`/api/research/ask`) returns, per
question, either one cited numeric fact, a set of evidence passages, an
ambiguous-metric clarification, or an honest "insufficient evidence" —
**not** a multi-metric trend comparison (that machinery exists only on the
Push/events side, for curated portfolio events, not for arbitrary ad-hoc
Pull questions). Synthesizing a Positive/Mixed verdict from a single cited
number or a handful of prose passages, with no LLM configured, would mean
either fabricating a judgement the data doesn't support or silently
guessing — both explicitly forbidden by this project's standing rules. The
"FINN's view" card therefore shows an honest, evidence-grounded status
(*Reported figure found* / *Evidence found* / *Needs clarification* /
*Insufficient evidence*) rather than a fabricated qualitative verdict.
This is flagged here explicitly, not silently scoped down.

Other fixes:
- `types/api.ts` was missing the `ambiguous_metric` answer type and
  `metric_alternatives` field, even though the backend already returns them
  — a real latent bug (an ambiguous-metric response would have silently
  fallen through to a bare evidence list with no explanation). Fixed, and
  the new "FINN's view" card now explicitly surfaces the competing metric
  names for the user to disambiguate.
- The technical "no LLM configured" disclosure (`generation_note`) was
  previously the first, most prominent line on every response (italic,
  top of the card). It's now a small, de-emphasized line at the very
  bottom — still always shown, never hidden, just no longer the headline
  message (per the explicit instruction not to hide the limitation while
  also not making it the dominant visible message).
- Warning styling (unreliable/needs-review evidence) migrated from hardcoded
  `amber-*` Tailwind classes to the new `--color-warning` tokens.

Verified live: asked a real question against TCS's actually-ingested
transcript (discovered and ingested in Phase 12B/12C) — `evidence_digest`
response with 5 real cited passages rendered correctly against the new
component.

## 5. Alerts — accurate labelling

**Root cause of the generic "Material filing" label**: the backend already
computed a real announcement `category` and `priority` for every
material-announcement alert (`compute_priority`) and included both in the
alert's `payload` — the frontend simply never read them, showing only the
generic `trigger_type` ("Material filing") instead. Fixed:
- **What happened** (`categoryLabel(payload.category)`, e.g. "Results",
  "Management Change") is now shown separately from **how important**
  (`PriorityBadge` using the real stored priority).
- Market alerts (volume/price) get a deterministic priority too — "high" only
  when the actual move cleared **twice** the user's own configured
  threshold, never from an arbitrary scale.
- **Sections**: "Needs attention" (high priority) vs. "Other recent alerts",
  plus a separate "Watch rules" panel (in `AlertsConfigForm`) stating the
  active rules in plain English ("Notify me when a portfolio company moves
  more than 3% in a day (EOD)...").
- **Trigger reasons made visible**: for price/volume alerts — previous
  close, latest close, % change, the user's own configured threshold,
  volume vs. average volume, and the EOD data date. For announcement
  alerts — the real "why it matters" text and a direct link to the source
  filing, plus a one-click "Ask FINN about this" research action.
- Every EOD-based alert is explicitly labeled "EOD" — never implied
  real-time.

### Backend payload enrichment required
`evaluate_market_alert`/`evaluate_announcement_alert` previously stored only
1-3 fields per alert. Both now also store the real previous/latest
close, configured threshold, average volume (market alerts), and
`why_it_matters`/`original_source_url`/`filed_at` (announcement alerts) — all
values the evaluator already had in scope, nothing fabricated or newly
computed. 523 backend tests pass after this change (26 alert-specific tests
re-verified directly).

## 6. Home — briefing structure

Added two sections the brief specifically asked for, reusing the existing
(already-tested) backend priority/direction fields — no second,
independently-invented scoring system:
- **Positive developments**: events (excluding already-"needs attention"
  ones) whose `financial_changes` include a real `direction: "positive"`
  entry.
- **Market watch**: EOD volume/price alerts within the selected window
  (client-side time-filtered, since `/api/alerts` has no server-side window
  param), explicitly EOD-labeled.
- **Other updates** is now a collapsed `<details>` (was always-expanded),
  per "routine items should be collapsed."
- An honest empty state ("Nothing important happened in this window") when
  all four sections are empty, rather than ever padding the screen with
  routine filler.
- A top-of-page search field that jumps straight into Research with the
  typed ticker.

## 7. APIs changed

| Endpoint | Change |
|---|---|
| `GET /api/market-data/{ticker}/history` | **New** — sparkline data. |
| `GET /api/companies?portfolio_only=true` | Now reads live `PortfolioRepository`, not the static seed list. |
| `GET /api/market-data/portfolio` | Same live-portfolio fix. |
| `evaluate_market_alert` / `evaluate_announcement_alert` (internal) | Enriched `Alert.payload` — additive fields only, no removed field, no behavior change to *when* an alert fires. |

No database schema change, no migration required for any of this phase's work.

## 8. Tests performed

- Backend: **523 passed, 0 failed** (full `pytest -q`), including 5 new tests
  for the history endpoint/function.
- Frontend: `tsc --noEmit` clean, `eslint .` clean (one real lint error found
  and fixed — a setState-in-effect issue in the new `ThemeToggle`), and a
  full production `next build` succeeded for all 4 routes.
- Live verification: confirmed real API responses for `/api/companies`,
  `/api/market-data/TCS/history`, `/api/events`, `/api/research/ask`, and
  `/api/alerts` all match what the rebuilt components expect, using the
  real portfolio/document/announcement data from Phases 12A-12C (not seed
  fixtures).

## 9. Before / after

- Portfolio: "15 tracked companies" (wrong, hardcoded) → live count, search,
  sector groups, mobile cards with visible price/change/volume/sparkline,
  explainable status badges.
- Research: a bare evidence-chunk dump with the AI-limitation notice as the
  headline → an insight-first card structure with honest status, clickable
  next-questions, and the limitation notice demoted to a small footer line.
- Alerts: "Material filing" (meaningless) → real category + priority +
  why-it-matters + trigger numbers + source link, split into
  attention/other sections.
- Home: flat event list → attention/positive/market-watch/other structure
  with routine items collapsed and an honest empty state.
- Entire app: no theme control → working, persistent, flash-free light/dark
  toggle reachable from every screen, desktop and mobile.

## 10. Known limitations

- **No real screenshots could be captured this phase.** A headless-browser
  screenshot command was blocked by this environment's own sandboxed-tool
  permission classifier (same restriction encountered in Phase 12C). All
  responsive/visual verification here is via `tsc`/`eslint`/`next build`
  success, direct inspection of the component code's responsive classes
  (`md:hidden`/`md:block` pairs for the table-vs-cards split), and real API
  response shapes — not an actual rendered screenshot at 375/390/430px.
  This is a materially weaker check than a visual screenshot and should be
  treated as such.
- Research's "FINN's view" deliberately does not produce a qualitative
  Positive/Mixed/Cautious investment verdict (see §4) — this is a scope
  decision driven by the anti-fabrication rule, not an oversight.
- The "Management guidance versus actual" comparison table (brief §4.8) was
  not built — the backend has no guidance-extraction/matching logic yet
  (confirmed absent in Phase 12C's own report); showing it without real data
  would mean fabricating rows, which was not done.
- Alerts' enriched payload fields were verified by unit tests and by
  inspecting real (older) alert rows gracefully degrading when the new
  fields are absent, but no *new* live volume/price alert happened to fire
  during this phase's verification window to confirm the enriched shape
  end-to-end against a freshly-triggered real alert.
- "Portfolio value" / "current portfolio trend" (brief §2.1) were correctly
  omitted — no real position or cost-basis data exists in this build, and
  the brief itself says to show these "only if actual position and cost
  data exist."
