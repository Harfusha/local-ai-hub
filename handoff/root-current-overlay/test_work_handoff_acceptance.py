from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time as _real_time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

source_root = Path(os.environ.get("LOCAL_AI_HUB_SOURCE_ROOT", Path(__file__).resolve().parents[1])).resolve()
overlay_root = os.environ.get("LOCAL_AI_HUB_SOURCE_OVERLAY")
if overlay_root:
    sys.path.insert(0, str(source_root / "src"))
    import local_ai_hub

    local_ai_hub.__path__.insert(0, str(Path(overlay_root).resolve() / "src" / "local_ai_hub"))

import pytest

from local_ai_hub.commands import CommandBroker
from local_ai_hub.repo_state import RepoStateTracker
from local_ai_hub.services import LocalAIServices
from local_ai_hub.work_fencing import FencingLeaseStore, LeaseLostError, canonical_resource
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.process_utils import run_hidden
from local_ai_hub.project_config import resolve_project_context
import local_ai_hub.work_orchestrator as work_orchestrator_module
from local_ai_hub.work_orchestrator import WorkOrchestrator, _JournalEntry


class _Leases:
    def claim_batch(self, tenant, root, paths, ttl_seconds=900, purpose="", *, coordination_id=None):
        return {"success": True, "lease_id": f"lease-{len(paths)}", "paths": paths}

    def release(self, tenant, lease_id=""):
        return {"success": True}


class _Artifacts:
    def put(self, text, tenant, kind):
        return f"artifact-{kind}"


def _make_orchestrator(tmp_path: Path, *, max_pending: int = 8):
    root = tmp_path / "repo"
    root.mkdir()
    state_dir = tmp_path / "state"
    config = {
        "work_orchestrator": {
            "enabled": True,
            "max_pending_work_orders": max_pending,
            "max_steps": 16,
            "max_llm_steps": 10,
            "max_seconds": 60,
        }
    }
    orchestrator = WorkOrchestrator(
        config,
        state_dir,
        services=object(),
        commands=object(),
        leases=_Leases(),
        artifacts=_Artifacts(),
    )
    orchestrator._ensure_workers = lambda: None
    return orchestrator, root, state_dir, config


def _payload(root: Path, work_id: str, task: str = "inspect repo") -> dict[str, object]:
    return {
        "root": str(root),
        "task": task,
        "work_id": work_id,
        "acceptance_criteria": ["report result"],
        "budget": {"max_seconds": 30},
    }


def test_path_leases_allow_disjoint_scopes_and_reject_overlap(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    leases = ScopeLeaseStore(tmp_path / "leases")
    first: dict[str, object] = {}
    disjoint: dict[str, object] = {}
    try:
        first = leases.claim_batch("tenant-a", str(root), ["src/a.py"])
        disjoint = leases.claim_batch("tenant-b", str(root), ["src/b.py"])
        overlapping = leases.claim_batch("tenant-b", str(root), ["src/a.py"])

        assert first["success"] is True
        assert disjoint["success"] is True
        assert overlapping["success"] is False
    finally:
        if first.get("success"):
            leases.release("tenant-a", first["lease_id"])
        if disjoint.get("success"):
            leases.release("tenant-b", disjoint["lease_id"])


def test_edit_lease_conflict_leaves_workspace_and_journal_unchanged(tmp_path: Path) -> None:
    orchestrator, root, state_dir, _config = _make_orchestrator(tmp_path)
    target = root / "owned.txt"
    target.write_text("old\n", encoding="utf-8")
    leases = ScopeLeaseStore(state_dir / "leases")
    held: dict[str, object] = {}
    patch = "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-old\n+new\n"
    try:
        held = leases.claim_batch("other-tenant", str(root), ["owned.txt"])
        assert held["success"] is True
        orchestrator.leases = leases
        with pytest.raises(RuntimeError, match="edit lease unavailable"):
            orchestrator._apply_patch(root, patch, "tenant", "work-lease", [])

        assert target.read_text(encoding="utf-8") == "old\n"
        assert orchestrator._load_journal("work-lease") == []
    finally:
        if held.get("success"):
            leases.release("other-tenant", held["lease_id"])
        orchestrator.close()


def test_submit_retry_after_lost_ack_returns_same_work_order(tmp_path: Path) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    try:
        # Treat first reply as lost. Retry must replay accepted order, not reject it.
        orchestrator.submit("tenant", _payload(root, "work-replay"))
        replay = orchestrator.submit("tenant", _payload(root, "work-replay"))

        assert replay["success"] is True
        assert replay["work_id"] == "work-replay"
        assert replay["status"] == "queued"
        with closing(orchestrator._connect()) as con:
            assert con.execute(
                "SELECT COUNT(*) FROM work_orders WHERE work_id=?", ("work-replay",)
            ).fetchone()[0] == 1
    finally:
        orchestrator.close()


def test_concurrent_idempotent_submits_create_one_work_order(tmp_path: Path) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    barrier = threading.Barrier(2)
    results: list[dict[str, object]] = []

    def submit() -> None:
        barrier.wait(timeout=5)
        results.append(orchestrator.submit("tenant", _payload(root, "work-concurrent-replay")))

    workers = [threading.Thread(target=submit) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)

        assert all(not worker.is_alive() for worker in workers)
        assert len(results) == 2
        assert all(result["success"] is True for result in results)
        assert {result["work_id"] for result in results} == {"work-concurrent-replay"}
        with closing(orchestrator._connect()) as con:
            assert con.execute(
                "SELECT COUNT(*) FROM work_orders WHERE work_id=?",
                ("work-concurrent-replay",),
            ).fetchone()[0] == 1
    finally:
        orchestrator.close()


def test_wait_caps_requested_timeout_at_ninety_seconds(tmp_path: Path, monkeypatch) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    work_id = "work-bounded-wait"
    clock = [100.0]
    waits: list[float] = []

    class WaitRecorder:
        def wait(self, timeout: float) -> None:
            waits.append(timeout)
            clock[0] += timeout

        def clear(self) -> None:
            pass

    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        monkeypatch.setattr(
            work_orchestrator_module,
            "time",
            SimpleNamespace(monotonic=lambda: clock[0], perf_counter=_real_time.perf_counter),
        )
        event = WaitRecorder()
        monkeypatch.setattr(orchestrator, "_event", lambda _work_id: event)

        result = orchestrator.wait("tenant", work_id, timeout_seconds=10_000)

        assert result["status"] == "queued"
        assert result["in_progress"] is True
        assert len(waits) == 180
        assert sum(waits) == pytest.approx(90.0)
        assert max(waits) <= 0.5
    finally:
        orchestrator.close()


def test_queue_full_still_replays_existing_work_order(tmp_path: Path) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path, max_pending=1)
    try:
        first = _payload(root, "work-one")
        assert orchestrator.submit("tenant", first)["success"] is True

        rejected = orchestrator.submit("tenant", _payload(root, "work-two"))
        replay = orchestrator.submit("tenant", first)

        assert rejected["error"] == "work-order queue is full"
        assert rejected["retryable"] is True
        assert replay["success"] is True
        assert replay["work_id"] == "work-one"
        with closing(orchestrator._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0] == 1
    finally:
        orchestrator.close()


def test_replayed_work_id_rejects_different_request(tmp_path: Path) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    try:
        assert orchestrator.submit(
            "tenant", _payload(root, "work-conflict", "inspect repo")
        )["success"] is True

        conflict = orchestrator.submit(
            "tenant", _payload(root, "work-conflict", "delete repo")
        )

        assert conflict["success"] is False
        assert conflict["error"] == "work_id already exists with different request"
        assert conflict["terminal"] is True
        with closing(orchestrator._connect()) as con:
            assert con.execute(
                "SELECT task FROM work_orders WHERE work_id=?", ("work-conflict",)
            ).fetchone()[0] == "inspect repo"
    finally:
        orchestrator.close()


def test_recovery_requeues_after_crash_between_journal_clear_and_state_update(
    tmp_path: Path, monkeypatch
) -> None:
    now = [100.0]
    orchestrator, root, state_dir, config = _make_orchestrator(tmp_path)
    fencing = FencingLeaseStore(state_dir / "work_fencing.sqlite3", clock=lambda: now[0])
    orchestrator.fencing_store = fencing
    work_id = "work-recover"
    target = root / "owned.txt"
    target.write_bytes(b"new\n")
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "executing", {"changed_files": ["owned.txt"]})
        stale_attempt = fencing.claim_attempt(
            str(root), work_id, "crashed-writer", ttl_seconds=5
        )
        stale = fencing.acquire(
            str(root), work_id, ["owned.txt"], ttl_seconds=5, attempt=stale_attempt
        )
        orchestrator._persist_journal(
            work_id,
            [
                _JournalEntry(
                    "owned.txt", True, b"old\n", True,
                    hashlib.sha256(b"new\n").hexdigest(),
                    stale.resource, stale.lease_id, stale.owner_id, stale.fencing_token,
                    stale_attempt.attempt_id, stale_attempt.fencing_token,
                )
            ],
        )
        orchestrator._recover()
        waiting_row = orchestrator._row(work_id, "tenant")
        assert waiting_row is not None and waiting_row["state"] == "executing"
        assert orchestrator._recovery_timer is not None
        assert target.read_text(encoding="utf-8") == "new\n"
        assert orchestrator._load_journal(work_id)
        now[0] = 106.0
        clear_journal = orchestrator._clear_journal

        class SimulatedProcessCrash(BaseException):
            pass

        def clear_then_crash(current_id: str) -> None:
            clear_journal(current_id)
            raise SimulatedProcessCrash()

        orchestrator._clear_journal = clear_then_crash
        with pytest.raises(SimulatedProcessCrash):
            orchestrator._recover()
        assert target.read_text(encoding="utf-8") == "old\n"
    finally:
        orchestrator.close()

    now[0] = 1007.0  # the simulated crashed recovery epoch has a 900 second lease
    monkeypatch.setattr(WorkOrchestrator, "_ensure_workers", lambda _self: None)
    recovered = WorkOrchestrator(
        config,
        state_dir,
        services=object(),
        commands=object(),
        leases=_Leases(),
        artifacts=_Artifacts(),
        fencing_store=FencingLeaseStore(state_dir / "work_fencing.sqlite3", clock=lambda: now[0]),
    )
    try:
        row = recovered._row(work_id, "tenant")
        assert row is not None
        assert row["state"] == "queued"
        assert json.loads(str(row["result_json"] or "{}")) == {}
        assert target.read_text(encoding="utf-8") == "old\n"
    finally:
        recovered.close()


def test_restart_rolls_back_patch_using_postimage_journaled_before_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    orchestrator, root, state_dir, config = _make_orchestrator(tmp_path)
    work_id = "work-restart-during-patch-transaction"
    target = root / "owned.txt"
    target.write_text("before\n", encoding="utf-8")
    patch = "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-before\n+after\n"
    orchestrator.submit("tenant", _payload(root, work_id))
    orchestrator._set_state(work_id, "executing", {"changed_files": ["owned.txt"]})

    journal: list[_JournalEntry] = []
    orchestrator._apply_patch(root, patch, "tenant", work_id, journal)
    assert target.read_text(encoding="utf-8") == "after\n"
    assert journal[0].postimage_existed is True
    assert journal[0].postimage_sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    orchestrator.close()

    monkeypatch.setattr(WorkOrchestrator, "_ensure_workers", lambda _self: None)
    recovered = WorkOrchestrator(
        config,
        state_dir,
        services=object(),
        commands=object(),
        leases=_Leases(),
        artifacts=_Artifacts(),
    )
    try:
        row = recovered._row(work_id, "tenant")
        assert row is not None and row["state"] == "queued"
        assert target.read_text(encoding="utf-8") == "before\n"
        assert recovered._load_journal(work_id) == []
    finally:
        recovered.close()


def test_recovery_rollback_failure_fails_closed_and_preserves_journal(
    tmp_path: Path, monkeypatch
) -> None:
    orchestrator, root, state_dir, config = _make_orchestrator(tmp_path)
    work_id = "work-recovery-fail-closed"
    target = root / "owned.txt"
    target.write_text("new\n", encoding="utf-8")
    journal_entry = _fenced_journal_entry(root, "owned.txt", b"old\n", b"new\n")
    orchestrator.submit("tenant", _payload(root, work_id))
    orchestrator._set_state(work_id, "executing", {"changed_files": ["owned.txt"]})
    orchestrator._persist_journal(work_id, [journal_entry])
    orchestrator.close()

    def fail_rollback(*_args, **_kwargs):
        raise OSError("simulated workspace restore failure")

    monkeypatch.setattr(WorkOrchestrator, "_rollback", fail_rollback)
    recovered = WorkOrchestrator(
        config,
        state_dir,
        services=object(),
        commands=object(),
        leases=_Leases(),
        artifacts=_Artifacts(),
    )
    try:
        row = recovered._row(work_id, "tenant")
        assert row is not None
        assert row["state"] == "needs_agent"
        assert "could not be safely restored" in str(row["result_json"])
        assert recovered._load_journal(work_id) is not None
        assert target.read_text(encoding="utf-8") == "new\n"
    finally:
        recovered.close()


def test_rollback_refuses_unrecognized_same_path_postimage_and_keeps_journal(
    tmp_path: Path,
) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    work_id = "work-same-path-postimage-conflict"
    target = root / "owned.txt"
    other = root / "other.txt"
    foreign = root / "foreign.txt"
    target.write_text("original\n", encoding="utf-8")
    other.write_text("other original\n", encoding="utf-8")
    foreign.write_text("foreign original\n", encoding="utf-8")
    patch = (
        "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n"
        "-original\n+orchestrator update\n"
        "--- a/other.txt\n+++ b/other.txt\n@@ -1 +1 @@\n"
        "-other original\n+other update\n"
    )
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "executing", {"changed_files": ["owned.txt"]})
        journal: list[_JournalEntry] = []
        orchestrator._apply_patch(root, patch, "tenant", work_id, journal)
        assert journal == orchestrator._load_journal(work_id)

        target.write_text("external update\n", encoding="utf-8")
        foreign.write_text("foreign external update\n", encoding="utf-8")

        with pytest.raises(RuntimeError, match="postimage changed"):
            orchestrator._rollback_transaction(work_id, root, journal)

        assert target.read_text(encoding="utf-8") == "external update\n"
        assert other.read_text(encoding="utf-8") == "other update\n"
        assert foreign.read_text(encoding="utf-8") == "foreign external update\n"
        assert orchestrator._load_journal(work_id) == journal
        row = orchestrator._row(work_id, "tenant")
        assert row is not None and row["state"] == "executing"
    finally:
        orchestrator.close()


def test_rollback_accepts_chained_same_path_postimages(tmp_path: Path) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    work_id = "work-same-path-postimage-chain"
    target = root / "owned.txt"
    target.write_bytes(b"final\n")
    entries = [
        _fenced_journal_entry(root, "owned.txt", b"original\n", b"middle\n"),
        _fenced_journal_entry(
            root, "owned.txt", b"middle\n", b"final\n",
            owner="later-owner", lease_id="later-lease", fencing_token=2,
            attempt_id="later-attempt", attempt_token=2,
        ),
    ]
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "executing", {"changed_files": ["owned.txt"]})
        orchestrator._persist_journal(work_id, entries)

        assert orchestrator._rollback_transaction(work_id, root, entries) is True

        assert target.read_text(encoding="utf-8") == "original\n"
        assert orchestrator._load_journal(work_id) == []
    finally:
        orchestrator.close()


def test_crash_recovery_conflict_fails_closed_without_partial_restore(tmp_path: Path) -> None:
    orchestrator, root, state_dir, config = _make_orchestrator(tmp_path)
    work_id = "work-recovery-postimage-conflict"
    target = root / "owned.txt"
    other = root / "other.txt"
    target.write_text("orchestrator update\n", encoding="utf-8")
    other.write_text("other update\n", encoding="utf-8")
    entries = [
        _fenced_journal_entry(
            root, "owned.txt", b"original\n", b"orchestrator update\n"
        ),
        _fenced_journal_entry(
            root, "other.txt", b"other original\n", b"other update\n"
        ),
    ]
    orchestrator.submit("tenant", _payload(root, work_id))
    orchestrator._set_state(work_id, "executing", {"changed_files": ["owned.txt", "other.txt"]})
    orchestrator._persist_journal(work_id, entries)
    orchestrator.close()

    target.write_text("external update\n", encoding="utf-8")
    recovered = WorkOrchestrator(
        config,
        state_dir,
        services=object(),
        commands=object(),
        leases=_Leases(),
        artifacts=_Artifacts(),
    )
    try:
        row = recovered._row(work_id, "tenant")
        assert row is not None and row["state"] == "needs_agent"
        assert "could not be safely restored" in str(row["result_json"])
        assert target.read_text(encoding="utf-8") == "external update\n"
        assert other.read_text(encoding="utf-8") == "other update\n"
        assert recovered._load_journal(work_id) == entries
    finally:
        recovered.close()


def test_restart_after_completion_keeps_workspace_and_clears_orphan_journal(tmp_path: Path) -> None:
    orchestrator, root, state_dir, config = _make_orchestrator(tmp_path)
    work_id = "work-complete-before-journal-clear"
    target = root / "owned.txt"
    target.write_text("committed\n", encoding="utf-8")
    orchestrator.submit("tenant", _payload(root, work_id))
    orchestrator._persist_journal(
        work_id, [_JournalEntry("owned.txt", True, b"before\n")]
    )
    orchestrator._set_state(work_id, "complete", {"summary": "committed"})
    orchestrator.close()

    recovered = WorkOrchestrator(
        config,
        state_dir,
        services=object(),
        commands=object(),
        leases=_Leases(),
        artifacts=_Artifacts(),
    )
    try:
        row = recovered._row(work_id, "tenant")
        assert row is not None
        assert row["state"] == "complete"
        assert target.read_text(encoding="utf-8") == "committed\n"
        assert recovered._load_journal(work_id) == []
    finally:
        recovered.close()


def test_concurrent_continue_has_one_compare_and_swap_winner(tmp_path: Path) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    work_id = "work-continue"
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "needs_agent", {"needs_agent": True})
        original_row = orchestrator._row
        read_barrier = threading.Barrier(2)

        def read_same_state(current_id: str, tenant: str = ""):
            row = original_row(current_id, tenant)
            if threading.current_thread().name.startswith("continue-"):
                read_barrier.wait(timeout=5)
            return row

        orchestrator._row = read_same_state
        results: list[dict[str, object]] = []
        workers = [
            threading.Thread(
                name=f"continue-{index}",
                target=lambda answer=answer: results.append(
                    orchestrator.continue_work("tenant", work_id, answer)
                ),
            )
            for index, answer in enumerate(("answer A", "answer B"))
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=6)

        assert all(not worker.is_alive() for worker in workers)
        assert sum(bool(result.get("success")) for result in results) == 1
        row = original_row(work_id, "tenant")
        assert row is not None
        assert row["state"] == "queued"
        saved_answer = json.loads(str(row["payload_json"]))["agent_answer"]
        assert saved_answer in {"answer A", "answer B"}
    finally:
        orchestrator.close()


def test_cancel_request_blocks_compare_and_swap_completion(tmp_path: Path) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    work_id = "work-cancel-finalize"
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "verifying", {"changed_files": ["owned.txt"]})

        cancelled = orchestrator.cancel("tenant", work_id)
        completed = orchestrator._complete_if_not_cancelled(
            work_id, {"summary": "verified"}
        )

        row = orchestrator._row(work_id, "tenant")
        assert cancelled["status"] == "cancelling"
        assert completed is False
        assert row is not None
        assert row["state"] == "verifying"
        assert row["cancel_requested"] == 1
    finally:
        orchestrator.close()


def test_completion_cas_wins_against_later_cancel(tmp_path: Path) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    work_id = "work-complete-before-cancel"
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "verifying", {})

        completed = orchestrator._complete_if_not_cancelled(
            work_id, {"summary": "verified"}
        )
        cancelled = orchestrator.cancel("tenant", work_id)

        assert completed is True
        assert cancelled["status"] == "complete"
        row = orchestrator._row(work_id, "tenant")
        assert row is not None
        assert row["state"] == "complete"
        assert row["cancel_requested"] == 0
    finally:
        orchestrator.close()


def test_cancel_and_completion_race_has_one_durable_winner(tmp_path: Path) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    work_id = "work-cancel-complete-race"
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "verifying", {})
        start = threading.Barrier(3)
        results: dict[str, object] = {}

        def cancel() -> None:
            start.wait(timeout=5)
            results["cancel"] = orchestrator.cancel("tenant", work_id)

        def complete() -> None:
            start.wait(timeout=5)
            results["complete"] = orchestrator._complete_if_not_cancelled(
                work_id, {"summary": "verified"}
            )

        workers = [threading.Thread(target=cancel), threading.Thread(target=complete)]
        for worker in workers:
            worker.start()
        start.wait(timeout=5)
        for worker in workers:
            worker.join(timeout=6)

        assert all(not worker.is_alive() for worker in workers)
        cancel_result = results["cancel"]
        completed = results["complete"]
        row = orchestrator._row(work_id, "tenant")
        assert isinstance(cancel_result, dict)
        assert row is not None
        if cancel_result["status"] == "complete":
            assert completed is True
            assert row["state"] == "complete"
            assert row["cancel_requested"] == 0
        else:
            assert cancel_result["status"] == "cancelling"
            assert completed is False
            assert row["state"] == "verifying"
            assert row["cancel_requested"] == 1
    finally:
        orchestrator.close()

def _fenced_journal_entry(
    root: Path,
    path: str,
    before: bytes,
    after: bytes,
    *,
    owner: str = "prior-owner",
    lease_id: str = "prior-lease",
    fencing_token: int = 1,
    attempt_id: str = "prior-attempt",
    attempt_token: int = 1,
) -> _JournalEntry:
    return _JournalEntry(
        path,
        True,
        before,
        True,
        hashlib.sha256(after).hexdigest(),
        canonical_resource(root),
        lease_id,
        owner,
        fencing_token,
        attempt_id,
        attempt_token,
    )

def test_recovery_reacquires_fence_after_writer_ttl_and_rejects_stale_commit(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    state_dir = tmp_path / "state"
    now = [100.0]
    fence_path = state_dir / "work_fencing.sqlite3"
    old_store = FencingLeaseStore(fence_path, clock=lambda: now[0])
    monkeypatch.setattr(WorkOrchestrator, "_ensure_workers", lambda _self: None)
    orchestrator = WorkOrchestrator(
        {"work_orchestrator": {"enabled": True}}, state_dir,
        services=object(), commands=object(), leases=_Leases(), artifacts=_Artifacts(),
        fencing_store=old_store,
    )
    work_id = "work-fenced-recovery"
    target = root / "owned.txt"
    target.write_bytes(b"new\n")
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "executing", {"changed_files": ["owned.txt"]})
        stale_attempt = old_store.claim_attempt(
            str(root), work_id, "crashed-writer", ttl_seconds=5
        )
        stale = old_store.acquire(
            str(root), work_id, ["owned.txt"], ttl_seconds=5, attempt=stale_attempt
        )
        orchestrator._persist_journal(
            work_id,
            [
                _JournalEntry(
                    "owned.txt", True, b"old\n", True,
                    hashlib.sha256(b"new\n").hexdigest(),
                    stale.resource, stale.lease_id, stale.owner_id, stale.fencing_token,
                    stale_attempt.attempt_id, stale_attempt.fencing_token,
                )
            ],
        )
        now[0] = 106.0
        recovered_store = FencingLeaseStore(fence_path, clock=lambda: now[0])
        recovered = WorkOrchestrator(
            {"work_orchestrator": {"enabled": True}}, state_dir,
            services=object(), commands=object(), leases=_Leases(), artifacts=_Artifacts(),
            fencing_store=recovered_store,
        )
        try:
            row = recovered._row(work_id, "tenant")
            assert row is not None and row["state"] == "queued"
            assert target.read_text(encoding="utf-8") == "old\n"
            assert recovered._load_journal(work_id) == []
            with pytest.raises(LeaseLostError):
                with recovered_store.commit_guard(stale, ["owned.txt"]):
                    target.write_text("stale-after-recovery\n", encoding="utf-8")
            assert target.read_text(encoding="utf-8") == "old\n"
        finally:
            recovered.close()
    finally:
        orchestrator.close()

def test_stale_attempt_cannot_complete_or_clear_successor_journal(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    state_dir = tmp_path / "state"
    now = [100.0]
    fencing = FencingLeaseStore(state_dir / "work_fencing.sqlite3", clock=lambda: now[0])
    orchestrator = WorkOrchestrator(
        {"work_orchestrator": {"enabled": True}}, state_dir,
        services=object(), commands=object(), leases=_Leases(), artifacts=_Artifacts(),
        fencing_store=fencing,
    )
    orchestrator._ensure_workers = lambda: None
    work_id = "work-stale-completion"
    target = root / "owned.txt"
    target.write_bytes(b"successor\n")
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "verifying", {"summary": "verification pending"})
        stale_attempt = fencing.claim_attempt(
            str(root), work_id, "old-execution", ttl_seconds=5
        )
        stale_lease = fencing.acquire(
            str(root), "old-execution", ["owned.txt"], ttl_seconds=30,
            attempt=stale_attempt,
        )
        stale_entry = _fenced_journal_entry(
            root, "owned.txt", b"before\n", b"old-write\n",
            owner=stale_lease.owner_id, lease_id=stale_lease.lease_id,
            fencing_token=stale_lease.fencing_token,
            attempt_id=stale_attempt.attempt_id,
            attempt_token=stale_attempt.fencing_token,
        )
        orchestrator._persist_journal(work_id, [stale_entry])

        now[0] = 106.0
        successor_attempt = fencing.claim_attempt(
            str(root), work_id, "successor-execution", ttl_seconds=30
        )
        successor_lease = fencing.acquire(
            str(root), "successor-execution", ["owned.txt"], ttl_seconds=30,
            attempt=successor_attempt,
        )
        successor_entry = _fenced_journal_entry(
            root, "owned.txt", b"before\n", b"successor\n",
            owner=successor_lease.owner_id, lease_id=successor_lease.lease_id,
            fencing_token=successor_lease.fencing_token,
            attempt_id=successor_attempt.attempt_id,
            attempt_token=successor_attempt.fencing_token,
        )
        orchestrator._persist_journal(work_id, [successor_entry])

        with pytest.raises(LeaseLostError):
            orchestrator._set_state(
                work_id, "complete", {"summary": "stale completion"},
                attempt=stale_attempt,
            )
        with pytest.raises(LeaseLostError):
            orchestrator._persist_handoff_receipts(
                work_id, [], [], attempt=stale_attempt
            )
        with pytest.raises(LeaseLostError):
            orchestrator._complete_if_not_cancelled(
                work_id, {"summary": "stale completion"},
                expected_state="verifying", attempt=stale_attempt,
            )
        with pytest.raises(LeaseLostError):
            orchestrator._clear_journal(work_id, attempt=stale_attempt)

        row = orchestrator._row(work_id, "tenant")
        assert row is not None and row["state"] == "verifying"
        assert orchestrator._load_journal(work_id) == [successor_entry]
        assert target.read_bytes() == b"successor\n"
    finally:
        orchestrator.close()

def test_rollback_refuses_hardlinked_postimage(tmp_path: Path) -> None:
    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    target = root / "owned.txt"
    external = tmp_path / "external-hardlink.txt"
    target.write_bytes(b"postimage\n")
    try:
        try:
            os.link(target, external)
        except OSError as exc:
            pytest.skip(f"hard links unavailable: {exc}")
        entry = _fenced_journal_entry(root, "owned.txt", b"before\n", b"postimage\n")

        with pytest.raises(RuntimeError, match="hardlinked postimage"):
            orchestrator._rollback(root, [entry])

        assert target.read_bytes() == b"postimage\n"
        assert external.read_bytes() == b"postimage\n"
    finally:
        orchestrator.close()

def test_recovery_defers_live_attempt_without_journal(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    state_dir = tmp_path / "state"
    now = [100.0]
    fencing = FencingLeaseStore(state_dir / "work_fencing.sqlite3", clock=lambda: now[0])
    monkeypatch.setattr(WorkOrchestrator, "_ensure_workers", lambda _self: None)
    orchestrator = WorkOrchestrator(
        {"work_orchestrator": {"enabled": True}}, state_dir,
        services=object(), commands=object(), leases=_Leases(), artifacts=_Artifacts(),
        fencing_store=fencing,
    )
    work_id = "work-live-attempt-no-journal"
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "planning", {"summary": "still running"})
        active = fencing.claim_attempt(str(root), work_id, "live-execution", ttl_seconds=5)

        orchestrator._recover()

        row = orchestrator._row(work_id, "tenant")
        assert row is not None and row["state"] == "planning"
        assert orchestrator._recovery_retry_requested is True
        assert orchestrator._recovery_timer is not None

        now[0] = 106.0
        orchestrator._recover()
        row = orchestrator._row(work_id, "tenant")
        assert row is not None and row["state"] == "queued"
    finally:
        orchestrator.close()

def test_invalid_patch_releases_advisory_lease(tmp_path: Path) -> None:
    class RecordingLeases(_Leases):
        def __init__(self):
            self.released: list[tuple[str, str]] = []

        def release(self, tenant, lease_id=""):
            self.released.append((tenant, lease_id))
            return super().release(tenant, lease_id)

    orchestrator, root, _state_dir, _config = _make_orchestrator(tmp_path)
    leases = RecordingLeases()
    orchestrator.leases = leases
    target = root / "owned.txt"
    target.write_bytes(b"original\n")
    invalid_patch = "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n-wrong\n+changed\n"
    try:
        with pytest.raises(ValueError):
            orchestrator._apply_patch(
                root, invalid_patch, "tenant", "work-invalid-patch", []
            )

        assert leases.released == [("tenant", "lease-1")]
        assert target.read_bytes() == b"original\n"
    finally:
        orchestrator.close()

def test_real_command_broker_accepts_forwarded_work_attempt_fence(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    state_dir = tmp_path / "state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "commands": {"enabled": True, "allow_unknown": True},
    }
    broker = CommandBroker(config, _Artifacts(), RepoStateTracker(config))
    now = [100.0]
    fencing = FencingLeaseStore(state_dir / "work_fencing.sqlite3", clock=lambda: now[0])
    broker.set_fencing_lease_store(fencing)
    attempt = fencing.claim_attempt(str(root), "work-real-broker", "acceptance", ttl_seconds=5)
    services = object.__new__(LocalAIServices)
    services.commands = broker
    services.agent_state = None
    command = f'"{sys.executable}" -B -c "print(123)"'

    result = services.command(
        {
            "action": "run",
            "command": command,
            "cwd": str(root),
            "task_id": "work-real-broker",
            "criterion": "real command broker fence",
            "record_verification": False,
            "writer_fence": attempt,
        },
        "tenant",
    )

    assert result["success"] is True, result
    assert "123" in result.get("stdout", "")

    now[0] += 6
    stale_result = services.command(
        {
            "action": "run",
            "command": command,
            "cwd": str(root),
            "task_id": "work-real-broker",
            "criterion": "stale real command broker fence",
            "record_verification": False,
            "writer_fence": attempt,
        },
        "tenant",
    )

    assert stale_result["success"] is False, stale_result
    assert "123" not in stale_result.get("stdout", "")


def test_root_current_command_broker_namespace_guard_commits_real_write(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text('shared_namespace = "broker-test"\n', encoding="utf-8")
    target = root / "owned.txt"
    target.write_text("before\n", encoding="utf-8")

    def git(*args: str) -> None:
        result = run_hidden(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, result.stderr

    initialized = run_hidden(
        ["git", "init", "--quiet", str(root)], capture_output=True, text=True, timeout=10
    )
    assert initialized.returncode == 0, initialized.stderr
    git("add", ".local-ai.toml", "owned.txt")
    git(
        "-c", "user.name=Broker Fence Test", "-c", "user.email=broker@example.invalid",
        "commit", "--quiet", "-m", "broker fence fixture",
    )

    source_path = source_root / "src" / "local_ai_hub" / "commands.py"
    module_path = Path(sys.modules[CommandBroker.__module__].__file__).resolve()
    assert module_path == source_path.resolve()

    state_dir = tmp_path / "state"
    config = {"server": {"state_dir": str(state_dir)}, "commands": {"enabled": True}}
    broker = CommandBroker(config, _Artifacts(), RepoStateTracker(config))
    now = [100.0]
    fencing = FencingLeaseStore(state_dir / "work_fencing.sqlite3", clock=lambda: now[0])
    broker.set_fencing_lease_store(fencing)
    context = resolve_project_context(root, state_dir)
    coordination_id = context.coordination_id
    assert coordination_id
    attempt = fencing.claim_attempt(
        str(root), "work-broker-write", "broker-owner", ttl_seconds=5,
        coordination_id=coordination_id,
    )
    physical_root = canonical_resource(root)
    assert attempt.resource == physical_root
    with broker._fenced_transaction_commit(
        attempt,
        task_id="work-broker-write",
        source=root,
        paths=["owned.txt"],
        owner_id="broker-writer",
    ) as (lease, payload):
        assert lease.resource == physical_root
        assert lease.scope_id == attempt.scope_id
        assert payload["resource"] == physical_root
        target.write_text("committed\n", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "committed\n"

    now[0] = 106.0
    with pytest.raises(LeaseLostError):
        with broker._fenced_transaction_commit(
            attempt,
            task_id="work-broker-write",
            source=root,
            paths=["owned.txt"],
            owner_id="stale-broker-writer",
        ):
            target.write_text("stale\n", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "committed\n"
