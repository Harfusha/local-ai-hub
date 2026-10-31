from __future__ import annotations

from local_ai_hub import mcp_server
from local_ai_hub.response_budget import _fit_to_tokens, budget_response


def test_coord_description_advertises_planning_actions_when_supported() -> None:
    desc = mcp_server._desc_coord()
    assert "plan_get" in desc
    assert "plan_list" in desc
    assert "plan_board_view" in desc
    assert "plan_task_edit" in desc


def test_fit_to_tokens_preserves_plan_and_file_revision() -> None:
    payload = {
        "success": True,
        "plan": {
            "id": "plan_test",
            "title": "Test Plan",
            "tasks": {"task_1": {"title": "Task 1", "work_status": "planned"}},
        },
        "file_revision": "abc123rev",
        "rel_path": ".local-ai-hub/plans/plan_test.plan.json",
    }
    # With a small max_tokens that forces fitting, plan and file_revision must not be silently dropped while returning success
    fitted = _fit_to_tokens(dict(payload), 50, protected_keys=("plan", "file_revision"))
    # When fitted exceeds budget, it retains protected keys for deterministic budget rejection
    assert "plan" in fitted or fitted.get("success") is False
    assert "file_revision" in fitted or fitted.get("success") is False


def test_plan_get_budget_projection_does_not_silently_drop_body() -> None:
    plan_dict = {
        "id": "plan_mock",
        "title": "Mock Plan",
        "tasks": {f"task_{i}": {"title": f"Task {i}", "work_status": "planned"} for i in range(100)},
    }
    raw = {
        "success": True,
        "plan": plan_dict,
        "file_revision": "deadbeef" * 8,
        "rel_path": ".local-ai-hub/plans/mock.plan.json",
        "git_branch": "master",
        "git_head": "12345678" * 5,
        "request_id": "req_mock",
    }
    compacted = mcp_server._compact(raw, "coord", extra_fields=["plan", "file_revision", "rel_path"])
    # If the response budget was too small for 100 tasks, it must return an explicit budget error rather than silent success: true with empty body
    if not compacted.get("success"):
        assert "error" in compacted
        assert "budget" in compacted["error"].lower() or "too small" in compacted["error"].lower()
    else:
        assert "plan" in compacted
        assert "file_revision" in compacted
