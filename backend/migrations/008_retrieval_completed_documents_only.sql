-- PROPOSED — NOT YET APPLIED. For review only. Do not execute without approval.
--
-- FINN — restrict match_document_chunks (migrations/006) to chunks whose parent
-- document has ingestion_status = 'completed', and add chunk_type to its returned
-- citation data.
--
-- Does NOT modify migrations/006_vector_similarity_search_rpc.sql on disk - that
-- file is left exactly as applied.
--
-- WHY DROP+CREATE INSIDE AN EXPLICIT TRANSACTION, NOT CREATE OR REPLACE:
-- This revision adds `chunk_type` to the RETURNS TABLE column list. Postgres
-- refuses a CREATE OR REPLACE FUNCTION that changes an existing function's return
-- type ("cannot change return type of existing function") - it would hard-fail,
-- not simply ignore the new column. The function must be dropped and recreated.
-- Wrapping DROP + CREATE + COMMENT + REVOKE/GRANT in one explicit transaction
-- means Postgres's own transactional DDL guarantees no concurrent caller can ever
-- observe the intermediate state where match_document_chunks does not exist -
-- from any other session's point of view, the old 4-column-citation version is
-- visible right up until this transaction commits, at which point the new
-- chunk_type-including version becomes visible atomically. NOTIFY's payload is
-- only actually delivered at COMMIT (standard Postgres behavior), so it is safe
-- to issue inside the same transaction.
--
-- WHY A SEPARATE MIGRATION (008) RATHER THAN FOLDED INTO 007: unchanged from the
-- prior review - this is a behavior change to live retrieval (what every future
-- query returns), a materially different risk class from a schema addition,
-- deserving its own isolated, independently reviewable/rollback-able migration -
-- consistent with 005 (dimension) and 006 (RPC) already being kept separate.
--
-- PRECONDITION GUARD: aborts clearly (before dropping anything) if migration 007
-- has not been applied yet (documents.ingestion_status or
-- document_chunks.chunk_type missing), rather than dropping the only existing
-- version of this function and then failing to recreate it.
--
-- REVISION (this version): DROP FUNCTION removes the prior function object
-- entirely, including its owner record - CREATE FUNCTION would otherwise set the
-- new function's owner to whichever role happens to execute this script, which is
-- not necessarily the same role that owned the original (migration 006) function.
-- This version captures the existing owner before dropping and explicitly restores
-- it afterward (see the owner-capture temp table and restore block below), so
-- ownership is preserved regardless of which role runs the migration.

begin;

-- Captures the EXISTING function's owner role before it is dropped, so this
-- migration can restore it on the new function afterward (see below) rather than
-- letting ownership silently fall to whichever role happens to execute this
-- script. Session-local, dropped automatically at commit/rollback - never a
-- persistent object.
create temporary table _migration_008_owner_capture (owner_role text) on commit drop;
insert into _migration_008_owner_capture (owner_role)
select r.rolname
from pg_proc p
join pg_roles r on r.oid = p.proowner
where p.proname = 'match_document_chunks' and p.pronamespace = 'public'::regnamespace;

do $$
begin
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.documents'::regclass
          and attname = 'ingestion_status'
          and attnum > 0
          and not attisdropped
    ) then
        raise exception 'migrations/008 requires documents.ingestion_status (added by migrations/007) to exist first - apply 007 before 008.';
    end if;

    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.document_chunks'::regclass
          and attname = 'chunk_type'
          and attnum > 0
          and not attisdropped
    ) then
        raise exception 'migrations/008 requires document_chunks.chunk_type (added by migrations/007) to exist first - apply 007 before 008.';
    end if;

    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.document_chunks'::regclass
          and attname = 'needs_manual_review'
          and attnum > 0
          and not attisdropped
    ) then
        raise exception 'migrations/008 requires document_chunks.needs_manual_review (added by migrations/007) to exist first - apply 007 before 008.';
    end if;
end $$;

-- IF EXISTS so this file stays rerunnable (e.g. a retry after an earlier partial
-- failure in this same transaction, before the precondition guard above existed
-- to catch it).
drop function if exists public.match_document_chunks(public.vector(384), uuid, integer);

create function public.match_document_chunks(
    query_embedding public.vector(384),
    filter_company_id uuid,
    match_count integer default 5
)
returns table (
    chunk_id uuid,
    document_id uuid,
    company_id uuid,
    company_ticker text,
    chunk_text text,
    chunk_type text,
    needs_manual_review boolean,
    page_reference int,
    section_label text,
    doc_type text,
    reporting_period text,
    original_source_url text,
    distance double precision,
    similarity double precision
)
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    effective_match_count integer;
begin
    if filter_company_id is null then
        raise exception 'match_document_chunks: filter_company_id is required and cannot be NULL — refusing to run an unfiltered, cross-company search.';
    end if;

    if query_embedding is null then
        raise exception 'match_document_chunks: query_embedding cannot be NULL.';
    end if;

    if match_count is null then
        raise exception 'match_document_chunks: match_count cannot be explicitly NULL — omit the argument entirely to use the default of 5.';
    elsif match_count < 1 then
        raise exception 'match_document_chunks: match_count must be a positive integer, got %.', match_count;
    else
        effective_match_count := least(match_count, 20);
    end if;

    return query
    select
        dc.id as chunk_id,
        dc.document_id,
        dc.company_id,
        c.ticker as company_ticker,
        dc.text as chunk_text,
        dc.chunk_type,
        dc.needs_manual_review,
        dc.page_reference,
        dc.section_label,
        d.doc_type,
        d.reporting_period,
        d.original_source_url,
        (dc.embedding OPERATOR(public.<=>) query_embedding)::double precision as distance,
        (1 - (dc.embedding OPERATOR(public.<=>) query_embedding))::double precision as similarity
    from public.document_chunks dc
    join public.documents d on d.id = dc.document_id
    join public.companies c on c.id = dc.company_id
    where dc.company_id = filter_company_id
      -- unchanged from migration 006: chunk/parent-document company consistency.
      and d.company_id = dc.company_id
      and dc.embedding is not null
      -- new in this migration: only serve evidence from a document the ingestion
      -- pipeline has actually finished processing. A document that is
      -- pending/in-progress may have partial or since-superseded chunks; a failed
      -- document's chunks are already deleted by the ingestion pipeline's own
      -- cleanup, but this guard means retrieval's correctness never depends on
      -- that cleanup having run - it is a second, independent safeguard.
      and d.ingestion_status = 'completed'
    order by dc.embedding OPERATOR(public.<=>) query_embedding
    limit effective_match_count;
end;
$$;

-- Restore the previous owner captured above, if there was one (an empty capture
-- table means the function didn't exist yet - nothing to restore, the new owner is
-- simply whichever role ran this migration, which is the correct and only sensible
-- outcome for a brand-new object).
do $$
declare
    captured_owner text;
begin
    select owner_role into captured_owner from _migration_008_owner_capture limit 1;
    if captured_owner is not null then
        execute format(
            'alter function public.match_document_chunks(public.vector(384), uuid, integer) owner to %I',
            captured_owner
        );
    end if;
end $$;

comment on function public.match_document_chunks(public.vector(384), uuid, integer) is
    'Company-scoped pgvector cosine-distance similarity search over document_chunks belonging only to documents with ingestion_status = ''completed'', joined to documents/companies for citation metadata, including chunk_type (prose/table_row_group/table_unparsed) and needs_manual_review so a caller can distinguish confidently-structured evidence from uncertain extraction. filter_company_id is required and not optional, and the join enforces that a chunk''s own company_id and its parent document''s company_id agree, so results and their citation metadata can never cross company boundaries. query_embedding must be vector(384), matching the pinned sentence-transformers/all-MiniLM-L6-v2 (rev 1110a243fdf4706b3f48f1d95db1a4f5529b4d41) embedding dimension.';

-- DROP FUNCTION removed all previously-granted privileges along with the old
-- function - reapply the exact same grant state as migration 006.
revoke all on function public.match_document_chunks(public.vector(384), uuid, integer) from public;
revoke all on function public.match_document_chunks(public.vector(384), uuid, integer) from anon;
revoke all on function public.match_document_chunks(public.vector(384), uuid, integer) from authenticated;
grant execute on function public.match_document_chunks(public.vector(384), uuid, integer) to service_role;

notify pgrst, 'reload schema';

commit;
