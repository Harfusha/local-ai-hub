from __future__ import annotations

import inspect
import json
import os
import sqlite3
import struct
import sys
from contextlib import closing
from types import ModuleType, SimpleNamespace

import pytest
from local_ai_hub import mcp_server
from local_ai_hub.rag import RAGStore
from local_ai_hub import reranker as reranker_module
from local_ai_hub.reranker import Reranker


def _store(tmp_path):
    return RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {"extensions": [".py", ".md", ".svg"], "ignore_dirs": []},
            "resilience": {"singleflight_wait_timeout_seconds": 2},
            "features": {"reranker": True},
        }
    )


def _decode_embedding(raw):
    if isinstance(raw, (bytes, memoryview)):
        assert len(raw) % 4 == 0
        return list(struct.unpack(f"={len(raw) // 4}f", bytes(raw)))
    return json.loads(raw)


def _chunk_text(store, tenant: str, workspace: str, path: str) -> str:
    with closing(store._connect()) as con:
        row = con.execute(
            "SELECT text FROM chunks WHERE tenant=? AND workspace=? AND path=? ORDER BY chunk_no LIMIT 1",
            (store._scope_key(tenant), workspace, path),
        ).fetchone()
    return str(row[0]) if row else ""


def _rag_snapshot(store, tenant: str, workspace: str):
    scope_key = store._scope_key(tenant)
    with closing(store._connect()) as con:
        files = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE tenant=? AND workspace=? ORDER BY path",
            (scope_key, workspace),
        ).fetchall()
        chunks = con.execute(
            "SELECT path,chunk_no,content_hash,text,embedding,embedding_space FROM chunks "
            "WHERE tenant=? AND workspace=? ORDER BY path,chunk_no",
            (scope_key, workspace),
        ).fetchall()
        fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE tenant=? AND workspace=? ORDER BY path,chunk_no",
            (scope_key, workspace),
        ).fetchall()
        embedding_space = store._stored_workspace_embedding_space(con, scope_key, workspace)
        generation = store._workspace_index_generation(con, scope_key, workspace)
    return files, chunks, fts, embedding_space, generation


def _inject_sqlite_write_failure(
    store, monkeypatch, sql_prefix, *, max_failures=1, error_message="injected sqlite write failure"
):
    connect = store._connect
    state = {"attempts": 0}

    class _FailingConnection:
        def __init__(self, connection):
            self._connection = connection

        def _fail_if_requested(self, sql):
            if str(sql).lstrip().startswith(sql_prefix):
                state["attempts"] += 1
                if max_failures is None or state["attempts"] <= max_failures:
                    raise sqlite3.OperationalError(error_message)

        def execute(self, sql, *args):
            self._fail_if_requested(sql)
            return self._connection.execute(sql, *args)

        def executemany(self, sql, rows):
            self._fail_if_requested(sql)
            return self._connection.executemany(sql, rows)

        def close(self):
            self._connection.close()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(store, "_connect", lambda: _FailingConnection(connect()))
    return state


def test_document_ingest_indexes_title_and_metadata(tmp_path):
    store = _store(tmp_path)

    result = store.ingest_document(
        "specs",
        "The system rotates service credentials weekly.",
        title="Credential Rotation Plan",
        metadata={"owner": "identity-team", "revision": 7},
    )

    assert result["success"] is True
    assert result["embedded"] is False
    assert result["embedding_status"] == "degraded"
    assert result["degraded"] is True
    indexed = _chunk_text(store, "default", "specs", "doc:Credential Rotation Plan")
    assert "Title: Credential Rotation Plan" in indexed
    assert '"owner":"identity-team"' in indexed
    assert '"revision":7' in indexed
    assert "Content:\nThe system rotates service credentials weekly." in indexed


def test_document_ingest_reports_embedded_only_when_all_chunks_have_vectors(tmp_path):
    store = _store(tmp_path)

    class _OneVectorServices:
        def embed(self, texts, _tenant, **_kwargs):
            return {"success": True, "embeddings": [[0.1, 0.2]]}

    store.services = _OneVectorServices()
    result = store.ingest_document("specs", "x" * 1200, title="Long document")

    assert result["success"] is True
    assert result["chunks_ingested"] > 1
    assert result["embedded_chunks"] == 1
    assert result["embedded"] is False
    assert result["embedding_status"] == "degraded"
    assert result["degraded"] is True
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT text,embedding FROM chunks WHERE tenant=? AND workspace=? "
            "AND path=? ORDER BY chunk_no",
            (store._scope_key("default"), "specs", "doc:Long document"),
        ).fetchall()
    assert len(rows) == result["chunks_ingested"]
    assert _decode_embedding(rows[0][1]) == pytest.approx([0.1, 0.2])
    assert all(not row[1] for row in rows[1:])


def test_document_ingest_reports_real_embedding_success(tmp_path):
    store = _store(tmp_path)

    class _VectorServices:
        def embed(self, texts, _tenant, **_kwargs):
            return {"success": True, "embeddings": [[0.1, 0.2] for _ in texts]}

    store.services = _VectorServices()
    result = store.ingest_document("specs", "A fully embedded document.", title="Embedded")

    assert result["success"] is True
    assert result["embedded"] is True
    assert result["embedded_chunks"] == result["chunks_ingested"]
    assert result["embedding_status"] == "embedded"
    assert result["degraded"] is False


def test_document_ingest_replay_replaces_one_stable_document_snapshot(tmp_path):
    store = _store(tmp_path)
    content = "repeatable section " * 90

    first = store.ingest_document("specs", content, title="Replay Safe")
    second = store.ingest_document("specs", content, title="Replay Safe")

    assert first["success"] is True
    assert second["success"] is True
    assert first["chunks_ingested"] == second["chunks_ingested"]
    with closing(store._connect()) as con:
        files = con.execute(
            "SELECT COUNT(*) FROM files WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("default"), "specs", "doc:Replay Safe"),
        ).fetchone()[0]
        chunks = con.execute(
            "SELECT COUNT(*) FROM chunks WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("default"), "specs", "doc:Replay Safe"),
        ).fetchone()[0]

    assert files == 1
    assert chunks == second["chunks_ingested"]


def test_document_ingest_retries_publish_busy_without_reembedding(tmp_path, monkeypatch):
    store = _store(tmp_path)

    class _CountingServices:
        def __init__(self):
            self.calls = 0

        def embed(self, texts, _tenant, **_kwargs):
            self.calls += 1
            return {"success": True, "embeddings": [[0.1, 0.2] for _ in texts]}

    services = _CountingServices()
    store.services = services
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

    connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _FlakyConnection(connect()))

    result = store.ingest_document("specs", "retryable publication", title="Busy")

    assert result["success"] is True
    assert state["begins"] == 2
    assert services.calls == 1


def test_document_ingest_disk_full_keeps_previous_snapshot(tmp_path, monkeypatch):
    store = _store(tmp_path)
    title = "Atomic Document"
    assert store.ingest_document("specs", "old content", title=title)["success"] is True

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

    result = store.ingest_document("specs", "new content", title=title)
    monkeypatch.setattr(store, "_connect", connect)

    assert result["success"] is False
    assert "old content" in _chunk_text(store, "default", "specs", f"doc:{title}")
    assert "new content" not in _chunk_text(store, "default", "specs", f"doc:{title}")


@pytest.mark.parametrize("failed_statement", ["INSERT INTO chunk_fts", "DELETE FROM chunk_fts"])
def test_incremental_index_fts_write_failure_keeps_previous_snapshot(
    tmp_path, monkeypatch, failed_statement
):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("before = 'old snapshot'\n", encoding="utf-8")

    class _VectorServices:
        def embed(self, texts, _tenant, **_kwargs):
            return {
                "success": True,
                "embedding_space_id": "atomic-index-test-space",
                "embeddings": [[0.25, 0.75] for _ in texts],
            }

    store.services = _VectorServices()
    workspace = "atomic-index-workspace"
    assert store.index_paths_step(str(root), "tenant", workspace, ["module.py"])["success"] is True
    previous = _rag_snapshot(store, "tenant", workspace)

    path.write_text("after = 'new snapshot'\n", encoding="utf-8")
    injected = _inject_sqlite_write_failure(store, monkeypatch, failed_statement)
    result = store.index_paths_step(str(root), "tenant", workspace, ["module.py"])

    assert result["success"] is False
    assert result["retryable"] is False
    assert injected["attempts"] == 1
    assert _rag_snapshot(store, "tenant", workspace) == previous


@pytest.mark.parametrize("failed_statement", ["INSERT INTO chunk_fts", "DELETE FROM chunk_fts"])
def test_document_ingest_fts_write_failure_keeps_previous_snapshot(
    tmp_path, monkeypatch, failed_statement
):
    store = _store(tmp_path)
    title = "Atomic FTS Document"
    assert store.ingest_document("specs", "before snapshot", title=title)["success"] is True
    previous = _rag_snapshot(store, "default", "specs")

    injected = _inject_sqlite_write_failure(store, monkeypatch, failed_statement)
    result = store.ingest_document("specs", "after snapshot", title=title)

    assert result["success"] is False
    assert result["retryable"] is False
    assert injected["attempts"] == 1
    assert _rag_snapshot(store, "default", "specs") == previous


@pytest.mark.parametrize("operation", ["incremental_index", "document_ingest"])
def test_exhausted_publish_busy_retries_preserve_snapshot_and_report_retryable(
    tmp_path, monkeypatch, operation
):
    store = _store(tmp_path)
    if operation == "incremental_index":
        root = tmp_path / "project"
        root.mkdir()
        path = root / "module.py"
        path.write_text("before = 'old snapshot'\n", encoding="utf-8")

        class _VectorServices:
            def __init__(self):
                self.calls = 0

            def embed(self, texts, _tenant, **_kwargs):
                self.calls += 1
                return {
                    "success": True,
                    "embedding_space_id": "busy-index-test-space",
                    "embeddings": [[0.5, 0.5] for _ in texts],
                }

        services = _VectorServices()
        store.services = services
        workspace = "busy-index-workspace"
        assert store.index_paths_step(str(root), "tenant", workspace, ["module.py"])["success"] is True
        previous = _rag_snapshot(store, "tenant", workspace)
        path.write_text("after = 'new snapshot'\n", encoding="utf-8")
        invoke = lambda: store.index_paths_step(str(root), "tenant", workspace, ["module.py"])
        expected_error = "publish_failed"
    else:
        title = "Busy Document"
        assert store.ingest_document("specs", "before snapshot", title=title)["success"] is True
        previous = _rag_snapshot(store, "default", "specs")
        invoke = lambda: store.ingest_document("specs", "after snapshot", title=title)
        expected_error = "ingest_publish_failed"

    injected = _inject_sqlite_write_failure(
        store,
        monkeypatch,
        "BEGIN IMMEDIATE",
        max_failures=None,
        error_message="database is locked",
    )
    result = invoke()

    assert result["success"] is False
    assert result["error"] == expected_error
    assert result["retryable"] is True
    assert 1 < injected["attempts"] <= store._sqlite_write_retries + 1
    assert _rag_snapshot(
        store,
        "tenant" if operation == "incremental_index" else "default",
        "busy-index-workspace" if operation == "incremental_index" else "specs",
    ) == previous
    if operation == "incremental_index":
        assert services.calls == 2


def test_index_paths_step_recovers_missing_embedding_space_from_existing_chunks(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "module.py").write_text("value = 'stable chunk'\n", encoding="utf-8")

    class _VectorServices:
        def __init__(self):
            self.calls = 0

        def embed(self, texts, _tenant, **_kwargs):
            self.calls += 1
            return {
                "success": True,
                "embedding_space_id": "legacy-inferred-test-space",
                "embeddings": [[0.25, 0.75] for _ in texts],
            }

    services = _VectorServices()
    store.services = services
    workspace = "legacy-incremental-workspace"
    assert store.index_paths_step(str(root), "tenant", workspace, ["module.py"])["success"] is True
    scope_key = store._scope_key("tenant")
    space_key = store._workspace_embedding_space_key(scope_key, workspace)
    with closing(store._connect()) as con:
        con.execute("DELETE FROM rag_meta WHERE key=?", (space_key,))
        con.commit()

    class _UnexpectedEmbed:
        def embed(self, *_args, **_kwargs):
            raise AssertionError("legacy embedding should be reused")

    store.services = _UnexpectedEmbed()
    result = store.index_paths_step(str(root), "tenant", workspace, ["module.py"])

    assert result["success"] is True
    assert result["embedding_space_id"] == "legacy-inferred-test-space"
    assert result["embedding_space_resolved"] is True
    assert result["reused_chunks"] > 0
    assert services.calls == 1
    with closing(store._connect()) as con:
        assert store._stored_workspace_embedding_space(con, scope_key, workspace) == "legacy-inferred-test-space"


def test_index_paths_step_persists_inferred_space_without_paths_to_publish(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "module.py").write_text("value = 'stable chunk'\n", encoding="utf-8")

    class _VectorServices:
        def embed(self, texts, _tenant, **_kwargs):
            return {
                "success": True,
                "embedding_space_id": "legacy-noop-test-space",
                "embeddings": [[0.5, 0.5] for _ in texts],
            }

    store.services = _VectorServices()
    workspace = "legacy-noop-workspace"
    assert store.index_paths_step(str(root), "tenant", workspace, ["module.py"])["success"] is True
    scope_key = store._scope_key("tenant")
    space_key = store._workspace_embedding_space_key(scope_key, workspace)
    with closing(store._connect()) as con:
        con.execute("DELETE FROM rag_meta WHERE key=?", (space_key,))
        con.commit()
        generation_before = store._workspace_index_generation(con, scope_key, workspace)

    result = store.index_paths_step(str(root), "tenant", workspace, [])

    assert result["success"] is True
    assert result["processed_paths"] == []
    assert result["embedding_space_id"] == "legacy-noop-test-space"
    assert result["embedding_space_resolved"] is True
    with closing(store._connect()) as con:
        assert store._stored_workspace_embedding_space(con, scope_key, workspace) == "legacy-noop-test-space"
        assert store._workspace_index_generation(con, scope_key, workspace) > generation_before


def test_index_paths_step_requests_rebuild_for_mixed_legacy_embedding_spaces(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "module.py").write_text("value = 'stable chunk'\n", encoding="utf-8")

    class _VectorServices:
        def embed(self, texts, _tenant, **_kwargs):
            return {
                "success": True,
                "embedding_space_id": "legacy-first-test-space",
                "embeddings": [[0.25, 0.75] for _ in texts],
            }

    store.services = _VectorServices()
    workspace = "legacy-mixed-workspace"
    assert store.index_paths_step(str(root), "tenant", workspace, ["module.py"])["success"] is True
    scope_key = store._scope_key("tenant")
    space_key = store._workspace_embedding_space_key(scope_key, workspace)
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (scope_key, workspace, "other.py", 0, "other-hash", "other chunk", "[0.5,0.5]", "legacy-second-test-space"),
        )
        con.execute("DELETE FROM rag_meta WHERE key=?", (space_key,))
        con.commit()
    previous = _rag_snapshot(store, "tenant", workspace)

    result = store.index_paths_step(str(root), "tenant", workspace, [])

    assert result["success"] is False
    assert result["error"] == "embedding_space_rebuild_required"
    assert result["rebuild_required"] is True
    assert result["retryable"] is False
    assert _rag_snapshot(store, "tenant", workspace) == previous


def test_document_ingest_bounds_batches_and_preserves_long_document_order(tmp_path):
    store = _store(tmp_path)
    title = "Large Ordered Document"
    content = " ".join(
        f"section-{index:04d} " + ("payload " * 112)
        for index in range(75)
    )
    indexed_text = f"Title: {title}\nContent:\n{content.strip()}"
    expected_chunks = store._text_chunks(indexed_text, size=1000, overlap=100)
    assert len(expected_chunks) > 64
    assert len(set(expected_chunks)) == len(expected_chunks)
    expected_positions = {text: index + 1 for index, text in enumerate(expected_chunks)}

    class _RecordingServices:
        def __init__(self):
            self.calls = []

        def embed(self, texts, _tenant, **_kwargs):
            batch = list(texts)
            self.calls.append(batch)
            return {
                "success": True,
                "backend": "test",
                "model": "bounded-document-test-model",
                "embedding_space_id": "bounded-document-test-space",
                "embeddings": [[float(expected_positions[text]), 1.0] for text in batch],
            }

    services = _RecordingServices()
    store.services = services

    result = store.ingest_document("specs", content, title=title)

    assert result["success"] is True
    assert result["embedded"] is True
    assert [len(batch) for batch in services.calls] == [64, len(expected_chunks) - 64]
    assert [text for batch in services.calls for text in batch] == expected_chunks
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT chunk_no,text,embedding FROM chunks "
            "WHERE tenant=? AND workspace=? AND path=? ORDER BY chunk_no",
            (store._scope_key("default"), "specs", f"doc:{title}"),
        ).fetchall()
    assert [(int(row[0]), str(row[1])) for row in rows] == list(enumerate(expected_chunks))
    assert [_decode_embedding(row[2]) for row in rows] == [
        [float(index + 1), 1.0] for index in range(len(expected_chunks))
    ]


def test_document_ingest_keeps_text_and_degrades_remainder_after_later_batch_failure(tmp_path):
    store = _store(tmp_path)
    title = "Partial Ordered Document"
    content = " ".join(
        f"section-{index:04d} " + ("payload " * 112)
        for index in range(75)
    )
    indexed_text = f"Title: {title}\nContent:\n{content.strip()}"
    expected_chunks = store._text_chunks(indexed_text, size=1000, overlap=100)
    assert len(expected_chunks) > 64

    class _FailSecondBatchServices:
        def __init__(self):
            self.calls = []

        def embed(self, texts, _tenant, **_kwargs):
            batch = list(texts)
            self.calls.append(batch)
            if len(self.calls) == 2:
                return {"success": False, "error": "backend unavailable"}
            return {
                "success": True,
                "embedding_space_id": "partial-document-test-space",
                "embeddings": [[0.5, 0.25] for _ in batch],
            }

    services = _FailSecondBatchServices()
    store.services = services

    result = store.ingest_document("specs", content, title=title)

    assert result["success"] is True
    assert result["embedded_chunks"] == 64
    assert result["embedded"] is False
    assert result["embedding_status"] == "degraded"
    assert result["degraded"] is True
    assert [len(batch) for batch in services.calls] == [64, len(expected_chunks) - 64]
    assert [text for batch in services.calls for text in batch] == expected_chunks
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT chunk_no,text,embedding FROM chunks "
            "WHERE tenant=? AND workspace=? AND path=? ORDER BY chunk_no",
            (store._scope_key("default"), "specs", f"doc:{title}"),
        ).fetchall()
    assert [(int(row[0]), str(row[1])) for row in rows] == list(enumerate(expected_chunks))
    assert all(bool(row[2]) for row in rows[:64])
    assert all(not row[2] for row in rows[64:])


def test_document_ingest_rejects_overlong_later_batch_without_misassociation(tmp_path):
    store = _store(tmp_path)
    title = "Overlong Ordered Document"
    content = " ".join(
        f"section-{index:04d} " + ("payload " * 112)
        for index in range(75)
    )
    indexed_text = f"Title: {title}\nContent:\n{content.strip()}"
    expected_chunks = store._text_chunks(indexed_text, size=1000, overlap=100)
    assert len(expected_chunks) > 64
    expected_positions = {text: index + 1 for index, text in enumerate(expected_chunks)}

    class _OverlongSecondBatchServices:
        def __init__(self):
            self.calls = []

        def embed(self, texts, _tenant, **_kwargs):
            batch = list(texts)
            self.calls.append(batch)
            if len(self.calls) == 2:
                return {
                    "success": True,
                    "embedding_space_id": "overlong-document-test-space",
                    "embeddings": [[999.0, 1.0] for _ in range(len(batch) + 1)],
                }
            return {
                "success": True,
                "embedding_space_id": "overlong-document-test-space",
                "embeddings": [[float(expected_positions[text]), 1.0] for text in batch],
            }

    services = _OverlongSecondBatchServices()
    store.services = services

    result = store.ingest_document("specs", content, title=title)

    assert result["success"] is True
    assert result["embedded_chunks"] == 64
    assert result["embedded"] is False
    assert result["embedding_status"] == "degraded"
    assert result["degraded"] is True
    assert [len(batch) for batch in services.calls] == [64, len(expected_chunks) - 64]
    assert [text for batch in services.calls for text in batch] == expected_chunks
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT chunk_no,text,embedding FROM chunks "
            "WHERE tenant=? AND workspace=? AND path=? ORDER BY chunk_no",
            (store._scope_key("default"), "specs", f"doc:{title}"),
        ).fetchall()
    assert [(int(row[0]), str(row[1])) for row in rows] == list(enumerate(expected_chunks))
    assert [_decode_embedding(row[2]) for row in rows[:64]] == [
        [float(index + 1), 1.0] for index in range(64)
    ]
    assert not rows[64][2]


def test_heuristic_rerank_scores_and_orders_every_candidate(tmp_path):
    store = _store(tmp_path)

    class _FixedServices:
        def embed(self, texts, _tenant, *, query=False, **_kwargs):
            vectors = [[1.0, 0.0] if query or "Credential Rotation Plan" in text else [0.0, 1.0] for text in texts]
            return {"success": True, "model": "fixed", "backend": "test", "embeddings": vectors}

    store.services = _FixedServices()
    workspace = "heuristic-rerank"
    store.ingest_document(workspace, "Rotate authentication credentials weekly.", title="Credential Rotation Plan")
    store.ingest_document(workspace, "Soup and tea are served at lunch.", title="Cafeteria Menu")

    result = store.search("credential rotation", "default", workspace, top_k=2, use_reranker=True)

    assert result["success"] is True
    assert result["reranked"] is False
    assert result["degraded"] is True
    assert result["results"][0]["path"] == "doc:Credential Rotation Plan"
    assert all("heuristic_rerank_score" in row for row in result["results"])


def test_docset_rejects_empty_names_without_index_or_search(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(store, "index", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("indexed empty docset")))
    monkeypatch.setattr(store, "search", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("searched empty docset")))

    assert store.docset_index("  ", str(tmp_path))["success"] is False
    assert store.docset_index(None, str(tmp_path))["success"] is False
    assert store.docset_search("\t", "query")["success"] is False


def test_raster_diagram_reports_metadata_only_and_indexes_caption_metadata(tmp_path):
    store = _store(tmp_path)
    image = tmp_path / "network.png"
    image.write_bytes(b"not decoded by metadata-only ingestion")

    result = store.ingest_diagram(
        "diagrams",
        str(image),
        caption="Private edge routing",
        metadata={"owner": "platform", "revision": 4},
    )

    assert result["success"] is True
    assert result["diagram_content_mode"] == "metadata_only"
    assert result["vision_or_ocr_used"] is False
    indexed = _chunk_text(store, "default", "diagrams", f"doc:{result['document_title']}")
    assert "Caption: Private edge routing" in indexed
    assert '"owner":"platform"' in indexed


def test_svg_diagram_reports_extracted_text_provenance(tmp_path):
    store = _store(tmp_path)
    image = tmp_path / "flow.svg"
    image.write_text("<svg><text>Queue Drain</text></svg>", encoding="utf-8")

    result = store.ingest_diagram("diagrams", str(image), caption="Drain workflow")

    assert result["diagram_content_mode"] == "svg_text_nodes"
    assert result["vision_or_ocr_used"] is False
    indexed = _chunk_text(store, "default", "diagrams", f"doc:{result['document_title']}")
    assert "Queue Drain" in indexed
    assert "Caption: Drain workflow" in indexed


def test_mcp_rag_ingest_accepts_explicit_document_and_diagram_fields(monkeypatch, tmp_path):
    parameters = inspect.signature(mcp_server.local_ai_rag).parameters
    assert {"content", "title", "metadata", "image_path", "caption"} <= set(parameters)

    requests = []

    def fake_post(path, payload, **_kwargs):
        requests.append((path, payload))
        return {"success": True}

    monkeypatch.setattr(mcp_server.FEATURES, "rag", True)
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)
    monkeypatch.setattr(mcp_server, "_timeout", lambda _kind: 1)
    monkeypatch.setattr(mcp_server.CLIENT, "post", fake_post)
    monkeypatch.setattr(mcp_server, "_compact", lambda value, *_args: value)

    mcp_server.local_ai_rag(
        action="ingest_document",
        workspace="specs",
        content="Explicit content",
        title="Explicit title",
        metadata={"owner": "team"},
    )
    mcp_server.local_ai_rag(
        action="ingest_diagram",
        workspace="diagrams",
        image_path=str(tmp_path / "diagram.png"),
        caption="Explicit caption",
        metadata={"owner": "team"},
    )

    assert requests[0][1] == {
        "workspace": "specs",
        "content": "Explicit content",
        "title": "Explicit title",
        "metadata": {"owner": "team"},
    }
    assert requests[1][1] == {
        "workspace": "diagrams",
        "image_path": str(tmp_path / "diagram.png"),
        "caption": "Explicit caption",
        "metadata": {"owner": "team"},
    }


@pytest.mark.skipif(os.environ.get("T11_REAL_OLLAMA") != "1", reason="set T11_REAL_OLLAMA=1 for isolated live Ollama verification")
def test_t11_live_ollama_rag_ingest_and_reranker_truthfulness(tmp_path):
    real_reranker = os.environ.get("T11_REAL_RERANKER") == "1"
    if real_reranker:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    from local_ai_hub.app import LocalAIApp

    state_dir = (tmp_path / "state").as_posix()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join((
            "[server]",
            f"state_dir = {json.dumps(state_dir)}",
            'ollama_url = "http://127.0.0.1:11434"',
            "[ollama]",
            "enabled = true",
            "[llama_cpp]",
            "fallback_to_ollama = true",
            "[models]",
            'embedding = "qwen3-embedding:0.6b"',
            'embedding_backend = "ollama"',
            "[features]",
            "rag = true",
            f"reranker = {'true' if real_reranker else 'false'}",
            "[resilience]",
            "watchdog_enabled = false",
            "",
        )),
        encoding="utf-8",
    )

    app = LocalAIApp(str(config_path))
    try:
        tenant = "t11-live"
        workspace = "t11-live-embedding"
        embedding_results = []
        embed = app.services.embed

        def capture_embed(texts, embed_tenant, **kwargs):
            result = embed(texts, embed_tenant, **kwargs)
            embedding_results.append({
                "success": bool(result.get("success")),
                "backend": result.get("backend"),
                "model": result.get("model"),
                "error": result.get("error"),
            })
            return result

        app.services.embed = capture_embed
        target = app.rag.ingest_document(
            workspace,
            "Rotate API authentication secrets every seven days.",
            title="Credential Rotation Plan",
            metadata={"owner": "identity-team"},
            tenant=tenant,
        )
        app.rag.ingest_document(
            workspace,
            "The cafeteria serves soup and tea during lunch.",
            title="Cafeteria Menu",
            tenant=tenant,
        )
        result = app.rag.search(
            "weekly API authentication secret rotation",
            tenant,
            workspace,
            top_k=2,
            use_reranker=True,
        )

        print("T11_LIVE_EMBED=" + json.dumps(embedding_results, sort_keys=True))
        print("T11_LIVE_SEARCH=" + json.dumps([
            {key: row.get(key) for key in ("path", "score", "embedding_score", "rrf_score", "heuristic_rerank_score")}
            for row in result.get("results", [])
        ], sort_keys=True))
        assert target["embedded"] is True
        assert target["embedding_status"] == "embedded"
        assert result["success"] is True
        assert result["results"][0]["path"] == "doc:Credential Rotation Plan"
        if real_reranker:
            assert result["reranked"] is True
            assert result["degraded"] is False
            assert result["fallback"] is None
        else:
            assert result["reranked"] is False
            assert result["degraded"] is True
            assert result["fallback"] == "heuristic_rerank"
        print("T11_LIVE_RAG=" + json.dumps({
            "embedding_model": app.config["models"]["embedding"],
            "embedded_chunks": target["embedded_chunks"],
            "top_path": result["results"][0]["path"],
            "reranked": result["reranked"],
            "degraded": result["degraded"],
            "fallback": result["fallback"],
        }, sort_keys=True))
    finally:
        app.close()


def test_offline_missing_reranker_weights_degrade_without_false_reranked_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    sentence_transformers = ModuleType("sentence_transformers")
    sentence_transformers.CrossEncoder = object
    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_transformers)
    loader_attempts = []

    def missing_offline_weights(_owner, *, uses_cuda, factory):
        assert uses_cuda is False
        assert callable(factory)
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
        loader_attempts.append(True)
        raise OSError("offline reranker weights missing from cache")

    monkeypatch.setattr(reranker_module, "load_model", missing_offline_weights)
    store = _store(tmp_path)

    def deterministic_embed(texts, _tenant, **_kwargs):
        batch = list(texts)
        return {
            "success": True,
            "embedding_space_id": "offline-missing-reranker-test-space",
            "embeddings": [[float(len(text)), 1.0] for text in batch],
        }

    store.services.embed = deterministic_embed
    reranker = Reranker({
        "server": {"state_dir": str(tmp_path / "state")},
        "models": {
            "reranker": "BAAI/bge-reranker-base",
            "reranker_backend": "torch",
            "reranker_device": "cpu",
        },
        "cpu_retrieval": {"reranker_batch_size": 4},
        "features": {"reranker": True},
        "cache": {"reranker": False},
    })
    store.reranker = reranker
    root = tmp_path / "offline-reranker-project"
    root.mkdir()
    (root / "auth.py").write_text(
        "def authenticate_token(token):\n    return token\n", encoding="utf-8"
    )
    assert store.index_step(str(root), "tenant", max_files=8)["success"] is True

    result = store.search(
        "authenticate token",
        "tenant",
        store.workspace_id(str(root)),
        use_reranker=True,
    )

    assert loader_attempts == [True]
    assert result["success"] is True
    assert result["results"]
    assert result["reranked"] is False
    assert result["degraded"] is True
    assert result["fallback"] == "heuristic_rerank"
    assert reranker.status()["loaded"] is False
    assert "offline reranker weights missing from cache" in reranker.status()["load_error"]


@pytest.mark.parametrize("entrypoint", ["index", "index_paths_step", "index_step"])
def test_index_embedding_calls_are_bounded_for_large_single_file(tmp_path, monkeypatch, entrypoint):
    store = _store(tmp_path)
    store.config["rag"]["dedup_near_duplicates"] = False
    root = tmp_path / "project"
    root.mkdir()
    (root / "large.py").write_text("def large():\n    return 1\n", encoding="utf-8")
    chunks = [f"unique generated chunk {index}: " + ("x" * 120) for index in range(65)]
    monkeypatch.setattr(store, "_chunks", lambda _text, **_kwargs: chunks)

    class _RecordingServices:
        def __init__(self):
            self.calls = []

        def embed(self, texts, _tenant, **_kwargs):
            batch = list(texts)
            self.calls.append(batch)
            return {
                "success": True,
                "backend": "test",
                "model": "bounded-test-model",
                "embedding_space_id": "bounded-test-space",
                "embeddings": [[float(index + 1), 1.0] for index, _text in enumerate(batch)],
            }

    services = _RecordingServices()
    store.services = services
    workspace = "bounded-index-workspace"
    if entrypoint == "index":
        result = store.index(str(root), "tenant", workspace=workspace)
    elif entrypoint == "index_paths_step":
        result = store.index_paths_step(str(root), "tenant", workspace, ["large.py"])
    else:
        result = store.index_step(str(root), "tenant", workspace, max_files=1)

    assert result["success"] is True
    assert [len(batch) for batch in services.calls] == [64, 1]
    assert [text for batch in services.calls for text in batch] == chunks
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT chunk_no,text FROM chunks WHERE tenant=? AND workspace=? AND path=? ORDER BY chunk_no",
            (store._scope_key("tenant"), workspace, "large.py"),
        ).fetchall()
    assert [(int(row[0]), str(row[1])) for row in rows] == list(enumerate(chunks))


def test_preemption_after_embed_batch_preserves_published_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("before = 1\n", encoding="utf-8")

    store = _store(tmp_path)

    class _RecordingServices:
        def __init__(self):
            self.calls = []

        def embed(self, texts, _tenant, **_kwargs):
            batch = list(texts)
            self.calls.append(batch)
            return {
                "success": True,
                "backend": "test",
                "model": "preemption-test-model",
                "embedding_space_id": "preemption-test-space",
                "embeddings": [[0.25, 0.75] for _ in batch],
            }

    services = _RecordingServices()
    store.services = services
    chunks = ["baseline chunk"]
    monkeypatch.setattr(store, "_chunks", lambda _text, path="": list(chunks))
    workspace = "preemption-workspace"

    initial = store.index_paths_step(str(root), "tenant", workspace, ["module.py"])
    assert initial["success"] is True
    previous = _rag_snapshot(store, "tenant", workspace)

    path.write_text("after = 2\n", encoding="utf-8")
    chunks[:] = [f"replacement chunk {index}" for index in range(65)]

    def should_yield():
        return len(services.calls) >= 2

    result = store.index_paths_step(
        str(root), "tenant", workspace, ["module.py"], should_yield=should_yield
    )

    assert result["success"] is True
    assert result["preempted"] is True
    assert [len(batch) for batch in services.calls] == [1, 64]
    assert _rag_snapshot(store, "tenant", workspace) == previous


@pytest.mark.parametrize(
    ("action", "kwargs", "expected_error"),
    [
        (
            "ingest_document",
            {"content": "", "query": "fallback text", "root": "."},
            "content is required",
        ),
        (
            "ingest_diagram",
            {"image_path": "", "query": "fallback.svg", "root": "."},
            "image_path is required",
        ),
    ],
)
def test_mcp_rag_ingest_requires_explicit_input(
    action, kwargs, expected_error, monkeypatch
):
    monkeypatch.setattr(
        mcp_server,
        "FEATURES",
        SimpleNamespace(
            rag=True, tasks=False, status=False, has_any_model=lambda: False
        ),
    )
    calls = []
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda *args, **kw: calls.append((args, kw)) or {"success": True},
    )

    result = mcp_server.local_ai_rag(action=action, **kwargs)

    assert result["success"] is False
    assert expected_error in result["error"]
    assert calls == []


def test_mcp_rag_ingest_forwards_explicit_fields_only(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "FEATURES",
        SimpleNamespace(
            rag=True, tasks=False, status=False, has_any_model=lambda: False
        ),
    )
    calls = []

    def post(path, payload, **kwargs):
        calls.append((path, payload))
        return {"success": True, "status": "accepted"}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    mcp_server.local_ai_rag(
        action="ingest_document",
        workspace="specs",
        content="Explicit document content.",
        title="Explicit title",
        metadata={"source": "test"},
        query="unrelated query",
    )
    mcp_server.local_ai_rag(
        action="ingest_diagram",
        image_path="diagram.svg",
        caption="",
        metadata={"kind": "diagram"},
        extra_fields=["must not become caption"],
        query="unrelated path",
    )

    assert calls == [
        (
            "/api/rag/ingest_document",
            {
                "workspace": "specs",
                "content": "Explicit document content.",
                "title": "Explicit title",
                "metadata": {"source": "test"},
            },
        ),
        (
            "/api/rag/ingest_diagram",
            {
                "workspace": "default",
                "image_path": "diagram.svg",
                "caption": "",
                "metadata": {"kind": "diagram"},
            },
        ),
    ]


def test_diagram_ingest_rejects_svg_over_configured_file_limit(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.config["rag"]["max_file_bytes"] = 8
    image = tmp_path / "oversized.svg"
    image.write_bytes(b"<svg>content too large</svg>")
    calls = []
    monkeypatch.setattr(store, "ingest_document", lambda **kwargs: calls.append(kwargs))

    result = store.ingest_diagram("diagrams", str(image))

    assert result["success"] is False
    assert calls == []


def test_diagram_ingest_bounds_svg_read_when_file_grows_after_stat(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.config["rag"]["max_file_bytes"] = 8
    image = tmp_path / "growing.svg"
    image.write_bytes(b"<svg>content grew after stat</svg>")
    path_type = type(image)
    original_stat = path_type.stat

    def report_small_file(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == image:
            return SimpleNamespace(st_mode=result.st_mode, st_size=1)
        return result

    monkeypatch.setattr(path_type, "stat", report_small_file)
    calls = []
    monkeypatch.setattr(store, "ingest_document", lambda **kwargs: calls.append(kwargs))

    result = store.ingest_diagram("diagrams", str(image))

    assert result["success"] is False
    assert calls == []


def test_diagram_ingest_uses_path_identity_for_same_stem_files(tmp_path):
    store = _store(tmp_path)
    first = tmp_path / "one" / "architecture.svg"
    second = tmp_path / "two" / "architecture.svg"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("<svg><text>first</text></svg>", encoding="utf-8")
    second.write_text("<svg><text>second</text></svg>", encoding="utf-8")

    assert store.ingest_diagram("diagrams", str(first))["success"] is True
    assert store.ingest_diagram("diagrams", str(second))["success"] is True
    assert store.ingest_diagram("diagrams", str(first))["success"] is True

    with closing(store._connect()) as con:
        paths = con.execute(
            "SELECT path FROM files WHERE tenant=? AND workspace=? ORDER BY path",
            (store._scope_key("default"), "diagrams"),
        ).fetchall()
    assert len(paths) == 2


def test_diagram_ingest_reports_document_publish_failure(tmp_path, monkeypatch):
    store = _store(tmp_path)
    image = tmp_path / "diagram.svg"
    image.write_text("<svg><text>diagram</text></svg>", encoding="utf-8")
    monkeypatch.setattr(
        store,
        "ingest_document",
        lambda **kwargs: {"success": False, "error": "publish failed"},
    )

    result = store.ingest_diagram("diagrams", str(image))

    assert result["success"] is False
    assert result["diagram_indexed"] is False


def test_document_ingest_rejects_content_over_configured_file_limit(tmp_path):
    store = _store(tmp_path)
    store.config["rag"]["max_file_bytes"] = 12

    result = store.ingest_document("specs", "x" * 13, title="oversized")

    assert result["success"] is False
    with closing(store._connect()) as con:
        count = con.execute(
            "SELECT COUNT(*) FROM files WHERE tenant=? AND workspace=?",
            (store._scope_key("default"), "specs"),
        ).fetchone()[0]
    assert count == 0


@pytest.mark.parametrize(
    "fields",
    [
        {"title": "t" * 80},
        {"metadata": {"description": "m" * 80}},
    ],
    ids=("title", "metadata"),
)
def test_document_ingest_rejects_indexed_fields_over_configured_file_limit(tmp_path, fields):
    store = _store(tmp_path)
    store.config["rag"]["max_file_bytes"] = 64

    result = store.ingest_document("specs", "ok", **fields)

    assert result["success"] is False
    assert result["error"] == "indexed document exceeds configured file size limit"
    with closing(store._connect()) as con:
        count = con.execute(
            "SELECT COUNT(*) FROM files WHERE tenant=? AND workspace=?",
            (store._scope_key("default"), "specs"),
        ).fetchone()[0]
    assert count == 0
