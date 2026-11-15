# FINN Production Quality — Fix Report

Companion to `FINN_PRODUCTION_QUALITY_AUDIT.md`. States plainly what was done,
what was verified, and — per explicit instruction — does not claim production
is fixed beyond what was actually tested.

## Files changed

| File | Change |
|---|---|
| `frontend/lib/movement.ts` (new) | Single shared signed-percentage → colour/tone utility |
| `frontend/components/PortfolioTable.tsx` | Rewired momentum filter to use real `daily_change_pct`; sector/momentum/search now combine (AND); colour sites use `movementTone()` |
| `frontend/components/Sparkline.tsx` | Animation duration 900ms → 1400ms |
| `frontend/lib/api.ts` | Added TTL cache + in-flight de-dup for company list / quotes / price history / pulse; left alerts/events/digest/research on `no-store` |
| `frontend/app/globals.css` | Re-tokenized light/dark theme to the supplied six-colour palette; `--color-positive`/`--color-negative` kept as unambiguous green/red in both themes |
| `backend/app/api/research.py` | No-evidence branch now calls `check_research_readiness()`, returns `sources_checked` + `suggested_alternative` |
| `backend/app/schemas/research.py` | Added `sources_checked`, `suggested_alternative` fields |
| `frontend/types/api.ts`, `frontend/components/ResearchAskForm.tsx` | Surface the two new fields in the insufficient-evidence view |
| `backend/tests/test_research_api.py` | Fixed a real cross-test pollution bug the new readiness call exposed (mocked `check_research_readiness` in the existing no-evidence test); added one new test for the suggested-alternative behaviour |

## Root causes identified

See `FINN_PRODUCTION_QUALITY_AUDIT.md` for the full detail on each. Summary:

1. Movement colour: `?? 0` fallback treated missing data as `0 >= 0` → green. Not a sign inversion on real data.
2. Positive Momentum filter: filtered on business-event `status`, not price `daily_change_pct` — two unrelated signals.
3. Insufficient evidence: correct behaviour for a PDF-only Pull engine against an un-ingested company, but gave no explanation. Resolved by making the failure explain itself (sources checked, concrete alternative) rather than by widening what Pull treats as evidence — that would have conflicted with `CLAUDE.md`'s primary-source-only rule; confirmed with the project owner before implementing.
4. Sparkline: correct logic, just too fast (900ms vs. requested 1200–1800ms).
5. Loading speed: `cache: "no-store"` hardcoded on every API call — a real caching gap, not a rendering or query problem.

## Portfolio colour and filter fixes

- `movementTone()`: `positive` (pct > 0) / `negative` (pct < 0) / `neutral` (pct === 0 or missing). Applied at all three sites that previously computed direction locally (desktop row, mobile card).
- Momentum filter (`all`/`positive`/`negative`/`stable`/`limited_data`) now reads `daily_change_pct` directly, independent of sector/search, and all three combine as one predicate.
- Summary tiles updated to count by momentum (positive/negative/limited) rather than conflating with business-event status; "Needs attention" tile kept, now clearly separate from momentum.

## Sparkline animation

Duration raised to 1400ms (within the requested 1200–1800ms range), ease-out curve, reduced-motion handling, and "animate once per dataset" behaviour were already correct and unchanged.

## Research retrieval improvements

Pull's evidence source was **not** widened — this was an explicit scope
decision (see audit §3), confirmed with the project owner rather than made
unilaterally, because the brief's suggestion to use market data/announcements
as Pull evidence conflicts with `CLAUDE.md`'s locked primary-source-only rule.
What changed is honesty and actionability of the failure case: a company with
no ingested documents now gets a reason that says so explicitly, what was
checked, and — when real market data exists for it — a pointer to where that
data actually lives (Portfolio / Daily Intelligence pages).

## Visual design system

Re-tokenized `globals.css` (light + dark + `prefers-color-scheme`) to the
supplied Warm Sand / Muted Rose / Deep Burgundy / Deep Teal / Sage Green / Soft
Sage palette: Deep Teal as the primary accent/brand anchor, sand/sage as
secondary surfaces, Muted Rose repurposed as the warning/caution colour.
`--color-positive` and `--color-negative` were deliberately **not** remapped
to palette colours — kept as a clear green and a burgundy-leaning red
respectively, per the explicit instruction that financial movement colour
correctness overrides palette purity. No component files needed changes
beyond the tokens themselves: a repo-wide grep confirmed no hardcoded hex
colours exist outside `globals.css`, so every component already inherits the
new palette automatically.

**Not done in this pass:** a from-scratch visual redesign of each page's
layout/typography/spacing (cards, charts, buttons, empty states as individual
design exercises). The existing layouts were already built with the token
system from an earlier design pass; this pass only changed what the tokens
resolve to. No live screenshot verification was performed (no running
instance was driven in a browser during this session) — the palette change
was verified by `next build` compiling successfully and inspection of the
generated CSS variables, not by visual inspection.

## Performance work actually done — and its limits

Done:
- Removed the unconditional `cache: "no-store"` on every request; added a
  small TTL cache (45s for quotes/pulse, 5 min for company list/history) with
  in-flight de-duplication, so navigating between pages no longer refetches
  identical data that's seconds old.
- Confirmed (by reading the code, not assuming) that the existing
  cross-component data fetches were already parallelized with `Promise.all` —
  there was no sequential-await antipattern to fix.

**Not done** — explicitly, so this isn't mistaken for complete:
- No before/after latency measurement was taken (no running dev server was
  driven with real network timing in this session).
- No bundle-size analysis or code-splitting/lazy-loading work.
- No backend database query/index review — the repositories were not
  profiled for N+1 or slow-query patterns beyond what the caching layer
  already sidesteps on the frontend.
- No loading-skeleton/progressive-loading redesign beyond what already
  existed (`PortfolioTable.tsx` already skeleton-loads).

If page load speed is still unacceptable after this change, the next real
step is to actually run the app and measure with the browser's network panel
— guessing further without a live measurement would not be honest.

## Tests executed and results

- Backend: `pytest` full suite — **536 passed, 0 failed** (535 existing + 1 new).
- Frontend: `tsc --noEmit` — clean. `next build` — succeeds, all routes compile.
- **No frontend unit/integration test runner exists in this repository** (no
  test script in `package.json`, no `*.test.ts(x)` files). This is a pre-existing
  gap, not something broken by this change — the brief's request for frontend
  tests covering filter/colour/chart cases was not fulfilled, because doing so
  properly means first choosing and wiring up a test runner (e.g. Vitest +
  Testing Library), which is a real infrastructure decision beyond this pass's
  scope. Flagging this explicitly rather than fabricating test results.

## Remaining limitations

- Mobile responsiveness: existing components already use a desktop-table /
  mobile-card split pattern and Tailwind breakpoints, but this was verified by
  reading the code, not by rendering at phone width in a real browser.
- Daily Intelligence (§9 of the brief) was found to already satisfy the stated
  requirements (EOD labelling, empty states, event/alert separation) from a
  prior rebuild in this project's history — not re-verified against a live
  instance in this pass.
- No manual deployment steps are required by anything in this fix set — all
  changes are code-only; no new environment variables, migrations, or
  infrastructure changes were introduced.

## Is production fixed?

The three specific bugs reported (colour, filter, insufficient-evidence
opacity) are fixed and covered by passing tests/typechecks, within the scope
agreed with the project owner. Broader claims — "the app is fast now," "the
redesign is complete," "mobile works" — are not made here, because they were
not verified against a live, running instance in this session.
