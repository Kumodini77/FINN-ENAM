-- FINN — switch document_chunks.embedding from vector(1536) to vector(384).
--
-- Context: embeddings were originally scoped against OpenAI's text-embedding-3-small
-- (1536-dim). Per an explicit no-paid-embedding-API decision, FINN now uses a local
-- model (sentence-transformers/all-MiniLM-L6-v2, pinned to commit
-- 1110a243fdf4706b3f48f1d95db1a4f5529b4d41, 384-dim) for all embeddings — see
-- backend/app/services/embeddings/.
--
-- Execution order (deliberately structured so the common no-op rerun is cheap and
-- never depends on anything that could change later, like a future HNSW index):
--   1. Acquire ACCESS EXCLUSIVE lock on public.document_chunks.
--   2. Read the embedding column's actual type oid (atttypid) and dimension
--      (atttypmod), schema-qualified.
--   3. Confirm atttypid genuinely resolves to pg_type.typname = 'vector' — a
--      matching typmod alone does not prove the column is a vector column at all,
--      so this is checked independently of the dimension value.
--   4. If dimension is already 384: return immediately with a NOTICE. Indexes and
--      constraints are NOT inspected on this path, so a future HNSW/other index
--      added after this migration first runs can never cause a rerun to fail.
--   5. If dimension is not 1536 at this point (not already handled by step 4):
--      abort — unexpected state.
--   6. Verify the table is genuinely empty (under the lock from step 1, so this
--      can't change before the DROP below).
--   7. Only now — on the one path that will actually mutate the schema — enumerate
--      every index and constraint keyed on the embedding column and verify each
--      index's access method/operator class before allowing it to be dropped.
--   8. Drop the verified dependent index(es), drop the column, add it back as
--      vector(384).
--   9. Do not create any approximate vector index (IVFFlat or HNSW).
--
-- DELIBERATE DECISION: no approximate vector index is created on the new vector(384)
-- column. Supabase's current guidance recommends HNSW for production use and
-- recommends building an approximate index only once there is a meaningful amount of
-- real data; IVFFlat in particular degrades badly when built on a near-empty table.
-- At this prototype's current data volume (zero real document chunks ingested yet),
-- exact cosine-distance search via a plain query is sufficient. HNSW should be
-- evaluated and added later, once FINN has ingested a genuine corpus of document
-- chunks — see docs/architecture.md.
--
-- Only document_chunks.embedding and indexes/constraints keyed on it are ever
-- touched. idx_chunks_company, every other table, and all existing rows are
-- untouched. document_chunks rows are never dropped by this migration.

do $$
declare
    embedding_typid oid;
    embedding_typname name;
    current_dim integer;
    embedding_attnum smallint;
    row_count integer;
    dependent_constraint_count integer;
    rec record;
begin
    -- 1. Lock the table FIRST, before any read, so no concurrent ingestion can race
    -- between our checks and the schema change.
    lock table public.document_chunks in access exclusive mode;

    -- 2. Read the embedding column's actual type oid and dimension, schema-qualified.
    select atttypid, atttypmod, attnum into embedding_typid, current_dim, embedding_attnum
    from pg_attribute
    where attrelid = 'public.document_chunks'::regclass
      and attname = 'embedding'
      and attnum > 0
      and not attisdropped;

    if embedding_typid is null then
        raise exception 'public.document_chunks.embedding column not found — aborting rather than guessing what to do.';
    end if;

    -- 3. Confirm the column's type actually resolves to pgvector's "vector" type.
    -- A matching typmod alone does not prove this is a vector column.
    select typname into embedding_typname from pg_type where oid = embedding_typid;

    if embedding_typname is distinct from 'vector' then
        raise exception 'public.document_chunks.embedding has type % (oid %), not pgvector''s vector type — aborting rather than assuming a matching type modifier means anything.', embedding_typname, embedding_typid;
    end if;

    -- 4. Already at the target dimension: true no-op. Deliberately returns BEFORE
    -- inspecting any index or constraint, so a future HNSW index (or anything else
    -- added once this migration has already run) can never make a rerun fail.
    if current_dim = 384 then
        raise notice 'document_chunks.embedding is already vector(384) — no schema change needed, migration is a no-op.';
        return;
    end if;

    -- 5. Any dimension other than 1536 or 384 is an unexpected state: abort.
    if current_dim <> 1536 then
        raise exception 'document_chunks.embedding has unexpected dimension % (expected 1536 or 384) — aborting rather than guessing how to proceed.', current_dim;
    end if;

    -- 6. current_dim = 1536: only safe to change if the table is genuinely empty.
    -- The ACCESS EXCLUSIVE lock from step 1 guarantees this can't change under us.
    select count(*) into row_count from public.document_chunks;
    if row_count > 0 then
        raise exception 'document_chunks has % row(s) and embedding is still vector(1536) — refusing to change dimension on non-empty data. This needs a real re-embedding migration, not a schema-only change.', row_count;
    end if;

    -- 7. Only reached on the one path that will actually mutate the schema: verify
    -- every index keyed on the embedding column (by catalog structure, not by name)
    -- has the expected access method + operator class before allowing it to be
    -- dropped below.
    for rec in
        select
            i.relname as index_name,
            am.amname as index_method,
            pgidx.indexdef as index_def
        from pg_index idx
        join pg_class i on i.oid = idx.indexrelid
        join pg_class t on t.oid = idx.indrelid
        join pg_namespace n on n.oid = t.relnamespace
        join pg_am am on am.oid = i.relam
        join pg_indexes pgidx
          on pgidx.schemaname = n.nspname
         and pgidx.tablename = t.relname
         and pgidx.indexname = i.relname
        where idx.indrelid = 'public.document_chunks'::regclass
          and embedding_attnum = any(idx.indkey)
    loop
        if rec.index_method <> 'ivfflat' or rec.index_def not ilike '%vector_cosine_ops%' then
            raise exception 'Index % on document_chunks.embedding has unexpected method/opclass (method: %, definition: %) — aborting rather than dropping an index this migration does not recognize.', rec.index_name, rec.index_method, rec.index_def;
        end if;
    end loop;

    -- Also verify no constraint depends on the embedding column before dropping it.
    select count(*) into dependent_constraint_count
    from pg_constraint c
    where c.conrelid = 'public.document_chunks'::regclass
      and embedding_attnum = any(c.conkey);

    if dependent_constraint_count > 0 then
        raise exception 'document_chunks.embedding has % constraint(s) depending on it — aborting rather than dropping a column with unexpected constraints.', dependent_constraint_count;
    end if;

    raise notice 'document_chunks is empty and embedding is vector(1536) — changing to vector(384). No approximate vector index will be created; exact cosine-distance search is sufficient at this data volume. HNSW can be evaluated and added later once FINN has ingested a meaningful number of genuine document chunks.';

    -- 8. Drop every verified dependent index, then change the column. Deliberately
    -- NOT recreating an approximate vector index. document_chunks rows themselves
    -- are never touched — only the column's type is dropped and re-added.
    for rec in
        select i.relname as index_name
        from pg_index idx
        join pg_class i on i.oid = idx.indexrelid
        where idx.indrelid = 'public.document_chunks'::regclass
          and embedding_attnum = any(idx.indkey)
    loop
        execute format('drop index public.%I', rec.index_name);
    end loop;

    execute 'alter table public.document_chunks drop column embedding';
    execute 'alter table public.document_chunks add column embedding vector(384)';
end $$;
