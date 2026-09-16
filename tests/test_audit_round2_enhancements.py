from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore, SwarmPubSub
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskStore, TaskStatus
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.agent_context import ContextCompiler, ContextRequest
from local_ai_hub.agent_blackboard import BlackboardStore
from local_ai_hub.features import FeatureSet
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.sqlite_support import connect_sqlite


def test_speculative_draft_reads_text_key(tmp_path: Path):
    """A1: speculative_draft must read 'text' (not 'response') from _generate() result."""
    from local_ai_hub.services import LocalAIServices

    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {"fast_code": "test-model", "heavy_code": "test-heavy"},
    }
    services = LocalAIServices(
        config=config,
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
    )
    # Mock _generate to return the standard dict with "text"
    services._generate = MagicMock(return_value={
        "success": True,
        "text": "def add(a, b):\n    return a + b\n",
        "duration_ms": 42,
    })

    result = services.speculative_draft({"task": "add function"}, tenant="test")
    assert result["success"] is True
    assert result["draft"] == "def add(a, b):\n    return a + b\n"


def test_swarm_pubsub_publish_appends_to_state_store(tmp_path: Path):
    """A2: SwarmPubSub.publish must call append() not non-existent append_event()."""
    db_path = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()

    pubsub = SwarmPubSub(state_store=state_store)
    res = pubsub.publish("test_channel", message={"msg": "hello"}, sender="agent_1")
    assert res["success"] is True

    # Verify the event was actually persisted in agent_events table
    con = connect_sqlite(db_path)
    try:
        rows = con.execute("SELECT kind, payload FROM agent_events WHERE stream_id='pubsub:test_channel'").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "pubsub_message"
    finally:
        con.close()


def test_features_coord_and_task_actions_include_new():
    """A4 & D1: features.py must declare all supported actions."""
    features = FeatureSet({
        "features": {"tasks": True, "coord": True, "agent_os": True, "repo": True},
        "models": {"fast_code": "dummy"},
    })
    coord_acts = features.supported_coord_actions()
    assert "task_sync" in coord_acts
    assert "task_zombie_reap" in coord_acts
    assert "task_cleanup_worktree" in coord_acts

    repo_acts = features.supported_repo_actions()
    assert "reachability_dead_code" in repo_acts
    assert "mutation_test" in repo_acts
    assert "type_stubs" in repo_acts
    assert "skeletonize" in repo_acts

    task_acts = features.supported_task_actions()
    assert "complete_code" in task_acts


def test_memory_cascade_delete_and_compact_linking(tmp_path: Path):
    """B1: delete() and reap_expired() must cascade clean agent_entity_relations."""
    db_path = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    store = MemoryStore(state_store=state_store)

    # Record two memory items with relations
    rec1 = store.record(MemoryRecord.create(kind=MemoryKind.DECISION, scope=AgentScope.SESSION, key="key1", value="val1"))
    rec2 = store.record(MemoryRecord.create(kind=MemoryKind.DECISION, scope=AgentScope.SESSION, key="key2", value="val2"))
    store.record_relation(rec1.record_id, "relates_to", rec2.record_id)

    # Check relation exists
    relations = store.find_relations(source_entity=rec1.record_id)
    assert len(relations) >= 1

    # Delete rec1 -> relation must be cleaned
    deleted = store.delete(rec1.record_id)
    assert deleted is True
    relations_after = store.find_relations(source_entity=rec1.record_id)
    assert len(relations_after) == 0


def test_task_completion_gate_checks_receipt_freshness(tmp_path: Path):
    """B2: Task completion must reject expired verification receipts."""
    db_path = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    task_store = TaskStore(state_store=state_store)
    verif_store = VerificationStore(state_store=state_store, task_store=task_store)

    contract = GoalContract(goal="Pass tests", acceptance_criteria=("all_passed",))
    context = ScopeContext(task_id="test")
    task = task_store.create(contract=contract, context=context)
    task_store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="k1")
    task_store.transition(task.task_id, TaskStatus.VERIFYING, reason="verify", actor="agent", idempotency_key="k2")

    # Create an expired receipt (expires_at in past)
    expired_rcpt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="all_passed",
        passed=True,
        expires_at=time.time() - 100.0,
    )
    verif_store.record(expired_rcpt)
    task_store.add_verification_receipt(task.task_id, "all_passed", expired_rcpt.receipt_id)

    # Attempting to transition to COMPLETED must raise CompletionGateError due to stale receipt
    with pytest.raises(CompletionGateError) as excinfo:
        task_store.transition(task.task_id, TaskStatus.COMPLETED, reason="done", actor="agent", idempotency_key="k3")
    assert "expired" in str(excinfo.value).lower()


def test_lease_release_scoped_wait_cleanup(tmp_path: Path):
    """B3: Releasing one lease must not clear wait graph for other active paths held by tenant."""
    leases = ScopeLeaseStore(state_dir=tmp_path)
    claim_a = leases.claim("tenant1", str(tmp_path), ["file_a.py"], ttl_seconds=600)
    claim_b = leases.claim("tenant1", str(tmp_path), ["file_b.py"], ttl_seconds=600)

    # Add wait records for both paths
    con = leases._connect()
    try:
        now = time.time()
        _, root_id = leases._root(str(tmp_path))
        con.execute("INSERT INTO lease_waits VALUES (?, ?, ?, ?, ?)", ("waiter1", "tenant1", root_id, "file_a.py", now))
        con.execute("INSERT INTO lease_waits VALUES (?, ?, ?, ?, ?)", ("waiter2", "tenant1", root_id, "file_b.py", now))
        con.commit()
    finally:
        con.close()

    # Release ONLY lease A
    leases.release("tenant1", lease_id=claim_a["lease_id"])

    # Waiter for file_a.py is cleaned, but waiter for file_b.py must REMAIN
    con = leases._connect()
    try:
        rows = con.execute("SELECT requested_path FROM lease_waits WHERE blocked_by='tenant1'").fetchall()
        paths = [r[0] for r in rows]
        assert "file_a.py" not in paths
        assert "file_b.py" in paths
    finally:
        con.close()


def test_blackboard_in_compiled_context(tmp_path: Path):
    """B4: ContextCompiler must include shared blackboard state in candidates."""
    db_path = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    blackboard = BlackboardStore(db_path=db_path)
    compiler = ContextCompiler(state_store=state_store, blackboard=blackboard)

    # Update global blackboard
    blackboard.update("global", "system_status", {"load": "normal", "healthy": True}, author="monitor")

    res = compiler.compile(ContextRequest(task_id="test_task"))
    element_sources = [el.source_kind for el in res.elements]
    assert "blackboard" in element_sources
    assert any("system_status" in el.content for el in res.elements)


def test_agent_scope_parse_and_contract_tolerance():
    """AgentScope.parse handles aliases and never crashes GoalContract.from_dict."""
    assert AgentScope.parse("code") == AgentScope.TASK
    assert AgentScope.parse("project") == AgentScope.REPOSITORY
    assert AgentScope.parse("repo") == AgentScope.REPOSITORY
    assert AgentScope.parse("workspace") == AgentScope.WORKTREE
    assert AgentScope.parse("user") == AgentScope.GLOBAL
    assert AgentScope.parse("UNKNOWN_RANDOM", default=AgentScope.TASK) == AgentScope.TASK

    # GoalContract accepts 'code' scope gracefully
    contract = GoalContract.from_dict({"goal": "Refactor parser", "scope": "code"})
    assert contract.scope == AgentScope.TASK


def test_lease_claim_auto_resolves_absolute_paths(tmp_path: Path):
    """ScopeLeaseStore.claim seamlessly converts absolute paths within root to relative paths."""
    leases = ScopeLeaseStore(state_dir=tmp_path)
    file_path = tmp_path / "src" / "worker.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("# worker", encoding="utf-8")

    # Claiming with an absolute path must succeed and store relative path
    claim_res = leases.claim("agent_worker", str(tmp_path), [str(file_path)])
    assert claim_res["success"] is True
    assert claim_res["paths"] == ["src/worker.py"]

