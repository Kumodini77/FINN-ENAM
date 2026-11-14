"""The single demo application user for this prototype.

This is NOT a Supabase Auth account — `users` (migrations/001_init.sql) is a plain
application table, unrelated to `auth.users`. The alerts and alerts_config tables'
user_id foreign key requires a real row to point at; this module creates exactly one,
idempotently, rather than inventing a UUID with nothing backing it.

Concurrency: the create-if-absent operation is atomic at the database level (an
upsert against a unique index on users.email, with ignore_duplicates=True — see
migrations/004_phase2_schema_fixes.sql), so two processes calling get_app_user_id()
at the same time cannot create two rows; the database's unique index is the lock,
not any Python-level coordination.
"""

import threading

from app.core.db import get_supabase_client

DEMO_USER_EMAIL = "demo@finn.local"

_lock = threading.Lock()
_cached_id: str | None = None


def get_app_user_id() -> str:
    """Returns the single demo user's id, creating that one row the first time it's
    needed. Cached in-process after the first successful resolution — the row never
    changes once created, so repeated network round trips would be pure waste."""
    global _cached_id
    if _cached_id is not None:
        return _cached_id

    client = get_supabase_client()
    client.table("users").upsert(
        {"email": DEMO_USER_EMAIL}, on_conflict="email", ignore_duplicates=True
    ).execute()
    resp = client.table("users").select("id").eq("email", DEMO_USER_EMAIL).limit(1).execute()

    with _lock:
        _cached_id = resp.data[0]["id"]
    return _cached_id


def _reset_cache_for_tests() -> None:
    """Test-only: clears the in-process cache so a mocked client can be exercised
    fresh in each test rather than leaking the previous test's cached id."""
    global _cached_id
    _cached_id = None
