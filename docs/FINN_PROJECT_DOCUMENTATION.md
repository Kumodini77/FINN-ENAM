# FINN — Financial Investment Agent

*ENAM AI Engineer Build Challenge — Project Documentation*

## Product vision and what we built

Indian retail investors tracking even a modest portfolio face a flood of
information: quarterly results, exchange filings, management commentary,
and daily price action, spread across exchange websites, company investor
pages, and news aggregators. Most of it is routine. A small fraction of it
actually deserves attention. FINN's job is to do that filtering — to watch
a portfolio, process the primary documents a company actually issues, and
surface what matters, while still letting an investor ask a direct
question and get an answer grounded in the company's own filings rather
than a general-purpose AI's background knowledge.

FINN has two complementary workflows.

**Push — Proactive Intelligence.** FINN monitors the portfolio's
announcements, filings and EOD market data, classifies what it finds into
material categories (results, M&A, management change, litigation, and
twelve others), scores priority, and presents it as a daily intelligence
feed — sectioned by what needs attention versus what's routine — plus
configurable EOD price/volume alerts.

**Pull — On-demand Research.** A user asks a question about a specific
company and gets an answer extracted from that company's own ingested
annual reports, concall transcripts and investor presentations, with the
exact source document, page, and passage attached. No broker notes, no
news commentary, and — in this build — no general LLM reasoning feed into
a Pull answer; retrieval and numeric extraction are deterministic.

The guiding product decision throughout was to reduce manual research
effort without pretending to replace judgment: FINN tells an investor what
changed and where the evidence is, not what to do about it.

### Companies covered

**Portfolio (20, Push-monitored):** HDFCBANK, ICICIBANK, SBIN, BAJFINANCE,
TCS, INFY, WIPRO, RELIANCE, TMPV, M&M, SUNPHARMA, CIPLA, HINDUNILVR, ITC,
BHARTIARTL, TATASTEEL, LT, POWERGRID, TRENT, LICI.

**Ad-hoc research (5, Pull-only):** ETERNAL, ADANIPORTS, COALINDIA, DIXON,
DRREDDY.

The portfolio spans banking (HDFCBANK, ICICIBANK, SBIN), NBFC (BAJFINANCE),
IT services (TCS, INFY, WIPRO), energy (RELIANCE), automobiles (TMPV, M&M),
pharmaceuticals (SUNPHARMA, CIPLA), FMCG (HINDUNILVR, ITC), telecom
(BHARTIARTL), metals (TATASTEEL), infrastructure (LT), utilities
(POWERGRID), retail (TRENT) and insurance (LICI) — thirteen sectors across
twenty names, chosen for variety of business model and reporting style
(bank disclosures look nothing like an IT services investor deck), not
through a documented quantitative screen. The five ad-hoc companies are
intentionally outside the monitored portfolio: they exist to prove that
Pull's research engine works for any valid NSE ticker, not just the twenty
names FINN happens to track — the same retrieval and extraction code path
handles both.

---

## How FINN works and what makes it different

### Architecture

**Frontend** (Next.js, mobile-first): four destinations — Daily
Intelligence, Portfolio, Research, Alerts — with a bottom tab bar on
mobile and a sidebar on desktop. Portfolio groups the twenty companies by
sector with a live search field and small EOD-based trend sparklines;
Research presents an evidence-first answer with supporting documents
collapsed below it; a light/dark theme (persisted, no flash on load) runs
across every screen.

**Backend** (FastAPI): a company registry with generalizable ticker
resolution (any NSE ticker verifies against yfinance, not just the
seeded twenty-five), a portfolio repository, document discovery and PDF
ingestion services, financial extraction and hybrid retrieval, and the
Push/Pull API surfaces that sit on top of them.

**Data flow:**

```
 Screener.in / company IR sites   yfinance (EOD)
          │                           │
   discovery + identity check   price/volume fetch
          │                           │
          ▼                           ▼
  PDF download → validate → extract → chunk → embed → store
          │                           │
          └──────────► Supabase (documents, chunks, announcements, prices) ◄──┘
                               │                        │
                             Push                      Pull
                     (classify, prioritise,     (hybrid retrieval, numeric
                      digest, alerts)            extraction, cited evidence)
                               │                        │
                               └────────► Investor ◄────┘
```

### Data sources

- **yfinance** supplies end-of-day price and volume — explicitly EOD, never
  real-time; a still-in-progress session's bar is labelled
  `provisional_intraday` and excluded from averages rather than treated as
  a finished day.
- **`ScreenerSourceAdapter`** discovers annual reports, concall transcripts
  and investor presentations via screener.in's per-company pages — verified
  live, reachable for all 20 portfolio companies, with every link pointing
  at the real exchange- or company-hosted PDF, not at screener itself.
- **`IRWebsiteSourceAdapter`** crawls a company's own investor-relations
  page directly; currently verified for one company (HDFCBANK) — it is a
  real, reusable adapter, just not yet configured with verified seed URLs
  for the rest of the portfolio.
- Direct NSE/BSE announcement access was tested and found blocked (301/403
  responses) — not bypassed.
- **Supabase** (Postgres + pgvector) is the persistent store for companies,
  documents, chunks, announcements, prices and job runs, with a JSON-file
  fallback used throughout local testing.

### Engineering features worth highlighting

- **Position-aware PDF table extraction.** Indian results decks often split
  a table's header across multiple lines (a "Quarter ended" phrase row, a
  date row, a year row) that plain text extraction cannot safely reassemble.
  FINN falls back to word-coordinate (bounding-box) reconstruction only when
  the text-only pass can't confidently resolve a header — and refuses to
  fabricate a figure when even that fails, rather than guessing.
- **Cross-company evidence isolation**, checked by a dedicated test suite:
  every evidence chunk returned for a question about one company is
  verified to actually belong to that company.
- **Content-hash and metadata deduplication** for every ingested document,
  so the same filing discovered twice (e.g. mirrored on both BSE and a
  company's own domain) is never processed or stored twice.
- **A reusable, durable job-execution foundation** (retry with backoff,
  timeout, duplicate-run prevention, crash recovery) shared by all three
  scheduled jobs — EOD market-data refresh, document discovery, and
  announcement discovery — rather than three separate ad hoc schedulers.
- **Automatic document and announcement discovery**, verified live: one
  concall transcript was discovered, downloaded and made searchable for
  TCS end-to-end, and 94 real announcements were discovered and classified
  across all 20 portfolio companies in a single run.
- **Evidence-linked research.** Every Pull answer — a single extracted
  number or a digest of passages — carries its source document, page, and
  a direct link back to the original filing.
- **Explainable prioritisation.** Push priority is a deterministic function
  of announcement category and recency, not an opaque score; each item
  states why it was ranked the way it was.

---

## Decisions, challenges, limitations and future direction

### Key decisions

- **EOD data via yfinance, not a paid real-time feed** — keeps the project
  free to run, and real-time price action was never the point of a
  research-and-briefing tool.
- **Primary documents only for Pull** — no broker notes, no news, no base
  LLM knowledge feeding a Pull answer, so every figure traces to a filing.
- **Deterministic calculation wherever possible** — numeric facts are
  extracted by pattern-matching real table structure, not generated by a
  model; an LLM (when configured) is reserved for cheaper classification
  work, not for inventing financial conclusions.
- **Reuse over rewrite** — three separate automation jobs (market data,
  documents, announcements) share one job-execution framework; Push and
  Pull share one retrieval/evidence-chunk model.
- **Portfolio Push and ad-hoc Pull are kept structurally separate** — an
  ad-hoc research company is never silently added to the monitored
  portfolio.
- **Ingestion is incremental and non-destructive** — existing documents and
  chunks are never deleted or reprocessed by a later discovery run; a
  duplicate is detected and skipped, not overwritten.
- **Unavailable sources are reported, not hidden** — a blocked source or an
  empty result window says so explicitly rather than presenting a quiet,
  misleadingly empty screen.

### Challenges and how they were handled

- **Multi-line table headers and reversed quarter notation** (e.g. a
  company writing "2QFY27" instead of "Q2FY27") required generic, tested
  parsing rules rather than per-document hacks — handled in a dedicated
  period-resolution module reused everywhere a period label appears.
- **PAT vs. EBITDA vs. EBITDA margin ambiguity**: a bare question like
  "What was PAT?" can match more than one row in a table (reported vs.
  adjusted). Rather than guessing, FINN surfaces the competing row labels
  and asks the user to disambiguate.
- **The Tata Motors demerger** split one company into TMPV (passenger
  vehicles) and TMCV (commercial vehicles) mid-project. The portfolio seed
  was updated to the correct successor (TMPV) without aliasing the old
  ticker, and the identity-matching logic used by document discovery was
  specifically hardened after a test caught it almost treating "Tata Motors
  Passenger Vehicles" and a hypothetical "Tata Motors Commercial Vehicles"
  as the same company under a looser matching rule.
- **Blocked exchange sources**: NSE and BSE's own announcement pages and
  APIs return 301/403 in this environment. Rather than attempting to
  bypass that, discovery was built around screener.in, which indexes the
  same filings and was verified reachable for the full portfolio.
- **Background job reliability**: a crashed or killed worker could
  otherwise leave a job permanently "running," blocking all future runs.
  Jobs record a heartbeat and are automatically reclaimed as failed if
  that heartbeat goes stale, so a new run is never stuck waiting forever.
- **Free data-provider limits**: yfinance has no official support contract
  and occasionally returns partial or malformed data; FINN validates every
  returned bar before storing it rather than persisting a bad value.

### Current functionality

| Area | Status |
|---|---|
| Portfolio & market data | Implemented and tested. Live EOD quotes and 30-day trend sparklines for all 20 companies; sector grouping and search. |
| Daily Intelligence & Alerts | Implemented and tested. Priority-sectioned feed (needs attention / positive / market pulse / other), EOD volume & price alerts with real trigger detail, duplicate-alert prevention. |
| Document discovery & processing | Implemented and tested for the discovery/classification path; **13 of 20** portfolio companies currently have at least one ingested document (14 documents total) — the other 7 are confirmed discoverable but not yet backfilled. |
| Pull research | Implemented and tested. Deterministic numeric extraction plus cited evidence digests; generalizes to any valid NSE ticker. |
| Automation & reliability | Implemented and tested against a local store; the live Supabase job-tracking tables require one pending database migration before scheduled runs can track state there. |
| User interface | Implemented: mobile-first navigation, light/dark theme, responsive Portfolio/Research/Alerts layouts. |

**122 announcements** and **14 documents** are live in the working
database today; **531 automated tests** pass in the current backend test
suite.

### Deliberately excluded or deferred

- **Real-time market data** — a paid feed was never introduced; everything
  is explicitly EOD.
- **Unauthorised exchange scraping** — NSE/BSE access was found blocked and
  was not bypassed.
- **Fully automatic, unreviewed document ingestion** — a discovery
  candidate whose source identity can't be confirmed is sent to a review
  queue rather than ingested automatically.
- **Complete document coverage of every company** — accurately reported as
  13/20 rather than implied as complete.
- **A full management-guidance-vs-actual comparison feature** and a
  dedicated company-timeline view were scoped but not built — real
  features correctly left for a later phase rather than shipped half-done.
- **Public deployment** — FINN runs locally against a live Supabase
  project; it has not been deployed to a public host as part of this
  submission.

### Where FINN goes next

The most valuable next steps are: completing automatic announcement
monitoring for the remaining uningested sources, comparing management's
own stated guidance against later actual results (an explicitly flagged
priority that needs a new, careful extraction step rather than a quick
addition), deepening the evidence-backed Research experience, simplifying
the mobile flow further, and finally standing up a real, scheduled,
publicly reachable deployment rather than a locally-run one. None of these
are presented here as already done.
