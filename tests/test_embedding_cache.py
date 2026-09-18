from __future__ import annotations

from local_ai_hub.services import LocalAIServices


class _EmbeddingBackend:
    def __init__(self):
        self.calls = []

    def encode(self, texts, **_kwargs):
        batch = list(texts)
        self.calls.append(batch)
        return {"success": True, "embeddings": [[float(len(text)), 1.0] for text in batch]}


class _Cache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value


def test_embed_reuses_cached_vectors_and_preserves_batch_order():
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {
        "models": {"embedding_backend": "sentence-transformers", "embedding": "test-model"},
        "cache": {"embeddings": True},
    }
    service.embeddings = _EmbeddingBackend()
    service.embedding_cache = _Cache()

    first = service.embed(["alpha", "beta"], "tenant")
    second = service.embed(["beta", "alpha"], "tenant")

    assert first["embeddings"] == [[5.0, 1.0], [4.0, 1.0]]
    assert second["embeddings"] == [[4.0, 1.0], [5.0, 1.0]]
    assert service.embeddings.calls == [["alpha", "beta"]]
