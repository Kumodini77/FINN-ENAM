-- PROPOSED — NOT YET APPLIED. For review only. Do not execute without approval.
--
-- FINN — company-filtered pgvector cosine-distance similarity search over
-- document_chunks, exposed as a Postgres function so it's callable via
-- Supabase's PostgREST /rpc/ endpoint. A plain client-side `.order()` call
-- cannot express `<=>`-based ordering through PostgREST's query builder, so a
-- function is the only way real pgvector search is reachable from the backend.
--
-- Does not touch migrations 001-005, does not alter documents/document_chunks
-- (no ALTER/DROP/CREATE TABLE here), and writes no rows. CREATE OR REPLACE
-- FUNCTION plus REVOKE/GRANT are naturally idempotent, so rerunning this file
-- is safe. No explicit transaction control is used — a single CREATE OR
-- REPLACE FUNCTION plus its REVOKE/GRANT statements already run as one
-- implicit transaction when applied via the Supabase SQL editor, same as
-- every prior migration in this project.
--
-- WHERE THE VECTOR EXTENSION LIVES: migrations/001_init.sql ran
-- `create extension if not exists vector;` with no explicit target schema.
-- Confirmed live (not assumed) via Supabase's PostgREST OpenAPI introspection:
-- GET {SUPABASE_URL}/rest/v1/ reports document_chunks.embedding's format as
-- literally "public.vector(384)" — PostgREST derives that qualified name from
-- the column's real type oid, so the vector type lives in `public`. An
-- extension installs its operators (including `<=>`) into the same schema as
-- its type, so `<=>` is also `public.<=>` — that is why every relation, the
-- vector type, and the operator below are qualified as `public.*` rather than
-- left to resolve via search_path.
--
-- RETURN-TYPE AUDIT (against migrations/001_init.sql through 005, the actual
-- source of these columns' declared types — not assumed):
--   dc.id                uuid              -> chunk_id uuid               (exact match)
--   dc.document_id       uuid              -> document_id uuid            (exact match)
--   dc.company_id        uuid              -> company_id uuid             (exact match)
--   c.ticker              text not null     -> company_ticker text         (exact match)
--   dc.text               text not null     -> chunk_text text             (exact match)
--   dc.page_reference     int               -> page_reference int          (exact match)
--   dc.section_label      text              -> section_label text          (exact match)
--   d.doc_type            text not null     -> doc_type text               (exact match)
--   d.reporting_period    text              -> reporting_period text       (exact match)
--   d.original_source_url text not null     -> original_source_url text    (exact match)
--   dc.embedding <=> query_embedding   -> pgvector's <=>/<->/<#> operators are all
--     declared to return float8 (double precision) — matches `distance double precision`
--     exactly; the explicit `::double precision` cast below is therefore redundant but
--     kept for clarity/defensiveness rather than relying on an implicit match.
--   1 - (dc.embedding <=> query_embedding) -> double precision - double precision ->
--     double precision — matches `similarity double precision` exactly; same
--     explicit cast kept for the same reason.
-- No column required a NEW cast or a change to any table definition: every 1:1
-- column copy already matches its declared RETURNS TABLE type exactly, and the
-- two derived (non-column) expressions were already being cast explicitly.
--
-- SUPABASE ROLES (anon, authenticated, service_role): these are Supabase's own
-- standard, always-present Postgres roles for every project (anon = unauthenticated
-- REST/RPC callers, authenticated = logged-in end users, service_role = full-access
-- trusted backend callers) — not something this migration creates. This
-- project's backend (backend/app/core/config.py's `supabase_key`) authenticates
-- with the service_role key, which is why GRANT below targets that role only.

create or replace function public.match_document_chunks(
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
    -- Required, non-bypassable company filter: this function will never run an
    -- unfiltered, cross-company search. The caller (FINN's FastAPI backend,
    -- the only intended caller per the GRANT below) controls this value; it is
    -- a retrieval filter, not an authentication mechanism.
    if filter_company_id is null then
        raise exception 'match_document_chunks: filter_company_id is required and cannot be NULL — refusing to run an unfiltered, cross-company search.';
    end if;

    if query_embedding is null then
        raise exception 'match_document_chunks: query_embedding cannot be NULL.';
    end if;

    -- match_count semantics (deliberately NOT the same branch):
    --   * OMITTED entirely by the caller -> Postgres substitutes the SQL-level
    --     `default 5` BEFORE this function body ever runs, so this IF sees 5,
    --     not NULL, and falls to the ELSE branch below.
    --   * EXPLICITLY passed as NULL -> Postgres does NOT apply the default in
    --     this case (defaults only apply to omitted arguments), so this IF
    --     sees a genuine NULL and must reject it, not silently coerce it to 5.
    if match_count is null then
        raise exception 'match_document_chunks: match_count cannot be explicitly NULL — omit the argument entirely to use the default of 5.';
    elsif match_count < 1 then
        raise exception 'match_document_chunks: match_count must be a positive integer, got %.', match_count;
    else
        -- Server-side cap: no caller-supplied value, however large, can
        -- request more than 20 rows.
        effective_match_count := least(match_count, 20);
    end if;

    return query
    select
        dc.id as chunk_id,
        dc.document_id,
        dc.company_id,
        c.ticker as company_ticker,
        dc.text as chunk_text,
        dc.page_reference,
        dc.section_label,
        d.doc_type,
        d.reporting_period,
        d.original_source_url,
        -- Cosine DISTANCE (pgvector's <=> operator): 0 = identical direction,
        -- larger = less similar. Schema-qualified via OPERATOR(public.<=>)
        -- because search_path is '' above, so an unqualified <=> would not
        -- resolve at all.
        (dc.embedding OPERATOR(public.<=>) query_embedding)::double precision as distance,
        -- similarity is derived purely for readability: 1 - distance. For
        -- normalized embedding vectors (sentence-transformers models, including
        -- the pinned all-MiniLM-L6-v2, output L2-normalized vectors) cosine
        -- distance ranges [0, 2], so this is NOT guaranteed to land in [0, 1] -
        -- treat `distance` as the authoritative ranking value and `similarity`
        -- as a convenience display figure, never the reverse.
        (1 - (dc.embedding OPERATOR(public.<=>) query_embedding))::double precision as similarity
    from public.document_chunks dc
    join public.documents d on d.id = dc.document_id
    join public.companies c on c.id = dc.company_id
    where dc.company_id = filter_company_id
      -- Correction 1: a chunk's own company_id (denormalized for pre-filtering)
      -- must also match its parent document's company_id. document_chunks.company_id
      -- and documents.company_id are populated independently at write time, so
      -- nothing in the schema itself guarantees they agree for a given row - this
      -- closes that gap explicitly rather than assuming it. This also guarantees
      -- the returned company_ticker/doc_type/reporting_period/original_source_url
      -- genuinely describe the chunk's real source document, not a mismatched one.
      and d.company_id = dc.company_id
      and dc.embedding is not null
    order by dc.embedding OPERATOR(public.<=>) query_embedding
    limit effective_match_count;
end;
$$;

comment on function public.match_document_chunks(public.vector(384), uuid, integer) is
    'Company-scoped pgvector cosine-distance similarity search over document_chunks, joined to documents/companies for citation metadata. filter_company_id is required and not optional, and the join enforces that a chunk''s own company_id and its parent document''s company_id agree, so results and their citation metadata can never cross company boundaries. query_embedding must be vector(384), matching the pinned sentence-transformers/all-MiniLM-L6-v2 (rev 1110a243fdf4706b3f48f1d95db1a4f5529b4d41) embedding dimension.';

-- Security: SECURITY INVOKER (not DEFINER) means this function runs with the
-- privileges of whoever calls it - it is not granted anything the caller
-- doesn't already have. Explicitly deny execution to every role except
-- service_role, since FINN's FastAPI backend (the only intended caller) talks
-- to Supabase using the service_role key; anon/authenticated are not expected
-- to call this directly.
revoke all on function public.match_document_chunks(public.vector(384), uuid, integer) from public;
revoke all on function public.match_document_chunks(public.vector(384), uuid, integer) from anon;
revoke all on function public.match_document_chunks(public.vector(384), uuid, integer) from authenticated;
grant execute on function public.match_document_chunks(public.vector(384), uuid, integer) to service_role;

-- PostgREST caches the schema (including which functions exist and their
-- signatures) at startup and does not notice a new function on its own. This
-- tells the running PostgREST instance to reload its schema cache immediately,
-- so match_document_chunks becomes callable via /rpc/match_document_chunks
-- without waiting for PostgREST's own periodic refresh or a restart.
notify pgrst, 'reload schema';
