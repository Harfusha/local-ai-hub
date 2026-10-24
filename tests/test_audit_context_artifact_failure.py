"""Recovery remains explicit when storage fails or an omitted goal changes."""
from dataclasses import replace

from local_ai_hub.agent_context import CompiledContext
from local_ai_hub.context_delivery import attach_compiled_context_artifact, prepare_context_delivery


def test_storage_failure_removes_stale_pointers_and_private_goal():
    class Unavailable:
        def put(self, *args, **kwargs):
            raise OSError("storage unavailable")

    value = {
        "success": True, "task_context_artifact_id": "stale-artifact",
        "task_context": {
            "success": True, "complete": True, "text": "selected facts",
            "artifact_id": "stale-artifact", "_omitted_task_goal": "private full goal",
            "omitted_sections": ["task_goal"],
        },
    }
    attached = attach_compiled_context_artifact(
        value, Unavailable(), root="root", coordination_id="repository", session_id="session",
    )
    assert "task_context_artifact_id" not in attached
    assert "artifact_id" not in attached["task_context"]
    assert "_omitted_task_goal" not in attached["task_context"]
    assert attached["success"] is False
    assert attached["task_context"]["complete"] is False
    delivered = prepare_context_delivery(attached, 3200)
    assert delivered["success"] is False
    assert delivered["complete"] is False
    assert delivered["next_action"] == "request_smaller_context"
    assert "unavailable" in delivered["error"]
    assert value["task_context"]["_omitted_task_goal"] == "private full goal"


def test_omitted_goal_changes_context_identity_without_inflating_inline_budget():
    first = CompiledContext(elements=[], estimated_tokens=0, token_budget=10,
                            truncated=True, omitted_task_goal="first full goal")
    second = replace(first, omitted_task_goal="second full goal")
    assert first.etag() != second.etag()
    assert first.text() == second.text() == ""
    assert first.token_budget == second.token_budget == 10
