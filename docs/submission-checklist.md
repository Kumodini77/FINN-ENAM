# FINN — Submission Checklist

Verified items are marked ✅ with how they were verified. Recommended-but-not-
yet-done items are marked ⬜ with the exact action needed.

## Repository readiness

- ✅ Root `.gitignore` created, verified against a disposable test repo —
  `.env`/`.env.local` correctly ignored, `.env.example`/`.env.local.example`
  correctly tracked, `.venv/`, `node_modules/`, `.next/`, `backend/data/`
  (local JSON-fallback DB + embedding cache) all ignored.
- ✅ No secrets found in any tracked source file (scanned for JWT-like and
  `sk-`-prefixed token patterns; the one hit was a false positive — an
  `npm` integrity hash in `package-lock.json`, not a credential).
- ⬜ **No git repository exists yet at the project root** (`git status`
  returns "not a git repository"). This is a finding, not something fixed —
  initializing one is a repo-level action I did not take without your
  explicit instruction. See §I of the final report for the exact commands.
- ⬜ `scripts/spikes/fundamentals_access_spike/extracted/` (≈5MB, a derived/
  unzipped duplicate of the already-tracked `reliance_ar_2013.zip`) —
  recommend excluding from the initial commit as regenerable, not deleting it
  locally. Not added to `.gitignore` automatically since that's a judgment
  call on repo history, not a safety requirement — your decision.

## Security and environment safety

- ✅ `backend/.env` holds real `SUPABASE_URL`/`SUPABASE_KEY` locally and is
  git-ignored; `backend/.env.example` has placeholders only.
- ✅ `frontend/.env.local` / `.env.local.example` — same pattern, verified.
- ✅ Error responses never leak a stack trace or secret
  (`unhandled_exception_handler` always returns a fixed generic message).
- ✅ Every GET endpoint, including `/api/research/ask`, verified read-only by
  code inspection — no endpoint mutates data on a GET.
- ✅ Company isolation enforced independently at the vector RPC, the lexical
  search, and the repository layer (not trusted from a single source).

## Test status

- ✅ Backend: `345 passed` (`cd backend && .venv/bin/python -m pytest tests/ -q`).
- ✅ Frontend: `npx tsc --noEmit` clean, `npm run lint` clean, `npm run build`
  succeeds (6 routes).
- ✅ Genuine-document tests (real HDFC PDF, real local model) are a distinct,
  clearly separated subset — see `tests/conftest.py`'s shared fixture and
  `test_end_to_end_hdfc.py`/`test_hybrid_retrieval.py`.
- ✅ Zero tests touch live Supabase.

## Supabase migration status

- ⬜ Migrations 007 and 008 are written, reviewed line-by-line (twice), and
  **not yet applied** to any live Supabase project. See
  `docs/migration-runbook.md` for the exact order, preflight, and recovery
  steps before you apply them.
- Migration 006 is believed already live per project history; this was not
  re-verified live this session (explicitly out of scope per your instruction).

## Live ingestion status

- ⬜ **Zero documents have been ingested against live Supabase.** All
  verification this session used an isolated local backend process with
  Supabase credentials deliberately blanked for that process only (JSON
  fallback), confirmed via `/api/health` reporting `"storage_backend":
  "json_fallback"` before any write.
- The exact one-document live ingestion command is in
  `docs/migration-runbook.md` §9 — not run.

## Demo readiness

- ✅ `docs/demo-script.md` — a reproducible ≈4-5 minute walkthrough using only
  locally-seedable demo data, with exact seed commands included.
- ✅ Every step in it was actually driven through a browser (Playwright,
  headless) against a real locally-running instance in the prior session, with
  screenshots at desktop and mobile widths and zero console errors.

## Deployment readiness

See §F of the final report for the full audit and recommendation. Summary:
- ⬜ Not deployed anywhere. No external account created, no service made
  public, per your explicit instruction.
- The app does not yet separate "model cache directory" from ephemeral
  storage — on most serverless/ephemeral-filesystem hosts, the local MiniLM
  model and embedding cache would re-download on every cold start. Flagged as
  a deployment consideration, not fixed (would be a feature/infra change,
  out of scope for a documentation-and-readiness pass).

## Covering email readiness

- ✅ Draft prepared (final report §covering email) addressed to
  `assessment@enam.com`, subject `IIT Delhi – AI Engineer - 2027`. Not sent.
  Contains two placeholders you must fill in before sending: the GitHub repo
  URL and the deployed-demo URL (neither exists yet).
