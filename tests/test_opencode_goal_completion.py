from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import CompletionGateError, ConcurrentTaskUpdateError, GoalContract, TaskCheckpoint, TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.verification_rules import complete_task_with_project_rules


@pytest.fixture
def stored_task(tmp_path: Path):
    root = tmp_path / "repository"
    root.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    events = AgentStateStore(state / "agent-state.sqlite3")
    tasks = TaskStore(events)
    receipts = VerificationStore(events, task_store=tasks)
    task = tasks.create(
        GoalContract(goal="fix failing test", acceptance_criteria=("pytest passes",)),
        ScopeContext(task_id="goal-task", session_id="session-1"), task_id="goal-task", actor="agent", repo_root=str(root),
    )
    return root, state, tasks, receipts, task


@pytest.mark.parametrize("criteria", [[], ["other"], ["pytest passes", "extra"], "pytest passes", [""], [False]])
def test_goal_completion_rejects_empty_malformed_or_changed_criteria(stored_task, criteria):
    root, state, tasks, receipts, before = stored_task
    with pytest.raises(CompletionGateError, match="acceptance criteria"):
        complete_task_with_project_rules(
            tasks, receipts, before.task_id, root=root, state_dir=state,
            current_revision="revision", expected_criteria=criteria,
        )
    assert tasks.get(before.task_id) == before


def test_matching_goal_criteria_cannot_override_missing_test_receipt(stored_task):
    root, state, tasks, receipts, before = stored_task
    with pytest.raises(CompletionGateError, match="verification incomplete"):
        complete_task_with_project_rules(
            tasks, receipts, before.task_id, root=root, state_dir=state,
            current_revision="revision", expected_criteria=["pytest passes"],
        )
    assert tasks.get(before.task_id) == before


@pytest.mark.parametrize("binding", [
    None, {}, {"goal": "other", "session_id": "session-1"},
    {"goal": "fix failing test", "session_id": "other"},
    {"goal": "fix failing test", "session_id": "session-1", "extra": True},
    {"goal": "fix failing test", "session_id": None},
])
def test_completion_rejects_invalid_goal_session_binding(stored_task, binding):
    root, state, tasks, receipts, before = stored_task
    with pytest.raises(CompletionGateError, match="binding"):
        complete_task_with_project_rules(
            tasks, receipts, before.task_id, root=root, state_dir=state,
            current_revision="revision", expected_criteria=["pytest passes"], expected_binding=binding,
        )
    assert tasks.get(before.task_id) == before


def test_binding_cannot_skip_criteria(stored_task):
    root, state, tasks, receipts, before = stored_task
    with pytest.raises(CompletionGateError, match="requires acceptance criteria"):
        complete_task_with_project_rules(
            tasks, receipts, before.task_id, root=root, state_dir=state, current_revision="revision",
            expected_binding={"goal": "fix failing test", "session_id": "session-1"},
        )
    assert tasks.get(before.task_id) == before


def test_valid_goal_session_binding_still_requires_real_receipts(stored_task):
    root, state, tasks, receipts, before = stored_task
    with pytest.raises(CompletionGateError, match="verification incomplete"):
        complete_task_with_project_rules(
            tasks, receipts, before.task_id, root=root, state_dir=state,
            current_revision="revision", expected_criteria=["pytest passes"],
            expected_binding={"goal": "fix failing test", "session_id": "session-1"},
        )
    assert tasks.get(before.task_id) == before


def test_binding_completion_rejects_task_change_after_preflight(stored_task, monkeypatch):
    from local_ai_hub import verification_rules

    root, state, tasks, receipts, before = stored_task
    monkeypatch.setattr(verification_rules, "evaluate_project_completion", lambda *a, **k: SimpleNamespace(complete=True))
    complete = tasks.complete
    def mutate_before_commit(task_id, **kwargs):
        current = tasks.get(task_id)
        tasks.checkpoint(task_id, TaskCheckpoint(phase="concurrent change", state_data=dict(current.checkpoint.state_data)), actor="agent")
        return complete(task_id, **kwargs)
    monkeypatch.setattr(tasks, "complete", mutate_before_commit)
    with pytest.raises(ConcurrentTaskUpdateError, match="changed"):
        complete_task_with_project_rules(
            tasks, receipts, before.task_id, root=root, state_dir=state, current_revision="revision",
            expected_criteria=["pytest passes"], expected_binding={"goal": "fix failing test", "session_id": "session-1"},
        )
    assert tasks.get(before.task_id).status.value != "completed"
