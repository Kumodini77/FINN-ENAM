# FINN Product Gap Analysis

Written: 2026-11-15 (submission day). Scope and method note: this document
was produced under the "Docs + highest-leverage safe polish" decision — see
the conversation log. It audits the **actual, currently-running** FINN
system (not a planned one) against ENAM's requirements, a realistic
investor workflow, and comparable products. Every "Working" claim below was
checked against real code paths and, where feasible, the running app —
not inferred from a function's existence. See `docs/requirements.md` for
the REQ/EX/OPT classification this document assumes.

Status vocabulary used throughout: **Working** / **Partially working** /
**Missing** / **Blocked by data source** / **Needs validation**.

---

## 1. Push

### 1.1 Daily digest / events feed
- **Required behaviour**: surface portfolio-relevant disclosures, filtered
  and prioritised, over a configurable window (default 24h).
- **Existing implementation**: `EventsFeed`/`DigestFeed` on the Home page,
  backed by `/events` and `/digest`. Events are grouped from announcements,
  carry a `priority` (`high`/`medium`/`low`), `why_it_matters`, and
  structured `financial_changes` (QoQ/YoY). `DateRangeFilter` supports
  24h/7d/30d/custom — window is **not** hardcoded to 24h.
- **What was missing (fixed today)**: the Home page rendered events as one
  flat list regardless of priority — a wall of cards, which is exactly the
  "AI slop" pattern CLAUDE.md prohibits. Fixed: events now render under
  three sections ("Needs your attention" / "Worth a look" / "Other
  updates") using the `priority` field the backend already returns.
  Frontend-only, additive, verified via `tsc --noEmit` and a live dev-server
  render.
- **User impact**: a user with 20 portfolio companies can now triage in
  seconds instead of reading every card.
- **Priority**: P0 (this is the single highest-visibility "no AI slop"
  grading criterion on the most-viewed screen).
- **Status**: **Working** (fixed this session).

### 1.2 Quarterly results: Revenue/EBITDA/PBT/PAT, QoQ+YoY
- **Required behaviour**: hard requirement (not an example) per CLAUDE.md
  rule 4 — must surface these four metrics with both QoQ and YoY deltas.
- **Existing implementation**: `EventItem.financial_changes: FinancialChange[]`
  already carries `metric`, `label`, `qoq_pct`, `yoy_pct`, `direction`, and
  an explicit `not_comparable_reason` when a delta can't be computed safely
  (e.g. ambiguous period binding — see `test_multiline_header_patterns.py`).
  This is rendered in `EventCard`'s `ChangeRow`.
- **What is missing**: coverage depends entirely on whether the ingested
  PDF's results table was extractable without ambiguity. Of 13 ingested
  documents, several quarterly tables (ICICI p.46, Tata Steel p.20) are
  **deliberately left unresolved** rather than guessed, per the
  non-fabrication rule — so for those companies this quarter, PAT/PBT may
  show "not comparable yet" instead of a number. This is correct, safe
  behaviour, not a bug, but it does mean the requirement is only
  **structurally** satisfied, not **universally** satisfied across every
  ingested company-quarter.
- **Status**: **Working** for cleanly-tabulated filings; **Partially
  working** (by design — refuses to fabricate) for multi-line/merged-header
  tables. Needs validation: a user-facing sanity count of how many of the
  13 docs produce all 4 metrics vs. partial vs. none.

### 1.3 Configurable alert thresholds (volume multiple, price move %)
- **Required behaviour**: hard requirement per CLAUDE.md rule 4.
- **Existing implementation**: `AlertsConfig` (`volume_spike_multiple`,
  `price_move_pct`, `digest_window_hours`, `alert_categories`) is a real,
  persisted, per-user config surfaced via `AlertsConfigForm` on the Alerts
  tab — not hardcoded constants.
- **Status**: **Working**.

### 1.4 Management-change enrichment (outside-source allowed)
- **Required behaviour**: optional (EX), explicitly allowed to use outside
  sources per CLAUDE.md rule 1's carve-out.
- **Existing implementation**: `management_change` is a recognised
  announcement category end-to-end (classification, badge, priority
  scoring). A dedicated bio-enrichment step (fetching outside background on
  the named executive) was **not found** in the current backend route
  inventory.
- **Status**: **Missing** (category classification works; the enrichment
  step itself does not exist). P2 — explicitly an example in the brief, not
  a hard requirement, and CLAUDE.md rule 1 only tells us it's *allowed*, not
  that it's required.

### 1.5 Announcement ingestion (17 categories)
- **Existing implementation**: all 17 categories from the brief are modeled
  in `AnnouncementCategory` and classified. Live NSE/BSE scraping is **not**
  implemented — `announcement_import.py`'s own docstring documents that this
  was tried and found blocked (`docs/filing-access-spike.md`), so ingestion
  is manual-import by deliberate, already-justified design.
- **Status**: **Blocked by data source** (not a gap to silently "fix" with
  unauthorized scraping — CLAUDE.md forbids that, and the brief calls
  ingestion plumbing, not the point).

---

## 2. Pull

### 2.1 Primary-source-only research
- **Required behaviour**: hard constraint — never answer from LLM
  pretraining, never use news/broker notes as evidence.
- **Existing implementation**: `hybrid_retrieval.py` retrieves only from
  ingested chunks; `numeric_answer.py` is a **deterministic, non-LLM**
  extractor for numeric facts — the LLM is not even in the loop for the
  highest-stakes answer type. Evidence chunks always carry
  `source_chunk_id`/`source_document_id`/`page_reference` back to the UI.
- **Status**: **Working**, and verified multiple times this session via a
  cross-company evidence-isolation check (每 evidence set only ever contains
  chunks tagged with the asked-about ticker — "no leaks detected" in the
  latest run) and a 4-numeric-fact/2-ambiguous-metric/14-evidence-digest/
  0-incorrect benchmark.

### 2.2 Generalizes to any NSE ticker
- **Existing implementation**: `companies.py`'s own docstring states this
  explicitly and the registry is pure seed data; `to_yfinance_symbol` and
  ticker resolution work for any ticker, not just the seed list.
- **Status**: **Working**, confirmed by code inspection (no ticker-specific
  branches anywhere in `pdf_extraction.py`, `numeric_answer.py`,
  `period_resolution.py`, `unit_scale.py`).

### 2.3 8 Pull output types (business snapshot, financial snapshot,
trajectory, balance sheet, cash quality, narrative-vs-numbers, guidance,
bull/bear)
- **Required behaviour**: these are explicitly EX (menu items), not REQ,
  per CLAUDE.md rule 3.
- **Existing implementation**: `ResearchAskForm`/`/research/ask` implements
  a **general question-answering** interface (numeric_fact /
  evidence_digest / insufficient_evidence), not 8 distinct named views. A
  user can ask "What was X's PAT in Q2FY27?" (numeric_fact) or "What did
  management say about margins?" (evidence_digest), which covers the
  *substance* of several of the 8 menu items (financial snapshot,
  narrative-vs-numbers) through one flexible interface rather than 8
  dedicated screens.
- **Status**: **Partially working** — the underlying retrieval/evidence
  engine supports the substance of most of the 8 menu items; the UI does
  not yet present them as named, guided views. Correctly scoped out of
  today's build per the user's explicit decision (no multi-screen UI
  rewrite). P1 for a future phase, not P0 — these are illustrative, not
  required.

### 2.4 Guidance-vs-actual reasoning
- **Required behaviour**: EX, explicitly called out as the one place the
  stronger model should be reserved for (CLAUDE.md rule 6).
- **Existing implementation**: no dedicated guidance-vs-actual comparison
  endpoint was found. `evidence_digest` answers can surface guidance
  language if it's in the retrieved chunk, but there's no structured
  "promised X, delivered Y" comparison.
- **Status**: **Missing**. P1 — valuable, not required, and a real build
  (needs a new extraction concept: identifying forward-looking statements
  in one filing/concall and matching them to actuals in a later one). Too
  large to safely attempt same-day without risking a half-built, broken
  feature — explicitly the outcome CLAUDE.md rule 8 says to avoid.

### 2.5 Cost efficiency (cheap model for classification/bulk, strong model
for Pull synthesis)
- **Existing implementation**: numeric answers bypass the LLM entirely
  (free, deterministic). Classification uses the cheaper model tier.
- **Status**: **Working**, by the architecture itself rather than a policy
  that could silently drift — there's no code path where classification or
  bulk extraction can accidentally call the expensive model.

---

## 3. UI / mobile-first

- **Existing implementation**: `Navigation.tsx` already implements a
  4-destination mobile tab bar + desktop sidebar (Home/Portfolio/
  Research/Alerts) — this independently converged with Part 8.1's
  suggested structure before this request existed. `PortfolioTable`
  degrades gracefully per-row when a quote is unavailable, labels EOD vs.
  provisional-intraday data explicitly, and never fabricates a stale value
  as live.
- **Gap found**: the Home page's `EventCard` "why it matters" text and
  category/priority badges are good, but there was no priority-based
  grouping until this session's fix (§1.1).
- **Status**: **Working** for the shipped screens; a full redesign (company
  detail page, dedicated research-view screens) was explicitly descoped
  today by user decision, not attempted, and is **not** claimed as done.

---

## 4. What this document is NOT claiming
No feature below "Working" above was silently patched to look done. Items
marked Missing or Partially working were deliberately left alone today —
per CLAUDE.md rule 8 ("thin-but-working beats broad-but-broken") and the
user's own explicit scope decision — rather than rushed into an untested
state on submission day.
