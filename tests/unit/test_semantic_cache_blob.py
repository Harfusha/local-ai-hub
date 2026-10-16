from contextlib import closing
import sqlite3
import numpy as np
from pathlib import Path
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
        row = con.execute("SELECT vector_blob FROM semantic_entries WHERE scope_key='test_scope'").fetchone()
        assert row is not None
        blob = row[0]
        assert isinstance(blob, (bytes, memoryview))
        # 4 floats * 4 bytes = 16 bytes
        arr = np.frombuffer(blob, dtype=np.float32)
        assert len(arr) == 4
        assert np.allclose(arr, [1.0, 2.0, 3.0, 4.0])

def test_semantic_cache_get_reads_blob(tmp_path: Path):
    db_path = tmp_path / "semantic.sqlite3"
    embeddings = _StubEmbeddings(dim=4)
    cache = SemanticGenerationCache({"server": {"state_dir": str(tmp_path)}}, embeddings)
    
    cache.set("test_scope", "sample search query", {"answer": 42})
    value, score = cache.get("test_scope", "different search phrase")

    assert value == {"answer": 42}
    assert score > 0.99
    val, sim = cache.get("test_scope", "sample search query")
    assert val == {"answer": 42}
    assert sim >= 0.99


def test_semantic_cache_rebuilds_stale_vector_schema_only(tmp_path: Path):
    db_path = tmp_path / "semantic-cache.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            """CREATE TABLE semantic_entries (
                id INTEGER PRIMARY KEY,
                scope_key TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                query_text TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                value_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                accessed_at REAL NOT NULL,
                hits INTEGER NOT NULL DEFAULT 0
            )"""
        )
        con.execute("INSERT INTO semantic_entries VALUES(1, 's', 'q', 'query', '[]', '{}', 1, 1, 0)")
        con.execute("CREATE TABLE unrelated_state (value TEXT NOT NULL)")
        con.execute("INSERT INTO unrelated_state VALUES('preserved')")
        con.commit()

    SemanticGenerationCache({"server": {"state_dir": str(tmp_path)}}, _StubEmbeddings())

    with closing(sqlite3.connect(db_path)) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(semantic_entries)")}
        assert "vector_blob" in columns
        assert "vector_json" not in columns
        assert con.execute("SELECT COUNT(*) FROM semantic_entries").fetchone()[0] == 0
        assert con.execute("SELECT value FROM unrelated_state").fetchone()[0] == "preserved"
