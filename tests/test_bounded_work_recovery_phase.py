from types import SimpleNamespace
from contextlib import closing
import json
import time

import pytest

from local_ai_hub.work_orchestrator import WorkOrchestrator
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStatus, TaskStore
from test_work_orchestrator import FakeArtifacts, FakeLeases, init_repo


@pytest.mark.parametrize("result,allowed", [
    ({"needs_agent": True, "question": "Clarify?"}, True),
    ({"needs_agent": True, "question": "Clarify?", "task_barrier_status": "released"}, True),
    ({"needs_agent": True, "error": "legacy recovery failed"}, False),
    ({"needs_agent": True, "question": "Review the result", "handoff_id": "handoff-1"}, False),
    ({"outcome_unknown": True}, False),
    ({"outcome_unknown": "false"}, False),
    ({"task_barrier_status": "pending_finalization"}, False),
    ({"task_barrier_status": "reconciliation_required"}, False),
    ({"rollback_status": "reconciliation_required"}, False),
])
def test_bounded_continue_rejects_ambiguous_handoff(tmp_path, monkeypatch, result, allowed):
    root = init_repo(tmp_path)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(orch, "_ensure_workers", lambda: None)
    try:
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)", (
                "work-1", str(root), "change", "needs_agent", json.dumps({"mode": "bounded"}),
                json.dumps(result), 0, time.time(), time.time()))
        resumed = orch.continue_work("work-1", "answer")
        assert resumed["success"] is allowed
        assert orch._row("work-1")["state"] == ("queued" if allowed else "needs_agent")
    finally:
        orch.close()


def test_bounded_continue_rejects_concurrently_changed_handoff(tmp_path, monkeypatch):
    root = init_repo(tmp_path)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(orch, "_ensure_workers", lambda: None)
    original_row = orch._row
    try:
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)", (
                "work-1", str(root), "change", "needs_agent", json.dumps({"mode": "bounded"}),
                json.dumps({"needs_agent": True, "question": "Clarify?"}), 0, time.time(), time.time()))
        def race(work_id):
            stale = original_row(work_id)
            with closing(orch._connect()) as con:
                con.execute("UPDATE work_orders SET result_json=? WHERE work_id=?",
                            (json.dumps({"outcome_unknown": True}), work_id))
            return stale
        monkeypatch.setattr(orch, "_row", race)
        resumed = orch.continue_work("work-1", "answer")
        assert resumed["success"] is False
        assert original_row("work-1")["state"] == "needs_agent"
    finally:
        orch.close()


@pytest.mark.parametrize("payload,task,expected", [
    ({}, None, False),
    ({"task_id": "task"}, None, True),
    ({"task_id": "task"}, {"_pending_fenced_work": {"work_id": "work-1"}}, True),
    ({"task_id": "task"}, {"_pending_fenced_work": None}, True),
    ({"task_id": "task"}, {}, False),
])
def test_recovery_rejects_unknown_or_pending_task_barrier(payload, task, expected):
    orch = object.__new__(WorkOrchestrator)
    record = None if task is None else SimpleNamespace(checkpoint=SimpleNamespace(state_data=task))
    orch.verification_store = SimpleNamespace(task_store=SimpleNamespace(get=lambda _id: record))
    assert orch._recovery_task_barrier_unresolved(payload) is expected


def test_recovery_rejects_unavailable_task_store():
    orch = object.__new__(WorkOrchestrator)
    orch.verification_store = None
    assert orch._recovery_task_barrier_unresolved({"task_id": "task"}) is True


def test_exact_finalization_event_requires_stream_actor_and_payload(tmp_path):
    from local_ai_hub.agent_events import AgentEvent

    store = AgentStateStore(tmp_path / "events.sqlite3")
    payload = {"work_id": "work-1", "attempt_id": "attempt", "attempt_token": 7, "rollback": False}
    store.append(AgentEvent.create(stream_id="task:task", kind="task.fenced_work_finalized",
                                   payload=payload, actor="owner", idempotency_key="event"))
    assert store.has_exact_event("task:task", "task.fenced_work_finalized", payload, actor="owner") is True
    assert store.has_exact_event("task:other", "task.fenced_work_finalized", payload, actor="owner") is False
    assert store.has_exact_event("task:task", "task.fenced_work_finalized", payload, actor="other") is False
    assert store.has_exact_event("task:task", "task.fenced_work_finalized", {**payload, "rollback": True}, actor="owner") is False
    assert store.has_exact_event("task:task", "task.fenced_work_finalized", {**payload, "rollback": 0}, actor="owner") is False
    assert store.has_exact_event("task:task", "task.fenced_work_finalized", {**payload, "extra": "x"}, actor="owner") is False


def test_exact_event_lookup_reports_busy_as_timeout(tmp_path, monkeypatch):
    import sqlite3
    from local_ai_hub import agent_events
    from local_ai_hub.agent_events import AgentEvent

    store = AgentStateStore(tmp_path / "events.sqlite3")
    store.append(AgentEvent.create(stream_id="task:task", kind="test", actor="owner", idempotency_key="event"))
    class BusyConnection:
        def set_progress_handler(self, *_args):
            pass
        def execute(self, *_args):
            raise sqlite3.OperationalError("database is locked")
        def close(self):
            pass
    monkeypatch.setattr(agent_events, "connect_sqlite", lambda *_args, **_kwargs: BusyConnection())
    with pytest.raises(TimeoutError, match="event lookup time limit"):
        store.has_exact_event("task:task", "test", {}, actor="owner")


@pytest.mark.parametrize("profile", ["minimal", "compact", "standard"])
def test_recovery_timeout_survives_work_and_mcp_projection(profile):
    from local_ai_hub.response_budget import budget_response
    from local_ai_hub.response_protocol import project_response

    raw = {"success": False, "status": "needs_agent", "work_id": "work-1", "requires_primary_review": True,
           "task_barrier_status": "pending_finalization", "task_barrier_error": "finalization_event_lookup_timeout",
           "summary": "detail " * 1000}
    projected = project_response(raw, profile=profile, return_fields=["summary"], max_output_tokens=64)
    result = budget_response(projected, profile=profile, max_tokens=128)
    assert result["success"] is False
    assert result["requires_primary_review"] is True
    assert result["task_barrier_status"] == "pending_finalization"
    assert result["task_barrier_error"] == "finalization_event_lookup_timeout"


def test_empty_journal_with_pending_barrier_requires_agent(tmp_path, monkeypatch):
    root = init_repo(tmp_path)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    original_recover = WorkOrchestrator._recover
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts(),
                            verification_store=SimpleNamespace(task_store=tasks))
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60,
                                                   coordination_id=coordination)
        lease = orch.fencing_store.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60,
                                           attempt=attempt, coordination_id=coordination)
        tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner", fencing_store=orch.fencing_store,
                                           lease=lease, attempt=attempt, paths=["a.txt"])
        orch.fencing_store.release(lease)
        orch.fencing_store.release_attempt(attempt)
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)",
                        ("work-1", str(root), "change", "executing", json.dumps({"task_id": "task"}),
                         "{}", 0, time.time(), time.time()))
        original_recover(orch)
        with closing(orch._connect()) as con:
            row = con.execute("SELECT state,result_json FROM work_orders WHERE work_id='work-1'").fetchone()
        assert row["state"] == "needs_agent"
        assert "barrier requires reconciliation" in json.loads(row["result_json"])["error"]
        assert "_pending_fenced_work" in tasks.get(task.task_id).checkpoint.state_data
    finally:
        orch.close()


@pytest.mark.parametrize("tampered", [False, True])
@pytest.mark.parametrize("mode", ["bounded", "execute"])
def test_recovery_rolls_back_journal_and_closes_adopted_barrier(tmp_path, monkeypatch, tampered, mode):
    root = init_repo(tmp_path)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    original_recover = WorkOrchestrator._recover
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts(),
                            verification_store=SimpleNamespace(task_store=tasks))
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60,
                                                   coordination_id=coordination)
        lease = orch.fencing_store.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60,
                                           attempt=attempt, coordination_id=coordination)
        tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner", fencing_store=orch.fencing_store,
                                           lease=lease, attempt=attempt, paths=["a.txt"])
        orch.fencing_store.release(lease)
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)",
                        ("work-1", str(root), "change", "executing", json.dumps({"task_id": "task", "mode": mode}),
                         "{}", 0, time.time(), time.time()))
        journal = []
        orch._apply_patch(root, "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n",
                          "work-1", journal, attempt=attempt, allowed_paths=["a.txt"])
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "new"
        if tampered:
            (root / "a.txt").write_text("foreign\n", encoding="utf-8")
        orch.fencing_store.release_attempt(attempt)
        original_recover(orch)
        with closing(orch._connect()) as con:
            row = con.execute("SELECT state,result_json FROM work_orders WHERE work_id='work-1'").fetchone()
        state = tasks.get(task.task_id).checkpoint.state_data
        assert state["mutation_generation"] == 3
        if tampered:
            assert row["state"] == "needs_agent"
            if mode == "bounded":
                result = json.loads(row["result_json"])
                assert result["outcome_unknown"] is True
                assert result["rollback_status"] == "reconciliation_required"
                assert result["task_barrier_status"] == "reconciliation_required"
                assert orch.continue_work("work-1", "continue")["success"] is False
            assert (root / "a.txt").read_text(encoding="utf-8").strip() == "foreign"
            assert "_pending_fenced_work" in state
            assert orch._load_journal("work-1")
        else:
            assert row["state"] == ("needs_agent" if mode == "bounded" else "queued")
            if mode == "bounded":
                assert json.loads(row["result_json"])["outcome_unknown"] is True
            assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
            assert "_pending_fenced_work" not in state
    finally:
        orch.close()


def test_windows_recovery_blocks_junction_swap_during_restore(tmp_path, monkeypatch):
    import os
    import subprocess
    from local_ai_hub import work_orchestrator as work_module
    from local_ai_hub.process_utils import hidden_run_kwargs

    if os.name != "nt":
        pytest.skip("Windows junctions")
    root = init_repo(tmp_path)
    source, saved, outside = root / "src", root / "saved-src", tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    (source / "file.py").write_text("old\n", encoding="utf-8")
    (outside / "file.py").write_text("new\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "src/file.py"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@e",
                    "commit", "-qm", "add source"], check=True)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    original_recover = WorkOrchestrator._recover
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts(),
                            verification_store=SimpleNamespace(task_store=tasks))
    swapped, blocked = [], []
    original_write = work_module._write_windows_rollback_file
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60, coordination_id=coordination)
        lease = orch.fencing_store.acquire(str(root), "writer", ["src/file.py"], ttl_seconds=60, attempt=attempt, coordination_id=coordination)
        tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner", fencing_store=orch.fencing_store,
                                           lease=lease, attempt=attempt, paths=["src/file.py"])
        orch.fencing_store.release(lease)
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)",
                        ("work-1", str(root), "change", "executing", json.dumps({"task_id": "task", "mode": "bounded"}),
                         "{}", 0, time.time(), time.time()))
        journal = []
        orch._apply_patch(root, "--- a/src/file.py\n+++ b/src/file.py\n@@ -1 +1 @@\n-old\n+new\n",
                          "work-1", journal, attempt=attempt, allowed_paths=["src/file.py"])
        orch.fencing_store.release_attempt(attempt)
        def swap_before_write(fd, data):
            if not swapped and not blocked:
                try:
                    source.rename(saved)
                except OSError:
                    blocked.append(True)
                else:
                    made = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(source), str(outside)],
                                          capture_output=True, text=True, timeout=10, **hidden_run_kwargs())
                    if made.returncode != 0:
                        saved.rename(source)
                        pytest.skip("junction creation unavailable")
                    swapped.append(True)
            return original_write(fd, data)
        monkeypatch.setattr(work_module, "_write_windows_rollback_file", swap_before_write)
        original_recover(orch)
        assert blocked and not swapped
        assert (outside / "file.py").read_text(encoding="utf-8") == "new\n"
        assert (source / "file.py").read_text(encoding="utf-8") == "old\n"
        assert "_pending_fenced_work" not in tasks.get(task.task_id).checkpoint.state_data
        assert orch._load_journal("work-1") == []
        with closing(orch._connect()) as con:
            assert con.execute("SELECT state FROM work_orders WHERE work_id='work-1'").fetchone()["state"] == "needs_agent"
    finally:
        orch.close()
        if swapped:
            os.rmdir(source)
            saved.rename(source)


@pytest.mark.parametrize("corrupt", [False, True])
def test_empty_journal_with_completed_rollback_is_reconciled(tmp_path, monkeypatch, corrupt):
    root = init_repo(tmp_path)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    original_recover = WorkOrchestrator._recover
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts(),
                            verification_store=SimpleNamespace(task_store=tasks))
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60, coordination_id=coordination)
        lease = orch.fencing_store.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt, coordination_id=coordination)
        args = dict(root=str(root), owner="owner", fencing_store=orch.fencing_store, lease=lease, attempt=attempt, paths=["a.txt"])
        tasks._begin_fenced_work_mutation(task.task_id, **args)
        orch.fencing_store.release(lease)
        payload = {"task_id": "task", "mode": "bounded", "allowed_paths": ["a.txt"], "approved_commands": ["git diff --check"]}
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)",
                        ("work-1", str(root), "change", "executing", json.dumps(payload), "{}", 0, time.time(), time.time()))
        journal = []
        orch._apply_patch(root, "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n",
                          "work-1", journal, attempt=attempt, allowed_paths=["a.txt"])
        lease = orch.fencing_store.acquire(str(root), "rollback", ["a.txt"], ttl_seconds=60,
                                           attempt=attempt, coordination_id=coordination)
        args["lease"] = lease
        def rollback_then_crash():
            orch._rollback(root, journal)
            assert orch._record_recovery_checkpoint("work-1", journal)
            orch._clear_journal("work-1")
            raise RuntimeError("simulated crash before barrier release")
        with pytest.raises(RuntimeError, match="simulated crash"):
            tasks._finish_fenced_work_mutation(task.task_id, rollback=True, finalize=rollback_then_crash, **args)
        if corrupt:
            with closing(orch._connect()) as con:
                result = json.loads(con.execute("SELECT result_json FROM work_orders WHERE work_id='work-1'").fetchone()[0])
                result["_recovery_checkpoint"]["journal_sha256"] = "invalid"
                con.execute("UPDATE work_orders SET result_json=? WHERE work_id='work-1'", (json.dumps(result),))
        orch.fencing_store.release(lease)
        orch.fencing_store.release_attempt(attempt)
        original_recover(orch)
        with closing(orch._connect()) as con:
            row = con.execute("SELECT state,result_json FROM work_orders WHERE work_id='work-1'").fetchone()
        assert row["state"] == "needs_agent"
        if not corrupt:
            result = json.loads(row["result_json"])
            assert result["outcome_unknown"] is True
            assert result["requires_primary_review"] is True
        else:
            result = json.loads(row["result_json"])
            assert result["outcome_unknown"] is True
            assert result["task_barrier_status"] == "reconciliation_required"
            resumed = orch.continue_work("work-1", "continue")
            assert resumed["success"] is False
            assert "_pending_fenced_work" in tasks.get(task.task_id).checkpoint.state_data
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
        assert ("_pending_fenced_work" in tasks.get(task.task_id).checkpoint.state_data) is corrupt
    finally:
        orch.close()


def test_terminal_handoff_with_pending_barrier_is_reported(tmp_path, monkeypatch):
    root = init_repo(tmp_path)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    original_recover = WorkOrchestrator._recover
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts(),
                            verification_store=SimpleNamespace(task_store=tasks))
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60, coordination_id=coordination)
        lease = orch.fencing_store.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt, coordination_id=coordination)
        tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner", fencing_store=orch.fencing_store,
                                           lease=lease, attempt=attempt, paths=["a.txt"])
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)",
                        ("work-1", str(root), "change", "needs_agent", json.dumps({"task_id": "task"}),
                         json.dumps({"summary": "handoff"}), 0, time.time(), time.time()))
        orch.fencing_store.release(lease)
        orch.fencing_store.release_attempt(attempt)
        original_recover(orch)
        with closing(orch._connect()) as con:
            row = con.execute("SELECT state,result_json FROM work_orders WHERE work_id='work-1'").fetchone()
        assert row["state"] == "needs_agent"
        assert json.loads(row["result_json"])["task_barrier_status"] == "reconciliation_required"
        assert "_pending_fenced_work" in tasks.get(task.task_id).checkpoint.state_data
    finally:
        orch.close()


@pytest.mark.parametrize("clear_journal,tampered,corrupt", [(False, False, False), (True, False, False),
                                                             (True, True, False), (False, False, True)])
def test_terminal_handoff_recovery_preserves_postimage(tmp_path, monkeypatch, clear_journal, tampered, corrupt):
    root = init_repo(tmp_path)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    original_recover = WorkOrchestrator._recover
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts(),
                            verification_store=SimpleNamespace(task_store=tasks))
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60, coordination_id=coordination)
        lease = orch.fencing_store.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt, coordination_id=coordination)
        tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner", fencing_store=orch.fencing_store,
                                           lease=lease, attempt=attempt, paths=["a.txt"])
        orch.fencing_store.release(lease)
        journal = []
        orch._apply_patch(root, "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n",
                          "work-1", journal, attempt=attempt, allowed_paths=["a.txt"])
        manifest = orch._handoff_postimage_manifest(journal)
        if corrupt:
            manifest["files"][0]["sha256"] = "f" * 64
        if clear_journal:
            orch._clear_journal("work-1", attempt=attempt)
        payload = {"task_id": "task", "mode": "bounded", "allowed_paths": ["a.txt"], "approved_commands": ["git diff --check"]}
        result = {"summary": "handoff", "task_barrier_status": "pending_finalization", "_task_handoff_manifest": manifest}
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)", ("work-1", str(root), "change", "needs_agent",
                        json.dumps(payload), json.dumps(result), 0, time.time(), time.time()))
        if tampered:
            (root / "a.txt").write_text("foreign\n", encoding="utf-8")
        orch.fencing_store.release_attempt(attempt)
        original_recover(orch)
        with closing(orch._connect()) as con:
            row = con.execute("SELECT state,result_json FROM work_orders WHERE work_id='work-1'").fetchone()
        assert row["state"] == "needs_agent"
        assert json.loads(row["result_json"])["task_barrier_status"] == ("reconciliation_required" if tampered or corrupt else "released")
        assert ("_pending_fenced_work" in tasks.get(task.task_id).checkpoint.state_data) is (tampered or corrupt)
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == ("foreign" if tampered else "new")
    finally:
        orch.close()


@pytest.mark.parametrize("drift", ["none", "file", "generation", "late_event", "event_timeout"])
def test_terminal_status_reconciles_only_matching_finalization(tmp_path, monkeypatch, drift):
    root = init_repo(tmp_path)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    original_recover = WorkOrchestrator._recover
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts(),
                            verification_store=SimpleNamespace(task_store=tasks))
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60, coordination_id=coordination)
        lease = orch.fencing_store.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt, coordination_id=coordination)
        guarded = tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner", fencing_store=orch.fencing_store,
                                                     lease=lease, attempt=attempt, paths=["a.txt"])
        identity = {**guarded.checkpoint.state_data["_pending_fenced_work"],
                    "mutation_generation": guarded.checkpoint.state_data["mutation_generation"]}
        orch.fencing_store.release(lease)
        journal = []
        orch._apply_patch(root, "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n",
                          "work-1", journal, attempt=attempt, allowed_paths=["a.txt"])
        manifest = orch._handoff_postimage_manifest(journal)
        payload = {"task_id": "task", "mode": "bounded", "allowed_paths": ["a.txt"], "approved_commands": ["git diff --check"]}
        result = {"summary": "handoff", "task_barrier_status": "pending_finalization",
                  "_task_handoff_manifest": manifest, "_task_handoff_identity": identity}
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)", ("work-1", str(root), "change", "needs_agent",
                        json.dumps(payload), json.dumps(result), 0, time.time(), time.time()))
        if drift == "late_event":
            from local_ai_hub.agent_events import AgentEvent
            from local_ai_hub.sqlite_support import connect_sqlite
            with closing(connect_sqlite(tasks.state_store.db_path)) as con:
                con.execute("BEGIN IMMEDIATE")
                for index in range(4001):
                    tasks.state_store.append_in_transaction(con, AgentEvent.create(
                        stream_id="task:task", kind="test.noise", payload={},
                        actor="owner", idempotency_key=f"noise-{index}"))
                con.commit()
        lease = orch.fencing_store.acquire(str(root), "finish", ["a.txt"], ttl_seconds=60, attempt=attempt, coordination_id=coordination)
        tasks._finish_fenced_work_mutation(task.task_id, root=str(root), owner="owner", fencing_store=orch.fencing_store,
            lease=lease, attempt=attempt, paths=["a.txt"], rollback=False, finalize=lambda: orch._clear_journal("work-1"))
        orch.fencing_store.release(lease)
        orch.fencing_store.release_attempt(attempt)
        if drift == "file":
            (root / "a.txt").write_text("foreign\n", encoding="utf-8")
        elif drift == "generation":
            tasks.advance_mutation_generation(task.task_id)
        elif drift == "event_timeout":
            original_lookup = tasks.state_store.has_exact_event
            def timeout(*_args, **_kwargs):
                raise TimeoutError("event lookup time limit exceeded")
            monkeypatch.setattr(tasks.state_store, "has_exact_event", timeout)
        original_recover(orch)
        with closing(orch._connect()) as con:
            row = con.execute("SELECT result_json FROM work_orders WHERE work_id='work-1'").fetchone()
        expected = ("released" if drift in {"none", "late_event"} else
                    "pending_finalization" if drift == "event_timeout" else "reconciliation_required")
        recovered = json.loads(row["result_json"])
        assert recovered["task_barrier_status"] == expected
        if drift == "event_timeout":
            assert recovered["task_barrier_error"] == "finalization_event_lookup_timeout"
            assert orch._recovery_retry_requested is True
            assert orch.get("work-1", profile="compact")["task_barrier_error"] == "finalization_event_lookup_timeout"
            monkeypatch.setattr(tasks.state_store, "has_exact_event", original_lookup)
            original_recover(orch)
            with closing(orch._connect()) as con:
                retried = json.loads(con.execute("SELECT result_json FROM work_orders WHERE work_id='work-1'").fetchone()[0])
            assert retried["task_barrier_status"] == "released"
            assert "task_barrier_error" not in retried
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == ("foreign" if drift == "file" else "new")
    finally:
        orch.close()


def test_terminal_cleanup_never_erases_journal_while_task_barrier_pending(tmp_path, monkeypatch):
    root = init_repo(tmp_path)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    original_recover = WorkOrchestrator._recover
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts(),
                            verification_store=SimpleNamespace(task_store=tasks))
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60, coordination_id=coordination)
        lease = orch.fencing_store.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt, coordination_id=coordination)
        tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner", fencing_store=orch.fencing_store,
                                           lease=lease, attempt=attempt, paths=["a.txt"])
        orch.fencing_store.release(lease)
        journal = []
        orch._apply_patch(root, "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n",
                          "work-1", journal, attempt=attempt, allowed_paths=["a.txt"])
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)", ("work-1", str(root), "change", "complete",
                        json.dumps({"task_id": "task"}), "{}", 0, time.time(), time.time()))
        orch.fencing_store.release_attempt(attempt)
        monkeypatch.setattr(orch, "_report_terminal_task_barriers", lambda: None)
        original_recover(orch)
        assert orch._load_journal("work-1")
        assert "_pending_fenced_work" in tasks.get(task.task_id).checkpoint.state_data
    finally:
        orch.close()


def test_terminal_cleanup_does_not_race_live_attempt(tmp_path, monkeypatch):
    root = init_repo(tmp_path)
    original_recover = WorkOrchestrator._recover
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(orch, "_schedule_recovery_retry", lambda: None)
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60, coordination_id=coordination)
        journal = []
        orch._apply_patch(root, "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n",
                          "work-1", journal, attempt=attempt, allowed_paths=["a.txt"])
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)", ("work-1", str(root), "change", "complete",
                        "{}", "{}", 0, time.time(), time.time()))
        original_recover(orch)
        assert orch._load_journal("work-1")
        assert orch._recovery_retry_requested is True
        orch.fencing_store.release_attempt(attempt)
    finally:
        orch.close()


def test_terminal_recovery_retries_after_live_attempt(tmp_path, monkeypatch):
    root = init_repo(tmp_path)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts(),
                            verification_store=SimpleNamespace(task_store=tasks))
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60, coordination_id=coordination)
        lease = orch.fencing_store.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt, coordination_id=coordination)
        tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner", fencing_store=orch.fencing_store,
                                           lease=lease, attempt=attempt, paths=["a.txt"])
        orch.fencing_store.release(lease)
        with closing(orch._connect()) as con:
            con.execute("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)", ("work-1", str(root), "change", "needs_agent",
                        json.dumps({"task_id": "task"}), "{}", 0, time.time(), time.time()))
        orch._recovery_retry_requested = False
        orch._report_terminal_task_barriers()
        assert orch._recovery_retry_requested is True
        orch.fencing_store.release_attempt(attempt)
        orch._report_terminal_task_barriers()
        with closing(orch._connect()) as con:
            row = con.execute("SELECT result_json FROM work_orders WHERE work_id='work-1'").fetchone()
        assert json.loads(row["result_json"])["task_barrier_status"] == "reconciliation_required"
    finally:
        orch.close()


def test_terminal_recovery_scans_past_first_bounded_batch(tmp_path, monkeypatch):
    root = init_repo(tmp_path)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts(),
                            verification_store=SimpleNamespace(task_store=tasks))
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "z-work", "worker", ttl_seconds=60, coordination_id=coordination)
        lease = orch.fencing_store.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt, coordination_id=coordination)
        tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner", fencing_store=orch.fencing_store,
                                           lease=lease, attempt=attempt, paths=["a.txt"])
        orch.fencing_store.release(lease)
        orch.fencing_store.release_attempt(attempt)
        with closing(orch._connect()) as con:
            rows = [(f"a-{n:04}", str(root), "done", "complete", "{}", "{}", 0, time.time(), time.time()) for n in range(128)]
            rows.append(("z-work", str(root), "change", "needs_agent", json.dumps({"task_id": "task"}), "{}", 0, time.time(), time.time()))
            con.executemany("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)", rows)
        orch._report_terminal_task_barriers()
        assert orch._recovery_retry_requested is True
        with closing(orch._connect()) as con:
            assert json.loads(con.execute("SELECT result_json FROM work_orders WHERE work_id='z-work'").fetchone()[0]) == {}
        orch._report_terminal_task_barriers()
        with closing(orch._connect()) as con:
            result = json.loads(con.execute("SELECT result_json FROM work_orders WHERE work_id='z-work'").fetchone()[0])
        assert result["task_barrier_status"] == "reconciliation_required"
    finally:
        orch.close()


def test_terminal_cleanup_scans_past_first_bounded_batch(tmp_path, monkeypatch):
    root = init_repo(tmp_path)
    original_recover = WorkOrchestrator._recover
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    orch = WorkOrchestrator({}, tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(orch, "_schedule_recovery_retry", lambda: None)
    try:
        coordination = orch._coordination_id(root)
        attempt = orch.fencing_store.claim_attempt(str(root), "z-work", "worker", ttl_seconds=60, coordination_id=coordination)
        journal = []
        orch._apply_patch(root, "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n",
                          "z-work", journal, attempt=attempt, allowed_paths=["a.txt"])
        orch.fencing_store.release_attempt(attempt)
        with closing(orch._connect()) as con:
            rows = [(f"a-{n:04}", str(root), "done", "complete", "{}", "{}", 0, time.time(), time.time()) for n in range(128)]
            rows.append(("z-work", str(root), "change", "complete", "{}", "{}", 0, time.time(), time.time()))
            con.executemany("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?)", rows)
        original_recover(orch)
        assert orch._load_journal("z-work")
        assert orch._recovery_retry_requested is True
        original_recover(orch)
        assert orch._load_journal("z-work") == []
    finally:
        orch.close()
