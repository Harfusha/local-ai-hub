from __future__ import annotations

import importlib.util
import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from local_ai_hub.config import load_config
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.projection import AgentProjector
from local_ai_hub.repo_tools import RepositoryTools


class _Rag:
    index_reset = False
    def workspace_id(self, root): return "w"


class _Scheduler:
    def __init__(self, busy: bool = False): self.busy = busy
    def foreground_busy(self): return self.busy
    def background_allowed(self): return True
    def note_background_yield(self): pass


class _Noop:
    def __getattr__(self, name): return lambda *a, **k: None


def _config(tmp_path: Path, *, cpu_during_foreground: bool = False):
    path = tmp_path / "config.toml"
    path.write_text(
        f'''[server]\nstate_dir="{(tmp_path / 'state').as_posix()}"\n[hardware]\nprofile="cpu"\nauto_tune=false\n[prewarm]\nenabled=false\n[search]\nprefer_git_files=true\ngit_files_timeout_seconds=0.1\ngit_files_cache_ttl_seconds=30\ngit_files_slow_cooldown_seconds=30\ngit_grep_timeout_seconds=0.1\n[preprocessing]\nenabled=false\nfs_watcher_enabled=false\ncpu_runs_during_foreground={str(cpu_during_foreground).lower()}\n''',
        encoding="utf-8",
    )
    return load_config(str(path))


def test_preprocessor_single_owner_prevents_duplicate_project_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path)
    pre = ProjectPreprocessor(config, _Noop(), _Rag(), _Scheduler(), _Noop(), RepositoryTools(config))
    entered = threading.Event(); release = threading.Event(); results: list[bool | None] = []
    try:
        def slow_step(row):
            entered.set()
            assert release.wait(2)
            return True
        monkeypatch.setattr(pre, "_step", slow_step)
        row = {"root": str(tmp_path / "repo"), "phase": "files"}
        worker = threading.Thread(target=lambda: results.append(pre._run_project_step(row)))
        worker.start(); assert entered.wait(1)
        assert pre._run_project_step(row) is None
        release.set(); worker.join(2)
        assert results == [True]
        assert pre.stats()["project_step_contention"] >= 1
    finally:
        release.set(); pre.close()


def test_cpu_background_policy_can_continue_during_foreground(tmp_path: Path):
    config = _config(tmp_path, cpu_during_foreground=True)
    pre = ProjectPreprocessor(config, _Noop(), _Rag(), _Scheduler(busy=True), _Noop(), RepositoryTools(config))
    try:
        assert pre._yield() is False
        assert pre._gpu_yield() is True
    finally:
        pre.close()


def test_git_file_inventory_cache_avoids_duplicate_processes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path)
    repo = tmp_path / "repo"; repo.mkdir(); (repo / ".git").mkdir(); (repo / "a.py").write_text("x=1\n", encoding="utf-8")
    tools = RepositoryTools(config)
    calls = {"n": 0}
    def fake_run(*args, **kwargs):
        calls["n"] += 1
        return subprocess.CompletedProcess(args[0], 0, b"a.py\0", b"")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert [p.name for p in tools._git_files(repo) or []] == ["a.py"]
    assert [p.name for p in tools._git_files(repo) or []] == ["a.py"]
    assert calls["n"] == 1
    assert tools.snapshot_stats()["git_files"]["file_list_hits"] >= 1


def test_git_timeout_cooldown_prevents_repeated_slow_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path)
    repo = tmp_path / "repo"; repo.mkdir(); (repo / ".git").mkdir()
    tools = RepositoryTools(config)
    calls = {"n": 0}
    def fake_run(*args, **kwargs):
        calls["n"] += 1
        raise subprocess.TimeoutExpired(args[0], 0.1)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert tools._git_files(repo) is None
    assert tools._git_files(repo) is None
    assert calls["n"] == 1
    stats = tools.snapshot_stats()["git_files"]
    assert stats["file_list_timeouts"] == 1
    assert stats["cooldown_roots"] == 1


def test_new_agent_projection_profiles_are_recognized(tmp_path: Path):
    projector = AgentProjector({"agent_output": {}})
    assert projector.profile("Cursor")["relationships"] is True
    assert projector.profile("Windsurf")["max_text"] == 1250
    assert projector.profile("GitHub Copilot")["max_text"] == 1100


def test_vscode_mcp_merge_uses_servers_and_stdio_type(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("local_ai_hub_setup_v14", root / "tools" / "setup.py")
    assert spec and spec.loader
    setup = importlib.util.module_from_spec(spec); spec.loader.exec_module(setup)
    path = tmp_path / "mcp-config.json"
    path.write_text(json.dumps({"inputs": [{"id": "keep"}], "servers": {"user": {"type": "http", "url": "https://example.invalid"}}}), encoding="utf-8")
    setup.vscode_mcp_merge(path, {"local-ai": {"command": "python", "args": ["-m", "local_ai_hub.mcp_server"]}}, False)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["inputs"] == [{"id": "keep"}]
    assert data["servers"]["user"]["type"] == "http"
    assert data["servers"]["local-ai"]["type"] == "stdio"
    assert data["servers"]["local-ai"]["command"] == "python"


def test_generated_manifests_cover_generic_and_vscode(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("local_ai_hub_setup_manifest_v14", root / "tools" / "setup.py")
    assert spec and spec.loader
    setup = importlib.util.module_from_spec(spec); spec.loader.exec_module(setup)
    install = tmp_path / "install"; install.mkdir()
    setup.write_generated_agent_manifests(install, tmp_path / "python", None, None, {"code_intelligence": {"direct_agent_mcp": False}})
    generic = json.loads((install / "generated" / "mcp-servers.json").read_text(encoding="utf-8"))
    vscode = json.loads((install / "generated" / "vscode-mcp.json").read_text(encoding="utf-8"))
    assert generic["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "generic"
    assert vscode["servers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "copilot"
    assert vscode["servers"]["local-ai"]["type"] == "stdio"
    assert "never poll" in (install / "generated" / "agent-policy.md").read_text(encoding="utf-8").lower()


def test_startup_lock_detects_dead_owner_without_waiting(tmp_path: Path):
    from local_ai_hub.client import _live_start_lock
    lock = tmp_path / "hub.start.lock"
    # Negative PID is guaranteed non-live on every supported platform.
    lock.write_text("-1 0", encoding="utf-8")
    assert _live_start_lock(lock, 20.0) is False
    lock.write_text(f"{__import__('os').getpid()} {time.time()}", encoding="utf-8")
    assert _live_start_lock(lock, 20.0) is True


def test_git_grep_timeout_enters_cooldown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path)
    repo = tmp_path / "repo"; repo.mkdir(); (repo / ".git").mkdir()
    tools = RepositoryTools(config); tools._rg = None
    calls = {"n": 0}
    def fake_run(*args, **kwargs):
        calls["n"] += 1
        raise subprocess.TimeoutExpired(args[0], 0.1)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert tools._git_grep_candidates(repo, ["needle"], 10) is None
    assert tools._git_grep_candidates(repo, ["needle"], 10) is None
    assert calls["n"] == 1
    stats = tools.snapshot_stats()["git_files"]
    assert stats["grep_timeouts"] == 1
    assert stats["grep_cooldown_skips"] == 1
