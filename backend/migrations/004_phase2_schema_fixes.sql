-- FINN — Phase 2 Supabase integration fixes.
--
-- Context: migrations 001-003 were applied directly to the live Supabase project
-- via the SQL editor. A subsequent live integration test against that real database
-- (not assumed — see docs/database-schema.md) found that the Phase 2 repositories
-- (announcements, financial_metrics, alerts, alerts_config) were written against
-- the wrong column names/types for a few fields. This migration is purely additive:
-- it does not touch any column, constraint, or table created by 001, 002, or 003.
--
-- Status: NOT YET APPLIED. Run this manually in the Supabase SQL editor, after 001,
-- 002, and 003 (all three of which are already live). Safe to run on the existing
-- live data — every statement is idempotent (if not exists / on conflict do
-- nothing) and nothing here drops or weakens an existing table or constraint.

-- ---------------------------------------------------------------------------
-- 1. Single demo application user.
--
-- users (001_init.sql) is a plain app table, unrelated to Supabase Auth's
-- auth.users. alerts.user_id and alerts_config.user_id are NOT NULL foreign keys
-- into it, so a single-user prototype needs exactly one real row to point at —
-- never an invented UUID with nothing backing it. A unique index on email is
-- added so the app can create that one row idempotently (insert ... on conflict
-- do nothing), safe under concurrent calls: the database's own unique index
-- resolves the race, not any application-level locking.
--
-- Deliberately NOT a partial index (no "where email is not null"): Postgres
-- already exempts NULL from uniqueness checks on an ordinary unique index (NULL
-- is never considered equal to another NULL), so a partial predicate here would
-- add no real restriction — it would only break plain `on conflict (email)`
-- inference below, which requires an arbiter whose predicate (or absence of one)
-- matches exactly. A first attempt at this migration used the partial form and
-- failed live with 42P10 for exactly this reason; this is the corrected version.
create unique index if not exists idx_users_email on users (email);

insert into users (email)
values ('demo@finn.local')
on conflict (email) do nothing;

-- ---------------------------------------------------------------------------
-- 2. alerts.trade_date — the column the dedup logic needs but 001_init.sql never
-- added (it modeled this via source_price_id -> prices, a path that was never
-- wired up since market data is fetched live and never persisted to `prices`).
alter table alerts add column if not exists trade_date date;

-- Database-level enforcement of an invariant the application already guarantees
-- (app/services/alert_evaluation.py): a market alert (volume_spike/price_move)
-- always carries trade_date and never source_announcement_id; a
-- material_announcement alert always carries source_announcement_id and never
-- trade_date. Making this explicit at the DB level catches a future application
-- bug before bad data lands, rather than restricting anything the app doesn't
-- already do.
alter table alerts add constraint chk_alerts_trigger_fields check (
    (trigger_type in ('volume_spike', 'price_move')
        and trade_date is not null and source_announcement_id is null)
    or
    (trigger_type = 'material_announcement'
        and source_announcement_id is not null and trade_date is null)
);

-- ---------------------------------------------------------------------------
-- 3. alerts: database-level deduplication, scoped by ownership (user_id) as well
-- as company and trigger type — alerts.user_id exists but had no index backing
-- the dedup rule AlertRepository.exists() already enforces in Python. Two partial
-- unique indexes, since the two trigger-type families have different dedup keys:
create unique index if not exists idx_alerts_dedup_market
    on alerts (user_id, company_id, trigger_type, trade_date)
    where trigger_type in ('volume_spike', 'price_move');

create unique index if not exists idx_alerts_dedup_material
    on alerts (user_id, company_id, trigger_type, source_announcement_id)
    where trigger_type = 'material_announcement';
