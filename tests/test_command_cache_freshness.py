from __future__ import annotations

import subprocess

from local_ai_hub.commands import CommandBroker
from local_ai_hub.repo_state import RepoStateTracker


def test_cached_command_rechecks_repo_after_immediate_file_change(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)

    state_dir = tmp_path / "hub-state"
    repo_state = RepoStateTracker({"workspace_cache": {"fingerprint_ttl_seconds": 60.0}})
    broker = CommandBroker(
        {
            "server": {"state_dir": str(state_dir)},
            "commands": {"enabled": True, "coalesced_wait_seconds": 2, "max_output_chars": 4096},
        },
        repo_state=repo_state,
    )
    executions: list[str] = []
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)

    def execute(_command, _cwd, _timeout, cancel_event=None, log_callback=None, **_kwargs):
        value = source.read_text(encoding="utf-8")
        executions.append(value)
        return {
            "success": True, "exit_code": 0, "stdout": value, "stderr": "",
            "duration_ms": 1, "timed_out": False, "cancelled": False,
            "aborted_interactive": False,
        }

    monkeypatch.setattr(broker, "_execute", execute)
    command = "python -m pytest -q"

    first = broker.run(command, str(repo))
    repeated = broker.run(command, str(repo))
    source.write_text("value = 2\n", encoding="utf-8")
    changed = broker.run(command, str(repo))

    assert first["cache_hit"] is False
    assert repeated["cache_hit"] is True
    assert changed["cache_hit"] is False
    assert changed["stdout"] == "value = 2\n"
    assert executions == ["value = 1\n", "value = 2\n"]
