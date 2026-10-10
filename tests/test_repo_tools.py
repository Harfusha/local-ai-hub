from __future__ import annotations

import hashlib
import io
import subprocess
import time
from pathlib import Path

from local_ai_hub.config import load_config
import local_ai_hub.repo_tools as repo_tools_module
from local_ai_hub.repo_tools import RepositoryTools


def test_git_diff_retains_bounded_text_but_hashes_full_stream(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "large.txt"
    baseline = "\n".join(f"base-{index}" for index in range(1200)) + "\n"
    target.write_text(baseline, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "large.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"], check=True)

    first = "\n".join(f"changed-{index}" for index in range(1200)) + "\nTAIL-A\n"
    target.write_text(first, encoding="utf-8")
    tools = RepositoryTools(_cfg(tmp_path))
    result_a = tools.git_diff(str(repo), max_tokens=32)

    second = "\n".join(f"changed-{index}" for index in range(1200)) + "\nTAIL-B\n"
    target.write_text(second, encoding="utf-8")
    result_b = tools.git_diff(str(repo), max_tokens=32)

    assert result_a["success"] and result_b["success"]
    assert result_a["truncated"] and result_b["truncated"]
    assert len(result_a["diff"]) < len(first) * 2
    assert len(result_a["diff_sha256"]) == 64
    assert result_a["diff_sha256"] != result_b["diff_sha256"]


def _cfg(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n[hardware]\nprofile="cpu"\n', encoding="utf-8")
    return load_config(str(path))


def test_generated_tool_metadata_never_enters_inventory(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("def main(): return 1\n", encoding="utf-8")
    for hidden in (
        ".serena", ".codegraphcontext", ".local-ai-hub", ".handoff",
        ".t03-main-preflight-overlay",
    ):
        d = repo / hidden
        d.mkdir()
        (d / "generated.py").write_text("SHOULD_NOT_INDEX = True\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    files = RepositoryTools(_cfg(tmp_path)).iter_files(str(repo))
    rel = {p.relative_to(repo).as_posix() for p in files}
    assert "src/main.py" in rel
    assert all(not p.startswith((
        ".serena/", ".codegraphcontext/", ".local-ai-hub/", ".handoff/",
        ".t03-main-preflight-overlay/",
    )) for p in rel)


def test_unity_generated_directories_never_enter_inventory(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "Assets").mkdir(parents=True)
    (repo / "Assets" / "game.cs").write_text("class Game {}\n", encoding="utf-8")
    for generated in ("Library", "Temp", "Logs", "UserSettings"):
        d = repo / generated
        d.mkdir()
        (d / "generated.cs").write_text("class Generated {}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    files = RepositoryTools(_cfg(tmp_path)).iter_files(str(repo))
    rel = {p.relative_to(repo).as_posix() for p in files}

    assert "Assets/game.cs" in rel
    assert all(not p.startswith(("Library/", "Temp/", "Logs/", "UserSettings/")) for p in rel)


def test_path_escape_is_rejected(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = _cfg(tmp_path)
    result = RepositoryTools(cfg).file_slice(str(repo), "../secret.txt", 1, 10)
    assert result["success"] is False


def test_repo_map_can_use_preindexed_paths_without_inventory(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    source = repo / "src" / "main.py"
    source.write_text("class Main:\n    pass\n", encoding="utf-8")
    tools = RepositoryTools(_cfg(tmp_path))

    monkeypatch.setattr(tools, "_git_files", lambda *_args: (_ for _ in ()).throw(AssertionError("inventory")))
    result = tools.repo_map(str(repo), paths=["src/main.py"])

    assert result["success"] is True
    assert result["files"] == 1
    assert result["symbols_sample"][0]["name"] == "Main"


def test_git_diff_on_non_git_root_is_a_terminal_client_result(tmp_path: Path):
    root = tmp_path / "plain-files"
    root.mkdir()

    result = RepositoryTools(_cfg(tmp_path)).git_diff(str(root))

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["error"] == "git diff requires a Git repository"


def test_repository_tools_returns_revision_and_changed_paths_for_guard(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tracked = repo / "main.py"
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "clean_one.py").write_text("VALUE = 10\n", encoding="utf-8")
    (repo / "clean_two.py").write_text("VALUE = 20\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "initial"],
        check=True,
    )
    tracked.write_text("VALUE = 2\n", encoding="utf-8")

    result = RepositoryTools(_cfg(tmp_path)).git_diff(str(repo))
    snapshot = RepositoryTools(_cfg(tmp_path)).git_snapshot(str(repo))

    assert result["revision"]
    assert result["changed_paths"] == ["main.py"]
    assert snapshot.changed_paths == ("main.py",)


def test_git_diff_base_range_lists_paths_beyond_content_cap(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    early = repo / "a_early.py"
    late = repo / "z_late.py"
    early.write_text("early = 1\n", encoding="utf-8")
    late.write_text("late = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "base"], check=True)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    early.write_text("early = 2\n", encoding="utf-8")
    late.write_text("\n".join(f"late = {index}" for index in range(3000)) + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "changes"], check=True)

    result = RepositoryTools(_cfg(tmp_path)).git_diff(str(repo), base=base, max_tokens=16)

    assert result["success"] is True
    assert result["truncated"] is True
    assert result["changed_paths"] == ["a_early.py", "z_late.py"]


def test_git_diff_rejects_path_capture_failure(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "main.py"
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "base"], check=True)
    target.write_text("value = 2\n", encoding="utf-8")

    real_popen = subprocess.Popen

    class FailedPathProcess:
        stdout = io.BytesIO()
        stderr = io.BytesIO(b"name-only capture failed")

        def wait(self, timeout=None):
            return 1

    def fake_popen(command, *args, **kwargs):
        if "--name-only" in command:
            return FailedPathProcess()
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(repo_tools_module, "popen_managed", fake_popen)
    result = RepositoryTools(_cfg(tmp_path)).git_diff(str(repo))

    assert result["success"] is False
    assert result["paths_complete"] is False
    assert result["retryable"] is True
    assert "path capture" in result["error"]


def test_git_diff_rejects_path_capture_cap(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "main.py"
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "base"], check=True)
    target.write_text("value = 2\n", encoding="utf-8")

    real_popen = subprocess.Popen

    class CappedPathProcess:
        stdout = io.BytesIO(("".join(f"path-{index}\0" for index in range(4097))).encode())
        stderr = io.BytesIO()

        def wait(self, timeout=None):
            return 0

    def fake_popen(command, *args, **kwargs):
        if "--name-only" in command:
            return CappedPathProcess()
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(repo_tools_module, "popen_managed", fake_popen)
    result = RepositoryTools(_cfg(tmp_path)).git_diff(str(repo))

    assert result["success"] is False
    assert result["paths_complete"] is False
    assert result["retryable"] is True
    assert "cap" in result["error"]


def test_git_diff_rejects_stream_read_failure(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "main.py"
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "base"], check=True)
    target.write_text("value = 2\n", encoding="utf-8")

    real_popen = subprocess.Popen

    class ExplodingStream:
        def read(self, _size):
            raise OSError("stream exploded")

        def close(self):
            return None

    class StreamFailureProcess:
        stdout = ExplodingStream()
        stderr = io.BytesIO()

        def wait(self, timeout=None):
            return 0

    def fake_popen(command, *args, **kwargs):
        if "--unified=3" in command:
            return StreamFailureProcess()
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(repo_tools_module, "popen_managed", fake_popen)
    result = RepositoryTools(_cfg(tmp_path)).git_diff(str(repo))

    assert result["success"] is False
    assert result["retryable"] is True
    assert "stream read" in result["error"]


def test_search_returns_bounded_retryable_result_after_accelerator_timeouts(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    tools = RepositoryTools(_cfg(tmp_path))
    tools._rg = "rg"
    tools.git_grep_timeout = 0.01

    calls = {"n": 0, "popen": 0, "killed": 0}
    def fake_run(*args, **kwargs):
        calls["n"] += 1
        raise subprocess.TimeoutExpired(args[0], 0.1)

    class TimeoutProcess:
        pid = 987654
        stdout = io.StringIO("")
        returncode = None

        def poll(self):
            return None

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("git", timeout)

    def fake_popen(*args, **kwargs):
        calls["popen"] += 1
        return TimeoutProcess()

    def fake_terminate_tree(_pid, grace_seconds=1.0, process_handle=None):
        calls["killed"] += 1

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(repo_tools_module, "popen_managed", fake_popen)
    monkeypatch.setattr(repo_tools_module, "terminate_tree", fake_terminate_tree)
    monkeypatch.setattr(tools, "iter_files", lambda *_args: (_ for _ in ()).throw(AssertionError("unbounded scan")))

    result = tools.search(str(repo), "needle")

    assert result["success"] is False
    assert result["retryable"] is True
    assert result["error"] == "bounded search accelerators timed out or failed"
    assert calls["n"] == 1
    assert calls["popen"] == 1
    assert calls["killed"] == 1


def test_git_grep_timeout_reaps_owned_process(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    tools = RepositoryTools(_cfg(tmp_path))
    tools.git_grep_timeout = 0.5
    calls = []

    class SlowOutput:
        def __iter__(self):
            time.sleep(0.6)
            yield "src/example.py:1:needle\n"

        def close(self):
            calls.append("stdout.close")

    class Process:
        pid = 43210
        stdout = SlowOutput()
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            self.returncode = -9
            return self.returncode

    process = Process()
    monkeypatch.setattr(repo_tools_module, "popen_managed", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        repo_tools_module,
        "terminate_tree",
        lambda pid, **kwargs: calls.append(("terminate", pid, kwargs.get("process_handle"))) or True,
    )

    matches, timed_out = tools._git_grep_candidates(repo, ["needle"], 5)

    assert matches is None
    assert timed_out is True
    assert calls[0] == ("terminate", process.pid, process)
    assert calls[1][0] == "wait"
