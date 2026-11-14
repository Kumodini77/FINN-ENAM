-- PROPOSED — NOT YET APPLIED. For review only. Do not execute without approval.
--
-- FINN — additive ingestion-tracking columns for documents/document_chunks.
--
-- Does NOT modify or recreate migrations 001-006, does not drop any existing
-- column, does not touch existing rows. Purely additive: new nullable or
-- safely-defaulted columns, new partial indexes, and new check constraints.
--
-- REVISION (this version): wrapped the whole file in one explicit transaction, and
-- every ADD COLUMN / ADD CONSTRAINT is now followed by a verification check rather
-- than a bare "IF NOT EXISTS" skip - if a column or constraint of the expected name
-- ALREADY exists but with the WRONG type/nullability/definition, this migration
-- raises an exception (rolling back the whole transaction) instead of silently
-- treating it as "already done". Idempotency is preserved: re-running this file
-- after it already succeeded hits only the "already exists and matches" branch of
-- every check, so a clean re-run still completes with no changes and no error.
--
-- WHY THESE COLUMNS (gaps identified against the live schema + migrations
-- 001-006, documents/repositories, and app/services/embeddings/retrieval.py):
--   1. file_sha256 — the ONLY idempotency key proposed here is content-based.
--      documents' existing unique constraint is (company_id, doc_type,
--      reporting_period) (001_init.sql) - that catches "we already have a FY2025-26
--      annual report for this company" but NOT "this exact PDF file was already
--      ingested". A SHA-256 of the actual file bytes is what that requires. The
--      conflict-handling logic between this new key and the existing metadata key
--      is implemented in app/repositories/documents.py (not in SQL) - see the
--      ingestion architecture writeup for the four explicit cases.
--   2. ingestion_status / ingestion_error / ingested_at / ingestion_claimed_at —
--      nothing in 001-006 tracks per-document pipeline state. ingestion_claimed_at
--      supports an atomic claim (conditional UPDATE WHERE ingestion_status IN
--      ('pending','failed')) so two concurrent ingestion jobs can never both
--      process the same document, and lets a recovery procedure find documents
--      stuck mid-ingestion after a process crash (stale ingestion_claimed_at with a
--      non-terminal status).
--   3. document_chunks.embedding_model / embedding_model_revision — nothing
--      currently records which model produced a stored embedding. Both are
--      required together whenever embedding is non-null.
--   4. document_chunks.chunk_type / needs_manual_review — three states: 'prose',
--      'table_row_group' (confidently parsed into rows/columns, header repeated),
--      and 'table_unparsed' (looked table-like but could NOT be confidently
--      structured - raw extracted text preserved verbatim). needs_manual_review is
--      mandatory-true whenever chunk_type = 'table_unparsed' by a check constraint
--      below, so an ambiguous extraction can never be silently presented as
--      reliable structured financial data.

begin;

-- 1. documents: ingestion tracking columns -----------------------------------
alter table public.documents
    add column if not exists file_sha256 text,
    add column if not exists ingestion_status text not null default 'pending',
    add column if not exists ingestion_error text,
    add column if not exists ingested_at timestamptz,
    add column if not exists ingestion_claimed_at timestamptz;

comment on column public.documents.file_sha256 is
    'SHA-256 of the actual source file bytes, computed by the ingestion pipeline before any extraction. The idempotency key for "has this exact document already been ingested" - independent of (and in addition to) the existing (company_id, doc_type, reporting_period) uniqueness. Conflict handling between the two keys lives in application code (app/repositories/documents.py), not in a database constraint alone.';
comment on column public.documents.ingestion_status is
    'Per-document pipeline state: pending (row created, not yet claimed) -> extracting -> chunking -> embedding -> completed, or failed at any stage. A worker may only move a document OUT of pending or failed via a conditional UPDATE ... WHERE ingestion_status IN (''pending'',''failed'') - this is the concurrency-safe claim mechanism, not an application-level lock.';
comment on column public.documents.ingestion_error is
    'Set only when ingestion_status = ''failed''. The real, sanitized error message from whichever stage failed (including a stale-claim recovery marking it failed after a process crash) - never fabricated, cleared when a retry successfully claims the document again.';
comment on column public.documents.ingested_at is
    'When ingestion_status last became ''completed''. Null while pending/in-progress/failed.';
comment on column public.documents.ingestion_claimed_at is
    'Set every time a worker successfully claims this document (the conditional UPDATE that moves it out of pending/failed). A non-terminal status (extracting/chunking/embedding) whose ingestion_claimed_at is older than a stale threshold indicates a crashed worker - the recovery procedure marks such documents failed (and cleans up their partial chunks) so a normal retry can claim them again.';

-- Verify each column's actual type/nullability rather than trusting that its mere
-- existence means it was created correctly by THIS migration (it might pre-date it
-- under a different definition - e.g. a hand-added column with the right name but
-- the wrong type).
do $$
declare
    col record;
begin
    for col in
        select * from (values
            ('file_sha256', 'text', 'YES'),
            ('ingestion_status', 'text', 'NO'),
            ('ingestion_error', 'text', 'YES'),
            ('ingested_at', 'timestamp with time zone', 'YES'),
            ('ingestion_claimed_at', 'timestamp with time zone', 'YES')
        ) as expected(column_name, expected_type, expected_nullable)
    loop
        if not exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'documents'
              and column_name = col.column_name
              and data_type = col.expected_type
              and is_nullable = col.expected_nullable
        ) then
            raise exception 'migrations/007: public.documents.% exists but does not match the expected type (%) / nullability (%) - refusing to proceed silently.',
                col.column_name, col.expected_type, col.expected_nullable;
        end if;
    end loop;
end $$;

-- Guarded (Postgres has no native ADD CONSTRAINT IF NOT EXISTS): add the check
-- constraint if absent; if a constraint of this name already exists, verify its
-- definition actually enforces all six expected states rather than assuming a
-- same-named constraint is automatically the right one.
do $$
declare
    existing_def text;
    expected_states text[] := array['pending', 'extracting', 'chunking', 'embedding', 'completed', 'failed'];
    s text;
begin
    select pg_get_constraintdef(oid) into existing_def
    from pg_constraint
    where conname = 'documents_ingestion_status_check'
      and conrelid = 'public.documents'::regclass;

    if existing_def is null then
        alter table public.documents
            add constraint documents_ingestion_status_check
            check (ingestion_status in ('pending', 'extracting', 'chunking', 'embedding', 'completed', 'failed'));
    else
        foreach s in array expected_states loop
            if existing_def not like '%' || quote_literal(s) || '%' then
                raise exception 'migrations/007: documents_ingestion_status_check already exists but its definition (%) does not include the expected state %. Refusing to proceed silently.',
                    existing_def, s;
            end if;
        end loop;
    end if;
end $$;

-- Natively idempotent (CREATE INDEX IF NOT EXISTS). Partial (where file_sha256 is
-- not null) because the column is nullable for any pre-existing row written before
-- this migration and never backfilled with a real hash.
create unique index if not exists idx_documents_file_sha256
    on public.documents (file_sha256)
    where file_sha256 is not null;

create index if not exists idx_documents_ingestion_status
    on public.documents (ingestion_status);

-- Supports the crash-recovery scan efficiently: only documents in a non-terminal
-- status are ever candidates, so the index only needs to cover those.
create index if not exists idx_documents_ingestion_claimed_at
    on public.documents (ingestion_claimed_at)
    where ingestion_status in ('extracting', 'chunking', 'embedding');

-- 2. document_chunks: embedding provenance + chunk kind -----------------------
alter table public.document_chunks
    add column if not exists embedding_model text,
    add column if not exists embedding_model_revision text,
    add column if not exists chunk_type text not null default 'prose',
    add column if not exists needs_manual_review boolean not null default false;

comment on column public.document_chunks.embedding_model is
    'The embedding provider''s model_name (an explicit provider property - e.g. app.services.embeddings.local_minilm.LocalMiniLMEmbeddingProvider.model_name - never derived by splitting provider.name at write time) that produced this row''s embedding.';
comment on column public.document_chunks.embedding_model_revision is
    'The embedding provider''s model_revision (an explicit provider property, never derived by splitting provider.name) - the exact pinned model revision that produced this row''s embedding.';
comment on column public.document_chunks.chunk_type is
    '''prose'' for ordinary extracted text; ''table_row_group'' for a chunk holding one or more complete table rows plus their repeated header, confidently parsed into row/column structure; ''table_unparsed'' for text the extractor judged table-like (e.g. numeric-heavy, chart-adjacent) but could NOT confidently structure into rows/columns - raw extracted text is preserved verbatim rather than inventing structure, and needs_manual_review is set true alongside it.';
comment on column public.document_chunks.needs_manual_review is
    'True when this chunk''s structure (table or otherwise) could not be confidently determined by the extraction heuristic and must not be treated as reliable structured financial data without a human checking it. Always true when chunk_type = ''table_unparsed''; may also be set true for other low-confidence extractions in the future.';

do $$
declare
    col record;
begin
    for col in
        select * from (values
            ('embedding_model', 'text', 'YES'),
            ('embedding_model_revision', 'text', 'YES'),
            ('chunk_type', 'text', 'NO'),
            ('needs_manual_review', 'boolean', 'NO')
        ) as expected(column_name, expected_type, expected_nullable)
    loop
        if not exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'document_chunks'
              and column_name = col.column_name
              and data_type = col.expected_type
              and is_nullable = col.expected_nullable
        ) then
            raise exception 'migrations/007: public.document_chunks.% exists but does not match the expected type (%) / nullability (%) - refusing to proceed silently.',
                col.column_name, col.expected_type, col.expected_nullable;
        end if;
    end loop;
end $$;

-- CORRECTION 2: require BOTH embedding_model and embedding_model_revision
-- whenever embedding is non-null - not just the revision.
do $$
declare
    existing_def text;
begin
    select pg_get_constraintdef(oid) into existing_def
    from pg_constraint
    where conname = 'document_chunks_embedding_model_required_check'
      and conrelid = 'public.document_chunks'::regclass;

    if existing_def is null then
        alter table public.document_chunks
            add constraint document_chunks_embedding_model_required_check
            check (embedding is null or (embedding_model is not null and embedding_model_revision is not null));
    elsif existing_def not like '%embedding_model%' or existing_def not like '%embedding_model_revision%' then
        raise exception 'migrations/007: document_chunks_embedding_model_required_check already exists but its definition (%) does not reference both embedding_model and embedding_model_revision. Refusing to proceed silently.',
            existing_def;
    end if;
end $$;

do $$
declare
    existing_def text;
    expected_types text[] := array['prose', 'table_row_group', 'table_unparsed'];
    t text;
begin
    select pg_get_constraintdef(oid) into existing_def
    from pg_constraint
    where conname = 'document_chunks_chunk_type_check'
      and conrelid = 'public.document_chunks'::regclass;

    if existing_def is null then
        alter table public.document_chunks
            add constraint document_chunks_chunk_type_check
            check (chunk_type in ('prose', 'table_row_group', 'table_unparsed'));
    else
        foreach t in array expected_types loop
            if existing_def not like '%' || quote_literal(t) || '%' then
                raise exception 'migrations/007: document_chunks_chunk_type_check already exists but its definition (%) does not include the expected value %. Refusing to proceed silently.',
                    existing_def, t;
            end if;
        end loop;
    end if;
end $$;

-- A table_unparsed chunk must always carry needs_manual_review = true - this is
-- the actual mechanism that prevents an ambiguous extraction from ever being
-- silently treated as reliable structured data.
do $$
declare
    existing_def text;
begin
    select pg_get_constraintdef(oid) into existing_def
    from pg_constraint
    where conname = 'document_chunks_table_unparsed_needs_review_check'
      and conrelid = 'public.document_chunks'::regclass;

    if existing_def is null then
        alter table public.document_chunks
            add constraint document_chunks_table_unparsed_needs_review_check
            check (chunk_type <> 'table_unparsed' or needs_manual_review);
    elsif existing_def not like '%table_unparsed%' or existing_def not like '%needs_manual_review%' then
        raise exception 'migrations/007: document_chunks_table_unparsed_needs_review_check already exists but its definition (%) does not reference both chunk_type/table_unparsed and needs_manual_review. Refusing to proceed silently.',
            existing_def;
    end if;
end $$;

commit;
