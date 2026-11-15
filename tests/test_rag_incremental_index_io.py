from __future__ import annotations

from contextlib import closing
import re

from local_ai_hub import async_jobs as async_jobs_module
from local_ai_hub import rag as rag_module
from local_ai_hub.rag import RAGStore


class _EmbeddingStub:
    space_id = "test-embedding-space"

    def embed(self, texts, **_kwargs):
        return {
            "success": True,
            "space_id": self.space_id,
            "embeddings": [[1.0, 0.0, 0.0] for _ in texts],
        }


def test_indexed_paths_reports_only_persisted_workspace_files(tmp_path):
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {"embedding": "test-embedding", "embedding_dimension": 3},
            "rag": {"dedup_near_duplicates": False},
        },
        services=_EmbeddingStub(),
    )
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO files(workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?)",
            [("ws", "guide.md", 1, 10, "hash"), ("other", "else.md", 1, 10, "hash")],
        )
        con.commit()

    assert store.indexed_paths(
        workspace="ws", paths=["guide.md", "missing.py", "else.md"],
    ) == {"guide.md"}


def test_unchanged_index_does_not_read_all_embedding_blobs(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "guide.md").write_text("A short stable document for indexing.\n", encoding="utf-8")
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {"embedding": "test-embedding", "embedding_dimension": 3},
            "rag": {"dedup_near_duplicates": False},
        },
        services=_EmbeddingStub(),
    )

    first = store.index(str(repo))
    assert first["success"] is True

    statements = []
    original_connect = rag_module.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(rag_module, "connect_sqlite", traced_connect)
    second = store.index(str(repo))

    assert second["success"] is True
    embedding_reads = [
        statement.lower()
        for statement in statements
        if statement.lstrip().lower().startswith("select")
        and " from chunks " in statement.lower()
        and re.search(
            r"(?:^|,)\s*embedding\s*(?:,|$)",
            statement.lower().partition(" from chunks ")[0],
        )
    ]
    assert embedding_reads == []


def test_index_reports_monotonic_progress_through_publish(tmp_path, monkeypatch):
    progress = []
    monkeypatch.setattr(
        async_jobs_module,
        "report_job_progress",
        lambda percent, stage: progress.append((percent, stage)) or True,
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "guide.md").write_text("A short document for progress reporting.\n", encoding="utf-8")
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {"embedding": "test-embedding", "embedding_dimension": 3},
            "rag": {"dedup_near_duplicates": False},
        },
        services=_EmbeddingStub(),
    )

    result = store.index(str(repo))

    assert result["success"] is True
    assert progress
    percentages = [percent for percent, _stage in progress]
    assert percentages == sorted(percentages)
    stages = [stage for _percent, stage in progress]
    assert any(stage.startswith("scanning files") for stage in stages)
    assert any(stage.startswith("checking file metadata") for stage in stages)
    assert any(stage.startswith("embedding chunks") for stage in stages)
    assert "publishing index" in stages
    assert "index published" in stages
    assert percentages[-1] < 99


def test_index_progress_retry_phase_is_offset_and_monotonic(tmp_path, monkeypatch):
    progress = []
    monkeypatch.setattr(
        async_jobs_module,
        "report_job_progress",
        lambda percent, stage: progress.append((percent, stage)) or True,
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    guide = repo / "guide.md"
    guide.write_text("Initial indexed content.\n", encoding="utf-8")
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {"embedding": "test-embedding", "embedding_dimension": 3},
            "rag": {"dedup_near_duplicates": False},
        },
        services=_EmbeddingStub(),
    )

    assert store.index(str(repo))["success"] is True
    progress.clear()
    guide.write_text("Changed content for identity retry.\n", encoding="utf-8")

    result = store._index_locked(
        str(repo), store.workspace_id(str(repo)),
        _space_override="test-embedding-space", _identity_retry=True,
    )

    assert result["success"] is True
    percentages = [percent for percent, _stage in progress]
    stages = [stage for _percent, stage in progress]
    assert percentages == sorted(percentages)
    assert any(stage.startswith("identity retry:") for stage in stages)


def test_index_paths_step_preserves_sqlite_publish_timeout_detail(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "guide.md").write_text("A short document for timeout diagnostics.\n", encoding="utf-8")
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {"embedding": "test-embedding", "embedding_dimension": 3},
            "rag": {"dedup_near_duplicates": False},
        },
        services=_EmbeddingStub(),
    )
    original_write_transaction = rag_module.write_transaction
    timeout_message = "SQLite write transaction exceeded its duration budget (RAG batch index publish)"

    def fail_publish_transaction(connection, **kwargs):
        if kwargs.get("rollback_label") == "RAG batch index publish":
            raise TimeoutError(timeout_message)
        return original_write_transaction(connection, **kwargs)

    monkeypatch.setattr(rag_module, "write_transaction", fail_publish_transaction)

    result = store.index_paths_step(
        str(repo), workspace=store.workspace_id(str(repo)), paths=["guide.md"],
    )

    assert result["success"] is False
    assert result["error"] == "publish_failed"
    assert result["error_detail"] == timeout_message



def test_incremental_index_rejects_source_rewrite_during_embedding(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    guide = root / "guide.md"
    guide.write_text("original persisted content\n", encoding="utf-8")

    class MutatingEmbedding(_EmbeddingStub):
        on_embed = None

        def embed(self, texts, **kwargs):
            if self.on_embed is not None:
                callback, self.on_embed = self.on_embed, None
                callback()
            return super().embed(texts, **kwargs)

    backend = MutatingEmbedding()
    store = RAGStore(
        {"server": {"state_dir": str(tmp_path / "state")},
         "models": {"embedding": "test-embedding", "embedding_dimension": 3},
         "rag": {"dedup_near_duplicates": False}},
        services=backend,
    )
    ws = store.workspace_id(str(root))
    assert store.index_paths_step(str(root), workspace=ws, paths=["guide.md"])["success"]
    with closing(store._connect()) as con:
        previous = con.execute(
            "SELECT text FROM chunks WHERE workspace=? AND path=?",
            (ws, "guide.md"),
        ).fetchall()
    guide.write_text("second content to embed\n", encoding="utf-8")
    backend.on_embed = lambda: guide.write_text("third content after read\n", encoding="utf-8")

    rejected = store.index_paths_step(str(root), workspace=ws, paths=["guide.md"])
    assert rejected["success"] is False
    assert rejected["retryable"] is True
    assert rejected["error"] == "source_changed_before_publish"
    assert rejected["stale_source_paths"] == ["guide.md"]
    with closing(store._connect()) as con:
        assert con.execute(
            "SELECT text FROM chunks WHERE workspace=? AND path=?",
            (ws, "guide.md"),
        ).fetchall() == previous

    accepted = store.index_paths_step(str(root), workspace=ws, paths=["guide.md"])
    assert accepted["success"] is True
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT text FROM chunks WHERE workspace=? AND path=?",
            (ws, "guide.md"),
        ).fetchall()
    assert "third content after read" in " ".join(str(row[0]) for row in rows)


def test_full_index_rejects_source_rewrite_during_embedding(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    guide = root / "guide.md"
    guide.write_text("original persisted content\n", encoding="utf-8")

    class MutatingEmbedding(_EmbeddingStub):
        on_embed = None

        def embed(self, texts, **kwargs):
            if self.on_embed is not None:
                callback, self.on_embed = self.on_embed, None
                callback()
            return super().embed(texts, **kwargs)

    backend = MutatingEmbedding()
    store = RAGStore(
        {"server": {"state_dir": str(tmp_path / "state")},
         "models": {"embedding": "test-embedding", "embedding_dimension": 3},
         "rag": {"dedup_near_duplicates": False}},
        services=backend,
    )
    assert store.index(str(root))["success"]
    ws = store.workspace_id(str(root))
    with closing(store._connect()) as con:
        previous = con.execute(
            "SELECT text FROM chunks WHERE workspace=? AND path=?",
            (ws, "guide.md"),
        ).fetchall()
    guide.write_text("second content to embed\n", encoding="utf-8")
    backend.on_embed = lambda: guide.write_text("third content after read\n", encoding="utf-8")

    rejected = store.index(str(root))
    assert rejected["success"] is False
    assert rejected["retryable"] is True
    assert rejected["error"] == "source_changed_before_publish"
    assert rejected["stale_source_paths"] == ["guide.md"]
    with closing(store._connect()) as con:
        assert con.execute(
            "SELECT text FROM chunks WHERE workspace=? AND path=?",
            (ws, "guide.md"),
        ).fetchall() == previous


def test_incremental_index_rejects_symlink_swap_during_embedding(tmp_path):
    import pytest

    root = tmp_path / "repo"
    root.mkdir()
    guide = root / "guide.md"
    guide.write_text("trusted content\n", encoding="utf-8")
    external = tmp_path / "external.md"
    external.write_text("external content\n", encoding="utf-8")
    probe = root / "probe"
    try:
        probe.symlink_to(external)
        probe.unlink()
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    class MutatingEmbedding(_EmbeddingStub):
        def embed(self, texts, **kwargs):
            guide.unlink()
            guide.symlink_to(external)
            return super().embed(texts, **kwargs)

    store = RAGStore(
        {"server": {"state_dir": str(tmp_path / "state")},
         "models": {"embedding": "test-embedding", "embedding_dimension": 3},
         "rag": {"dedup_near_duplicates": False}},
        services=MutatingEmbedding(),
    )
    workspace = store.workspace_id(str(root))
    rejected = store.index_paths_step(str(root), workspace=workspace, paths=["guide.md"])
    assert rejected["success"] is False
    assert rejected["error"] == "source_changed_before_publish"
    assert rejected["retryable"] is True
    assert store.indexed_paths(workspace=workspace, paths=["guide.md"]) == set()



def test_changed_file_rejects_stale_content_override_at_index_boundary(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "guide.md").write_text("current and correct text\n", encoding="utf-8")
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {"embedding": "test-embedding", "embedding_dimension": 3},
            "rag": {"dedup_near_duplicates": False},
        },
        services=_EmbeddingStub(),
    )
    ws = store.workspace_id(str(repo))
    result = store.index_paths_step(
        str(repo), workspace=ws, paths=["guide.md"],
        content_overrides={"guide.md": "STALE TEXT"},
    )
    assert result["success"] is True
    assert result["processed_paths"] == []
    assert "guide.md" in result["read_uncertain_paths"]
    assert store.indexed_paths(workspace=ws, paths=["guide.md"]) == set()
