# FINN Production Quality Audit

Scope: the seven problems reported against the deployed app (Vercel frontend, Railway backend, Supabase DB). For each, the actual root cause, the affected files, and what was required to fix it — not just the visual symptom.

## 1. Movement colour correctness (negative shown green)

**Root cause:** `frontend/components/PortfolioTable.tsx` computed direction as
`(quote.daily_change_pct ?? 0) >= 0`. The nullish-coalescing fallback meant a
*missing* percentage (no quote, or `data_available: false`) defaulted to `0`,
which the `>= 0` check then classified as positive → rendered green. The
backend's actual sign calculation (`backend/app/services/market_data.py:104-106`,
`(latest_close - previous_close) / previous_close * 100`) was verified correct —
the bug was entirely in the frontend's handling of the *absent* case, not a
sign inversion on real data.

There was also no single shared colour utility — `PortfolioTable.tsx` and
`components/EventsFeed.tsx` each computed "up/down" independently, which is how
a null-handling bug could exist in one place without being caught by the other
using a different (correct) signal (`financial_changes[].direction`, computed
in `backend/app/services/event_intelligence.py:50-57`, already correctly
returns `"not_available"` for null/zero and was not itself buggy).

**Fix:** `frontend/lib/movement.ts` (new) — one `movementTone()` function, used
everywhere a percentage needs a colour. Missing/null now resolves to `neutral`,
never `positive`.

**Test:** no frontend test runner exists in this repo (see §4 of the fix
report) — verified by `tsc --noEmit` type-checking the new call sites and by
reading the three affected call sites to confirm each converts a quote through
`movementTone()` rather than a local comparison.

## 2. "Positive Momentum" filter returning the wrong companies

**Root cause:** the filter did not filter on price movement at all.
`PortfolioTable.tsx`'s `filter === "positive"` checked `row.status ===
"positive"`, where `status` comes from `computeStatus()`
(`frontend/lib/portfolioStatus.ts`) — a business-event signal (does this
company have a push event with `financial_changes[].direction === "positive"`
and no high-priority alert?), completely independent of whether the stock's
price actually moved up or down that day. A company with a stock up 4% but no
recent Push event would show `status: "stable"` and never match "Positive
Momentum"; a company flat on price but with an old positive earnings event
would.

A second, compounding bug: the sector filter and the status filters shared one
`filter` state variable, so choosing a sector silently reset any momentum
selection (`filter === "sector" ? ... : "all"` on the `<select>`'s `onChange`)
— the brief's "search and sector filters work together with momentum filters"
requirement could not have been satisfied by this structure.

**Fix:** added `frontend/lib/movement.ts`'s `movementTone()` as the single
signal for a new `momentum` field per row, derived straight from
`quote.daily_change_pct`. Momentum filtering (`all` / `positive` / `negative`
/ `stable` / `limited_data`) and sector filtering are now independent state
(`momentumFilter`, `sectorFilter`) applied together with search as a single
AND predicate. `status` (business-event severity) is unchanged and still
drives the "Needs attention" badge/dot — it was never wrong, just wrongly
reused for a different filter.

**Test:** `tsc --noEmit` confirms the new filter predicate type-checks;
verified by reading the new `filteredRows` memo logic directly against the
five required momentum semantics (positive/negative/stable/limited/all) and
the "combine with sector + search" requirement.

## 3. "Ask FINN about this company" returning insufficient evidence too often

**Root cause:** `backend/app/api/research.py`'s `/research/ask` endpoint only
ever retrieves from chunks of *ingested* primary-source documents
(`retrieve_hybrid_evidence`). For any company with zero ingested PDFs/
transcripts — which is the common case, since document ingestion is a separate
manual step from the rest of the pipeline — every question returns
`insufficient_evidence`, with no explanation of *why*, even for a question
market data could answer (e.g. "how has the price moved recently").

This was flagged to the project owner as a scope decision rather than silently
changed: `CLAUDE.md`'s non-negotiable constraint #1 requires Pull research
output to be grounded only in primary-source document chunks, and explicitly
forbids incorporating "news" into Pull answers — which conflicts with widening
retrieval to market data/announcements as originally requested. The owner
confirmed: keep Pull PDF-only, but make the failure honest and actionable.

**Fix:** `/research/ask`'s no-evidence branch now calls
`app.services.research_readiness.check_research_readiness()` (already existed,
was previously unused by this endpoint) to distinguish "no documents ingested
yet" from "documents ingested but none completed" from "genuinely no matching
chunk found," and returns a new `sources_checked` field (what was actually
looked at) and, when the company has real market data but no documents, a
`suggested_alternative` pointing at the Portfolio/Daily Intelligence pages
instead of a dead end. No new evidence source was added to Pull itself.

**Test:** `backend/tests/test_research_api.py` — added
`test_insufficient_evidence_for_company_with_no_documents_suggests_portfolio_data`
asserting the reason text, `sources_checked`, and `suggested_alternative` are
all populated for a `STATUS_KNOWN_NO_DOCUMENTS` company. Full backend suite:
536/536 passed.

## 4. Sparkline animation speed

**Root cause:** not a bug — `components/Sparkline.tsx` already had a
draw-on-load animation, direction/colour correctly computed from real
historical closes (`isPositive = closes[last] >= closes[0]`, not the daily
badge), and reduced-motion support, but at 900ms, faster than the requested
1200–1800ms range.

**Fix:** `ANIMATION_MS` changed 900 → 1400.

## 5. Application loading speed

**Root cause:** `frontend/lib/api.ts`'s `request()` hardcoded
`cache: "no-store"` on every single call — nothing was ever cached, so every
page visit (and every component re-mount) refetched company metadata, EOD
quotes, and per-company price history from scratch, including the portfolio
page's fan-out of one history request per tracked company. The fan-out itself
was already parallelized with `Promise.all` (not a sequential-await bug), but
with no caching it ran in full on every visit.

**Fix:** added a small in-memory TTL cache (`cachedRequest()` in
`frontend/lib/api.ts`) with in-flight request de-duplication, applied only to
data that is safe to reuse briefly — company list (5 min), EOD quotes/pulse
(45s), price history (5 min). Alerts, digest, events, and research answers are
deliberately left on `no-store`: those must stay live.

See the fix report for what performance work this does *not* cover (bundle
splitting, lazy-loading, DB query/index review, before/after measurement).
