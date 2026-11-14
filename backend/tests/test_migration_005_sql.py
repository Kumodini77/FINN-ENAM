"""Structural tests for migrations/005_local_embeddings_dimension.sql.

There is no local Postgres+pgvector instance available in this environment (no
psycopg driver installed, and the migration must not be run against the live
Supabase project without explicit approval), so these tests verify the actual SQL
file on disk contains the branching logic each required database state depends
on — they prove the right logic is present, not that Postgres executes it exactly
as written. Live behavioral verification happens via the actual approved run,
same as every other migration in this project.
"""

from pathlib import Path

MIGRATION_PATH = Path(__file__).parent.parent / "migrations" / "005_local_embeddings_dimension.sql"


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _sql_without_comments() -> str:
    """Strips `--` comment lines so a mention in prose (e.g. explaining what this
    migration does NOT touch) can't be mistaken for an actual DDL reference."""
    lines = MIGRATION_PATH.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.strip().startswith("--"))


def test_migration_file_exists():
    assert MIGRATION_PATH.exists()


def test_takes_access_exclusive_lock_before_any_read():
    sql = _sql_without_comments()
    lower = sql.lower()
    assert "lock table public.document_chunks in access exclusive mode" in lower
    lock_pos = lower.index("lock table public.document_chunks in access exclusive mode")
    first_select_pos = lower.index("select atttypid")
    assert lock_pos < first_select_pos


def test_reads_actual_column_dimension_from_the_schema_qualified_catalog():
    sql = _sql()
    assert "pg_attribute" in sql
    assert "atttypmod" in sql
    assert "'public.document_chunks'::regclass" in sql


def test_verifies_column_type_via_pg_type_not_just_typmod():
    """A matching typmod alone must not be trusted as proof the column is
    pgvector's vector type — pg_type.typname must be checked independently."""
    sql = _sql()
    assert "atttypid" in sql
    assert "pg_type" in sql
    assert "typname" in sql
    assert "embedding_typname is distinct from 'vector'" in sql
    type_check_branch = sql.split("embedding_typname is distinct from 'vector'")[1].split("end if;")[0]
    assert "raise exception" in type_check_branch.lower()


def test_already_384_returns_before_inspecting_indexes_or_constraints():
    """The early-return for the already-correct dimension must come before any
    pg_index/pg_constraint inspection, so a future HNSW index added after this
    migration first runs can never cause a rerun to fail."""
    sql_lower = _sql_without_comments().lower()
    return_pos = sql_lower.index("if current_dim = 384")
    pg_index_pos = sql_lower.index("pg_index")
    pg_constraint_pos = sql_lower.index("pg_constraint")
    assert return_pos < pg_index_pos
    assert return_pos < pg_constraint_pos

    sql = _sql()
    no_op_branch = sql.split("current_dim = 384")[1].split("current_dim <> 1536")[0]
    assert "return" in no_op_branch
    assert "pg_index" not in no_op_branch
    assert "pg_constraint" not in no_op_branch
    assert "drop" not in no_op_branch.lower()
    assert "create index" not in no_op_branch.lower()


def test_unexpected_dimension_aborts_rather_than_guessing():
    sql = _sql()
    assert "current_dim <> 1536" in sql
    unexpected_branch = sql.split("current_dim <> 1536")[1].split("row_count")[0]
    assert "raise exception" in unexpected_branch.lower()


def test_non_empty_table_with_1536_aborts_before_any_dependency_check():
    """The emptiness check must happen, and abort, before indexes/constraints are
    even inspected on the 1536 path — dependency checks only matter once we know
    we're actually going to mutate the schema."""
    sql = _sql()
    assert "select count(*) into row_count from public.document_chunks" in sql
    assert "row_count > 0" in sql
    non_empty_branch = sql.split("row_count > 0")[1].split("end if;")[0]
    assert "raise exception" in non_empty_branch.lower()

    sql_lower = _sql_without_comments().lower()
    row_count_check_pos = sql_lower.index("row_count > 0")
    pg_index_pos = sql_lower.index("pg_index")
    assert row_count_check_pos < pg_index_pos


def test_enumerates_dependent_indexes_by_catalog_structure_not_by_name():
    sql = _sql()
    assert "pg_index" in sql
    assert "pg_am" in sql
    assert "amname" in sql
    assert "embedding_attnum = any(idx.indkey)" in sql
    assert "ivfflat" in sql.lower()
    assert "vector_cosine_ops" in sql.lower()


def test_checks_constraints_depending_on_the_embedding_column():
    sql = _sql()
    assert "pg_constraint" in sql
    assert "conkey" in sql
    assert "dependent_constraint_count > 0" in sql
    constraint_branch = sql.split("dependent_constraint_count > 0")[1].split("end if;")[0]
    assert "raise exception" in constraint_branch.lower()


def test_does_not_create_an_approximate_vector_index():
    """Deliberate decision: leave vector(384) without IVFFlat/HNSW for now."""
    sql_lower = _sql_without_comments().lower()
    assert "create index" not in sql_lower
    assert "using ivfflat" not in sql_lower
    assert "using hnsw" not in sql_lower


def test_never_drops_the_table_or_its_rows():
    sql_lower = _sql_without_comments().lower()
    assert "drop table" not in sql_lower
    assert "delete from" not in sql_lower
    assert "truncate" not in sql_lower


def test_only_touches_embedding_column_and_its_own_dependents():
    """idx_chunks_company and every other table must never appear as a DDL target
    in this migration — this is a static guarantee that the blast radius is
    exactly document_chunks.embedding and whatever is actually keyed on it."""
    sql = _sql_without_comments()
    assert "idx_chunks_company" not in sql
    for forbidden_table in ["announcements", "financial_metrics", "alerts", "companies", "users"]:
        assert f"alter table {forbidden_table}" not in sql.lower()
        assert f"drop table {forbidden_table}" not in sql.lower()


def test_migration_is_a_single_do_block_so_branching_logic_cannot_be_bypassed():
    sql = _sql()
    assert sql.count("do $$") == 1
    assert sql.count("end $$;") == 1
