# FINN Document Source Registry (Phase 12B)

Reference for what each document-source adapter is, how it's configured, and
its current real status. See `docs/FINN_DOCUMENT_COVERAGE.md` for the
per-company coverage results and `docs/FINN_PHASE_12B_REPORT.md` for the full
phase report.

## Priority ranking (per this phase's brief)
1. Official company investor-relations websites
2. Official company annual-report/results pages
3. Accessible official company-issued document repositories
4. Screener.in links where access is permitted
5. Other legitimate sources that link to the original company-issued document

## Adapter 1 — `ScreenerSourceAdapter` (tier 4, practical primary this phase)

**File**: `backend/app/services/document_discovery/screener_adapter.py`

- **How it works**: fetches `https://www.screener.in/company/{TICKER}/consolidated/`
  (falling back to `.../company/{TICKER}/` on 404), confirms the page's
  `<title>` fully contains every meaningful word of the company's registered
  name (full containment, not a loose ratio — see the module's own docstring
  for why a looser threshold was tried and rejected after it nearly confused
  TMPV with TMCV), then parses the page's "Annual reports" and "Concalls"
  sections for direct PDF links.
- **Why it's the practical primary source**: its URL scheme is purely
  ticker-based, so it generalizes to ANY ticker with zero per-company
  configuration — unlike the IR-website adapter, which needs a verified seed
  URL per company. Confirmed live and reachable from this environment
  (NSE/BSE's own sites return 403 here; screener.in returns 200).
- **Live status**: verified reachable with confirmed identity for **all 20
  portfolio companies** on 2026-11-15 (see coverage doc).
- **What it discovers**: `annual_report` (reporting_period = `FY{YY}`, derived
  directly from screener's own stated year, a documented convention not a
  guess) and `concall_transcript`/`investor_presentation` (reporting_period =
  screener's own concall-month label, e.g. `OCT2026` — deliberately NOT
  converted into a fiscal quarter, since that would require guessing a
  company's exact reporting lag; the document's real fiscal period is
  resolved from its own content once ingested, by the existing
  period-resolution pipeline, independent of this label).
- **What it does NOT discover**: audio/video concall recordings (skipped —
  not a document type FINN ingests), and anything behind screener's own
  paid/registration-gated features (not used).

## Adapter 2 — `IRWebsiteSourceAdapter` (tier 1, built but seed-data-limited)

**File**: `backend/app/services/document_discovery/ir_website_adapter.py`
**Seed data**: `backend/app/core/investor_relations_seeds.py`

- **How it works**: given a company's own, verified `investor_relations_url`
  (pure DATA, not logic — same category as `app.core.companies`' ticker/
  yfinance_symbol seeds), fetches that page, confirms identity the same way
  the screener adapter does, then collects same-domain PDF links classified
  by keyword (annual report / concall transcript / investor presentation /
  financial results).
- **Why it's not the practical primary source yet**: every company's IR site
  has its own layout and bot posture; discovering and verifying 20 real
  sites reliably within this phase would mean guessing at 19 of them, which
  the phase's own instruction ("prioritise reliable automatic coverage over
  pretending every source is accessible") says not to do.
- **Live status**: one seed URL verified today —
  `HDFCBANK` → `https://www.hdfcbank.com/personal/about-us/investor-relations`
  (HTTP 200, title/body confirms "HDFC Bank", directly exposes annual-report,
  quarterly-results, and earnings-presentation PDFs on the landing page).
- **To extend**: add a verified URL to `INVESTOR_RELATIONS_URLS` in
  `investor_relations_seeds.py` — no code change required. The adapter code
  itself contains zero per-company branching.

## Review queue and source health

- **`ReviewQueueRepository`** (`backend/app/repositories/document_review_queue.py`):
  holds any candidate whose source identity wasn't confirmed, or whose
  doc_type/period was unrecognized. Nothing in this queue has ever been
  downloaded or ingested — approving an entry is a deliberate future step,
  not implemented by this phase (the admin endpoint
  `GET /api/admin/document-discovery/review-queue` is read-only).
- **`DocumentSourceRepository`** (`backend/app/repositories/document_sources.py`):
  durable per-(ticker, source) checkpoint — last checked, last successful
  check, last discovered document, health (`healthy`/`degraded`/`blocked`/
  `unknown`), error message. A source that fails is marked `degraded`, never
  silently dropped; the last known good state is preserved.

## Storage status (read before assuming any of this is "live")

Both new tables (`document_sources`, `document_review_queue`) are proposed
in `migrations/011_document_discovery_tracking.sql` — **written, not
applied**, exactly like Phase 12A's migration 010. The JSON-fallback path is
what every automated test in this phase actually exercises. The one real,
live proof documented in the coverage report (TCS) used the live Supabase
`documents`/`document_chunks` tables directly (already real — migration 007
is confirmed applied there) without needing the new tables at all, since
that was a single manual verification, not a full scheduled run across all
20 companies.
