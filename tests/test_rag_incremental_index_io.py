from __future__ import annotations

from contextlib import closing
import re
import sqlite3

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




def test_rag_bounded_read_rejects_symlink_file_and_parent(tmp_path):
    import pytest

    root = tmp_path / "repo"
    root.mkdir()
    actual = root / "actual.md"
    actual.write_text("ordinary source\n", encoding="utf-8")
    alias = root / "alias.md"
    nested = root / "nested"
    nested.mkdir()
    (nested / "doc.md").write_text("nested source\n", encoding="utf-8")
    directory_alias = root / "alias-directory"
    try:
        alias.symlink_to(actual)
        directory_alias.symlink_to(nested, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert rag_module._read_bounded_file(actual, 128, root=root) == b"ordinary source\n"
    assert rag_module._read_bounded_file(alias, 128, root=root) is None
    assert rag_module._read_bounded_file(directory_alias / "doc.md", 128, root=root) is None


def test_rag_bounded_read_rejects_replaced_descriptor(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    expected = root / "expected.md"
    other = root / "other.md"
    expected.write_bytes(b"trusted bytes\n")
    other.write_bytes(b"other bytes!\n")
    original_open = rag_module.os.open

    def redirect_open(path, flags, *args, **kwargs):
        if path == expected:
            return original_open(other, flags, *args, **kwargs)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(rag_module.os, "open", redirect_open)
    assert rag_module._read_bounded_file(expected, 128, root=root) is None


def test_incremental_rag_never_embeds_an_in_root_symlink(tmp_path):
    import pytest

    root = tmp_path / "repo"
    root.mkdir()
    source = root / "source.md"
    source.write_text("original document\n", encoding="utf-8")
    alias = root / "alias.md"
    try:
        alias.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    class CountingEmbedding(_EmbeddingStub):
        calls = 0

        def embed(self, texts, **kwargs):
            self.calls += 1
            return super().embed(texts, **kwargs)

    backend = CountingEmbedding()
    store = RAGStore(
        {"server": {"state_dir": str(tmp_path / "state")},
         "models": {"embedding": "test-embedding", "embedding_dimension": 3},
         "rag": {"dedup_near_duplicates": False}},
        services=backend,
    )
    ws = store.workspace_id(str(root))
    result = store.index_paths_step(str(root), workspace=ws, paths=["alias.md"])
    assert result["success"] is True
    assert result["processed_paths"] == []
    assert "alias.md" in result["read_uncertain_paths"]
    assert backend.calls == 0



def test_sqlite_timeout_after_delete_preserves_previous_rag_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    guide = root / "guide.md"
    guide.write_text("previous indexed document\n", encoding="utf-8")
    store = RAGStore(
        {"server": {"state_dir": str(tmp_path / "state")},
         "models": {"embedding": "test-embedding", "embedding_dimension": 3},
         "rag": {"dedup_near_duplicates": False}},
        services=_EmbeddingStub(),
    )
    ws = store.workspace_id(str(root))
    assert store.index_paths_step(str(root), workspace=ws, paths=["guide.md"])["success"]

    def snapshot():
        with closing(store._connect()) as con:
            return {
                "files": [tuple(row) for row in con.execute(
                    "SELECT path,content_hash FROM files WHERE workspace=? ORDER BY path", (ws,),
                ).fetchall()],
                "chunks": [tuple(row) for row in con.execute(
                    "SELECT path,chunk_no,text FROM chunks WHERE workspace=? ORDER BY path,chunk_no", (ws,),
                ).fetchall()],
            }

    previous = snapshot()
    guide.write_text("updated document for publication\n", encoding="utf-8")
    original_check = rag_module._check_rag_publish_budget

    def fail_after_delete(*, started_at, stage, budget_seconds):
        if stage == "delete_old_rows":
            raise TimeoutError("simulated publish timeout after deleting original chunks")
        return original_check(
            started_at=started_at, stage=stage, budget_seconds=budget_seconds,
        )

    monkeypatch.setattr(rag_module, "_check_rag_publish_budget", fail_after_delete)
    rejected = store.index_paths_step(str(root), workspace=ws, paths=["guide.md"])
    assert rejected["success"] is False
    assert rejected["error"] == "publish_failed"
    assert rejected["retryable"] is False
    assert "simulated publish timeout" in rejected["error_detail"]
    assert snapshot() == previous

    monkeypatch.setattr(rag_module, "_check_rag_publish_budget", original_check)
    recovered = store.index_paths_step(str(root), workspace=ws, paths=["guide.md"])
    assert recovered["success"] is True
    assert snapshot() != previous
    assert "updated document for publication" in str(snapshot()["chunks"])


def test_transient_sqlite_busy_retries_publish_without_reembedding(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    guide = root / "guide.md"
    guide.write_text("original version\n", encoding="utf-8")

    class CountingEmbedding(_EmbeddingStub):
        calls = 0

        def embed(self, texts, **kwargs):
            self.calls += 1
            return super().embed(texts, **kwargs)

    backend = CountingEmbedding()
    store = RAGStore(
        {"server": {"state_dir": str(tmp_path / "state")},
         "models": {"embedding": "test-embedding", "embedding_dimension": 3},
         "rag": {"dedup_near_duplicates": False}},
        services=backend,
    )
    ws = store.workspace_id(str(root))
    assert store.index_paths_step(str(root), workspace=ws, paths=["guide.md"])["success"]
    prior_calls = backend.calls
    guide.write_text("replacement after lock\n", encoding="utf-8")

    original_check = rag_module._check_rag_publish_budget
    injected = {"count": 0}

    def transient_busy(*, started_at, stage, budget_seconds):
        if stage == "delete_old_rows" and injected["count"] == 0:
            injected["count"] += 1
            raise sqlite3.OperationalError("database is locked")
        return original_check(
            started_at=started_at, stage=stage, budget_seconds=budget_seconds,
        )

    monkeypatch.setattr(rag_module, "_check_rag_publish_budget", transient_busy)
    result = store.index_paths_step(str(root), workspace=ws, paths=["guide.md"])
    assert result["success"] is True
    assert injected["count"] == 1
    assert backend.calls == prior_calls + 1
    with closing(store._connect()) as con:
        chunks = con.execute(
            "SELECT text FROM chunks WHERE workspace=? AND path=? ORDER BY chunk_no",
            (ws, "guide.md"),
        ).fetchall()
    assert "replacement after lock" in " ".join(str(row[0]) for row in chunks)


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
