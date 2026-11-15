# FINN Document Coverage Audit (Phase 12B)

Written 2026-11-15. All "existing documents" data below is a live read of the
production Supabase `documents` table (not derived from memory/earlier phase
notes). All "screener.in reachable / identity verified" columns are a live
check performed today via `ScreenerSourceAdapter.check()` against the real
screener.in site for every one of the 20 frozen portfolio companies — not
assumed. The five ad-hoc companies (ETERNAL, ADANIPORTS, COALINDIA, DIXON,
DRREDDY) are deliberately excluded from this table — they remain independent
Pull-only research targets and are never added to portfolio Push, so Phase
12B's scheduled discovery job never touches them (verified by a test —
`TestAdHocSeparation` in `tests/test_document_discovery_job.py`).

## Coverage table — all 20 portfolio companies

| Ticker | Existing documents (live DB) | Latest ingestion | screener.in reachable | Identity verified | Candidates found today |
|---|---|---|---|---|---|
| HDFCBANK | investor_presentation / Q1FY27 (completed) | see DB `ingested_at` | yes | yes | 61 |
| ICICIBANK | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 105 |
| SBIN | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 74 |
| BAJFINANCE | **none** | — | yes | yes | 98 |
| TCS | concall_transcript / OCT2026 (completed) — **ingested live during this phase, see §"Live end-to-end proof"** | 2026-11-15 (this phase) | yes | yes | 71 |
| INFY | **none** | — | yes | yes | 61 |
| WIPRO | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 66 |
| RELIANCE | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 78 |
| TMPV | **none** | — | yes | yes | 83 |
| M&M | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 157 |
| SUNPHARMA | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 62 |
| CIPLA | **none** | — | yes | yes | 118 |
| HINDUNILVR | **none** | — | yes | yes | 122 |
| ITC | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 51 |
| BHARTIARTL | **none** | — | yes | yes | 60 |
| TATASTEEL | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 98 |
| LT | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 116 |
| POWERGRID | **none** | — | yes | yes | 63 |
| TRENT | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 28 |
| LICI | investor_presentation / Q2FY27 (completed) | see DB | yes | yes | 55 |

**Headline finding: all 20/20 portfolio companies have an accessible,
identity-verified screener.in page today**, each exposing real annual-report
and concall-transcript/presentation links pointing at company- or
exchange-hosted PDFs (bseindia.com, or the company's own domain). This is a
materially better starting point than the earlier-phase finding that
NSE/BSE's own sites block automated access (`docs/filing-access-spike.md`) —
screener.in was always the sanctioned fallback (priority tier 4 in this
phase's own source ranking) and turns out, on live verification, to cover
100% of the portfolio, not just a subset.

**7 of 20 portfolio companies (BAJFINANCE, INFY, TMPV, CIPLA, HINDUNILVR,
BHARTIARTL, POWERGRID) currently have zero ingested documents** — not because
no source is reachable (screener.in is reachable and verified for every one
of them), but because no prior phase ever ran discovery/ingestion against
them. This is the real, honest coverage gap Phase 12B's job exists to close
incrementally (see `document_discovery_max_new_docs_per_company` — 6 per run
by default — so closing this gap for all 7 happens over a few scheduled runs,
not one unbounded backfill).

## Document types available per company, by type

Every company above exposes, via screener.in's own structure: **annual
reports** (going back over a decade in most cases) and **concall
transcripts + investor presentations** (quarterly, going back several
years). Standalone "quarterly/annual financial results" filings are not a
separate document type in FINN's schema (`app.models.document.DocType` has
only three values — `annual_report`, `concall_transcript`,
`investor_presentation`); by the established convention already used for
every existing ingested document, a results-only PDF is filed as
`investor_presentation`.

## Official investor-relations websites

Verified reachable (HTTP 200, page content confirms company identity) for:
- **HDFCBANK** → `https://www.hdfcbank.com/personal/about-us/investor-relations` (confirmed today; directly exposes annual-report, quarterly-results, and earnings-presentation PDFs on the landing page itself).

Not verified for the other 19 portfolio companies this phase — each has its
own URL structure and bot posture that would need individual confirmation
(see `app/core/investor_relations_seeds.py`'s own docstring: deliberately
incomplete, populated only with what's actually confirmed, not guessed).
This is exactly the "prioritise reliable automatic coverage over pretending
every source is accessible" instruction in practice: screener.in's uniform,
generalizable URL scheme makes it the practical primary source for this
phase; the official-IR-website adapter is built and real (see
`app/services/document_discovery/ir_website_adapter.py`) but only usable for
a company once its own IR URL is verified and added to that seed file — a
pure data addition, no code change, going forward.

## Source accessibility and restrictions

- **NSE/BSE direct access**: blocked (HTTP 403 observed live against
  nseindia.com during this phase — consistent with the prior
  `docs/filing-access-spike.md` finding). Not attempted to be bypassed.
- **screener.in**: reachable, no bot-protection encountered, no login
  required for the document links checked. The PDFs it links to are hosted
  on bseindia.com or each company's own domain — screener itself is just the
  index, never claimed as the primary source in any ingested document's
  `original_source_url` (that field always holds the real bseindia.com/
  company-domain URL screener pointed at, not a screener.in URL).

## Live end-to-end proof

To meet this phase's acceptance criterion ("at least one accessible official
source completes an end-to-end discovery-to-searchable-document workflow"),
one real discovery → download → ingest → Pull-retrieval run was performed
live against TCS (chosen because it had zero prior documents, so this
represents genuinely new coverage, not a duplicate):

1. `ScreenerSourceAdapter.check("TCS", "Tata Consultancy Services Ltd")` → 71
   real candidates, identity verified against the live page title.
2. Downloaded the most recent concall transcript
   (`bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=7dc14216-...pdf`, 723 KB,
   valid PDF).
3. Ran it through the **existing, unmodified** `ingest_document()` pipeline
   against the real Supabase project → document id
   `d2ad3364-39cc-422b-831c-18cb261b0f8c`, 74 chunks, `ingestion_status =
   completed`.
4. `check_research_readiness("TCS")` → `status = "ready"`, confirming this
   updated automatically with zero code changes (research-readiness has
   always derived its answer live from `DocumentRepository`).
5. `DocumentRepository.search_chunks_by_keywords()` against the new
   document's company_id → real matching chunks returned (e.g. discussion of
   TCV, AI revenue, segment growth), confirming the document is genuinely
   Pull-searchable, not just "stored."

This is a real, verified result, not a projection — see
`docs/FINN_PHASE_12B_REPORT.md` for the full write-up.
