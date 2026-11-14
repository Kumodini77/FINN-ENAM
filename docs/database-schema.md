# FINN — Database Schema (Supabase/Postgres + pgvector)

**Implementation status:** `001_init.sql`, `002_seed_companies.sql`, and `003_phase2_additions.sql` are applied to a live Supabase project. `004_phase2_schema_fixes.sql` is written and reviewed, not yet applied (see `backend/migrations/README.md` for exact instructions). The design below is mostly as originally proposed; where the live integration pass found a real mismatch between this design and the application code, it's called out inline rather than silently edited away.

**What a live integration test actually found (not assumed):** after connecting the backend to a real Supabase project, a direct insert/read-back/delete test against `announcements`, `financial_metrics`, and `alerts` failed outright — the repositories had been written using `company_ticker` (text) where the live schema has `company_id` (uuid FK, as designed below), `alerts` was missing a `trade_date` column, and `financial_metrics.id`/`alerts.id` were being built as human-readable strings instead of real UUIDs (both columns are typed `uuid`). The repository layer (`backend/app/repositories/`) now translates ticker↔company_id and injects a real `user_id` at the boundary — every Pydantic model and API schema above it is unchanged. Migration `004_phase2_schema_fixes.sql` adds the small set of schema pieces that correction needed (the `trade_date` column, ownership-and-trigger-type-aware unique indexes on `alerts`, a check constraint on which fields each alert trigger type requires, and a unique index on `users.email`). None of 001-003 were edited.

**Known residue, pending your confirmation to clean up:** before this mismatch was fixed, several test runs briefly lost their JSON-fallback test isolation (a separate bug, now fixed — see `backend/app/repositories/{announcements,financial_metrics,alerts}.py`'s `_force_json` handling) and wrote synthetic test rows into the live `announcements` (23 rows) and `financial_metrics` (3 rows) tables. No `alerts`, `alerts_config`, or `users` rows were affected (those inserts all failed outright, for unrelated reasons, before any row was written). I have not deleted these rows myself — a bulk delete against the live database was blocked by the environment's own safety gate as a destructive action requiring explicit sign-off. They are straightforward to identify (every one matches a test fixture pattern — `https://example.com/...` URLs, titles like "Mine"/"Not mine"/"Low, newest", period `Q9FY99`) and safe to delete; ask for this to be done, or run the deletes yourself, whenever convenient.

Field types below are Postgres-flavored; this was originally a proposed design and adjusted lightly during implementation where noted.

---

## Entity overview

```
companies ──< prices
companies ──< announcements ──< alerts
companies ──< financial_metrics
companies ──< documents ──< chunks (pgvector)
companies ──< research_outputs (cached Pull results)
users ──< user_config (thresholds, portfolio membership)
users ──< portfolio_companies >── companies
```

---

## Tables

### `companies`
Master list of tickers FINN knows about — not limited to the portfolio (ad-hoc/arbitrary NSE tickers get rows created lazily on first request).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `ticker` | text, unique | e.g. `RELIANCE.NS` |
| `name` | text | |
| `exchange` | text | `NSE` / `BSE` |
| `sector` | text | nullable |
| `is_seed_portfolio` | boolean | true for the 15–20 chosen portfolio companies |
| `created_at` | timestamptz | |

Index: unique on `ticker`.

---

### `prices`
EOD price/volume, one row per company per trading day.

| Column | Type | Notes |
|---|---|---|
| `id` | bigint, PK | |
| `company_id` | uuid, FK → companies | |
| `date` | date | |
| `open`, `high`, `low`, `close` | numeric | |
| `volume` | bigint | |
| `avg_volume_20d` | numeric | precomputed rolling baseline, used by anomaly engine |
| `pct_change_1d` | numeric | precomputed |

Index: unique on `(company_id, date)`; index on `date` for window queries.

---

### `announcements`
Raw corporate filings/announcements from NSE/BSE.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `company_id` | uuid, FK → companies | |
| `filed_at` | timestamptz | exchange filing timestamp |
| `title` | text | |
| `raw_source_url` | text | link to original filing/PDF |
| `category` | text | one of the 17 reference-doc categories (or `unclassified`) |
| `category_confidence` | numeric | from classifier, nullable |
| `one_line_summary` | text | nullable — not generated for every category (see requirements.md §6c) |
| `is_material` | boolean | derived from category + user config, used for alerting |
| `created_at` | timestamptz | ingestion time |

Indexes: `(company_id, filed_at desc)` for the windowed digest query; index on `category`.

Check constraint: `category` in the 17-value enum (or implemented as a Postgres `enum` type `announcement_category`).

---

### `financial_metrics`
Structured extraction from `results`-category filings — what powers the Push "headline numbers QoQ/YoY" feature.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `company_id` | uuid, FK → companies | |
| `announcement_id` | uuid, FK → announcements, nullable | source filing this was extracted from |
| `period` | text | e.g. `Q2FY26` |
| `period_end_date` | date | |
| `revenue` | numeric | |
| `ebitda` | numeric | |
| `pbt` | numeric | |
| `pat` | numeric | |
| `extraction_source` | text | `filing` / `screener` — provenance for debugging |
| `created_at` | timestamptz | |

Index: unique on `(company_id, period)`. QoQ/YoY are computed at query time by joining the previous/year-ago `period` row rather than stored redundantly.

---

### `alerts`
Triggered push notifications — both threshold-crossing and material-announcement types.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `company_id` | uuid, FK → companies | |
| `user_id` | uuid, FK → users | whose configured threshold fired |
| `trigger_type` | text | `volume_spike` / `price_move` / `material_announcement` |
| `source_announcement_id` | uuid, FK → announcements, nullable | set when trigger_type = material_announcement |
| `source_price_id` | bigint, FK → prices, nullable | set when trigger_type is volume/price |
| `payload` | jsonb | bespoke rendering data — e.g. management bio card, metrics table |
| `triggered_at` | timestamptz | |
| `seen_at` | timestamptz | nullable, for read/unread state |

Index: `(user_id, triggered_at desc)`.

---

### `documents`
Fundamentals source documents (annual reports, concall transcripts) — the RAG corpus.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `company_id` | uuid, FK → companies | |
| `doc_type` | text | `annual_report` / `concall_transcript` / `investor_presentation` |
| `period` | text | nullable, e.g. `FY2025` or `Q2FY26` |
| `source_url` | text | screener.in / IR site link |
| `fetched_at` | timestamptz | |
| `raw_text_available` | boolean | whether extraction succeeded |

Index: `(company_id, doc_type, period)`.

---

### `chunks`
Embedded text chunks of `documents`, for pgvector retrieval.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `document_id` | uuid, FK → documents | |
| `company_id` | uuid, FK → companies | denormalized for retrieval filtering without a join |
| `chunk_index` | int | ordering within document |
| `text` | text | |
| `embedding` | vector(N) | N = embedding model's dimension (model TBD) |
| `section_label` | text | nullable — e.g. "Q&A", "MD&A", page/section ref, used for citations |

Index: `ivfflat` or `hnsw` on `embedding`; btree on `company_id` for pre-filtering before vector search.

---

### `research_outputs`
Cache of generated Pull answers, keyed by company + output type, to avoid re-running RAG synthesis on repeat requests and to control LLM cost.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `company_id` | uuid, FK → companies | |
| `output_type` | text | one of the 8 menu items, e.g. `guidance_vs_actual` |
| `content` | jsonb | structured answer + citations |
| `source_chunk_ids` | uuid[] | provenance, for auditability of the primary-source-only rule |
| `generated_at` | timestamptz | |
| `stale_after` | timestamptz | invalidate when new filings/documents land |

Index: unique on `(company_id, output_type)` (latest wins; could instead keep history if we want to show "as of" versions — deferred decision).

---

### `users`
Minimal — this is a prototype, likely single-user or a handful of demo users, not multi-tenant auth at MVP scope.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `email` | text | nullable for prototype; Supabase auth can supply this later |
| `created_at` | timestamptz | |

---

### `portfolio_companies`
Join table: which companies are in a given user's portfolio (vs. ad-hoc research targets, which don't need a row here — any ticker is researchable via Pull).

| Column | Type | Notes |
|---|---|---|
| `user_id` | uuid, FK → users | |
| `company_id` | uuid, FK → companies | |
| `added_at` | timestamptz | |

PK: `(user_id, company_id)`.

---

### `user_config`
Per-user configurable alert thresholds (requirements.md §6b: "the point is I decide what 'unusual' means").

| Column | Type | Notes |
|---|---|---|
| `user_id` | uuid, FK → users, PK | |
| `volume_spike_multiple` | numeric | default 2.0 (≈2× recent average) |
| `price_move_pct` | numeric | default e.g. 5.0 (±X%/day) |
| `digest_window_hours` | int | default 24 |
| `alert_categories` | text[] | subset of the 17 categories the user wants triggered-alerted on |
| `updated_at` | timestamptz | |

---

## Notes on design choices

- **Why jsonb for `alerts.payload` and `research_outputs.content`:** these have category-dependent shapes (a metrics table vs. a bio card vs. a bull/bear writeup) — forcing them into rigid columns would mean constant schema churn as Pull output types are added/changed during the build.
- **Why `financial_metrics` is separate from `announcements`:** QoQ/YoY computation needs structured numeric rows to join against, not free text; keeping it separate also lets screener.in-sourced historical financials backfill the same table for trajectory/multi-year views (Pull item #3) without needing a matching announcement row.
- **Why denormalize `company_id` onto `chunks`:** vector search needs to pre-filter to one company's documents; joining through `documents` for every retrieval call is avoidable overhead.
- **pgvector dimension (`vector(N)`)** depends on the embedding model chosen — left as `N` pending that decision (see architecture.md open questions).
