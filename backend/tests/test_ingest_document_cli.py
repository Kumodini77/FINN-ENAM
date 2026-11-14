"""End-to-end tests for scripts/ingest_document.py's own argument handling, file
validation, and exit codes - with company resolution, the repository, and the
embedding provider all mocked/isolated, so this suite never touches a live Supabase
project or genuinely loads the MiniLM model."""

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import scripts.ingest_document as cli
from app.core.exceptions import DocumentAlreadyClaimedError, DocumentMetadataConflictError
from app.models.document import Document, IngestionStatus
from app.services.ingestion import IngestionError, IngestionResult


@pytest.fixture
def fake_pdf(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    return str(path)


def _base_argv(pdf_path, **overrides):
    argv = [
        "ingest_document.py",
        "--pdf", pdf_path,
        "--ticker", "RELIANCE",
        "--doc-type", "annual_report",
        "--source-url", "https://example.invalid/ar.pdf",
    ]
    for key, value in overrides.items():
        argv += [key, value]
    return argv


def test_help_exits_zero_without_loading_the_embedding_model(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ingest_document.py", "--help"])
    with patch("sentence_transformers.SentenceTransformer") as mock_cls:
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code == 0
    mock_cls.assert_not_called()


def test_missing_pdf_file_exits_nonzero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", _base_argv(str(tmp_path / "nope.pdf")))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code != 0
    assert "not found" in capsys.readouterr().out.lower()


def test_unsupported_file_extension_exits_nonzero_before_touching_anything(monkeypatch, tmp_path, capsys):
    bad_file = tmp_path / "notes.txt"
    bad_file.write_text("hello")
    monkeypatch.setattr(sys, "argv", _base_argv(str(bad_file)))
    with patch.object(cli, "get_or_register_company_id") as mock_resolve:
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code != 0
    assert "only .pdf files" in capsys.readouterr().out.lower()
    mock_resolve.assert_not_called()


def test_empty_pdf_file_is_rejected(monkeypatch, tmp_path, capsys):
    empty_file = tmp_path / "empty.pdf"
    empty_file.touch()
    monkeypatch.setattr(sys, "argv", _base_argv(str(empty_file)))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code != 0
    assert "empty" in capsys.readouterr().out.lower()


def test_invalid_doc_type_choice_is_rejected_by_argparse(monkeypatch, fake_pdf):
    monkeypatch.setattr(sys, "argv", _base_argv(fake_pdf, **{"--doc-type": "not_a_real_type"}))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code != 0


def test_missing_required_argument_is_rejected_by_argparse(monkeypatch, fake_pdf):
    argv = ["ingest_document.py", "--pdf", fake_pdf, "--doc-type", "annual_report", "--source-url", "https://x.invalid/a.pdf"]
    monkeypatch.setattr(sys, "argv", argv)  # missing --ticker
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code != 0


def test_unresolvable_ticker_exits_nonzero(monkeypatch, fake_pdf, capsys):
    monkeypatch.setattr(sys, "argv", _base_argv(fake_pdf))
    with patch.object(cli, "get_or_register_company_id", side_effect=Exception("yfinance lookup failed")):
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code != 0
    assert "could not resolve ticker" in capsys.readouterr().out.lower()


def test_duplicate_document_conflict_exits_with_code_2(monkeypatch, fake_pdf, capsys):
    monkeypatch.setattr(sys, "argv", _base_argv(fake_pdf))
    with patch.object(cli, "get_or_register_company_id", return_value="company-1"), \
         patch.object(cli, "DocumentRepository", return_value=MagicMock()), \
         patch.object(cli, "get_embedding_provider", return_value=MagicMock()), \
         patch.object(cli, "ingest_document", side_effect=DocumentMetadataConflictError("same file, different metadata")):
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code == 2
    assert "conflict" in capsys.readouterr().out.lower()


def test_already_claimed_conflict_exits_with_code_2(monkeypatch, fake_pdf, capsys):
    monkeypatch.setattr(sys, "argv", _base_argv(fake_pdf))
    with patch.object(cli, "get_or_register_company_id", return_value="company-1"), \
         patch.object(cli, "DocumentRepository", return_value=MagicMock()), \
         patch.object(cli, "get_embedding_provider", return_value=MagicMock()), \
         patch.object(cli, "ingest_document", side_effect=DocumentAlreadyClaimedError("already claimed")):
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code == 2


def test_ingestion_service_failure_exits_with_code_3(monkeypatch, fake_pdf, capsys):
    monkeypatch.setattr(sys, "argv", _base_argv(fake_pdf))
    with patch.object(cli, "get_or_register_company_id", return_value="company-1"), \
         patch.object(cli, "DocumentRepository", return_value=MagicMock()), \
         patch.object(cli, "get_embedding_provider", return_value=MagicMock()), \
         patch.object(cli, "ingest_document", side_effect=IngestionError("pdf extraction crashed")):
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code == 3
    assert "failed" in capsys.readouterr().out.lower()


def test_successful_ingestion_prints_success_and_exits_zero(monkeypatch, fake_pdf, capsys):
    doc = Document.model_validate(dict(
        id="doc-1", company_id="company-1", company_ticker="RELIANCE", doc_type="annual_report",
        original_source_url="https://example.invalid/ar.pdf", fetched_at=datetime.now(timezone.utc),
        ingestion_status=IngestionStatus.COMPLETED,
    ))
    monkeypatch.setattr(sys, "argv", _base_argv(fake_pdf))
    with patch.object(cli, "get_or_register_company_id", return_value="company-1"), \
         patch.object(cli, "DocumentRepository", return_value=MagicMock()), \
         patch.object(cli, "get_embedding_provider", return_value=MagicMock()), \
         patch.object(cli, "ingest_document", return_value=IngestionResult(document=doc, chunk_count=12, reused=False)):
        cli.main()  # does not call sys.exit on success
    out = capsys.readouterr().out
    assert "SUCCESS" in out
    assert "doc-1" in out
    assert "12" in out


def test_reused_already_completed_document_is_reported_distinctly(monkeypatch, fake_pdf, capsys):
    doc = Document.model_validate(dict(
        id="doc-1", company_id="company-1", company_ticker="RELIANCE", doc_type="annual_report",
        original_source_url="https://example.invalid/ar.pdf", fetched_at=datetime.now(timezone.utc),
        ingestion_status=IngestionStatus.COMPLETED,
    ))
    monkeypatch.setattr(sys, "argv", _base_argv(fake_pdf))
    with patch.object(cli, "get_or_register_company_id", return_value="company-1"), \
         patch.object(cli, "DocumentRepository", return_value=MagicMock()), \
         patch.object(cli, "get_embedding_provider", return_value=MagicMock()), \
         patch.object(cli, "ingest_document", return_value=IngestionResult(document=doc, chunk_count=12, reused=True)):
        cli.main()
    out = capsys.readouterr().out
    assert "ALREADY INGESTED" in out
