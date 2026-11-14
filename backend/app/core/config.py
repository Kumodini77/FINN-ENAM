from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / .env.

    Nothing here has a hardcoded secret default — missing required values
    must be supplied via the environment, not assumed.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "FINN API"
    environment: str = "development"
    api_prefix: str = "/api"

    cors_allow_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    supabase_url: str | None = None
    supabase_key: str | None = None

    log_level: str = "INFO"

    market_data_eod_window_days: int = 20
    """Rolling window (trading days) used for average-volume baseline calculations."""

    data_dir: str = "data"
    """Where the JSON-file fallback store writes when Supabase isn't configured (Phase 2)."""

    anthropic_api_key: str | None = None
    """Optional. When unset, announcement classification runs rule-based only (Module 3)."""

    classification_llm_confidence_threshold: float = 0.6
    """Rule-based results at or above this confidence are trusted without an LLM call."""

    default_volume_spike_multiple: float = 2.0
    default_price_move_pct: float = 5.0
    default_digest_window_hours: int = 24

    embedding_provider: str = "local_minilm"
    """Which app.services.embeddings provider to use. Local-only by design (no paid
    API calls for embeddings) — see app/services/embeddings/ for the provider
    abstraction if a second option is ever added."""

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def llm_configured(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
