from __future__ import annotations

import multiprocessing
import queue
from contextlib import contextmanager
from pathlib import Path

import pytest

from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.work_orchestrator import WorkOrchestrator, _JournalEntry


def _claim_from_child(state_dir: str, root: str, output) -> None:
    store = ScopeLeaseStore(Path(state_dir))
    output.put(store.claim_batch("tenant-b", root, ["src/owned.py"]))


def _claim_while_guarded(state_dir: str, root: str, started, output) -> None:
    store = ScopeLeaseStore(Path(state_dir))
    started.set()
    output.put(store.claim_batch("tenant-b", root, ["src/owned.py"]))


def test_cross_process_claim_cannot_supersede_fence_during_guard(tmp_path: Path) -> None:
    root = str(tmp_path / "repo")
    Path(root).mkdir()
    state_dir = tmp_path / "state"
    store = ScopeLeaseStore(state_dir)
    first = store.claim_batch("tenant-a", root, ["src/owned.py"])
    assert first["success"] is True
    token = int(first["fencing_tokens"]["src/owned.py"])
    started = multiprocessing.Event()
    output = multiprocessing.Queue()
    child = multiprocessing.Process(
        target=_claim_while_guarded,
        args=(str(state_dir), root, started, output),
    )

    with store.fence_guard(
        "tenant-a", str(first["lease_id"]), root,
        ["src/owned.py"], {"src/owned.py": token},
    ):
        child.start()
        assert started.wait(timeout=3)
        with pytest.raises(queue.Empty):
            output.get(timeout=0.2)

    child.join(timeout=5)
    assert child.exitcode == 0
    competing = output.get(timeout=2)
    assert competing["success"] is False
    assert store.release("tenant-a", str(first["lease_id"]))["success"] is True
    next_claim = store.claim_batch("tenant-b", root, ["src/owned.py"])
    assert next_claim["success"] is True
    assert int(next_claim["fencing_tokens"]["src/owned.py"]) > token


def test_cross_process_reclaim_advances_fence_and_rejects_stale_writer(
    tmp_path: Path,
) -> None:
    root = str(tmp_path / "repo")
    Path(root).mkdir()
    state_dir = tmp_path / "state"
    first_store = ScopeLeaseStore(state_dir)
    first = first_store.claim_batch("tenant-a", root, ["src/owned.py"])
    assert first["success"] is True
    first_token = int(first["fencing_tokens"]["src/owned.py"])
    first_store.release("tenant-a", str(first["lease_id"]))

    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    child = context.Process(
        target=_claim_from_child,
        args=(str(state_dir), root, output),
    )
    child.start()
    child.join(timeout=15)
    assert child.exitcode == 0
    second = output.get(timeout=2)
    assert second["success"] is True
    second_token = int(second["fencing_tokens"]["src/owned.py"])
    assert second_token > first_token

    with pytest.raises(RuntimeError, match="stale fencing token"):
        with first_store.fence_guard(
            "tenant-a", str(first["lease_id"]), root,
            ["src/owned.py"], {"src/owned.py": first_token},
        ):
            pass
    with first_store.fence_guard(
        "tenant-b", str(second["lease_id"]), root,
        ["src/owned.py"], {"src/owned.py": second_token},
    ):
        pass


def test_patch_write_is_rejected_when_fence_is_stale(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "owned.txt"
    target.write_text("old\n", encoding="utf-8")
    store = ScopeLeaseStore(tmp_path / "state")

    @contextmanager
    def stale_guard(*args, **kwargs):
        raise RuntimeError("stale fencing token")
        yield

    store.fence_guard = stale_guard
    orchestrator = WorkOrchestrator(
        {"work_orchestrator": {"enabled": True}},
        tmp_path / "state",
        services=object(),
        commands=object(),
        leases=store,
        artifacts=object(),
    )
    orchestrator._ensure_workers = lambda: None
    patch = "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-old\n+new\n"
    try:
        with pytest.raises(RuntimeError, match="stale fencing token"):
            orchestrator._apply_patch(root, patch, "tenant-a", "work-write-stale", [])
        assert target.read_text(encoding="utf-8") == "old\n"
        assert orchestrator._load_journal("work-write-stale") == []
    finally:
        orchestrator.close()


def test_stale_fence_cannot_clear_journal_or_commit_work_order(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    state_dir = tmp_path / "state"
    store = ScopeLeaseStore(state_dir)
    first = store.claim_batch("tenant-a", str(root), ["owned.txt"])
    assert first["success"] is True
    claim = {
        "tenant": "tenant-a",
        "root": str(root),
        "paths": ["owned.txt"],
        "lease_id": first["lease_id"],
        "fencing_tokens": first["fencing_tokens"],
    }
    store.release("tenant-a", str(first["lease_id"]))
    successor = store.claim_batch("tenant-b", str(root), ["owned.txt"])
    assert successor["success"] is True

    orchestrator = WorkOrchestrator(
        {"work_orchestrator": {"enabled": True, "max_pending_work_orders": 2,
                               "max_steps": 4, "max_llm_steps": 2, "max_seconds": 30}},
        state_dir,
        services=object(),
        commands=object(),
        leases=store,
        artifacts=object(),
    )
    orchestrator._ensure_workers = lambda: None
    work_id = "work-stale-commit"
    payload = {
        "root": str(root), "task": "inspect repo", "work_id": work_id,
        "acceptance_criteria": ["report result"], "budget": {"max_seconds": 30},
    }
    try:
        orchestrator.submit("tenant-a", payload)
        orchestrator._set_state(work_id, "executing", {"changed_files": ["owned.txt"]})
        journal = [_JournalEntry("owned.txt", True, b"original\n")]
        orchestrator._persist_journal(work_id, journal)
        with pytest.raises(RuntimeError, match="stale fencing token"):
            orchestrator._commit_handoff(work_id, {"summary": "done"}, [claim])
        row = orchestrator._row(work_id, "tenant-a")
        assert row is not None and row["state"] == "executing"
        assert orchestrator._load_journal(work_id) == journal
    finally:
        orchestrator.close()


def test_multi_patch_work_order_commits_all_current_fences(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "owned.txt"
    target.write_text("before\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    store = ScopeLeaseStore(state_dir)
    config = {
        "work_orchestrator": {
            "enabled": True, "max_pending_work_orders": 2,
            "max_steps": 4, "max_llm_steps": 2, "max_seconds": 30,
        }
    }
    orchestrator = WorkOrchestrator(
        config, state_dir, services=object(), commands=object(),
        leases=store, artifacts=object(),
    )
    orchestrator._ensure_workers = lambda: None
    work_id = "work-multi-patch-commit"
    payload = {
        "root": str(root), "task": "inspect repo", "work_id": work_id,
        "acceptance_criteria": ["report result"], "budget": {"max_seconds": 30},
    }
    leases = []
    try:
        orchestrator.submit("tenant-a", payload)
        orchestrator._set_state(work_id, "verifying", {})
        journal = []
        first_patch = "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-before\n+middle\n"
        second_patch = "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-middle\n+after\n"
        for patch in (first_patch, second_patch):
            _paths, lease_id = orchestrator._apply_patch(
                root, patch, "tenant-a", work_id, journal,
            )
            leases.append(lease_id)
        assert target.read_text(encoding="utf-8") == "after\n"
        assert orchestrator._commit_handoff(work_id, {"summary": "verified"}) is True
        row = orchestrator._row(work_id, "tenant-a")
        assert row is not None and row["state"] == "complete"
        assert orchestrator._load_journal(work_id) == []
    finally:
        for lease_id in leases:
            store.release("tenant-a", lease_id)
        orchestrator.close()
