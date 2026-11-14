# FINN — Migration & Live-Ingestion Runbook

Read fresh from `backend/migrations/006_vector_similarity_search_rpc.sql`,
`007_document_ingestion_tracking.sql`, and `008_retrieval_completed_documents_only.sql`
on disk for this document. Nothing in this runbook has been executed. No SQL
was run, no Supabase connection for writes was made, no document was ingested
live, and no data was deleted, while preparing this.

## 1. Is migration 006 reflected in the intended current schema?

Per the project's own history, 006 (`match_document_chunks`, 4-column citation
shape, no `chunk_type`) is the version believed to be live today. This runbook
does **not** verify that against the actual database — that would require a
live read, which is out of scope for this task per your explicit instruction.
The preflight query in §4 is how you (or a future session, if asked) would
confirm it live, read-only.

## 2. Exact dependencies

- **007 depends on**: 001_init.sql's `documents`/`document_chunks` tables
  existing (already live, per project history). No dependency on 006.
- **008 depends on**: 007 having been applied (`documents.ingestion_status`,
  `document_chunks.chunk_type`, `document_chunks.needs_manual_review` must all
  exist — 008's own leading `DO` block checks this via `pg_attribute` and
  raises a clear exception naming the exact missing column if not, *before*
  dropping anything). 008 also depends on 006 having been applied first (it
  `DROP FUNCTION`s the exact 3-argument signature 006 created).

## 3. Migration order

**006 → 007 → 008**, strictly in that order. 007 and 008 cannot be
reordered or combined — 008's own precondition guard will abort cleanly
(rolling back its whole transaction, touching nothing) if run before 007.

## 4. Required preflight checks (read-only — safe to run anytime)

Run this in the Supabase SQL Editor *before* applying 007/008, to confirm the
starting state matches what both migrations assume:

```sql
-- 1. Confirm match_document_chunks exists with the expected 006 signature, and note its owner.
select
    p.oid, pg_get_function_identity_arguments(p.oid) as identity_arguments,
    pg_get_function_result(p.oid) as result_type, r.rolname as owner,
    p.prosecdef as is_security_definer, p.proconfig as config_settings
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
join pg_roles r on r.oid = p.proowner
where n.nspname = 'public' and p.proname = 'match_document_chunks';

-- 2. Confirm current grants on it.
select grantee, privilege_type from information_schema.role_routine_grants
where routine_schema = 'public' and routine_name = 'match_document_chunks';

-- 3. Confirm nothing else depends on it (DROP FUNCTION, no CASCADE, should succeed cleanly).
select classid::regclass as dependent_object_type, objid, deptype
from pg_depend
where refobjid = (select oid from pg_proc where proname = 'match_document_chunks' and pronamespace = 'public'::regnamespace)
  and deptype not in ('i');

-- 4. Confirm the prerequisite tables/columns 007 will touch exist with the expected shape.
select table_name, column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public' and table_name in ('documents', 'document_chunks')
order by table_name, column_name;

-- 5. Confirm no pre-existing column/constraint name-collision with what 007 will add
--    (007 itself also checks this and will abort safely if one exists with the wrong shape).
select conname, conrelid::regclass as table_name, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid in ('public.documents'::regclass, 'public.document_chunks'::regclass)
order by table_name, conname;
```

## 5. Expected schema changes

**007** (additive only, no drops):
- `documents`: + `file_sha256 text`, `ingestion_status text not null default 'pending'`,
  `ingestion_error text`, `ingested_at timestamptz`, `ingestion_claimed_at timestamptz`.
- `documents_ingestion_status_check`: exactly `pending|extracting|chunking|embedding|completed|failed`.
- `idx_documents_file_sha256` (unique, partial), `idx_documents_ingestion_status`,
  `idx_documents_ingestion_claimed_at` (partial).
- `document_chunks`: + `embedding_model text`, `embedding_model_revision text`,
  `chunk_type text not null default 'prose'`, `needs_manual_review boolean not null default false`.
- Three new check constraints on `document_chunks`: embedding-provenance
  required-together, chunk_type in exactly 3 values, `table_unparsed` ⇒
  `needs_manual_review`.

**008** (behavior change, same table schema):
- `match_document_chunks` dropped and recreated with the same 3-argument
  signature, now returning 2 additional columns (`chunk_type`,
  `needs_manual_review`) inserted after `chunk_text`, and an added `WHERE
  d.ingestion_status = 'completed'` filter.
- No table is touched by 008 at all.

## 6. Expected function ownership and grants (after both migrations)

- **Owner**: 008 explicitly captures `match_document_chunks`'s owner *before*
  dropping it and restores the same owner on the new function via `ALTER
  FUNCTION ... OWNER TO`. If 006 was originally applied by role `postgres`
  (the typical Supabase SQL Editor role), the function should still be owned
  by `postgres` afterward — verify with preflight query 1 before, and the
  same query again after, and confirm they match.
- **Grants**: `REVOKE ALL` from `public`/`anon`/`authenticated`, `GRANT
  EXECUTE` only to `service_role` — identical to 006's grant state, since
  `DROP FUNCTION` removes prior grants and 008 explicitly reapplies them.
- **Security**: `SECURITY INVOKER`, `SET search_path = ''` — unchanged.

## 7. What success should look like

After applying 006 (if not already live) → 007 → 008, in order, with no errors:
1. Preflight query 1 shows `match_document_chunks` with identity arguments
   `public.vector(384), uuid, integer`, result type including `chunk_type
   text, needs_manual_review boolean` in the returned table, owner unchanged
   from before 008 ran.
2. `select ingestion_status from public.documents limit 1;` and `select
   chunk_type, needs_manual_review from public.document_chunks limit 1;`
   both succeed (columns exist) even with zero rows.
3. A test call like:
   ```sql
   select * from public.match_document_chunks(
       (select embedding from public.document_chunks limit 1),
       (select company_id from public.document_chunks limit 1),
       5
   );
   ```
   either returns rows (if any completed document's chunks exist) or an empty
   set (if none do) — not an error.
4. `GET {SUPABASE_URL}/rest/v1/` (PostgREST's own OpenAPI introspection) lists
   `match_document_chunks` with the new return shape, confirming
   `NOTIFY pgrst, 'reload schema'` took effect.

## 8. Recovery steps if an operation fails

- **007 fails partway** (e.g. one `DO` block raises): 007 is wrapped in an
  explicit `BEGIN`/`COMMIT`, so a raised exception inside any block rolls back
  the **entire** transaction — no partial column/constraint state is left
  behind. Fix whatever the error message named (it's an explicit, named
  mismatch — e.g. "documents.file_sha256 exists but does not match the
  expected type") and re-run the whole file; every statement in it is
  idempotent, so re-running after a clean rollback is safe.
- **008 fails at its precondition guard** (007 not actually applied, or a
  column missing): the guard runs *before* `DROP FUNCTION`, inside the same
  transaction, so a failure here leaves `match_document_chunks` completely
  untouched — apply 007 (or fix it) and re-run 008.
- **008 fails after `DROP FUNCTION` but before `CREATE FUNCTION`** (should not
  happen absent a Postgres-level fault, but if it does): the whole transaction
  rolls back together, including the `DROP` — `match_document_chunks` reverts
  to its pre-008 state. No manual cleanup needed; just re-run 008.
- **General**: never run `DROP FUNCTION ... CASCADE` or any destructive
  statement not already in these files to "fix" a failure — re-running the
  file as-is is the designed recovery path for both migrations.

## 9. Live ingestion — exact command, NOT to be run yet

Only after 007 and 008 have been applied **and** verified per §7 above:

```bash
cd backend
.venv/bin/python scripts/ingest_document.py \
  --pdf ../scripts/spikes/fundamentals_access_spike/documents/hdfcbank_earnings_presentation.pdf \
  --ticker HDFCBANK --doc-type investor_presentation --reporting-period Q1FY27 \
  --source-url "https://www.hdfc.bank.in/content/dam/hdfcbankpws/in/en/pdf/about-us/financial-results/2026-2027/quarter-1/q1fy27-earnings-presentation.pdf"
```

This requires `backend/.env` to have real `SUPABASE_URL`/`SUPABASE_KEY` set and
reachable (confirm first with `curl http://127.0.0.1:8000/api/health` showing
`"storage_backend": "supabase"`). Ingest **exactly one document**, then
manually inspect the resulting `documents`/`document_chunks` rows (and run a
real `/api/research/ask` call against it) before ingesting any second
document — per the project's own standing "thin-but-working" and no-bulk-
ingestion constraints.
