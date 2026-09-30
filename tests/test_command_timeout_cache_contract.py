from __future__ import annotations

import pytest

from local_ai_hub.commands import CommandBroker


@pytest.mark.parametrize("outcome", ["timed_out", "cancelled"])
def test_timeout_and_cancelled_repeatable_commands_are_not_cached(tmp_path, monkeypatch, outcome: str) -> None:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True},
        }
    )
    command = "python -m pytest -q"
    assert broker.classify(command)["cacheable"] is True

    monkeypatch.setattr(broker, "_unavailable_executable", lambda command, cwd: None)
    def fixed_key(command, cwd, classification, *, tenant, timeout, tool_identity=None, phase_timings_ms=None, **_fingerprints):
        return "stable-key", {"fingerprint": "fixed", "changed_paths": []}

    monkeypatch.setattr(broker, "_key", fixed_key)
    executions: list[str] = []

    def execute(command, cwd, timeout, cancel_event=None, log_callback=None):
        executions.append(command)
        return {
            "success": False,
            "exit_code": -9,
            "timed_out": outcome == "timed_out",
            "cancelled": outcome == "cancelled",
            "aborted_interactive": False,
            "stdout": "",
            "stderr": "",
            "duration_ms": 0,
        }

    monkeypatch.setattr(broker, "_execute", execute)

    first = broker.run(command, str(tmp_path), tenant="test")
    second = broker.run(command, str(tmp_path), tenant="test")

    assert first["cache_hit"] is False
    assert second["cache_hit"] is False
    assert len(executions) == 2
