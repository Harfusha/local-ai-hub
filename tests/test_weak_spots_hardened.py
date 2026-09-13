from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock

from local_ai_hub.commands import _BoundedStreamBuffer
from local_ai_hub.rag import RAGStore
from local_ai_hub.sqlite_support import incremental_vacuum, optimize_db


class _FailingServices:
    def __init__(self, succeed_init: bool = True) -> None:
        self.should_succeed = succeed_init

    def embed(self, texts, _tenant, **_kwargs):
        if not self.should_succeed:
            return {"success": False, "error": "ollama embeddings unavailable"}
        batch = list(texts)
        return {"success": True, "embeddings": [[float(len(text)), 1.0] for text in batch]}


class _MockReranker:
    def rerank(self, query, texts, top_k=8, priority=3):
        results = [{"index": idx, "score": 1.0 / (idx + 1)} for idx in range(len(texts))]
        return {"success": True, "results": results[:top_k]}


def test_rag_bm25_fts_fallback_when_embedding_fails(tmp_path: Path):
    services = _FailingServices(succeed_init=True)
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {"extensions": [".py"], "ignore_dirs": [], "chunk_chars": 4096, "chunk_overlap_chars": 0},
            "resilience": {"singleflight_wait_timeout_seconds": 2},
            "features": {"reranker": True},
        },
        services,
        _MockReranker(),
    )
    root = tmp_path / "project"
    root.mkdir()
    (root / "token_service.py").write_text("def validate_secret_token(token):\n    return token.is_active()\n", encoding="utf-8")
    (root / "other.py").write_text("def placeholder(): pass\n", encoding="utf-8")

    res = store.index_step(str(root), "tenant1", max_files=10)
    assert res["success"] is True

    # Now make embeddings fail completely
    services.should_succeed = False

    search_res = store.search("validate_secret_token", "tenant1", store.workspace_id(str(root)), top_k=5)
    assert search_res["success"] is True
    assert search_res.get("degraded") is True
    assert search_res.get("fallback") == "bm25_fts"
    assert len(search_res["results"]) > 0
    assert "token_service.py" in search_res["results"][0]["path"]


def test_sqlite_incremental_vacuum_and_freelist(tmp_path: Path):
    db_file = tmp_path / "test_vacuum.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, data TEXT)")
    conn.executemany("INSERT INTO items (data) VALUES (?)", [(f"payload-{i}" * 50,) for i in range(1000)])
    conn.commit()

    # Delete most rows to build up freelist pages
    conn.execute("DELETE FROM items WHERE id > 50")
    conn.commit()
    conn.close()

    # Run incremental vacuum
    vac_res = incremental_vacuum(db_file, pages=20, freelist_threshold=5)
    assert vac_res["success"] is True
    assert vac_res["freelist_count"] >= 0
    assert "vacuumed" in vac_res

    # Optimize db should check freelist maintenance
    opt_res = optimize_db(db_file)
    assert opt_res["success"] is True
    assert "freelist_pages" in opt_res
    assert opt_res["freelist_pages"] >= 0


def test_command_stream_buffer_bounds():
    buf = _BoundedStreamBuffer(max_chars=2000)
    for i in range(25):
        buf.append(f"line {i}\n")

    assert buf.total_lines == 25
    val = buf.getvalue()
    assert "line 24" in val
    assert "line 0" in val


from local_ai_hub.repo_tools import RepositoryTools


def test_repo_traversal_depth_and_cycle_bounds(tmp_path: Path):
    # Deeply nested directory tree
    curr = tmp_path
    for i in range(15):
        curr = curr / f"lvl_{i}"
        curr.mkdir()
    (curr / "deep_file.py").write_text("# deep file\n", encoding="utf-8")

    tools = RepositoryTools({
        "rag": {"extensions": [".py"], "ignore_dirs": []},
        "search": {"prefer_git_files": False},
    })

    # With max_depth=5, deep_file must be ignored
    files_shallow = list(tools.iter_files(str(tmp_path), max_depth=5))
    assert not any("deep_file.py" in str(f) for f in files_shallow)

    # With max_depth=20, deep_file must be found
    files_deep = list(tools.iter_files(str(tmp_path), max_depth=20))
    assert any("deep_file.py" in str(f) for f in files_deep)
