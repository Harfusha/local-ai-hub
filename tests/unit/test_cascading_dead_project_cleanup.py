from __future__ import annotations

import sqlite3
import shutil
import time
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub import sqlite_support
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.rag import RAGStore
from local_ai_hub.sqlite_support import ensure_incremental_vacuum


class _StubEmbeddings:
    space_id = "test-embedding-space"

    def embed(self, texts, *_args, **_kwargs):
        return {
            "success": True,
            "embedding_space_id": self.space_id,
            "embeddings": [[0.1, 0.2] for _ in texts],
        }


@pytest.mark.parametrize("failure_site", ["code_index", "deterministic", "rag"])
def test_deleted_project_cleanup_prunes_only_its_rag_paths(
    tmp_path: Path, monkeypatch, failure_site: str
) -> None:
    state_dir = tmp_path / "state"
    config = {"server": {"state_dir": str(state_dir)}, "rag": {}}
    rag = RAGStore(config, _StubEmbeddings())
    code_index = CodeIndex(config, None)
    deterministic = DeterministicEngine(config, code_index=code_index)
    preprocessor = ProjectPreprocessor(
        config, None, rag, None, None, None,
        code_index=code_index, deterministic=deterministic,
    )

    dead_root = tmp_path / "removed-project"
    dead_root.mkdir()
    (dead_root / "stale.md").write_text("owned stale RAG content " * 9000, encoding="utf-8")
    (dead_root / "shared.md").write_text("aliased content", encoding="utf-8")
    live_root = tmp_path / "live-project"
    live_root.mkdir()
    (live_root / "shared.md").write_text("aliased content", encoding="utf-8")
    dead_workspace = "removed-project-workspace"
    live_workspace = "live-project-workspace"
    now = time.time()
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
            (str(dead_root), dead_workspace, "complete", "complete", now, now),
        )
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
            (str(live_root), live_workspace, "complete", "complete", now, now),
        )
        for root, path in ((str(dead_root), "stale.md"), (str(live_root), "shared.md")):
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
                (root, path, "hash", 1, 1, now),
            )
        con.commit()

    first_index = rag.index_paths_step(
        str(dead_root), workspace=dead_workspace, paths=["stale.md"]
    )
    assert first_index["success"], first_index
    live_index = rag.index_paths_step(
        str(live_root), workspace=live_workspace, paths=["shared.md"]
    )
    assert live_index["success"], live_index
    large = "derived project payload " * 9000
    for db_path in (preprocessor.db_path, code_index.db_path, rag.db_path):
        with closing(sqlite3.connect(db_path)) as con:
            con.execute("PRAGMA auto_vacuum=NONE")
            con.execute("VACUUM")
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        con.execute(
            "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,?)",
            (str(dead_root), "stale.md", "hash", large, now),
        )
        con.execute(
            "INSERT INTO source_fts(root,path,content) VALUES(?,?,?)",
            (str(dead_root), "stale.md", large),
        )
        con.commit()
    with closing(sqlite3.connect(code_index.db_path)) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,analyzer_version,language,updated_at) VALUES(?,?,?,?,?,?)",
            (str(dead_root), "stale.md", "hash", "test", "markdown", now),
        )
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,docstring) VALUES(?,?,?,?,?,?,?)",
            (str(dead_root), "stale.md", "stale", "class", 1, 1, large),
        )
        con.commit()
    with closing(sqlite3.connect(rag.db_path)) as con:
        con.execute(
            "INSERT INTO files(workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?)",
            (dead_workspace, "unrelated.md", 0, 1, "unowned"),
        )
        con.commit()
    shutil.rmtree(dead_root)
    before_cleanup_bytes = rag.db_path.stat().st_size
    with closing(rag._connect()) as con:
        generation_before = rag._workspace_index_generation(con, dead_workspace)
    revision_before = rag.revision(workspace=dead_workspace)

    before_db_sizes = {
        path: path.stat().st_size
        for path in (preprocessor.db_path, code_index.db_path, rag.db_path)
    }
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError(f"injected bounded {failure_site} lock failure")
        return None

    if failure_site == "code_index":
        original = code_index.prune

        def fail_code_index(root: str, paths: list[str]) -> dict[str, object]:
            fail_once()
            return original(root, paths)

        monkeypatch.setattr(code_index, "prune", fail_code_index)
    elif failure_site == "deterministic":
        original = deterministic._connect

        def fail_deterministic():
            fail_once()
            return original()

        monkeypatch.setattr(deterministic, "_connect", fail_deterministic)
    else:
        original = rag.remove_project

        def fail_rag(*args, **kwargs):
            fail_once()
            return original(*args, **kwargs)

        monkeypatch.setattr(rag, "remove_project", fail_rag)
    first_cleanup = preprocessor.cleanup_deleted_projects()
    assert first_cleanup["pruned_count"] == 0
    assert first_cleanup["success"] is False
    assert first_cleanup["failed_projects"] == [str(dead_root)]
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM projects WHERE root=?", (str(dead_root),)
        ).fetchone() is not None
        assert con.execute(
            "SELECT 1 FROM file_refs WHERE root=? AND path='stale.md'", (str(dead_root),)
        ).fetchone() is not None

    retried_cleanup = preprocessor.cleanup_deleted_projects()
    assert retried_cleanup["pruned_count"] == 1
    assert attempts == 2
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM projects WHERE root=?", (str(dead_root),)
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM file_refs WHERE root=?", (str(dead_root),)
        ).fetchone() is None

    with closing(sqlite3.connect(rag.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM files WHERE workspace=? AND path=?",
            (dead_workspace, "stale.md"),
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM chunks WHERE workspace=? AND path=?",
            (dead_workspace, "stale.md"),
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM files WHERE workspace=? AND path=?",
            (live_workspace, "shared.md"),
        ).fetchone() is not None
        assert con.execute(
            "SELECT 1 FROM files WHERE workspace=? AND path=?",
            (dead_workspace, "unrelated.md"),
        ).fetchone() is not None
    with closing(rag._connect()) as con:
        assert rag._workspace_index_generation(con, dead_workspace) > generation_before
    assert rag.revision(workspace=dead_workspace) != revision_before
    for db_path, size_before in before_db_sizes.items():
        with closing(sqlite3.connect(db_path)) as con:
            assert con.execute("PRAGMA auto_vacuum").fetchone() == (2,)
        # A failed cascade pass also runs bounded vacuum; retry can therefore
        # finish cleanup without further file-size change on that store.
        assert db_path.stat().st_size <= size_before

    reclaim_payload = "periodic reclaim payload " * 90_000
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        con.execute(
            "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,?)",
            (str(dead_root), "late-stale.md", "late", reclaim_payload, now),
        )
        con.commit()
        con.execute("DELETE FROM source_index WHERE root=?", (str(dead_root),))
        con.commit()
        preprocess_freelist_before = int(con.execute("PRAGMA freelist_count").fetchone()[0])
    with closing(sqlite3.connect(code_index.db_path)) as con:
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,docstring) VALUES(?,?,?,?,?,?,?)",
            (str(dead_root), "late-stale.md", "late", "class", 1, 1, reclaim_payload),
        )
        con.commit()
        con.execute("DELETE FROM symbols WHERE root=?", (str(dead_root),))
        con.commit()
        code_freelist_before = int(con.execute("PRAGMA freelist_count").fetchone()[0])
    assert preprocess_freelist_before > 100
    assert code_freelist_before > 100
    preprocessor._last_db_maintenance = 0
    preprocessor._step_complete({"root": str(live_root)})
    assert preprocessor._stats["db_maintenance_runs"] == 1
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        assert int(con.execute("PRAGMA freelist_count").fetchone()[0]) < preprocess_freelist_before
    with closing(sqlite3.connect(code_index.db_path)) as con:
        assert int(con.execute("PRAGMA freelist_count").fetchone()[0]) < code_freelist_before


def test_startup_repair_keeps_failed_cleanup_discoverable_after_restart(
    tmp_path: Path, monkeypatch
) -> None:
    state_dir = tmp_path / "state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "preprocessing": {"enabled": False, "startup_delay_seconds": 0},
        "rag": {},
    }
    rag = RAGStore(config, _StubEmbeddings())
    code_index = CodeIndex(config, None)
    deterministic = DeterministicEngine(config, code_index=code_index)
    preprocessor = ProjectPreprocessor(
        config, None, rag, None, None, None,
        code_index=code_index, deterministic=deterministic,
    )
    dead_root = tmp_path / "restart-removed-project"
    dead_root.mkdir()
    (dead_root / "owned.md").write_text("restart-owned content", encoding="utf-8")
    workspace = "restart-shared-workspace"
    now = time.time()
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
            (str(dead_root), workspace, "complete", "complete", now, now),
        )
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
            (str(dead_root), "owned.md", "owned-hash", 1, 1, now),
        )
        con.commit()
    indexed = rag.index_paths_step(
        str(dead_root), workspace=workspace, paths=["owned.md"]
    )
    assert indexed["success"], indexed
    with closing(sqlite3.connect(code_index.db_path)) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,analyzer_version,language,updated_at) VALUES(?,?,?,?,?,?)",
            (str(dead_root), "owned.md", "owned-hash", "test", "markdown", now),
        )
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line) VALUES(?,?,?,?,?,?)",
            (str(dead_root), "owned.md", "owned", "class", 1, 1),
        )
        con.commit()
    with closing(deterministic._connect()) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)",
            (str(dead_root), "owned.md", "owned-hash", "markdown", 0, now),
        )
        con.execute(
            "INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)",
            (str(dead_root), "owned.md", "symbol", "owned", "class", 1, "{}"),
        )
        con.commit()
    shutil.rmtree(dead_root)

    original_prune = code_index.prune
    prune_attempts = 0

    def fail_first_prune(root: str, paths: list[str]) -> dict[str, object]:
        nonlocal prune_attempts
        prune_attempts += 1
        if prune_attempts == 1:
            raise sqlite3.OperationalError("injected restart cleanup lock failure")
        return original_prune(root, paths)

    monkeypatch.setattr(code_index, "prune", fail_first_prune)
    failed = preprocessor.cleanup_deleted_projects()
    assert failed["success"] is False
    assert failed["pruned_count"] == 0
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM projects WHERE root=?", (str(dead_root),)
        ).fetchone() is not None
        assert con.execute(
            "SELECT 1 FROM file_refs WHERE root=? AND path='owned.md'", (str(dead_root),)
        ).fetchone() is not None
    with closing(sqlite3.connect(code_index.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM symbols WHERE root=? AND path='owned.md'", (str(dead_root),)
        ).fetchone() is not None

    monkeypatch.undo()
    restarted = ProjectPreprocessor(
        config, None, rag, None, None, None,
        code_index=code_index, deterministic=deterministic,
    )
    with closing(sqlite3.connect(restarted.db_path)) as con:
        pending = con.execute(
            "SELECT status,paused FROM projects WHERE root=?", (str(dead_root),)
        ).fetchone()
        assert pending is not None
        assert pending == ("error", 1)
        assert con.execute(
            "SELECT 1 FROM file_refs WHERE root=? AND path='owned.md'", (str(dead_root),)
        ).fetchone() is not None

    restarted._last_db_maintenance = 0
    assert restarted._next_cpu_project() is None
    monkeypatch.setattr(restarted, "_background_work_allowed", lambda: True)

    def stop_after_idle_pass(_timeout: float) -> None:
        restarted._stop.set()

    monkeypatch.setattr(restarted._cpu_wakeup, "wait", stop_after_idle_pass)
    restarted._cpu_loop()
    with closing(sqlite3.connect(restarted.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM projects WHERE root=?", (str(dead_root),)
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM file_refs WHERE root=?", (str(dead_root),)
        ).fetchone() is None
    with closing(sqlite3.connect(code_index.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM files WHERE root=?", (str(dead_root),)
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM symbols WHERE root=?", (str(dead_root),)
        ).fetchone() is None
    with closing(sqlite3.connect(deterministic.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM files WHERE root=?", (str(dead_root),)
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM facts WHERE root=?", (str(dead_root),)
        ).fetchone() is None


def test_unregister_purge_failure_retains_retry_marker_and_retries(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "preprocessing": {"enabled": False},
        "rag": {},
    }
    rag = RAGStore(config, _StubEmbeddings())
    code_index = CodeIndex(config, None)
    deterministic = DeterministicEngine(config, code_index=code_index)
    preprocessor = ProjectPreprocessor(
        config, None, rag, None, None, None,
        code_index=code_index, deterministic=deterministic,
    )
    root = tmp_path / "unregister-project"
    root.mkdir()
    (root / "owned.md").write_text("owned unregister data", encoding="utf-8")
    (root / "shared.md").write_text("same path, separate live owner", encoding="utf-8")
    live_root = tmp_path / "unregister-live-alias"
    live_root.mkdir()
    (live_root / "shared.md").write_text("live alias", encoding="utf-8")
    workspace = "unregister-shared-workspace"
    now = time.time()
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        for project_root in (root, live_root):
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
                (str(project_root), workspace, "complete", "complete", now, now),
            )
        for project_root, path in ((root, "owned.md"), (live_root, "shared.md")):
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
                (str(project_root), path, "hash", 1, 1, now),
            )
        con.commit()
    indexed = rag.index_paths_step(str(root), workspace=workspace, paths=["owned.md"])
    assert indexed["success"], indexed
    rag.index_paths_step(str(root), workspace=workspace, paths=["shared.md"])
    with closing(sqlite3.connect(code_index.db_path)) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,analyzer_version,language,updated_at) VALUES(?,?,?,?,?,?)",
            (str(root), "owned.md", "hash", "test", "markdown", now),
        )
        con.commit()
    with closing(deterministic._connect()) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)",
            (str(root), "owned.md", "hash", "markdown", 0, now),
        )
        con.commit()

    original_prune = code_index.prune
    attempts = 0

    def fail_first_prune(project_root: str, paths: list[str]) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("injected unregister purge lock failure")
        return original_prune(project_root, paths)

    monkeypatch.setattr(code_index, "prune", fail_first_prune)
    first = preprocessor.unregister(str(root), purge_data=True)
    assert first["success"] is False
    assert first["removed"] == 0
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM projects WHERE root=?", (str(root),)
        ).fetchone() is not None
        assert con.execute(
            "SELECT 1 FROM file_refs WHERE root=? AND path='owned.md'", (str(root),)
        ).fetchone() is not None
    monkeypatch.undo()

    retried = preprocessor.unregister(str(root), purge_data=True)
    assert retried["success"] is True
    assert retried["removed"] == 1
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM projects WHERE root=?", (str(root),)
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM file_refs WHERE root=?", (str(root),)
        ).fetchone() is None
    with closing(sqlite3.connect(rag.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM files WHERE workspace=? AND path='owned.md'",
            (workspace,),
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM files WHERE workspace=? AND path='shared.md'",
            (workspace,),
        ).fetchone() is not None

    # Unregister without purge remains scheduler-only and preserves reusable data.
    retained_root = tmp_path / "unregister-retained"
    retained_root.mkdir()
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
            (str(retained_root), workspace, "complete", "complete", now, now),
        )
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
            (str(retained_root), "kept.md", "hash", 1, 1, now),
        )
        con.commit()
    retained = preprocessor.unregister(str(retained_root), purge_data=False)
    assert retained["success"] is True
    assert retained["purged"] is False
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM file_refs WHERE root=? AND path='kept.md'", (str(retained_root),)
        ).fetchone() is not None


def test_watcher_ignores_paths_under_missing_cleanup_root(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": False},
    }
    repo_tools = type("RepoToolsStub", (), {"ignore_dirs": set()})()
    preprocessor = ProjectPreprocessor(config, None, None, None, None, repo_tools)
    missing_root = tmp_path / "already-removed"

    assert preprocessor._watch_relevant(missing_root, missing_root / "file.py") is None


def test_workspace_cleanup_removes_orphan_rag_paths_and_preserves_unrelated_paths(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    config = {"server": {"state_dir": str(state_dir)}, "rag": {}}
    rag = RAGStore(config, _StubEmbeddings())
    preprocessor = ProjectPreprocessor(config, None, rag, None, None, None)
    dead_root = tmp_path / "removed-project"
    dead_root.mkdir()
    (dead_root / "stale.md").write_text("orphaned project RAG content " * 9000, encoding="utf-8")
    workspace = rag.workspace_id(str(dead_root))
    now = time.time()
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
            (str(dead_root), workspace, "complete", "complete", now, now),
        )
        con.commit()

    with closing(sqlite3.connect(rag.db_path)) as con:
        con.execute("PRAGMA auto_vacuum=NONE")
        con.execute("VACUUM")
    indexed = rag.index_paths_step(
        str(dead_root), workspace=workspace, paths=["stale.md"]
    )
    assert indexed["success"], indexed
    with closing(sqlite3.connect(rag.db_path)) as con:
        con.execute(
            "INSERT INTO files(workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?)",
            (workspace, "unrelated.md", 0, 1, "hash"),
        )
        con.commit()
    shutil.rmtree(dead_root)
    before_cleanup_bytes = rag.db_path.stat().st_size

    preprocessor.cleanup_deleted_projects()

    with closing(sqlite3.connect(rag.db_path)) as con:
        assert con.execute("PRAGMA auto_vacuum").fetchone() == (2,)
        assert con.execute(
            "SELECT 1 FROM files WHERE workspace=? AND path=?",
            (workspace, "stale.md"),
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM files WHERE workspace=? AND path=?",
            (workspace, "unrelated.md"),
        ).fetchone() is not None
    assert rag.db_path.stat().st_size < before_cleanup_bytes


def test_incremental_vacuum_setup_closes_connection_after_sqlite_error(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")
    assert ensure_incremental_vacuum(corrupt, timeout_seconds=0.1)["success"] is False
    moved = tmp_path / "renamed.sqlite3"
    corrupt.rename(moved)
    moved.unlink()


def test_incremental_vacuum_setup_interrupt_closes_connection(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "interrupted.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("CREATE TABLE payload(value TEXT)")
        con.executemany("INSERT INTO payload(value) VALUES(?)", [("x" * 1024,) for _ in range(4000)])
        con.commit()
    ticks = iter((10.0, 11.0))
    monkeypatch.setattr(sqlite_support.time, "monotonic", lambda: next(ticks, 11.0))
    result = ensure_incremental_vacuum(db_path, timeout_seconds=0.1)
    monkeypatch.undo()
    assert result["success"] is False
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM payload").fetchone() == (4000,)
    renamed = tmp_path / "interrupted-renamed.sqlite3"
    db_path.rename(renamed)
    renamed.unlink()
