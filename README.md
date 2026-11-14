# FINN — Evidence-First Financial Investment Agent

Built for the ENAM AI Engineer Build Challenge. FINN connects a company's own
disclosures, management commentary, and actual financial performance to explain
**what changed, why it matters, and what to investigate next** — never from
outside sources, never from a model's own pretraining knowledge of the company.

Two connected modes:

- **Push** — "Something changed. Should I care?" Related disclosures (results +
  investor presentation + concall transcript for the same quarter) are grouped
  into one event, enriched with a deterministic financial comparison ("what
  changed" vs. the previous quarter / same quarter last year), and explained with
  a transparent, non-opaque priority rationale.
- **Pull** — "Help me understand this company." Ask a question; FINN classifies
  its intent, retrieves evidence with **hybrid vector + lexical search** over the
  company's own primary documents (never news, broker notes, or model knowledge),
  and either extracts an exact cited figure or returns the ranked evidence itself
  — honestly labeled as retrieval, not AI-generated analysis (**no answer-
  generation LLM is configured in this build** — see Known limitations).

Every Push event carries a **"Research this event"** link that opens Pull
pre-filled with a relevant question — the two modes share one company/document
model, not two disconnected products.

Full requirements, design rationale, and verification history live in
[`docs/`](docs/). This README covers what's actually built and how to run it.

## What's actually built (verified this session)

| Area | Status |
|---|---|
| Push: announcement import, classification, priority, why-it-matters, alerts, digest | ✅ Built, tested |
| Push: event grouping (related disclosures → one event, never force-merged) | ✅ Built, tested |
| Push: "What changed?" financial comparison (QoQ/YoY, reused `compare_period`) | ✅ Built, tested |
| Push: alert transparency (primary-disclosure flag, evidence completeness, no opaque score) | ✅ Built, tested |
| Pull: document ingestion (PDF extraction, token-aware chunking, embedding) | ✅ Built, tested against a genuine document |
| Pull: query-intent classification (7 intents) | ✅ Built, tested |
| Pull: hybrid (vector + lexical) retrieval | ✅ Built, tested — fixed a real retrieval failure (see below) |
| Pull: deterministic numeric-value extraction with citation | ✅ Built, tested |
| Pull: `/api/research/ask` + Research page | ✅ Built, tested, manually verified in a browser |
| Push → Pull navigation ("Research this event") | ✅ Built, verified end-to-end with screenshots |
| Supabase persistence | ✅ Code path implemented, repository-tested; **live migrations 007/008 not yet applied** |
| JSON-fallback persistence | ✅ Working now, used for all local verification |
| Pull answer-generation (LLM synthesis) | ❌ Not implemented — no LLM is configured for Pull; see Known limitations |
| Live NSE/BSE automated ingestion | ❌ Not implemented — confirmed non-viable via direct automated access (`docs/filing-access-spike.md`) |
| Guidance-vs-actual / narrative-change tracking | ❌ Not implemented — would need transcript documents that don't exist yet in this build |

**The headline retrieval result**: for "What was HDFC Bank's net interest income
in Q1 FY27?" against the genuine HDFC Q1 FY27 earnings presentation, the correct
table ranked **26th of 203 chunks** by vector similarity alone. Hybrid retrieval
(vector + lexical + intent-aware re-ranking) now ranks it **1st**, and the system
returns the exact cited figure (335.3, page 4) rather than an irrelevant prose
snippet.

## Architecture

```
frontend/   Next.js 16 (App Router) + TypeScript + Tailwind CSS
backend/    Python + FastAPI, Pydantic schemas
            services/   classification, priority, why_it_matters, digest,
                        alert_evaluation, financial_extraction, anomaly,
                        pdf_extraction, chunking, ingestion, embeddings,
                        hybrid_retrieval, query_intent, metric_aliases,
                        period_resolution, numeric_answer,
                        event_grouping, event_intelligence, research_prompts
            repositories/  Supabase-or-JSON-fallback persistence
            migrations/    001-006 applied live; 007-008 written, reviewed,
                           NOT YET applied (see docs/migration-runbook.md)
docs/       requirements, architecture, technical decisions, demo script,
            submission checklist, migration runbook, access-verification spikes
scripts/    manual import CLI, document ingestion CLI, recovery script,
            access-verification spike scripts and raw evidence
```

Full system design: [`docs/architecture.md`](docs/architecture.md). Why each
major decision was made: [`docs/technical-decisions.md`](docs/technical-decisions.md).
Database design: [`docs/database-schema.md`](docs/database-schema.md).

## Setup

Tested on Python 3.14.7, Node.js 24.18.0, npm. Python 3.11+ / Node 18+ should
also work but have not been verified in this environment.

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # edit values as needed — see "Environment variables" below
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Health check: `curl http://127.0.0.1:8000/api/health` — reports `storage_backend`
(`"json_fallback"` or `"supabase"`) and `llm_configured` honestly, never assumed.

First request that touches embeddings (ingestion, or any `/api/research/ask`
call once a document exists) downloads `sentence-transformers/all-MiniLM-L6-v2`
(~90MB) from Hugging Face and caches it locally — no API key required, one-time
download.

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # edit NEXT_PUBLIC_API_BASE_URL if needed
npm run dev
```

Open `http://localhost:3000` — mobile-first, verified at phone width.

### Environment variables

Names and purpose only — never commit real values. See `backend/.env.example`
and `frontend/.env.local.example` for the placeholder files.

**Backend** (`backend/.env`):

| Variable | Purpose | Required? |
|---|---|---|
| `SUPABASE_URL` | Supabase project URL | No — JSON fallback used if blank/unreachable |
| `SUPABASE_KEY` | Supabase service-role key | No — same as above |
| `ANTHROPIC_API_KEY` | Enables LLM-assisted classification for *ambiguous Push filing titles only* — never used for Pull synthesis | No — rule-based classification covers all categories without it |
| `APP_NAME`, `ENVIRONMENT`, `LOG_LEVEL` | App metadata / logging | No — sensible defaults |
| `DATA_DIR` | Where the JSON-fallback store writes | No — defaults to `data` |
| `EMBEDDING_PROVIDER` | Embedding backend selector | No — `local_minilm`, no key needed |
| `CORS_ALLOW_ORIGINS` | Allowed frontend origins | No — defaults to `localhost:3000` |
| `MARKET_DATA_EOD_WINDOW_DAYS`, `CLASSIFICATION_LLM_CONFIDENCE_THRESHOLD`, `DEFAULT_VOLUME_SPIKE_MULTIPLE`, `DEFAULT_PRICE_MOVE_PCT`, `DEFAULT_DIGEST_WINDOW_HOURS` | Tunable defaults | No |

**Frontend** (`frontend/.env.local`):

| Variable | Purpose | Required? |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Base URL the frontend calls | No — defaults to `http://127.0.0.1:8000/api` |

### Running tests

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```
345 tests passing at last verification — real PDF extraction/chunking tests (genuine
HDFC document), real local-model tokenizer tests, hybrid-retrieval acceptance
tests, mocked repository/service tests, and structural SQL tests for the
unapplied migrations. No test touches live Supabase.

```bash
cd frontend
npx tsc --noEmit    # type check
npm run lint        # eslint
npm run build       # production build
```

### Seeding local demo data

The data store ships empty — nothing is fabricated. To see Push working locally:

```bash
curl -X POST http://127.0.0.1:8000/api/announcements/import -H "Content-Type: application/json" -d '{
  "ticker": "HDFCBANK", "title": "Unaudited Financial Results for the quarter ended June 30, 2026",
  "filed_at": "2026-07-18T10:00:00Z", "original_source_url": "https://example.invalid/results.pdf"
}'
```
See [`docs/demo-script.md`](docs/demo-script.md) for the full reproducible walkthrough,
including a real local document ingestion for Pull.

## Known limitations (stated plainly, not hidden)

- **No Pull answer-generation LLM is configured.** The only LLM call anywhere in
  this codebase is an *optional*, gated Anthropic call used solely for
  classifying ambiguous Push filing titles — never for Pull synthesis. Every
  `/api/research/ask` response says so explicitly in its `generation_note` field.
- **Only one genuine company document has been validated end-to-end** (HDFC Bank
  Q1 FY27 earnings presentation, 36 pages, locally ingested). The pipeline is
  designed to generalize to any NSE ticker/document, but only this one has real
  verification.
- **Management guidance and narrative-change tracking are not implemented** —
  they would require earnings-call transcripts with forward-looking statements,
  which don't exist in this build. Nothing is fabricated to simulate them.
- **Automated NSE/BSE ingestion is not implemented** — confirmed non-viable via
  direct automated access (`docs/filing-access-spike.md`); manual import is the
  implemented path.
- **Migrations 007 and 008 remain unapplied** against any live Supabase project —
  see [`docs/migration-runbook.md`](docs/migration-runbook.md) before applying them.
- **Live Supabase ingestion has not been performed** — all verification this
  session used an isolated local JSON-fallback instance with Supabase
  credentials deliberately unset for that process only.

## Manual actions required from you

1. If you want live Push/Pull data: apply migrations 007 and 008 (runbook above),
   then run the ingestion CLI against one real document, then verify before
   ingesting more.
2. If you want LLM-assisted Push classification: set `ANTHROPIC_API_KEY`.
3. If you want to deploy: see [`docs/submission-checklist.md`](docs/submission-checklist.md)
   for the deployment-readiness audit — nothing has been deployed or made public
   as part of this work.
