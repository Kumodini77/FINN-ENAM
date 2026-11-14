"""Structural tests for migrations/007_document_ingestion_tracking.sql. Same
approach as test_migration_006_sql.py: no live Postgres instance is available, so
these verify the SQL file on disk, not an executed result."""

from pathlib import Path

MIGRATION_PATH = Path(__file__).parent.parent / "migrations" / "007_document_ingestion_tracking.sql"


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _sql_without_comments() -> str:
    lines = MIGRATION_PATH.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.strip().startswith("--"))


def test_migration_file_exists():
    assert MIGRATION_PATH.exists()


def test_wrapped_in_explicit_transaction():
    sql_lower = _sql_without_comments().lower()
    assert sql_lower.strip().startswith("begin;")
    assert sql_lower.strip().endswith("commit;")


def test_documents_columns_added_with_if_not_exists():
    sql = _sql()
    for column in ["file_sha256 text", "ingestion_error text", "ingested_at timestamptz", "ingestion_claimed_at timestamptz"]:
        assert f"add column if not exists {column}" in sql
    assert "add column if not exists ingestion_status text not null default 'pending'" in sql


def test_document_chunks_columns_added_with_if_not_exists():
    sql = _sql()
    assert "add column if not exists embedding_model text" in sql
    assert "add column if not exists embedding_model_revision text" in sql
    assert "add column if not exists chunk_type text not null default 'prose'" in sql
    assert "add column if not exists needs_manual_review boolean not null default false" in sql


def test_column_type_and_nullability_are_verified_not_assumed():
    """Correction: an existing column with the wrong type/nullability must raise,
    not be silently treated as 'already migrated'."""
    sql = _sql()
    assert sql.count("does not match the expected type") >= 2
    assert "information_schema.columns" in sql


def test_ingestion_status_check_has_exactly_six_states():
    sql = _sql()
    assert "check (ingestion_status in ('pending', 'extracting', 'chunking', 'embedding', 'completed', 'failed'))" in sql


def test_ingestion_status_constraint_definition_is_verified_if_preexisting():
    sql = _sql()
    assert "pg_get_constraintdef" in sql
    assert "documents_ingestion_status_check" in sql
    assert "does not include the expected state" in sql


def test_chunk_type_check_allows_exactly_three_values():
    sql = _sql()
    assert "check (chunk_type in ('prose', 'table_row_group', 'table_unparsed'))" in sql


def test_needs_manual_review_is_not_null_boolean_with_default_false():
    sql = _sql()
    assert "needs_manual_review boolean not null default false" in sql


def test_embedding_model_and_revision_both_required_when_embedding_present():
    sql_lower = _sql_without_comments().lower()
    assert "check (embedding is null or (embedding_model is not null and embedding_model_revision is not null))" in sql_lower


def test_table_unparsed_requires_needs_manual_review():
    sql_lower = _sql_without_comments().lower()
    assert "check (chunk_type <> 'table_unparsed' or needs_manual_review)" in sql_lower


def test_constraint_additions_are_guarded_not_unconditional():
    sql = _sql()
    assert sql.count("do $$") >= 5  # 2 type-verification blocks + 3+ constraint blocks


def test_indexes_use_if_not_exists():
    sql = _sql()
    assert "create unique index if not exists idx_documents_file_sha256" in sql
    assert "create index if not exists idx_documents_ingestion_status" in sql
    assert "create index if not exists idx_documents_ingestion_claimed_at" in sql


def test_no_destructive_operations():
    sql_lower = _sql_without_comments().lower()
    for forbidden in ["drop table", "drop column", "alter column", "truncate", "delete from", "cascade"]:
        assert forbidden not in sql_lower


def test_does_not_touch_unrelated_tables():
    sql_lower = _sql_without_comments().lower()
    for forbidden_table in ["announcements", "financial_metrics", "alerts", "users", "companies"]:
        assert f"alter table public.{forbidden_table}" not in sql_lower


def test_only_touches_documents_and_document_chunks():
    sql_lower = _sql_without_comments().lower()
    assert "alter table public.documents" in sql_lower
    assert "alter table public.document_chunks" in sql_lower
