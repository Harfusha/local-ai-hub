from __future__ import annotations

import json
import subprocess
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


@pytest.fixture
def mock_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "player.py").write_text("class Player:\n    def move(self):\n        pass\n", encoding="utf-8")
    (repo / "tests" / "test_player.py").write_text("def test_player_move():\n    pass\n", encoding="utf-8")
    # Unity asset files to test ignore filtering
    (repo / "src" / "player.py.meta").write_text("fileFormatVersion: 2\nguid: abc123\n", encoding="utf-8")
    (repo / "src" / "level.asset").write_text("%YAML 1.1\n--- !u!114\n", encoding="utf-8")
    (repo / "src" / "character.prefab").write_text("%YAML 1.1\n--- !u!1 &1\n", encoding="utf-8")
    return repo


def test_ignore_extensions_and_unity_dirs(mock_repo: Path, tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "rag": {},
        "search": {},
    }
    repo_tools = RepositoryTools(config)
    inv = repo_tools.file_inventory(str(mock_repo), include_hashes=False)
    assert inv["success"] is True
    paths = [f["path"] for f in inv["files"]]

    # Valid source files present
    assert "src/player.py" in paths
    assert "tests/test_player.py" in paths

    # Asset files excluded
    assert "src/player.py.meta" not in paths
    assert "src/level.asset" not in paths
    assert "src/character.prefab" not in paths


def test_treesitter_extraction(tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_index": {},
    }
    repo_tools = RepositoryTools(config)
    ci = CodeIndex(config, repo_tools)

    # C#
    cs_code = """
    using System;
    namespace Game {
        public class EnemyController : MonoBehaviour {
            public int Health { get; set; }
            public void TakeDamage(int amount) {}
        }
    }
    """
    syms, refs, edges = ci._parse_file_content(cs_code, "csharp")
    names = [s["name"] for s in syms]
    assert "EnemyController" in names
    assert "TakeDamage" in names

    # TypeScript
    ts_code = """
    import { Router } from "express";
    export class ApiService {
        async handleRequest(req: any) {}
    }
    """
    ts_syms, ts_refs, ts_edges = ci._parse_file_content(ts_code, "typescript")
    ts_names = [s["name"] for s in ts_syms]
    assert "ApiService" in ts_names
    assert "handleRequest" in ts_names


def test_precompute_test_mappings_and_affected_tests(mock_repo: Path, tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "deterministic": {},
    }
    repo_tools = RepositoryTools(config)
    det = DeterministicEngine(config, repo_tools=repo_tools)

    # Precompute mappings
    count = det.precompute_test_mappings(str(mock_repo))
    assert count >= 1

    # Verify lookup via get_test_source_links
    linked = det.get_test_source_links(str(mock_repo), ["src/player.py"])
    assert "tests/test_player.py" in linked

    # Verify affected_tests uses precomputed link
    affected = det.affected_tests(str(mock_repo), changed_paths=["src/player.py"])
    assert affected["success"] is True
    assert "tests/test_player.py" in affected["test_files"]


def test_hotspots_cache(mock_repo: Path, tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "deterministic": {},
    }
    repo_tools = RepositoryTools(config)
    det = DeterministicEngine(config, repo_tools=repo_tools)

    res1 = det.find_hotspots(str(mock_repo), days=30, limit=10)
    assert res1["success"] is True

    # Second call should be served from cache
    res2 = det.find_hotspots(str(mock_repo), days=30, limit=10)
    assert res2["success"] is True
    assert res2.get("cached") is True


def test_stale_codegraph_config_does_not_add_preprocess_phase(mock_repo: Path, tmp_path: Path):
    state_dir = tmp_path / "state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "code_intelligence": {
            "enabled": True,
            "codegraph_enabled": True,
            "preprocess_codegraph": True,
        },
        "preprocessing": {
            "enabled": True,
            "disable_llm_card_synthesis": True,
        },
    }
    repo_tools = RepositoryTools(config)

    class MockServices:
        def repo_profile(self, root):
            return {"validation_commands": []}

    class MockScheduler:
        def background_allowed(self):
            return True
        def foreground_busy(self):
            return False

    pre = ProjectPreprocessor(
        config, services=MockServices(), rag=None, scheduler=MockScheduler(),
        runtime=None, repo_tools=repo_tools, code_index=None,
    )
    pre._init_db()

    assert "codegraph" not in pre.PHASES

    # Register project at serena phase
    with pre._db_lock, closing(pre._connect()) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
            (str(mock_repo), "test", "registered", "serena", 0.0, 0.0),
        )
        con.commit()

    # Step serena phase (with external tools disabled/None, it advances to lexical)
    stepped = pre._step({"root": str(mock_repo), "workspace": "test", "phase": "serena"})
    assert stepped is True

    # Next phase should be lexical directly; no retired intermediate phase remains.
    with pre._db_lock, closing(pre._connect()) as con:
        row = con.execute("SELECT phase FROM projects WHERE root=?", (str(mock_repo),)).fetchone()
        assert row["phase"] == "lexical"


def test_idle_diagnostics_launches_quoted_unicode_command_as_argv(
    mock_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import subprocess
    import sys

    state_dir = tmp_path / "state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "preprocessing": {"enabled": True, "idle_diagnostics_enabled": True},
    }
    command_arg = "space and Unicode: café 東京"
    command = (
        f'"{sys.executable}" -c "import sys; print(sys.argv[1])" '
        f'"{command_arg}"'
    )

    class MockServices:
        def repo_profile(self, root):
            return {"validation_commands": [{"command": command}]}

    class MockScheduler:
        def background_allowed(self):
            return True

        def foreground_busy(self):
            return False

    pre = ProjectPreprocessor(
        config, services=MockServices(), rag=None, scheduler=MockScheduler(),
        runtime=None, repo_tools=RepositoryTools(config), code_index=None,
    )
    pre._init_db()

    launched: dict[str, object] = {}
    real_popen = subprocess.Popen

    def record_popen(args, **kwargs):
        launched["args"] = args
        launched["shell"] = kwargs.get("shell", False)
        return real_popen(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", record_popen)
    assert pre._step_diagnostics({"root": str(mock_repo)}) is True

    assert launched["shell"] is False
    assert isinstance(launched["args"], list)
    with closing(pre._connect()) as con:
        row = con.execute(
            "SELECT exit_code, stdout_preview FROM diagnostic_baselines WHERE root=?",
            (str(mock_repo),),
        ).fetchone()
    assert row["exit_code"] == 0
    assert command_arg in row["stdout_preview"]


def test_idle_diagnostics_baseline(mock_repo: Path, tmp_path: Path):
    state_dir = tmp_path / "state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "preprocessing": {
            "enabled": True,
            "idle_diagnostics_enabled": True,
        },
    }
    repo_tools = RepositoryTools(config)

    class MockServices:
        def repo_profile(self, root):
            return {"validation_commands": [{"command": "python -c \"print('all clear')\""}]}

    class MockScheduler:
        def background_allowed(self):
            return True
        def foreground_busy(self):
            return False

    pre = ProjectPreprocessor(
        config, services=MockServices(), rag=None, scheduler=MockScheduler(),
        runtime=None, repo_tools=repo_tools, code_index=None,
    )
    pre._init_db()

    stepped = pre._step_diagnostics({"root": str(mock_repo)})
    assert stepped is True

    # Verify diagnostic baseline record
    with pre._db_lock, closing(pre._connect()) as con:
        row = con.execute("SELECT command, exit_code, stdout_preview FROM diagnostic_baselines WHERE root=?", (str(mock_repo),)).fetchone()
        assert row is not None
        assert row["exit_code"] == 0
        assert "all clear" in row["stdout_preview"]


def test_idle_diagnostics_runs_quoted_unicode_command_without_shell(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "projekt s čárkou"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "preprocessing": {"enabled": True, "idle_diagnostics_enabled": True},
    }
    command = subprocess.list2cmdline(
        [sys.executable, "-c", "print('validace žluťoučká')"]
    )

    class MockServices:
        def repo_profile(self, root):
            return {"validation_commands": [{"command": command}]}

    class MockScheduler:
        def background_allowed(self):
            return True

        def foreground_busy(self):
            return False

    calls = []
    original_popen = subprocess.Popen

    def capture_popen(args, *pos_args, **kwargs):
        calls.append((args, kwargs.get("shell", False)))
        return original_popen(args, *pos_args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", capture_popen)
    pre = ProjectPreprocessor(
        config, services=MockServices(), rag=None, scheduler=MockScheduler(),
        runtime=None, repo_tools=RepositoryTools(config), code_index=None,
    )
    pre._init_db()

    assert pre._step_diagnostics({"root": str(repo_root)}) is True

    diagnostic_calls = [
        (args, shell)
        for args, shell in calls
        if isinstance(args, list) and args and args[0] == sys.executable
    ]
    assert len(diagnostic_calls) == 1
    assert all(shell is False for _, shell in calls)
    assert diagnostic_calls[0][0] == [
        sys.executable,
        "-c",
        "print('validace žluťoučká')",
    ]
    with pre._db_lock, closing(pre._connect()) as con:
        row = con.execute(
            "SELECT exit_code, stdout_preview FROM diagnostic_baselines WHERE root=?",
            (str(repo_root),),
        ).fetchone()
    assert row is not None
    assert row["exit_code"] == 0
    assert "validace žluťoučká" in row["stdout_preview"]


def test_worktree_cache_inheritance(mock_repo: Path, tmp_path: Path):
    state_dir = tmp_path / "state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "preprocessing": {"enabled": True},
    }
    repo_tools = RepositoryTools(config)
    det = DeterministicEngine(config, repo_tools)
    code_idx = CodeIndex(config, repo_tools)

    class MockRag:
        def workspace_id(self, r):
            return "ws-1"

    class MockScheduler:
        def background_allowed(self):
            return True
        def foreground_busy(self):
            return False

    pre = ProjectPreprocessor(
        config, services=None, rag=MockRag(), scheduler=MockScheduler(),
        runtime=None, repo_tools=repo_tools, code_index=code_idx,
        deterministic=det,
    )
    pre._init_db()

    # Create parent files and worktree copy
    parent_repo = tmp_path / "parent_repo"
    parent_repo.mkdir()
    (parent_repo / "foo.py").write_text("def hello(): pass\n", encoding="utf-8")

    worktree_repo = tmp_path / "worktree_repo"
    worktree_repo.mkdir()
    (worktree_repo / "foo.py").write_text("def hello(): pass\n", encoding="utf-8")

    p_root = pre._root(str(parent_repo))
    w_root = pre._root(str(worktree_repo))

    real_hash = pre.repo_tools._hash_file_only(parent_repo / "foo.py")

    # Seed parent data
    with pre._db_lock, closing(pre._connect()) as con:
        con.execute(
            """INSERT INTO file_refs(root, path, content_hash, size, mtime_ns, needs_hash, card_key, rag_hash, generation, last_accessed_at, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p_root, "foo.py", real_hash, (parent_repo / "foo.py").stat().st_size, 1000, 0, "card_foo", "rag_foo", 1, 10.0, 10.0),
        )
        con.execute(
            "INSERT INTO source_index(root, path, content_hash, text, updated_at) VALUES(?, ?, ?, ?, ?)",
            (p_root, "foo.py", real_hash, "def hello(): pass", 10.0),
        )
        con.commit()

    with closing(det._connect()) as con:
        con.execute(
            "INSERT INTO test_source_links(root, source_path, test_path, confidence, updated_at) VALUES(?, ?, ?, ?, ?)",
            (p_root, "foo.py", "test_foo.py", 1.0, 10.0),
        )
        con.execute(
            "INSERT INTO hotspots_cache(root, days, cached_at, data_json) VALUES(?, ?, ?, ?)",
            (p_root, 30, 10.0, "{\"hotspots\": [\"foo.py\"]}"),
        )
        con.commit()

    # Register worktree with parent_root inheritance
    reg = pre.register(str(worktree_repo), is_worktree=True, parent_root=str(parent_repo))
    assert reg.get("success") is True

    # Verify worktree inherited caches
    with pre._db_lock, closing(pre._connect()) as con:
        row = con.execute("SELECT content_hash, card_key FROM file_refs WHERE root=? AND path='foo.py'", (w_root,)).fetchone()
        assert row is not None
        assert row["content_hash"] == real_hash
        assert row["card_key"] == "card_foo"

    with closing(det._connect()) as con:
        link = con.execute("SELECT test_path FROM test_source_links WHERE root=? AND source_path='foo.py'", (w_root,)).fetchone()
        assert link is not None
        assert link["test_path"] == "test_foo.py"

        hs = con.execute("SELECT data_json FROM hotspots_cache WHERE root=?", (w_root,)).fetchone()
        assert hs is not None
        assert "foo.py" in hs["data_json"]


def test_worktree_cache_seed_logs_expected_sqlite_failures_without_paths(tmp_path: Path, monkeypatch, caplog):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()

    class BrokenCacheStore:
        def _connect(self):
            raise sqlite3.OperationalError("database is locked")

    repo_tools = RepositoryTools(config)
    pre = ProjectPreprocessor(
        config,
        services=None,
        rag=None,
        scheduler=None,
        runtime=None,
        repo_tools=repo_tools,
        code_index=BrokenCacheStore(),
        deterministic=BrokenCacheStore(),
    )
    monkeypatch.setattr(pre, "_connect", BrokenCacheStore()._connect)
    try:
        with caplog.at_level("WARNING", logger="local_ai_hub.preprocess"):
            stats = pre._seed_from_parent(str(child), str(parent))

        assert stats == {"file_refs": 0, "code_index": 0, "deterministic": 0}
        messages = [record.getMessage() for record in caplog.records]
        assert len(messages) == 3
        assert all("OperationalError" in message for message in messages)
        assert all(str(tmp_path) not in message for message in messages)
    finally:
        pre.close()


def test_worktree_cache_seed_propagates_unexpected_errors(tmp_path: Path, monkeypatch):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    repo_tools = RepositoryTools(config)
    pre = ProjectPreprocessor(
        config,
        services=None,
        rag=None,
        scheduler=None,
        runtime=None,
        repo_tools=repo_tools,
    )

    def fail_with_programming_error():
        raise RuntimeError("unexpected cache seed defect")

    monkeypatch.setattr(pre, "_connect", fail_with_programming_error)
    try:
        with pytest.raises(RuntimeError, match="unexpected cache seed defect"):
            pre._seed_from_parent(str(child), str(parent))
    finally:
        pre.close()


def test_temp_project_filter_fails_closed_when_temp_path_cannot_be_resolved(tmp_path: Path, monkeypatch, caplog):
    from local_ai_hub import preprocess as preprocess_module

    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True, "reject_temp_projects": True},
    }
    pre = ProjectPreprocessor(
        config,
        services=None,
        rag=None,
        scheduler=None,
        runtime=None,
        repo_tools=RepositoryTools(config),
    )

    def fail_tempdir():
        raise OSError("temporary directory unavailable")

    monkeypatch.setattr(preprocess_module.tempfile, "gettempdir", fail_tempdir)
    try:
        with caplog.at_level("WARNING", logger="local_ai_hub.preprocess"):
            assert pre._is_ephemeral_root(str(tmp_path / "project")) is True

        assert any("OSError" in record.getMessage() for record in caplog.records)
        assert all(str(tmp_path) not in record.getMessage() for record in caplog.records)
    finally:
        pre.close()


def test_unregister_logs_derived_cache_purge_failure_without_project_path(tmp_path: Path, caplog):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }

    class BrokenCodeIndex:
        def _connect(self):
            raise sqlite3.OperationalError("database is locked")

    root = tmp_path / "repository"
    root.mkdir()
    pre = ProjectPreprocessor(
        config,
        services=None,
        rag=None,
        scheduler=None,
        runtime=None,
        repo_tools=RepositoryTools(config),
        code_index=BrokenCodeIndex(),
    )
    pre._init_db()
    try:
        with caplog.at_level("WARNING", logger="local_ai_hub.preprocess"):
            result = pre.unregister(str(root), purge_data=True)

        assert result["success"] is True
        assert result["purged"] is True
        messages = [record.getMessage() for record in caplog.records]
        assert len(messages) == 1
        assert "OperationalError" in messages[0]
        assert str(root) not in messages[0]
    finally:
        pre.close()


def test_unregister_rolls_back_when_required_source_fts_table_is_missing(tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }
    root = tmp_path / "repository"
    root.mkdir()

    class WorkspaceIdProvider:
        @staticmethod
        def workspace_id(path: str) -> str:
            return Path(path).name

    class SchedulerStub:
        @staticmethod
        def background_allowed() -> bool:
            return True

    pre = ProjectPreprocessor(
        config,
        services=None,
        rag=WorkspaceIdProvider(),
        scheduler=SchedulerStub(),
        runtime=None,
        repo_tools=RepositoryTools(config),
    )
    pre._init_db()
    try:
        assert pre.register(str(root))["success"] is True
        with closing(pre._connect()) as con:
            con.execute("DROP TABLE source_fts")
            con.commit()

        with pytest.raises(sqlite3.OperationalError, match="no such table: source_fts"):
            pre.unregister(str(root), purge_data=True)

        with closing(pre._connect()) as con:
            row = con.execute("SELECT root FROM projects WHERE root=?", (pre._root(str(root)),)).fetchone()
        assert row is not None
    finally:
        pre.close()


def test_missing_file_prune_rolls_back_when_required_source_fts_table_is_missing(tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }
    root = tmp_path / "repository"
    root.mkdir()
    pre = ProjectPreprocessor(
        config,
        services=None,
        rag=None,
        scheduler=None,
        runtime=None,
        repo_tools=RepositoryTools(config),
    )
    pre._init_db()
    resolved = pre._root(str(root))
    try:
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
                (resolved, "deleted.py", "content-hash", 10, 0, 1.0),
            )
            con.execute(
                "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,?)",
                (resolved, "deleted.py", "content-hash", "stale source", 1.0),
            )
            con.execute("DROP TABLE source_fts")
            con.commit()

        with pytest.raises(sqlite3.OperationalError, match="no such table: source_fts"):
            pre._prune_missing_file_refs(str(root))

        with closing(pre._connect()) as con:
            assert con.execute(
                "SELECT 1 FROM file_refs WHERE root=? AND path=?", (resolved, "deleted.py")
            ).fetchone() is not None
            assert con.execute(
                "SELECT 1 FROM source_index WHERE root=? AND path=?", (resolved, "deleted.py")
            ).fetchone() is not None
    finally:
        pre.close()


def test_rag_skip_keeps_file_pending_when_stale_rows_cannot_be_removed(tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True, "skip_rag_for_deterministic_declarative": True},
    }
    root = tmp_path / "repository"
    root.mkdir()

    class FailingRag:
        def remove_paths(self, *_args, **_kwargs):
            raise RuntimeError("RAG cleanup failed")

    class Deterministic:
        def semantic_needed(self, *_args, **_kwargs):
            return False

    pre = ProjectPreprocessor(
        config,
        services=None,
        rag=FailingRag(),
        scheduler=None,
        runtime=None,
        repo_tools=RepositoryTools(config),
        deterministic=Deterministic(),
    )
    pre._init_db()
    resolved = pre._root(str(root))
    pre._yield = lambda: False
    try:
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
                (resolved, "settings.json", "content-hash", 10, 0, 1.0),
            )
            con.commit()

        with pytest.raises(RuntimeError, match="RAG cleanup failed"):
            pre._step_rag({"root": resolved, "workspace": str(root), "generation": 0})

        with closing(pre._connect()) as con:
            row = con.execute(
                "SELECT rag_hash FROM file_refs WHERE root=? AND path=?",
                (resolved, "settings.json"),
            ).fetchone()
        assert row is not None and row["rag_hash"] is None
    finally:
        pre.close()


def test_lexical_index_does_not_store_empty_text_when_source_read_fails(tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True, "compact_lexical_for_deterministic_declarative": False},
    }
    root = tmp_path / "repository"
    root.mkdir()
    pre = ProjectPreprocessor(
        config,
        services=None,
        rag=None,
        scheduler=None,
        runtime=None,
        repo_tools=RepositoryTools(config),
    )
    pre._init_db()
    resolved = pre._root(str(root))
    try:
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
                (resolved, "missing.py", "content-hash", 10, 0, 1.0),
            )
            con.commit()

        with pytest.raises(FileNotFoundError):
            pre._step_lexical({"root": resolved})

        with closing(pre._connect()) as con:
            assert con.execute(
                "SELECT 1 FROM source_index WHERE root=? AND path=?", (resolved, "missing.py")
            ).fetchone() is None
    finally:
        pre.close()


def test_disabled_code_index_cleanup_failure_does_not_advance_phase(tmp_path: Path, monkeypatch):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }
    root = tmp_path / "repository"
    root.mkdir()

    class FailedCodeIndex:
        def prune(self, _root, _paths):
            return {"success": False, "error": "private database detail"}

    pre = ProjectPreprocessor(
        config,
        services=None,
        rag=None,
        scheduler=None,
        runtime=None,
        repo_tools=RepositoryTools(config),
        code_index=FailedCodeIndex(),
    )
    pre._init_db()
    set_calls = []
    monkeypatch.setattr(pre, "_background_work_allowed", lambda: True)
    monkeypatch.setattr(pre, "_yield", lambda: False)
    monkeypatch.setattr(pre, "_project_phase_allowed", lambda *_args: False)
    monkeypatch.setattr(pre, "_set_project", lambda _root, **kwargs: set_calls.append(kwargs))
    try:
        with pytest.raises(RuntimeError, match="code index cleanup failed"):
            pre._step({"root": str(root), "phase": "code_index"})

        assert {"phase": "deterministic"} not in set_calls
    finally:
        pre.close()


def test_code_index_prune_failure_does_not_mark_generation_pruned(tmp_path: Path, monkeypatch):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }
    root = tmp_path / "repository"
    root.mkdir()

    class FailedCodeIndex:
        def prune(self, _root, _paths):
            return {"success": False, "error": "private database detail"}

    pre = ProjectPreprocessor(
        config,
        services=None,
        rag=None,
        scheduler=None,
        runtime=None,
        repo_tools=RepositoryTools(config),
        code_index=FailedCodeIndex(),
    )
    pre._init_db()
    resolved = pre._root(str(root))
    monkeypatch.setattr(pre, "_project_settings", lambda _root: None)
    try:
        with pytest.raises(RuntimeError, match="code index prune failed"):
            pre._step_code_index({"root": resolved, "generation": 0})

        assert (resolved, 0) not in getattr(pre, "_code_index_pruned_generations", set())
    finally:
        pre.close()


def test_diagnostic_profile_failure_does_not_mark_phase_complete(tmp_path: Path, monkeypatch):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True, "idle_diagnostics_enabled": True},
    }

    class FailedServices:
        def repo_profile(self, _root):
            raise RuntimeError("profile lookup failed")

    class AvailableScheduler:
        def background_allowed(self):
            return True

        def foreground_busy(self):
            return False

    pre = ProjectPreprocessor(
        config,
        services=FailedServices(),
        rag=None,
        scheduler=AvailableScheduler(),
        runtime=None,
        repo_tools=RepositoryTools(config),
    )
    set_calls = []
    monkeypatch.setattr(pre, "_set_project", lambda _root, **kwargs: set_calls.append(kwargs))
    try:
        with pytest.raises(RuntimeError, match="profile lookup failed"):
            pre._step_diagnostics({"root": str(tmp_path), "workspace": str(tmp_path)})

        assert not any(call.get("phase") == "complete" for call in set_calls)
    finally:
        pre.close()


def test_code_index_find_callers_and_callees(tmp_path: Path):
    state_dir = tmp_path / "state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "code_index": {},
    }
    repo = tmp_path / "repo"
    repo.mkdir()
    py_code = """
def helper():
    return 42

def main():
    return helper()
"""
    (repo / "app.py").write_text(py_code, encoding="utf-8")
    repo_tools = RepositoryTools(config)
    code_idx = CodeIndex(config, repo_tools)

    res = code_idx.update_files_batch(str(repo), [("app.py", None)])
    assert res["success"] is True

    # Query callers of helper
    callers = code_idx.find_callers(str(repo), "helper")
    assert callers["success"] is True
    assert callers["count"] >= 1
    assert any("main" in c["caller"] for c in callers["callers"])

    # Query callees of main
    callees = code_idx.find_callees(str(repo), "main")
    assert callees["success"] is True
    assert callees["count"] >= 1
    assert any("helper" in c["callee"] for c in callees["callees"])


def test_repo_pipeline_composite_action(tmp_path: Path, monkeypatch):
    import local_ai_hub.mcp_server as mcp_mod

    class FakeClient:
        def post(self, endpoint, payload, timeout=None):
            if endpoint == "/api/repo/affected_tests":
                return {"success": True, "affected": ["test_foo.py"]}
            if endpoint == "/api/security_audit":
                return {"success": True, "findings": []}
            return {"success": True, "endpoint": endpoint}

    monkeypatch.setattr(mcp_mod, "CLIENT", FakeClient())

    steps = [
        {"action": "affected_tests", "path": "src/foo.py"},
        {"action": "security_audit"},
    ]
    res = mcp_mod._local_ai_repo_impl(action="pipeline", root=str(tmp_path), steps=steps)
    assert res["success"] is True
    assert res["pipeline"] is True
    assert res["steps_total"] == 2
    assert res["steps_completed"] == 2
    assert "affected_tests" in res["results"]
    assert "security_audit" in res["results"]
