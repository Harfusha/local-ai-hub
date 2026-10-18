from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from local_ai_hub.commands import CommandBroker
from local_ai_hub.repo_state import RepoStateTracker


class _Artifacts:
    def put(self, *_args, **_kwargs):
        return "artifact"


def test_changed_repository_does_not_join_stale_singleflight(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)

    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "workspace_cache": {"fingerprint_ttl_seconds": 60.0},
        "commands": {"enabled": True, "coalesced_wait_seconds": 2},
    }
    broker = CommandBroker(config, _Artifacts(), RepoStateTracker(config))
    monkeypatch.setattr(broker, "_unavailable_executable", lambda *_args: None)
    started = {value: threading.Event() for value in ("value = 1\n", "value = 2\n")}
    release = {value: threading.Event() for value in started}
    executions: list[str] = []
    results: dict[str, dict] = {}
    errors: list[BaseException] = []

    def execute(_command, _cwd, _timeout, *_args, **_kwargs):
        value = source.read_text(encoding="utf-8")
        executions.append(value)
        started[value].set()
        if not release[value].wait(5):
            raise TimeoutError(f"test did not release {value!r}")
        return {
            "success": True,
            "exit_code": 0,
            "stdout": value,
            "stderr": "",
            "duration_ms": 1,
            "timed_out": False,
            "cancelled": False,
            "aborted_interactive": False,
        }

    monkeypatch.setattr(broker, "_execute", execute)

    def run(label: str) -> None:
        try:
            results[label] = broker.run("python -m pytest -q", str(repo))
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=run, args=("first",), daemon=True)
    second = threading.Thread(target=run, args=("second",), daemon=True)
    first.start()
    try:
        assert started["value = 1\n"].wait(3)
        source.write_text("value = 2\n", encoding="utf-8")
        second.start()
        assert started["value = 2\n"].wait(3)
        assert len(broker._inflight) == 2
    finally:
        for event in release.values():
            event.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert executions == ["value = 1\n", "value = 2\n"]
    assert results["first"]["success"] is True
    assert results["second"]["success"] is True
    assert results["first"]["coalesced"] is False
    assert results["second"]["coalesced"] is False
    assert results["first"]["cache_hit"] is False
    assert results["second"]["cache_hit"] is False
    assert results["first"]["stdout"] == "value = 1\n"
    assert results["second"]["stdout"] == "value = 2\n"
    assert results["first"]["repository_revision"] != results["second"]["repository_revision"]
