class EmbeddingModelUnavailableError(Exception):
    """Raised whenever a real embedding can't be produced - missing dependency,
    failed model download, unexpected output shape. Callers must treat this as a
    hard failure, never as a signal to fall back to a fake/random/zero vector."""
