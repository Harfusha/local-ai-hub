from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_context import (
    CompiledContext,
    ContextCompiler,
    ContextElement,
    ContextRequest,
    KnowledgeLink,
)
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore


@pytest.fixture
def compiler(tmp_path: Path) -> ContextCompiler:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    verif_store = VerificationStore(state_store, task_store=task_store)

    task_store.create(
        GoalContract(goal="Compile feature", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-1"),
        task_id="task-1",
    )
    verif_store.record(
        VerificationReceipt.create(
            task_id="task-1",
            criterion="tests",
            passed=True,
            details={"output": "all passed"},
        )
    )

    comp = ContextCompiler(
        state_store=state_store,
        task_store=task_store,
        verification_store=verif_store,
    )
    comp.link(
        source_id="rec-1",
        target_id="src/changed.py",
        relationship="modifies",
        path="src/changed.py",
    )
    comp.link(
        source_id="rec-2",
        target_id="src/other.py",
        relationship="modifies",
        path="src/other.py",
    )
    return comp


def test_compiler_prefers_fresh_task_evidence_within_budget(compiler: ContextCompiler):
    result = compiler.compile(ContextRequest(task_id="task-1", token_budget=80))
    assert result.estimated_tokens <= 80
    assert len(result.elements) > 0
    assert result.elements[0].source_kind == "verification_receipt"


def test_change_invalidates_only_linked_records(compiler: ContextCompiler):
    invalidated_count = compiler.invalidate({"src/changed.py"}, "rev-2")
    assert invalidated_count == 1
    # Check that other link remains valid
    active_links = compiler.get_active_links("src/other.py")
    assert len(active_links) == 1
    assert compiler.get_active_links("src/changed.py") == []
