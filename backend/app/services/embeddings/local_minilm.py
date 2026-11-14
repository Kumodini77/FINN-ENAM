"""Local embedding provider: sentence-transformers' all-MiniLM-L6-v2, run entirely
on-device. No API key, no per-call cost, no network dependency after the model's
first-run download from Hugging Face has succeeded once.

Caching: a persistent on-disk cache keyed by sha256(model_name + text), so the same
chunk or query text is never re-embedded across process restarts - both ingestion
and query-time embedding go through this one class, so they're guaranteed to use
the exact same model and produce comparable vectors.
"""

import hashlib
import json
import logging
import threading
from pathlib import Path

from app.core.config import get_settings
from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.errors import EmbeddingModelUnavailableError

logger = logging.getLogger("finn.services.embeddings")

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Pinned to an exact, immutable Hugging Face commit SHA — "main" is a branch, not
# a fixed point, so pinning to "main" would let the weights change underneath this
# code without any visible signal here. This exact SHA was verified two ways
# before being hardcoded: (1) it is the real snapshot directory name this machine
# downloaded to its local HF cache on first use, and (2) it matches the "sha" field
# returned live by https://huggingface.co/api/models/sentence-transformers/all-MiniLM-L6-v2
# at the time this was pinned (both agreed exactly). It is part of the cache key
# below, so a future deliberate bump to a different SHA automatically invalidates
# old cache entries rather than silently mixing vectors from two revisions.
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
DIMENSION = 384


def _sanitize_for_filename(value: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in value)


class LocalMiniLMEmbeddingProvider(EmbeddingProvider):
    # Cache keys are derived from `name`, which encodes both model and revision —
    # two different models (or two revisions of the same model) can never collide
    # on a cache entry, because they never produce the same key.
    name = f"{MODEL_NAME}@{MODEL_REVISION}"
    dimension = DIMENSION
    model_name = MODEL_NAME
    model_revision = MODEL_REVISION

    _model = None
    _model_lock = threading.Lock()

    def __init__(self, cache_dir: str | None = None):
        settings = get_settings()
        # Filename itself also encodes the model identity, not just the key inside
        # it — so even a future second local provider writing to the same
        # directory gets its own file, never a shared one that could be read with
        # the wrong assumptions about what's inside it.
        filename = f"embedding_cache__{_sanitize_for_filename(self.name)}.json"
        self._cache_path = Path(cache_dir or settings.data_dir) / filename
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[float]] = self._load_cache()

    def _load_cache(self) -> dict[str, list[float]]:
        if self._cache_path.exists():
            try:
                return json.loads(self._cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Embedding cache at %s was unreadable; starting fresh.", self._cache_path)
        return {}

    def _save_cache(self) -> None:
        try:
            self._cache_path.write_text(json.dumps(self._cache), encoding="utf-8")
        except OSError:
            logger.warning("Could not persist embedding cache to %s", self._cache_path)

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.name}:{text}".encode("utf-8")).hexdigest()

    def _ensure_model_loaded(self) -> None:
        if LocalMiniLMEmbeddingProvider._model is not None:
            return
        with LocalMiniLMEmbeddingProvider._model_lock:
            if LocalMiniLMEmbeddingProvider._model is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise EmbeddingModelUnavailableError(
                    "sentence-transformers is not installed. Install it with "
                    "`pip install sentence-transformers` to enable local embeddings. "
                    "No embedding was generated."
                ) from e
            try:
                LocalMiniLMEmbeddingProvider._model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION)
            except Exception as e:
                raise EmbeddingModelUnavailableError(
                    f"Could not load the local embedding model '{MODEL_NAME}'. This usually "
                    "means its first-run download from Hugging Face failed (no network access, "
                    "or a Hugging Face outage) or the local model cache is corrupted. "
                    "No embedding was generated - nothing was fabricated as a substitute."
                ) from e

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        to_compute: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            cached = self._cache.get(self._key(text))
            if cached is not None:
                results[i] = cached
            else:
                to_compute.append((i, text))

        if to_compute:
            self._ensure_model_loaded()
            batch_texts = [t for _, t in to_compute]
            vectors = LocalMiniLMEmbeddingProvider._model.encode(
                batch_texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True
            )
            for (i, text), vector in zip(to_compute, vectors):
                vec_list = [float(x) for x in vector]
                if len(vec_list) != self.dimension:
                    raise EmbeddingModelUnavailableError(
                        f"'{MODEL_NAME}' returned {len(vec_list)} dimensions, expected {self.dimension}. "
                        "Refusing to store a mismatched vector."
                    )
                results[i] = vec_list
                self._cache[self._key(text)] = vec_list
            self._save_cache()

        return results  # type: ignore[return-value]

    def count_tokens(self, text: str) -> int:
        """Delegates to the exact tokenizer bundled inside the already-loaded
        SentenceTransformer model (model.tokenizer) - the same tokenizer `embed()`
        uses internally - rather than loading a second, independent tokenizer
        instance for chunking to call. Applied uniformly, including to an empty
        string (which still counts the tokenizer's own special tokens, e.g.
        [CLS]/[SEP]) - there is no special-cased shortcut for "".
        """
        self._ensure_model_loaded()
        return len(LocalMiniLMEmbeddingProvider._model.tokenizer.encode(text))
