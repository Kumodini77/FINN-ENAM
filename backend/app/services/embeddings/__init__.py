"""Public entry point for embeddings. Callers must use get_embedding_provider()
rather than importing a concrete provider class - that's the one place a future
provider gets wired in, per the configured EMBEDDING_PROVIDER setting."""

from app.core.config import get_settings
from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.errors import EmbeddingModelUnavailableError
from app.services.embeddings.local_minilm import LocalMiniLMEmbeddingProvider

_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        settings = get_settings()
        name = settings.embedding_provider
        if name == "local_minilm":
            _provider = LocalMiniLMEmbeddingProvider()
        else:
            raise ValueError(f"Unknown embedding provider: {name!r}")
    return _provider


def reset_embedding_provider_for_tests() -> None:
    """Test-only: clears the cached provider instance so tests can swap settings
    or inject a fresh instance without leaking state between them."""
    global _provider
    _provider = None


__all__ = [
    "EmbeddingProvider",
    "EmbeddingModelUnavailableError",
    "get_embedding_provider",
    "reset_embedding_provider_for_tests",
]
