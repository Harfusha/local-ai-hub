from __future__ import annotations

import io
import os
import threading
import sqlite3
import json
import struct
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.rag import RAGStore, _fragment_hash


class _Services:
    def __init__(self, block: bool = False, space_id: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = block
        self.space_id = space_id

    def embed(self, texts, _tenant, **_kwargs):
        batch = list(texts)
        self.calls.append(batch)
        self.started.set()
        if self.block:
            assert self.release.wait(2)
        result = {"success": True, "embeddings": [[float(len(text)), 1.0] for text in batch]}
        if self.space_id:
            result["embedding_space_id"] = self.space_id
        return result


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


@pytest.mark.parametrize("defer_worker_until_embedding", [False, True])
def test_index_coalesces_identical_concurrent_requests(tmp_path, monkeypatch, defer_worker_until_embedding):
    root = tmp_path / "project"
    root.mkdir()
    (root / "one.py").write_text("def same():\n    return 1\n", encoding="utf-8")
    services = _Services()
    store = _store(tmp_path, services)
    second: dict[str, object] = {}
    errors: list[BaseException] = []
    follower_waiting = threading.Event()
    leader_at_embedding = threading.Event()
    original_embed = services.embed
    original_index = store.index
    main_thread = threading.current_thread()

    def scheduled_index(*args, **kwargs):
        if defer_worker_until_embedding and threading.current_thread() is not main_thread:
            # Deterministically model a worker unable to run pre-embedding
            # setup until the owner is ready, without sleeps or CPU load.
            assert leader_at_embedding.wait(2)
        return original_index(*args, **kwargs)

    monkeypatch.setattr(store, "index", scheduled_index)

    def follow():
        try:
            second.update(store.index(str(root), "tenant"))
        except BaseException as exc:
            errors.append(exc)

    second_thread = threading.Thread(target=follow)

    def embed_with_waiting_follower(texts, tenant, **kwargs):
        # Leader setup runs synchronously: policy/discovery/SQLite readiness is
        # not a two-second background-thread startup requirement of coalescing.
        leader_at_embedding.set()
        with store._index_flights_lock:
            assert len(store._index_flights) == 1
            flight = next(iter(store._index_flights.values()))
        original_wait = flight["event"].wait

        def observe_wait(timeout=None):
            follower_waiting.set()
            return original_wait(timeout)

        # Observe the real completion event; do not replace singleflight or its
        # result. Thread.start alone does not prove the follower joined it.
        monkeypatch.setattr(flight["event"], "wait", observe_wait)
        second_thread.start()
        assert follower_waiting.wait(2), {"result": second, "errors": errors}
        return original_embed(texts, tenant, **kwargs)

    monkeypatch.setattr(services, "embed", embed_with_waiting_follower)
    try:
        first = store.index(str(root), "tenant")
    finally:
        if second_thread.ident is not None:
            second_thread.join(2)

    assert not second_thread.is_alive(), {"result": second, "errors": errors}
    assert not errors
    assert first["success"] is True, first
    assert second["success"] is True, second
    assert second["coalesced"] is True
    assert {key: value for key, value in second.items() if key != "coalesced"} == first
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


def test_same_workspace_blank_space_chunk_is_reembedded_not_relabelled(tmp_path):
    class _SpaceServices(_Services):
        def __init__(self):
            super().__init__()
            self.space_id = "space-current"

        def embed(self, texts, tenant, **kwargs):
            result = super().embed(texts, tenant, **kwargs)
            result["embedding_space_id"] = self.space_id
            return result

    services = _SpaceServices()
    store = _store(tmp_path, services)
    root = tmp_path / "project"
    root.mkdir()
    (root / "same.py").write_text("def same_value():\n    return 4\n", encoding="utf-8")
    workspace = "same-workspace"
    assert store.index_paths_step(str(root), "tenant", workspace, ["same.py"])["success"]
    calls_before = len(services.calls)
    with closing(store._connect()) as con:
        con.execute(
            "UPDATE chunks SET embedding='[99.0,99.0]',embedding_space='' "
            "WHERE tenant=? AND workspace=? AND path='same.py'",
            (store._scope_key("tenant"), workspace),
        )
        con.commit()

    result = store.index_paths_step(str(root), "tenant", workspace, ["same.py"])

    assert result["success"] is True
    assert len(services.calls) > calls_before
    with closing(store._connect()) as con:
        row = con.execute(
            "SELECT text,embedding,embedding_space FROM chunks "
            "WHERE tenant=? AND workspace=? AND path='same.py'",
            (store._scope_key("tenant"), workspace),
        ).fetchone()
    vector = struct.unpack(f"{len(row[1]) // 4}f", row[1]) if isinstance(row[1], bytes) else json.loads(row[1])
    assert row[2] == "space-current"
    assert tuple(vector) == (float(len(row[0])), 1.0)


def test_reused_chunks_keep_original_space_when_embedder_falls_back(tmp_path):
    class _FallbackServices(_Services):
        def __init__(self):
            super().__init__()
            self.space_id = "model-a@revision-1"
            self.output_space = self.space_id

        def embed(self, texts, tenant, **kwargs):
            result = super().embed(texts, tenant, **kwargs)
            result["embeddings"] = [
                [float(len(text)), float(ord(self.output_space[6]))]
                for text in texts
            ]
            result["embedding_space_id"] = self.output_space
            return result

    services = _FallbackServices()
    store = _store(tmp_path, services)
    source_root = tmp_path / "source"
    source_root.mkdir()
    shared_text = "def shared_value():\n    return 1\n"
    (source_root / "shared.py").write_text(shared_text, encoding="utf-8")
    assert store.index(str(source_root), "tenant", workspace="source")["success"] is True
    with closing(store._connect()) as con:
        source_embedding = con.execute(
            "SELECT embedding FROM chunks WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), "source", "shared.py"),
        ).fetchone()[0]

    for mode in ("index", "index_paths_step", "index_step"):
        target_root = tmp_path / mode
        target_root.mkdir()
        (target_root / "shared.py").write_text(shared_text, encoding="utf-8")
        (target_root / "new.py").write_text("def new_value():\n    return 2\n", encoding="utf-8")
        services.output_space = "model-b@revision-2"
        workspace = f"target:{mode}"
        if mode == "index":
            result = store.index(str(target_root), "tenant", workspace=workspace)
        elif mode == "index_paths_step":
            result = store.index_paths_step(
                str(target_root), "tenant", workspace, ["shared.py", "new.py"]
            )
        else:
            result = store.index_step(
                str(target_root), "tenant", workspace=workspace, max_files=2
            )
        assert result["success"] is True
        with closing(store._connect()) as con:
            rows = {
                row[0]: (row[1], row[2])
                for row in con.execute(
                "SELECT path,embedding_space,embedding FROM chunks WHERE tenant=? AND workspace=?",
                (store._scope_key("tenant"), workspace),
                ).fetchall()
            }
        assert rows["shared.py"][0] == "model-b@revision-2"
        assert rows["new.py"][0] == "model-b@revision-2"
        value = rows["shared.py"][1]
        embedding = (
            struct.unpack(f"{len(value) // 4}f", value)
            if isinstance(value, bytes)
            else json.loads(value)
        )
        assert tuple(embedding) == (float(len(shared_text)), float(ord("b")))
        assert rows["shared.py"][1] != source_embedding
def test_same_workspace_blank_space_chunk_is_reembedded_not_relabelled(tmp_path):
    services = _Services(space_id="space-current")
    store = _store(tmp_path, services)
    root = tmp_path / "project"
    root.mkdir()
    source = root / "same.py"
    source.write_text("def same_value():\n    return 4\n", encoding="utf-8")
    workspace = "same-workspace"
    assert store.index_paths_step(str(root), "tenant", workspace, ["same.py"])["success"]
    calls_before = len(services.calls)
    with closing(store._connect()) as con:
        con.execute(
            "UPDATE chunks SET embedding='[99.0, 99.0]', embedding_space='' "
            "WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), workspace, "same.py"),
        )
        con.commit()

    result = store.index_paths_step(str(root), "tenant", workspace, ["same.py"])

    assert result["success"] is True
    assert len(services.calls) > calls_before
    with closing(store._connect()) as con:
        row = con.execute(
            "SELECT text,embedding,embedding_space FROM chunks "
            "WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), workspace, "same.py"),
        ).fetchone()
    assert row[2] == "space-current"
    embedding = (
        struct.unpack(f"{len(row[1]) // 4}f", row[1])
        if isinstance(row[1], bytes)
        else json.loads(row[1])
    )
    assert tuple(embedding) == (float(len(row[0])), 1.0)


def test_configured_embedding_space_id_is_stable_across_store_instances(tmp_path):
    first = _store(tmp_path, _Services())
    second = _store(tmp_path, _Services())

    assert first._embedding_space_id() == second._embedding_space_id()


def test_index_fingerprint_tracks_embedding_space_configuration(tmp_path):
    base_models = {
        "embedding": "model-a",
        "embedding_backend": "ollama",
        "embedding_dimension": 2,
        "embedding_normalized": False,
        "embedding_digest": "digest-a",
        "embedding_revision": "revision-a",
    }

    def make_store(state_name, models):
        return RAGStore(
            {
                "server": {"state_dir": str(tmp_path / state_name)},
                "models": models,
                "cpu_retrieval": {},
                "workspace_cache": {},
                "rag": {"extensions": [".py"], "ignore_dirs": []},
            },
            _Services(),
            _Reranker(),
        )

    baseline = make_store("fingerprint-base", base_models).index_fingerprint
    changed = [
        {"embedding_digest": "digest-b"},
        {"embedding_revision": "revision-b"},
        {"embedding_dimension": 3},
        {"embedding_normalized": True},
    ]

    for index, values in enumerate(changed):
        models = {**base_models, **values}
        assert make_store(f"fingerprint-{index}", models).index_fingerprint != baseline


def test_index_fingerprint_reset_clears_orphaned_fts_rows(tmp_path):
    state_dir = tmp_path / "fingerprint-reset"
    base_models = {
        "embedding": "model-a",
        "embedding_backend": "ollama",
        "embedding_dimension": 2,
        "embedding_digest": "digest-a",
    }

    def make_store(models):
        return RAGStore(
            {
                "server": {"state_dir": str(state_dir)},
                "models": models,
                "cpu_retrieval": {},
                "workspace_cache": {},
                "rag": {"extensions": [".py"], "ignore_dirs": []},
            },
            _Services(),
            _Reranker(),
        )

    first = make_store(base_models)
    scope_key = first._scope_key("tenant")
    with closing(first._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?,?)",
            (scope_key, "workspace", "old.py", 0, "hash", "old text", "[]", "model-a"),
        )
        con.execute(
            "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
            (scope_key, "workspace", "old.py", 1, 8, "hash"),
        )
        con.execute(
            "INSERT INTO chunk_fts(tenant,workspace,path,chunk_no,text) VALUES(?,?,?,?,?)",
            (scope_key, "workspace", "old.py", 0, "old text"),
        )
        con.commit()

    rebuilt = make_store({**base_models, "embedding_digest": "digest-b"})

    assert rebuilt.index_reset is True
    with closing(rebuilt._connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0] == 0


def test_index_reembeds_unchanged_files_when_runtime_space_changes(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "one.py").write_text("def stable():\n    return 1\n", encoding="utf-8")
    services = _Services(space_id="runtime-space-a")
    store = _store(tmp_path, services)

    first = store.index(str(root), "tenant")
    assert first["success"] is True
    first_call_count = len(services.calls)
    services.space_id = "runtime-space-b"

    rebuilt = store.index(str(root), "tenant", workspace=first["workspace"])

    assert rebuilt["success"] is True
    assert len(services.calls) > first_call_count
    with closing(store._connect()) as con:
        spaces = {row[0] for row in con.execute("SELECT DISTINCT embedding_space FROM chunks")}
    assert spaces == {"runtime-space-b"}


def test_cold_unresolved_index_reuses_persisted_workspace_space(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "one.py").write_text("def stable():\n    return 1\n", encoding="utf-8")
    first_services = _Services(space_id="runtime-space-a")
    first_store = _store(tmp_path, first_services)
    first = first_store.index(str(root), "tenant")
    second_services = _Services()
    second_store = _store(tmp_path, second_services)

    reused = second_store.index(str(root), "tenant", workspace=first["workspace"])

    assert reused["success"] is True
    assert reused["embedding_space_id"] == "runtime-space-a"
    assert second_services.calls == []


def test_index_step_rebuilds_only_stale_space_paths_incrementally(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    (root / "two.py").write_text("def two():\n    return 2\n", encoding="utf-8")
    services = _Services(space_id="runtime-space-a")
    store = _store(tmp_path, services)
    first = store.index(str(root), "tenant")
    services.space_id = "runtime-space-b"

    step = store.index_step(str(root), "tenant", workspace=first["workspace"], max_files=1)

    assert step["success"] is True
    assert step["done"] is False
    assert step["processed_files"] == 1
    with closing(store._connect()) as con:
        rows = con.execute("SELECT path, embedding_space FROM chunks ORDER BY path").fetchall()
    spaces_by_path = {path: space for path, space in rows}
    assert len(set(spaces_by_path.values())) == 2


def test_search_cache_tracks_incremental_reindex_generation(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    (root / "two.py").write_text("def two():\n    return 222222\n", encoding="utf-8")
    (root / "three.py").write_text("def three():\n    return 333333333\n", encoding="utf-8")
    services = _Services(space_id="runtime-space-a")
    store = _store(tmp_path, services)
    first = store.index(str(root), "tenant")
    services.space_id = "runtime-space-b"

    initial_step = store.index_step(str(root), "tenant", workspace=first["workspace"], max_files=1)
    assert initial_step["done"] is False
    first_search = store.search("qzxunknown", "tenant", first["workspace"], use_reranker=False)
    repeated_search = store.search("qzxunknown", "tenant", first["workspace"], use_reranker=False)
    assert len(first_search["results"]) == 1
    assert repeated_search["search_cache"]["hit"] is True

    middle_step = store.index_step(str(root), "tenant", workspace=first["workspace"], max_files=1)
    assert middle_step["done"] is False
    middle_search = store.search("qzxunknown", "tenant", first["workspace"], use_reranker=False)
    assert middle_search["search_cache"]["hit"] is False
    assert len(middle_search["results"]) == 2

    final_step = store.index_step(str(root), "tenant", workspace=first["workspace"], max_files=1)
    assert final_step["done"] is True
    rebuilt_search = store.search("qzxunknown", "tenant", first["workspace"], use_reranker=False)

    assert rebuilt_search["search_cache"]["hit"] is False
    assert len(rebuilt_search["results"]) == 3


def test_search_rechecks_generation_after_cache_lookup(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "one.py"
    source.write_text("def old_value():\n    return 1\n", encoding="utf-8")
    store = _store(tmp_path, _Services(space_id="runtime-space-a"))
    indexed = store.index(str(root), "tenant")
    workspace = indexed["workspace"]
    initial = store.search("value query", "tenant", workspace, use_reranker=False)
    assert initial["results"][0]["text"] == "def old_value():\n    return 1\n"

    source.write_text("def new_value():\n    return 2\n", encoding="utf-8")
    original_lookup = store.search_flight.get_or_compute
    interleaved: dict[str, object] = {}

    def publish_before_lookup(key, compute):
        staged = store.index_paths_step(str(root), "tenant", workspace, ["one.py"])
        assert staged["success"] is True
        raw, hit, coalesced = original_lookup(key, compute)
        interleaved["hit"] = hit
        return raw, hit, coalesced

    monkeypatch.setattr(store.search_flight, "get_or_compute", publish_before_lookup)
    result = store.search("value query", "tenant", workspace, use_reranker=False)

    assert interleaved["hit"] is True
    assert result["search_cache"]["hit"] is False
    assert result["results"][0]["text"] == "def new_value():\n    return 2\n"


def test_search_rechecks_generation_after_uncertain_source_read(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "one.py"
    source.write_text("def old_value():\n    return 1\n", encoding="utf-8")
    services = _Services(space_id="runtime-space-a")
    store = _store(tmp_path, services)
    store.config["rag"]["max_file_bytes"] = 32
    indexed = store.index(str(root), "tenant")
    workspace = indexed["workspace"]
    initial = store.search("value query", "tenant", workspace, use_reranker=False)
    assert initial["results"][0]["text"] == "def old_value():\n    return 1\n"

    source.write_text("def new_value():\n    return 2\n", encoding="utf-8")
    original_open = Path.open

    def grow_after_stat(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == source.resolve() and mode == "rb":
            return io.BytesIO(b"x" * 33)
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", grow_after_stat)
    original_lookup = store.search_flight.get_or_compute
    interleaved: dict[str, object] = {}

    def publish_uncertainty_before_lookup(key, compute):
        staged = store.index_paths_step(str(root), "tenant", workspace, ["one.py"])
        assert staged["success"] is True
        assert staged["read_uncertain_paths"] == ["one.py"]
        raw, hit, coalesced = original_lookup(key, compute)
        interleaved["hit"] = hit
        return raw, hit, coalesced

    monkeypatch.setattr(store.search_flight, "get_or_compute", publish_uncertainty_before_lookup)
    result = store.search("value query", "tenant", workspace, use_reranker=False)

    assert interleaved["hit"] is True
    assert result["search_cache"]["hit"] is False
    assert result["results"] == []
    assert result["fallback"] == "source_read_uncertain"


def test_index_step_reindexes_explicit_same_stat_dirty_path(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "one.py"
    original_text = "def value():\n    return 'old'\n"
    updated_text = "def value():\n    return 'new'\n"
    source.write_text(original_text, encoding="utf-8")
    store = _store(tmp_path, _Services(space_id="runtime-space-a"))
    indexed = store.index(str(root), "tenant")
    workspace = indexed["workspace"]
    original_stat = source.stat()

    source.write_text(updated_text, encoding="utf-8")
    assert source.stat().st_size == original_stat.st_size
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    unchanged = store.index_step(str(root), "tenant", workspace=workspace, max_files=1)
    assert unchanged["processed_files"] == 0
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT text FROM chunks WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), workspace, "one.py"),
        ).fetchall()
    assert [row[0] for row in rows] == [original_text]

    updated = store.index_step(
        str(root), "tenant", workspace=workspace, max_files=1, dirty_paths=["one.py"]
    )

    assert updated["processed_files"] == 1
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT text FROM chunks WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), workspace, "one.py"),
        ).fetchall()
    assert [row[0] for row in rows] == [updated_text]


def test_index_step_keeps_unpublished_paths_pending(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "one.py").write_text("def pending():\n    return 1\n", encoding="utf-8")
    store = _store(tmp_path, _Services())
    monkeypatch.setattr(
        store,
        "index_paths_step",
        lambda *_args, **_kwargs: {
            "success": True, "preempted": True, "processed_paths": [], "deleted_paths": []
        },
    )

    result = store.index_step(str(root), "tenant", max_files=1)

    assert result["preempted"] is True
    assert result["done"] is False
    assert result["remaining_changed_files"] == 1


def test_index_step_keeps_skipped_paths_pending(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "one.py").write_text("def unreadable():\n    return 1\n", encoding="utf-8")
    store = _store(tmp_path, _Services())
    monkeypatch.setattr(
        store,
        "index_paths_step",
        lambda *_args, **_kwargs: {
            "success": True, "preempted": False, "processed_paths": [], "deleted_paths": []
        },
    )

    result = store.index_step(str(root), "tenant", max_files=1)

    assert result["done"] is False
    assert result["processed_files"] == 0
    assert result["remaining_changed_files"] == 1


def test_legacy_unidentified_embedding_is_not_reused(tmp_path):
    services = _Services()
    store = _store(tmp_path, services)
    text = "def shared_legacy():\n    return 9\n"
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (store._scope_key("tenant"), "legacy", "shared.py", 0, _fragment_hash(text), text, json.dumps([99.0, 99.0]), ""),
        )
        con.commit()
    root = tmp_path / "target"
    root.mkdir()
    (root / "shared.py").write_text(text, encoding="utf-8")

    result = store.index_paths_step(str(root), "tenant", "target", ["shared.py"])

    assert result["success"] is True
    assert len(services.calls) == 1


def test_incremental_index_does_not_reuse_unidentified_embedding_for_known_space(tmp_path):
    services = _Services(space_id="model-a@revision-1")
    store = _store(tmp_path, services)
    text = "def shared_incremental():\n    return 11\n"
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (store._scope_key("tenant"), "legacy-empty", "shared.py", 0, _fragment_hash(text), text, json.dumps([99.0, 99.0]), ""),
        )
        con.commit()
    root = tmp_path / "incremental-target"
    root.mkdir()
    (root / "shared.py").write_text(text, encoding="utf-8")

    result = store.index_step(str(root), "tenant")

    assert result["success"] is True
    assert len(services.calls) == 1
    with closing(store._connect()) as con:
        row = con.execute(
            "SELECT embedding_space FROM chunks WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), result["workspace"], "shared.py"),
        ).fetchone()
    assert row == ("model-a@revision-1",)


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


def test_search_rechecks_generation_after_uncertain_source_read(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "one.py"
    source.write_text("def old_value():\n    return 1\n", encoding="utf-8")
    store = _store(tmp_path, _Services())
    store.services.space_id = "race-space"
    store.config["rag"]["max_file_bytes"] = 32
    indexed = store.index(str(root), "tenant")
    workspace = indexed["workspace"]
    initial = store.search("value query", "tenant", workspace, use_reranker=False)
    assert initial["results"][0]["text"].replace("\r\n", "\n") == "def old_value():\n    return 1\n"

    source.write_text("def new_value():\n    return 2\n", encoding="utf-8")
    original_open = Path.open

    def grow_after_stat(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == source.resolve() and mode == "rb":
            return io.BytesIO(b"x" * 33)
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", grow_after_stat)
    original_lookup = store.search_flight.get_or_compute
    interleaved = {}

    def publish_uncertainty_before_lookup(key, compute):
        staged = store.index_paths_step(str(root), "tenant", workspace, ["one.py"])
        assert staged["success"] is True
        assert staged["read_uncertain_paths"] == ["one.py"]
        raw, hit, coalesced = original_lookup(key, compute)
        interleaved["hit"] = hit
        return raw, hit, coalesced

    monkeypatch.setattr(store.search_flight, "get_or_compute", publish_uncertainty_before_lookup)
    result = store.search("value query", "tenant", workspace, use_reranker=False)

    assert interleaved["hit"] is True
    assert result["search_cache"]["hit"] is False
    assert result["results"] == []
    assert result["fallback"] == "source_read_uncertain"

def test_index_step_reembeds_same_workspace_blank_space_chunk(tmp_path):
    class _SpaceServices(_Services):
        def __init__(self):
            super().__init__()
            self.space_id = "space-current"

        def embed(self, texts, tenant, **kwargs):
            result = super().embed(texts, tenant, **kwargs)
            result["embedding_space_id"] = self.space_id
            return result

    services = _SpaceServices()
    store = _store(tmp_path, services)
    root = tmp_path / "project"
    root.mkdir()
    (root / "same.py").write_text("def same_value():\n    return 4\n", encoding="utf-8")
    workspace = "same-workspace"
    assert store.index_step(str(root), "tenant", workspace)["success"]
    calls_before = len(services.calls)
    with closing(store._connect()) as con:
        con.execute(
            "UPDATE chunks SET embedding='[99.0,99.0]',embedding_space='' "
            "WHERE tenant=? AND workspace=? AND path='same.py'",
            (store._scope_key("tenant"), workspace),
        )
        con.commit()

    result = store.index_step(str(root), "tenant", workspace)

    assert result["success"] is True
    assert len(services.calls) > calls_before
    with closing(store._connect()) as con:
        row = con.execute(
            "SELECT text,embedding,embedding_space FROM chunks "
            "WHERE tenant=? AND workspace=? AND path='same.py'",
            (store._scope_key("tenant"), workspace),
        ).fetchone()
    vector = struct.unpack(f"{len(row[1]) // 4}f", row[1]) if isinstance(row[1], bytes) else json.loads(row[1])
    assert row[2] == "space-current"
    assert tuple(vector) == (float(len(row[0])), 1.0)

def test_full_index_reembeds_same_workspace_blank_space_chunk(tmp_path):
    class _SpaceServices(_Services):
        def __init__(self):
            super().__init__()
            self.space_id = "space-current"

        def embed(self, texts, tenant, **kwargs):
            result = super().embed(texts, tenant, **kwargs)
            result["embedding_space_id"] = self.space_id
            return result

    services = _SpaceServices()
    store = _store(tmp_path, services)
    root = tmp_path / "project"
    root.mkdir()
    (root / "same.py").write_text("def same_value():\n    return 4\n", encoding="utf-8")
    workspace = "same-workspace"
    assert store.index(str(root), "tenant", workspace)["success"]
    calls_before = len(services.calls)
    with closing(store._connect()) as con:
        con.execute(
            "UPDATE chunks SET embedding='[99.0,99.0]',embedding_space='' "
            "WHERE tenant=? AND workspace=? AND path='same.py'",
            (store._scope_key("tenant"), workspace),
        )
        con.commit()

    result = store.index(str(root), "tenant", workspace)

    assert result["success"] is True
    assert len(services.calls) > calls_before
    with closing(store._connect()) as con:
        row = con.execute(
            "SELECT text,embedding,embedding_space FROM chunks "
            "WHERE tenant=? AND workspace=? AND path='same.py'",
            (store._scope_key("tenant"), workspace),
        ).fetchone()
    vector = struct.unpack(f"{len(row[1]) // 4}f", row[1]) if isinstance(row[1], bytes) else json.loads(row[1])
    assert row[2] == "space-current"
    assert tuple(vector) == (float(len(row[0])), 1.0)


def test_changed_embedding_space_reembeds_reused_chunks_without_mixing_spaces(tmp_path):
    class _ChangingSpaceServices(_Services):
        def __init__(self):
            super().__init__()
            self.space_id = "model-a@revision-1"
            self.output_space = self.space_id

        def embed(self, texts, tenant, **kwargs):
            result = super().embed(texts, tenant, **kwargs)
            result["embeddings"] = [
                [float(len(text)), float(ord(self.output_space[6]))]
                for text in texts
            ]
            result["embedding_space_id"] = self.output_space
            return result

    services = _ChangingSpaceServices()
    store = _store(tmp_path, services)
    source_root = tmp_path / "source"
    source_root.mkdir()
    shared_text = "def shared_value():\n    return 1\n"
    (source_root / "shared.py").write_text(shared_text, encoding="utf-8")
    assert store.index(str(source_root), "tenant", workspace="source")["success"] is True
    with closing(store._connect()) as con:
        source_embedding = con.execute(
            "SELECT embedding FROM chunks WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), "source", "shared.py"),
        ).fetchone()[0]

    for mode in ("index", "index_paths_step", "index_step"):
        target_root = tmp_path / mode
        target_root.mkdir()
        (target_root / "shared.py").write_text(shared_text, encoding="utf-8")
        (target_root / "new.py").write_text("def new_value():\n    return 2\n", encoding="utf-8")
        services.output_space = "model-b@revision-2"
        workspace = f"target:{mode}"
        if mode == "index":
            result = store.index(str(target_root), "tenant", workspace=workspace)
        elif mode == "index_paths_step":
            result = store.index_paths_step(
                str(target_root), "tenant", workspace, ["shared.py", "new.py"]
            )
        else:
            result = store.index_step(
                str(target_root), "tenant", workspace=workspace, max_files=2
            )
        assert result["success"] is True
        with closing(store._connect()) as con:
            rows = {
                row[0]: (row[1], row[2])
                for row in con.execute(
                "SELECT path,embedding_space,embedding FROM chunks WHERE tenant=? AND workspace=?",
                (store._scope_key("tenant"), workspace),
                ).fetchall()
            }
        assert rows["shared.py"][0] == "model-b@revision-2"
        assert rows["new.py"][0] == "model-b@revision-2"
        value = rows["shared.py"][1]
        embedding = (
            struct.unpack(f"{len(value) // 4}f", value)
            if isinstance(value, bytes)
            else json.loads(value)
        )
        assert tuple(embedding) == (float(len(shared_text)), float(ord("b")))
        assert rows["shared.py"][1] != source_embedding
