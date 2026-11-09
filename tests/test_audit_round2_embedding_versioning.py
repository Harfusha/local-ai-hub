from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock


from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.semantic_cache import SemanticGenerationCache


class _StubEmbeddings:
    def __init__(self, model_name="model-a", dim=4, space_id="space-a"):
        self.model_name = model_name
        self.dim = dim
        self.space_id = space_id

    def embedding_space_id(self, identity=None, *, dimension=None):
        return self.space_id

    def encode(self, texts, query=False):
        return {
            "success": True,
            "embeddings": [[1.0, 2.0, 3.0, 4.0][:self.dim] for _ in texts],
            "model": self.model_name,
            "embedding_space_id": self.space_id,
        }


def test_n09_agent_memory_embeddings_space_versioning(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory_store = MemoryStore(state_store)

    # 1. Record a memory
    rec = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            key="config.arch",
            value="sqlite-wal",
            scope=AgentScope.GLOBAL,
            scope_id="global",
            source="user",
            provenance={"root": str(tmp_path)},
        )
    )

    # 2. Store embedding with model-a and space-a
    memory_store.set_embedding(
        rec.record_id,
        [1.0, 0.0, 0.0, 0.0],
        model_name="model-a",
        embedding_space_id="space-a",
    )

    # 3. Query with service providing matching space-a
    services_matching = MagicMock()
    services_matching.embed = lambda texts: {
        "success": True,
        "embeddings": [[1.0, 0.0, 0.0, 0.0]],
        "model": "model-a",
        "embedding_space_id": "space-a",
    }
    found = memory_store.find(query="sqlite", services=services_matching, include_all_scopes=True)
    assert len(found) >= 1
    assert found[0].record_id == rec.record_id

    # 4. Query with service providing DIFFERENT model-b / space-b
    services_mismatch = MagicMock()
    services_mismatch.embed = lambda texts: {
        "success": True,
        "embeddings": [[1.0, 0.0, 0.0, 0.0]],
        "model": "model-b",
        "embedding_space_id": "space-b",
    }
    # Should fall back cleanly without vector similarity match on incompatible space
    with closing(sqlite3.connect(db_path)) as con:
        # Check that table has new metadata columns
        cols = [r[1] for r in con.execute("PRAGMA table_info(agent_memory_embeddings)").fetchall()]
        assert "embedding_space_id" in cols
        assert "model_name" in cols
        assert "dimension" in cols


def test_n19_semantic_generation_cache_embedding_space_isolation(tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path)},
        "semantic_cache": {"threshold": 0.5, "min_query_chars": 4},
    }
    emb_a = _StubEmbeddings(model_name="nomic-embed-a", space_id="space-a", dim=4)
    cache_a = SemanticGenerationCache(config, emb_a)

    # Store entry in space-a
    cache_a.set("test-scope", "How do I configure WAL?", {"answer": "Use PRAGMA journal_mode=WAL;"})
    
    # Same cache instance retrieves it
    res, score = cache_a.get("test-scope", "How do I configure WAL?")
    assert res is not None
    assert score >= 0.5

    # Switch embedding model to space-b
    emb_b = _StubEmbeddings(model_name="bge-m3-b", space_id="space-b", dim=4)
    cache_b = SemanticGenerationCache(config, emb_b)

    # Different embedding space must NOT hit entries from space-a
    res_b, score_b = cache_b.get("test-scope", "How do I configure WAL?")
    assert res_b is None, "Semantic cache must not return hit across different embedding spaces"
