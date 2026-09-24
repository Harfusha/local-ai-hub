from __future__ import annotations

import inspect
import json
import os
import struct
from contextlib import closing

import pytest
from local_ai_hub import mcp_server
from local_ai_hub.rag import RAGStore


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


def test_document_ingest_bounds_batches_and_preserves_long_document_order(tmp_path):
    store = _store(tmp_path)
    title = "Large Ordered Document"
    content = " ".join(
        f"section-{index:04d} " + ("payload " * 112)
        for index in range(75)
    )
    indexed_text = f"Title: {title}\nContent:\n{content}"
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
    indexed_text = f"Title: {title}\nContent:\n{content}"
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
    indexed_text = f"Title: {title}\nContent:\n{content}"
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
    assert [len(batch) for batch in services.calls] == [64, 1]
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
    indexed = _chunk_text(store, "default", "diagrams", "doc:diagram_network")
    assert "Caption: Private edge routing" in indexed
    assert '"owner":"platform"' in indexed


def test_svg_diagram_reports_extracted_text_provenance(tmp_path):
    store = _store(tmp_path)
    image = tmp_path / "flow.svg"
    image.write_text("<svg><text>Queue Drain</text></svg>", encoding="utf-8")

    result = store.ingest_diagram("diagrams", str(image), caption="Drain workflow")

    assert result["diagram_content_mode"] == "svg_text_nodes"
    assert result["vision_or_ocr_used"] is False
    indexed = _chunk_text(store, "default", "diagrams", "doc:diagram_flow")
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
