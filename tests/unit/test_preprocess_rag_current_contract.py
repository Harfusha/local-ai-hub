"""Exercise preprocessing against strict current RAG and hybrid call signatures."""

import sqlite3
import threading
from collections import defaultdict
from contextlib import closing
from unittest.mock import Mock, create_autospec

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.rag import RAGStore
from local_ai_hub.services import LocalAIServices


@pytest.fixture
def prep(tmp_path):
    worker = ProjectPreprocessor.__new__(ProjectPreprocessor)
    worker.cfg = {"hot_queries": ["architecture"]}
    worker.rag = create_autospec(RAGStore, instance=True, spec_set=True)
    worker.services = create_autospec(LocalAIServices, instance=True, spec_set=True)
    worker.deterministic = None
    worker.code_index = None
    worker.learner = None
    worker._db_lock = threading.RLock()
    worker._stats_lock = threading.RLock()
    worker._stats = defaultdict(int)
    worker._yield = Mock(return_value=False)
    worker._set_project = Mock()
    worker._record_progress = Mock()
    worker.lookup = Mock(return_value={})
    database = tmp_path / "preprocess.sqlite3"

    def connect():
        con = sqlite3.connect(database)
        con.row_factory = sqlite3.Row
        return con

    worker._connect = connect
    with closing(connect()) as con:
        con.executescript("""
            CREATE TABLE file_refs (
                root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER,
                rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL
            );
            CREATE TABLE source_index (root TEXT, path TEXT, content_hash TEXT, text TEXT);
            CREATE TABLE source_fts (root TEXT, path TEXT, content TEXT);
            CREATE TABLE hot_query_state (
                root TEXT, query TEXT, revision_hash TEXT, updated_at REAL
            );
            CREATE TABLE task_capsules (
                root TEXT, query TEXT, revision_hash TEXT, capsule_json TEXT, updated_at REAL
            );
        """)
    return worker


def add_pending(prep, root, path):
    with closing(prep._connect()) as con:
        con.execute(
            "INSERT INTO file_refs VALUES(?,?,?,0,'',0,1,0)",
            (root, path, "current-hash"),
        )
        con.execute("INSERT INTO source_index VALUES(?,?,?,?)", (root, path, "current-hash", "cached text"))
        con.commit()


def add_completed_project(prep, root, workspace="repo-workspace"):
    with closing(prep._connect()) as con:
        con.execute(
            """CREATE TABLE projects (
                root TEXT PRIMARY KEY, workspace TEXT, status TEXT, phase TEXT,
                paused INTEGER, retry_after REAL, next_check_at REAL,
                updated_at REAL, generation INTEGER, force_refresh INTEGER,
                last_requested_at REAL
            )"""
        )
        con.execute(
            "INSERT INTO projects VALUES(?, ?, 'complete', 'complete', 0, 0, 0, 0, 7, 0, 0)",
            (root, workspace),
        )
        con.execute(
            "INSERT INTO file_refs VALUES(?,?,?,0,?,0,1,0)",
            (root, "service.py", "current-hash", "current-hash"),
        )
        con.commit()


def configure_watched_rag_reconciliation(prep):
    prep.cfg.update({"auto_recheck_seconds": 1800})
    prep._watcher_active = True
    prep._project_limit = Mock(return_value=6)
    prep._scheduler_order = Mock(return_value=("root ASC", []))
    prep._rebalance_processing_slots = Mock()
    prep._first_unowned_project = lambda rows: rows[0] if rows else None
    prep._project_phase_allowed = Mock(return_value=True)


def test_rag_idle_prunes_current_workspace(prep, tmp_path):
    root = str(tmp_path)
    prep.rag.prune_missing.return_value = 2
    assert prep._step_rag({"root": root, "workspace": "repo-workspace"})
    prep.rag.prune_missing.assert_called_once_with(root, "repo-workspace", [])
    prep._set_project.assert_called_once_with(root, phase="files")
    assert prep._stats["rag_deleted_files"] == 2


def test_rag_idle_requeues_semantic_paths_missing_from_workspace(prep, tmp_path):
    root = str(tmp_path)
    prep.cfg["rag_files_per_step"] = 1
    prep.deterministic = Mock()
    prep.deterministic.semantic_needed.return_value = True
    prep.rag.indexed_paths.return_value = set()
    with closing(prep._connect()) as con:
        con.execute(
            "INSERT INTO file_refs VALUES(?,?,?,0,?,0,1,0)",
            (root, "service.py", "current-hash", "current-hash"),
        )
        con.commit()

    assert prep._step_rag({"root": root, "workspace": "repo-workspace"})

    prep.rag.indexed_paths.assert_called_once_with(
        workspace="repo-workspace", paths=["service.py"],
    )
    prep.rag.prune_missing.assert_not_called()
    prep._set_project.assert_not_called()
    with closing(prep._connect()) as con:
        assert con.execute("SELECT rag_hash FROM file_refs").fetchone()[0] is None


def test_declarative_skip_removes_stale_paths_and_marks_synced(prep, tmp_path):
    root = str(tmp_path)
    add_pending(prep, root, "settings.json")
    prep.deterministic = Mock()
    prep.deterministic.semantic_needed.return_value = False
    assert prep._step_rag({"root": root, "workspace": "repo-workspace"})
    prep.rag.remove_paths.assert_called_once_with(workspace="repo-workspace", paths=["settings.json"])
    prep.rag.index_paths_step.assert_not_called()
    with closing(prep._connect()) as con:
        assert con.execute("SELECT rag_hash=content_hash FROM file_refs").fetchone()[0] == 1


@pytest.mark.parametrize("exists", [True, False])
def test_indexing_passes_cached_content_and_cleans_missing_paths(prep, tmp_path, exists):
    root = str(tmp_path)
    if exists:
        (tmp_path / "module.py").write_text("pass", encoding="utf-8")
    add_pending(prep, root, "module.py")
    prep.rag.index_paths_step.return_value = {
        "success": True, "processed_paths": ["module.py"] if exists else [],
    }
    assert prep._step_rag({"root": root, "workspace": "repo-workspace"})
    prep.rag.index_paths_step.assert_called_once_with(
        root, workspace="repo-workspace", paths=["module.py"],
        should_yield=prep._yield, content_overrides={"module.py": "cached text"},
    )
    with closing(prep._connect()) as con:
        if exists:
            prep.rag.remove_paths.assert_not_called()
            assert con.execute("SELECT rag_hash=content_hash FROM file_refs").fetchone()[0] == 1
        else:
            prep.rag.remove_paths.assert_called_once_with(workspace="repo-workspace", paths=["module.py"])
            assert con.execute("SELECT COUNT(*) FROM file_refs").fetchone()[0] == 0
            assert con.execute("SELECT COUNT(*) FROM source_index").fetchone()[0] == 0


@pytest.mark.parametrize("workspace", ["repo-workspace", None])
def test_deleted_project_purge_preserves_live_alias_paths(prep, tmp_path, workspace):
    root = str(tmp_path)
    prep.rag.workspace_id.return_value = "repo-workspace"
    prep._live_workspace_paths = Mock(return_value={"shared.py"})
    assert prep._purge_project_secondary_indexes(root, workspace)
    prep.rag.remove_project.assert_called_once_with(
        root, workspace="repo-workspace", preserve_paths={"shared.py"},
    )


def test_hot_query_uses_current_search_revision_and_hybrid_contracts(prep, tmp_path):
    root = str(tmp_path)
    prep.rag.revision.return_value = "revision-current"
    prep.rag.search.return_value = {"success": True, "results": [{"path": "module.py"}]}
    prep.services._hybrid_context.return_value = {"evidence": [{"evidence_id": "source-1"}]}
    assert prep._step_hot_query({"root": root, "workspace": "repo-workspace"})
    prep.rag.require_workspace_root.assert_called_once_with(workspace="repo-workspace", root=root)
    prep.rag.revision.assert_called_once_with(workspace="repo-workspace")
    prep.rag.search.assert_called_once_with(
        "architecture", workspace="repo-workspace", top_k=8, use_reranker=False, priority=0,
    )
    prep.services._hybrid_context.assert_called_once_with(
        root, "architecture", workspace="repo-workspace", max_tokens=1800,
    )
    with closing(prep._connect()) as con:
        assert con.execute("SELECT revision_hash FROM hot_query_state").fetchone()[0] == "revision-current"
    assert prep._stats["hot_queries"] == 1


def test_completed_project_requeues_missing_rag_rows_with_watcher_active(prep, tmp_path):
    root = str(tmp_path)
    add_completed_project(prep, root)
    configure_watched_rag_reconciliation(prep)
    prep.rag.indexed_paths.return_value = set()

    row = prep._next_cpu_project()

    assert row is not None
    assert row["root"] == root
    assert row["workspace"] == "repo-workspace"
    assert row["status"] == "queued"
    assert row["phase"] == "rag"
    prep.rag.indexed_paths.assert_called_once_with(
        workspace="repo-workspace", paths=["service.py"],
    )
    with closing(prep._connect()) as con:
        assert con.execute("SELECT rag_hash FROM file_refs").fetchone()[0] is None


def test_completed_project_rag_check_advances_cadence_when_workspace_is_current(prep, tmp_path):
    root = str(tmp_path)
    add_completed_project(prep, root)
    configure_watched_rag_reconciliation(prep)
    prep.rag.indexed_paths.return_value = {"service.py"}
    prep.rag.indexed_chunk_paths.return_value = {"service.py"}

    assert prep._next_cpu_project() is None

    with closing(prep._connect()) as con:
        project = con.execute(
            "SELECT status,phase,next_check_at FROM projects WHERE root=?", (root,),
        ).fetchone()
    assert project["status"] == "complete"
    assert project["phase"] == "complete"
    assert project["next_check_at"] > 0


def test_completed_project_rag_check_error_is_deferred_without_stopping_selection(prep, tmp_path):
    root = str(tmp_path)
    add_completed_project(prep, root)
    configure_watched_rag_reconciliation(prep)
    prep.rag.indexed_paths.side_effect = RuntimeError("database locked")

    assert prep._next_cpu_project() is None

    with closing(prep._connect()) as con:
        project = con.execute(
            "SELECT status,phase,next_check_at FROM projects WHERE root=?", (root,),
        ).fetchone()
    assert project["status"] == "complete"
    assert project["phase"] == "complete"
    assert project["next_check_at"] > 0


def test_completed_project_requeues_nonempty_file_when_chunk_rows_are_lost(prep, tmp_path):
    root = str(tmp_path)
    (tmp_path / "service.py").write_text("def service():\n    return 'ready'\n", encoding="utf-8")
    add_completed_project(prep, root)
    configure_watched_rag_reconciliation(prep)
    prep.rag.indexed_paths.return_value = {"service.py"}
    prep.rag.indexed_chunk_paths.return_value = set()

    row = prep._next_cpu_project()

    assert row is not None
    assert row["status"] == "queued"
    assert row["phase"] == "rag"
    prep.rag.indexed_chunk_paths.assert_called_once_with(
        workspace="repo-workspace", paths=["service.py"],
    )


def test_completed_project_keeps_whitespace_file_without_chunk_rows(prep, tmp_path):
    root = str(tmp_path)
    (tmp_path / "service.py").write_text(" \n\t \n", encoding="utf-8")
    add_completed_project(prep, root)
    configure_watched_rag_reconciliation(prep)
    prep.rag.indexed_paths.return_value = {"service.py"}
    prep.rag.indexed_chunk_paths.return_value = set()

    assert prep._next_cpu_project() is None

    prep.rag.indexed_chunk_paths.assert_called_once_with(
        workspace="repo-workspace", paths=["service.py"],
    )


def test_indexed_chunk_paths_reads_chunk_rows_not_file_rows(tmp_path):
    store = RAGStore({"server": {"state_dir": str(tmp_path / "state")}})
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO files(workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?)",
            ("ws", "missing-chunk.py", 1, 20, "file-hash"),
        )
        con.execute(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?)",
            ("ws", "indexed.py", 0, "chunk-hash", "text", "[]", "test-space"),
        )
        con.commit()

    assert store.indexed_chunk_paths(
        workspace="ws", paths=["indexed.py", "missing-chunk.py", "other-workspace.py"],
    ) == {"indexed.py"}
