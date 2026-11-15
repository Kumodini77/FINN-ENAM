-- FINN Phase 12A — additive support for scheduled EOD market-data refresh.
--
-- Reuses two tables that already existed in 001_init.sql but were never read or
-- written by any application code: `prices` (raw EOD bars) and `ingestion_jobs`
-- (job audit trail). This migration only widens `ingestion_jobs` so it can track a
-- 20-company batch job (pending/running states, retries, timeouts, a structured
-- per-company result summary, and a heartbeat for crash recovery) instead of the
-- single-company/three-terminal-state shape it started with. No existing column is
-- dropped or redefined; every change is additive and guarded so re-running this file
-- after it already succeeded is a no-op, matching the pattern established in
-- 007_document_ingestion_tracking.sql.
--
-- Nothing here changes the `companies`, `portfolio`, or `document_chunks` tables, and
-- nothing here reprocesses or deletes any existing row.

begin;

-- 1. ingestion_jobs: widen status + add job-execution-framework columns ------
alter table public.ingestion_jobs
    add column if not exists retry_count int not null default 0,
    add column if not exists max_retries int not null default 2,
    add column if not exists timeout_seconds int not null default 300,
    add column if not exists claimed_at timestamptz,
    add column if not exists heartbeat_at timestamptz,
    add column if not exists triggered_by text not null default 'manual',
    add column if not exists result_summary jsonb not null default '{}'::jsonb,
    add column if not exists log text;

comment on column public.ingestion_jobs.retry_count is
    'How many retry attempts this run has consumed so far across its own internal bounded-backoff retries (per sub-unit, e.g. per company) — not how many times the whole job was restarted.';
comment on column public.ingestion_jobs.max_retries is
    'Retry budget for this run''s job_type.';
comment on column public.ingestion_jobs.timeout_seconds is
    'Wall-clock budget for one unit of work within this job (e.g. one company''s fetch) — not the whole batch.';
comment on column public.ingestion_jobs.claimed_at is
    'Set when this run transitions into status=''running''. A ''running'' row whose heartbeat_at is older than a stale threshold indicates a crashed worker — see app.repositories.job_runs.reclaim_stale_running, which marks it failed so a new run can start (the actual duplicate-run-prevention + crash-recovery mechanism, not a database-level lock).';
comment on column public.ingestion_jobs.heartbeat_at is
    'Updated periodically while status=''running'' (and once more at completion). Used only for stale-run detection.';
comment on column public.ingestion_jobs.triggered_by is
    'Who/what started this run: ''scheduler'', ''manual'', or ''api''. Never fabricated — set explicitly by the caller.';
comment on column public.ingestion_jobs.result_summary is
    'Structured per-unit results, e.g. {"TCS": {"status": "success", "trade_date": "2026-11-13"}, "WIPRO": {"status": "failed", "error": "..."}}. One ingestion_jobs row represents one batch run (company_id stays null for a batch run); per-company outcomes live here instead of one row per company, to avoid a second table for what is still a small, bounded 20-row result set.';
comment on column public.ingestion_jobs.log is
    'Free-text execution log for operator inspection — append-only summary lines, not a replacement for real application logging.';

do $$
declare
    col record;
begin
    for col in
        select * from (values
            ('retry_count', 'integer', 'NO'),
            ('max_retries', 'integer', 'NO'),
            ('timeout_seconds', 'integer', 'NO'),
            ('claimed_at', 'timestamp with time zone', 'YES'),
            ('heartbeat_at', 'timestamp with time zone', 'YES'),
            ('triggered_by', 'text', 'NO'),
            ('result_summary', 'jsonb', 'NO'),
            ('log', 'text', 'YES')
        ) as expected(column_name, expected_type, expected_nullable)
    loop
        if not exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'ingestion_jobs'
              and column_name = col.column_name
              and data_type = col.expected_type
              and is_nullable = col.expected_nullable
        ) then
            raise exception 'migrations/010: public.ingestion_jobs.% exists but does not match the expected type (%) / nullability (%) - refusing to proceed silently.',
                col.column_name, col.expected_type, col.expected_nullable;
        end if;
    end loop;
end $$;

-- Widen the status check constraint: add 'pending' and 'running' to the existing
-- ('success','partial','failed') set, without weakening it.
do $$
declare
    existing_def text;
    expected_states text[] := array['pending', 'running', 'success', 'partial', 'failed'];
    s text;
begin
    select pg_get_constraintdef(oid) into existing_def
    from pg_constraint
    where conname = 'ingestion_jobs_status_check'
      and conrelid = 'public.ingestion_jobs'::regclass;

    if existing_def is null then
        raise exception 'migrations/010: expected constraint ingestion_jobs_status_check (from 001_init.sql) not found - refusing to add a replacement blind.';
    end if;

    if existing_def like '%pending%' and existing_def like '%running%' then
        -- Already widened by a previous run of this migration.
        null;
    else
        alter table public.ingestion_jobs drop constraint ingestion_jobs_status_check;
        alter table public.ingestion_jobs
            add constraint ingestion_jobs_status_check
            check (status in ('pending', 'running', 'success', 'partial', 'failed'));
    end if;

    foreach s in array expected_states loop
        if not exists (
            select 1 from pg_constraint
            where conname = 'ingestion_jobs_status_check' and conrelid = 'public.ingestion_jobs'::regclass
              and pg_get_constraintdef(oid) like '%' || quote_literal(s) || '%'
        ) then
            raise exception 'migrations/010: ingestion_jobs_status_check does not include expected state %. Refusing to proceed silently.', s;
        end if;
    end loop;
end $$;

-- Widen job_type to include the new batch job. 'price_fetch' already existed in
-- 001_init.sql's check constraint but was never used - 'market_data_refresh' is a
-- distinct, more specific name for this phase's batch job so it's never confused
-- with a future single-company price_fetch unit.
do $$
declare
    existing_def text;
begin
    select pg_get_constraintdef(oid) into existing_def
    from pg_constraint
    where conname = 'ingestion_jobs_job_type_check'
      and conrelid = 'public.ingestion_jobs'::regclass;

    if existing_def is null then
        raise exception 'migrations/010: expected constraint ingestion_jobs_job_type_check (from 001_init.sql) not found - refusing to add a replacement blind.';
    end if;

    if existing_def not like '%market_data_refresh%' then
        alter table public.ingestion_jobs drop constraint ingestion_jobs_job_type_check;
        alter table public.ingestion_jobs
            add constraint ingestion_jobs_job_type_check
            check (job_type in ('price_fetch', 'announcement_seed', 'fundamentals_fetch', 'fundamentals_seed', 'market_data_refresh'));
    end if;
end $$;

-- Supports "is a market_data_refresh run currently pending/running" (duplicate-run
-- prevention) and "find stale running rows" (crash recovery) efficiently.
create index if not exists idx_ingestion_jobs_job_type_status
    on public.ingestion_jobs (job_type, status);

create index if not exists idx_ingestion_jobs_heartbeat
    on public.ingestion_jobs (heartbeat_at)
    where status = 'running';

commit;
