"""Supabase connectivity — attempted only when credentials are configured, and its
result is actually verified with a real query, never assumed from the presence of
an env var alone."""

import logging

from app.core.config import get_settings

logger = logging.getLogger("finn.db")

_client = None
_connection_verified: bool | None = None


def get_supabase_client():
    """Returns a supabase-py client if configured, else None. Does not verify
    connectivity by itself — call verify_supabase_connection() for that."""
    global _client
    settings = get_settings()
    if not settings.supabase_configured:
        return None
    if _client is None:
        from supabase import create_client

        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client


def verify_supabase_connection() -> bool:
    """Actually runs a lightweight query against the `companies` table. Returns False
    (not an exception) on any failure — used by /api/health so "connected" is never
    claimed without a real round trip having succeeded."""
    global _connection_verified
    client = get_supabase_client()
    if client is None:
        _connection_verified = False
        return False
    try:
        client.table("companies").select("ticker").limit(1).execute()
        _connection_verified = True
    except Exception:
        logger.exception("Supabase configured but connection check failed")
        _connection_verified = False
    return _connection_verified


def storage_backend_name() -> str:
    """'supabase' only if configured AND the connection actually verified; otherwise
    'json_fallback' — this is what every repository checks to decide where to read/write."""
    settings = get_settings()
    if settings.supabase_configured and verify_supabase_connection():
        return "supabase"
    return "json_fallback"
