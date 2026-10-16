from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskCheckpoint, TaskStore
from local_ai_hub.agent_verification import CompletionResult
from local_ai_hub.verification_rules import complete_task_with_project_rules


@pytest.mark.parametrize("damage", ["missing_checkpoint", "boolean_generation", "negative_generation", "float_generation", "string_generation", "invalid_state_data"])
def test_completion_rejects_invalid_checkpoint_after_receipt_verification(tmp_path: Path, damage: str):
    root = tmp_path / "repo"
    root.mkdir()
    task_id = "checkpoint-fence"
    state_data = {"repo_root": str(root), "repository_revision": "rev-1", "mutation_generation": 1}
    task = SimpleNamespace(
        task_id=task_id, owner="owner", context=SimpleNamespace(repository_id=str(root)),
        contract=GoalContract(goal="checkpoint fence", acceptance_criteria=("tests",)),
        checkpoint=TaskCheckpoint(state_data=state_data),
    )
    current = SimpleNamespace(**vars(task))
    if damage == "missing_checkpoint":
        del current.checkpoint
    elif damage == "invalid_state_data":
        current.checkpoint = SimpleNamespace(state_data=[])
    else:
        invalid = {"boolean_generation": True, "negative_generation": -1,
                   "float_generation": 1.0, "string_generation": "1"}[damage]
        current.checkpoint = TaskCheckpoint(state_data={**state_data, "mutation_generation": invalid})

    class Tasks:
        preflight_completion_response_budget = TaskStore.preflight_completion_response_budget

        def __init__(self):
            self.task = task
            self.completed = False
            self.receipts_checked = False

        def get(self, key):
            assert key == task_id
            return self.task

        def complete(self, *_args, **_kwargs):
            self.completed = True
            return "completed"

    tasks = Tasks()

    class Receipts:
        task_store = tasks

        def completion(self, key, **_kwargs):
            # The receipt boundary accepts the initial snapshot; the task
            # projection changes before the real completion fence rereads it.
            tasks.receipts_checked = True
            tasks.task = current
            return CompletionResult(key, True, (), (), (), ())

    with pytest.raises(CompletionGateError):
        complete_task_with_project_rules(
            tasks, Receipts(), task_id, root=root, state_dir=tmp_path / "state",
            current_revision="rev-1", actor="owner",
        )

    assert tasks.receipts_checked is True
    assert tasks.completed is False
