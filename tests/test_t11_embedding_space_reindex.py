from __future__ import annotations

import hashlib
import os
import sqlite3

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

import local_ai_hub.rag as rag_module
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.rag import RAGStore
from local_ai_hub.repo_tools import RepositoryTools


class SpaceEmbedder:
    def __init__(self, space_id: str):
        self.space_id = space_id
        self.calls = 0

    def embed(self, texts, **_kwargs):
        self.calls += 1
        return {
            "success": True,
            "embeddings": [[float(len(text)), 1.0] for text in texts],
            "embedding_space_id": self.space_id,
            "backend": "test",
        }


def _config(state_dir: Path) -> dict:
    return {
        "server": {"state_dir": str(state_dir)},
        "rag": {"extensions": [".py"], "max_file_bytes": 1_000_000},
        "models": {"embedding": "same-configured-model", "embedding_backend": "test"},
    }


def test_hub_release_does_not_invalidate_rag_index_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = _config(tmp_path / "state")
    first = RAGStore(config, services=SpaceEmbedder("space-a"))
    fingerprint = first.index_fingerprint

    monkeypatch.setattr(rag_module, "__version__", "next-release", raising=False)
    second = RAGStore(config, services=SpaceEmbedder("space-a"))

    assert second.index_fingerprint == fingerprint


def test_full_index_honors_cooperative_yield(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "stable.py").write_text("stable project knowledge\n", encoding="utf-8")
    store = RAGStore(_config(tmp_path / "state"), services=SpaceEmbedder("space-a"))

    result = store.index(
        root=str(root),
        workspace=RAGStore.workspace_id(str(root)),
        should_yield=lambda: True,
    )

    assert result["success"] is True
    assert result["preempted"] is True


def test_full_index_reembeds_unchanged_files_when_embedding_space_changes(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "stable.py").write_text("stable project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))

    first_embedder = SpaceEmbedder("space-a")
    first = RAGStore(config, services=first_embedder)
    assert first.index(root=str(root),  workspace=workspace)["success"] is True
    assert first_embedder.calls == 1

    second_embedder = SpaceEmbedder("space-b")
    second = RAGStore(config, services=second_embedder)
    result = second.index(root=str(root),  workspace=workspace)

    assert result["success"] is True
    assert result["changed_files"] == 1
    assert second_embedder.calls == 1
    with closing(second._connect()) as con:
        spaces = {
            str(row[0])
            for row in con.execute(
                "SELECT DISTINCT embedding_space FROM chunks WHERE workspace=?",
                (workspace,),
            ).fetchall()
        }
    assert spaces == {"space-b"}

    repeated = second.index(root=str(root),  workspace=workspace)
    assert repeated["success"] is True
    assert repeated["changed_files"] == 0
    assert second_embedder.calls == 1


def test_incremental_reindex_keeps_target_until_all_paths_use_new_space(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "first.py").write_text("first project knowledge\n", encoding="utf-8")
    (root / "second.py").write_text("second project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))

    original = RAGStore(config, services=SpaceEmbedder("space-a"))
    indexed = original.index(root=str(root),  workspace=workspace)
    assert indexed["success"] is True, indexed

    reindex = RAGStore(config, services=SpaceEmbedder("space-b"))
    reindex._request_workspace_reindex(workspace, "space-b")
    assert original.paths_needing_reindex(str(root), workspace=workspace) == ["first.py", "second.py"]
    result = reindex.index_paths_step(str(root), workspace=workspace, paths=["first.py"])

    assert result["success"] is True
    with closing(reindex._connect()) as con:
        assert reindex._stored_workspace_reindex_target(con, workspace) == "space-b"
        assert reindex._stored_workspace_embedding_space(con, workspace) == "space-a"
        spaces_by_path = {
            str(path): str(space)
            for path, space in con.execute(
                "SELECT path,embedding_space FROM chunks WHERE workspace=? GROUP BY path",
                (workspace,),
            ).fetchall()
        }
    assert spaces_by_path == {"first.py": "space-b", "second.py": "space-a"}

    stale_paths = reindex.paths_needing_reindex(str(root), workspace=workspace, limit=8)
    assert stale_paths == ["second.py"]
    result = reindex.index_paths_step(str(root), workspace=workspace, paths=stale_paths)
    assert result["success"] is True
    with closing(reindex._connect()) as con:
        assert reindex._stored_workspace_reindex_target(con, workspace) is None
        assert reindex._stored_workspace_embedding_space(con, workspace) == "space-b"
        assert {
            str(row[0])
            for row in con.execute(
                "SELECT DISTINCT embedding_space FROM chunks WHERE workspace=?",
                (workspace,),
            ).fetchall()
        } == {"space-b"}

    original_connect = reindex._connect

    def forbid_vector_payloads():
        con = original_connect()
        con.set_authorizer(lambda action, table, column, *_: (
            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table == "chunks" and column == "embedding"
            else sqlite3.SQLITE_OK
        ))
        return con

    monkeypatch.setattr(reindex, "_connect", forbid_vector_payloads)
    assert reindex.paths_needing_reindex(str(root), workspace=workspace) == []


@pytest.mark.parametrize("watcher_active", [True, False], ids=["watcher", "inventory"])
def test_due_preprocessor_reindexes_unchanged_project(tmp_path: Path, monkeypatch, watcher_active):
    root = tmp_path / "repo"
    root.mkdir()
    source = b"def project_knowledge():\n    return 42\n"
    (root / "stable.py").write_bytes(source)
    digest = hashlib.sha256(source).hexdigest()
    config = _config(tmp_path / "state")
    config["preprocessing"] = {"enabled": False}
    rag = RAGStore(config, services=SpaceEmbedder("space-a"))
    scheduler = SimpleNamespace(background_allowed=lambda: True, foreground_busy=lambda: False, status=lambda: {})
    preprocessor = ProjectPreprocessor(config, None, rag, scheduler, None, RepositoryTools(config))
    try:
        monkeypatch.setattr(preprocessor, "enabled", True)
        monkeypatch.setattr(preprocessor, "_watcher_active", watcher_active)
        monkeypatch.setattr(preprocessor, "_yield", lambda: False)
        preprocessor.register(str(root))
        project = preprocessor._project_row(str(root))
        workspace = project["workspace"]
        assert preprocessor._step_inventory(dict(project))
        assert rag.index(str(root), workspace=workspace)["success"]
        with closing(preprocessor._connect()) as con, con:
            con.execute(
                "UPDATE file_refs SET content_hash=?,rag_hash=?,needs_hash=0,card_key='complete-card' WHERE root=?",
                (digest, digest, str(root)),
            )
        preprocessor._set_project(str(root), phase="complete", status="complete", last_complete_at=1, next_check_at=0)
        rag._request_workspace_reindex(workspace, "space-b")
        rag.services = SpaceEmbedder("space-b")

        for _ in range(1 if watcher_active else 3):
            project = preprocessor._next_cpu_project()
            if project is None:
                break
            assert preprocessor._run_project_step(dict(project))

        with closing(rag._connect()) as con:
            assert rag._stored_workspace_embedding_space(con, workspace) == "space-b"
            assert rag._stored_workspace_reindex_target(con, workspace) is None
    finally:
        preprocessor.close()


def test_cold_embedder_uses_persisted_reindex_target_instead_of_configured_fingerprint(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "knowledge.py").write_text("project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    config["models"]["embedding_revision"] = "a" * 40
    workspace = RAGStore.workspace_id(str(root))
    indexed = RAGStore(config, services=SpaceEmbedder("space-a"))
    assert indexed.index(str(root), workspace=workspace)["success"]

    def unresolved_fingerprint():
        pytest.fail("reindex selection should not use an unloaded embedder's fingerprint")

    cold = SimpleNamespace(embeddings=SimpleNamespace(_active_cache_identity=None, embedding_space_id=unresolved_fingerprint))
    store = RAGStore(config, services=cold)
    assert store.paths_needing_reindex(str(root), workspace=workspace) == []
    store._request_workspace_reindex(workspace, "space-b")
    assert store.paths_needing_reindex(str(root), workspace=workspace) == ["knowledge.py"]


def test_embedding_space_rebuild_read_error_preserves_previous_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "stable.py"
    source.write_text("stable project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))
    first = RAGStore(config, services=SpaceEmbedder("space-a"))
    assert first.index(root=str(root),  workspace=workspace)["success"] is True
    with closing(first._connect()) as con:
        old_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()

    second = RAGStore(config, services=SpaceEmbedder("space-b"))
    # Rebuild reads use the nofollow os.open path, not pathlib.Path.open.
    original_open = os.open

    def fail_indexed_file(path, *args, **kwargs):
        if isinstance(path, (str, os.PathLike)) and Path(path) == source:
            raise PermissionError("simulated read error during embedding-space rebuild")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("local_ai_hub.rag.os.open", fail_indexed_file)
    result = second.index(root=str(root),  workspace=workspace)

    assert result["success"] is False
    assert result["retryable"] is True
    with closing(second._connect()) as con:
        new_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()
    assert new_rows == old_rows
    assert new_file == old_file
    assert new_fts == old_fts


@pytest.mark.parametrize("access_method", ["exists", "is_dir"])
def test_embedding_space_rebuild_root_access_error_is_retryable_and_preserves_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, access_method: str
):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "stable.py").write_text("stable project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))
    first = RAGStore(config, services=SpaceEmbedder("space-a"))
    assert first.index(root=str(root),  workspace=workspace)["success"] is True
    with closing(first._connect()) as con:
        old_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()

    second = RAGStore(config, services=SpaceEmbedder("space-b"))
    original_access = getattr(Path, access_method)

    def deny_root_access(path: Path, *args, **kwargs):
        if path == root:
            return False
        return original_access(path, *args, **kwargs)

    monkeypatch.setattr(Path, access_method, deny_root_access)
    result = second.index(root=str(root),  workspace=workspace)

    assert result["success"] is False
    assert result["retryable"] is True
    with closing(second._connect()) as con:
        new_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()
    assert new_rows == old_rows
    assert new_file == old_file
    assert new_fts == old_fts


def test_embedding_space_rebuild_stat_error_preserves_previous_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "stable.py"
    source.write_text("stable project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))
    first = RAGStore(config, services=SpaceEmbedder("space-a"))
    assert first.index(root=str(root),  workspace=workspace)["success"] is True
    with closing(first._connect()) as con:
        old_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()

    second = RAGStore(config, services=SpaceEmbedder("space-b"))
    original_stat = Path.stat
    stat_failed = False

    def fail_indexed_file_stat(path: Path, *args, **kwargs):
        nonlocal stat_failed
        if path == source and not stat_failed:
            stat_failed = True
            raise PermissionError("simulated stat error during embedding-space rebuild")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_indexed_file_stat)
    result = second.index(root=str(root),  workspace=workspace)

    assert result["success"] is False
    assert result["retryable"] is True
    with closing(second._connect()) as con:
        new_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()
    assert new_rows == old_rows
    assert new_file == old_file
    assert new_fts == old_fts


def test_embedding_space_rebuild_direntry_stat_error_preserves_previous_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import local_ai_hub.rag as rag_module

    root = tmp_path / "repo"
    root.mkdir()
    source = root / "stable.py"
    source.write_text("stable project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))
    first = RAGStore(config, services=SpaceEmbedder("space-a"))
    assert first.index(root=str(root),  workspace=workspace)["success"] is True
    with closing(first._connect()) as con:
        old_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()

    second = RAGStore(config, services=SpaceEmbedder("space-b"))
    original_scandir = rag_module.os.scandir
    stat_failed = False

    class FailingEntry:
        def __init__(self, entry):
            self._entry = entry
            self.name = entry.name
            self.path = entry.path

        def __getattr__(self, name):
            return getattr(self._entry, name)

        def stat(self, *args, **kwargs):
            nonlocal stat_failed
            if self.name == source.name and not stat_failed:
                stat_failed = True
                raise PermissionError("simulated DirEntry.stat error during reindex")
            return self._entry.stat(*args, **kwargs)

    def failing_scandir(path):
        entries = list(original_scandir(path))
        if Path(path) == root:
            return [FailingEntry(entry) for entry in entries]
        return entries

    monkeypatch.setattr(rag_module.os, "scandir", failing_scandir)
    result = second.index(root=str(root),  workspace=workspace)

    assert stat_failed is True
    assert result["success"] is False
    assert result["retryable"] is True
    with closing(second._connect()) as con:
        new_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()
    assert new_rows == old_rows
    assert new_file == old_file
    assert new_fts == old_fts


def test_embedding_space_rebuild_scandir_error_preserves_previous_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import local_ai_hub.rag as rag_module

    root = tmp_path / "repo"
    nested = root / "nested"
    nested.mkdir(parents=True)
    source = nested / "stable.py"
    source.write_text("stable project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))
    first = RAGStore(config, services=SpaceEmbedder("space-a"))
    assert first.index(root=str(root),  workspace=workspace)["success"] is True
    with closing(first._connect()) as con:
        old_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()

    second = RAGStore(config, services=SpaceEmbedder("space-b"))
    original_scandir = rag_module.os.scandir
    scan_failed = False

    def failing_scandir(path):
        nonlocal scan_failed
        if Path(path) == nested and not scan_failed:
            scan_failed = True
            raise PermissionError("simulated scandir error during reindex")
        return original_scandir(path)

    monkeypatch.setattr(rag_module.os, "scandir", failing_scandir)
    result = second.index(root=str(root),  workspace=workspace)

    assert scan_failed is True
    assert result["success"] is False
    assert result["retryable"] is True
    with closing(second._connect()) as con:
        new_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()
    assert new_rows == old_rows
    assert new_file == old_file
    assert new_fts == old_fts


@pytest.mark.parametrize("failure_method", ["is_dir", "is_symlink"])
def test_embedding_space_rebuild_direntry_probe_error_preserves_previous_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_method: str
):
    import local_ai_hub.rag as rag_module

    root = tmp_path / "repo"
    root.mkdir()
    source = root / "stable.py"
    source.write_text("stable project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))
    first = RAGStore(config, services=SpaceEmbedder("space-a"))
    assert first.index(root=str(root),  workspace=workspace)["success"] is True
    with closing(first._connect()) as con:
        old_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        old_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()

    second = RAGStore(config, services=SpaceEmbedder("space-b"))
    original_scandir = rag_module.os.scandir
    probe_failed = False

    class FailingEntry:
        def __init__(self, entry):
            self._entry = entry
            self.name = entry.name
            self.path = entry.path

        def __getattr__(self, name):
            return getattr(self._entry, name)

        def _fail_if_selected(self, method):
            nonlocal probe_failed
            if self.name == source.name and method == failure_method and not probe_failed:
                probe_failed = True
                raise PermissionError(f"simulated DirEntry.{method} error during reindex")

        def is_dir(self, *args, **kwargs):
            self._fail_if_selected("is_dir")
            return self._entry.is_dir(*args, **kwargs)

        def is_symlink(self):
            self._fail_if_selected("is_symlink")
            return self._entry.is_symlink()

    def wrapped_scandir(path):
        entries = list(original_scandir(path))
        if Path(path) == root:
            return [FailingEntry(entry) for entry in entries]
        return entries

    monkeypatch.setattr(rag_module.os, "scandir", wrapped_scandir)
    result = second.index(root=str(root),  workspace=workspace)

    assert probe_failed is True
    assert result["success"] is False
    assert result["retryable"] is True
    with closing(second._connect()) as con:
        new_rows = con.execute(
            "SELECT path,chunk_no,content_hash,embedding,embedding_space "
            "FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_file = con.execute(
            "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
        new_fts = con.execute(
            "SELECT path,chunk_no,text FROM chunk_fts WHERE workspace=?",
            (workspace,),
        ).fetchall()
    assert new_rows == old_rows
    assert new_file == old_file
    assert new_fts == old_fts


def test_embedding_space_rebuild_prunes_newly_excluded_file_and_fts(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    excluded_dir = root / "excluded"
    excluded_dir.mkdir()
    (excluded_dir / "stable.py").write_text("stable project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))
    first = RAGStore(config, services=SpaceEmbedder("space-a"))
    assert first.index(root=str(root),  workspace=workspace)["success"] is True

    excluded_config = _config(tmp_path / "state")
    excluded_config["rag"]["ignore_dirs"] = ["excluded"]
    second = RAGStore(excluded_config, services=SpaceEmbedder("space-b"))
    result = second.index(root=str(root),  workspace=workspace)

    assert result["success"] is True
    assert result["deleted_files"] == 1
    with closing(second._connect()) as con:
        for table in ("files", "chunks", "chunk_fts"):
            count = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE workspace=?",
                (workspace,),
            ).fetchone()[0]
            assert count == 0


def test_embedding_space_rebuild_prunes_genuinely_deleted_file_and_fts(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "stable.py"
    source.write_text("stable project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))
    first = RAGStore(config, services=SpaceEmbedder("space-a"))
    assert first.index(root=str(root),  workspace=workspace)["success"] is True
    source.unlink()

    second = RAGStore(config, services=SpaceEmbedder("space-b"))
    result = second.index(root=str(root),  workspace=workspace)

    assert result["success"] is True
    assert result["deleted_files"] == 1
    with closing(second._connect()) as con:
        for table in ("files", "chunks", "chunk_fts"):
            count = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE workspace=?",
                (workspace,),
            ).fetchone()[0]
            assert count == 0

class ConfigIdentityEmbedder:
    def __init__(self):
        self.calls = 0

    def embed(self, texts, **_kwargs):
        self.calls += 1
        return {
            "success": True,
            "embeddings": [[float(len(text)), 1.0] for text in texts],
            "backend": "test",
        }


def test_embedding_fingerprint_change_is_degraded_and_preserves_rows(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "stable.py").write_text("stable project knowledge\n", encoding="utf-8")
    workspace = RAGStore.workspace_id(str(root))

    first_config = _config(tmp_path / "state")
    first_config["models"]["embedding_digest"] = "sha256:first"
    embedder = ConfigIdentityEmbedder()
    first = RAGStore(first_config, services=embedder)
    assert first.index(root=str(root),  workspace=workspace)["success"] is True
    with closing(first._connect()) as con:
        before_rows = con.execute(
            "SELECT path,content_hash,text,embedding,embedding_space FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
    assert embedder.calls == 1

    second_config = _config(tmp_path / "state")
    second_config["models"]["embedding_digest"] = "sha256:second"
    second = RAGStore(second_config, services=embedder)
    assert second.index_fingerprint_mismatch is True

    with closing(first._connect()) as con:
        after_rows = con.execute(
            "SELECT path,content_hash,text,embedding,embedding_space FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
    assert after_rows == before_rows
    assert embedder.calls == 1


def test_legacy_embedding_space_recovery_does_not_select_embedding_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "stable.py").write_text("stable project knowledge\n", encoding="utf-8")
    workspace = RAGStore.workspace_id(str(root))
    embedder = SpaceEmbedder("space-a")
    store = RAGStore(_config(tmp_path / "state"), services=embedder)
    assert store.index(root=str(root),  workspace=workspace)["success"] is True

    with closing(store._connect()) as con:
        con.execute(
            "DELETE FROM rag_meta WHERE key=?",
            (store._workspace_embedding_space_key(workspace),),
        )
        con.commit()

    statements: list[str] = []
    connect = store._connect

    def traced_connect():
        con = connect()
        con.set_trace_callback(statements.append)
        return con

    monkeypatch.setattr(store, "_connect", traced_connect)
    result = store.index_paths_step(
        str(root), workspace=workspace, paths=["stable.py"]
    )

    assert result["success"] is True
    with closing(connect()) as con:
        assert store._stored_workspace_embedding_space(con, workspace) == "space-a"

    normalized_statements = [" ".join(statement.upper().split()) for statement in statements]
    assert any(
        "SELECT DISTINCT COALESCE(TRIM(CAST(EMBEDDING_SPACE AS TEXT)), '')" in statement
        for statement in normalized_statements
    ), normalized_statements
    assert not any(
        "SELECT EMBEDDING,EMBEDDING_SPACE FROM CHUNKS" in statement
        for statement in normalized_statements
    ), normalized_statements


def test_legacy_vectors_without_space_still_require_rebuild_and_preserve_rows(
    tmp_path: Path,
):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "stable.py").write_text("stable project knowledge\n", encoding="utf-8")
    workspace = RAGStore.workspace_id(str(root))
    store = RAGStore(_config(tmp_path / "state"), services=SpaceEmbedder("space-a"))
    assert store.index(root=str(root),  workspace=workspace)["success"] is True

    with closing(store._connect()) as con:
        con.execute(
            "DELETE FROM rag_meta WHERE key=?",
            (store._workspace_embedding_space_key(workspace),),
        )
        con.execute(
            "UPDATE chunks SET embedding_space='' WHERE workspace=?",
            (workspace,),
        )
        con.commit()
        before_rows = con.execute(
            "SELECT path,text,embedding,embedding_space FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()

    result = store.index_paths_step(
        str(root), workspace=workspace, paths=["stable.py"]
    )

    assert result["success"] is False
    assert result["error"] == "embedding_space_rebuild_required"
    assert result["rebuild_required"] is True
    with closing(store._connect()) as con:
        after_rows = con.execute(
            "SELECT path,text,embedding,embedding_space FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
    assert after_rows == before_rows
