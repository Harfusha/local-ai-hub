from __future__ import annotations

import threading
import time
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.rag import RAGStore
from local_ai_hub.sqlite_support import connect_sqlite


@pytest.fixture
def rag_with_many_chunks(tmp_path: Path) -> tuple[RAGStore, str]:
    db_path = str(tmp_path / "rag.db")
    config = {
        "server": {"state_dir": str(tmp_path)},
        "rag": {"db_path": db_path, "search_batch_size": 32},
        "features": {"reranker": True},
    }
    rag = RAGStore(config)
    rag._init_db()

    # Pre-populate 200 chunks with dummy float embeddings
    workspace = "deadline_ws"
    dimension = 384
    import numpy as np
    dummy_vec = np.ones(dimension, dtype=np.float32).tobytes()

    with closing(connect_sqlite(rag.db_path)) as con:
        rows = [
            (
                workspace,
                f"src/file_{i}.py",
                i,
                f"def compute_task_{i}(): return {i}",
                f"hash_{i}",
                "default_space",
                dummy_vec,
            )
            for i in range(200)
        ]
        con.executemany(
            """
            INSERT INTO chunks (workspace, path, chunk_no, text, content_hash, embedding_space, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()

    # Mock services.embed
    class DummyEmbedServices:
        def embed(self, texts, priority=3, query=True):
            return {
                "success": True,
                "embedding_space_id": "default_space",
                "embeddings": [np.ones(dimension, dtype=np.float32).tolist()],
            }
    rag.services = DummyEmbedServices()

    return rag, workspace


def test_rag_search_aborts_immediately_on_cancel_event(rag_with_many_chunks: tuple[RAGStore, str]):
    rag, ws = rag_with_many_chunks
    cancel_event = threading.Event()
    cancel_event.set()  # Pre-cancelled

    result = rag.search("compute_task", workspace=ws, cancel_event=cancel_event)
    assert result["success"] is True
    assert "deadline_exceeded" in result.get("fallbacks", [])


def test_rag_search_skips_rerank_when_deadline_exceeded(rag_with_many_chunks: tuple[RAGStore, str]):
    rag, ws = rag_with_many_chunks

    # Pass an expired deadline
    past_deadline = time.perf_counter() - 1.0

    result = rag.search("compute_task", workspace=ws, deadline=past_deadline)
    assert result["success"] is True
    assert "deadline_exceeded" in result.get("fallbacks", [])


def test_rag_search_normal_without_deadline(rag_with_many_chunks: tuple[RAGStore, str]):
    rag, ws = rag_with_many_chunks

    result = rag.search("compute_task", workspace=ws)
    assert result["success"] is True
    assert len(result["results"]) > 0
    assert "deadline_exceeded" not in result.get("fallbacks", [])
