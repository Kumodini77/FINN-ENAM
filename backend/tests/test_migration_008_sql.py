"""Structural tests for migrations/008_retrieval_completed_documents_only.sql."""

from pathlib import Path

MIGRATION_PATH = Path(__file__).parent.parent / "migrations" / "008_retrieval_completed_documents_only.sql"


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


def test_precondition_guard_checks_migration_007_columns_before_dropping():
    sql_lower = _sql_without_comments().lower()
    drop_pos = sql_lower.index("drop function if exists public.match_document_chunks")
    assert "documents.ingestion_status (added by migrations/007)" in _sql()
    assert "document_chunks.chunk_type (added by migrations/007)" in _sql()
    assert "document_chunks.needs_manual_review (added by migrations/007)" in _sql()
    guard_pos = sql_lower.index("raise exception 'migrations/008 requires documents.ingestion_status")
    assert guard_pos < drop_pos


def test_drop_signature_matches_migration_006_parameter_types_in_order():
    sql_lower = _sql().lower()
    assert "drop function if exists public.match_document_chunks(public.vector(384), uuid, integer);" in sql_lower


def test_owner_is_captured_before_drop_and_restored_after_create():
    sql = _sql()
    drop_pos = sql.index("drop function if exists public.match_document_chunks")
    create_pos = sql.index("create function public.match_document_chunks")
    capture_pos = sql.index("_migration_008_owner_capture")
    restore_pos = sql.index("owner to %I")
    assert capture_pos < drop_pos < create_pos < restore_pos


def test_returns_table_includes_chunk_type_and_needs_manual_review_in_order():
    sql = _sql()
    returns_block = sql.split("returns table (")[1].split(")")[0]
    columns = [c.strip().split()[0] for c in returns_block.strip().split(",")]
    assert columns == [
        "chunk_id", "document_id", "company_id", "company_ticker", "chunk_text",
        "chunk_type", "needs_manual_review", "page_reference", "section_label",
        "doc_type", "reporting_period", "original_source_url", "distance", "similarity",
    ]


def test_select_list_order_matches_returns_table_order():
    sql = _sql()
    select_block = sql.split("return query\n    select\n")[1].split("from public.document_chunks")[0]
    select_exprs = [line.strip().rstrip(",") for line in select_block.strip().splitlines() if line.strip()]
    # First token of each select expr's alias/column should align positionally with RETURNS TABLE
    expected_order = [
        "chunk_id", "document_id", "company_id", "company_ticker", "chunk_text",
        "chunk_type", "needs_manual_review", "page_reference", "section_label",
        "doc_type", "reporting_period", "original_source_url", "distance", "similarity",
    ]
    assert len(select_exprs) == len(expected_order)
    for expr, expected in zip(select_exprs, expected_order):
        assert expected in expr


def test_security_invoker_and_empty_search_path():
    sql = _sql()
    assert "security invoker" in sql.lower()
    assert "set search_path = ''" in sql.lower()


def test_company_filter_and_consistency_check_retained():
    sql_lower = _sql_without_comments().lower()
    assert "dc.company_id = filter_company_id" in sql_lower
    assert "d.company_id = dc.company_id" in sql_lower


def test_restricts_to_completed_documents():
    sql_lower = _sql_without_comments().lower()
    assert "d.ingestion_status = 'completed'" in sql_lower


def test_company_filter_required_with_no_bypass():
    sql = _sql()
    assert "filter_company_id is null then" in sql
    branch = sql.split("filter_company_id is null then")[1].split("end if;")[0]
    assert "raise exception" in branch.lower()


def test_no_cascade_anywhere():
    sql_lower = _sql().lower()
    assert "cascade" not in sql_lower


def test_only_touches_match_document_chunks_function_and_its_own_temp_table():
    sql_lower = _sql_without_comments().lower()
    for forbidden_table in ["documents", "document_chunks", "companies", "announcements"]:
        assert f"drop table public.{forbidden_table}" not in sql_lower
        assert f"alter table public.{forbidden_table}" not in sql_lower


def test_revokes_then_grants_matching_migration_006_pattern():
    sql_lower = _sql().lower()
    assert "revoke all on function public.match_document_chunks" in sql_lower
    assert "from public;" in sql_lower
    assert "from anon;" in sql_lower
    assert "from authenticated;" in sql_lower
    assert "grant execute on function public.match_document_chunks" in sql_lower
    assert "to service_role;" in sql_lower


def test_notify_pgrst_present_before_commit():
    sql_lower = _sql_without_comments().lower()
    notify_pos = sql_lower.index("notify pgrst, 'reload schema';")
    commit_pos = sql_lower.rindex("commit;")
    assert notify_pos < commit_pos


def test_temp_table_is_on_commit_drop_not_a_persistent_object():
    sql_lower = _sql().lower()
    assert "create temporary table _migration_008_owner_capture" in sql_lower
    assert "on commit drop" in sql_lower
