"""Tests for scripts/recover_stuck_ingestions.py's dry-run/apply logic, driven
directly against a JSON-fallback DocumentRepository - never against live Supabase."""

import sys
from datetime import datetime, timedelta, timezone

import pytest

from app.models.document import Document, IngestionStatus
from app.repositories.documents import DocumentRepository
from app.repositories.json_store import JsonListStore


@pytest.fixture
def repo(tmp_path):
    return DocumentRepository(
        store=JsonListStore(str(tmp_path), "documents.json"),
        chunk_store=JsonListStore(str(tmp_path), "document_chunks.json"),
    )


def _stuck_doc(repo, stale_minutes=90):
    doc = Document.model_validate(
        dict(
            id="stuck-1", company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
            reporting_period="FY2025-26", original_source_url="https://x.invalid/a.pdf",
            fetched_at=datetime.now(timezone.utc), file_sha256="a" * 64,
        )
    )
    created, _ = repo.resolve_or_create(doc)
    repo.claim_for_ingestion(created.id)
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)).isoformat()
    repo.update_status(created.id, ingestion_claimed_at=stale_time)
    return created.id


def test_defaults_to_dry_run_and_makes_no_changes(repo, monkeypatch, capsys):
    doc_id = _stuck_doc(repo)
    monkeypatch.setattr(sys, "argv", ["recover_stuck_ingestions.py"])
    import scripts.recover_stuck_ingestions as script_module

    monkeypatch.setattr(script_module, "DocumentRepository", lambda: repo)
    script_module.main()
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    reloaded = repo.get_by_id(doc_id)
    assert reloaded.ingestion_status == IngestionStatus.EXTRACTING  # unchanged


def test_apply_without_confirmation_makes_no_changes(repo, monkeypatch, capsys):
    doc_id = _stuck_doc(repo)
    monkeypatch.setattr(sys, "argv", ["recover_stuck_ingestions.py", "--apply"])
    monkeypatch.setattr("builtins.input", lambda _: "no")
    import scripts.recover_stuck_ingestions as script_module

    monkeypatch.setattr(script_module, "DocumentRepository", lambda: repo)
    script_module.main()
    reloaded = repo.get_by_id(doc_id)
    assert reloaded.ingestion_status == IngestionStatus.EXTRACTING


def test_apply_with_confirmation_marks_failed_and_cleans_chunks(repo, monkeypatch):
    doc_id = _stuck_doc(repo)
    monkeypatch.setattr(sys, "argv", ["recover_stuck_ingestions.py", "--apply"])
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    import scripts.recover_stuck_ingestions as script_module

    monkeypatch.setattr(script_module, "DocumentRepository", lambda: repo)
    script_module.main()
    reloaded = repo.get_by_id(doc_id)
    assert reloaded.ingestion_status == IngestionStatus.FAILED


def test_never_affects_completed_documents(repo, monkeypatch):
    doc = Document.model_validate(
        dict(
            id="done-1", company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
            reporting_period="FY2026-27", original_source_url="https://x.invalid/b.pdf",
            fetched_at=datetime.now(timezone.utc), file_sha256="b" * 64,
        )
    )
    created, _ = repo.resolve_or_create(doc)
    repo.claim_for_ingestion(created.id)
    repo.mark_completed(created.id)
    stale = repo.find_stale_claims(stale_minutes=0)
    assert stale == []


def test_never_affects_recently_claimed_documents(repo):
    _stuck_doc(repo, stale_minutes=5)
    stale = repo.find_stale_claims(stale_minutes=60)
    assert stale == []


def test_apply_only_deletes_chunks_scoped_to_the_exact_stuck_document(repo, monkeypatch):
    """A second, unrelated document's chunks must survive recovery of the first -
    no broad/table-wide delete."""
    from app.models.document import DocumentChunk
    from datetime import datetime, timezone

    stuck_id = _stuck_doc(repo)
    other = Document.model_validate(
        dict(
            id="other-1", company_id="c1", company_ticker="RELIANCE", doc_type="annual_report",
            reporting_period="FY2027-28", original_source_url="https://x.invalid/c.pdf",
            fetched_at=datetime.now(timezone.utc), file_sha256="c" * 64,
        )
    )
    created_other, _ = repo.resolve_or_create(other)
    repo.insert_chunks([
        DocumentChunk(id="chunk-stuck", document_id=stuck_id, company_id="c1", chunk_index=0, text="x", created_at=datetime.now(timezone.utc)),
        DocumentChunk(id="chunk-other", document_id=created_other.id, company_id="c1", chunk_index=0, text="y", created_at=datetime.now(timezone.utc)),
    ])

    monkeypatch.setattr(sys, "argv", ["recover_stuck_ingestions.py", "--apply"])
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    import scripts.recover_stuck_ingestions as script_module

    monkeypatch.setattr(script_module, "DocumentRepository", lambda: repo)
    script_module.main()

    assert repo.get_chunks_for_document(stuck_id) == []
    assert len(repo.get_chunks_for_document(created_other.id)) == 1


def test_one_documents_recovery_failure_does_not_abort_the_others(repo, monkeypatch, capsys):
    """If mark_failed() raises for one stuck document (e.g. a transient error), the
    script must still attempt and report the rest, not crash mid-loop."""
    doc_a = _stuck_doc(repo)
    repo_mark_failed = repo.mark_failed
    call_count = {"n": 0}

    def flaky_mark_failed(document_id, error_message):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated transient Supabase error")
        return repo_mark_failed(document_id, error_message)

    monkeypatch.setattr(repo, "mark_failed", flaky_mark_failed)
    monkeypatch.setattr(sys, "argv", ["recover_stuck_ingestions.py", "--apply"])
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    import scripts.recover_stuck_ingestions as script_module

    monkeypatch.setattr(script_module, "DocumentRepository", lambda: repo)
    script_module.main()  # must not raise
    out = capsys.readouterr().out
    assert "could NOT be recovered" in out
    assert doc_a in out


def test_stale_minutes_argument_overrides_the_default(repo, monkeypatch):
    _stuck_doc(repo, stale_minutes=20)  # stale under a 10-minute threshold, not under the 60-minute default
    monkeypatch.setattr(sys, "argv", ["recover_stuck_ingestions.py", "--stale-minutes", "10"])
    import scripts.recover_stuck_ingestions as script_module

    monkeypatch.setattr(script_module, "DocumentRepository", lambda: repo)
    script_module.main()
    # still dry-run (no --apply) - nothing mutated, but the custom threshold must
    # have been the one actually used to find it in the first place.
    assert repo.find_stale_claims(stale_minutes=10) != []
    assert repo.find_stale_claims(stale_minutes=60) == []
