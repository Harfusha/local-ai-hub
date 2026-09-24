from __future__ import annotations

import threading
import sqlite3
from contextlib import closing

from local_ai_hub.rag import RAGStore, _fragment_hash


class _Services:
    def __init__(self, block: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = block

    def embed(self, texts, _tenant, **_kwargs):
        batch = list(texts)
        self.calls.append(batch)
        self.started.set()
        if self.block:
            assert self.release.wait(2)
        return {"success": True, "embeddings": [[float(len(text)), 1.0] for text in batch]}


class _Reranker:
    pass


def _store(tmp_path, services: _Services) -> RAGStore:
    return RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {"extensions": [".py"], "ignore_dirs": [], "chunk_chars": 4096, "chunk_overlap_chars": 0},
            "resilience": {"singleflight_wait_timeout_seconds": 2},
        },
        services,
        _Reranker(),
    )


def test_fragment_hash_reuses_crlf_and_lf_content():
    assert _fragment_hash("def same():\r\n    return 1\r\n") == _fragment_hash("def same():\n    return 1\n")


def test_postprocess_keeps_highest_ranked_unique_evidence():
    payload = {
        "success": True,
        "results": [
            {"content_hash": "same", "text": "first"},
            {"content_hash": "same", "text": "duplicate"},
            {"content_hash": "other", "text": "second"},
            {"content_hash": "third", "text": "trimmed"},
        ],
    }

    result = RAGStore._postprocess_search_payload(payload, 2)

    assert [row["text"] for row in result["results"]] == ["first", "second"]
    assert result["deterministic_postprocess"] == {"deduplicated": 2}


def test_index_embeds_identical_fragments_once(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = "def same():\n    return 1\n"
    (root / "one.py").write_text(source, encoding="utf-8")
    (root / "two.py").write_text(source, encoding="utf-8")
    services = _Services()

    result = _store(tmp_path, services).index(str(root), "tenant")

    assert result["success"] is True
    assert len(services.calls) == 1
    assert [_fragment_hash(text) for text in services.calls[0]] == [_fragment_hash(source)]


def test_index_coalesces_identical_concurrent_requests(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "one.py").write_text("def same():\n    return 1\n", encoding="utf-8")
    services = _Services(block=True)
    store = _store(tmp_path, services)
    first: dict[str, object] = {}
    second: dict[str, object] = {}

    first_thread = threading.Thread(target=lambda: first.update(store.index(str(root), "tenant")))
    second_thread = threading.Thread(target=lambda: second.update(store.index(str(root), "tenant")))
    first_thread.start()
    assert services.started.wait(2)
    second_thread.start()
    services.release.set()
    first_thread.join(2)
    second_thread.join(2)

    assert first["success"] is True
    assert second["success"] is True
    assert second["coalesced"] is True
    assert len(services.calls) == 1


def test_index_paths_step_cancellation_after_embedding_preserves_old_snapshot(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "one.py"
    source.write_text("def old_value():\n    return 1\n", encoding="utf-8")
    services = _Services()
    store = _store(tmp_path, services)
    workspace = store.workspace_id(str(root))
    assert store.index(str(root), "tenant", workspace=workspace)["success"] is True

    source.write_text("def new_value():\n    return 2\n", encoding="utf-8")
    checks = iter((False, False, True))
    result = store.index_paths_step(
        str(root), "tenant", workspace, ["one.py"], should_yield=lambda: next(checks, False)
    )

    assert result["preempted"] is True
    with closing(store._connect()) as con:
        texts = [row[0] for row in con.execute(
            "SELECT text FROM chunks WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), workspace, "one.py"),
        ).fetchall()]
    assert any("old_value" in text for text in texts)
    assert not any("new_value" in text for text in texts)

def test_index_step_cancellation_after_embedding_and_deletion_preserves_snapshot(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    keep = root / "keep.py"
    removed = root / "removed.py"
    added = root / "added.py"
    keep.write_text("def old_value():\n    return 1\n", encoding="utf-8")
    removed.write_text("def removed_value():\n    return 3\n", encoding="utf-8")
    services = _Services()
    store = _store(tmp_path, services)
    workspace = store.workspace_id(str(root))
    assert store.index(str(root), "tenant", workspace=workspace)["success"] is True
    services.calls.clear()
    with closing(store._connect()) as con:
        before = con.execute(
            "SELECT path,chunk_no,content_hash,text,embedding FROM chunks WHERE tenant=? AND workspace=? ORDER BY path,chunk_no",
            (store._scope_key("tenant"), workspace),
        ).fetchall()

    keep.write_text("def new_value():\n    return 2\n", encoding="utf-8")
    removed.unlink()
    added.write_text("def added_value():\n    return 4\n", encoding="utf-8")
    result = store.index_step(
        str(root), "tenant", workspace=workspace, max_files=3,
        should_yield=lambda: bool(services.calls),
    )

    assert result["preempted"] is True
    assert services.calls
    with closing(store._connect()) as con:
        after = con.execute(
            "SELECT path,chunk_no,content_hash,text,embedding FROM chunks WHERE tenant=? AND workspace=? ORDER BY path,chunk_no",
            (store._scope_key("tenant"), workspace),
        ).fetchall()
    assert after == before

def test_indexed_chunk_reuse_isolated_by_embedding_space(tmp_path):
    class _SpaceServices(_Services):
        def __init__(self):
            super().__init__()
            self.space_id = "model-a@revision-1"

        def embed(self, texts, tenant, **kwargs):
            result = super().embed(texts, tenant, **kwargs)
            result["embedding_space_id"] = self.space_id
            return result

    services = _SpaceServices()
    store = _store(tmp_path, services)
    root_a = tmp_path / "project-a"
    root_b = tmp_path / "project-b"
    root_a.mkdir()
    root_b.mkdir()
    text = "def shared_function():\n    return 7\n"
    (root_a / "shared.py").write_text(text, encoding="utf-8")
    (root_b / "shared.py").write_text(text, encoding="utf-8")
    workspace_a = store.workspace_id(str(root_a))
    workspace_b = store.workspace_id(str(root_b))

    assert store.index_paths_step(str(root_a), "tenant", workspace_a, ["shared.py"])["success"] is True
    first_call_count = len(services.calls)
    services.space_id = "model-b@revision-1"
    assert store.index_paths_step(str(root_b), "tenant", workspace_b, ["shared.py"])["success"] is True

    assert len(services.calls) > first_call_count
    with closing(store._connect()) as con:
        spaces = con.execute(
            "SELECT DISTINCT embedding_space FROM chunks WHERE tenant=? ORDER BY embedding_space",
            (store._scope_key("tenant"),),
        ).fetchall()
    assert [row[0] for row in spaces] == ["model-a@revision-1", "model-b@revision-1"]


def test_reused_chunks_keep_original_space_when_embedder_falls_back(tmp_path):
    class _FallbackServices(_Services):
        def __init__(self):
            super().__init__()
            self.space_id = "model-a@revision-1"
            self.output_space = self.space_id

        def embed(self, texts, tenant, **kwargs):
            result = super().embed(texts, tenant, **kwargs)
            result["embedding_space_id"] = self.output_space
            return result

    services = _FallbackServices()
    store = _store(tmp_path, services)
    source_root = tmp_path / "source"
    source_root.mkdir()
    shared_text = "def shared_value():\n    return 1\n"
    (source_root / "shared.py").write_text(shared_text, encoding="utf-8")
    assert store.index(str(source_root), "tenant", workspace="source")["success"] is True

    for mode in ("index", "index_paths_step"):
        target_root = tmp_path / mode
        target_root.mkdir()
        (target_root / "shared.py").write_text(shared_text, encoding="utf-8")
        (target_root / "new.py").write_text("def new_value():\n    return 2\n", encoding="utf-8")
        services.output_space = "model-b@revision-2"
        workspace = f"target:{mode}"
        if mode == "index":
            result = store.index(str(target_root), "tenant", workspace=workspace)
        else:
            result = store.index_paths_step(
                str(target_root), "tenant", workspace, ["shared.py", "new.py"]
            )
        assert result["success"] is True
        with closing(store._connect()) as con:
            spaces = dict(con.execute(
                "SELECT path,embedding_space FROM chunks WHERE tenant=? AND workspace=?",
                (store._scope_key("tenant"), workspace),
            ).fetchall())
        assert spaces["shared.py"] == "model-a@revision-1"
        assert spaces["new.py"] == "model-b@revision-2"


def test_index_publish_disk_full_keeps_previous_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "one.py"
    source.write_text("def old_value():\n    return 1\n", encoding="utf-8")
    services = _Services()
    store = _store(tmp_path, services)
    workspace = store.workspace_id(str(root))
    assert store.index(str(root), "tenant", workspace=workspace)["success"] is True
    source.write_text("def new_value():\n    return 2\n", encoding="utf-8")

    class _DiskFullConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args):
            return self._connection.execute(sql, *args)

        def executemany(self, sql, rows):
            if sql.startswith("INSERT INTO chunks"):
                raise sqlite3.OperationalError("database or disk is full")
            return self._connection.executemany(sql, rows)

        def close(self):
            self._connection.close()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _DiskFullConnection(connect()))
    result = store.index(str(root), "tenant", workspace=workspace)
    monkeypatch.setattr(store, "_connect", connect)

    assert result["success"] is False
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT text FROM chunks WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), workspace, "one.py"),
        ).fetchall()
    assert any("old_value" in row[0] for row in rows)
    assert not any("new_value" in row[0] for row in rows)


def test_independent_stores_publish_concurrently_without_partial_snapshot(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "one.py").write_text("def first():\n    return 1\n", encoding="utf-8")
    (root / "two.py").write_text("def second():\n    return 2\n", encoding="utf-8")
    rendezvous = threading.Barrier(2)

    class _ConcurrentServices:
        def embed(self, texts, _tenant, **_kwargs):
            rendezvous.wait(timeout=3)
            return {"success": True, "embeddings": [[float(len(text)), 1.0] for text in texts]}

    store_one = _store(tmp_path, _ConcurrentServices())
    store_two = _store(tmp_path, _ConcurrentServices())
    workspace = store_one.workspace_id(str(root))
    results: list[dict[str, object]] = []
    failures: list[BaseException] = []

    def publish(store):
        try:
            results.append(store.index(str(root), "tenant", workspace=workspace))
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=publish, args=(store,)) for store in (store_one, store_two)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert failures == []
    assert len(results) == 2
    assert all(result["success"] is True for result in results)
    with closing(store_one._connect()) as con:
        rows = con.execute(
            "SELECT path, text FROM chunks WHERE tenant=? AND workspace=? ORDER BY path",
            (store_one._scope_key("tenant"), workspace),
        ).fetchall()
    assert {row[0] for row in rows} == {"one.py", "two.py"}
