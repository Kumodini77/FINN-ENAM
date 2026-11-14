from datetime import datetime, timezone

from app.models.announcement import Announcement, AnnouncementCategory
from app.repositories.announcements import AnnouncementRepository, new_announcement_id
from app.repositories.json_store import JsonListStore


def _make_repo(tmp_path):
    store = JsonListStore(str(tmp_path), "announcements.json")
    return AnnouncementRepository(store=store)


def _make_announcement(ticker="RELIANCE", url="https://example.com/filing1", title="Board meeting intimation"):
    now = datetime.now(timezone.utc)
    return Announcement(
        id=new_announcement_id(),
        company_ticker=ticker,
        filed_at=now,
        title=title,
        original_source_url=url,
        ingested_at=now,
    )


def test_add_new_announcement_is_created(tmp_path):
    repo = _make_repo(tmp_path)
    record, created = repo.add(_make_announcement())
    assert created is True
    assert len(repo.list_all()) == 1


def test_duplicate_same_company_and_url_is_rejected(tmp_path):
    repo = _make_repo(tmp_path)
    repo.add(_make_announcement(url="https://example.com/same"))
    _, created = repo.add(_make_announcement(url="https://example.com/same", title="Different title, same filing"))
    assert created is False
    assert len(repo.list_all()) == 1


def test_same_url_different_company_is_not_a_duplicate(tmp_path):
    repo = _make_repo(tmp_path)
    repo.add(_make_announcement(ticker="RELIANCE", url="https://example.com/shared"))
    _, created = repo.add(_make_announcement(ticker="TCS", url="https://example.com/shared"))
    assert created is True
    assert len(repo.list_all()) == 2


def test_missing_optional_fields_default_sensibly(tmp_path):
    repo = _make_repo(tmp_path)
    record, _ = repo.add(_make_announcement())
    assert record.category == AnnouncementCategory.UNCLASSIFIED
    assert record.document_url is None
    assert record.one_line_summary is None
    assert record.priority_score == 0.0


def test_persists_across_repository_instances(tmp_path):
    store = JsonListStore(str(tmp_path), "announcements.json")
    AnnouncementRepository(store=store).add(_make_announcement())
    # A second repository instance pointed at the same file must see the same data —
    # this is what "persistence" means for the JSON-fallback backend.
    reloaded = AnnouncementRepository(store=JsonListStore(str(tmp_path), "announcements.json"))
    assert len(reloaded.list_all()) == 1
