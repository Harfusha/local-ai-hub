from contextlib import closing
import sqlite3
import pytest
import numpy as np
from pathlib import Path
from types import SimpleNamespace
import local_ai_hub.semantic_cache as semantic_cache
from local_ai_hub.semantic_cache import SemanticGenerationCache

class _StubEmbeddings:
    def __init__(self, dim: int = 4):
        self.dim = dim
    def encode(self, texts, **kwargs):
        # Deterministic mock vectors
        return {
            "success": True,
            "embeddings": [[float(i + 1) for i in range(self.dim)] for _ in texts],
        }

def test_semantic_cache_exposes_only_canonical_class():
    assert not hasattr(semantic_cache, "SemanticCache")

def test_semantic_cache_stores_vector_as_blob(tmp_path: Path):
    db_path = tmp_path / "semantic.sqlite3"
    embeddings = _StubEmbeddings(dim=4)
    cache = SemanticGenerationCache({"server": {"state_dir": str(tmp_path)}}, embeddings)
    
    cache.set("test_scope", "sample search query", {"answer": 42})
    
    with closing(sqlite3.connect(cache.path)) as con:
        row = con.execute("SELECT vector_json FROM semantic_entries WHERE scope_key='test_scope'").fetchone()
        assert row is not None
        blob = row[0]
        assert isinstance(blob, (bytes, memoryview))
        # 4 floats * 4 bytes = 16 bytes
        arr = np.frombuffer(blob, dtype=np.float32)
        assert len(arr) == 4
        assert np.allclose(arr, [1.0, 2.0, 3.0, 4.0])

def test_semantic_cache_get_reads_blob_without_list_decode(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "semantic.sqlite3"
    embeddings = _StubEmbeddings(dim=4)
    cache = SemanticGenerationCache({"server": {"state_dir": str(tmp_path)}}, embeddings)
    
    cache.set("test_scope", "sample search query", {"answer": 42})
    monkeypatch.setattr(
        cache,
        "_decode_vector",
        lambda raw: (_ for _ in ()).throw(AssertionError("BLOB retrieval decoded a Python list")),
    )

    value, score = cache.get("test_scope", "different search phrase")

    assert value == {"answer": 42}
    assert score > 0.99
    val, sim = cache.get("test_scope", "sample search query")
    assert val == {"answer": 42}
    assert sim >= 0.99
