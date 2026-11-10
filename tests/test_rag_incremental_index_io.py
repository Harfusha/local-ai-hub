from __future__ import annotations

import re

from local_ai_hub import rag as rag_module
from local_ai_hub.rag import RAGStore


class _EmbeddingStub:
    space_id = "test-embedding-space"

    def embed(self, texts, **_kwargs):
        return {
            "success": True,
            "space_id": self.space_id,
            "embeddings": [[1.0, 0.0, 0.0] for _ in texts],
        }


def test_unchanged_index_does_not_read_all_embedding_blobs(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "guide.md").write_text("A short stable document for indexing.\n", encoding="utf-8")
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {"embedding": "test-embedding", "embedding_dimension": 3},
            "rag": {"dedup_near_duplicates": False},
        },
        services=_EmbeddingStub(),
    )

    first = store.index(str(repo))
    assert first["success"] is True

    statements = []
    original_connect = rag_module.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(rag_module, "connect_sqlite", traced_connect)
    second = store.index(str(repo))

    assert second["success"] is True
    embedding_reads = [
        statement.lower()
        for statement in statements
        if statement.lstrip().lower().startswith("select")
        and " from chunks " in statement.lower()
        and re.search(
            r"(?:^|,)\s*embedding\s*(?:,|$)",
            statement.lower().partition(" from chunks ")[0],
        )
    ]
    assert embedding_reads == []
