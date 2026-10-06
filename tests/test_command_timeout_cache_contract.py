from __future__ import annotations

import threading
import time

import pytest

from local_ai_hub.commands import CommandBroker


@pytest.mark.parametrize("outcome", ["timed_out", "cancelled", "outcome_unknown"])
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

    def execute(command, cwd, timeout, cancel_event=None, log_callback=None, **_kwargs):
        executions.append(command)
        return {
            "success": False,
            "exit_code": -9,
            "timed_out": outcome == "timed_out",
            "cancelled": outcome == "cancelled",
            "outcome_unknown": outcome == "outcome_unknown",
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
    assert "stable-key" not in broker._last


def test_singleflight_waiter_preserves_owner_timeout_without_trusting_outcome(
    tmp_path, monkeypatch
) -> None:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "coalesced_wait_seconds": 2},
        }
    )
    command = "python -m pytest -q"
    monkeypatch.setattr(broker, "_unavailable_executable", lambda *_args: None)
    monkeypatch.setattr(
        broker,
        "_key",
        lambda *_args: ("shared-key", {"fingerprint": "fixed", "changed_paths": []}),
    )
    owner_started = threading.Event()
    release_owner = threading.Event()
    executions: list[str] = []
    results: dict[str, dict] = {}

    def execute(*_args, **_kwargs):
        executions.append(command)
        owner_started.set()
        assert release_owner.wait(2)
        return {
            "success": False,
            "exit_code": -9,
            "timed_out": True,
            "outcome_unknown": True,
            "fail_closed": True,
            "retryable": False,
            "error": "timeout; process-tree cleanup unconfirmed",
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(broker, "_execute", execute)

    def run_as(name: str) -> None:
        results[name] = broker.run(command, str(tmp_path), tenant="test")

    owner = threading.Thread(target=run_as, args=("owner",))
    waiter = threading.Thread(target=run_as, args=("waiter",))
    owner.start()
    try:
        assert owner_started.wait(2)
        waiter.start()
        deadline = time.monotonic() + 2
        while broker.coalesced < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert broker.coalesced == 1
    finally:
        release_owner.set()
        owner.join(2)
        if waiter.ident is not None:
            waiter.join(2)

    assert owner.is_alive() is False
    assert waiter.is_alive() is False
    assert executions == [command]
    result = results["waiter"]
    assert result["timed_out"] is True
    assert result["outcome_unknown"] is True
    assert result["fail_closed"] is True
    assert result["retryable"] is False
    assert result["cache_hit"] is False
