from __future__ import annotations

import sqlite3
import errno
import threading

import pytest
import json
import struct
from contextlib import closing
from pathlib import Path

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub import rag as rag_module
from local_ai_hub.rag import RAGStore, _fragment_hash


class _Services:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts, **_kwargs):
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
    res = store.index_step(str(root), max_files=10)
    assert res["success"] is True

    # Search with exact keyword
    search_res = store.search("authenticate_jwt_token", top_k=5, workspace=store.workspace_id(str(root)))
    assert search_res["success"] is True
    assert len(search_res["results"]) > 0
    top = search_res["results"][0]
    assert "auth.py" in top["path"]
    assert search_res.get("hybrid") is True


def test_index_embeds_changed_chunks_without_undefined_text_list(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project-index"
    root.mkdir()
    source = root / "module.py"
    source.write_text("def indexed_value():\n    return 'fresh text'\n", encoding="utf-8")

    result = store.index(str(root), workspace="index-regression")

    assert result["success"] is True
    assert result["embedded_chunks"] > 0
    assert len(store.services.calls) == 1
    assert store.services.calls[0]


def test_index_paths_step_sets_embedding_space_before_nonempty_records(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project-path-step"
    root.mkdir()
    source = root / "module.py"
    source.write_text("def indexed_step_value():\n    return 'fresh text'\n", encoding="utf-8")

    result = store.index_paths_step(str(root), workspace="path-step-regression", paths=["module.py"])

    assert result["success"] is True
    assert result["embedded_chunks"] > 0
    with closing(store._connect()) as con:
        row = con.execute(
            "SELECT embedding,embedding_space FROM chunks "
            "WHERE workspace=? AND path=?",
            ("path-step-regression", "module.py"),
        ).fetchone()
    assert row is not None
    assert row[0]
    assert row[1]


def test_search_marks_heuristic_rerank_as_degraded_not_model_reranked(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "auth.py").write_text("def authenticate_token(token):\n    return token\n", encoding="utf-8")
    assert store.index_step(str(root), max_files=10)["success"] is True

    class _FailedReranker:
        def rerank(self, *_args, **_kwargs):
            return {"success": False, "results": []}

    store.reranker = _FailedReranker()
    result = store.search("authenticate token", use_reranker=True, workspace=store.workspace_id(str(root)))

    assert result["reranked"] is False
    assert result["degraded"] is True
    assert result["fallback"] == "heuristic_rerank"


def test_search_propagates_embedding_backend_fallback_status(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "auth.py").write_text("def authenticate_token(token):\n    return token\n", encoding="utf-8")
    assert store.index_step(str(root), max_files=10)["success"] is True

    original_embed = store.services.embed

    def _fallback_embed(texts, **kwargs):
        result = original_embed(texts, **kwargs)
        result.update({"degraded": True, "fallback": "sentence-transformers"})
        return result

    store.services.embed = _fallback_embed
    result = store.search("authenticate_token", use_reranker=False, workspace=store.workspace_id(str(root)))

    assert result["degraded"] is True
    assert result["fallback"] == "sentence-transformers"


def test_search_excludes_vectors_from_other_embedding_spaces(tmp_path):
    store = _store(tmp_path)
    store.services.embed = lambda *_args, **_kwargs: {
        "success": True,
        "embedding_space_id": "space-a",
        "embeddings": [[1.0, 0.0]],
    }
    workspace = "mixed-spaces"
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                (workspace, "a.py", 0, "hash-a", "space a", "[1.0,0.0]", "space-a"),
                (workspace, "b.py", 0, "hash-b", "space b", "[0.0,1.0]", "space-b"),
            ],
        )
        con.commit()

    result = store._search_uncached("query", workspace,  top_k=2, use_reranker=False)

    assert [row["path"] for row in result["results"]] == ["a.py"]


def test_search_reports_degraded_when_index_has_no_matching_embedding_space(tmp_path):
    store = _store(tmp_path)
    store.services.embed = lambda texts, *_args, **_kwargs: {
        "success": True,
        "embedding_space_id": "space-current",
        "embeddings": [[1.0, 0.0] for _ in texts],
    }
    workspace = "stale-space"
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?)",
            (workspace, "old.py", 0, "old-hash", "unrelated words", "[1.0,0.0]", "space-old"),
        )
        con.commit()

    result = store._search_uncached("zebra query", workspace,  top_k=2, use_reranker=False)

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
    workspace = "partial-spaces"
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                (workspace, "current.py", 0, "current", "current result", "[1.0,0.0]", "space-current"),
                (workspace, "old.py", 0, "old", "old result", "[0.0,1.0]", "space-old"),
            ],
        )
        con.commit()

    result = store._search_uncached("query", workspace,  top_k=2, use_reranker=False)

    assert [row["path"] for row in result["results"]] == ["current.py"]
    assert result["degraded"] is True
    assert result["reindex_required"] is True
    assert "embedding_space_rebuild_pending" in result["fallbacks"]
    with closing(store._connect()) as con:
        assert store._stored_workspace_embedding_space(con, workspace) == "space-current"


def test_search_cache_key_tracks_runtime_embedding_space(tmp_path):
    store = _store(tmp_path)
    active_space = {"value": "space-a"}
    calls = []
    store.services.space_id = active_space["value"]

    def embed(texts, **_kwargs):
        calls.append(list(texts))
        return {
            "success": True,
            "embedding_space_id": active_space["value"],
            "embeddings": [[1.0, 0.0] for _ in texts],
        }

    store.services.embed = embed
    workspace = "cache-spaces"
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                (workspace, "a.py", 0, "hash-a", "space a", "[1.0,0.0]", "space-a"),
                (workspace, "b.py", 0, "hash-b", "space b", "[1.0,0.0]", "space-b"),
            ],
        )
        con.commit()

    first = store.search("same query", use_reranker=False, workspace=workspace)
    repeated = store.search("same query", use_reranker=False, workspace=workspace)
    active_space["value"] = "space-b"
    store.services.space_id = active_space["value"]
    second = store.search("same query", use_reranker=False, workspace=workspace)

    assert [row["path"] for row in first["results"]] == ["a.py"]
    assert repeated["search_cache"]["hit"] is True
    assert [row["path"] for row in second["results"]] == ["b.py"]
    assert second["search_cache"]["hit"] is False
    assert len(calls) == 2


def test_warm_search_skips_embedding_space_write_lock(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.services.space_id = "space-a"
    workspace = "warm-space-metadata"
    original_connect = store._connect
    with closing(original_connect()) as con:
        store._store_workspace_embedding_space(con, workspace, "space-a")
        con.commit()
    begin_immediate_calls = []

    class _TrackingConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE":
                begin_immediate_calls.append(sql)
            return self._connection.execute(sql, *args)

        def close(self):
            self._connection.close()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(store, "_connect", lambda: _TrackingConnection(original_connect()))

    for query in ("first query", "second query"):
        result = store._search_uncached(query, workspace,  use_reranker=False)
        assert result["success"] is True
    assert begin_immediate_calls == []

    with closing(store._connect()) as con:
        assert store._stored_workspace_embedding_space(con, workspace) == "space-a"


def test_warm_search_reads_embedding_space_from_vector_snapshot(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.services.space_id = "space-a"
    workspace = "snapshot-space-metadata"
    with closing(store._connect()) as con:
        store._store_workspace_embedding_space(con, workspace, "space-a")
        con.execute(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?)",
            (workspace, "known.py", 0, "known", "known result", "[1.0, 0.0]", "space-a"),
        )
        con.commit()

    transaction_states = []
    read_metadata = store._stored_workspace_embedding_space

    def observe_snapshot(connection, observed_workspace):
        transaction_states.append(connection.in_transaction)
        return read_metadata(connection, observed_workspace)

    monkeypatch.setattr(store, "_stored_workspace_embedding_space", observe_snapshot)
    result = store._search_uncached("query", workspace,  use_reranker=False)

    assert result["success"] is True
    assert [row["path"] for row in result["results"]] == ["known.py"]
    assert transaction_states == [True]


def test_public_search_cache_isolated_by_workspace(tmp_path):
    store = _store(tmp_path)
    store.services.space_id = "shared-runtime-space"
    store.services.embed = lambda *_args, **_kwargs: {
        "success": True,
        "embedding_space_id": "shared-runtime-space",
        "embeddings": [[1.0, 0.0]],
    }
    workspace = "same-workspace"
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                ("workspace-a", "same.py", 0, "same-metadata", "workspace a", "[1.0,0.0]", "shared-runtime-space"),
                ("workspace-b", "same.py", 0, "same-metadata", "workspace b", "[1.0,0.0]", "shared-runtime-space"),
            ],
        )
        con.commit()

    first = store.search("same query", use_reranker=False, workspace="workspace-a")
    second = store.search("same query", use_reranker=False, workspace="workspace-b")

    assert [row["text"] for row in first["results"]] == ["workspace a"]
    assert [row["text"] for row in second["results"]] == ["workspace b"]
    assert second["search_cache"]["hit"] is False


def test_public_search_cache_tracks_runtime_embedding_dimension(tmp_path):
    store = _store(tmp_path)
    store.services.space_id = "same-runtime-space"

    class _RuntimeDimension:
        _active_embedding_dimension = 2

    runtime = _RuntimeDimension()
    store.services.embeddings = runtime
    calls = []

    def uncached(query, workspace,  top_k=8, use_reranker=True, priority=3, scope_path=None):
        calls.append(runtime._active_embedding_dimension)
        return {"success": True, "results": [{"path": f"dimension-{runtime._active_embedding_dimension}"}]}

    store._search_uncached = uncached
    first = store.search("same query", use_reranker=False, workspace="same-workspace")
    runtime._active_embedding_dimension = 3
    second = store.search("same query", use_reranker=False, workspace="same-workspace")

    assert first["results"][0]["path"] == "dimension-2"
    assert second["results"][0]["path"] == "dimension-3"
    assert second["search_cache"]["hit"] is False
    assert calls == [2, 3]


def test_public_search_rekeys_when_runtime_embedding_identity_changes_during_query(tmp_path):
    store = _store(tmp_path)
    store.services.space_id = "space-before"

    class _RuntimeDimension:
        _active_embedding_dimension = 2

    runtime = _RuntimeDimension()
    store.services.embeddings = runtime
    query_calls = []

    def embed(texts, **kwargs):
        if kwargs.get("query", False):
            query_calls.append(list(texts))
            if len(query_calls) == 1:
                store.services.space_id = "space-after"
                runtime._active_embedding_dimension = 3
            dimension = runtime._active_embedding_dimension
            return {
                "success": True,
                "embedding_space_id": store.services.space_id,
                "embeddings": [[1.0] * dimension for _ in texts],
            }
        return {"success": True, "embedding_space_id": store.services.space_id, "embeddings": []}

    store.services.embed = embed

    first = store.search("same query", use_reranker=False, workspace="same-workspace")
    second = store.search("same query", use_reranker=False, workspace="same-workspace")

    assert first["success"] is True
    assert second["search_cache"]["hit"] is True
    assert len(query_calls) == 1


def test_hybrid_fts_excludes_foreign_and_empty_embedding_spaces(tmp_path):
    store = _store(tmp_path)
    store.services.space_id = "space-current"
    store.services.embed = lambda texts, *_args, **_kwargs: {
        "success": True,
        "embedding_space_id": "space-current",
        "embeddings": [[1.0, 0.0] for _ in texts],
    }
    root = tmp_path / "project"
    root.mkdir()
    (root / "current.py").write_text("# sharedprobe current\ndef current():\n    return 1\n", encoding="utf-8")
    (root / "foreign.py").write_text("# sharedprobe foreign\ndef foreign():\n    return 2\n", encoding="utf-8")
    (root / "legacy.py").write_text("# sharedprobe legacy\ndef legacy():\n    return 3\n", encoding="utf-8")
    workspace = "hybrid-spaces"
    indexed = store.index(str(root), workspace=workspace)
    assert indexed["success"] is True, indexed
    with closing(store._connect()) as con:
        con.execute(
            "UPDATE chunks SET embedding_space='space-old' WHERE workspace=? AND path='foreign.py'",
            (workspace),
        )
        con.execute(
            "UPDATE chunks SET embedding_space='' WHERE workspace=? AND path='legacy.py'",
            (workspace),
        )
        con.executemany(
            "INSERT INTO chunk_fts(workspace,path,chunk_no,text) VALUES(?,?,?,?)",
            [
                (workspace, "current.py", 0, "sharedprobe current"),
                (workspace, "foreign.py", 0, "sharedprobe foreign"),
                (workspace, "legacy.py", 0, "sharedprobe legacy"),
            ],
        )
        con.commit()

    result = store._search_uncached("sharedprobe", workspace, use_reranker=False)

    assert [row["path"] for row in result["results"]] == ["current.py"]

    store.services.embed = lambda *_args, **_kwargs: {"success": False, "error": "offline"}
    lexical = store._search_uncached("sharedprobe", workspace, use_reranker=False)

    assert {row["path"] for row in lexical["results"]} == {"current.py", "foreign.py", "legacy.py"}
    assert lexical["retrieval_mode"] == "lexical_fallback"
    assert lexical["lexical_backend"] == "fts5"


def test_uncertain_fts_paths_do_not_consume_candidate_limit(tmp_path, monkeypatch):
    store = _store(tmp_path)
    workspace = "uncertainty-limit"
    with closing(store._connect()) as con:
        for chunk_no in range(20):
            text = "needle " * 12
            con.execute(
                "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
                "VALUES(?,?,?,?,?,?,?)",
                (workspace, "uncertain.py", chunk_no, f"u{chunk_no}", text, "[1.0,0.0]", "space"),
            )
            con.execute(
                "INSERT INTO chunk_fts(workspace,path,chunk_no,text) VALUES(?,?,?,?)",
                (workspace, "uncertain.py", chunk_no, text),
            )
        con.execute(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?)",
            (workspace, "healthy.py", 0, "healthy", "needle healthy", "[1.0,0.0]", "space"),
        )
        con.execute(
            "INSERT INTO chunk_fts(workspace,path,chunk_no,text) VALUES(?,?,?,?)",
            (workspace, "healthy.py", 0, "needle healthy"),
        )
        store._update_workspace_read_uncertainty(
            con, workspace, uncertain_paths={"uncertain.py"}
        )
        con.commit()
    store.services.embed = lambda *_args, **_kwargs: {"success": False, "error": "offline"}
    monkeypatch.setattr(store, "_search_token_overlap", lambda *_args, **_kwargs: [])

    result = store._search_uncached("needle", workspace,  top_k=1, use_reranker=False)

    assert [row["path"] for row in result["results"]] == ["healthy.py"]


def test_unresolved_embedding_uses_explicit_lexical_fallback(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.services.embed = lambda *_args, **_kwargs: {"success": False, "error": "offline"}
    monkeypatch.setattr(store, "_search_fts_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        store,
        "_search_token_overlap",
        lambda *_args, **_kwargs: [{"path": "lexical.py", "chunk_no": 0, "text": "needle text", "content_hash": "h", "fts_score": 1.0}],
    )

    result = store._search_uncached("needle", "lexical-workspace", use_reranker=False)

    assert [row["path"] for row in result["results"]] == ["lexical.py"]
    assert result["degraded"] is True
    assert result["retrieval_mode"] == "lexical_fallback"
    assert result["lexical_backend"] == "token_overlap"


def test_project_policy_identity_retries_transient_publish_lock(tmp_path, monkeypatch):
    store = _store(tmp_path)
    root = tmp_path / "policy-lock-project"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        'exclude_paths = ["vendor/**"]\n', encoding="utf-8"
    )
    context = store.project_context(root)
    assert context is not None
    assert context.config_digest
    workspace = "policy-lock-workspace"
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

    removed = store._sync_workspace_project_policy_identity(
        root, workspace, context
    )

    assert removed == 0
    assert state["begins"] == 2
    key = store._workspace_project_config_key(
        workspace, store._project_root_identity(root)
    )
    with closing(original_connect()) as con:
        row = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
    assert row is not None
    assert row[0] == context.config_digest


def test_project_policy_identity_does_not_commit_stale_concurrent_snapshot(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    root = tmp_path / "policy-race-project"
    vendor = root / "vendor"
    vendor.mkdir(parents=True)
    source = vendor / "old.py"
    source.write_text("old indexed source\n", encoding="utf-8")
    config_path = root / ".local-ai.toml"
    config_path.write_text('exclude_paths = ["initial/**"]\n', encoding="utf-8")
    workspace = "policy-race-workspace"

    initial = store.project_context(root)
    assert initial is not None
    store._sync_workspace_project_policy_identity(root, workspace, initial)
    stat = source.stat()
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO files VALUES(?,?,?,?,?)",
            (workspace, "vendor/old.py", stat.st_mtime_ns, stat.st_size, "old-hash"),
        )
        con.execute(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?,?)",
            (workspace, "vendor/old.py", 0, "old-hash", "old indexed source", "[]", "space"),
        )
        con.commit()

    config_path.write_text('exclude_paths = ["other/**"]\n', encoding="utf-8")
    stale_context = store.project_context(root)
    assert stale_context is not None
    config_path.write_text('exclude_paths = ["vendor/**"]\n', encoding="utf-8")
    current_context = store.project_context(root)
    assert current_context is not None

    entered_scan = threading.Event()
    release_scan = threading.Event()
    original_path_decision = store._project_path_decision

    def pause_stale_scan(scan_root, path, context, *, phase, size_bytes):
        if context.config_digest == stale_context.config_digest:
            entered_scan.set()
            assert release_scan.wait(3)
        return original_path_decision(
            scan_root, path, context, phase=phase, size_bytes=size_bytes
        )

    monkeypatch.setattr(store, "_project_path_decision", pause_stale_scan)
    outcome = {}

    def run_stale_sync():
        try:
            outcome["value"] = store._sync_workspace_project_policy_identity(
                root, workspace, stale_context
            )
        except Exception as exc:  # captured for assertion in the test thread
            outcome["error"] = exc

    worker = threading.Thread(target=run_stale_sync, daemon=True)
    worker.start()
    assert entered_scan.wait(3)
    removed = store._sync_workspace_project_policy_identity(
        root, workspace, current_context
    )
    release_scan.set()
    worker.join(3)

    assert not worker.is_alive()
    assert removed == 1
    assert isinstance(outcome.get("error"), rag_module.ProjectPolicySyncError)
    assert outcome["error"].retryable is True
    key = store._workspace_project_config_key(
        workspace, store._project_root_identity(root)
    )
    with closing(store._connect()) as con:
        digest = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()[0]
        remaining = con.execute(
            "SELECT COUNT(*) FROM chunks WHERE workspace=?",
            (workspace),
        ).fetchone()[0]
    assert digest == current_context.config_digest
    assert remaining == 0


@pytest.mark.parametrize("error_code", [errno.EACCES, errno.EIO])
def test_project_policy_identity_does_not_prune_on_transient_stat_error(
    tmp_path, monkeypatch, error_code
):
    store = _store(tmp_path)
    root = tmp_path / f"policy-stat-{error_code}"
    root.mkdir()
    source = root / "denied.py"
    source.write_text("retained source\n", encoding="utf-8")
    config_path = root / ".local-ai.toml"
    config_path.write_text('exclude_paths = ["initial/**"]\n', encoding="utf-8")
    workspace = f"policy-stat-workspace-{error_code}"
    old_context = store.project_context(root)
    assert old_context is not None
    store._sync_workspace_project_policy_identity(root, workspace, old_context)
    stat = source.stat()
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO files VALUES(?,?,?,?,?)",
            (workspace, "denied.py", stat.st_mtime_ns, stat.st_size, "file-hash"),
        )
        con.execute(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?,?)",
            (workspace, "denied.py", 0, "file-hash", "retained source", "[]", "space"),
        )
        con.commit()
    config_path.write_text('exclude_paths = ["other/**"]\n', encoding="utf-8")
    new_context = store.project_context(root)
    assert new_context is not None

    original_stat = Path.stat

    def fail_indexed_path(path, *args, **kwargs):
        if path == source:
            raise OSError(error_code, "transient indexed-path stat failure")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_indexed_path)
    with pytest.raises(rag_module.ProjectPolicySyncError) as error:
        store._sync_workspace_project_policy_identity(root, workspace, new_context)

    assert error.value.retryable is True
    key = store._workspace_project_config_key(
        workspace, store._project_root_identity(root)
    )
    uncertain_key = store._workspace_read_uncertainty_key(workspace)
    with closing(store._connect()) as con:
        digest = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()[0]
        file_count = con.execute(
            "SELECT COUNT(*) FROM files WHERE workspace=?",
            (workspace),
        ).fetchone()[0]
        chunk_count = con.execute(
            "SELECT COUNT(*) FROM chunks WHERE workspace=?",
            (workspace),
        ).fetchone()[0]
        uncertain = con.execute(
            "SELECT value FROM rag_meta WHERE key=?", (uncertain_key,)
        ).fetchone()[0]
    assert digest == old_context.config_digest
    assert file_count == chunk_count == 1
    assert "denied.py" in uncertain


def test_project_policy_identity_prunes_confirmed_missing_path(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "policy-missing-project"
    root.mkdir()
    config_path = root / ".local-ai.toml"
    config_path.write_text('exclude_paths = ["initial/**"]\n', encoding="utf-8")
    workspace = "policy-missing-workspace"
    old_context = store.project_context(root)
    assert old_context is not None
    store._sync_workspace_project_policy_identity(root, workspace, old_context)
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO files VALUES(?,?,?,?,?)",
            (workspace, "missing.py", 1, 1, "missing-hash"),
        )
        con.execute(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?,?)",
            (workspace, "missing.py", 0, "missing-hash", "gone", "[]", "space"),
        )
        con.commit()
    config_path.write_text('exclude_paths = ["other/**"]\n', encoding="utf-8")
    new_context = store.project_context(root)
    assert new_context is not None

    assert store._sync_workspace_project_policy_identity(
        root, workspace, new_context
    ) == 1
    key = store._workspace_project_config_key(
        workspace, store._project_root_identity(root)
    )
    with closing(store._connect()) as con:
        digest = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()[0]
        remaining = con.execute(
            "SELECT COUNT(*) FROM chunks WHERE workspace=?",
            (workspace),
        ).fetchone()[0]
    assert digest == new_context.config_digest
    assert remaining == 0


def test_project_policy_identity_rejects_workspace_bound_to_another_root(tmp_path):
    store = _store(tmp_path)
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    source = root_a / "from-a.py"
    source.write_text("root a source\n", encoding="utf-8")
    workspace = "shared-explicit-workspace"
    context_a = store.project_context(root_a)
    context_b = store.project_context(root_b)
    assert context_a is not None and context_b is not None
    store._sync_workspace_project_policy_identity(root_a, workspace, context_a)
    stat = source.stat()
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO files VALUES(?,?,?,?,?)",
            (workspace, "from-a.py", stat.st_mtime_ns, stat.st_size, "root-a-hash"),
        )
        con.execute(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?,?)",
            (workspace, "from-a.py", 0, "root-a-hash", "root a source", "[]", "space"),
        )
        con.commit()

    with pytest.raises(rag_module.ProjectPolicySyncError) as error:
        store._sync_workspace_project_policy_identity(root_b, workspace, context_b)

    assert error.value.retryable is False
    root_key = store._workspace_root_identity_key(workspace)
    with closing(store._connect()) as con:
        bound_root = con.execute(
            "SELECT value FROM rag_meta WHERE key=?", (root_key,)
        ).fetchone()[0]
        paths = con.execute(
            "SELECT path FROM files WHERE workspace=?",
            (workspace),
        ).fetchall()
    assert bound_root == store._project_root_identity(root_a)
    assert [row[0] for row in paths] == ["from-a.py"]


def test_index_paths_step_retries_uncertain_only_publish_lock(tmp_path, monkeypatch):
    store = _store(tmp_path)
    root = tmp_path / "uncertain-lock-project"
    root.mkdir()
    (root / "unreadable.py").write_text("content", encoding="utf-8")
    monkeypatch.setattr(rag_module, "_read_bounded_file", lambda *_args: None)
    state = {"begins": 0, "failures": 1}

    class _FlakyConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE":
                state["begins"] += 1
                # Identity sync and first uncertainty publish succeed. Inject one
                # busy failure in the uncertain-only follow-up transaction.
                if state["begins"] == 3 and state["failures"]:
                    state["failures"] -= 1
                    raise sqlite3.OperationalError("database is locked")
            return self._connection.execute(sql, *args)

        def close(self):
            self._connection.close()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    original_connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _FlakyConnection(original_connect()))

    result = store.index_paths_step(str(root), workspace="uncertain-lock-workspace", paths=["unreadable.py"])

    assert result["success"] is True
    assert result["read_uncertain_paths"] == ["unreadable.py"]
    assert state["begins"] == 4
    key = workspace
    with closing(original_connect()) as con:
        uncertain = store._workspace_read_uncertain_paths(
            con, key, "uncertain-lock-workspace"
        )
    assert uncertain == {"unreadable.py"}


def test_rag_index_retries_transient_publish_lock(tmp_path, monkeypatch):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "locked.py").write_text("def locked():\n    return 1\n", encoding="utf-8")
    workspace = "locked-workspace"
    store._sync_workspace_project_policy_identity(
        root, workspace, store.project_context(root)
    )

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

    result = store.index(str(root), workspace=workspace)

    assert result["success"] is True
    assert state["begins"] == 2
    assert len(store.services.calls) == 1


def test_unresolved_embedding_token_fallback_is_explicit(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.services.embed = lambda *_args, **_kwargs: {"success": False, "error": "offline"}
    monkeypatch.setattr(store, "_search_fts_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(store, "_search_token_overlap", lambda *_args, **_kwargs: [
        {"path": "lexical.py", "chunk_no": 0, "text": "needle text", "content_hash": "h", "fts_score": 1.0}
    ])
    result = store._search_uncached("needle", "lexical-workspace", use_reranker=False)
    assert [row["path"] for row in result["results"]] == ["lexical.py"]
    assert result["degraded"] is True
    assert result["retrieval_mode"] == "lexical_fallback"
    assert result["lexical_backend"] == "token_overlap"


def test_cross_workspace_legacy_embeddings_are_recomputed_in_every_index_path(tmp_path):
    text = "def shared_legacy():\n    return 17\n"
    for mode in ("index", "index_step", "index_paths_step"):
        services = _Services()
        services.space_id = f"space-{mode}"
        store = _store(tmp_path / mode)
        store.services = services
        with closing(store._connect()) as con:
            con.execute(
                "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?)",
                ("source-workspace", "shared.py", 0, _fragment_hash(text), text, "[99.0,99.0]", ""),
            )
            con.commit()
        root = tmp_path / f"target-{mode}"
        root.mkdir()
        (root / "shared.py").write_text(text, encoding="utf-8")
        calls_before = len(services.calls)
        if mode == "index":
            result = store.index(str(root), workspace="target-workspace")
            workspace = "target-workspace"
        elif mode == "index_step":
            result = store.index_step(str(root), max_files=2)
            workspace = result["workspace"]
        else:
            workspace = "target-workspace"
            result = store.index_paths_step(str(root), workspace=workspace, paths=["shared.py"])
        assert result["success"] is True, result
        embedded_texts = [
            item
            for batch in services.calls[calls_before:]
            for item in batch
            if text in item.replace("\r\n", "\n")
        ]
        assert embedded_texts, (mode, result, services.calls[calls_before:])
        with closing(store._connect()) as con:
            row = con.execute(
                "SELECT embedding,embedding_space FROM chunks WHERE workspace=? AND path='shared.py'",
                (workspace),
            ).fetchone()
        assert row is not None and row[1] == f"space-{mode}"
        vector = (
            struct.unpack(f"{len(row[0]) // 4}f", row[0])
            if isinstance(row[0], bytes)
            else json.loads(row[0])
        )
        assert tuple(vector) == (float(len(embedded_texts[0])), 1.0)


def test_rag_index_paths_step_retries_publish_lock_without_reembedding(tmp_path, monkeypatch):
    store = _store(tmp_path)
    root = tmp_path / "project-step"
    root.mkdir()
    (root / "locked.py").write_text("def locked_step():\n    return 1\n", encoding="utf-8")
    workspace = "step-workspace"
    store._sync_workspace_project_policy_identity(
        root, workspace, store.project_context(root)
    )
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

    result = store.index_paths_step(str(root), workspace=workspace, paths=["locked.py"])

    assert result["success"] is True
    assert state["begins"] == 2
    assert len(store.services.calls) == 1
