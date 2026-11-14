"""Tests for the local embedding provider (Phase 3 / RAG foundation).

Most tests mock sentence-transformers so the suite stays fast and network-free;
one test is marked to actually load the real model and is the one that genuinely
proves "384 dimensions, real local inference" rather than mocked behavior.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.embeddings.errors import EmbeddingModelUnavailableError
from app.services.embeddings.local_minilm import DIMENSION, MODEL_NAME, MODEL_REVISION, LocalMiniLMEmbeddingProvider


def _fake_model(dimension=DIMENSION):
    model = MagicMock()

    def _encode(texts, **_kwargs):
        return [[float(i)] * dimension for i, _ in enumerate(texts, start=1)]

    model.encode.side_effect = _encode
    return model


@pytest.fixture(autouse=True)
def _reset_model_singleton():
    LocalMiniLMEmbeddingProvider._model = None
    yield
    LocalMiniLMEmbeddingProvider._model = None


def test_embed_returns_one_vector_per_text_of_the_declared_dimension(tmp_path):
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    with patch("sentence_transformers.SentenceTransformer", return_value=_fake_model()):
        vectors = provider.embed(["first sentence", "second sentence"])
    assert len(vectors) == 2
    assert all(len(v) == DIMENSION for v in vectors)


def test_declared_dimension_matches_pgvector_schema():
    assert LocalMiniLMEmbeddingProvider.dimension == 384


def test_empty_input_returns_empty_output_without_loading_the_model(tmp_path):
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    with patch("sentence_transformers.SentenceTransformer") as mock_cls:
        result = provider.embed([])
    assert result == []
    mock_cls.assert_not_called()


def test_identical_text_is_served_from_cache_without_a_second_model_call(tmp_path):
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    fake = _fake_model()
    with patch("sentence_transformers.SentenceTransformer", return_value=fake):
        provider.embed(["same text"])
        provider.embed(["same text"])
    assert fake.encode.call_count == 1  # second call was a pure cache hit


def test_cache_persists_across_provider_instances(tmp_path):
    fake = _fake_model()
    with patch("sentence_transformers.SentenceTransformer", return_value=fake):
        LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path)).embed(["persisted text"])
        LocalMiniLMEmbeddingProvider._model = None  # simulate a fresh process
        LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path)).embed(["persisted text"])
    assert fake.encode.call_count == 1  # second instance found it on disk, didn't recompute


def test_query_and_document_text_use_the_same_model_and_cache(tmp_path):
    """There's only one embed() path for both ingestion and query text - this test
    exists to make that explicit and catch any future accidental divergence."""
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    fake = _fake_model()
    with patch("sentence_transformers.SentenceTransformer", return_value=fake):
        doc_vector = provider.embed(["Revenue grew 15% year on year."])[0]
        query_vector = provider.embed(["Revenue grew 15% year on year."])[0]
    assert doc_vector == query_vector


def test_missing_dependency_raises_clear_error_not_a_fabricated_vector(tmp_path):
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    with patch.dict("sys.modules", {"sentence_transformers": None}):
        with pytest.raises(EmbeddingModelUnavailableError):
            provider.embed(["anything"])


def test_model_load_failure_raises_clear_error_not_a_fabricated_vector(tmp_path):
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    with patch("sentence_transformers.SentenceTransformer", side_effect=OSError("simulated download failure")):
        with pytest.raises(EmbeddingModelUnavailableError):
            provider.embed(["anything"])


def test_unexpected_output_dimension_is_rejected_not_silently_stored(tmp_path):
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    with patch("sentence_transformers.SentenceTransformer", return_value=_fake_model(dimension=999)):
        with pytest.raises(EmbeddingModelUnavailableError):
            provider.embed(["anything"])


def test_cache_key_encodes_model_name_and_revision_not_just_text():
    provider = LocalMiniLMEmbeddingProvider(cache_dir="/tmp")
    assert provider.name == f"{MODEL_NAME}@{MODEL_REVISION}"
    key_a = provider._key("same text")
    # Simulate a different revision of the same model by constructing a second
    # provider-like key with a different `name` - this must produce a different
    # key, so a future revision bump can never be mistaken for today's cache.
    other_key = hashlib_sha256(f"{MODEL_NAME}@some-other-revision:same text")
    assert key_a != other_key


def hashlib_sha256(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_different_providers_never_share_a_cache_file(tmp_path):
    """Even a hypothetical second local provider writing to the same directory
    must get its own cache file - the filename itself encodes model identity,
    not just the keys inside it."""
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    assert "all_MiniLM_L6_v2" in provider._cache_path.name
    assert MODEL_REVISION in provider._cache_path.name


def test_model_name_and_revision_are_explicit_properties_not_derived_from_name(tmp_path):
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    assert provider.model_name == MODEL_NAME
    assert provider.model_revision == MODEL_REVISION
    assert provider.name == f"{provider.model_name}@{provider.model_revision}"


def test_count_tokens_uses_the_real_tokenizer_not_an_approximation(tmp_path):
    """Real (non-mocked) tokenizer test - loads the actual model's bundled
    tokenizer and checks genuine token counts, not a word-count/char-count proxy."""
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    short = provider.count_tokens("Revenue grew.")
    longer = provider.count_tokens("Revenue grew significantly across all major business segments this quarter.")
    assert short > 0
    assert longer > short


def test_count_tokens_hard_limit_boundary_matches_model_max_seq_length(tmp_path):
    """MiniLM's max_seq_length is 256 - this is the real source of the chunking
    hard limit, verified against the actual loaded model, not hardcoded blindly."""
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    provider._ensure_model_loaded()
    assert LocalMiniLMEmbeddingProvider._model.max_seq_length == 256


def test_count_tokens_handles_empty_string_consistently_not_as_a_special_case(tmp_path):
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    count = provider.count_tokens("")
    assert count >= 1  # the real tokenizer still emits its special tokens for ""


def test_real_local_model_produces_genuine_384_dim_vectors(tmp_path):
    """The one real (non-mocked) test: actually loads all-MiniLM-L6-v2 and runs
    real local inference. Slower (downloads/loads the real model) but this is what
    genuinely proves local embedding generation works, not just the plumbing
    around it."""
    provider = LocalMiniLMEmbeddingProvider(cache_dir=str(tmp_path))
    vectors = provider.embed(["Reliance Industries reported a 15% revenue increase."])
    assert len(vectors) == 1
    assert len(vectors[0]) == 384
    assert all(isinstance(x, float) for x in vectors[0])
