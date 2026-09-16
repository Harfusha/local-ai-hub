from __future__ import annotations

import sys
import threading
from local_ai_hub.commands import CommandBroker


class _Artifacts:
    def put(self, *_args, **_kwargs):
        return "artifact"


class _RepoState:
    def fingerprint(self, _cwd):
        return {"fingerprint": "stable"}


def _default_broker(tmp_path):
    return CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True},
        },
        _Artifacts(),
        _RepoState(),
    )


def test_command_is_not_blocked_by_default(tmp_path):
    broker = _default_broker(tmp_path)
    res = broker.run(f'{sys.executable} -c "print(123)"', str(tmp_path), "tenant")
    assert res.get("policy_blocked") is not True
    assert res.get("success") is True
    assert "123" in res.get("stdout", "")


def test_mutating_command_bypasses_existing_singleflight(tmp_path, monkeypatch):
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "allow_mutating": True, "coalesced_wait_seconds": 1},
        },
        _Artifacts(),
        _RepoState(),
    )
    command = "git add changed.py"
    classification = broker.classify(command)
    assert classification["class"] == "mutating"
    key, _ = broker._key(command, str(tmp_path), classification)
    blocker = threading.Event()
    broker._inflight[key] = blocker
    calls = []

    def execute(*_args, **_kwargs):
        calls.append(command)
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(broker, "_execute", execute)

    result = broker.run(command, str(tmp_path), "tenant")

    assert result["success"] is True
    assert result["coalesced"] is False
    assert calls == [command]
    assert broker._inflight[key] is blocker
    assert blocker.is_set() is False


def test_non_cacheable_read_command_coalesces_existing_singleflight(tmp_path, monkeypatch):
    broker = _default_broker(tmp_path)
    command = "git status; git diff --check"
    classification = broker.classify(command)
    assert classification["class"] == "read"
    assert classification["cacheable"] is False
    key, _ = broker._key(command, str(tmp_path), classification)
    completed = threading.Event()
    completed.set()
    broker._inflight[key] = completed
    broker._last[key] = {"success": True, "exit_code": 0, "stdout": "cached", "stderr": ""}
    calls = []

    def execute(*_args, **_kwargs):
        calls.append(command)
        return {"success": True, "exit_code": 0, "stdout": "executed", "stderr": ""}

    monkeypatch.setattr(broker, "_execute", execute)

    result = broker.run(command, str(tmp_path), "tenant")

    assert result["success"] is True
    assert result["coalesced"] is True
    assert result["stdout"] == "cached"
    assert calls == []


def test_mutating_policy_block_is_not_suppressed(tmp_path):
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "policy_blocking": True, "allow_mutating": False},
        },
        _Artifacts(),
        _RepoState(),
    )

    first = broker.run("git add changed.py", str(tmp_path), "tenant")
    second = broker.run("git add changed.py", str(tmp_path), "tenant")

    assert first["policy_blocked"] is True
    assert second["policy_blocked"] is True
    assert second.get("suppression_cache_hit") is not True
    assert broker.stats()["blocked"] == 2


def test_docker_sandbox_mutation_is_not_suppressed(tmp_path, monkeypatch):
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "policy_blocking": True, "allow_mutating": False},
        },
        _Artifacts(),
        _RepoState(),
    )
    monkeypatch.setattr("local_ai_hub.commands.shutil.which", lambda name: "docker" if name == "docker" else None)

    first = broker.run("git add changed.py", str(tmp_path), "tenant", sandbox="docker")
    second = broker.run("git add changed.py", str(tmp_path), "tenant", sandbox="docker")

    assert first["policy_blocked"] is True
    assert "git add may mutate" in first["error"]
    assert second["policy_blocked"] is True
    assert second.get("suppression_cache_hit") is not True
    assert broker.stats()["blocked"] == 2


def test_non_mutating_policy_block_remains_suppressed(tmp_path):
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "policy_blocking": True, "allow_unknown": False},
        },
        _Artifacts(),
        _RepoState(),
    )

    first = broker.run("unknown-tool", str(tmp_path), "tenant")
    second = broker.run("unknown-tool", str(tmp_path), "tenant")

    assert first["policy_blocked"] is True
    assert second["suppression_cache_hit"] is True
    assert broker.stats()["blocked"] == 1


def test_error_distillation_on_command_failure(tmp_path):
    broker = _default_broker(tmp_path)
    res = broker.run(f'{sys.executable} -c "raise ValueError(\'custom_failure_test\')"', str(tmp_path), "tenant")
    assert res.get("success") is False
    assert res.get("policy_blocked") is not True
    assert "error_distillation" in res
    assert "custom_failure_test" in res["error_distillation"]
