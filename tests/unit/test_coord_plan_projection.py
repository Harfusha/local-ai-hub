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


def test_plan_task_edit_budget_rejection_keeps_mutation_ack_and_revision() -> None:
    raw = {
        "success": True,
        "mutation_applied": True,
        "plan_id": "plan_large",
        "task_id": "task_large",
        "file_revision": "revision-after-write",
        "task": {
            "title": "Large task",
            "description": "description " * 3000,
            "next_action": "next action " * 2000,
            "acceptance_criteria": [f"criterion {i} " * 100 for i in range(10)],
        },
    }

    compacted = mcp_server._compact(raw, "coord", extra_fields=[
        "plan", "plans", "file_revision", "plan_id", "rel_path", "git_branch",
        "git_head", "board", "columns", "items", "tasks",
    ])

    assert compacted["success"] is False
    assert "budget" in compacted["error"].lower() or "too small" in compacted["error"].lower()
    assert compacted["mutation_applied"] is True
    assert compacted["task_id"] == "task_large"
    assert compacted["plan_id"] == "plan_large"
    assert compacted["file_revision"] == "revision-after-write"


def test_plan_board_view_projection_retains_required_fields() -> None:
    raw = {
        "success": True,
        "project_root": "C:/fake/repo",
        "git_branch": "master",
        "git_head": "abcdef123456",
        "plan_filter": "plan_test",
        "columns": {
            "planned": [{"task_id": "t1", "title": "Task 1", "work_status": "planned"}],
            "ready": [],
            "in_progress": [],
            "blocked": [],
            "source_ready": [],
            "done": [],
        },
        "counts": {"planned": 1, "ready": 0, "in_progress": 0, "blocked": 0, "source_ready": 0, "done": 0},
        "total_items": 1,
    }
    compacted = mcp_server._compact(raw, "coord", extra_fields=[
        "plan", "plans", "file_revision", "plan_id", "rel_path", "git_branch", "git_head",
        "board", "columns", "items", "tasks",
        "project_root", "counts", "total_items", "plan_filter", "plan_task_id",
    ])
    assert compacted.get("success") is True
    assert compacted.get("project_root") == "C:/fake/repo"
    assert compacted.get("counts") == raw["counts"]
    assert compacted.get("total_items") == 1
    assert "columns" in compacted


def test_plan_get_wire_budget_error_preserves_identity() -> None:
    rejection = {
        "success": False,
        "error": "Plan response incomplete; request a larger budget or read the plan source in bounded slices.",
        "terminal": True,
        "retryable": False,
        "plan_id": "plan_audit",
        "file_revision": "rev1234567890abcdef",
        "rel_path": ".local-ai-hub/plans/audit.plan.json",
    }
    content, structured = mcp_server._build_mcp_budget_payload(
        "local_ai_coord",
        {"action": "plan_get", "plan_id": "plan_audit", "max_response_tokens": 512},
        rejection,
    )
    assert structured.get("plan_id") == "plan_audit"
    assert structured.get("file_revision") == "rev1234567890abcdef"
    assert structured.get("rel_path") == ".local-ai-hub/plans/audit.plan.json"

