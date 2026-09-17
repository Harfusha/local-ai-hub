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


def test_concurrent_mutating_commands_keep_separate_active_entries(tmp_path, monkeypatch):
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "allow_mutating": True},
        },
        _Artifacts(),
        _RepoState(),
    )
    command = "git add changed.py"
    started = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    call_lock = threading.Lock()
    calls = 0

    def execute(*_args, **_kwargs):
        nonlocal calls
        with call_lock:
            index = calls
            calls += 1
        started[index].set()
        assert release[index].wait(2)
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(broker, "_execute", execute)
    workers = [threading.Thread(target=broker.run, args=(command, str(tmp_path), "tenant")) for _ in range(2)]
    for worker in workers:
        worker.start()
    assert started[0].wait(2)
    assert started[1].wait(2)
    assert broker.stats()["active_count"] == 2

    release[0].set()
    deadline = time.monotonic() + 2
    while broker.stats()["active_count"] != 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert broker.stats()["active_count"] == 1

    release[1].set()
    for worker in workers:
        worker.join(5)
    assert all(not worker.is_alive() for worker in workers)


def test_concurrent_mutating_commands_require_exact_execution_id_for_cancel(tmp_path, monkeypatch):
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "allow_mutating": True},
        },
        _Artifacts(),
        _RepoState(),
    )
    command = "git add changed.py"
    started = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    call_lock = threading.Lock()
    calls = 0
    results = []

    def execute(*args, **_kwargs):
        nonlocal calls
        with call_lock:
            index = calls
            calls += 1
        started[index].set()
        assert release[index].wait(2)
        return {"success": False, "cancelled": args[3].is_set(), "exit_code": 1, "stdout": "", "stderr": ""}

    monkeypatch.setattr(broker, "_execute", execute)
    workers = [threading.Thread(target=lambda: results.append(broker.run(command, str(tmp_path), "tenant"))) for _ in range(2)]
    for worker in workers:
        worker.start()
    assert started[0].wait(2)
    assert started[1].wait(2)
    active = broker.stats()["active"]
    execution_ids = {item["execution_id"] for item in active}
    assert len(execution_ids) == 2

    ambiguous = broker.cancel(command, str(tmp_path), "tenant")
    assert ambiguous["success"] is False
    assert set(ambiguous["execution_ids"]) == execution_ids

    exact_id = next(iter(execution_ids))
    cancelled = broker.cancel("", "", "tenant", execution_id=exact_id)
    assert cancelled["success"] is True
    assert cancelled["execution_id"] == exact_id

    for event in release:
        event.set()
    for worker in workers:
        worker.join(2)
    assert all(not worker.is_alive() for worker in workers)
    assert {result["execution_id"] for result in results} == execution_ids


def test_execution_id_cannot_cross_cancel_same_prefix_tenant(tmp_path, monkeypatch):
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "allow_mutating": True},
        },
        _Artifacts(),
        _RepoState(),
    )
    started = threading.Event()
    release = threading.Event()
    tenant_prefix = "tenant-" + "x" * 80
    owner = tenant_prefix + "owner"
    other = tenant_prefix + "other"

    def execute(*_args, **_kwargs):
        started.set()
        assert release.wait(2)
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(broker, "_execute", execute)
    worker = threading.Thread(target=broker.run, args=("git add changed.py", str(tmp_path), owner))
    worker.start()
    assert started.wait(2)
    active = broker.stats()["active"]
    assert len(active) == 1
    assert "tenant" not in active[0]
    assert "tenant_identity" not in active[0]

    denied = broker.cancel("", "", other, execution_id=active[0]["execution_id"])
    assert denied["success"] is False
    assert denied["error"] == "no matching active command"

    release.set()
    worker.join(2)
    assert worker.is_alive() is False


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
