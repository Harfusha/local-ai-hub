from __future__ import annotations

import sys
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.services import LocalAIServices
from local_ai_hub.rag import RAGStore


def test_embedding_space_mismatch_yields_reindex_required_without_blocking(tmp_path):
    store = RAGStore({"server": {"state_dir": str(tmp_path / "state")}})
    store.services = MagicMock()
    store.services.space_id = "new_embedding_space_v2"
    workspace = "known-stale-space"

    with closing(store._connect()) as con:
        store._store_workspace_embedding_space(con, workspace, "old_embedding_space_v1")
        con.commit()

    res = store._search_uncached("test query", workspace, top_k=2, semantic_only=True)
    assert res.get("success") is True
    assert res.get("degraded") is True
    assert res.get("fallback") == "embedding_space_mismatch"
    assert res.get("reindex_required") is True


def test_hybrid_search_falls_back_cleanly_on_rag_mismatch(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "guide.md").write_text("installation guide content\n", encoding="utf-8")

    mock_repo_tools = MagicMock()
    mock_repo_tools.search.return_value = {
        "success": True,
        "results": [{"path": "guide.md", "text": "installation guide content"}],
        "total_matches": 1,
        "count_exact": True,
        "has_more": False,
    }

    services = LocalAIServices(
        config={"server": {"state_dir": str(tmp_path / "state")}, "features": {"rag": True}},
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=mock_repo_tools,
        repo_state=MagicMock(),
    )

    # Simulate RAG returning embedding_space_mismatch
    services._repo_rag_search = MagicMock(return_value=([], {
        "success": True,
        "degraded": True,
        "fallback": "embedding_space_mismatch",
        "reindex_required": True,
        "reason": "embedding_space_mismatch",
    }))

    result = services.repo_search(str(repo_dir), "installation guide", search_mode="hybrid")
    assert result.get("success") is True
    assert result.get("degraded") is True
    assert result.get("degradation_reason") == "embedding_space_mismatch"
    # Lexical fallback results must be preserved
    assert len(result.get("results", [])) > 0
    assert result["results"][0]["path"] == "guide.md"


def test_repo_rag_search_passes_configured_deadline(tmp_path):
    import time

    class StubRag:
        def __init__(self):
            self.search_kwargs = None

        def workspace_id(self, _root):
            return "workspace"

        def require_workspace_root(self, **_kwargs):
            return None

        def has_workspace_chunks(self, **_kwargs):
            return True

        def search(self, *_args, **kwargs):
            self.search_kwargs = kwargs
            return {"success": False, "error": "test fallback"}

    repo = tmp_path / "repo"
    repo.mkdir()
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {
        "features": {"rag": True, "reranker": False},
        "resilience": {"repository_search_timeout_seconds": 0.5},
    }
    services.rag = StubRag()

    started = time.perf_counter()
    services._repo_rag_search(str(repo), "needle", 8)

    deadline = services.rag.search_kwargs["deadline"]
    assert started + 0.4 <= deadline <= started + 0.7


def test_rag_search_caps_singleflight_wait_to_deadline(tmp_path, monkeypatch):
    import time

    store = RAGStore({"server": {"state_dir": str(tmp_path / "state")}})
    store.services = MagicMock()
    store._embedding_space_cache_identity_known = lambda: True
    store._embedding_space_id = lambda *_args, **_kwargs: "space"
    store._embedding_dimension_cache_identity = lambda: {"dimension": 3}
    store._search_uncached = lambda *_args, **_kwargs: {"success": True, "results": []}

    observed_timeouts = []
    original = store.search_flight.get_or_compute

    def capture_timeout(key, compute, *, wait_timeout_seconds=None):
        observed_timeouts.append(wait_timeout_seconds)
        if wait_timeout_seconds is None:
            return original(key, compute)
        return original(key, compute, wait_timeout_seconds=wait_timeout_seconds)

    monkeypatch.setattr(store.search_flight, "get_or_compute", capture_timeout)
    deadline = time.perf_counter() + 0.5
    store.search("needle", workspace="workspace", deadline=deadline, semantic_only=True)

    assert observed_timeouts
    assert 0 < observed_timeouts[0] <= 0.5


def test_auto_embedding_receives_search_wait_timeout():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"embedding_backend": "auto", "embedding": "test-model"}}
    services.embeddings = MagicMock()
    services.embeddings.encode.return_value = {"success": True, "embeddings": [[0.1]]}

    services.embed(["needle"], query=True, wait_timeout=0.25)

    services.embeddings.encode.assert_called_once_with(
        ["needle"], query=True, priority=3, wait_timeout_seconds=0.25,
    )
