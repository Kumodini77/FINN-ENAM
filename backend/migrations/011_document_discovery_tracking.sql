-- PROPOSED — NOT YET APPLIED. For review only. Do not execute without approval.
--
-- FINN Phase 12B — two new, additive tables for automatic document discovery:
-- `document_sources` (durable per-company/per-source checkpoints — never an
-- in-memory dict) and `document_review_queue` (ambiguous candidates awaiting
-- human review, never auto-ingested). Neither table is read by any other part
-- of the system; nothing existing is modified, dropped, or reprocessed by this
-- file. Applied the same way as 007/009 — reviewed and run manually via the
-- Supabase SQL Editor (see docs/migration-runbook.md) — never executed
-- automatically by the application or by this agent.
--
-- Depends on: `companies` (001_init.sql) for the FK below. Independent of
-- migration 010 (ingestion_jobs widening) — can be applied in either order
-- relative to it.

begin;

create table if not exists public.document_sources (
    id uuid primary key default uuid_generate_v4(),
    company_ticker text not null,
    source_name text not null,
    source_url text,
    last_checked_at timestamptz,
    last_successful_check_at timestamptz,
    last_discovered_document_title text,
    last_discovered_document_url text,
    latest_processed_document_id uuid references public.documents(id) on delete set null,
    health text not null default 'unknown' check (health in ('healthy', 'degraded', 'blocked', 'unknown')),
    error_message text,
    next_eligible_check_at timestamptz,
    updated_at timestamptz not null default now(),
    unique (company_ticker, source_name)
);

comment on table public.document_sources is
    'Durable per-company, per-source discovery checkpoints for Phase 12B (app.repositories.document_sources.DocumentSourceRepository). company_ticker is used directly (not company_id) so a source can be checked even for a ticker not yet registered in `companies` — discovery can run before a company is otherwise known to FINN.';
comment on column public.document_sources.health is
    'healthy: last check succeeded. degraded: last check failed but a prior successful check exists (last_successful_check_at is set) — the system keeps serving the last known good state rather than treating a transient failure as total unavailability. blocked: repeated/durable failure (e.g. bot protection, like the real NTPC/NSE findings documented elsewhere in this project) — an operator should stop expecting this source to recover without investigation. unknown: never successfully checked yet.';

create index if not exists idx_document_sources_health on public.document_sources (health);
create index if not exists idx_document_sources_next_check on public.document_sources (next_eligible_check_at);

create table if not exists public.document_review_queue (
    id uuid primary key default uuid_generate_v4(),
    company_ticker text not null,
    doc_type text not null,
    title text not null,
    source_url text not null,
    source_name text not null,
    reporting_period text,
    reason text not null,
    status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
    created_at timestamptz not null default now(),
    reviewed_at timestamptz,
    unique (source_url)
);

comment on table public.document_review_queue is
    'Discovery candidates the automated pipeline refused to auto-ingest (unconfirmed source identity, ambiguous doc_type/period, or an ambiguous collision with existing document metadata) — app.repositories.document_review_queue.ReviewQueueRepository. Nothing here has ever been downloaded or ingested; approving an entry here is a separate, explicit future step, not implemented by this migration.';

create index if not exists idx_document_review_queue_status on public.document_review_queue (status);

commit;
