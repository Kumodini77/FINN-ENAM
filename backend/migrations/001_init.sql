-- FINN — initial schema
-- Run against a Supabase/Postgres project. Nothing here has been executed against a
-- live database as part of this build — Supabase credentials were not available/configured
-- in this environment (see README.md). This file and 002_seed_companies.sql are the
-- migration source of truth; apply via `supabase db push` or the SQL editor once a
-- project is provisioned.

create extension if not exists "uuid-ossp";
create extension if not exists vector;

-- Shared enum for data provenance: every row that can come from more than one path
-- must say which path produced it, per the Phase 0 / Phase 0B findings (live scraping
-- of NSE/BSE failed; data is either a verified live fetch, a cached live fetch, or a
-- manually-curated seed).
create type data_source_type as enum ('live', 'cached', 'manual_seed');

-- 1. companies ---------------------------------------------------------------
create table companies (
    id uuid primary key default uuid_generate_v4(),
    ticker text not null unique,
    name text not null,
    exchange text not null check (exchange in ('NSE', 'BSE')),
    sector text,
    yfinance_symbol text not null,
    is_seed_portfolio boolean not null default false,
    created_at timestamptz not null default now()
);

-- 2. portfolio ----------------------------------------------------------------
-- Which companies belong to which user's tracked portfolio (prototype may have one
-- implicit demo user; table still models multi-user for a clean upgrade path).
create table users (
    id uuid primary key default uuid_generate_v4(),
    email text,
    created_at timestamptz not null default now()
);

create table portfolio (
    user_id uuid not null references users(id) on delete cascade,
    company_id uuid not null references companies(id) on delete cascade,
    added_at timestamptz not null default now(),
    primary key (user_id, company_id)
);

-- 3. prices ---------------------------------------------------------------
create table prices (
    id bigserial primary key,
    company_id uuid not null references companies(id) on delete cascade,
    trade_date date not null,
    open numeric,
    high numeric,
    low numeric,
    close numeric not null,
    volume bigint not null,
    currency text not null default 'INR',
    session_status text not null default 'closed_eod' check (session_status in ('closed_eod', 'provisional_intraday')),
    source data_source_type not null default 'live',
    fetched_at timestamptz not null default now(),
    unique (company_id, trade_date)
);
create index idx_prices_company_date on prices (company_id, trade_date desc);

-- 4. announcements ---------------------------------------------------------------
-- Per docs/filing-access-spike.md: NSE/BSE do not permit direct automated access in our
-- tested environment. `source` tracks whether a row was live-fetched (future, if a
-- licensed feed is procured) or manually curated (the prototype's actual path) —
-- never silently presented as live when it is not.
create type announcement_category as enum (
    'results', 'M&A', 'fund_raise', 'management_change', 'litigation',
    'insider_trading', 'earnings_call', 'investor_meetings', 'credit_rating',
    'dividend', 'bonus_split', 'capex', 'press_release', 'postal_ballot',
    'agm_egm', 'pledging', 'unclassified'
);

create table announcements (
    id uuid primary key default uuid_generate_v4(),
    company_id uuid not null references companies(id) on delete cascade,
    filed_at timestamptz not null,
    title text not null,
    category announcement_category not null default 'unclassified',
    category_confidence numeric,
    one_line_summary text,
    is_material boolean not null default false,
    original_source_url text not null,
    source data_source_type not null default 'manual_seed',
    seeded_by text,
    created_at timestamptz not null default now(),
    -- Prevent the same real-world filing being inserted twice (manual curation risk).
    unique (company_id, filed_at, title)
);
create index idx_announcements_company_filed on announcements (company_id, filed_at desc);
create index idx_announcements_category on announcements (category);

-- 5. documents ---------------------------------------------------------------
-- Per docs/fundamentals-access-spike.md: screener.in is a reliable index; the documents
-- it links to are hosted inconsistently (BSE blocked, company IR sites vary). `source`
-- and `original_source_url` preserve exactly where each document actually came from.
create table documents (
    id uuid primary key default uuid_generate_v4(),
    company_id uuid not null references companies(id) on delete cascade,
    doc_type text not null check (doc_type in ('annual_report', 'concall_transcript', 'investor_presentation')),
    reporting_period text,         -- e.g. 'FY2025-26', 'Q1FY27'
    period_end_date date,
    original_source_url text not null,
    discovered_via text,           -- e.g. 'screener.in', 'company_ir_site', 'nse_archives', 'manual'
    source data_source_type not null default 'manual_seed',
    file_path text,                -- local/object-storage path to the downloaded file, if retained
    page_count int,
    publication_date date,
    fetched_at timestamptz not null default now(),
    unique (company_id, doc_type, reporting_period)
);
create index idx_documents_company on documents (company_id, doc_type);

-- 6. document_chunks ---------------------------------------------------------------
create table document_chunks (
    id uuid primary key default uuid_generate_v4(),
    document_id uuid not null references documents(id) on delete cascade,
    company_id uuid not null references companies(id) on delete cascade, -- denormalized for retrieval pre-filtering
    chunk_index int not null,
    text text not null,
    page_reference int,            -- original document page number, for citation (verified preservable — see fundamentals-access-spike.md §7)
    section_label text,
    embedding vector(1536),        -- dimension depends on the embedding model chosen; adjust before first real embedding run
    created_at timestamptz not null default now(),
    unique (document_id, chunk_index)
);
create index idx_chunks_company on document_chunks (company_id);
create index idx_chunks_embedding on document_chunks using ivfflat (embedding vector_cosine_ops);

-- 7. financial_metrics ---------------------------------------------------------------
create table financial_metrics (
    id uuid primary key default uuid_generate_v4(),
    company_id uuid not null references companies(id) on delete cascade,
    announcement_id uuid references announcements(id) on delete set null,
    period text not null,          -- e.g. 'Q2FY26'
    period_end_date date,
    revenue numeric,
    ebitda numeric,
    pbt numeric,
    pat numeric,
    currency text not null default 'INR',
    unit text not null default 'crore',  -- preserve the reporting unit explicitly
    extraction_source text not null default 'manual_seed' check (extraction_source in ('filing', 'screener', 'manual_seed')),
    created_at timestamptz not null default now(),
    unique (company_id, period)
);

-- 8. alerts_config ---------------------------------------------------------------
create table alerts_config (
    user_id uuid primary key references users(id) on delete cascade,
    volume_spike_multiple numeric not null default 2.0,
    price_move_pct numeric not null default 5.0,
    digest_window_hours int not null default 24,
    alert_categories announcement_category[] not null default array['results','M&A','management_change']::announcement_category[],
    updated_at timestamptz not null default now()
);

-- 9. alerts ---------------------------------------------------------------
create table alerts (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references users(id) on delete cascade,
    company_id uuid not null references companies(id) on delete cascade,
    trigger_type text not null check (trigger_type in ('volume_spike', 'price_move', 'material_announcement')),
    source_announcement_id uuid references announcements(id) on delete set null,
    source_price_id bigint references prices(id) on delete set null,
    payload jsonb not null default '{}'::jsonb,
    triggered_at timestamptz not null default now(),
    seen_at timestamptz
);
create index idx_alerts_user_triggered on alerts (user_id, triggered_at desc);

-- 10. ingestion_jobs ---------------------------------------------------------------
-- Audit trail of every ingestion run — live fetch attempt, manual seed load, etc. —
-- so it's always possible to answer "was this data actually fetched live, and when."
create table ingestion_jobs (
    id uuid primary key default uuid_generate_v4(),
    job_type text not null check (job_type in ('price_fetch', 'announcement_seed', 'fundamentals_fetch', 'fundamentals_seed')),
    company_id uuid references companies(id) on delete set null,
    status text not null check (status in ('success', 'partial', 'failed')),
    source data_source_type not null,
    records_affected int not null default 0,
    error_message text,
    started_at timestamptz not null default now(),
    finished_at timestamptz
);
create index idx_ingestion_jobs_company on ingestion_jobs (company_id, started_at desc);
