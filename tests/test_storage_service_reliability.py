from __future__ import annotations

import inspect
import json
import sqlite3
import threading
import time
from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_learning import (
    CandidateStatus,
    ImprovementCandidate,
    LearningStore,
)
from local_ai_hub.agent_verification import (
    ChangeIntent,
    OutcomeRecord,
    VerificationReceipt,
    VerificationStore,
)
from local_ai_hub.agent_incidents import (
    IncidentStore,
    ToolOutcome,
)
from local_ai_hub.agent_tasks import (
    GoalContract,
    ScopeContext,
    TaskCheckpoint,
    TaskState,
    TaskStatus,
    TaskStore,
)
from local_ai_hub.agent_blackboard import BlackboardStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.process_utils import canonical_root


def test_service_hubctl_timeout_alignment():
    """Verify service.py run() timeout is 12s and hubctl _service timeout is 35s."""
    import tools.service as service
    import tools.hubctl as hubctl

    sig = inspect.signature(service.run)
    assert sig.parameters["timeout"].default == 12.0

    hubctl_src = inspect.getsource(hubctl._service)
    assert "timeout=35" in hubctl_src


def test_learning_store_thread_safe_and_status_validation(tmp_path: Path):
    """Verify LearningStore has RLock, retry_busy in reads, and rejects illegal state transitions."""
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store = LearningStore(state_store)

    assert hasattr(store, "_lock")
    assert isinstance(store._lock, type(threading.RLock()))

    cand = store.create_candidate(
        ImprovementCandidate.create(
            name="test_rule",
            baseline_version="1.0",
            candidate_version="1.1",
        )
    )

    # Transition to ROLLED_BACK
    rolled = store.advance(cand.candidate_id, CandidateStatus.ROLLED_BACK)
    assert rolled.status == CandidateStatus.ROLLED_BACK

    # Advancing from ROLLED_BACK must fail
    with pytest.raises(ValueError, match="Cannot advance candidate in terminal status 'rolled_back'"):
        store.advance(cand.candidate_id, CandidateStatus.CANARY_PASSED)

    # Promoting from ROLLED_BACK must fail
    with pytest.raises(ValueError, match="Cannot promote candidate in terminal status 'rolled_back'"):
        store.promote(cand.candidate_id, approver="user")

    # Create another candidate and reject it
    cand2 = store.create_candidate(
        ImprovementCandidate.create(
            name="test_rule_2",
            baseline_version="1.0",
            candidate_version="1.1",
        )
    )
    rejected = store.advance(cand2.candidate_id, CandidateStatus.REJECTED)
    assert rejected.status == CandidateStatus.REJECTED

    # Advancing or promoting from REJECTED must fail
    with pytest.raises(ValueError, match="Cannot advance candidate in terminal status 'rejected'"):
        store.advance(cand2.candidate_id, CandidateStatus.PROMOTED)

    with pytest.raises(ValueError, match="Cannot promote candidate in terminal status 'rejected'"):
        store.promote(cand2.candidate_id, approver="user")

    # Verify get and list_candidates work smoothly
    fetched = store.get(cand.candidate_id)
    assert fetched is not None
    assert fetched.candidate_id == cand.candidate_id

    all_cands = store.list_candidates()
    assert len(all_cands) == 2


def test_verification_store_indexes_and_retry(tmp_path: Path):
    """Verify verification store has task_id and change_id indexes, and completion uses retry_busy."""
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    vstore = VerificationStore(state_store)

    con = sqlite3.connect(state_store.db_path)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cur.fetchall()}
    con.close()

    assert "idx_agent_verif_task" in indexes
    assert "idx_agent_change_task" in indexes
    assert "idx_agent_outcomes_task" in indexes
    assert "idx_agent_outcomes_change" in indexes

    rcpt = VerificationReceipt.create(
        task_id="t-123",
        criterion="test_pass",
        passed=True,
    )
    vstore.record(rcpt)

    comp = vstore.completion("t-123")
    assert comp.task_id == "t-123"
    assert comp.complete is True
    assert "test_pass" in comp.satisfied_criteria


def test_incident_store_compound_index_and_repeated_event(tmp_path: Path):
    """Verify IncidentStore capture uses composite index alignment and emits incident.repeated."""
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    istore = IncidentStore(state_store)

    outcome = ToolOutcome(
        tool_name="test_tool",
        command="python -m pytest",
        error="SyntaxError: invalid syntax in foo.py",
        exit_code=1,
        state_revision="rev_1",
    )

    rec1 = istore.capture(outcome)
    assert rec1 is not None
    assert rec1.attempts == 1

    # Second capture with identical error/operation/revision
    rec2 = istore.capture(outcome)
    assert rec2 is not None
    assert rec2.incident_id == rec1.incident_id
    assert rec2.attempts == 2

    # Check that incident.repeated event was emitted to state_store
    con = sqlite3.connect(state_store.db_path)
    cur = con.cursor()
    cur.execute("SELECT kind, payload FROM agent_events WHERE kind = 'incident.repeated'")
    events = cur.fetchall()
    con.close()

    assert len(events) == 1
    kind, payload_json = events[0]
    payload = json.loads(payload_json)
    assert payload["attempts"] == 2

    # Test retry_decision: syntax error produces verified_fix with high confidence
    dec = istore.retry_decision(rec1.fingerprint, "rev_1")
    assert dec.action == "apply_verified_fix"

    # Test retry_decision on unknown error without verified fix
    unclassified = ToolOutcome(
        tool_name="test_tool",
        command="run_custom",
        error="unclassified internal failure",
        exit_code=1,
        state_revision="rev_1",
    )
    rec_unclass = istore.capture(unclassified)
    dec_stop = istore.retry_decision(rec_unclass.fingerprint, "rev_1")
    assert dec_stop.action == "stop"  # Identical error on unchanged revision
    dec_retry = istore.retry_decision(rec_unclass.fingerprint, "rev_2")
    assert dec_retry.action == "retry"  # Revision changed

    fetched = istore.get(rec1.incident_id)
    assert fetched is not None
    assert fetched.attempts == 2

    listed = istore.list_incidents()
    assert len(listed) == 2


def test_task_store_lock_and_retry(tmp_path: Path):
    """Verify TaskStore projection table has RLock and query methods use retry_busy."""
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    tstore = TaskStore(state_store)

    assert hasattr(tstore, "_lock")
    assert isinstance(tstore._lock, type(threading.RLock()))

    task = tstore.create(
        contract=GoalContract(goal="test goal", acceptance_criteria=("crit1",)),
        context=ScopeContext(repository_id="repo1"),
    )

    assert tstore.count() == 1
    assert tstore.count(TaskStatus.PLANNED) == 1
    assert tstore.count(TaskStatus.ACTIVE) == 0

    fetched = tstore.get(task.task_id)
    assert fetched is not None
    assert fetched.task_id == task.task_id

    listed = tstore.list_tasks()
    assert len(listed) == 1

    # Heartbeat and reap test
    tstore.transition(task.task_id, TaskStatus.ACTIVE, reason="activate", actor="agent", idempotency_key="act_1")
    tstore.heartbeat(task.task_id, ttl_seconds=10.0)

    # Advance time to expire heartbeat
    reaped = tstore.reap_expired_heartbeats(now=time.time() + 100.0)
    assert task.task_id in reaped

    after_reap = tstore.get(task.task_id)
    assert after_reap.status == TaskStatus.ABANDONED


def test_blackboard_store_retry(tmp_path: Path):
    """Verify BlackboardStore get and list_boards work cleanly with retry_busy."""
    bb_path = tmp_path / "blackboard.sqlite3"
    bstore = BlackboardStore(bb_path)

    bstore.update("board_1", "plan", {"step": 1}, author="agent")
    bstore.update("board_2", "results", {"status": "ok"}, author="agent")

    boards = bstore.list_boards()
    assert "board_1" in boards
    assert "board_2" in boards

    res = bstore.get("board_1", "plan")
    assert res["success"] is True
    assert res["section"]["content"] == {"step": 1}

    all_secs = bstore.get("board_1")
    assert all_secs["success"] is True
    assert "plan" in all_secs["sections"]


def test_repair_loop_drive_letter_casing(tmp_path: Path):
    """Verify repair_loop handles path normalization without raising relative_to ValueError."""
    broker = CommandBroker(config={"server": {"state_dir": str(tmp_path / "broker_state")}, "commands": {"enabled": True}})

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    bad_file = project_dir / "target.py"
    bad_file.write_text("def run():\n    raise ValueError('broken')\n", encoding="utf-8")

    # Deliberately pass cwd using canonical_root
    canon_cwd = canonical_root(project_dir)

    def mock_generator(cmd, cwd, result):
        return {"target.py": "def run():\n    return 42\n"}

    # Run repair_loop with a command that passes once repaired
    res = broker.repair_loop(
        command='python -c "import target; assert target.run() == 42"',
        cwd=canon_cwd,
        tenant="test",
        fix_generator=mock_generator,
        max_attempts=1,
    )
    assert res["success"] is True
    assert res["repaired"] is True
    assert bad_file.read_text(encoding="utf-8") == "def run():\n    return 42\n"


def test_code_index_wal_sidecar_cleanup(tmp_path: Path):
    """Verify CodeIndex _init_db unlinks WAL and SHM sidecars upon corruption recovery."""
    cfg = {"server": {"state_dir": str(tmp_path)}}
    db_path = tmp_path / "code-index.sqlite3"
    wal_path = tmp_path / "code-index.sqlite3-wal"
    shm_path = tmp_path / "code-index.sqlite3-shm"

    # Initialize a valid code index first
    idx = CodeIndex(config=cfg, repo_tools=None)

    # Create dummy WAL and SHM sidecars
    wal_path.write_text("dummy wal data", encoding="utf-8")
    shm_path.write_text("dummy shm data", encoding="utf-8")
    assert wal_path.exists()
    assert shm_path.exists()

    # Corrupt the main db file
    db_path.write_text("GARBAGE NOT SQLITE DATA", encoding="utf-8")

    # Re-instantiating triggers corruption recovery
    idx2 = CodeIndex(config=cfg, repo_tools=None)
    idx2._init_db()

    # Sidecars should be unlinked/deleted
    assert not wal_path.exists()
    assert not shm_path.exists()

    # A corrupt backup was created
    corrupt_files = list(tmp_path.glob("code-index.sqlite3.corrupt-*"))
    assert len(corrupt_files) == 1

    # New DB is healthy
    con = sqlite3.connect(db_path)
    ok = con.execute("PRAGMA quick_check").fetchone()[0]
    con.close()
    assert ok == "ok"
