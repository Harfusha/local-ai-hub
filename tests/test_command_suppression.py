from __future__ import annotations

import sys
import threading
import time

from local_ai_hub.commands import CommandBroker


class _Artifacts:
    def put(self, *_args, **_kwargs):
        return "artifact"


class _RepoState:
    def fingerprint(self, _cwd):
        return {"fingerprint": "stable"}


def _broker(tmp_path):
    return CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
        },
        _Artifacts(),
        _RepoState(),
    )


def test_policy_block_is_terminal_and_suppressed(tmp_path):
    broker = _broker(tmp_path)

    first = broker.run("npm install", str(tmp_path), "tenant")
    second = broker.run("npm install", str(tmp_path), "tenant")

    assert first["policy_blocked"] is True
    assert first["terminal"] is True
    assert first["retryable"] is False
    assert second["suppression_cache_hit"] is True
    assert broker.stats()["blocked"] == 1


def test_missing_safe_executable_is_rejected_before_spawn(tmp_path, monkeypatch):
    import local_ai_hub.commands as module

    broker = _broker(tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    first = broker.run("rg needle", str(tmp_path), "tenant")
    second = broker.run("rg needle", str(tmp_path), "tenant")

    assert first["preflight"] is True
    assert first["terminal"] is True
    assert broker.executed == 0
    assert second["suppression_cache_hit"] is True


def test_missing_working_directory_is_rejected_before_fingerprint(tmp_path):
    broker = _broker(tmp_path)
    missing = tmp_path / "deleted-worktree"

    result = broker.run(f'"{sys.executable}" -m pytest -q', str(missing), "tenant")

    assert result.get("preflight") is True, result
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "working directory does not exist" in result["error"]
    assert broker.executed == 0


def test_cancel_stops_active_command_and_clears_broker_state(tmp_path):
    (tmp_path / "test_wait.py").write_text(
        "import time\n\ndef test_wait():\n    time.sleep(10)\n",
        encoding="utf-8",
    )
    broker = _broker(tmp_path)
    command = f'"{sys.executable}" -m pytest -q test_wait.py'
    result: dict = {}
    worker = threading.Thread(target=lambda: result.setdefault("value", broker.run(command, str(tmp_path), "tenant", timeout=1)))
    worker.start()
    deadline = time.monotonic() + 2
    while not broker.stats()["active_count"] and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        assert broker.stats()["active_count"] == 1
        cancelled = broker.cancel(command, str(tmp_path), "tenant")
        assert cancelled["success"] is True
        assert cancelled["cancellation_requested"] is True
    finally:
        worker.join(4)
    assert worker.is_alive() is False
    assert result["value"]["cancelled"] is True
    assert broker.stats()["active_count"] == 0
