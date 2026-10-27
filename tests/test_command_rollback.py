from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from local_ai_hub import commands as commands_module
from local_ai_hub.commands import CommandBroker, _get_windows_dacl, _windows_dacl_bytes
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.artifacts import ArtifactStore
from fencing_lease_support import FakeFencingLeaseStore, install_test_work_attempt_fence
from local_ai_hub.process_utils import hidden_run_kwargs


class _FakeTaskStore:
    def __init__(
        self,
        worktree_path: str,
        *,
        repo_root: str | None = None,
        branch: str | None = None,
    ) -> None:
        self.worktree_path = worktree_path
        path = Path(worktree_path).resolve()
        path.mkdir(parents=True, exist_ok=True)
        probe = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False, timeout=10, **hidden_run_kwargs()
        )
        if probe.returncode != 0:
            subprocess.run(
                ["git", "init"], cwd=str(path), capture_output=True, check=True,
                timeout=10, **hidden_run_kwargs()
            )
        top = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, timeout=10, **hidden_run_kwargs()
        ).stdout.strip()
        current_branch = subprocess.run(
            ["git", "-C", str(path), "symbolic-ref", "--quiet", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10, **hidden_run_kwargs()
        ).stdout.strip()
        self.worktree_identity = {
            "repo_root": repo_root or top,
            "branch": branch or current_branch,
        }

    def get(self, task_id: str):
        if task_id != "task-owned":
            return None
        return SimpleNamespace(
            checkpoint=SimpleNamespace(
                state_data={"worktree": {
                    "success": True, "worktree_path": self.worktree_path,
                    **self.worktree_identity,
                }}
            )
        )


@pytest.mark.parametrize("execution_mode", ["command_failure", "timeout"])
def test_rollback_restore_oserror_marks_outcome_unknown_and_invalidates_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, execution_mode: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    owned = repo / "owned.txt"
    owned.write_text("before", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "add", "owned.txt"], cwd=str(repo), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(repo), capture_output=True, check=True, **hidden_run_kwargs())

    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}}, artifacts=None, repo_state=None)
    broker.set_task_store(_FakeTaskStore(str(repo)))
    classification = {"class": "validation", "allowed": True, "cacheable": True, "reason": "test"}
    monkeypatch.setattr(broker, "classify", lambda *_args, **_kwargs: classification)
    command = "pytest -q"
    command_cache_key = broker._key(command, str(repo), classification)[0]
    caches = (broker.success_cache, broker.failure_cache, broker.suppression_cache)
    cache_keys = ("rollback-success-stale", "rollback-failure-stale", "rollback-suppression-stale")
    for cache, key in zip(caches, cache_keys):
        cache.set(key, {"success": True})

    def fail_execute(*_args: object, **_kwargs: object) -> dict[str, object]:
        if execution_mode == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        return {"success": False, "exit_code": 1, "stdout": "", "stderr": "command failed"}

    monkeypatch.setattr(broker, "_execute", fail_execute)

    def fail_restore(_cwd: str, _snapshot: object) -> None:
        raise OSError("rollback restore failed")

    monkeypatch.setattr(commands_module, "_restore_rollback_scope", fail_restore)
    result = broker.run(
        command,
        str(repo),
        force=True,
        task_id="task-owned",
        rollback_on_failure=True,
        rollback_paths=["owned.txt"],
    )

    assert result["success"] is False
    assert result["rolled_back"] is False
    assert result["outcome_unknown"] is True
    assert result["failure_kind"] == "rollback_incomplete"
    assert result["retryable"] is False
    assert result["terminal"] is True
    assert all(cache.get(key) is None for cache, key in zip(caches, cache_keys))
    assert broker.failure_cache.get(command_cache_key) is None
    assert command_cache_key not in broker._last
def _commit_task_worktree(root: Path, *paths: str) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "add", *paths], cwd=root, capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "initial"], cwd=root, capture_output=True, check=True, **hidden_run_kwargs())


def test_untrusted_python_scripts_require_mutation_policy(tmp_path: Path) -> None:
    broker = CommandBroker({
        "server": {"state_dir": str(tmp_path / "state")},
        "commands": {"allow_read": True, "allow_validation": True, "allow_mutating": False},
    }, artifacts=None, repo_state=None)

    for command in (
        "python tools/custom_side_effect.py",
        "python tools/custom_report.py",
    ):
        result = broker.classify(command)

        assert result["class"] == "mutating"
        assert result["allowed"] is False
        assert result["cacheable"] is False


def _write_concurrent_rollback_edit(path: str, complete) -> None:
    Path(path).write_text("concurrent edit", encoding="utf-8")
    complete.set()


def test_command_rollback_on_failure_preserves_unowned_changes(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    tracked = tmp_path / "app.py"
    tracked.write_text("initial content", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    tracked.write_text("user's dirty baseline", encoding="utf-8")
    unrelated = tmp_path / "unrelated.py"
    unrelated.write_text("committed", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.py"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "unrelated"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    unrelated.write_text("pre-existing user edit", encoding="utf-8")
    preexisting = tmp_path / "preexisting.tmp"
    preexisting.write_text("keep", encoding="utf-8")
    external_alias = tmp_path / "external-alias.tmp"
    external_alias.write_text("foreign bytes", encoding="utf-8")

    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path)}, "commands": {"allowed": True, "allow_mutating": True}},
        artifacts=None,
        repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))

    def execute_in_private_tree(argv, cwd, *_args, **_kwargs):
        transaction = Path(cwd)
        assert argv[:3] == ["docker", "run", "--rm"]
        assert "--network=none" in argv
        assert "--read-only" in argv
        assert transaction.resolve() != tmp_path.resolve()
        (transaction / "app.py").write_text("corrupted", encoding="utf-8")
        (transaction / "unwanted.tmp").write_text("trash", encoding="utf-8")
        (tmp_path / "concurrent.tmp").write_text("foreign", encoding="utf-8")
        tracked.unlink()
        tracked.hardlink_to(external_alias)
        return {"success": False, "exit_code": 1, "stdout": "", "stderr": "simulated command failure", "duration_ms": 1}

    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    monkeypatch.setattr(broker, "_execute", execute_in_private_tree)
    result = broker.run(
        "git add app.py",
        str(tmp_path),
        force=True,
        task_id="task-owned",
        rollback_on_failure=True,
        rollback_paths=["app.py", "unwanted.tmp"],
    )

    assert result["success"] is False
    assert result.get("rolled_back") is False
    assert result.get("outcome_unknown") is True, result
    assert result.get("fail_closed") is True
    assert "transaction source path changed while command was running" in result.get("rollback_error", "")
    # A same-path hardlink appeared while private command ran. Preserve foreign source state.
    assert tracked.read_text(encoding="utf-8") == "foreign bytes"
    assert tracked.samefile(external_alias)
    assert not (tmp_path / "unwanted.tmp").exists()
    assert unrelated.read_text(encoding="utf-8") == "pre-existing user edit"
    assert preexisting.read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "concurrent.tmp").read_text(encoding="utf-8") == "foreign"
    assert external_alias.read_text(encoding="utf-8") == "foreign bytes"


def test_command_rollback_restores_only_declared_write_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    owned = tmp_path / "owned.txt"
    owned.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "owned.txt"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    user_file = tmp_path / "user-untracked.txt"
    user_file.write_text("keep user data\n", encoding="utf-8")
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path)}, "commands": {"allow_mutating": True}},
        artifacts=None, repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    def fail_in_private_tree(argv: object, cwd: str, *_args: object, **_kwargs: object) -> dict[str, object]:
        transaction_root = Path(cwd)
        (transaction_root / "owned.txt").write_text("corrupted\n", encoding="utf-8")
        (transaction_root / "undeclared.txt").write_text("outside write set\n", encoding="utf-8")
        return {"success": False, "exit_code": 1, "stdout": "", "stderr": "failed"}

    monkeypatch.setattr(broker, "_execute", fail_in_private_tree)
    result = broker.run(
        "git add owned.txt",
        str(tmp_path),
        force=True,
        task_id="task-owned",
        paths=["owned.txt"],
        rollback_on_failure=True,
        rollback_paths=["owned.txt"],
    )

    assert result["success"] is False
    assert result["rolled_back"] is True
    assert owned.read_text(encoding="utf-8") == "before\n"
    assert user_file.read_text(encoding="utf-8") == "keep user data\n"
    assert not (tmp_path / "undeclared.txt").exists()












@pytest.mark.parametrize("write_scope", ("rollback_paths", "paths"))
def test_failed_mutating_run_discards_private_transaction_without_source_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_scope: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    owned = repo / "owned.txt"
    owned.write_text("before", encoding="utf-8")
    unrelated = repo / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "add", "owned.txt", "unrelated.txt"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}, "commands": {"allow_mutating": True, "allow_unknown": True}},
        artifacts=None, repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(repo)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())

    class _IncidentStore:
        outcome = None

        def capture(self, outcome):
            self.outcome = outcome
            return None

        def find_regressions(self, *_args, **_kwargs):
            return []

        def find_negative_knowledge(self, **_kwargs):
            return []

    incidents = _IncidentStore()
    broker.set_incident_store(incidents)
    verification_receipts: list[object] = []
    monkeypatch.setattr(broker, "_record_command_verification", lambda *args, **kwargs: verification_receipts.append((args, kwargs)))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    def fail_private_execution(argv, cwd, *_args, **_kwargs):
        assert argv[:3] == ["docker", "run", "--rm"]
        Path(cwd, "owned.txt").write_text("after", encoding="utf-8")
        return {
            "success": False, "exit_code": 2, "stdout": "", "stderr": "failed",
            "timed_out": False, "duration_ms": 1,
        }

    monkeypatch.setattr(broker, "_execute", fail_private_execution)
    command = 'python -c "import pathlib,sys; pathlib.Path(\'owned.txt\').write_text(\'after\'); sys.exit(2)"'
    write_kwargs = {write_scope: ["owned.txt"]}
    result = broker.run(
        command, str(repo), force=True, task_id="task-owned", rollback_on_failure=True,
        **write_kwargs,
    )

    assert result["success"] is False
    assert result["transaction_status"] == "discarded"
    assert result["failure_kind"] == "command_failed"
    assert result.get("rolled_back") is True
    assert result.get("outcome_unknown") is False
    assert incidents.outcome is not None
    assert "failed" in incidents.outcome.error.lower()
    assert len(verification_receipts) == 1
    assert verification_receipts[0][0][0]["success"] is False
    assert owned.read_text(encoding="utf-8") == "before"
    assert unrelated.read_text(encoding="utf-8") == "keep"

def test_run_uses_rollback_paths_as_write_set_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owned.txt").write_text("before", encoding="utf-8")
    _commit_task_worktree(repo, "owned.txt")
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"allow_mutating": True},
        },
        artifacts=None,
        repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(repo)))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    executed: list[bool] = []

    def fake_execute(*_args: object, **_kwargs: object) -> dict[str, object]:
        executed.append(True)
        return {
            "success": True,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "duration_ms": 1,
        }

    monkeypatch.setattr(broker, "_execute", fake_execute)
    result = broker.run(
        "git add owned.txt",
        str(repo),
        force=True,
        task_id="task-owned",
        rollback_paths=["owned.txt"],
    )

    assert result["success"] is True
    assert executed == [True]

def test_expired_work_attempt_cannot_import_or_recover_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from local_ai_hub.work_fencing import FencingLeaseStore

    repo = tmp_path / "repo"
    repo.mkdir()
    owned = repo / "owned.txt"
    owned.write_text("before", encoding="utf-8")
    _commit_task_worktree(repo, "owned.txt")
    state_dir = tmp_path / "state"
    clock = [100.0]
    fencing_store = FencingLeaseStore(
        state_dir / "work-fencing.sqlite3",
        clock=lambda: clock[0],
    )
    attempt = fencing_store.claim_attempt(
        str(repo), "task-owned", "owner-one", ttl_seconds=5
    )
    broker = CommandBroker(
        {
            "server": {"state_dir": str(state_dir)},
            "commands": {"allow_mutating": True},
        },
        artifacts=None,
        repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(repo)))
    broker.set_fencing_lease_store(fencing_store)
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    executed: list[bool] = []

    def fake_execute(_argv, cwd, *_args, **_kwargs):
        executed.append(True)
        (Path(cwd) / "owned.txt").write_text("after", encoding="utf-8")
        clock[0] = attempt.expires_at + 1
        return {
            "success": True,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "duration_ms": 1,
        }

    monkeypatch.setattr(broker, "_execute", fake_execute)
    result = broker.run(
        "git add owned.txt",
        str(repo),
        force=True,
        task_id="task-owned",
        rollback_paths=["owned.txt"],
        _work_attempt_fence=attempt,
    )

    assert result["success"] is False
    assert owned.read_text(encoding="utf-8") == "before"
    transaction_parent = state_dir / "command-transactions"
    assert not list(transaction_parent.glob("*.journal.json"))

    before = commands_module.RollbackFileSnapshot(
        b"before", 0o644, {}, None, None, None
    )
    after = commands_module.RollbackFileSnapshot(
        b"after", 0o644, {}, None, None, None
    )
    journal_path = transaction_parent / "stale-attempt.journal.json"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_payload = {
        "schema": 1,
        "transaction_id": "stale-attempt",
        "task_id": "task-owned",
        "source_root": str(repo.resolve()),
        "transaction_root": str(transaction_parent / "stale-attempt"),
        "paths": ["owned.txt"],
        "files": {
            "owned.txt": {
                "before": broker._transaction_file_payload(before),
                "after": broker._transaction_file_payload(after),
            }
        },
        "fencing": {"lease_id": "expired-lease", "fencing_token": 1},
        "attempt_fence": broker._work_attempt_fence_payload(attempt),
    }
    journal_path.write_text(json.dumps(journal_payload), encoding="utf-8")
    journal_before = journal_path.read_bytes()

    recovery_result = broker.run(
        "git add owned.txt",
        str(repo),
        force=True,
        task_id="task-owned",
        rollback_paths=["owned.txt"],
        _work_attempt_fence=attempt,
    )

    assert recovery_result["success"] is False
    assert executed == [True]
    assert owned.read_text(encoding="utf-8") == "before"
    assert journal_path.read_bytes() == journal_before


def test_rollback_oserror_marks_outcome_unknown_invalidates_caches_and_records_incident(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    owned = repo / "owned.txt"
    owned.write_text("before", encoding="utf-8")
    unrelated = repo / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "add", "owned.txt", "unrelated.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repo, check=True)
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}, "commands": {"allowed": True, "allow_mutating": True}}, artifacts=None, repo_state=None)
    broker.set_task_store(_FakeTaskStore(str(repo)))

    class _IncidentStore:
        outcome = None

        def capture(self, outcome):
            self.outcome = outcome
            return None

        def find_regressions(self, *_args, **_kwargs):
            return []

        def find_negative_knowledge(self, **_kwargs):
            return []

    incidents = _IncidentStore()
    broker.set_incident_store(incidents)
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    def fail_private_rollback_verification(*_args, **_kwargs):
        raise OSError("transaction source path changed while command was running: simulated rollback failure")

    monkeypatch.setattr(commands_module, "verify_transaction_source_unchanged", fail_private_rollback_verification)
    receipts: list[object] = []
    monkeypatch.setattr(broker, "_record_command_verification", lambda *args, **kwargs: receipts.append((args, kwargs)))
    deleted: dict[str, list[str]] = {"success": [], "failure": [], "suppression": []}
    for name in deleted:
        cache = getattr(broker, f"{name}_cache")
        original_delete = cache.delete

        def record_delete(key, *, _name=name, _delete=original_delete):
            deleted[_name].append(key)
            return _delete(key)

        monkeypatch.setattr(cache, "delete", record_delete)

    def fail_success_delete(key):
        deleted["success"].append(key)
        return False

    monkeypatch.setattr(broker.success_cache, "delete", fail_success_delete)

    def fail_restore(*_args, **_kwargs):
        raise OSError("simulated rollback failure")

    monkeypatch.setattr(commands_module, "_restore_rollback_scope", fail_restore)
    def fail_execution(*_args, **_kwargs):
        owned.write_text("after", encoding="utf-8")
        return {"success": False, "exit_code": 2, "stdout": "", "stderr": "simulated command failure", "duration_ms": 1}

    monkeypatch.setattr(broker, "_execute", fail_execution)
    command = "git add owned.txt"
    result = broker.run(
        command, str(repo), force=True, task_id="task-owned", rollback_on_failure=True,
        rollback_paths=["owned.txt"],
    )

    assert result["success"] is False
    assert result.get("rolled_back") is False
    assert result.get("outcome_unknown") is True, result
    assert result.get("fail_closed") is True
    assert result.get("incident_required") is True
    assert "simulated rollback failure" in result.get("rollback_error", "")
    assert result.get("cache_invalidation_failed") is True
    assert result.get("cache_invalidation_errors")
    assert result.get("rollback_paths") == ["owned.txt"]
    assert incidents.outcome is not None
    assert "rollback" in incidents.outcome.error.lower()
    assert receipts == []
    assert deleted["suppression"]
    assert deleted["success"] and deleted["failure"]
    assert owned.read_text(encoding="utf-8") == "after"
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_rollback_reports_suppressed_sqlite_cache_delete_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}}, artifacts=None, repo_state=None)
    cache = broker.success_cache
    # Exercise the non-coordinated fallback where SQLiteCache.delete suppresses
    # SQLITE_BUSY and returns its fallback value instead of raising.
    cache._coordinator = None

    def busy_connect():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache.l2, "_connect", busy_connect)
    result: dict[str, object] = {}
    broker._mark_rollback_outcome_unknown(
        result,
        command_key="command-key",
        attempt_key="attempt-key",
        error=OSError("rollback failed"),
    )

    assert result.get("outcome_unknown") is True
    assert result.get("cache_invalidation_failed") is True
    assert result.get("cache_invalidation_errors")


def test_rollback_cache_delete_exception_still_clears_shared_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    broker = CommandBroker(config, artifacts=None, repo_state=None)
    reader = CommandBroker(config, artifacts=None, repo_state=None)
    cache = broker.success_cache
    reader_cache = reader.success_cache
    command_key = "command-key"
    cache.set(command_key, {"success": True, "value": "stale"})
    assert reader_cache.get(command_key) == {"success": True, "value": "stale"}

    clear_calls = 0
    original_clear = cache.clear

    def tracked_clear() -> int:
        nonlocal clear_calls
        clear_calls += 1
        return original_clear()

    def fail_delete(_key: str) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache, "clear", tracked_clear)
    monkeypatch.setattr(cache.l2, "_delete_strict", fail_delete)
    result: dict[str, object] = {}

    broker._mark_rollback_outcome_unknown(
        result,
        command_key=command_key,
        attempt_key="attempt-key",
        error=OSError("rollback failed"),
    )

    assert result.get("outcome_unknown") is True
    assert result.get("cache_invalidation_failed") is True
    assert clear_calls == 1
    assert reader_cache.get(command_key) is None


def test_command_rollback_requires_explicit_scope(tmp_path: Path) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    result = broker.run(
        "git status --short",
        str(tmp_path),
        force=True,
        task_id="task-owned",
        rollback_on_failure=True,
    )

    assert result["success"] is False
    assert result.get("rolled_back") is False
    assert result.get("rollback_scope_required") is True
    assert not (tmp_path / "keep.tmp").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows paths are case-insensitive by default")
def test_rollback_scope_rejects_case_aliases_in_write_set(tmp_path: Path) -> None:
    snapshot, error = commands_module._snapshot_rollback_scope(
        str(tmp_path), ["owned.txt", "OWNED.TXT"]
    )
    try:
        assert snapshot is None
        assert error is not None and "duplicate" in error
    finally:
        if snapshot is not None:
            commands_module._close_rollback_root(snapshot.root_guard)


def test_rollback_worktree_preflight_happens_before_snapshot_handle_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)
    snapshot_calls: list[tuple[str, list[str] | None]] = []

    def snapshot(cwd: str, paths: list[str] | None):
        snapshot_calls.append((cwd, paths))
        return SimpleNamespace(root_guard=123), None

    monkeypatch.setattr(commands_module, "_snapshot_rollback_scope", snapshot)
    result = broker.run(
        'python -c "pass"',
        str(tmp_path),
        force=True,
        task_id="task-without-registration",
        rollback_on_failure=True,
        rollback_paths=["owned.txt"],
    )

    assert result["mutation_worktree_required"] is True
    assert snapshot_calls == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX atomic no-replace rollback quarantine")
def test_rollback_preserves_concurrent_replacement_when_removing_created_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "created.txt"
    displaced = tmp_path / "displaced-transaction-output.txt"
    snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
    assert error is None and snapshot is not None
    target.write_text("transaction output\n", encoding="utf-8")
    commands_module._capture_rollback_postimages(snapshot)
    original_postimage_at = commands_module._rollback_postimage_at
    postimage_checks = 0

    def replace_after_final_check(parent_handle: int, leaf: str):
        nonlocal postimage_checks
        postimage_checks += 1
        result = original_postimage_at(parent_handle, leaf)
        # Capture happened before this hook. Replace the path immediately
        # after rollback's final pre-quarantine postimage check.
        if postimage_checks == 2:
            target.replace(displaced)
            target.write_text("concurrent replacement\n", encoding="utf-8")
        return result

    monkeypatch.setattr(commands_module, "_rollback_postimage_at", replace_after_final_check)
    try:
        with pytest.raises(OSError, match="changed postimages"):
            commands_module._restore_rollback_scope(str(tmp_path), snapshot)

        assert postimage_checks == 3
        assert target.read_text(encoding="utf-8") == "concurrent replacement\n"
        assert displaced.read_text(encoding="utf-8") == "transaction output\n"
        assert not list(tmp_path.glob(".local-ai-rollback-*"))
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-based rollback deletion race")
def test_windows_rollback_preserves_path_replaced_after_postimage_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "created.txt"
    displaced = tmp_path / "displaced-transaction-output.txt"
    snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
    assert error is None and snapshot is not None
    target.write_text("transaction output\n", encoding="utf-8")
    commands_module._capture_rollback_postimages(snapshot)
    original_postimage_at = commands_module._rollback_postimage_at
    postimage_checks = 0

    def replace_after_preopen_check(parent_handle: int, leaf: str):
        nonlocal postimage_checks
        postimage_checks += 1
        result = original_postimage_at(parent_handle, leaf)
        if leaf == target.name and postimage_checks == 2:
            target.replace(displaced)
            target.write_text("concurrent replacement\n", encoding="utf-8")
        return result

    monkeypatch.setattr(commands_module, "_rollback_postimage_at", replace_after_preopen_check)
    try:
        with pytest.raises(OSError, match="changed postimages"):
            commands_module._restore_rollback_scope(str(tmp_path), snapshot)

        assert postimage_checks >= 2
        assert target.read_text(encoding="utf-8") == "concurrent replacement\n"
        assert displaced.read_text(encoding="utf-8") == "transaction output\n"
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)


def test_command_rollback_preserves_concurrent_edit_to_declared_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "owned.txt"
    target.write_text("before\n", encoding="utf-8")
    unrelated = tmp_path / "foreign.txt"
    unrelated.write_text("keep foreign bytes\n", encoding="utf-8")
    _commit_task_worktree(tmp_path, target.name, unrelated.name)
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path)}, "commands": {"allow_mutating": True}},
        artifacts=None, repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    def fail_after_command_write(_argv: object, cwd: str, *_args: object, **_kwargs: object) -> dict[str, object]:
        (Path(cwd) / target.name).write_text("transaction postimage\n", encoding="utf-8")
        target.write_text("user concurrent edit\n", encoding="utf-8")
        return {"success": False, "exit_code": 1, "stdout": "", "stderr": "failed"}

    monkeypatch.setattr(broker, "_execute", fail_after_command_write)

    result = broker.run(
        "git add owned.txt",
        str(tmp_path),
        force=True,
        task_id="task-owned",
        paths=[target.name],
        rollback_on_failure=True,
        rollback_paths=[target.name],
    )

    assert result["success"] is False
    assert result["rolled_back"] is False
    assert result.get("outcome_unknown") is True, result
    assert result.get("fail_closed") is True
    assert result.get("incident_required") is True
    assert "transaction source path changed" in result.get("rollback_error", "")
    assert target.read_text(encoding="utf-8") == "user concurrent edit\n"
    assert unrelated.read_text(encoding="utf-8") == "keep foreign bytes\n"




def test_run_can_leave_verification_receipt_to_task_orchestrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Artifacts:
        def put_json(self, *_args: object, **_kwargs: object) -> str:
            return "artifact-proof"

    class _VerificationStore:
        def __init__(self) -> None:
            self.records: list[object] = []



@pytest.mark.skipif(os.name != "nt", reason="Windows handle-based atomic no-replace publication")
def test_windows_rollback_does_not_replace_leaf_created_after_absence_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "owned.txt"
    target.write_text("preimage\n", encoding="utf-8")
    snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
    assert error is None and snapshot is not None
    target.unlink()
    commands_module._capture_rollback_postimages(snapshot)

    original_rename = commands_module._rename_windows_handle

    def create_foreign_before_rename(
        handle: int, parent_handle: int, name: str, *, replace_if_exists: bool = True
    ) -> None:
        assert replace_if_exists is False
        target.write_text("foreign replacement\n", encoding="utf-8")
        original_rename(
            handle,
            parent_handle,
            name,
            replace_if_exists=replace_if_exists,
        )

    monkeypatch.setattr(commands_module, "_rename_windows_handle", create_foreign_before_rename)
    try:
        with pytest.raises(OSError):
            commands_module._restore_rollback_scope(str(tmp_path), snapshot)
        assert target.read_text(encoding="utf-8") == "foreign replacement\n"
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)


def test_patch_and_verify_rollback_preserves_concurrent_foreign_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(tmp_path), capture_output=True,
            text=True, check=True, **hidden_run_kwargs()
        )

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    owned = tmp_path / "owned.txt"
    foreign = tmp_path / "foreign.txt"
    owned.write_text("before\n", encoding="utf-8")
    foreign.write_text("committed\n", encoding="utf-8")
    git("add", "owned.txt", "foreign.txt")
    git("commit", "-m", "initial")
    foreign.write_text("pre-existing dirty edit\n", encoding="utf-8")
    unknown = tmp_path / "unknown.tmp"
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    def fail_after_foreign_changes(*_args: object, **_kwargs: object) -> dict[str, object]:
        foreign.write_text("concurrent foreign edit\n", encoding="utf-8")
        unknown.write_text("unknown untracked file\n", encoding="utf-8")
        return {"success": False, "exit_code": 1, "stdout": "", "stderr": "failed"}

    monkeypatch.setattr(broker, "run", fail_after_foreign_changes)
    patch = "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-before\n+after\n"

    result = broker.patch_and_verify(
        patch, str(tmp_path), command="verify", task_id="task-owned", auto_rollback=True
    )

    assert result["success"] is False
    assert result["rolled_back"] is True
    assert owned.read_text(encoding="utf-8") == "before\n"
    assert foreign.read_text(encoding="utf-8") == "concurrent foreign edit\n"
    assert unknown.read_text(encoding="utf-8") == "unknown untracked file\n"


def test_patch_rollback_conflict_is_outcome_unknown_and_preserves_foreign_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(tmp_path), capture_output=True,
            text=True, check=True, **hidden_run_kwargs()
        )

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    owned = tmp_path / "owned.txt"
    foreign = tmp_path / "foreign.txt"
    owned.write_text("before\n", encoding="utf-8")
    foreign.write_text("committed\n", encoding="utf-8")
    git("add", "owned.txt", "foreign.txt")
    git("commit", "-m", "initial")
    foreign.write_text("pre-existing dirty edit\n", encoding="utf-8")
    untracked = tmp_path / "keep.tmp"
    untracked.write_text("pre-existing untracked file\n", encoding="utf-8")

    broker = CommandBroker({"server": {"state_dir": str(tmp_path.parent / f"{tmp_path.name}-state")}})
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    invalidated: list[str] = []
    for cache_name in ("success", "failure", "suppression"):
        cache = getattr(broker, f"{cache_name}_cache")
        original_delete = cache.delete

        def record_delete(key: str, *, _name=cache_name, _delete=original_delete):
            invalidated.append(_name)
            return _delete(key)

        monkeypatch.setattr(cache, "delete", record_delete)

    def fail_after_target_edit(*_args: object, **_kwargs: object) -> dict[str, object]:
        owned.write_text("concurrent validation edit\n", encoding="utf-8")
        return {"success": False, "exit_code": 1, "stdout": "", "stderr": "failed"}

    monkeypatch.setattr(broker, "run", fail_after_target_edit)
    patch = "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-before\n+after\n"
    result = broker.patch_and_verify(
        patch, str(tmp_path), command="verify", task_id="task-owned", auto_rollback=True
    )

    assert result["success"] is False
    assert result["rolled_back"] is False
    assert result.get("outcome_unknown") is True
    assert result.get("fail_closed") is True
    assert result.get("incident_required") is True
    assert result.get("retryable") is False
    assert "rollback_error" in result
    assert result["rollback_paths"] == ["owned.txt"]
    assert set(invalidated) == {"success", "failure", "suppression"}
    assert owned.read_text(encoding="utf-8") == "concurrent validation edit\n"
    assert foreign.read_text(encoding="utf-8") == "pre-existing dirty edit\n"
    assert untracked.read_text(encoding="utf-8") == "pre-existing untracked file\n"


def test_patch_rollback_conflict_uses_snapshot_and_never_overwrites_foreign_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(tmp_path), capture_output=True,
            text=True, check=True, **hidden_run_kwargs()
        )

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    owned = tmp_path / "owned.txt"
    owned.write_text("start\nbefore\nend\n", encoding="utf-8")
    git("add", "owned.txt")
    git("commit", "-m", "initial")

    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    apply_check_calls: list[str] = []
    reverse_check_failed = False
    original_run = commands_module.subprocess.run

    def concurrent_apply_checks(*args: object, **kwargs: object):
        nonlocal reverse_check_failed
        argv = args[0] if args else kwargs.get("args")
        if argv == ["git", "apply", "--reverse", "--check", "--whitespace=nowarn"]:
            reverse_check_failed = True
            apply_check_calls.append("reverse")
            return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"concurrent postimage")
        if reverse_check_failed and argv == ["git", "apply", "--check", "--whitespace=nowarn"]:
            apply_check_calls.append("forward")
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        return original_run(*args, **kwargs)

    invalidated: list[str] = []
    for cache_name in ("success", "failure", "suppression"):
        cache = getattr(broker, f"{cache_name}_cache")
        original_delete = cache.delete

        def record_delete(key: str, *, _name=cache_name, _delete=original_delete):
            invalidated.append(_name)
            return _delete(key)

        monkeypatch.setattr(cache, "delete", record_delete)

    def fail_after_foreign_edit(_command: str, cwd: str, *_args: object, **_kwargs: object) -> dict[str, object]:
        transaction_root = Path(cwd)
        (transaction_root / owned.name).write_text("foreign-start\nafter\nend\n", encoding="utf-8")
        return {"success": False, "exit_code": 1, "stdout": "", "stderr": "failed"}

    monkeypatch.setattr(broker, "run", fail_after_foreign_edit)
    monkeypatch.setattr(commands_module.subprocess, "run", concurrent_apply_checks)
    result = broker.patch_and_verify(
        "--- a/owned.txt\n+++ b/owned.txt\n@@ -1,3 +1,3 @@\n start\n-before\n+after\n end\n",
        str(tmp_path), command="verify", task_id="task-owned", auto_rollback=True,
    )

    assert result["rolled_back"] is False
    assert result.get("outcome_unknown") is True
    assert result.get("fail_closed") is True
    assert result.get("incident_required") is True
    # Restore now uses the exact preimage plus postimage checks; git's reverse
    # apply probe is not an authority for overwriting a concurrent edit.
    assert apply_check_calls == []
    assert set(invalidated) == {"success", "failure", "suppression"}
    assert owned.read_text(encoding="utf-8") == "start\nbefore\nend\n"


def test_patch_apply_timeout_returns_unknown_and_invalidates_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(tmp_path), capture_output=True,
            text=True, check=True, **hidden_run_kwargs()
        )

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    owned = tmp_path / "owned.txt"
    owned.write_text("before\n", encoding="utf-8")
    git("add", "owned.txt")
    git("commit", "-m", "initial")

    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    invalidated: list[str] = []
    for cache_name in ("success", "failure", "suppression"):
        cache = getattr(broker, f"{cache_name}_cache")
        original_delete = cache.delete

        def record_delete(key: str, *, _name=cache_name, _delete=original_delete):
            invalidated.append(_name)
            return _delete(key)

        monkeypatch.setattr(cache, "delete", record_delete)

    original_run = commands_module.subprocess.run

    def timeout_during_patch_apply(*args: object, **kwargs: object):
        argv = args[0] if args else kwargs.get("args")
        if argv == ["git", "apply", "--whitespace=nowarn"]:
            Path(str(kwargs["cwd"]), "owned.txt").write_text("partial apply state\n", encoding="utf-8")
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        return original_run(*args, **kwargs)

    monkeypatch.setattr(commands_module.subprocess, "run", timeout_during_patch_apply)
    result = broker.patch_and_verify(
        "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-before\n+after\n",
        str(tmp_path), command="verify", task_id="task-owned", auto_rollback=True,
    )

    assert result.get("outcome_unknown") is True
    assert result.get("fail_closed") is True
    assert result.get("incident_required") is True
    assert result.get("rollback_paths") == ["owned.txt"]
    assert set(invalidated) == {"success", "failure", "suppression"}
    assert owned.read_text(encoding="utf-8") == "before\n"


def test_patch_and_verify_preserves_run_uncertainty_after_compensation_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(tmp_path), capture_output=True,
            text=True, check=True, **hidden_run_kwargs()
        )

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    owned = tmp_path / "owned.txt"
    owned.write_text("before\n", encoding="utf-8")
    git("add", "owned.txt")
    git("commit", "-m", "initial")

    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    class IncidentStore:
        outcome = None

        def capture(self, outcome):
            self.outcome = outcome
            return None

    incidents = IncidentStore()
    broker.set_incident_store(incidents)
    invalidated: list[str] = []
    for cache_name in ("success", "failure", "suppression"):
        cache = getattr(broker, f"{cache_name}_cache")
        original_delete = cache.delete

        def record_delete(key: str, *, _name=cache_name, _delete=original_delete):
            invalidated.append(_name)
            return _delete(key)

        monkeypatch.setattr(cache, "delete", record_delete)
    monkeypatch.setattr(
        broker,
        "run",
        lambda *_args, **_kwargs: {
            "success": False,
            "outcome_unknown": True,
            "rollback_error": "validation cleanup unconfirmed",
            "exit_code": 1,
            "stdout": "",
            "stderr": "cleanup unconfirmed",
        },
    )

    result = broker.patch_and_verify(
        "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-before\n+after\n",
        str(tmp_path), command="verify", task_id="task-owned", auto_rollback=True,
    )

    assert result["success"] is False
    assert result["rolled_back"] is True
    assert result["outcome_unknown"] is True
    assert result["fail_closed"] is True
    assert result["retryable"] is False
    assert result["rollback_paths"] == ["owned.txt"]
    assert owned.read_text(encoding="utf-8") == "before\n"
    assert incidents.outcome is not None
    assert incidents.outcome.affected_paths == ("owned.txt",)
    assert set(invalidated) == {"success", "failure", "suppression"}


@pytest.mark.skipif(os.name != "nt", reason="Windows rollback root guard regression")
def test_patch_validation_holds_and_releases_rollback_root_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, capture_output=True, check=True, **hidden_run_kwargs())
    owned = root / "owned.txt"
    owned.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "owned.txt"], cwd=root, capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "initial"], cwd=root, capture_output=True, check=True, **hidden_run_kwargs())

    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "allow_validation": True, "allow_unknown": True},
        }
    )
    broker.set_task_store(_FakeTaskStore(str(root)))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    rename_blocked: list[bool] = []
    moved_root = root.with_name("repo-renamed")

    def validation_try_root_rename(*_args: object, **_kwargs: object) -> dict[str, object]:
        try:
            root.rename(moved_root)
        except OSError:
            rename_blocked.append(True)
        else:
            rename_blocked.append(False)
            moved_root.rename(root)
        return {
            "success": True,
            "exit_code": 0,
            "timed_out": False,
            "cancelled": False,
            "outcome_unknown": False,
            "aborted_interactive": False,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 1,
        }

    monkeypatch.setattr(broker, "_execute", validation_try_root_rename)
    patch = "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-before\n+after\n"
    result = broker.patch_and_verify(
        patch,
        str(root),
        command="python -c \"pass\"",
        task_id="task-owned",
        auto_rollback=True,
    )

    assert result["success"] is True
    assert rename_blocked == [True]
    try:
        root.rename(moved_root)
        moved_root.rename(root)
    finally:
        if moved_root.exists() and not root.exists():
            moved_root.rename(root)


def test_patch_and_verify_rejects_symlink_write_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "target.txt"
    outside_file.write_text("outside baseline\n", encoding="utf-8")
    linked = tmp_path / "linked"
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == linked or real_is_symlink(path),
    )

    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    patch = "--- a/linked/target.txt\n+++ b/linked/target.txt\n@@ -1 +1 @@\n-outside baseline\n+outside changed\n"

    result = broker.patch_and_verify(
        patch, str(tmp_path), command="verify", task_id="task-owned", auto_rollback=True
    )

    assert result["success"] is False
    assert result["applied"] is False
    assert "symlink" in result["error"]
    assert outside_file.read_text(encoding="utf-8") == "outside baseline\n"


def test_mutating_command_requires_registered_task_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path)}, "commands": {"allow_mutating": True}},
        artifacts=None,
        repo_state=None,
    )
    launched = False

    def fail_if_executed(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal launched
        launched = True
        raise AssertionError("mutation reached command execution without task worktree")

    monkeypatch.setattr(broker, "_execute", fail_if_executed)
    result = broker.run(
        'python -c "pass"',
        str(tmp_path),
        force=True,
        task_id="task-without-registration",
        rollback_on_failure=True,
        rollback_paths=["owned.txt"],
    )

    assert result["success"] is False
    assert result["mutation_worktree_required"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert launched is False


def test_mutating_run_requires_explicit_paths_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path)},
            "commands": {"allow_mutating": True},
        },
        artifacts=None,
        repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    launched = False

    def fail_if_executed(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal launched
        launched = True
        raise AssertionError("mutating command ran without an explicit write set")

    monkeypatch.setattr(broker, "_execute", fail_if_executed)
    result = broker.run(
        "git add owned.txt",
        str(tmp_path),
        force=True,
        task_id="task-owned",
    )

    assert result["success"] is False
    assert result["mutation_write_set_required"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert launched is False


def test_mutating_run_rejects_unsafe_write_set_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path)},
            "commands": {"allow_mutating": True},
        },
        artifacts=None,
        repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    launched = False

    def fail_if_executed(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal launched
        launched = True
        raise AssertionError("mutating command ran with an unsafe write set")

    monkeypatch.setattr(broker, "_execute", fail_if_executed)
    result = broker.run(
        "git add owned.txt",
        str(tmp_path),
        force=True,
        task_id="task-owned",
        paths=["../outside.txt"],
    )

    assert result["success"] is False
    assert result["rollback_scope_invalid"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert launched is False


def test_mutating_git_command_rejects_shared_worktree_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned"
    shared = tmp_path / "shared"
    owned.mkdir()
    shared.mkdir()
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path)}, "commands": {"allow_mutating": True}},
        artifacts=None,
        repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(owned)))
    launched = False

    def fail_if_executed(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal launched
        launched = True
        raise AssertionError("Git command reached shared worktree")

    monkeypatch.setattr(broker, "_execute", fail_if_executed)
    result = broker.run(
        f'git -C "{shared}" checkout -- owned.txt',
        str(owned),
        force=True,
        task_id="task-owned",
    )

    assert result["success"] is False
    assert "outside the registered task worktree" in result["error"]
    assert launched is False


def test_rollback_snapshot_does_not_change_file_access_time(tmp_path: Path) -> None:
    target = tmp_path / "preserve-atime.txt"
    target.write_text("baseline", encoding="utf-8")
    os.utime(target, ns=(1_000_000_000, 2_000_000_000))
    original_atime = target.stat().st_atime_ns
    snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
    assert error is None and snapshot is not None
    try:
        assert target.stat().st_atime_ns == original_atime
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point race regression")
def test_rollback_snapshot_rejects_symlink_swapped_before_handle_open(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "race.txt"
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    target.write_bytes(b"inside")
    outside.write_bytes(b"outside-secret")
    original_open = commands_module._open_rollback_snapshot_file
    swapped = False
    snapshot = None

    def swap_before_open(parent_handle: int, name: str):
        nonlocal swapped
        if name == target.name and not swapped:
            swapped = True
            target.unlink()
            try:
                os.symlink(outside, target)
            except OSError as exc:
                pytest.skip(f"file symlink creation unavailable: {exc}")
        return original_open(parent_handle, name)

    monkeypatch.setattr(commands_module, "_open_rollback_snapshot_file", swap_before_open)
    try:
        snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
        assert swapped is True
        assert snapshot is None
        assert error is not None and "reparse" in error.lower()
        assert outside.read_bytes() == b"outside-secret"
    finally:
        if snapshot is not None:
            commands_module._close_rollback_root(snapshot.root_guard)
        target.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)
        assert not outside.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction race regression")
def test_rollback_snapshot_rejects_junction_swapped_before_handle_open(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "race.txt"
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    outside_secret = outside / "secret.txt"
    outside_secret.write_bytes(b"outside-secret")
    target.write_bytes(b"inside")
    original_open = commands_module._open_rollback_snapshot_file
    swapped = False
    snapshot = None

    def swap_before_open(parent_handle: int, name: str):
        nonlocal swapped
        if name == target.name and not swapped:
            swapped = True
            target.unlink()
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(target), str(outside)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                pytest.skip(f"junction creation unavailable: {result.stdout}{result.stderr}")
        return original_open(parent_handle, name)

    monkeypatch.setattr(commands_module, "_open_rollback_snapshot_file", swap_before_open)
    try:
        snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
        assert swapped is True
        assert snapshot is None
        assert error is not None and "reparse" in error.lower()
        assert outside_secret.read_bytes() == b"outside-secret"
    finally:
        if snapshot is not None:
            commands_module._close_rollback_root(snapshot.root_guard)
        try:
            os.rmdir(target)
        except OSError:
            target.unlink(missing_ok=True)
        outside_secret.unlink(missing_ok=True)
        outside.rmdir()
        assert not target.exists()
        assert not outside.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows root-junction race regression")
def test_rollback_snapshot_rejects_parent_junction_during_root_open(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "project-parent"
    root = parent / "repo"
    parent.mkdir()
    root.mkdir()
    inside = root / "state.txt"
    inside.write_bytes(b"inside")
    outside_parent = tmp_path / "outside-parent"
    outside_root = outside_parent / "repo"
    outside_root.mkdir(parents=True)
    outside = outside_root / "state.txt"
    outside.write_bytes(b"outside-secret")
    moved_parent = tmp_path / "project-parent-original"
    original_acquire = commands_module._acquire_rollback_root
    snapshot = None

    def redirect_during_open(resolved_root: Path) -> int:
        parent.rename(moved_parent)
        junction_created = False
        try:
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(parent), str(outside_parent)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                pytest.skip(f"junction creation unavailable: {result.stdout}{result.stderr}")
            junction_created = True
            return original_acquire(resolved_root)
        finally:
            if junction_created:
                os.rmdir(parent)
            moved_parent.rename(parent)

    monkeypatch.setattr(commands_module, "_acquire_rollback_root", redirect_during_open)
    try:
        snapshot, error = commands_module._snapshot_rollback_scope(str(root), [inside.name])
        assert snapshot is None
        assert error is not None and "reparse" in error.lower()
        assert outside.read_bytes() == b"outside-secret"
        assert inside.read_bytes() == b"inside"
    finally:
        if snapshot is not None:
            commands_module._close_rollback_root(snapshot.root_guard)
        assert parent.is_dir()
        assert not moved_parent.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX root-parent symlink race regression")
def test_rollback_snapshot_rejects_parent_symlink_swapped_after_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "project-parent"
    root = parent / "repo"
    root.mkdir(parents=True)
    inside = root / "state.txt"
    inside.write_bytes(b"inside")
    outside_parent = tmp_path / "outside-parent"
    outside_root = outside_parent / "repo"
    outside_root.mkdir(parents=True)
    outside = outside_root / "state.txt"
    outside.write_bytes(b"outside-secret")
    moved_parent = tmp_path / "project-parent-original"
    original_acquire = commands_module._acquire_rollback_root
    snapshot = None

    def redirect_during_open(resolved_root: Path) -> int:
        parent.rename(moved_parent)
        try:
            try:
                parent.symlink_to(outside_parent, target_is_directory=True)
            except OSError as exc:
                moved_parent.rename(parent)
                pytest.skip(f"directory symlink creation unavailable: {exc}")
            return original_acquire(resolved_root)
        finally:
            if parent.is_symlink():
                parent.unlink()
            if moved_parent.exists():
                moved_parent.rename(parent)

    monkeypatch.setattr(commands_module, "_acquire_rollback_root", redirect_during_open)
    try:
        snapshot, error = commands_module._snapshot_rollback_scope(str(root), [inside.name])
        assert snapshot is None
        assert error is not None
        assert outside.read_bytes() == b"outside-secret"
        assert inside.read_bytes() == b"inside"
    finally:
        if snapshot is not None:
            commands_module._close_rollback_root(snapshot.root_guard)
        assert parent.is_dir()
        assert not moved_parent.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows root handle identity regression")
def test_rollback_snapshot_records_root_identity_from_pinned_handle(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "state.txt"
    target.write_bytes(b"content")
    original_acquire = commands_module._acquire_rollback_root
    original_stat = Path.stat

    def acquire_then_disable_root_path_stat(resolved_root: Path) -> int:
        handle = original_acquire(resolved_root)

        def reject_path_identity(path: Path, *args, **kwargs):
            if path == root:
                raise AssertionError("root identity must come from the pinned handle")
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", reject_path_identity)
        return handle

    monkeypatch.setattr(commands_module, "_acquire_rollback_root", acquire_then_disable_root_path_stat)
    snapshot = None
    try:
        snapshot, error = commands_module._snapshot_rollback_scope(str(root), [target.name])
        assert error is None
        assert snapshot is not None
        assert snapshot.root_identity == commands_module._rollback_root_identity(snapshot.root_guard)
        assert snapshot.files[target.name].content == b"content"
    finally:
        if snapshot is not None:
            commands_module._close_rollback_root(snapshot.root_guard)


@pytest.mark.skipif(os.name != "nt", reason="Windows handle cleanup regression")
def test_rollback_snapshot_closes_file_handle_when_fstat_fails(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "fstat-failure.txt"
    target.write_bytes(b"content")
    real_open = commands_module._open_rollback_snapshot_file
    real_fstat = os.fstat
    real_close = os.close
    opened: list[int] = []
    closed: list[int] = []

    def track_open(root_handle: int, name: str) -> int | None:
        fd = real_open(root_handle, name)
        if fd is not None:
            opened.append(fd)
        return fd

    def fail_open_fstat(fd: int):
        if fd in opened:
            raise OSError("injected fstat failure")
        return real_fstat(fd)

    def track_close(fd: int) -> None:
        if fd in opened:
            closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(commands_module, "_open_rollback_snapshot_file", track_open)
    monkeypatch.setattr(commands_module.os, "fstat", fail_open_fstat)
    monkeypatch.setattr(commands_module.os, "close", track_close)
    try:
        snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
        assert snapshot is None
        assert error is not None and "injected fstat failure" in error
        assert opened and set(opened) <= set(closed)
    finally:
        for fd in opened:
            if fd not in closed:
                real_close(fd)


def test_rollback_snapshot_accepts_regular_file_control(tmp_path: Path) -> None:
    target = tmp_path / "regular.txt"
    target.write_bytes(b"inside-control")

    snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])

    assert error is None
    assert snapshot is not None
    try:
        assert snapshot.files[target.name].content == b"inside-control"
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)


def test_rollback_snapshot_requests_noatime_on_supported_posix(monkeypatch) -> None:
    monkeypatch.setattr(commands_module.os, "name", "posix")
    monkeypatch.setattr(commands_module.os, "O_NOATIME", 0x40000, raising=False)

    flags = commands_module._rollback_snapshot_open_flags()

    assert flags & 0x40000


def test_command_rollback_rejects_path_escape(tmp_path: Path) -> None:
    (tmp_path / "test_mutation_failure.py").write_text(
        "from pathlib import Path\n\n"
        "def test_failure_would_write_marker():\n"
        "    Path('must_not_run.tmp').touch()\n"
        "    assert False\n",
        encoding="utf-8",
    )
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path)},
            "commands": {"enabled": True, "allow_validation": True, "allow_mutating": True},
        },
        artifacts=None, repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())

    result = broker.run(
        "python -B -m pytest -q test_mutation_failure.py",
        str(tmp_path),
        force=True,
        task_id="task-owned",
        rollback_on_failure=True,
        rollback_paths=["../outside.txt"],
    )

    assert result["success"] is False
    assert result.get("rollback_scope_invalid") is True
    assert result.get("rolled_back") is not True
    assert not (tmp_path / "must_not_run.tmp").exists()


def test_rollback_snapshot_and_restore_accept_nested_paths(tmp_path: Path) -> None:
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    target = subdir / "file.txt"
    target.write_bytes(b"before")
    created = subdir / "created.txt"
    snapshot, error = commands_module._snapshot_rollback_scope(
        str(tmp_path), ["subdir/file.txt", "subdir/created.txt"]
    )
    assert error is None and snapshot is not None
    try:
        target.write_bytes(b"after")
        created.write_bytes(b"created")
        commands_module._capture_rollback_postimages(snapshot)
        commands_module._restore_rollback_scope(str(tmp_path), snapshot)
        assert target.read_bytes() == b"before"
        assert not created.exists()
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)


def test_rollback_restore_fails_closed_without_captured_postimages(tmp_path: Path) -> None:
    target = tmp_path / "state.txt"
    target.write_bytes(b"before")
    snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
    assert error is None and snapshot is not None
    try:
        target.write_bytes(b"after")
        with pytest.raises(OSError, match="postimages were not captured"):
            commands_module._restore_rollback_scope(str(tmp_path), snapshot)
        assert target.read_bytes() == b"after"
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)


@pytest.mark.skipif(os.name == "nt", reason="POSIX root identity replacement regression")
def test_rollback_restore_rejects_replaced_root_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "state.txt"
    target.write_bytes(b"before")
    snapshot, error = commands_module._snapshot_rollback_scope(str(root), [target.name])
    assert error is None and snapshot is not None
    target.write_bytes(b"inside-mutated")
    commands_module._capture_rollback_postimages(snapshot)

    moved_root = tmp_path / "repo-original"
    try:
        root.rename(moved_root)
        root.mkdir()
        replacement = root / "state.txt"
        replacement.write_bytes(b"replacement-secret")

        with pytest.raises(OSError, match="rollback root changed since snapshot"):
            commands_module._restore_rollback_scope(str(root), snapshot)

        assert (moved_root / "state.txt").read_bytes() == b"inside-mutated"
        assert replacement.read_bytes() == b"replacement-secret"
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)
        if root.exists():
            replacement_target = root / "state.txt"
            replacement_target.unlink(missing_ok=True)
            root.rmdir()
        if moved_root.exists():
            moved_root.rename(root)


def test_rollback_restore_rejects_current_path_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state.txt"
    target.write_bytes(b"before")
    snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
    assert error is None and snapshot is not None
    target.write_bytes(b"after")

    replacement_handle = 1_000_000_000
    original_identity = commands_module._rollback_root_identity
    original_close = commands_module._close_rollback_root

    def acquire_replacement(_root: Path) -> int:
        return replacement_handle

    def identity_for_handle(handle: int) -> tuple[int, int]:
        if handle == replacement_handle:
            return (-1, -1)
        return original_identity(handle)

    def close_handle(handle: int) -> None:
        if handle != replacement_handle:
            original_close(handle)

    monkeypatch.setattr(commands_module, "_acquire_rollback_root", acquire_replacement)
    monkeypatch.setattr(commands_module, "_rollback_root_identity", identity_for_handle)
    monkeypatch.setattr(commands_module, "_close_rollback_root", close_handle)
    try:
        with pytest.raises(OSError, match="rollback root changed since snapshot"):
            commands_module._restore_rollback_scope(str(tmp_path), snapshot)
        assert target.read_bytes() == b"after"
    finally:
        original_close(snapshot.root_guard)


@pytest.mark.skipif(os.name == "nt", reason="POSIX pinned-root restore race regression")
def test_rollback_restore_stays_inside_pinned_root_if_path_moves_after_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "state.txt"
    target.write_bytes(b"before")
    snapshot, error = commands_module._snapshot_rollback_scope(str(root), [target.name])
    assert error is None and snapshot is not None
    target.write_bytes(b"inside-mutated")
    commands_module._capture_rollback_postimages(snapshot)

    moved_root = tmp_path / "repo-original"
    original_open_parent = commands_module._open_rollback_parent_handle
    replaced = False

    def move_root_after_identity_check(root_handle: int, parts: list[str], **kwargs):
        nonlocal replaced
        if not replaced and root_handle == snapshot.root_guard:
            root.rename(moved_root)
            root.mkdir()
            (root / "state.txt").write_bytes(b"replacement-secret")
            replaced = True
        return original_open_parent(root_handle, parts, **kwargs)

    monkeypatch.setattr(commands_module, "_open_rollback_parent_handle", move_root_after_identity_check)
    try:
        commands_module._restore_rollback_scope(str(root), snapshot)

        assert replaced is True
        assert (moved_root / "state.txt").read_bytes() == b"before"
        assert (root / "state.txt").read_bytes() == b"replacement-secret"
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)
        if root.exists():
            (root / "state.txt").unlink(missing_ok=True)
            root.rmdir()
        if moved_root.exists():
            moved_root.rename(root)


def test_command_rollback_rejects_nested_path_traversal(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))

    result = broker.run(
        'python -c "import sys; sys.exit(1)"',
        str(tmp_path),
        force=True,
        task_id="task-owned",
        rollback_on_failure=True,
        rollback_paths=["subdir/../file.txt"],
    )

    assert result.get("rollback_scope_invalid") is True


@pytest.mark.skipif(os.name != "nt", reason="Windows temporary-handle cleanup regression")
@pytest.mark.parametrize("delete_failures", [1, 2])
def test_rollback_temp_handle_closes_when_delete_by_handle_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delete_failures: int
) -> None:
    import msvcrt

    target = tmp_path / "state.txt"
    target.write_bytes(b"before")
    snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
    assert error is None and snapshot is not None
    target.write_bytes(b"after")
    commands_module._capture_rollback_postimages(snapshot)

    active_fds: set[int] = set()
    original_open_osfhandle = msvcrt.open_osfhandle
    original_close = os.close

    def track_open_osfhandle(handle: int, flags: int) -> int:
        fd = original_open_osfhandle(handle, flags)
        active_fds.add(fd)
        return fd

    def track_close(fd: int) -> None:
        active_fds.discard(fd)
        original_close(fd)

    def fail_rename(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected rename failure")

    delete_calls = 0
    original_delete = commands_module._delete_windows_handle

    def fail_delete(handle: int) -> None:
        nonlocal delete_calls
        delete_calls += 1
        if delete_calls <= delete_failures:
            raise OSError("injected delete failure")
        original_delete(handle)

    monkeypatch.setattr(msvcrt, "open_osfhandle", track_open_osfhandle)
    monkeypatch.setattr(commands_module.os, "close", track_close)
    monkeypatch.setattr(commands_module, "_rename_windows_handle", fail_rename)
    monkeypatch.setattr(commands_module, "_delete_windows_handle", fail_delete)
    try:
        with pytest.raises(OSError, match="injected rename failure") as raised:
            commands_module._restore_rollback_scope(str(tmp_path), snapshot)
        assert active_fds == set()
        assert delete_calls == 2
        if delete_failures == 1:
            assert list(tmp_path.glob(".local-ai-rollback-*")) == []
        else:
            notes = getattr(raised.value, "__notes__", ())
            assert any("rollback temporary cleanup failed" in note for note in notes)
    finally:
        for fd in active_fds:
            original_close(fd)
        commands_module._close_rollback_root(snapshot.root_guard)
        for temp_file in tmp_path.glob(".local-ai-rollback-*"):
            temp_file.unlink(missing_ok=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows restore-junction race regression")
def test_rollback_restore_stays_on_pinned_root_after_junction_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    parent = root / "subdir"
    parent.mkdir(parents=True)
    target = parent / "state.txt"
    target.write_bytes(b"inside-before")
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "state.txt"
    outside_file.write_bytes(b"outside-secret")
    moved_parent = root / "subdir-original"
    snapshot, error = commands_module._snapshot_rollback_scope(str(root), ["subdir/state.txt"])
    assert error is None and snapshot is not None
    target.write_bytes(b"inside-mutated")

    original_identity = commands_module._rollback_root_identity
    swapped = False
    junction_created = False

    def swap_after_root_check(handle: int) -> tuple[int, int]:
        nonlocal swapped, junction_created
        identity = original_identity(handle)
        if not swapped:
            swapped = True
            parent.rename(moved_parent)
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(parent), str(outside)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                moved_parent.rename(parent)
                pytest.skip(f"junction creation unavailable: {result.stdout}{result.stderr}")
            junction_created = True
        return identity

    monkeypatch.setattr(commands_module, "_rollback_root_identity", swap_after_root_check)
    try:
        with pytest.raises((OSError, ValueError)):
            commands_module._restore_rollback_scope(str(root), snapshot)
        assert swapped is True
        assert outside_file.read_bytes() == b"outside-secret"
        assert (moved_parent / "state.txt").read_bytes() == b"inside-mutated"
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)
        if junction_created:
            os.rmdir(parent)
        if moved_parent.exists():
            moved_parent.rename(parent)


def test_command_rollback_rejects_hardlinks(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("preserve", encoding="utf-8")
    try:
        (tmp_path / "owned.txt").hardlink_to(outside)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())

    result = broker.run(
        'python -c "import sys; sys.exit(1)"',
        str(tmp_path),
        force=True,
        task_id="task-owned",
        rollback_on_failure=True,
        rollback_paths=["owned.txt"],
    )

    assert result.get("rollback_scope_invalid") is True
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_command_rollback_rejects_auto_fix_combination(tmp_path: Path) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    result = broker.run(
        'python -c "raise SystemExit(1)"',
        str(tmp_path),
        force=True,
        auto_fix=True,
        rollback_on_failure=True,
        rollback_paths=["owned.py"],
    )

    assert result.get("rollback_unsupported_action") is True
    assert result.get("rollback_scope_invalid") is not True


def test_command_rollback_preserves_filesystem_security_metadata(tmp_path: Path) -> None:
    target = tmp_path / "metadata.txt"
    target.write_text("baseline", encoding="utf-8")
    if os.name == "nt":
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            before = _get_windows_dacl(fd)
        finally:
            os.close(fd)
        metadata_name = None
    else:
        metadata_name = "user.local_ai_hub_rollback_test"
        try:
            os.setxattr(target, metadata_name, b"preserve-acl-xattr")
        except (AttributeError, OSError) as exc:
            pytest.skip(f"extended attributes unavailable: {exc}")
        before = os.getxattr(target, metadata_name)

    snapshot, error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
    assert error is None and snapshot is not None
    try:
        target.write_text("changed", encoding="utf-8")
        commands_module._capture_rollback_postimages(snapshot)
        commands_module._restore_rollback_scope(str(tmp_path), snapshot)

        assert target.read_text(encoding="utf-8") == "baseline"
        if os.name == "nt":
            fd = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                assert _windows_dacl_bytes(_get_windows_dacl(fd)) == _windows_dacl_bytes(before)
            finally:
                os.close(fd)
        else:
            assert os.getxattr(target, metadata_name) == before
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)


def test_command_rollback_runs_when_execution_raises_timeout(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "timed-out.txt"
    target.write_text("before", encoding="utf-8")
    _commit_task_worktree(tmp_path, target.name)
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path)}, "commands": {"allow_mutating": True}},
        artifacts=None, repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    monkeypatch.setattr(broker, "_transaction_stop_container", lambda _transaction_id: True)

    def timeout_after_write(_argv, cwd: str, *_args, **_kwargs):
        (Path(cwd) / target.name).write_text("partial", encoding="utf-8")
        raise subprocess.TimeoutExpired("test-command", 1)

    monkeypatch.setattr(broker, "_execute", timeout_after_write)
    result = broker.run(
        "git add timed-out.txt",
        str(tmp_path),
        force=True,
        task_id="task-owned",
        paths=[target.name],
        rollback_on_failure=True,
        rollback_paths=["timed-out.txt"],
    )

    assert result.get("timed_out") is True, result
    assert result.get("rolled_back") is True, {
        "rollback_error": result.get("rollback_error"),
        "outcome_unknown": result.get("outcome_unknown"),
        "rollback_details": result.get("rollback_details"),
    }
    assert target.read_text(encoding="utf-8") == "before"


def test_timeout_rollback_failure_is_unknown_invalidates_cache_and_records_write_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "timed-out.txt"
    target.write_text("before", encoding="utf-8")
    _commit_task_worktree(tmp_path, target.name)
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}, "commands": {"allow_mutating": True}},
        artifacts=None, repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    monkeypatch.setattr(broker, "_transaction_stop_container", lambda _transaction_id: False)

    class IncidentStore:
        outcome = None

        def capture(self, outcome):
            self.outcome = outcome
            return None

    incidents = IncidentStore()
    broker.set_incident_store(incidents)
    deleted: list[tuple[str, str]] = []
    for cache_name in ("success", "failure", "suppression"):
        cache = getattr(broker, f"{cache_name}_cache")
        original_delete = cache.delete

        def record_delete(key: str, *, _name=cache_name, _delete=original_delete):
            deleted.append((_name, key))
            return _delete(key)

        monkeypatch.setattr(cache, "delete", record_delete)

    def timeout_after_write(_argv, cwd: str, *_args, **_kwargs):
        (Path(cwd) / target.name).write_text("partial", encoding="utf-8")
        raise subprocess.TimeoutExpired("test-command", 1)

    monkeypatch.setattr(broker, "_execute", timeout_after_write)
    result = broker.run(
        "git add timed-out.txt", str(tmp_path), force=True, task_id="task-owned",
        paths=[target.name], rollback_on_failure=True, rollback_paths=["timed-out.txt"],
    )

    assert result["outcome_unknown"] is True, result
    assert result["fail_closed"] is True
    assert result["retryable"] is False
    assert result["rollback_paths"] == ["timed-out.txt"]
    assert incidents.outcome is not None
    assert incidents.outcome.affected_paths == ("timed-out.txt",)
    assert {name for name, _key in deleted} == {"success", "failure", "suppression"}
    assert target.read_text(encoding="utf-8") == "before"


def test_run_does_not_restore_while_process_tree_cleanup_is_unconfirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "owned.txt"
    target.write_text("before", encoding="utf-8")
    _commit_task_worktree(tmp_path, target.name)
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}, "commands": {"allow_mutating": True}},
        artifacts=None, repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    monkeypatch.setattr(broker, "_transaction_stop_container", lambda _transaction_id: False)

    class IncidentStore:
        outcome = None

        def capture(self, outcome):
            self.outcome = outcome
            return None

    incidents = IncidentStore()
    broker.set_incident_store(incidents)
    invalidated: list[str] = []
    for cache_name in ("success", "failure", "suppression"):
        cache = getattr(broker, f"{cache_name}_cache")
        original_delete = cache.delete

        def record_delete(key: str, *, _name=cache_name, _delete=original_delete):
            invalidated.append(_name)
            return _delete(key)

        monkeypatch.setattr(cache, "delete", record_delete)
    executed: list[bool] = []

    def live_writer_unconfirmed(_argv, cwd: str, *_args, **_kwargs):
        executed.append(True)
        (Path(cwd) / target.name).write_text("partial", encoding="utf-8")
        return {
            "success": False,
            "exit_code": -9,
            "timed_out": True,
            "cleanup_unconfirmed": True,
            "outcome_unknown": True,
            "fail_closed": True,
            "retryable": False,
            "error": "process-tree cleanup could not be confirmed",
            "stdout": "",
            "stderr": "",
        }

    def restore_must_not_run(*_args, **_kwargs):
        raise AssertionError("rollback must not race an unconfirmed live writer")

    monkeypatch.setattr(broker, "_execute", live_writer_unconfirmed)
    monkeypatch.setattr(commands_module, "_restore_rollback_scope", restore_must_not_run)
    result = broker.run(
        "git add owned.txt", str(tmp_path), force=True, task_id="task-owned",
        paths=[target.name], rollback_on_failure=True, rollback_paths=["owned.txt"],
    )

    assert executed == [True], result
    assert result["outcome_unknown"] is True
    assert result["fail_closed"] is True
    assert result["rolled_back"] is False
    assert result["rollback_paths"] == ["owned.txt"]
    assert result["retryable"] is False
    assert set(invalidated) == {"success", "failure", "suppression"}
    assert incidents.outcome is not None
    assert incidents.outcome.affected_paths == ("owned.txt",)
    assert target.read_text(encoding="utf-8") == "before"


@pytest.mark.skipif(os.name == "nt", reason="Windows Job Object cleanup is verified in process lifecycle tests")
def test_execute_does_not_kill_or_reap_after_tree_cleanup_is_unconfirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    class Stream:
        def readline(self, _size: int) -> str:
            return ""

        def close(self) -> None:
            pass

    class LiveProcess:
        pid = 24680
        returncode = None

        def __init__(self) -> None:
            self.stdout = Stream()
            self.stderr = Stream()
            self.kill_calls = 0
            self.wait_calls = 0

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.kill_calls += 1

        def wait(self, *_args, **_kwargs):
            self.wait_calls += 1
            raise AssertionError("unconfirmed process must not be waited/reaped")

    process = LiveProcess()
    cleanup_calls: list[tuple[int, float]] = []
    monkeypatch.setattr(commands_module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        commands_module,
        "terminate_tree",
        lambda pid, *, grace_seconds: cleanup_calls.append((pid, grace_seconds)) or False,
    )
    clock = {"now": -2.0}

    def advance_monotonic() -> float:
        clock["now"] += 2.0
        return clock["now"]

    group_signals = []

    def missing_process_group(*args, **_kwargs) -> None:
        group_signals.append(args)
        raise ProcessLookupError

    monkeypatch.setattr(commands_module.os, "killpg", missing_process_group)
    monkeypatch.setattr(
        commands_module,
        "time",
        SimpleNamespace(perf_counter=lambda: 0.0, monotonic=advance_monotonic, sleep=lambda _s: None),
    )

    result = CommandBroker({"commands": {"enabled": True}})._execute(
        "python -c pass", str(tmp_path), timeout=1
    )

    assert cleanup_calls == [(process.pid, 2.0)]
    assert process.kill_calls == 0
    assert process.wait_calls == 0
    assert group_signals == []
    assert result["cleanup_unconfirmed"] is True
    assert result["outcome_unknown"] is True
    assert result["fail_closed"] is True
    assert result["retryable"] is False


def test_command_snapshot_on_success(tmp_path: Path) -> None:
    # Set up git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    tracked = tmp_path / "app.py"
    tracked.write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    # Command succeeds
    cmd = 'python -c "print(\'everything ok\')"'
    result = broker.run(
        cmd,
        str(tmp_path),
        force=True,
        snapshot=True,
    )

    assert result["success"] is True
    assert result.get("snapshot_taken") is True
    assert result.get("rolled_back") is None


def test_snapshot_git_operations_use_configured_timeout(tmp_path: Path, monkeypatch) -> None:
    class _RepoState:
        @staticmethod
        def fingerprint(_cwd: str) -> dict[str, str]:
            return {"fingerprint": "test"}

    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path)},
            "workspace_cache": {"git_status_timeout_seconds": 0.7},
        },
        repo_state=_RepoState(),
    )
    timeouts = []

    def fake_run(argv, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(commands_module.subprocess, "run", fake_run)
    monkeypatch.setattr(broker, "_execute", lambda *_args, **_kwargs: {"success": True, "exit_code": 0, "stdout": "", "stderr": ""})

    result = broker.run("python -c \"print('ok')\"", str(tmp_path), force=True, snapshot=True)

    assert result["success"] is True
    assert timeouts == [0.7, 0.7]


def test_successful_short_command_creates_auditable_verification_evidence(tmp_path: Path) -> None:
    (tmp_path / ".local-ai.toml").write_text(
        '[commands.tests]\nargv = ["python", "-m", "pytest", "-q"]\n',
        encoding="utf-8",
    )
    (tmp_path / "test_command_evidence.py").write_text(
        "def test_evidence_source():\n    assert True\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Hub test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "hub-test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "add", ".local-ai.toml", "test_command_evidence.py"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "commit", "--quiet", "-m", "initialize evidence repository"], cwd=tmp_path, check=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, text=True, capture_output=True
    ).stdout.strip()
    state = AgentStateStore(tmp_path / "agent-state.sqlite3", enabled=True)
    tasks = TaskStore(state)
    owner = "command-test-owner"
    task = tasks.create(
        GoalContract(goal="record command evidence", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-proof"),
        task_id="task-proof",
        actor=owner,
        repo_root=str(tmp_path),
        repository_revision=revision,
    )
    artifacts = ArtifactStore(tmp_path / "artifacts")
    verification = VerificationStore(state, task_store=tasks, artifact_store=artifacts)
    class _RepoState:
        def fingerprint(self, cwd):
            current = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=cwd, check=True, text=True, capture_output=True
            ).stdout.strip()
            return {"fingerprint": current, "root": str(cwd)}

    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "command-state")},
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
        },
        artifacts=artifacts,
        repo_state=_RepoState(),
    )
    broker.set_task_store(tasks)
    broker.set_verification_store(verification)
    verification.set_command_execution_record_lookup(broker.get_command_execution_record)
    result = broker.run_project_command(
        "tests",
        str(tmp_path),
        force=True,
        task_id="task-proof",
        criterion="tests",
    )

    assert result["success"] is True
    receipt_data = result.get("verification_receipt")
    assert isinstance(receipt_data, dict)
    artifact = artifacts.get(receipt_data["evidence_id"], max_chars=50_000)
    assert artifact["kind"] == "command_verification"
    proof = json.loads(artifact["text"])
    assert proof["exit_code"] == 0
    assert "command" not in proof
    assert proof["command_sha256"] == hashlib.sha256(b"python -m pytest -q").hexdigest()
    assert any(item["artifact_id"] == receipt_data["evidence_id"] for item in artifacts.list(limit=20))
    exported = verification.export_receipts("task-proof", format="json")
    assert exported["success"] is True
    assert exported["count"] == 1
    receipt = json.loads(exported["output"])[0]
    assert receipt["evidence_id"] == receipt_data["evidence_id"]
    assert receipt["command_id"] == result["execution_id"]


def test_private_transaction_source_conflict_marks_outcome_unknown_and_invalidates_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    owned = repo / "owned.txt"
    owned.write_text("before", encoding="utf-8")
    unrelated = repo / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "add", "owned.txt", "unrelated.txt"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}, "commands": {"allow_mutating": True}},
        artifacts=None,
    )
    broker.set_task_store(_FakeTaskStore(str(repo)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())

    class _IncidentStore:
        outcome = None

        def capture(self, outcome):
            self.outcome = outcome
            return None

        def find_regressions(self, *_args, **_kwargs):
            return []

        def find_negative_knowledge(self, **_kwargs):
            return []

    incidents = _IncidentStore()
    broker.set_incident_store(incidents)
    deleted: dict[str, list[str]] = {"success": [], "failure": [], "suppression": []}
    for name in deleted:
        cache = getattr(broker, f"{name}_cache")
        original_delete = cache.delete

        def record_delete(key, *, _name=name, _delete=original_delete):
            deleted[_name].append(key)
            return _delete(key)

        monkeypatch.setattr(cache, "delete", record_delete)
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    def execute_in_private_tree(argv, _cwd, *_args, **_kwargs):
        assert argv[:3] == ["docker", "run", "--rm"]
        owned.write_text("concurrent edit", encoding="utf-8")
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1}

    monkeypatch.setattr(broker, "_execute", execute_in_private_tree)
    command = "git add owned.txt"
    result = broker.run(
        command, str(repo), force=True, task_id="task-owned", rollback_on_failure=True,
        rollback_paths=["owned.txt"],
    )

    assert result["success"] is False
    assert result["rolled_back"] is False
    assert result["outcome_unknown"] is True
    assert result["fail_closed"] is True
    assert result["incident_required"] is True
    assert incidents.outcome is not None
    assert "unknown" in incidents.outcome.error.lower()
    assert deleted["suppression"]
    assert deleted["success"] and deleted["failure"]
    assert owned.read_text(encoding="utf-8") == "concurrent edit"
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_rollback_aborts_when_hardlink_appears_after_postimage_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "owned.txt"
    target.write_text("before\n", encoding="utf-8")
    alias = tmp_path / "foreign-alias.txt"
    original_postimage_at = commands_module._rollback_postimage_at
    postimage_checks = 0

    def create_alias_after_postimage_check(parent_handle: int, leaf: str):
        nonlocal postimage_checks
        postimage_checks += 1
        # Snapshot and postimage checks are first two calls. Inject alias before final restore validation.
        if postimage_checks == 3:
            os.link(target, alias)
        return original_postimage_at(parent_handle, leaf)

    monkeypatch.setattr(commands_module, "_rollback_postimage_at", create_alias_after_postimage_check)
    snapshot, scope_error = commands_module._snapshot_rollback_scope(str(tmp_path), [target.name])
    assert scope_error is None
    assert snapshot is not None
    try:
        target.write_text("transaction postimage\n", encoding="utf-8")
        commands_module._capture_rollback_postimages(snapshot)

        with pytest.raises(OSError, match="external aliases"):
            commands_module._restore_rollback_scope(str(tmp_path), snapshot)

        assert postimage_checks == 3
        assert target.read_text(encoding="utf-8") == "transaction postimage\n"
        assert alias.read_text(encoding="utf-8") == "transaction postimage\n"
        assert os.path.samefile(target, alias)
    finally:
        commands_module._close_rollback_root(snapshot.root_guard)


def test_posix_rollback_exchange_restores_concurrent_write_between_check_and_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "owned.txt"
    staged = tmp_path / ".local-ai-rollback-test"
    target.write_text("transaction postimage", encoding="utf-8")
    staged.write_text("rollback preimage", encoding="utf-8")
    original_postimage = target.read_bytes()

    def postimage_at(parent: Path, leaf: str):
        path = parent / leaf
        if not path.exists():
            return SimpleNamespace(safe=True, fingerprint=None)
        return SimpleNamespace(safe=True, fingerprint=path.read_bytes())

    exchanges = 0

    def exchange(parent: Path, left: str, right: str) -> None:
        nonlocal exchanges
        left_path, right_path = parent / left, parent / right
        scratch = parent / f".exchange-{exchanges}"
        if exchanges == 0:
            right_path.write_text("concurrent edit", encoding="utf-8")
        left_path.rename(scratch)
        right_path.rename(left_path)
        scratch.rename(right_path)
        exchanges += 1

    monkeypatch.setattr(commands_module, "_rollback_postimage_at", postimage_at)
    monkeypatch.setattr(commands_module, "_rename_exchange_at", exchange)

    expected = SimpleNamespace(safe=True, fingerprint=original_postimage)
    with pytest.raises(OSError, match="changed during atomic exchange"):
        commands_module._restore_existing_rollback_leaf(
            tmp_path, staged.name, target.name, expected
        )

    assert target.read_text(encoding="utf-8") == "concurrent edit"
    assert staged.read_text(encoding="utf-8") == "rollback preimage"
    assert exchanges == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX atomic directory-entry exchange")
def test_rollback_exchange_primitive_swaps_entries_atomically(tmp_path: Path) -> None:
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text("left", encoding="utf-8")
    right.write_text("right", encoding="utf-8")
    parent_handle = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        commands_module._rename_exchange_at(parent_handle, left.name, right.name)
        assert left.read_text(encoding="utf-8") == "right"
        assert right.read_text(encoding="utf-8") == "left"
    finally:
        os.close(parent_handle)


def test_timeout_rollback_oserror_marks_outcome_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    owned = repo / "owned.txt"
    owned.write_text("before", encoding="utf-8")
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}}, artifacts=None, repo_state=None)
    broker.set_task_store(_FakeTaskStore(str(repo)))
    incidents: list[object] = []

    class _IncidentStore:
        def capture(self, outcome):
            incidents.append(outcome)
            return None

    broker.set_incident_store(_IncidentStore())
    monkeypatch.setattr(
        broker, "_execute",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("command", 1)),
    )
    monkeypatch.setattr(
        commands_module, "_restore_rollback_scope",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("restore blocked")),
    )
    receipts: list[object] = []
    monkeypatch.setattr(broker, "_record_command_verification", lambda *args, **kwargs: receipts.append(args))

    result = broker.run(
        "python -c pass", str(repo), force=True, task_id="task-owned",
        rollback_on_failure=True, rollback_paths=["owned.txt"],
    )

    assert result.get("timed_out") is True
    assert result.get("outcome_unknown") is True
    assert result.get("fail_closed") is True
    assert result.get("incident_required") is True
    assert result.get("retryable") is False
    assert "restore blocked" in result.get("rollback_error", "")
    assert incidents
    assert receipts == []

@pytest.mark.parametrize("script", ["custom_report.py", "custom_audit.py", "custom_check.py"])
def test_untrusted_python_scripts_require_mutation_policy_parametrized(script: str) -> None:
    broker = CommandBroker(
        {"commands": {"allow_mutating": False}}, artifacts=None, repo_state=None
    )

    classification = broker.classify(f"python {script}")

    assert classification["class"] == "mutating"
    assert classification["allowed"] is False


def test_source_directory_sync_failure_retains_journal_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    owned = repo / "owned.txt"
    owned.write_text("before", encoding="utf-8")
    _commit_task_worktree(repo, "owned.txt")
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")},
         "commands": {"allow_mutating": True}},
        artifacts=None,
    )
    broker.set_task_store(_FakeTaskStore(str(repo)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())

    class _IncidentStore:
        outcome = None

        def capture(self, outcome):
            self.outcome = outcome
            return None

        def find_regressions(self, *_args, **_kwargs):
            return []

        def find_negative_knowledge(self, **_kwargs):
            return []

    incidents = _IncidentStore()
    broker.set_incident_store(incidents)
    deleted: dict[str, list[str]] = {"success": [], "failure": [], "suppression": []}
    sync_order: list[tuple[str, bool, str]] = []
    for name in deleted:
        cache = getattr(broker, f"{name}_cache")
        original_delete = cache.delete
        monkeypatch.setattr(cache, "delete", lambda key, _name=name, _delete=original_delete:
                            (deleted[_name].append(key), _delete(key))[1])
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    persist_journal = CommandBroker._persist_transaction_journal

    def observe_journal_persist(self, path, payload):
        supported = persist_journal(path, payload)
        sync_order.append(("journal", path.exists(), owned.read_text(encoding="utf-8")))
        return supported

    def fail_source_sync(_self, _root, _paths):
        journals = list((tmp_path / "state").rglob("*.journal.json"))
        sync_order.append(("source", bool(journals), owned.read_text(encoding="utf-8")))
        raise OSError("simulated source directory sync failure")

    monkeypatch.setattr(CommandBroker, "_persist_transaction_journal", observe_journal_persist)
    monkeypatch.setattr(CommandBroker, "_fsync_rollback_directories", fail_source_sync)

    def commit_private_tree(_argv, cwd, *_args, **_kwargs):
        Path(cwd, "owned.txt").write_text("committed", encoding="utf-8")
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1}

    monkeypatch.setattr(broker, "_execute", commit_private_tree)
    command = "git add owned.txt"
    result = broker.run(
        command, str(repo), force=True, task_id="task-owned", paths=["owned.txt"],
        rollback_on_failure=True, rollback_paths=["owned.txt"],
    )

    journals = list((tmp_path / "state").rglob("*.journal.json"))
    assert result["success"] is False
    assert result["transaction_status"] == "recovery_required"
    assert result["outcome_unknown"] is True
    assert result["fail_closed"] is True
    assert result["incident_required"] is True
    assert owned.read_text(encoding="utf-8") == "committed"
    assert journals
    assert sync_order == [("journal", True, "before"), ("source", True, "committed")], result
    assert incidents.outcome is not None
    assert deleted["success"] and deleted["failure"] and deleted["suppression"]


def test_windows_directory_fsync_is_explicitly_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = Path.cwd()
    monkeypatch.setattr(commands_module.os, "name", "nt")

    assert CommandBroker._fsync_transaction_directory(state_dir) is False
    assert CommandBroker._fsync_rollback_directories(state_dir, []) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-fsync semantics")
def test_windows_mutation_succeeds_with_explicit_durability_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    owned = repo / "owned.txt"
    owned.write_text("before", encoding="utf-8")
    _commit_task_worktree(repo, "owned.txt")
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")},
         "commands": {"allow_mutating": True}},
        artifacts=None,
    )
    broker.set_task_store(_FakeTaskStore(str(repo)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    def commit_private_tree(_argv, cwd, *_args, **_kwargs):
        Path(cwd, "owned.txt").write_text("committed", encoding="utf-8")
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1}

    monkeypatch.setattr(broker, "_execute", commit_private_tree)
    result = broker.run(
        "git add owned.txt", str(repo), force=True, task_id="task-owned",
        paths=["owned.txt"], rollback_on_failure=True, rollback_paths=["owned.txt"],
    )

    assert result["success"] is True
    assert result["directory_fsync_supported"] is False
    assert "crash durability is not guaranteed" in result["durability_warning"]
    assert owned.read_text(encoding="utf-8") == "committed"


def test_post_import_verification_error_invalidates_caches_and_requires_incident(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    owned = repo / "owned.txt"
    owned.write_text("before", encoding="utf-8")
    unrelated = repo / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "add", "owned.txt", "unrelated.txt"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}, "commands": {"allow_mutating": True}},
        artifacts=None,
        repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(repo)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    class _IncidentStore:
        outcome = None

        def capture(self, outcome):
            self.outcome = outcome
            return None

    incidents = _IncidentStore()
    broker.set_incident_store(incidents)
    deleted: dict[str, list[str]] = {"success": [], "failure": [], "suppression": []}
    for name in deleted:
        cache = getattr(broker, f"{name}_cache")
        original_delete = cache.delete

        def record_delete(key, *, _name=name, _delete=original_delete):
            deleted[_name].append(key)
            return _delete(key)

        monkeypatch.setattr(cache, "delete", record_delete)

    def succeed_in_private_tree(_argv: object, cwd: str, *_args: object, **_kwargs: object):
        Path(cwd, "owned.txt").write_text("transaction output", encoding="utf-8")
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}

    def fail_post_import_verification(*_args: object) -> bool:
        raise OSError("simulated post-import verification failure")

    monkeypatch.setattr(broker, "_execute", succeed_in_private_tree)
    monkeypatch.setattr(broker, "_transaction_file_matches", fail_post_import_verification)
    result = broker.run(
        "git add owned.txt",
        str(repo),
        force=True,
        task_id="task-owned",
        paths=["owned.txt"],
    )

    assert result["success"] is False
    assert result["transaction_status"] == "recovery_required"
    assert result["outcome_unknown"] is True
    assert result["fail_closed"] is True
    assert result["incident_required"] is True
    assert result["cache_hit"] is False
    assert incidents.outcome is not None
    assert incidents.outcome.metadata["outcome_unknown"] is True
    assert deleted["success"] and deleted["failure"] and deleted["suppression"]
    assert owned.read_text(encoding="utf-8") == "transaction output"
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_transaction_journal_removal_follows_durable_source_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    owned = repo / "owned.txt"
    owned.write_text("before", encoding="utf-8")
    _commit_task_worktree(repo, "owned.txt")
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}, "commands": {"allow_mutating": True}},
        artifacts=None,
        repo_state=None,
    )
    broker.set_task_store(_FakeTaskStore(str(repo)))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    events: list[str] = []
    monkeypatch.setattr(
        CommandBroker, "_fsync_transaction_directory", lambda *args: events.append("journal-dir-fsync") or (os.name != "nt")
    )
    monkeypatch.setattr(
        CommandBroker, "_fsync_rollback_directories", lambda *args: events.append("source-dir-fsync") or (os.name != "nt")
    )
    original_restore = commands_module._restore_rollback_scope

    def track_source_import(root: str, snapshot: object) -> None:
        if Path(root) == repo:
            events.append("source-import")
        original_restore(root, snapshot)

    monkeypatch.setattr(commands_module, "_restore_rollback_scope", track_source_import)
    original_unlink = Path.unlink

    def track_journal_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.name.endswith(".journal.json"):
            events.append("journal-unlink")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", track_journal_unlink)

    def succeed_in_private_tree(_argv: object, cwd: str, *_args: object, **_kwargs: object):
        Path(cwd, "owned.txt").write_text("committed", encoding="utf-8")
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(broker, "_execute", succeed_in_private_tree)
    result = broker.run(
        "git add owned.txt",
        str(repo),
        force=True,
        task_id="task-owned",
        paths=["owned.txt"],
    )

    assert result["success"] is True
    assert result["transaction_status"] == "committed"
    if os.name == "nt":
        assert result["directory_fsync_supported"] is False
        assert "unsupported on Windows" in result["durability_warning"]
    else:
        assert events.index("journal-dir-fsync") < events.index("source-import")
        assert events.index("source-import") < events.index("source-dir-fsync")
        assert events.index("source-dir-fsync") < events.index("journal-unlink")
    assert owned.read_text(encoding="utf-8") == "committed"


def test_posix_rollback_exchange_preserves_concurrent_process_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "owned.txt"
    staged = tmp_path / ".local-ai-rollback-process-test"
    target.write_text("transaction postimage", encoding="utf-8")
    staged.write_text("rollback preimage", encoding="utf-8")
    expected = SimpleNamespace(safe=True, fingerprint=target.read_bytes())

    def postimage_at(parent: Path, leaf: str):
        path = parent / leaf
        if not path.exists():
            return SimpleNamespace(safe=True, fingerprint=None)
        return SimpleNamespace(safe=True, fingerprint=path.read_bytes())

    context = multiprocessing.get_context("spawn")
    complete = context.Event()
    writer = context.Process(
        target=_write_concurrent_rollback_edit,
        args=(str(target), complete),
    )
    exchanges = 0

    def exchange(parent: Path, left: str, right: str) -> None:
        nonlocal exchanges
        left_path, right_path = parent / left, parent / right
        scratch = parent / f".process-exchange-{exchanges}"
        if exchanges == 0:
            writer.start()
            assert complete.wait(15), "concurrent writer did not complete"
            writer.join(15)
            assert writer.exitcode == 0
        left_path.rename(scratch)
        right_path.rename(left_path)
        scratch.rename(right_path)
        exchanges += 1

    monkeypatch.setattr(commands_module, "_rollback_postimage_at", postimage_at)
    monkeypatch.setattr(commands_module, "_rename_exchange_at", exchange)

    try:
        with pytest.raises(OSError, match="changed during atomic exchange"):
            commands_module._restore_existing_rollback_leaf(
                tmp_path, staged.name, target.name, expected
            )
        assert target.read_text(encoding="utf-8") == "concurrent edit"
        assert staged.read_text(encoding="utf-8") == "rollback preimage"
        assert exchanges == 2
    finally:
        if writer.is_alive():
            writer.terminate()
            writer.join(5)
