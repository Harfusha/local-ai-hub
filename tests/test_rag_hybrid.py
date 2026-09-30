from __future__ import annotations

import sqlite3
from contextlib import closing

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.rag import RAGStore, _fragment_hash


class _Services:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts, _tenant, **_kwargs):
        batch = list(texts)
        self.calls.append(batch)
        return {"success": True, "embeddings": [[float(len(text)), 1.0] for text in batch]}


class _Reranker:
    def rerank(self, query, texts, top_k=8, priority=3):
        results = [{"index": idx, "score": 1.0 / (idx + 1)} for idx in range(len(texts))]
        return {"success": True, "results": results[:top_k]}


def _store(tmp_path) -> RAGStore:
    return RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {"extensions": [".py"], "ignore_dirs": [], "chunk_chars": 4096, "chunk_overlap_chars": 0},
            "resilience": {"singleflight_wait_timeout_seconds": 2},
            "features": {"reranker": True},
        },
        _Services(),
        _Reranker(),
    )


def test_hybrid_rag_search_combines_fts_and_vector(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "auth.py").write_text("def authenticate_jwt_token(token):\n    # specific keyword\n    return token.valid()\n", encoding="utf-8")
    (root / "misc.py").write_text("def unrelated_helper_function():\n    return 42\n", encoding="utf-8")

    # Index files
    res = store.index_step(str(root), "test_tenant", max_files=10)
    assert res["success"] is True

    # Search with exact keyword
    search_res = store.search("authenticate_jwt_token", "test_tenant", store.workspace_id(str(root)), top_k=5)
    assert search_res["success"] is True
    assert len(search_res["results"]) > 0
    top = search_res["results"][0]
    assert "auth.py" in top["path"]
    assert search_res.get("hybrid") is True


def test_search_marks_heuristic_rerank_as_degraded_not_model_reranked(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "auth.py").write_text("def authenticate_token(token):\n    return token\n", encoding="utf-8")
    assert store.index_step(str(root), "tenant", max_files=10)["success"] is True

    class _FailedReranker:
        def rerank(self, *_args, **_kwargs):
            return {"success": False, "results": []}

    store.reranker = _FailedReranker()
    result = store.search("authenticate token", "tenant", store.workspace_id(str(root)), use_reranker=True)

    assert result["reranked"] is False
    assert result["degraded"] is True
    assert result["fallback"] == "heuristic_rerank"


def test_search_propagates_embedding_backend_fallback_status(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "auth.py").write_text("def authenticate_token(token):\n    return token\n", encoding="utf-8")
    assert store.index_step(str(root), "tenant", max_files=10)["success"] is True

    original_embed = store.services.embed

    def _fallback_embed(texts, tenant, **kwargs):
        result = original_embed(texts, tenant, **kwargs)
        result.update({"degraded": True, "fallback": "sentence-transformers"})
        return result

    store.services.embed = _fallback_embed
    result = store.search("authenticate_token", "tenant", store.workspace_id(str(root)), use_reranker=False)

    assert result["degraded"] is True
    assert result["fallback"] == "sentence-transformers"


def test_search_excludes_vectors_from_other_embedding_spaces(tmp_path):
    store = _store(tmp_path)
    store.services.embed = lambda *_args, **_kwargs: {
        "success": True,
        "embedding_space_id": "space-a",
        "embeddings": [[1.0, 0.0]],
    }
    tenant = "tenant"
    workspace = "mixed-spaces"
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                (store._scope_key(tenant), workspace, "a.py", 0, "hash-a", "space a", "[1.0,0.0]", "space-a"),
                (store._scope_key(tenant), workspace, "b.py", 0, "hash-b", "space b", "[0.0,1.0]", "space-b"),
            ],
        )
        con.commit()

    result = store._search_uncached("query", tenant, workspace, top_k=2, use_reranker=False)

    assert [row["path"] for row in result["results"]] == ["a.py"]


def test_search_reports_degraded_when_index_has_no_matching_embedding_space(tmp_path):
    store = _store(tmp_path)
    store.services.embed = lambda *_args, **_kwargs: {
        "success": True,
        "embedding_space_id": "space-current",
        "embeddings": [[1.0, 0.0]],
    }
    tenant = "tenant"
    workspace = "stale-space"
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (store._scope_key(tenant), workspace, "old.py", 0, "old-hash", "unrelated words", "[1.0,0.0]", "space-old"),
        )
        con.commit()

    result = store._search_uncached("zebra query", tenant, workspace, top_k=2, use_reranker=False)

    assert result["success"] is True
    assert result["results"] == []
    assert result["degraded"] is True
    assert result["fallback"] == "embedding_space_mismatch"


def test_search_reports_pending_rebuild_for_partial_embedding_space(tmp_path):
    store = _store(tmp_path)
    store.services.embed = lambda *_args, **_kwargs: {
        "success": True,
        "embedding_space_id": "space-current",
        "embeddings": [[1.0, 0.0]],
    }
    tenant = "tenant"
    workspace = "partial-spaces"
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                (store._scope_key(tenant), workspace, "current.py", 0, "current", "current result", "[1.0,0.0]", "space-current"),
                (store._scope_key(tenant), workspace, "old.py", 0, "old", "old result", "[0.0,1.0]", "space-old"),
            ],
        )
        con.commit()

    result = store._search_uncached("query", tenant, workspace, top_k=2, use_reranker=False)

    assert [row["path"] for row in result["results"]] == ["current.py"]
    assert result["degraded"] is True
    assert result["reindex_required"] is True
    assert "embedding_space_rebuild_pending" in result["fallbacks"]
    with closing(store._connect()) as con:
        assert store._stored_workspace_embedding_space(con, store._scope_key(tenant), workspace) == "space-current"


def test_search_cache_key_tracks_runtime_embedding_space(tmp_path):
    store = _store(tmp_path)
    active_space = {"value": "space-a"}
    calls = []
    store.services.space_id = active_space["value"]

    def embed(texts, _tenant, **_kwargs):
        calls.append(list(texts))
        return {
            "success": True,
            "embedding_space_id": active_space["value"],
            "embeddings": [[1.0, 0.0] for _ in texts],
        }

    store.services.embed = embed
    tenant, workspace = "tenant", "cache-spaces"
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                (store._scope_key(tenant), workspace, "a.py", 0, "hash-a", "space a", "[1.0,0.0]", "space-a"),
                (store._scope_key(tenant), workspace, "b.py", 0, "hash-b", "space b", "[1.0,0.0]", "space-b"),
            ],
        )
        con.commit()

    first = store.search("same query", tenant, workspace, use_reranker=False)
    repeated = store.search("same query", tenant, workspace, use_reranker=False)
    active_space["value"] = "space-b"
    store.services.space_id = active_space["value"]
    second = store.search("same query", tenant, workspace, use_reranker=False)

    assert [row["path"] for row in first["results"]] == ["a.py"]
    assert repeated["search_cache"]["hit"] is True
    assert [row["path"] for row in second["results"]] == ["b.py"]
    assert second["search_cache"]["hit"] is False
    assert len(calls) == 2


def test_rag_index_retries_transient_publish_lock(tmp_path, monkeypatch):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "locked.py").write_text("def locked():\n    return 1\n", encoding="utf-8")

    state = {"failures": 1, "begins": 0}

    class _FlakyConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE":
                state["begins"] += 1
                if state["failures"]:
                    state["failures"] -= 1
                    raise sqlite3.OperationalError("database is locked")
            return self._connection.execute(sql, *args)

        def close(self):
            self._connection.close()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    original_connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _FlakyConnection(original_connect()))

    result = store.index(str(root), "test_tenant", workspace="locked-workspace")

    assert result["success"] is True
    assert state["begins"] == 2
    assert len(store.services.calls) == 1


def test_rag_index_paths_step_retries_publish_lock_without_reembedding(tmp_path, monkeypatch):
    store = _store(tmp_path)
    root = tmp_path / "project-step"
    root.mkdir()
    (root / "locked.py").write_text("def locked_step():\n    return 1\n", encoding="utf-8")
    state = {"failures": 1, "begins": 0}

    class _FlakyConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE":
                state["begins"] += 1
                if state["failures"]:
                    state["failures"] -= 1
                    raise sqlite3.OperationalError("database is locked")
            return self._connection.execute(sql, *args)

        def close(self):
            self._connection.close()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    original_connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _FlakyConnection(original_connect()))

    result = store.index_paths_step(
        str(root), "test_tenant", "step-workspace", ["locked.py"]
    )

    assert result["success"] is True
    assert state["begins"] == 2
    assert len(store.services.calls) == 1


def test_legacy_rag_schema_reset_preserves_agent_state_history(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    agent_state = AgentStateStore(state_dir / "agent_state.sqlite3")
    event = AgentEvent.create("task:durable", "task_created", {"task_id": "durable"})
    assert agent_state.append(event).seq == 1

    rag_path = state_dir / "rag.sqlite3"
    with closing(sqlite3.connect(rag_path)) as con:
        con.execute(
            "CREATE TABLE chunks (tenant TEXT, workspace TEXT, path TEXT, chunk_no INTEGER, "
            "content_hash TEXT, text TEXT, embedding BLOB, PRIMARY KEY "
            "(tenant, workspace, path, chunk_no))"
        )
        con.execute(
            "INSERT INTO chunks VALUES ('tenant', 'workspace', 'old.py', 0, 'hash', 'old', X'00')"
        )
        con.commit()

    store = _store(tmp_path)

    assert store.db_path == rag_path
    assert agent_state.db_path == state_dir / "agent_state.sqlite3"
    assert store.index_reset is True
    with closing(sqlite3.connect(agent_state.db_path)) as con:
        rows = con.execute(
            "SELECT stream_id, seq, event_id FROM agent_events WHERE stream_id=?",
            ("task:durable",),
        ).fetchall()
    assert rows == [("task:durable", 1, event.event_id)]
    with closing(sqlite3.connect(rag_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0


def test_rag_fingerprint_reset_and_corruption_recovery_preserve_agent_state_history(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    agent_state = AgentStateStore(state_dir / "agent_state.sqlite3")
    event = AgentEvent.create("task:durable", "task_created", {"task_id": "durable"})
    assert agent_state.append(event).seq == 1

    store = _store(tmp_path)
    rag_path = store.db_path
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks "
            "(tenant, workspace, path, chunk_no, content_hash, text, embedding, embedding_space) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("tenant", "workspace", "old.py", 0, "hash", "old", "[1.0, 0.0]", "space"),
        )
        con.commit()

    store.config["rag"]["chunk_chars"] += 1
    reset_store = RAGStore(store.config, store.services, store.reranker)
    assert reset_store.index_reset is True
    with closing(reset_store._connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0

    rag_path.write_bytes(b"not a SQLite database")
    recovered_store = RAGStore(store.config, store.services, store.reranker)
    assert recovered_store.db_path.exists()
    assert list(state_dir.glob("rag.sqlite3.corrupt-*"))

    assert agent_state.db_path.exists()
    with closing(sqlite3.connect(agent_state.db_path)) as con:
        rows = con.execute(
            "SELECT stream_id, seq, event_id FROM agent_events WHERE stream_id=?",
            ("task:durable",),
        ).fetchall()
    assert rows == [("task:durable", 1, event.event_id)]
