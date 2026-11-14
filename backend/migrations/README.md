# FINN database migrations

**Status: 001, 002, and 003 are applied to a live Supabase project. 004 is written and reviewed, not yet applied — see below.**

## Setup

1. Create a Supabase project at https://supabase.com (free tier is sufficient for the prototype).
2. In the project's SQL editor (or via `supabase db push` with the CLI), run `001_init.sql`, `002_seed_companies.sql`, `003_phase2_additions.sql`, then `004_phase2_schema_fixes.sql`, in that order.
3. Confirm the `vector` extension enabled successfully (`001_init.sql` requests it) — required for `document_chunks.embedding`.
4. Copy the project URL and service_role key into `backend/.env` (see `.env.example`):
   ```
   SUPABASE_URL=https://<project>.supabase.co
   SUPABASE_KEY=<service_role key>
   ```
   A service_role key is the right choice here, not anon: none of these tables have Row Level Security policies defined, so an anon key would be unrestricted anyway, and the backend is server-side only.
5. The backend's `get_settings().supabase_configured` becomes `true` once both are set, and `GET /api/health`'s `storage_backend` field reports `"supabase"` only after a real round-trip query against `companies` succeeds — never assumed from the env vars alone.

## Why migration 004 exists

001-003 modeled `announcements`, `financial_metrics`, and `alerts` with `company_id`/`user_id` uuid foreign keys, matching sound relational design. A live integration test against the real database (not assumed — see `docs/database-schema.md`) found that the application layer had been written against different field names/types in a few places:

- `company_ticker` (text) was used instead of `company_id` (uuid FK) in several queries/payloads.
- `alerts` had no `trade_date` column, and no database-level dedup index despite `AlertRepository.exists()` already enforcing one in Python.
- `financial_metrics.id` and `alerts.id` were being built as human-readable composite strings instead of real UUIDs.
- `users.id` (the FK target for `alerts.user_id`/`alerts_config.user_id`) had no row and no way to create one idempotently.

The repository layer (`app/repositories/{announcements,financial_metrics,alerts}.py`) was corrected to translate ticker↔uuid and inject a real user id at the boundary — the ticker-based Pydantic models and API contracts above it are unchanged. Migration `004_phase2_schema_fixes.sql` makes the small set of additive schema changes that correction needed: a `trade_date` column, ownership-and-trigger-type-aware unique indexes on `alerts`, a check constraint enforcing which fields each alert trigger type requires, and a unique index on `users.email` so the single demo user row can be created idempotently. It never edits 001, 002, or 003, and does not drop or weaken any existing table, column, or constraint.

**To apply it:** open `004_phase2_schema_fixes.sql` in the Supabase SQL editor and run it. It's safe to run against the live project as-is — every statement is idempotent (`if not exists` / `on conflict do nothing`), and the tables it touches are currently empty (test-pollution cleanup pending, see `docs/database-schema.md`).

## What's wired up

As of this integration pass, `announcements`, `financial_metrics`, `alerts`, and `alerts_config` read and write the live Supabase tables when configured and reachable, falling back to the JSON-file store otherwise — see `docs/database-schema.md` for the verification evidence. `companies` and `market-data` endpoints still serve from the in-code registry (`app/core/companies.py`) and live yfinance calls respectively, not from the `companies`/`prices` tables — that remains unchanged from Phase 1.

## Embedding dimension

`document_chunks.embedding vector(1536)` assumes a 1536-dimension embedding model (e.g. OpenAI `text-embedding-3-small`). If a different model is chosen later, this column's dimension must be changed before any real embeddings are written — vectors of the wrong dimension will be rejected by pgvector.
