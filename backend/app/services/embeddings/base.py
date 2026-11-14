"""Embedding-provider abstraction. Every provider (local or API-based) implements
this interface; callers go through app.services.embeddings.get_embedding_provider()
and never import a concrete provider class directly, so adding a second provider
later never requires touching ingestion/retrieval code."""

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    name: str
    """Stable identifier for this provider+model, used as part of the cache key -
    changing it invalidates cached vectors, which is correct: a different model
    version can legitimately produce different embeddings for the same text."""

    dimension: int
    """Vector length this provider always returns. Must match the database
    column's vector(N) dimension exactly."""

    model_name: str
    """The underlying model identifier (e.g. "sentence-transformers/all-MiniLM-L6-v2"),
    recorded as document_chunks.embedding_model (migrations/007) for every chunk this
    provider embeds. A separate property from `name`, which also encodes the revision -
    never derived by splitting `name` at write time, so a future change to `name`'s
    format can't silently corrupt stored provenance."""

    model_revision: str
    """The exact pinned model revision (e.g. a Hugging Face commit SHA), recorded as
    document_chunks.embedding_model_revision. Never derived by splitting `name`."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Returns one embedding per input text, same order, each exactly
        `dimension` long. Must raise rather than return a fabricated/zero/random
        vector if the model can't produce a real one."""

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Returns the exact token count this provider's own tokenizer would produce
        for `text` - the real count used for chunking's soft/hard token limits, never
        an approximation (e.g. word count or char count / 4)."""
