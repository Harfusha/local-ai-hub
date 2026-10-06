from __future__ import annotations

import os
import subprocess
import threading
import time

import pytest

from local_ai_hub.commands import CommandBroker


class _Artifacts:
    def put(self, *_args, **_kwargs):
        return "artifact"


class _RepoState:
    def fingerprint(self, _cwd):
        return {"fingerprint": "stable", "changed_paths": []}


def _broker(tmp_path, *, policy_blocking: bool = False, coalesced_wait_seconds: float = 1.0):
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "commands": {
            "enabled": True,
            "allow_read": True,
            "allow_validation": True,
            "policy_blocking": policy_blocking,
            "coalesced_wait_seconds": coalesced_wait_seconds,
        },
    }
    return CommandBroker(config, _Artifacts(), _RepoState())


def test_bypass_cache_skips_reads_and_does_not_write_results(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    command = "python -m pytest -q"
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    monkeypatch.setattr(
        broker,
        "_key",
        lambda _command, _cwd, _classification, **_kwargs: (
            "stable-key",
            {"fingerprint": "stable", "changed_paths": []},
        ),
    )
    executions = 0

    def execute(*_args, **_kwargs):
        nonlocal executions
        executions += 1
        return {
            "success": True,
            "exit_code": 0,
            "stdout": f"run-{executions}",
            "stderr": "",
            "duration_ms": 1,
        }

    monkeypatch.setattr(broker, "_execute", execute)

    initial = broker.run(command, str(tmp_path), tenant="test")
    bypassed = broker.run(command, str(tmp_path), tenant="test", bypass_cache=True)
    cached_again = broker.run(command, str(tmp_path), tenant="test")

    assert initial["stdout"] == "run-1"
    assert bypassed["cache_hit"] is False
    assert bypassed["stdout"] == "run-2"
    assert cached_again["cache_hit"] is True
    assert cached_again["stdout"] == "run-1"
    assert executions == 2


def test_bypass_cache_does_not_write_suppression_results(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    monkeypatch.setattr(
        broker, "_unavailable_executable", lambda _command, _cwd: "missing-tool"
    )

    bypassed = broker.run("missing-tool", str(tmp_path), tenant="test", bypass_cache=True)
    ordinary = broker.run("missing-tool", str(tmp_path), tenant="test")

    assert bypassed.get("preflight") is True
    assert ordinary.get("suppression_cache_hit") is not True
    assert ordinary.get("preflight") is True


def test_suppression_cache_does_not_cross_policy_configuration(tmp_path, monkeypatch) -> None:
    strict = _broker(tmp_path, policy_blocking=True)
    first = strict.run("unknown-tool", str(tmp_path), tenant="test")
    assert first["policy_blocked"] is True

    permissive = _broker(tmp_path, policy_blocking=False)
    monkeypatch.setattr(
        permissive, "_unavailable_executable", lambda _command, _cwd: "unknown-tool"
    )
    second = permissive.run("unknown-tool", str(tmp_path), tenant="test")

    assert second.get("suppression_cache_hit") is not True
    assert second.get("policy_blocked") is not True
    assert second.get("preflight") is True


def test_singleflight_waiter_receives_escaped_owner_timeout(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path, coalesced_wait_seconds=2.0)
    command = "python -m pytest -q"
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    monkeypatch.setattr(
        broker,
        "_key",
        lambda _command, _cwd, _classification, **_kwargs: (
            "stable-key",
            {"fingerprint": "stable", "changed_paths": []},
        ),
    )
    owner_entered = threading.Event()
    release_owner = threading.Event()

    def execute(actual_command, _cwd, timeout, *_args, **_kwargs):
        owner_entered.set()
        assert release_owner.wait(2.0)
        raise subprocess.TimeoutExpired(actual_command, timeout)

    monkeypatch.setattr(broker, "_execute", execute)
    owner_result: dict[str, object] = {}
    waiter_result: dict[str, object] = {}
    owner = threading.Thread(
        target=lambda: owner_result.update(
            broker.run(command, str(tmp_path), tenant="test", timeout=1)
        )
    )
    waiter = threading.Thread(
        target=lambda: waiter_result.update(
            broker.run(command, str(tmp_path), tenant="test", timeout=1)
        )
    )

    owner.start()
    assert owner_entered.wait(1.0)
    waiter.start()
    deadline = time.monotonic() + 1.0
    while broker.coalesced < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    coalesced_waiters = broker.coalesced
    release_owner.set()
    owner.join(2.0)
    waiter.join(2.0)

    assert not owner.is_alive()
    assert not waiter.is_alive()
    assert coalesced_waiters == 1
    assert owner_result.get("timed_out") is True
    assert waiter_result.get("timed_out") is True
    assert waiter_result.get("coalesced") is True
    assert waiter_result.get("error") == owner_result.get("error")


def test_command_cache_key_changes_with_environment_tool_and_revision(
    tmp_path, monkeypatch
) -> None:
    broker = _broker(tmp_path)
    broker.config["commands"]["environment_keys"] = ["T15_CACHE_CONTEXT"]
    command = "python -m pytest -q"
    classification = broker.classify(command)
    revision = {"value": "revision-one"}
    tool = {"value": "tool-one"}
    monkeypatch.setattr(
        broker.repo_state,
        "fingerprint",
        lambda _cwd: {"fingerprint": revision["value"], "changed_paths": []},
    )
    monkeypatch.setattr(broker, "_tool_identity", lambda *_args: tool["value"])
    monkeypatch.setenv("T15_CACHE_CONTEXT", "environment-one")

    env_one, _ = broker._key(command, str(tmp_path), classification)
    monkeypatch.setenv("T15_CACHE_CONTEXT", "environment-two")
    env_two, _ = broker._key(command, str(tmp_path), classification)
    tool["value"] = "tool-two"
    tool_two, _ = broker._key(command, str(tmp_path), classification)
    revision["value"] = "revision-two"
    revision_two, _ = broker._key(command, str(tmp_path), classification)

    assert len({env_one, env_two, tool_two, revision_two}) == 4


def test_command_result_cache_does_not_reuse_across_environment_values(
    tmp_path, monkeypatch
) -> None:
    broker = _broker(tmp_path)
    broker.config["commands"]["environment_keys"] = ["T15_CACHE_CONTEXT"]
    monkeypatch.setattr(broker, "_unavailable_executable", lambda *_args: None)
    monkeypatch.setattr(broker, "_tool_identity", lambda *_args: "fixed-tool")
    monkeypatch.setenv("T15_CACHE_CONTEXT", "environment-one")
    executions = 0

    def execute(*_args, **_kwargs):
        nonlocal executions
        executions += 1
        return {
            "success": True,
            "exit_code": 0,
            "stdout": os.environ["T15_CACHE_CONTEXT"],
            "stderr": "",
            "duration_ms": 1,
        }

    monkeypatch.setattr(broker, "_execute", execute)
    first = broker.run("python -m pytest -q", str(tmp_path), tenant="test")
    warm = broker.run("python -m pytest -q", str(tmp_path), tenant="test")
    monkeypatch.setenv("T15_CACHE_CONTEXT", "environment-two")
    changed = broker.run("python -m pytest -q", str(tmp_path), tenant="test")

    assert first["stdout"] == "environment-one"
    assert warm["cache_hit"] is True
    assert changed["cache_hit"] is False
    assert changed["stdout"] == "environment-two"
    assert executions == 2


def test_command_result_cache_observes_l1_and_l2_ttl(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    broker.success_cache.l1.ttl_seconds = 2
    broker.success_cache.l2.ttl_seconds = 10
    clock = {"monotonic": 0.0, "wall": 1000.0}
    monkeypatch.setattr(
        "local_ai_hub.cache.time.monotonic", lambda: clock["monotonic"]
    )
    monkeypatch.setattr("local_ai_hub.cache.time.time", lambda: clock["wall"])
    command = "python -m pytest -q"
    monkeypatch.setattr(broker, "_unavailable_executable", lambda *_args: None)
    monkeypatch.setattr(
        broker,
        "_key",
        lambda *_args, **_kwargs: (
            "stable-key",
            {"fingerprint": "stable", "changed_paths": []},
        ),
    )
    executions = 0

    def execute(*_args, **_kwargs):
        nonlocal executions
        executions += 1
        return {
            "success": True,
            "exit_code": 0,
            "stdout": f"run-{executions}",
            "stderr": "",
            "duration_ms": 1,
        }

    monkeypatch.setattr(broker, "_execute", execute)

    first = broker.run(command, str(tmp_path), tenant="test")
    warm = broker.run(command, str(tmp_path), tenant="test")
    clock.update(monotonic=3.0, wall=1003.0)
    l2_promoted = broker.run(command, str(tmp_path), tenant="test")
    clock.update(monotonic=15.0, wall=1015.0)
    expired = broker.run(command, str(tmp_path), tenant="test")

    assert first["cache_hit"] is False
    assert warm["cache_hit"] is True
    assert l2_promoted["cache_hit"] is True
    assert expired["cache_hit"] is False
    assert executions == 2
    assert expired["stdout"] == "run-2"


@pytest.mark.parametrize("outcome", ["success", "failure"])
@pytest.mark.parametrize("l1_ttl_seconds", [0, 10])
def test_configured_result_cache_l1_ttl_does_not_outlive_l2(
    tmp_path, monkeypatch, outcome: str, l1_ttl_seconds: int
) -> None:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {
                "enabled": True,
                "allow_read": True,
                "allow_validation": True,
                "success_ttl_seconds": 2,
                "failure_ttl_seconds": 2,
                "l1_ttl_seconds": l1_ttl_seconds,
            },
        },
        _Artifacts(),
        _RepoState(),
    )
    clock = {"monotonic": 0.0, "wall": 2000.0}
    monkeypatch.setattr(
        "local_ai_hub.cache.time.monotonic", lambda: clock["monotonic"]
    )
    monkeypatch.setattr("local_ai_hub.cache.time.time", lambda: clock["wall"])
    command = "python -m pytest -q"
    monkeypatch.setattr(broker, "_unavailable_executable", lambda *_args: None)
    monkeypatch.setattr(
        broker,
        "_key",
        lambda *_args, **_kwargs: (
            "stable-key",
            {"fingerprint": "stable", "changed_paths": []},
        ),
    )
    executions = 0

    def execute(*_args, **_kwargs):
        nonlocal executions
        executions += 1
        return {
            "success": outcome == "success",
            "retryable": outcome == "failure",
            "exit_code": 0 if outcome == "success" else 1,
            "stdout": f"run-{executions}",
            "stderr": "",
            "duration_ms": 1,
        }

    monkeypatch.setattr(broker, "_execute", execute)
    first = broker.run(command, str(tmp_path), tenant="test")
    clock.update(monotonic=3.0, wall=2003.0)
    expired = broker.run(command, str(tmp_path), tenant="test")

    assert first["cache_hit"] is False
    assert expired["cache_hit"] is False
    assert expired["stdout"] == "run-2"
    assert executions == 2


@pytest.mark.parametrize("l1_ttl_seconds", [0, 10])
def test_configured_suppression_l1_ttl_does_not_outlive_l2(
    tmp_path, monkeypatch, l1_ttl_seconds: int
) -> None:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {
                "enabled": True,
                "policy_blocking": True,
                "suppression_ttl_seconds": 2,
                "l1_ttl_seconds": l1_ttl_seconds,
            },
        },
        _Artifacts(),
        _RepoState(),
    )
    clock = {"monotonic": 0.0, "wall": 3000.0}
    monkeypatch.setattr(
        "local_ai_hub.cache.time.monotonic", lambda: clock["monotonic"]
    )
    monkeypatch.setattr("local_ai_hub.cache.time.time", lambda: clock["wall"])

    first = broker.run("unknown-tool", str(tmp_path), tenant="test")
    warm = broker.run("unknown-tool", str(tmp_path), tenant="test")
    clock.update(monotonic=3.0, wall=3003.0)
    expired = broker.run("unknown-tool", str(tmp_path), tenant="test")

    assert first["policy_blocked"] is True
    assert warm["suppression_cache_hit"] is True
    assert expired.get("suppression_cache_hit") is not True
