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
