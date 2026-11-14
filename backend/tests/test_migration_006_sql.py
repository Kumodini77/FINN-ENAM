"""Structural tests for migrations/006_vector_similarity_search_rpc.sql.

Same approach as test_migration_005_sql.py: no local Postgres+pgvector instance is
available, and this migration must not run against live Supabase without explicit
approval, so these tests verify the actual SQL file on disk contains the required
logic. They prove the right logic is present, not that Postgres executes it exactly
as written - live verification happens via the actual approved run.
"""

from pathlib import Path

MIGRATION_PATH = Path(__file__).parent.parent / "migrations" / "006_vector_similarity_search_rpc.sql"


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _sql_without_comments() -> str:
    lines = MIGRATION_PATH.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.strip().startswith("--"))


def test_migration_file_exists():
    assert MIGRATION_PATH.exists()


def test_function_signature_matches_required_parameters():
    sql = _sql()
    assert "query_embedding public.vector(384)" in sql
    assert "filter_company_id uuid" in sql
    assert "match_count integer default 5" in sql


def test_filter_company_id_is_required_with_no_bypass():
    sql = _sql()
    assert "filter_company_id is null then" in sql
    branch = sql.split("filter_company_id is null then")[1].split("end if;")[0]
    assert "raise exception" in branch.lower()


def test_explicit_null_match_count_is_rejected_not_silently_defaulted():
    """Correction 2: an explicitly-passed NULL match_count must raise, not be
    coerced to 5 - only an OMITTED argument should reach the SQL-level default."""
    sql = _sql()
    assert "match_count is null then" in sql
    null_branch = sql.split("match_count is null then")[1].split("elsif")[0]
    assert "raise exception" in null_branch.lower()
    assert ":= 5" not in null_branch
    assert "effective_match_count := 5" not in sql


def test_omitted_match_count_defaults_to_five_via_sql_default_not_plpgsql():
    """The default must live in the function signature (`default 5`), which Postgres
    only substitutes when the argument is omitted - never in the NULL-handling branch."""
    sql = _sql()
    assert "match_count integer default 5" in sql


def test_match_count_below_one_is_rejected():
    sql = _sql()
    assert "match_count < 1 then" in sql
    branch = sql.split("match_count < 1 then")[1].split("else")[0]
    assert "raise exception" in branch.lower()


def test_match_count_above_cap_is_clamped_to_twenty():
    sql = _sql()
    assert "least(match_count, 20)" in sql


def test_query_embedding_null_is_rejected():
    sql = _sql()
    assert "query_embedding is null then" in sql
    branch = sql.split("query_embedding is null then")[1].split("end if;")[0]
    assert "raise exception" in branch.lower()


def test_chunk_and_parent_document_company_consistency_is_enforced():
    """Correction 1: dc.company_id = filter_company_id alone is not enough - the
    chunk's own company_id and its parent document's company_id must also agree,
    so no cross-company source document's citation metadata can ever be returned."""
    sql = _sql_without_comments()
    assert "dc.company_id = filter_company_id" in sql
    assert "d.company_id = dc.company_id" in sql


def test_company_filter_applied_in_where_before_order_and_limit():
    sql_lower = _sql_without_comments().lower()
    where_pos = sql_lower.index("where dc.company_id = filter_company_id")
    order_pos = sql_lower.index("order by")
    limit_pos = sql_lower.index("limit effective_match_count")
    assert where_pos < order_pos < limit_pos


def test_orders_by_cosine_distance_operator_directly():
    sql = _sql()
    assert "order by dc.embedding operator(public.<=>) query_embedding" in sql.lower()


def test_returns_citation_metadata_columns_without_inventing_any():
    sql = _sql()
    required_columns = [
        "chunk_id", "document_id", "company_id", "company_ticker", "chunk_text",
        "page_reference", "section_label", "doc_type", "reporting_period",
        "original_source_url", "distance", "similarity",
    ]
    for col in required_columns:
        assert col in sql


def test_distance_and_similarity_both_use_the_schema_qualified_operator():
    sql = _sql()
    assert sql.count("OPERATOR(public.<=>)") >= 2


def test_security_invoker_and_empty_search_path():
    sql = _sql()
    assert "security invoker" in sql.lower()
    assert "set search_path = ''" in sql.lower()


def test_revokes_execute_from_public_anon_and_authenticated():
    sql_lower = _sql().lower()
    assert "revoke all on function public.match_document_chunks" in sql_lower
    assert "from public;" in sql_lower
    assert "from anon;" in sql_lower
    assert "from authenticated;" in sql_lower


def test_grants_execute_only_to_service_role():
    sql_lower = _sql().lower()
    assert "grant execute on function public.match_document_chunks" in sql_lower
    assert "to service_role;" in sql_lower
    assert "to anon;" not in sql_lower
    assert "to authenticated;" not in sql_lower


def test_does_not_touch_rls_or_unrelated_tables():
    sql_lower = _sql_without_comments().lower()
    assert "row level security" not in sql_lower
    assert "enable row level security" not in sql_lower
    assert "disable row level security" not in sql_lower
    for forbidden_table in ["announcements", "financial_metrics", "alerts", "users"]:
        assert f"alter table {forbidden_table}" not in sql_lower
        assert f"drop table {forbidden_table}" not in sql_lower


def test_does_not_drop_or_recreate_documents_or_document_chunks_tables():
    sql_lower = _sql_without_comments().lower()
    assert "drop table public.documents" not in sql_lower
    assert "drop table public.document_chunks" not in sql_lower
    assert "create table" not in sql_lower


def test_function_is_idempotent_via_create_or_replace():
    sql_lower = _sql().lower()
    assert "create or replace function public.match_document_chunks" in sql_lower


def test_notifies_postgrest_to_reload_schema_after_grants():
    """PostgREST caches its schema at startup and won't notice the new function
    without this - and it must come after the function/grants are established,
    not before."""
    sql_lower = _sql_without_comments().lower()
    assert "notify pgrst, 'reload schema';" in sql_lower
    grant_pos = sql_lower.index("grant execute on function public.match_document_chunks")
    notify_pos = sql_lower.index("notify pgrst, 'reload schema';")
    assert grant_pos < notify_pos
