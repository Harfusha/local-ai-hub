from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.rag import RAGStore


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


def test_full_index_reembeds_unchanged_files_when_embedding_space_changes(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "stable.py").write_text("stable project knowledge\n", encoding="utf-8")
    config = _config(tmp_path / "state")
    workspace = RAGStore.workspace_id(str(root))

    first_embedder = SpaceEmbedder("space-a")
    first = RAGStore(config, services=first_embedder)
    assert first.index(root=str(root), workspace=workspace)["success"] is True
    assert first_embedder.calls == 1

    second_embedder = SpaceEmbedder("space-b")
    second = RAGStore(config, services=second_embedder)
    result = second.index(root=str(root), workspace=workspace)

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

    repeated = second.index(root=str(root), workspace=workspace)
    assert repeated["success"] is True
    assert repeated["changed_files"] == 0
    assert second_embedder.calls == 1


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
    assert first.index(root=str(root), workspace=workspace)["success"] is True
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
    original_open = Path.open

    def fail_indexed_file(path: Path, mode="r", *args, **kwargs):
        if path == source and mode == "rb":
            raise PermissionError("simulated read error during embedding-space rebuild")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_indexed_file)
    result = second.index(root=str(root), workspace=workspace)

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
    assert first.index(root=str(root), workspace=workspace)["success"] is True
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
    result = second.index(root=str(root), workspace=workspace)

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
    assert first.index(root=str(root), workspace=workspace)["success"] is True
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
    result = second.index(root=str(root), workspace=workspace)

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
    assert first.index(root=str(root), workspace=workspace)["success"] is True
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
    result = second.index(root=str(root), workspace=workspace)

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
    assert first.index(root=str(root), workspace=workspace)["success"] is True
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
    result = second.index(root=str(root), workspace=workspace)

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
    assert first.index(root=str(root), workspace=workspace)["success"] is True
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
    result = second.index(root=str(root), workspace=workspace)

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
    assert first.index(root=str(root), workspace=workspace)["success"] is True

    excluded_config = _config(tmp_path / "state")
    excluded_config["rag"]["ignore_dirs"] = ["excluded"]
    second = RAGStore(excluded_config, services=SpaceEmbedder("space-b"))
    result = second.index(root=str(root), workspace=workspace)

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
    assert first.index(root=str(root), workspace=workspace)["success"] is True
    source.unlink()

    second = RAGStore(config, services=SpaceEmbedder("space-b"))
    result = second.index(root=str(root), workspace=workspace)

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


def test_full_index_reembeds_unchanged_files_after_embedding_config_change(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "stable.py").write_text("stable project knowledge\n", encoding="utf-8")
    workspace = RAGStore.workspace_id(str(root))

    first_config = _config(tmp_path / "state")
    first_config["models"]["embedding_digest"] = "sha256:first"
    embedder = ConfigIdentityEmbedder()
    first = RAGStore(first_config, services=embedder)
    assert first.index(root=str(root), workspace=workspace)["success"] is True
    first_space = first._embedding_space_id({"backend": "test"})
    assert embedder.calls == 1

    second_config = _config(tmp_path / "state")
    second_config["models"]["embedding_digest"] = "sha256:second"
    second = RAGStore(second_config, services=embedder)
    second_space = second._embedding_space_id({"backend": "test"})
    result = second.index(root=str(root), workspace=workspace)

    assert first_space != second_space
    assert result["success"] is True
    assert result["changed_files"] == 1
    assert embedder.calls == 2
    with closing(second._connect()) as con:
        spaces = {
            str(row[0])
            for row in con.execute(
                "SELECT DISTINCT embedding_space FROM chunks WHERE workspace=?",
                (workspace,),
            ).fetchall()
        }
    assert spaces == {second_space}
