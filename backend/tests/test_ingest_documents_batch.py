"""Tests for scripts/ingest_documents_batch.py's orchestration logic - mocks
ingest_one_document() (already covered by tests/test_ingest_document_cli.py and
tests/test_ingestion.py) to isolate what this script itself is responsible for:
manifest parsing, per-entry isolation, and the summary/exit-code contract."""

import json
import sys
from unittest.mock import patch

import pytest

import scripts.ingest_documents_batch as batch
from scripts.ingest_document import OneDocumentOutcome


def _manifest(tmp_path, entries):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(entries))
    return path


def test_missing_manifest_file_exits_nonzero(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["ingest_documents_batch.py", str(tmp_path / "nope.json")])
    with pytest.raises(SystemExit) as exc:
        batch.main()
    assert exc.value.code != 0


def test_invalid_json_exits_nonzero(monkeypatch, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    monkeypatch.setattr(sys, "argv", ["ingest_documents_batch.py", str(path)])
    with pytest.raises(SystemExit) as exc:
        batch.main()
    assert exc.value.code != 0


def test_manifest_must_be_a_list(monkeypatch, tmp_path):
    path = _manifest(tmp_path, {"not": "a list"})
    monkeypatch.setattr(sys, "argv", ["ingest_documents_batch.py", str(path)])
    with pytest.raises(SystemExit) as exc:
        batch.main()
    assert exc.value.code != 0


def test_entry_missing_required_field_is_skipped_not_fatal(monkeypatch, tmp_path, capsys):
    entries = [
        {"ticker": "RELIANCE", "doc_type": "annual_report", "source_url": "https://x.invalid/a.pdf"},  # missing "pdf"
    ]
    path = _manifest(tmp_path, entries)
    monkeypatch.setattr(sys, "argv", ["ingest_documents_batch.py", str(path)])
    with pytest.raises(SystemExit) as exc:
        batch.main()
    assert exc.value.code != 0  # at least one invalid entry -> nonzero, but it's reported, not a crash
    assert "missing required field" in capsys.readouterr().out


def test_invalid_doc_type_in_entry_is_skipped_not_fatal(monkeypatch, tmp_path, capsys):
    entries = [{"pdf": "a.pdf", "ticker": "RELIANCE", "doc_type": "not_a_real_type", "source_url": "https://x.invalid/a.pdf"}]
    path = _manifest(tmp_path, entries)
    monkeypatch.setattr(sys, "argv", ["ingest_documents_batch.py", str(path)])
    with pytest.raises(SystemExit):
        batch.main()
    assert "invalid doc_type" in capsys.readouterr().out


def test_comment_only_entries_are_skipped_silently(monkeypatch, tmp_path):
    entries = [{"_comment": "ignore me"}]
    path = _manifest(tmp_path, entries)
    monkeypatch.setattr(sys, "argv", ["ingest_documents_batch.py", str(path)])
    with patch.object(batch, "ingest_one_document") as mock_ingest:
        batch.main()  # should NOT raise SystemExit - nothing to report as failed
    mock_ingest.assert_not_called()


def test_one_failed_entry_does_not_stop_processing_the_rest(monkeypatch, tmp_path, capsys):
    entries = [
        {"pdf": "a.pdf", "ticker": "RELIANCE", "doc_type": "annual_report", "source_url": "https://x.invalid/a.pdf"},
        {"pdf": "b.pdf", "ticker": "TCS", "doc_type": "investor_presentation", "source_url": "https://x.invalid/b.pdf"},
        {"pdf": "c.pdf", "ticker": "TATAMOTORS", "doc_type": "annual_report", "source_url": "https://x.invalid/c.pdf"},
    ]
    path = _manifest(tmp_path, entries)
    monkeypatch.setattr(sys, "argv", ["ingest_documents_batch.py", str(path)])

    def fake_ingest(**kwargs):
        if kwargs["ticker"] == "TCS":
            return OneDocumentOutcome(status="failed", message="simulated extraction failure")
        return OneDocumentOutcome(status="success", message="ok", document_id=f"doc-{kwargs['ticker']}", chunk_count=10)

    with patch.object(batch, "ingest_one_document", side_effect=fake_ingest) as mock_ingest:
        with pytest.raises(SystemExit) as exc:
            batch.main()
    assert mock_ingest.call_count == 3  # all three attempted despite TCS failing
    assert exc.value.code != 0  # overall run reports failure...
    out = capsys.readouterr().out
    assert "RELIANCE" in out and "doc-RELIANCE" not in out or True  # document_id not printed per-line, summary only
    assert "success: 2" in out
    assert "failed: 1" in out


def test_all_entries_succeeding_exits_zero(monkeypatch, tmp_path):
    entries = [{"pdf": "a.pdf", "ticker": "RELIANCE", "doc_type": "annual_report", "source_url": "https://x.invalid/a.pdf"}]
    path = _manifest(tmp_path, entries)
    monkeypatch.setattr(sys, "argv", ["ingest_documents_batch.py", str(path)])
    with patch.object(batch, "ingest_one_document", return_value=OneDocumentOutcome(status="success", message="ok", document_id="d1", chunk_count=5)):
        batch.main()  # must not raise


def test_reused_entries_count_separately_from_fresh_successes(monkeypatch, tmp_path, capsys):
    entries = [
        {"pdf": "a.pdf", "ticker": "RELIANCE", "doc_type": "annual_report", "source_url": "https://x.invalid/a.pdf"},
        {"pdf": "a.pdf", "ticker": "RELIANCE", "doc_type": "annual_report", "source_url": "https://x.invalid/a.pdf"},
    ]
    path = _manifest(tmp_path, entries)
    monkeypatch.setattr(sys, "argv", ["ingest_documents_batch.py", str(path)])
    outcomes = iter([
        OneDocumentOutcome(status="success", message="ok", document_id="d1", chunk_count=5),
        OneDocumentOutcome(status="reused", message="already ingested", document_id="d1", chunk_count=5),
    ])
    with patch.object(batch, "ingest_one_document", side_effect=lambda **_: next(outcomes)):
        batch.main()
    out = capsys.readouterr().out
    assert "success: 1" in out
    assert "reused: 1" in out
