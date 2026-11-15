import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / .env.

    Nothing here has a hardcoded secret default — missing required values
    must be supplied via the environment, not assumed.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "FINN API"
    environment: str = "development"
    api_prefix: str = "/api"

    cors_allow_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    """Production override: CORS_ALLOW_ORIGINS as a JSON array, e.g.
    '["https://finn-enam-rho.vercel.app","http://localhost:3000"]' — a real
    deployed frontend origin must be added here or the browser will block it.
    `NoDecode` is required here: pydantic-settings otherwise JSON-decodes any
    env var for a list field itself, BEFORE any field_validator runs — found
    live, an empty-string env var (a real, easy platform-config mistake) would
    raise a SettingsError and crash the whole app at startup. With NoDecode,
    the validator below gets the raw string and can treat blank as "use the
    default" instead of a fatal parse error."""

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value):
        if isinstance(value, str):
            if not value.strip():
                return ["http://localhost:3000", "http://127.0.0.1:3000"]
            return json.loads(value)
        return value

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

    admin_api_token: str | None = None
    """Shared-secret header value (X-Admin-Token) required by /api/admin/* routes.
    When unset, those routes refuse all requests (503) rather than being left open —
    see app/api/admin.py. No default/baked-in value, per the no-hardcoded-secret rule
    at the top of this file."""

    enable_market_data_scheduler: bool = False
    """Whether app.main starts the in-process APScheduler for the EOD market-data
    refresh job on app startup. Off by default — see docs/FINN_PHASE_12A_REPORT.md
    for why an in-process scheduler alone is not a durable production mechanism on a
    dyno that can idle/restart, and for the recommended external-cron alternative
    (scripts/run_market_data_refresh.py)."""

    market_data_refresh_cron: str = "0 18 * * 1-5"
    """Standard 5-field cron expression (minute hour day month weekday), interpreted
    in Asia/Kolkata. Default 18:00 IST Mon-Fri — well after NSE's 15:30 IST close,
    giving yfinance's own upstream time to finalize the day's EOD bar."""

    enable_document_discovery_scheduler: bool = False
    """Same in-process-vs-external-cron tradeoff as enable_market_data_scheduler
    (see docs/FINN_PHASE_12A_REPORT.md §4) — off by default."""

    document_discovery_cron: str = "30 19 * * 1-5"
    """Default 19:30 IST Mon-Fri — after the market-data refresh's default slot,
    so the two scheduled jobs don't compete for the same minute."""

    document_discovery_max_new_docs_per_company: int = 6
    """Backfill limit per company per run — enough for ~4 recent quarters'
    transcripts plus 1-2 recent annual reports, never an unbounded archive
    download (see Phase 12B's own instruction against indiscriminate backfill)."""

    document_discovery_lookback_quarters: int = 4
    """How many of the most recent concall/transcript periods to consider per
    company — matches the 'four-quarter comparison' need called out in the
    Phase 12B brief, not an arbitrary number."""

    enable_announcement_discovery_scheduler: bool = False
    """Same in-process-vs-external-cron tradeoff as the other two schedulers
    (see docs/FINN_PHASE_12A_REPORT.md §4) — off by default."""

    announcement_discovery_cron: str = "0 17 * * 1-5"
    """Default 17:00 IST Mon-Fri — before the market-data (18:00) and document
    (19:30) slots, so announcements (typically same-day news) surface first."""

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def llm_configured(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
