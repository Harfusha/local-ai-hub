import pytest

from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStatus
from local_ai_hub.repo_plan.agent_bridge import bind_plan_execution
from local_ai_hub.repo_plan.workspace import RepoPlanWorkspace
from test_repo_plan_verified_flow import environment


def test_second_binding_with_stale_plan_revision_is_rejected(environment):
    root, tasks, _, _, _, _, _, _ = environment
    tasks.transition("execution_a", TaskStatus.CANCELLED, reason="superseded", actor="agent_a", idempotency_key="dispose-a")
    for name in ("b", "c"):
        tasks.create(GoalContract(goal="Verify real work", acceptance_criteria=["tests pass"]),
            context=ScopeContext(repository_id=str(root), session_id=f"session_{name}"),
            actor=f"agent_{name}", repo_root=str(root), task_id=f"execution_{name}")
    before = RepoPlanWorkspace(root).get_plan("plan_work")["file_revision"]
    assert bind_plan_execution(tasks, root=str(root), task_id="execution_b", plan_id="plan_work",
                               plan_task_id="task_work", expected_revision=before)["success"] is True
    after = RepoPlanWorkspace(root).get_plan("plan_work")["file_revision"]
    assert after != before
    with pytest.raises(ValueError, match="expected_revision conflicts"):
        bind_plan_execution(tasks, root=str(root), task_id="execution_c", plan_id="plan_work",
                            plan_task_id="task_work", expected_revision=before)
