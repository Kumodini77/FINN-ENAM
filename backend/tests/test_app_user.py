from unittest.mock import patch

import pytest

from app.repositories import app_user
from tests.fakes.fake_supabase import FakeSupabaseClient


@pytest.fixture(autouse=True)
def _reset_cache():
    app_user._reset_cache_for_tests()
    yield
    app_user._reset_cache_for_tests()


def test_first_call_creates_exactly_one_demo_user_row():
    client = FakeSupabaseClient()
    with patch.object(app_user, "get_supabase_client", return_value=client):
        user_id = app_user.get_app_user_id()
        assert user_id is not None
        rows = client.tables["users"]
        assert len(rows) == 1
        assert rows[0]["email"] == app_user.DEMO_USER_EMAIL


def test_repeat_calls_return_the_same_cached_id_without_a_second_row():
    client = FakeSupabaseClient()
    with patch.object(app_user, "get_supabase_client", return_value=client):
        id1 = app_user.get_app_user_id()
        id2 = app_user.get_app_user_id()
        assert id1 == id2
        assert len(client.tables["users"]) == 1


def test_resolution_is_stable_across_a_cold_cache_simulating_a_second_process():
    """Simulates two separate processes each calling get_app_user_id() for the
    first time: both reach the same single row via the upsert's on_conflict +
    ignore_duplicates idiom, never creating a second one."""
    client = FakeSupabaseClient()
    with patch.object(app_user, "get_supabase_client", return_value=client):
        id1 = app_user.get_app_user_id()
        app_user._reset_cache_for_tests()
        id2 = app_user.get_app_user_id()
        assert id1 == id2
        assert len(client.tables["users"]) == 1
