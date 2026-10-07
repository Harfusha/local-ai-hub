from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import command_transactions
from local_ai_hub.command_transactions import (
    create_private_transaction_snapshot,
    create_private_transaction_snapshot_with_manifest,
    validate_transaction_output,
    verify_transaction_source_unchanged,
)
from local_ai_hub import commands as commands_module
from local_ai_hub import leases as leases_module
from local_ai_hub.commands import CommandBroker
from fencing_lease_support import FakeFencingLeaseStore, install_test_work_attempt_fence


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


class _RegisteredTaskStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def get(self, task_id: str):
        if task_id != "task-owned":
            return None
        return SimpleNamespace(checkpoint=SimpleNamespace(state_data={
            "worktree": {
                "success": True,
                "worktree_path": str(self.root),
                "repo_root": _git(self.root, "rev-parse", "--show-toplevel"),
                "branch": _git(self.root, "symbolic-ref", "--quiet", "--short", "HEAD"),
            }
        }))


def _make_source_repo(source: Path) -> None:
    source.mkdir()
    _git(source, "init", "--quiet")
    _git(source, "config", "user.name", "Snapshot Test")
    _git(source, "config", "user.email", "snapshot@example.invalid")
    (source / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (source / "tracked.txt").write_text("committed\n", encoding="utf-8")
    (source / "owned.txt").write_text("original\n", encoding="utf-8")
    _git(source, "add", ".gitignore", "tracked.txt", "owned.txt")
    _git(source, "commit", "--quiet", "-m", "seed")


def test_private_snapshot_preserves_dirty_ignored_and_untracked_inputs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    (source / "tracked.txt").write_text("staged tracked\n", encoding="utf-8")
    _git(source, "add", "tracked.txt")
    (source / "tracked.txt").write_text("dirty tracked\n", encoding="utf-8")
    (source / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    (source / "ignored.txt").write_text("ignored\n", encoding="utf-8")

    snapshot = create_private_transaction_snapshot(source, tmp_path / "transaction")

    assert (snapshot / "tracked.txt").read_text(encoding="utf-8") == "dirty tracked\n"
    assert _git(snapshot, "diff", "--cached", "--", "tracked.txt") == _git(
        source, "diff", "--cached", "--", "tracked.txt"
    )
    assert _git(snapshot, "diff", "--", "tracked.txt") == _git(
        source, "diff", "--", "tracked.txt"
    )
    assert (snapshot / "untracked.txt").read_text(encoding="utf-8") == "untracked\n"
    assert (snapshot / "ignored.txt").read_text(encoding="utf-8") == "ignored\n"
    assert Path(_git(snapshot, "rev-parse", "--show-toplevel")).resolve() == snapshot.resolve()
    source_common = Path(_git(source, "rev-parse", "--git-common-dir"))
    snapshot_common = Path(_git(snapshot, "rev-parse", "--git-common-dir"))
    if not source_common.is_absolute():
        source_common = source / source_common
    if not snapshot_common.is_absolute():
        snapshot_common = snapshot / snapshot_common
    assert snapshot_common.resolve() != source_common.resolve()
    assert _git(snapshot, "rev-parse", "HEAD") == _git(source, "rev-parse", "HEAD")
    _git(snapshot, "update-ref", "refs/heads/transaction-only", "HEAD")
    assert "refs/heads/transaction-only" not in _git(source, "show-ref")


def test_private_snapshot_does_not_retain_source_remote(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)

    snapshot = create_private_transaction_snapshot(source, tmp_path / "transaction")

    assert _git(snapshot, "remote") == ""


def test_private_snapshot_rejects_source_index_change_during_copy(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    (source / "tracked.txt").write_text("staged before race\n", encoding="utf-8")
    _git(source, "add", "tracked.txt")
    real_run = subprocess.run
    injected = False

    def race_index(argv, *args, **kwargs):
        nonlocal injected
        result = real_run(argv, *args, **kwargs)
        if not injected and "ls-files" in argv and "--stage" in argv:
            injected = True
            (source / "tracked.txt").write_text("staged during race\n", encoding="utf-8")
            real_run(["git", "add", "tracked.txt"], cwd=source, check=True)
        return result

    monkeypatch.setattr(command_transactions.subprocess, "run", race_index)

    with pytest.raises(OSError, match="source Git index changed"):
        create_private_transaction_snapshot(source, tmp_path / "transaction")
    assert injected is True
    assert not (tmp_path / "transaction").exists()


def test_transaction_output_returns_only_declared_postimages_and_allows_new_parent(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    transaction, baseline = create_private_transaction_snapshot_with_manifest(
        source, tmp_path / "transaction"
    )
    output = transaction / "nested" / "owned.txt"
    output.parent.mkdir()
    output.write_text("new output\n", encoding="utf-8")

    changes = validate_transaction_output(baseline, transaction, ["nested/owned.txt"])

    assert set(changes) == {"nested/owned.txt"}
    assert changes["nested/owned.txt"] is not None
    assert changes["nested/owned.txt"].digest


def test_transaction_output_rejects_undeclared_path(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    transaction, baseline = create_private_transaction_snapshot_with_manifest(
        source, tmp_path / "transaction"
    )
    (transaction / "extra.txt").write_text("private output\n", encoding="utf-8")

    with pytest.raises(ValueError, match="undeclared transaction output: extra.txt"):
        validate_transaction_output(baseline, transaction, ["owned.txt"])


def test_transaction_output_records_declared_removal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    transaction, baseline = create_private_transaction_snapshot_with_manifest(
        source, tmp_path / "transaction"
    )
    (transaction / "owned.txt").unlink()

    changes = validate_transaction_output(baseline, transaction, ["owned.txt"])

    assert changes == {"owned.txt": None}


def test_transaction_source_change_after_snapshot_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    _transaction, baseline = create_private_transaction_snapshot_with_manifest(
        source, tmp_path / "transaction"
    )
    (source / "owned.txt").write_text("concurrent writer\n", encoding="utf-8")

    with pytest.raises(OSError, match="transaction source path changed while command was running: owned.txt"):
        verify_transaction_source_unchanged(source, baseline, ["owned.txt"])


def test_transaction_source_unrelated_change_does_not_conflict_with_write_set(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    _transaction, baseline = create_private_transaction_snapshot_with_manifest(
        source, tmp_path / "transaction"
    )
    (source / "unrelated.txt").write_text("concurrent unrelated edit\n", encoding="utf-8")

    verify_transaction_source_unchanged(source, baseline, ["owned.txt"])


def test_mutating_run_requires_enforced_docker_boundary_before_spawn(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")},
         "commands": {"allowed": True, "allow_mutating": True}},
        artifacts=None,
    )
    broker.set_task_store(_RegisteredTaskStore(source))
    spawned: list[bool] = []

    def execute(*_args, **_kwargs):
        spawned.append(True)
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1}

    monkeypatch.setattr(broker, "_execute", execute)
    monkeypatch.setattr(
        broker, "_transaction_docker_ready",
        lambda: (False, "Docker engine unavailable for private command transaction: test"),
    )

    result = broker.run(
        "git add owned.txt", str(source), force=True, task_id="task-owned", paths=["owned.txt"]
    )

    assert result["success"] is False
    assert result["mutation_sandbox_required"] is True
    assert result["failure_kind"] == "sandbox_unavailable"
    assert spawned == []


def test_mutating_run_requires_authoritative_fencing_before_spawn(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")},
         "commands": {"allowed": True, "allow_mutating": True}},
        artifacts=None,
    )
    broker.set_task_store(_RegisteredTaskStore(source))
    # The module-wide fixture normally installs a positive test fence; this
    # test intentionally exercises the no-authoritative-fence failure path.
    broker.set_fencing_lease_store(None)
    monkeypatch.setattr(broker, "run", CommandBroker.run.__get__(broker, CommandBroker))
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    spawned: list[bool] = []
    monkeypatch.setattr(
        broker, "_execute",
        lambda *_args, **_kwargs: spawned.append(True) or {"success": True},
    )

    result = broker.run(
        "git add owned.txt", str(source), force=True, task_id="task-owned",
        paths=["owned.txt"],
    )

    assert result["success"] is False
    assert result["failure_kind"] == "mutation_fence_unavailable"
    assert result["mutation_fence_required"] is True
    assert result["outcome_unknown"] is False
    assert spawned == []


def test_private_transaction_requires_work_attempt_even_when_store_is_available(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}, "commands": {"allowed": True}},
        artifacts=None,
    )
    broker.set_fencing_lease_store(FakeFencingLeaseStore())
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    spawned: list[bool] = []
    monkeypatch.setattr(
        broker, "_execute",
        lambda *_args, **_kwargs: spawned.append(True) or {"success": True},
    )

    result = broker._run_private_transaction(
        "git add owned.txt", source, "tenant-1", task_id="task-owned",
        paths=["owned.txt"], timeout=1, docker_image="python:3.11-slim",
    )

    assert result["success"] is False
    assert result["failure_kind"] == "work_attempt_fence_required"
    assert result["outcome_unknown"] is False
    assert spawned == []


def _run_mutation(tmp_path: Path, monkeypatch, *, write_undeclared: bool):
    source = tmp_path / "source"
    _make_source_repo(source)
    (source / "tracked.txt").write_text("dirty tracked\n", encoding="utf-8")
    (source / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    (source / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")},
         "commands": {"allowed": True, "allow_mutating": True}},
        artifacts=None,
    )
    broker.set_task_store(_RegisteredTaskStore(source))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    executed_roots: list[Path] = []

    def execute(command, cwd, *_args, **_kwargs):
        transaction = Path(cwd)
        executed_roots.append(transaction.resolve())
        assert command[:3] == ["docker", "run", "--rm"]
        assert "--network=none" in command
        assert "--read-only" in command
        assert all(
            str(source.resolve()) not in token
            for token in command
            if token.startswith("--volume") or ":/workspace:" in token
        )
        assert (transaction / "tracked.txt").read_text(encoding="utf-8") == "dirty tracked\n"
        assert (transaction / "untracked.txt").read_text(encoding="utf-8") == "untracked\n"
        assert (transaction / "ignored.txt").read_text(encoding="utf-8") == "ignored\n"
        (transaction / "owned.txt").write_text("transaction output\n", encoding="utf-8")
        if write_undeclared:
            (transaction / "undeclared.txt").write_text("private output\n", encoding="utf-8")
        _git(transaction, "update-ref", "refs/heads/transaction-only", "HEAD")
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1}

    monkeypatch.setattr(broker, "_execute", execute)
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    result = broker.run(
        "git add owned.txt", str(source), force=True, task_id="task-owned", paths=["owned.txt"]
    )
    return result, source, executed_roots


def test_mutating_run_executes_private_snapshot_and_imports_declared_output(
    tmp_path: Path, monkeypatch
) -> None:
    result, source, executed_roots = _run_mutation(tmp_path, monkeypatch, write_undeclared=False)

    assert result["success"] is True, result
    assert result["transaction_id"]
    assert result["transaction_status"] == "committed"
    assert len(executed_roots) == 1
    assert executed_roots[0] != source.resolve()
    assert (source / "owned.txt").read_text(encoding="utf-8") == "transaction output\n"
    assert not (source / "undeclared.txt").exists()
    assert "refs/heads/transaction-only" not in _git(source, "show-ref")


def test_mutating_run_rejects_undeclared_transaction_output(
    tmp_path: Path, monkeypatch
) -> None:
    result, source, executed_roots = _run_mutation(tmp_path, monkeypatch, write_undeclared=True)

    assert result["success"] is False
    assert result["transaction_id"]
    assert result["transaction_status"] == "discarded", result
    assert result["failure_kind"] == "undeclared_output"
    assert len(executed_roots) == 1
    assert executed_roots[0] != source.resolve()
    assert (source / "owned.txt").read_text(encoding="utf-8") == "original\n"
    assert not (source / "undeclared.txt").exists()


def test_patch_and_verify_runs_and_imports_inside_private_transaction(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")},
         "commands": {"enabled": True, "allowed": True, "allow_mutating": True, "allow_validation": True}},
        artifacts=None,
    )
    broker.set_task_store(_RegisteredTaskStore(source))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    executed_roots: list[Path] = []

    def execute(command, cwd, *_args, **_kwargs):
        assert command[:3] == ["docker", "run", "--rm"]
        executed_roots.append(Path(cwd).resolve())
        return {"success": True, "exit_code": 0, "stdout": "ok", "stderr": "", "duration_ms": 1}

    monkeypatch.setattr(broker, "_execute", execute)
    patch = """--- a/owned.txt
+++ b/owned.txt
@@ -1 +1 @@
-original
+verified\n
"""

    result = broker.patch_and_verify(
        patch, source, "tenant-1", task_id="task-owned", command="python -m pytest -q",
        record_verification=False,
    )

    assert result["success"] is True, result
    assert result["transaction_status"] == "committed"
    assert (source / "owned.txt").read_text(encoding="utf-8") == "verified\n"
    assert len(executed_roots) == 1
    assert executed_roots[0] != source.resolve()


def _write_recovery_journal(broker: CommandBroker, source: Path, transaction_root: Path) -> tuple[Path, object]:
    from local_ai_hub.work_fencing import FencingLeaseStore

    paths = ["owned.txt", "tracked.txt"]
    fencing_store = FencingLeaseStore(
        broker._transaction_state_dir / "work-fencing.sqlite3"
    )
    broker.set_fencing_lease_store(fencing_store)
    namespace_kwargs = broker._transaction_namespace_kwargs(source, fencing_store)
    original_attempt = fencing_store.claim_attempt(
        str(source), "task-owned", "crashed-writer", ttl_seconds=300,
        **namespace_kwargs,
    )
    original_writer = fencing_store.acquire(
        str(source), "crashed-writer", paths, ttl_seconds=300,
        attempt=original_attempt, **namespace_kwargs,
    )
    before, error = commands_module._snapshot_rollback_scope(str(source), paths)
    assert error is None and before is not None
    after, error = commands_module._snapshot_rollback_scope(str(transaction_root), paths)
    assert error is None and after is not None
    try:
        payload = {
            "schema": 1,
            "transaction_id": "crashed-transaction",
            "task_id": "task-owned",
            "source_root": str(source.resolve()),
            "transaction_root": str(transaction_root.resolve()),
            "paths": paths,
            "fencing": {
                "lease_id": original_writer.lease_id,
                "fencing_token": original_writer.fencing_token,
            },
            "attempt_fence": broker._work_attempt_fence_payload(original_attempt),
            "files": {
                path: {
                    "before": broker._transaction_file_payload(before.files[path]),
                    "after": broker._transaction_file_payload(after.files[path]),
                }
                for path in paths
            },
        }
    finally:
        commands_module._close_rollback_root(before.root_guard)
        commands_module._close_rollback_root(after.root_guard)
    broker._transaction_state_dir.mkdir(parents=True, exist_ok=True)
    journal = broker._transaction_state_dir / "crashed-transaction.journal.json"
    broker._persist_transaction_journal(journal, payload)
    fencing_store.release(original_writer)
    fencing_store.release_attempt(original_attempt)
    recovery_attempt = fencing_store.claim_attempt(
        str(source), "task-owned", "test-recovery", ttl_seconds=300,
        **namespace_kwargs,
    )
    return journal, recovery_attempt


def test_fenced_transaction_recovery_requires_current_work_attempt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    transaction_parent = tmp_path / "state" / "command-transactions"
    transaction_parent.mkdir(parents=True)
    transaction_root, _baseline = create_private_transaction_snapshot_with_manifest(
        source, transaction_parent / "crashed-transaction"
    )
    (transaction_root / "owned.txt").write_text("recovered owned\n", encoding="utf-8")
    (transaction_root / "tracked.txt").write_text("recovered tracked\n", encoding="utf-8")
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}}, artifacts=None
    )
    journal_result = _write_recovery_journal(broker, source, transaction_root)
    journal = journal_result[0] if isinstance(journal_result, tuple) else journal_result
    journal_before = journal.read_bytes()

    try:
        recovery = broker._recover_transaction_journals(
            source, "task-owned", broker._transaction_state_dir, "ordinary-recovery",
            work_attempt_fence=None,
        )
    except ValueError:
        recovery = None

    if recovery is not None:
        assert recovery["transaction_status"] == "recovery_required"
        assert recovery["failure_kind"] == "work_attempt_fence_required"
        assert recovery["mutation_fence_required"] is True
        assert recovery["outcome_unknown"] is True
    assert journal.read_bytes() == journal_before
    assert (source / "owned.txt").read_text(encoding="utf-8") == "original\n"
    assert (source / "tracked.txt").read_text(encoding="utf-8") == "committed\n"


def test_transaction_recovery_completes_outputs_from_persisted_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    transaction_parent = tmp_path / "state" / "command-transactions"
    transaction_parent.mkdir(parents=True)
    transaction_root, _baseline = create_private_transaction_snapshot_with_manifest(
        source, transaction_parent / "crashed-transaction"
    )
    (transaction_root / "owned.txt").write_text("recovered owned\n", encoding="utf-8")
    (transaction_root / "tracked.txt").write_text("recovered tracked\n", encoding="utf-8")
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}}, artifacts=None
    )
    journal, recovery_attempt = _write_recovery_journal(broker, source, transaction_root)
    monkeypatch.setattr(
        CommandBroker,
        "_fsync_transaction_directory",
        staticmethod(lambda _directory: True),
    )
    monkeypatch.setattr(
        CommandBroker,
        "_fsync_rollback_directories",
        staticmethod(lambda _root, _paths: True),
    )

    recovery = broker._recover_transaction_journals(
        source, "task-owned", broker._transaction_state_dir, "test-recovery",
        recovery_attempt,
    )

    assert recovery is None
    assert not journal.exists()
    assert (source / "owned.txt").read_text(encoding="utf-8") == "recovered owned\n"
    assert (source / "tracked.txt").read_text(encoding="utf-8") == "recovered tracked\n"


@pytest.mark.parametrize("directory_sync", ["unsupported", "error"])
def test_transaction_recovery_reports_durability_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory_sync: str
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    transaction_parent = tmp_path / "state" / "command-transactions"
    transaction_parent.mkdir(parents=True)
    transaction_root, _baseline = create_private_transaction_snapshot_with_manifest(
        source, transaction_parent / "crashed-transaction"
    )
    (transaction_root / "owned.txt").write_text("recovered owned\n", encoding="utf-8")
    (transaction_root / "tracked.txt").write_text("recovered tracked\n", encoding="utf-8")
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}}, artifacts=None
    )
    journal, recovery_attempt = _write_recovery_journal(broker, source, transaction_root)

    if directory_sync == "unsupported":
        monkeypatch.setattr(
            CommandBroker,
            "_fsync_transaction_directory",
            staticmethod(lambda _directory: False),
        )
    else:
        def fail_source_sync(_root: Path, _paths: list[str]) -> bool:
            raise OSError("simulated source directory sync failure")

        monkeypatch.setattr(
            CommandBroker,
            "_fsync_rollback_directories",
            staticmethod(fail_source_sync),
        )

    recovery = broker._recover_transaction_journals(
        source, "task-owned", broker._transaction_state_dir, "test-recovery",
        recovery_attempt,
    )

    assert recovery is not None
    assert (source / "owned.txt").read_text(encoding="utf-8") == "recovered owned\n"
    assert (source / "tracked.txt").read_text(encoding="utf-8") == "recovered tracked\n"
    if directory_sync == "unsupported":
        assert recovery["success"] is True
        assert recovery["transaction_status"] == "recovered"
        assert recovery["rollback_paths"] == ["owned.txt", "tracked.txt"]
        assert recovery["command_not_run"] is True
        assert recovery["directory_fsync_supported"] is False
        assert "crash durability is not guaranteed" in recovery["durability_warning"]
        assert not journal.exists()
    else:
        assert recovery["success"] is False
        assert recovery["transaction_status"] == "recovery_required"
        assert recovery["outcome_unknown"] is True
        assert recovery["retryable"] is False
        assert recovery["terminal"] is True
        assert journal.exists()

def test_transaction_recovery_preserves_foreign_change_and_keeps_journal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    transaction_parent = tmp_path / "state" / "command-transactions"
    transaction_parent.mkdir(parents=True)
    transaction_root, _baseline = create_private_transaction_snapshot_with_manifest(
        source, transaction_parent / "crashed-transaction"
    )
    (transaction_root / "owned.txt").write_text("transaction result\n", encoding="utf-8")
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}}, artifacts=None
    )
    journal, recovery_attempt = _write_recovery_journal(broker, source, transaction_root)
    (source / "owned.txt").write_text("foreign edit\n", encoding="utf-8")

    recovery = broker._recover_transaction_journals(
        source, "task-owned", broker._transaction_state_dir, "test-recovery",
        recovery_attempt,
    )

    assert recovery is not None
    assert recovery["transaction_status"] == "recovery_required"
    assert recovery["outcome_unknown"] is True
    assert journal.exists()
    assert (source / "owned.txt").read_text(encoding="utf-8") == "foreign edit\n"


def test_expired_transaction_lease_cannot_overwrite_newer_declared_path(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    state = tmp_path / "state"
    owner_a = CommandBroker(
        {"server": {"state_dir": str(state)}, "commands": {"allowed": True}},
        artifacts=None,
    )
    owner_b = CommandBroker(
        {"server": {"state_dir": str(state)}, "commands": {"allowed": True}},
        artifacts=None,
    )
    clock = [1_000_000.0]
    monkeypatch.setattr(leases_module, "time", SimpleNamespace(time=lambda: clock[0]))
    fencing_store = FakeFencingLeaseStore(clock=lambda: clock[0])
    attempt_a = fencing_store.claim_attempt(
        str(source.resolve()), "task-owned", "owner-a", ttl_seconds=100.0
    )
    attempt_b: list[object] = []
    a_started = threading.Event()
    release_a = threading.Event()

    def execute_a(_argv, cwd, *_args, **_kwargs):
        a_started.set()
        assert release_a.wait(30)
        (Path(cwd) / "owned.txt").write_text("stale owner A\n", encoding="utf-8")
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}

    def execute_b(_argv, cwd, *_args, **_kwargs):
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}

    for broker in (owner_a, owner_b):
        broker.set_task_store(_RegisteredTaskStore(source))
        broker.set_fencing_lease_store(fencing_store)
        monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))
    monkeypatch.setattr(owner_a, "_execute", execute_a)
    monkeypatch.setattr(owner_b, "_execute", execute_b)

    result_a: list[dict] = []
    thread_a = threading.Thread(
        target=lambda: result_a.append(owner_a._run_private_transaction(
            "git add owned.txt", source, "tenant-a", task_id="task-owned",
            paths=["owned.txt"], timeout=1, docker_image="python:3.11-slim",
            work_attempt_fence=attempt_a,
        ))
    )
    thread_a.start()
    try:
        assert a_started.wait(30)
        clock[0] += 150
        attempt_b.append(fencing_store.claim_attempt(
            str(source.resolve()), "task-owned", "owner-b", ttl_seconds=300.0
        ))
        result_b = owner_b._run_private_transaction(
            "git add owned.txt", source, "tenant-b", task_id="task-owned",
            paths=["owned.txt"], timeout=1, docker_image="python:3.11-slim",
            work_attempt_fence=attempt_b[0],
        )
    finally:
        release_a.set()
        thread_a.join(30)

    assert not thread_a.is_alive()
    assert result_b["transaction_status"] == "committed", result_b
    # This scenario issues a newer attempt but commits no changed paths, so
    # the transaction-write lease generation need not advance.
    assert fencing_store.attempt_generations[str(source.resolve())] == 2
    assert result_a[0]["transaction_status"] == "discarded", result_a[0]
    assert result_a[0]["failure_kind"] == "mutation_fence_lost", result_a[0]
    assert result_a[0]["outcome_unknown"] is False
    assert (source / "owned.txt").read_text(encoding="utf-8") == "original\n"


def test_disjoint_private_transactions_commit_only_their_declared_paths(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    _make_source_repo(source)
    (source / "other.txt").write_text("other original\n", encoding="utf-8")
    state = tmp_path / "state"
    brokers = [
        CommandBroker(
            {"server": {"state_dir": str(state)}, "commands": {"allowed": True}},
            artifacts=None,
        )
        for _ in range(2)
    ]
    fencing_store = FakeFencingLeaseStore()
    barrier = threading.Barrier(2)
    shared_attempt = fencing_store.claim_attempt(
        str(source.resolve()), "task-owned", "task-caller", ttl_seconds=300.0
    )
    for broker in brokers:
        broker.set_task_store(_RegisteredTaskStore(source))
        broker.set_fencing_lease_store(fencing_store)
        monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    def execute_owned(_argv, cwd, *_args, **_kwargs):
        (Path(cwd) / "owned.txt").write_text("owned output\n", encoding="utf-8")
        barrier.wait(5)
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}

    def execute_other(_argv, cwd, *_args, **_kwargs):
        (Path(cwd) / "other.txt").write_text("other output\n", encoding="utf-8")
        barrier.wait(5)
        return {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(brokers[0], "_execute", execute_owned)
    monkeypatch.setattr(brokers[1], "_execute", execute_other)
    results: list[dict] = []

    def run(broker: CommandBroker, path: str) -> None:
        results.append(broker._run_private_transaction(
            f"git add {path}", source, f"tenant-{path}", task_id="task-owned",
            paths=[path], timeout=5, docker_image="python:3.11-slim",
            work_attempt_fence=shared_attempt,
        ))

    threads = [
        threading.Thread(target=run, args=(brokers[0], "owned.txt")),
        threading.Thread(target=run, args=(brokers[1], "other.txt")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert all(result["transaction_status"] == "committed" for result in results), results
    assert (source / "owned.txt").read_text(encoding="utf-8") == "owned output\n"
    assert (source / "other.txt").read_text(encoding="utf-8") == "other output\n"
