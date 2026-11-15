# FINN Daily Intelligence Upgrade

Written 2026-11-15.

## Root cause of the empty feed

Not a category-preselection bug, not a scraping-coverage bug (those are real
but secondary) — **the primary cause was the default 24-hour window**,
confirmed live: `GET /api/events?window_hours=24` → **0 events**, while
`GET /api/events?window_hours=168` (7 days) → **64 events**. The 94+ real
announcements imported in Phase 12C span Nov 5–14; a 24h window from "now"
(Nov 15) genuinely has nothing in it most days. No category was preselected
(`EventsFeed` had no category filter UI at all; `DigestFeed`'s category set
started empty = unfiltered). `event_date` was already correctly the
announcement's real `filed_at`, never the ingestion date — verified in
`app.services.event_grouping.Event.event_date` (earliest `filed_at` among
grouped announcements).

## Fix: intelligent empty-window fallback + three real activity streams

- When the 24h window returns 0 events, the page now also fetches the 7-day
  window and shows it as a **separate, clearly labelled** "Latest available
  portfolio activity" section — never silently merged into the 24h filter.
- **Company activity**: unchanged data source (`/api/events`), reused as-is.
- **Market pulse** (genuinely new): a new backend endpoint,
  `GET /api/market-data/portfolio/pulse`, computes daily / 5-session /
  20-session % change and volume-vs-average from real stored EOD history
  (`fetch_history`, the same call the existing quote endpoint uses) against
  **fixed editorial thresholds** (±2% daily, ±5% over 5 sessions, ±10% over
  20 sessions, ≥1.5× average volume) — **explicitly not** the user's
  configured alert thresholds. Verified live today: 10 of 20 portfolio
  companies cross at least one threshold (e.g. M&M +19.3% over 20 sessions,
  TMPV −3.3% today) — real, deterministic, zero fabrication.
- **Fundamental watch**: reuses `EventItem.financial_changes` (already
  computed by the existing, tested `event_intelligence` pipeline from the
  `financial_metrics` table) — **honest finding: 0 of 64 real events
  currently have financial_changes populated**, because financial-metric
  import is a separate manual step nobody has performed for the real 20
  portfolio companies (the only 3 rows in `financial_metrics` today are
  leftover test fixtures for an unrelated company, not real data). The
  section therefore shows a compact, honest "no validated fundamental
  changes yet" note rather than any fabricated ratio or conclusion.

## Daily Intelligence vs. Alerts — kept separate

Market Pulse's thresholds live in `app/services/market_data.py` as fixed
constants (`PULSE_*`), completely independent of `AlertsConfig`
(`volume_spike_multiple`/`price_move_pct`). A 1.5% move can appear in Market
Pulse without ever creating a row in the `alerts` table; a move that clears
the user's own configured threshold creates a real alert (unchanged logic)
and may *also* appear in Market Pulse with a different, editorial framing.
No alert is ever created from an ordinary Daily Intelligence item.

## Tests

8 new backend tests (`TestMarketPulse` in `tests/test_market_data.py`):
threshold crossing/non-crossing, volume-only trigger, single-item-per-company
dedup, insufficient-history honesty, ticker generalization, endpoint
reachability. **A real test-pollution bug was found and fixed**: the pulse
endpoint test's unmocked `PortfolioRepository` call leaked a real Supabase
company_id into the process-global `company_lookup` cache, breaking an
unrelated cross-company-isolation test run later in the same process —
reproduced deliberately, then fixed by mocking `PortfolioRepository` for
that one test. Full suite: **531 passed, 0 failed**.

## Known limitations

- Market Pulse cards don't show a sparkline (would add 10+ more live history
  fetches on an already request-heavy page — deferred, see the performance
  report).
- Fundamental Watch has no real data to show today — this is accurately
  reported, not hidden.
- A dedicated company-timeline view (clicking into one company's full
  chronological history) was **not built** this phase — a real, sizeable
  feature correctly deferred rather than rushed.
