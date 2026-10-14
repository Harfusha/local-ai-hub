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
    config = {"server": {"state_dir": str(state_dir)}, "rag": {"scope": "shared"}}
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
    shared_workspace = "shared-workspace"
    now = time.time()
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
            (str(dead_root), shared_workspace, "complete", "complete", now, now),
        )
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
            (str(live_root), shared_workspace, "complete", "complete", now, now),
        )
        for root, path in ((str(dead_root), "stale.md"), (str(live_root), "shared.md")):
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
                (root, path, "hash", 1, 1, now),
            )
        con.commit()

    scope = rag._scope_key("__preprocess__")
    first_index = rag.index_paths_step(str(dead_root), "__preprocess__", shared_workspace, ["stale.md", "shared.md"])
    assert first_index["success"], first_index
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
            "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
            (scope, shared_workspace, "legacy-user.md", 0, 1, "unowned"),
        )
        con.commit()
    shutil.rmtree(dead_root)
    before_cleanup_bytes = rag.db_path.stat().st_size
    with closing(rag._connect()) as con:
        generation_before = rag._workspace_index_generation(con, scope, shared_workspace)
    revision_before = rag.revision("__preprocess__", shared_workspace)

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
            "SELECT 1 FROM files WHERE tenant=? AND workspace=? AND path=?",
            (scope, shared_workspace, "stale.md"),
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM chunks WHERE tenant=? AND workspace=? AND path=?",
            (scope, shared_workspace, "stale.md"),
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM files WHERE tenant=? AND workspace=? AND path=?",
            (scope, shared_workspace, "shared.md"),
        ).fetchone() is not None
        assert con.execute(
            "SELECT 1 FROM files WHERE tenant=? AND workspace=? AND path=?",
            (scope, shared_workspace, "legacy-user.md"),
        ).fetchone() is not None
    with closing(rag._connect()) as con:
        assert rag._workspace_index_generation(con, scope, shared_workspace) > generation_before
    assert rag.revision("__preprocess__", shared_workspace) != revision_before
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


def test_tenant_cleanup_removes_orphan_rag_paths_from_existing_database(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    config = {"server": {"state_dir": str(state_dir)}, "rag": {"scope": "tenant"}}
    rag = RAGStore(config, _StubEmbeddings())
    preprocessor = ProjectPreprocessor(config, None, rag, None, None, None)
    dead_root = tmp_path / "removed-project"
    dead_root.mkdir()
    (dead_root / "stale.md").write_text("orphaned tenant RAG content " * 9000, encoding="utf-8")
    workspace = rag.workspace_id(str(dead_root))
    now = time.time()
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
            (str(dead_root), workspace, "complete", "complete", now, now),
        )
        con.commit()

    scope = rag._scope_key("__preprocess__")
    with closing(sqlite3.connect(rag.db_path)) as con:
        con.execute("PRAGMA auto_vacuum=NONE")
        con.execute("VACUUM")
        con.execute(
            "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
            ("user-tenant", workspace, "user.md", 0, 1, "hash"),
        )
        con.commit()
    indexed = rag.index_paths_step(str(dead_root), "__preprocess__", workspace, ["stale.md"])
    assert indexed["success"], indexed
    shutil.rmtree(dead_root)
    before_cleanup_bytes = rag.db_path.stat().st_size

    preprocessor.cleanup_deleted_projects()

    with closing(sqlite3.connect(rag.db_path)) as con:
        assert con.execute("PRAGMA auto_vacuum").fetchone() == (2,)
        assert con.execute(
            "SELECT 1 FROM files WHERE tenant=? AND workspace=? AND path=?",
            (scope, workspace, "stale.md"),
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM files WHERE tenant=? AND workspace=? AND path=?",
            ("user-tenant", workspace, "user.md"),
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
