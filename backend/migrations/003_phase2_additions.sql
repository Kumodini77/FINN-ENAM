-- Phase 2 (Push engine) additive schema changes.
-- Status: NOT APPLIED to any live database — same as 001/002 (see migrations/README.md).
-- These are additive-only (new nullable/defaulted columns); nothing in 001_init.sql's
-- existing tables/columns is removed or renamed, so this is safe to run after 001+002
-- whenever a Supabase project is actually provisioned.

-- announcements: separate the filing's own fact (title) from FINN's interpretation
-- (why_it_matters), track classification provenance, and support the priority engine.
alter table announcements
    add column if not exists document_url text,
    add column if not exists verification_status text not null default 'unverified'
        check (verification_status in ('verified', 'unverified')),
    add column if not exists why_it_matters text,
    add column if not exists priority text not null default 'low'
        check (priority in ('high', 'medium', 'low')),
    add column if not exists priority_score numeric not null default 0,
    add column if not exists classification_method text not null default 'fallback_unclassified'
        check (classification_method in ('rule_based', 'llm', 'fallback_unclassified', 'manual')),
    add column if not exists classification_evidence jsonb not null default '[]'::jsonb;

-- Application-level dedup key: (company, original_source_url). Enforced as a DB
-- constraint here for when this is wired to a live Postgres; the JSON-fallback
-- repository (app/repositories/announcements.py) enforces the same rule in Python
-- today, since no live database is connected yet.
create unique index if not exists idx_announcements_company_source_url
    on announcements (company_id, original_source_url);

-- financial_metrics: standalone vs consolidated must never be silently mixed when
-- computing QoQ/YoY (docs/requirements.md Module 5 — "same financial basis compared").
alter table financial_metrics
    add column if not exists basis text not null default 'standalone'
        check (basis in ('standalone', 'consolidated')),
    add column if not exists source_document_url text,
    add column if not exists source_page_number int,
    add column if not exists extraction_confidence numeric;

-- A company can have both a standalone and a consolidated row for the same period —
-- the original unique(company_id, period) from 001_init.sql is too narrow once basis
-- is tracked explicitly.
alter table financial_metrics drop constraint if exists financial_metrics_company_id_period_key;
create unique index if not exists idx_financial_metrics_company_period_basis
    on financial_metrics (company_id, period, basis);
