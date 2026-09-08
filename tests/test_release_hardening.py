from __future__ import annotations

import ctypes
import io
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.commands import CommandBroker
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.external_tools import ExternalCodeIntelligence, MCPStdioClient
from local_ai_hub.process_utils import pid_alive
from local_ai_hub.repo_state import RepoStateTracker
from local_ai_hub.state_paths import configured_state_dir
from tools.release_check import _iter_release_hygiene_violations, run_checks

ROOT = Path(__file__).resolve().parents[1]


class _ReaderProc:
    def __init__(self, stdout: str = "", stderr: str = ""):
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)


class _LiveProc:
    def poll(self):
        return None


def test_mcp_reader_is_bound_to_process_generation_queue() -> None:
    client = MCPStdioClient(["dummy"])
    old_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    new_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    client._responses = new_queue
    proc = _ReaderProc('{"jsonrpc":"2.0","id":7,"result":{"ok":true}}\n')

    client._read_stdout(proc, old_queue)  # type: ignore[arg-type]

    assert old_queue.get_nowait()["id"] == 7
    assert new_queue.empty()


def test_mcp_explicit_short_deadline_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MCPStdioClient(["dummy"])
    client._proc = _LiveProc()  # type: ignore[assignment]
    monkeypatch.setattr(client, "_send", lambda _message: None)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        client._request("tools/list", {}, timeout=0.08, ensure_started=False)
    elapsed = time.monotonic() - started
    assert 0.05 <= elapsed < 0.30


def test_external_close_is_best_effort_across_all_sessions(tmp_path: Path) -> None:
    external = ExternalCodeIntelligence({"server": {"state_dir": str(tmp_path)}, "code_intelligence": {"enabled": False}})
    closed: list[str] = []

    class Bad:
        def close(self) -> None:
            closed.append("bad")
            raise RuntimeError("boom")

    class Good:
        def close(self) -> None:
            closed.append("good")

    external._serena_sessions["a"] = Bad()  # type: ignore[assignment]
    external._codegraph_sessions["b"] = Good()  # type: ignore[assignment]
    external.close()
    assert closed == ["bad", "good"]


def test_external_index_unexpected_failure_reaps_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    external = ExternalCodeIntelligence({"server": {"state_dir": str(tmp_path)}, "code_intelligence": {"enabled": False}})
    terminated: list[int] = []

    class BrokenProc:
        pid = 424242
        returncode = None
        def communicate(self, timeout=None):
            raise OSError("pipe failed")
        def poll(self):
            return None
        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr("local_ai_hub.external_tools.subprocess.Popen", lambda *a, **k: BrokenProc())
    monkeypatch.setattr("local_ai_hub.external_tools.terminate_tree", lambda pid, grace_seconds=1.0: terminated.append(pid) or True)
    result = external._run_index("serena", ["fake"], str(tmp_path))
    assert result["success"] is False
    assert terminated == [424242]


def test_repository_fingerprint_flight_wait_is_bounded() -> None:
    tracker = RepoStateTracker({"workspace_cache": {"fingerprint_flight_timeout_seconds": 0.05}})
    entered = threading.Event()
    release = threading.Event()

    def owner() -> None:
        with tracker._root_flight("root") as acquired:
            assert acquired is True
            entered.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=owner, daemon=True)
    thread.start()
    assert entered.wait(timeout=1)
    started = time.monotonic()
    with tracker._root_flight("root") as acquired:
        elapsed = time.monotonic() - started
        assert acquired is False
    release.set()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert 0.04 <= elapsed < 0.30
    assert tracker.stats()["flight_timeouts"] == 1


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="Linux /proc required")
def test_linux_zombie_is_not_reported_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exercise the Linux zombie branch deterministically. Spawning a real short-lived
    # child is flaky under a saturated CI host because the child can remain runnable
    # for longer than the test deadline before it ever gets scheduled.
    import local_ai_hub.process_utils as process_utils

    original_read_text = Path.read_text

    def fake_read_text(path: Path, *args, **kwargs):
        if str(path) == "/proc/4242/stat":
            return "4242 (python) Z 1 4242 4242 0 -1 0 0 0 0 0 0 0 0 0 0 1 0 0 0"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    monkeypatch.setattr(process_utils.os, "kill", lambda pid, sig: (_ for _ in ()).throw(AssertionError("kill(0) should not be needed for a zombie")))
    assert process_utils.pid_alive(4242) is False


def test_windows_exited_process_handle_is_not_reported_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    import local_ai_hub.process_utils as process_utils

    class Kernel32:
        def __init__(self, wait_result: int):
            self.wait_result = wait_result
            self.closed = 0
        def OpenProcess(self, access, inherit, pid):
            return 123
        def WaitForSingleObject(self, handle, timeout):
            return self.wait_result
        def CloseHandle(self, handle):
            self.closed += 1
            return 1

    exited = Kernel32(0)
    monkeypatch.setattr(process_utils.os, "name", "nt")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=exited), raising=False)
    assert process_utils.pid_alive(1234) is False
    assert exited.closed == 1

    running = Kernel32(0x00000102)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=running), raising=False)
    assert process_utils.pid_alive(1234) is True
    assert running.closed == 1


def test_partial_config_uses_private_temp_state_not_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    state = configured_state_dir({})
    assert state != tmp_path
    assert state.is_dir()

    CommandBroker({"commands": {"enabled": False}})
    EmbeddingModel({"features": {"rag": False}})
    DeterministicEngine({"deterministic": {"enabled": False}})

    assert not (tmp_path / "cache.sqlite3").exists()
    assert not (tmp_path / "deterministic.sqlite3").exists()


def test_fallback_state_is_pid_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    import local_ai_hub.state_paths as state_paths

    real_pid = os.getpid()
    monkeypatch.setattr(state_paths.os, "getpid", lambda: real_pid + 100000)
    first = configured_state_dir({})
    monkeypatch.setattr(state_paths.os, "getpid", lambda: real_pid + 100001)
    second = configured_state_dir({})
    try:
        assert first != second
        if os.name != "nt":
            assert first.stat().st_mode & 0o077 == 0
            assert second.stat().st_mode & 0o077 == 0
    finally:
        shutil.rmtree(first, ignore_errors=True)
        shutil.rmtree(second, ignore_errors=True)


def test_post_test_hygiene_allows_tooling_caches_but_not_runtime_db(tmp_path: Path) -> None:
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "x").write_text("x", encoding="utf-8")
    (tmp_path / "pkg.egg-info").mkdir()
    (tmp_path / "pkg.egg-info" / "PKG-INFO").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "__pycache__").mkdir(parents=True)
    (tmp_path / "src" / "__pycache__" / "x.pyc").write_bytes(b"x")
    (tmp_path / ".coverage").write_text("x", encoding="utf-8")
    (tmp_path / "cache.sqlite3").write_bytes(b"sqlite")

    violations = list(_iter_release_hygiene_violations(tmp_path, post_test=True))
    assert len(violations) == 1
    assert "cache.sqlite3" in violations[0]


def test_release_gate_can_bind_expected_tag_version() -> None:
    ok = run_checks(ROOT, expected_version="3.0.0", post_test=True)
    assert not [e for e in ok["errors"] if "expected release version" in e]
    bad = run_checks(ROOT, expected_version="v9.9.9", post_test=True)
    assert any("expected release version '9.9.9'" in e for e in bad["errors"])


def test_release_workflow_contracts() -> None:
    defaults = (ROOT / "defaults.toml").read_text(encoding="utf-8")
    assert "fingerprint_flight_timeout_seconds = 8.0" in defaults
    release_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    ci_workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--expected-version" in release_workflow
    assert "--post-test" in release_workflow and "--post-test" in ci_workflow
    assert "SHA256SUMS.txt" in release_workflow
    assert "git diff --exit-code" in release_workflow and "git diff --exit-code" in ci_workflow
    assert "ORIGINAL_REQUEST.md" not in {p.name for p in ROOT.iterdir()}
