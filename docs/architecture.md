# FINN — Architecture (as built)

This supersedes the earlier "proposed, pending approval" version of this document.
Everything below describes what is actually implemented and verified, not a plan.
Where something was proposed but not built, it's marked **not implemented**.

## 1. System overview

```
┌──────────────────────────────┐        ┌──────────────────────────────┐
│   Push data (structured)     │        │  Pull data (unstructured)     │
│  announcements, financial_   │        │  annual reports, investor     │
│  metrics, prices             │        │  presentations, concall       │
│  (manual import — no live    │        │  transcripts (manual document │
│  NSE/BSE feed exists)        │        │  ingestion CLI, one at a time)│
└───────────────┬──────────────┘        └───────────────┬──────────────┘
                │                                        │
                ▼                                        ▼
   ┌─────────────────────────┐          ┌──────────────────────────────┐
   │ Push processing          │          │ Pull ingestion pipeline       │
   │ classify → priority →    │          │ extract (pdfplumber heuristic)│
   │ why-it-matters →         │          │ → classify chunk (prose /     │
   │ event grouping →         │          │   table_row_group /           │
   │ "what changed" (reuses   │          │   table_unparsed) → chunk     │
   │ compare_period)          │          │   (token-aware) → embed       │
   │ deterministic, no LLM    │          │   (local MiniLM, 384-dim)     │
   └───────────┬──────────────┘          └───────────────┬──────────────┘
               │                                         │
               ▼                                         ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │        Supabase / Postgres + pgvector  (or JSON-file fallback)   │
   │  companies, announcements, financial_metrics, alerts,            │
   │  documents (+ ingestion_status, file_sha256 — migration 007),    │
   │  document_chunks (+ chunk_type, needs_manual_review — 007),      │
   │  match_document_chunks() RPC (vector search — 006, restricted    │
   │  to completed documents — 008, both reviewed, NOT YET applied)   │
   └───────────┬─────────────────────────────────┬─────────────────── ┘
               │                                  │
               ▼                                  ▼
   ┌─────────────────────────┐        ┌──────────────────────────────┐
   │ GET /api/digest          │        │ Hybrid retrieval              │
   │ GET /api/events           │        │ vector RPC (top 20, hard cap) │
   │ GET /api/alerts           │        │ + lexical REST search (plain  │
   │ (FastAPI)                 │        │ ILIKE, company+completed-doc  │
   │                           │        │ scoped) + intent-aware rerank │
   │                           │        │ → GET /api/research/ask       │
   └───────────┬──────────────┘        └───────────────┬────────────── ┘
               │                                        │
               └───────────────┬────────────────────────┘
                               ▼
                 ┌─────────────────────────────┐
                 │ Next.js frontend (mobile-first)│
                 │ Push: event cards + digest     │
                 │ Pull: cited answers + evidence │
                 │ "Research this event" links    │
                 │ Push directly into Pull        │
                 └─────────────────────────────── ┘
```

## 2. Components and responsibilities

### Frontend (`frontend/`)
Next.js 16 App Router, TypeScript, Tailwind CSS. Server components fetch
`searchParams` for deep-linking (`/research?ticker=&question=`); client
components (`EventsFeed`, `DigestFeed`, `ResearchAskForm`) own their own
fetch/loading/error state. No charting library — financial comparisons render
as plain labeled rows with directional color, not decorative charts.

### FastAPI backend (`backend/app/`)
- `api/` — one router per resource (`digest`, `events`, `alerts`, `research`,
  `financials`, `announcements`, `companies`, `market_data`, `health`). Each
  endpoint is a thin wrapper; all logic lives in `services/`.
- `repositories/` — Supabase-or-JSON-fallback persistence. Every repository
  checks `storage_backend_name()` (configured AND a real connection verified,
  never assumed) and branches explicitly; callers above this layer never know
  which backend is active.
- `services/` — the actual logic, organized by concern (see below).

### Push services
- `classification.py` — rule-based keyword classification (17 categories, free,
  deterministic); an *optional* Anthropic call only for genuinely ambiguous
  titles, gated on `ANTHROPIC_API_KEY` being set.
- `priority.py` — `category_weight × recency_decay`, a fixed inspectable table,
  never an opaque score.
- `why_it_matters.py` — template-based explanation per category; extended (not
  replaced) by `event_intelligence.py` with a numbers-grounded "what changed"
  sentence when real `financial_metrics` exist for that period.
- `event_grouping.py` — groups announcements into one Event only when company,
  category-family (results + earnings-call), AND resolved reporting period all
  agree. No migration — purely derived from existing data at read time.
- `event_intelligence.py` — "what changed" financial comparison, built entirely
  on the existing, already-tested `financial_extraction.compare_period` — no
  duplicate math.
- `digest.py` / `alert_evaluation.py` / `anomaly.py` — unchanged from earlier
  phases; still the source of truth for the flat (non-grouped) view and for
  threshold-triggered alerts.

### Pull services (RAG pipeline)
- `pdf_extraction.py` — a custom text-pattern heuristic (not `pdfplumber.
  extract_tables()`, which failed on this document's colour-fill row banding,
  not vector rulings). Classifies each page into `prose`, confident
  `table_row_group`, or `table_unparsed` (ambiguous — raw text preserved, never
  force-structured).
- `chunking.py` — token-aware (real tokenizer, not an approximation), soft
  target 180-220 tokens, hard limit 256 (MiniLM's `max_seq_length`). A chunk
  never spans two pages; a table chunk always repeats its full header.
- `embeddings/local_minilm.py` — `sentence-transformers/all-MiniLM-L6-v2`,
  pinned to an exact HF commit SHA, run entirely on-device. No key, no
  per-call cost, persistent on-disk cache.
- `ingestion.py` — the full pipeline (validate → hash → dedup → claim → extract
  → chunk → embed → persist → complete), with explicit failure cleanup and a
  guard against marking a document "completed" after an error if the write
  actually already succeeded (a real race discovered and fixed this session).
- `query_intent.py` — rule-based classification into 7 intents (numerical,
  trend/comparison, guidance, strategy, risk, segment KPI, peer comparison).
- `metric_aliases.py` / `period_resolution.py` — generic (not ticker-specific)
  financial-term synonym table and fiscal-quarter resolution ("June 2026" →
  "Q1FY27"), shared by both ingestion-time and query-time logic.
- `hybrid_retrieval.py` — the actual fix for the reported retrieval failure.
  Combines the vector RPC's top-20 candidates with an independent lexical
  search (plain REST `ILIKE`, company + completed-document scoped, no new SQL
  function) over the same tables, then re-ranks with a hard priority tier for
  NUMERICAL-intent questions (structured table evidence always outranks prose,
  not just a score nudge).
- `numeric_answer.py` — deterministic (non-LLM) extraction of one cited figure
  from a `table_row_group` chunk, binding the asked-for period to the right
  column via a generic regex over the header — never guesses when ambiguous.

### Database (Supabase/Postgres + pgvector)
`companies`, `announcements`, `financial_metrics`, `alerts`, `documents`,
`document_chunks` — see `docs/database-schema.md`. Migrations 001-006 are
written and (per the project history) applied to the configured live project;
**007 and 008 are written, reviewed line-by-line twice, and still not applied**
— see `docs/migration-runbook.md`.

## 3. Data flow: a Pull question end to end

1. `GET /api/research/ask?ticker=HDFCBANK&question=...`
2. `classify_query_intent()` — rule-based, e.g. `{numerical_financial}`.
3. `retrieve_hybrid_evidence()`:
   a. Calls the existing `match_document_chunks` RPC for up to 20 vector
      candidates (company-filtered, completed-documents-only, cosine distance).
   b. Independently calls `search_chunks_by_keywords()` — a plain REST read
      over `document_chunks`, filtered to this company's completed documents,
      matching metric-alias terms.
   c. Merges by chunk id, scores each (vector similarity, lexical match,
      intent-aware chunk-type tiering, manual-review penalty), returns the
      top-k with a transparent `matched_via`/`relevance_score` breakdown.
4. If the intent is NUMERICAL: `extract_numeric_answer()` looks for a
   `table_row_group` chunk (never `table_unparsed`, never `needs_manual_review`)
   whose row label matches the asked metric and whose header's period columns
   bind unambiguously to the asked period. Returns the exact figure + citation,
   or `None` if not confidently bindable.
5. Response: `numeric_fact` (cited figure) / `evidence_digest` (ranked chunks,
   no LLM synthesis) / `insufficient_evidence` (explicit reason) — always with
   a `generation_note` stating plainly that no LLM is configured.

## 4. Security and data-isolation approach

- **Company isolation**: enforced independently at every layer — the vector
  RPC's own `WHERE` clause, the lexical search's own `company_id` +
  `ingestion_status='completed'` filter, and the repository layer never trusts
  a caller-supplied company_id without resolving it from the ticker first.
- **`SECURITY INVOKER`, empty `search_path`**: both `match_document_chunks`
  versions (006 live, 008 reviewed) run with the caller's own privileges, not
  elevated, and every identifier is schema-qualified so nothing resolves
  unexpectedly via a mutable search path.
- **Grants**: `REVOKE ALL` from `public`/`anon`/`authenticated`, `GRANT EXECUTE`
  only to `service_role` — the only role this backend's credentials use.
- **No credentials in code or logs**: `backend/.env` is git-ignored; errors are
  caught and returned as a generic message (`unhandled_exception_handler`),
  never a raw stack trace or exception string to the client.
- **No live writes without explicit action**: every GET endpoint in this
  codebase, including `/api/research/ask`, is read-only by construction —
  verified by code inspection, not assumed.

## 5. Important technical decisions

See [`docs/technical-decisions.md`](technical-decisions.md) for the full
rationale behind each of these; summarized here:
- Deterministic rules for Push priority/classification, not an LLM, for cost
  and auditability.
- Hybrid retrieval, not vector-only, because vector similarity alone
  demonstrably failed on structured table content.
- Local MiniLM embeddings, not a paid API, by explicit cost-efficiency
  requirement.
- Reliable, cited evidence preferred over unsupported generated prose — no
  answer-generation model is configured, and the product is honest about that
  rather than faking a chatbot.
- Original source URLs, page references, and reporting periods are preserved
  at every layer, never summarized away.

## 6. What was deliberately not built this phase

Event-centric Push and hybrid Pull retrieval were the explicit priorities.
Guidance-vs-actual tracking, narrative-change tracking, bull/bear cases,
theme-based watchlists, and a full research-template UI are **not
implemented** — most are blocked by having only one real document (no
transcripts, no multi-quarter history) rather than by missing code.
