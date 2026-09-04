from __future__ import annotations

from local_ai_hub.embeddings import EmbeddingModel


class _EmbeddingBackend:
    prompts: dict[str, str] = {}

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts, **_kwargs):
        batch = list(texts)
        self.calls.append(batch)
        return [[float(len(text)), 1.0] for text in batch]


def test_embedding_batch_computes_duplicate_content_once(tmp_path):
    backend = _EmbeddingBackend()
    embeddings = EmbeddingModel(
        {
            "server": {"state_dir": str(tmp_path)},
            "models": {"embedding": "test-model", "embedding_backend": "sentence-transformers"},
            "cache": {"embeddings": True},
        }
    )
    embeddings._model = backend

    result = embeddings.encode(["same content", "same content", "different", "same content"])

    assert backend.calls == [["same content", "different"]]
    assert result["cache_hits"] == 0
    assert result["computed"] == 2
    assert result["batch_deduplicated"] == 2
    assert result["embeddings"][0] == result["embeddings"][1] == result["embeddings"][3]
