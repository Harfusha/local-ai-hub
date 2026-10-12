from __future__ import annotations

import json
from pathlib import Path

from local_ai_hub.agent_consistency import AgentConsistencyGuard, ConsistencyRequest
from local_ai_hub.agent_context import ContextCompiler, ContextRequest
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.config import load_config
from local_ai_hub.repo_tools import RepositoryTools


def _safety_fixture(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        '[hardware]\nprofile="cpu"\n',
        encoding="utf-8",
    )
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory = MemoryStore(state)
    guard = AgentConsistencyGuard(
        RepositoryTools(load_config(str(config_path))), memory_store=memory
    )
    compiler = ContextCompiler(state_store=state, memory_store=memory)
    consistency_request = ConsistencyRequest(
        root=str(root), task_id="task-memory-safety", tenant="tenant-a", query="reuse service"
    )
    context_request = ContextRequest(
        task_id="task-memory-safety", root=str(root), tenant="tenant-a", token_budget=1200
    )
    return root, memory, guard, compiler, consistency_request, context_request


def test_unconfirmed_guard_proposals_are_not_delivered_as_context(tmp_path: Path):
    _, memory, guard, compiler, request, context_request = _safety_fixture(tmp_path)

    finding = guard.record_finding(
        request,
        finding={
            "summary": "Model narrative: UserService may be reusable",
            "raw_source": "raw source must not persist",
            "chat": "chat transcript must not enter context",
            "token": "secretvalue",
        },
        evidence_ids=("evidence-only-is-not-approval",),
    )
    reuse = guard.record_reuse_decision(
        request, candidate_id="reuse-1", decision="accepted", evidence_ids=("evidence-2",)
    )
    unknown = guard.record_unknown(request, claim="unsupported claim", evidence_ids=("evidence-3",))
    rejected = guard.record_rejected_approach(
        request, approach="new endpoint", reason="existing service may fit", evidence_ids=("evidence-4",)
    )

    records = (finding, reuse, unknown, rejected)
    assert all(record is not None for record in records)
    assert all(record.status is MemoryStatus.CANDIDATE for record in records)
    assert memory.count() == 4
    assert "Model narrative" not in compiler.compile(context_request).text()
    assert "raw source" not in compiler.compile(context_request).text()
    assert "chat transcript" not in compiler.compile(context_request).text()
    persisted = json.dumps([record.to_dict() for record in records])
    assert "secretvalue" not in persisted
    assert "raw source must not persist" not in persisted
    assert "chat transcript must not enter context" not in persisted


def test_only_explicitly_approved_guard_decision_is_confirmed(tmp_path: Path):
    _, _, guard, compiler, request, context_request = _safety_fixture(tmp_path)

    evidence_only = guard.record_decision(
        request, decision="reuse", reason="token=secretvalue", evidence_ids=("evidence-5",)
    )
    approved = guard.record_decision(
        request, decision="reuse UserService", reason="operator approved", approved=True
    )

    assert evidence_only is not None and evidence_only.status is MemoryStatus.CANDIDATE
    assert approved is not None and approved.status is MemoryStatus.CONFIRMED
    context = compiler.compile(context_request).text()
    assert "reuse UserService" in context
    assert "token=secretvalue" not in context


def test_manual_active_memory_stays_eligible_for_context(tmp_path: Path):
    root, memory, _, compiler, _, context_request = _safety_fixture(tmp_path)
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="operator-fact",
        value="Keep the established API contract",
        status=MemoryStatus.ACTIVE,
        provenance={"root": str(root), "tenant": "tenant-a"},
    )

    saved = memory.record(record)

    assert saved.status is MemoryStatus.ACTIVE
    assert "Keep the established API contract" in compiler.compile(context_request).text()
