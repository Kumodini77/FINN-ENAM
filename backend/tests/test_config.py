"""Northflank deployment audit — CORS_ALLOW_ORIGINS parsing.

A real bug found live during the audit: pydantic-settings JSON-decodes any
env var for a list-typed field itself, before any field_validator runs — an
empty-string CORS_ALLOW_ORIGINS (an easy platform-config mistake) raised a
SettingsError and crashed the whole app at startup. Fixed with `NoDecode` +
a validator that treats blank as "use the default" instead of a fatal parse
error (see app.core.config.Settings.cors_allow_origins).
"""

from app.core.config import Settings


def test_unset_cors_env_uses_the_localhost_default(monkeypatch):
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.cors_allow_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_blank_cors_env_does_not_crash_startup(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "")
    settings = Settings(_env_file=None)
    assert settings.cors_allow_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_real_json_array_cors_env_is_parsed_correctly(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", '["https://finn-enam-rho.vercel.app","http://localhost:3000"]')
    settings = Settings(_env_file=None)
    assert settings.cors_allow_origins == ["https://finn-enam-rho.vercel.app", "http://localhost:3000"]


def test_single_origin_json_array_cors_env(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", '["https://finn-enam-rho.vercel.app"]')
    settings = Settings(_env_file=None)
    assert settings.cors_allow_origins == ["https://finn-enam-rho.vercel.app"]
