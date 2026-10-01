from __future__ import annotations

import hashlib
import json
import threading
import time as _real_time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.leases import ScopeLeaseStore
import local_ai_hub.work_orchestrator as work_orchestrator_module
from local_ai_hub.work_orchestrator import WorkOrchestrator, _JournalEntry


class _Leases:
    def claim_batch(self, tenant, root, paths, ttl_seconds=900, purpose=""):
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
    tmp_path: Path,
) -> None:
    orchestrator, root, state_dir, config = _make_orchestrator(tmp_path)
    work_id = "work-recover"
    target = root / "owned.txt"
    target.write_bytes(b"new\n")
    try:
        orchestrator.submit("tenant", _payload(root, work_id))
        orchestrator._set_state(work_id, "executing", {"changed_files": ["owned.txt"]})
        orchestrator._persist_journal(
            work_id,
            [
                _JournalEntry(
                    "owned.txt", True, b"old\n", True,
                    hashlib.sha256(b"new\n").hexdigest(),
                )
            ],
        )
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
        assert row["state"] == "queued"
        assert json.loads(str(row["result_json"] or "{}")) == {}
        assert target.read_text(encoding="utf-8") == "old\n"
    finally:
        recovered.close()


def test_restart_rolls_back_patch_using_postimage_journaled_before_mutation(
    tmp_path: Path,
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
    journal_entry = _JournalEntry("owned.txt", True, b"old\n")
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
        _JournalEntry(
            "owned.txt", True, b"original\n", True,
            hashlib.sha256(b"middle\n").hexdigest(),
        ),
        _JournalEntry(
            "owned.txt", True, b"middle\n", True,
            hashlib.sha256(b"final\n").hexdigest(),
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
        _JournalEntry(
            "owned.txt", True, b"original\n", True,
            hashlib.sha256(b"orchestrator update\n").hexdigest(),
        ),
        _JournalEntry(
            "other.txt", True, b"other original\n", True,
            hashlib.sha256(b"other update\n").hexdigest(),
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
