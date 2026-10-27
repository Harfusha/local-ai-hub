"""Unit tests for RepoPlanWorkspace and Kanban board view."""

import pytest

from local_ai_hub.repo_plan import (
    RepoPlanConflictError,
    RepoPlanValidationError,
    RepoPlanWorkspace,
)


@pytest.fixture
def workspace(tmp_path):
    ws = RepoPlanWorkspace(tmp_path)
    ws.init_workspace()
    return tmp_path, ws


def test_init_workspace(tmp_path):
    """Test initialization creates directories, README, and .gitignore."""
    ws = RepoPlanWorkspace(tmp_path)
    res = ws.init_workspace()
    assert res["success"] is True
    assert (tmp_path / ".local-ai-hub" / "README.md").exists()
    assert (tmp_path / ".local-ai-hub" / ".gitignore").exists()
    assert (tmp_path / ".local-ai-hub" / "plans").is_dir()


def test_workspace_rejects_symlinked_plan_directory_outside_repo(tmp_path):
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    local_hub_dir = root / ".local-ai-hub"
    local_hub_dir.mkdir()
    try:
        (local_hub_dir / "plans").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")

    with pytest.raises(RepoPlanValidationError):
        RepoPlanWorkspace(root)


def test_create_get_list_plans(workspace):
    """Test creating, getting, and listing plans."""
    tmp_path, ws = workspace

    res_create = ws.create_plan(
        plan_id="plan_alpha",
        title="Alpha Plan",
        description="First plan",
        default_target_ref="refs/heads/master",
    )
    assert res_create["success"] is True
    assert res_create["plan_id"] == "plan_alpha"

    # Get plan
    res_get = ws.get_plan("plan_alpha")
    assert res_get["success"] is True
    assert res_get["plan"]["title"] == "Alpha Plan"

    # List plans
    plans = ws.list_plans()
    assert len(plans) == 1
    assert plans[0]["id"] == "plan_alpha"
    assert plans[0]["title"] == "Alpha Plan"


def test_update_plan_preserves_file_identity(workspace):
    """Test updating title preserves plan ID and does not rename file."""
    tmp_path, ws = workspace
    ws.create_plan(plan_id="plan_beta", title="Old Title")

    res_update = ws.update_plan("plan_beta", title="New Title", description="Updated desc")
    assert res_update["success"] is True
    assert res_update["plan"]["title"] == "New Title"

    # Original file path still exists and contains new title
    plan_file = tmp_path / ".local-ai-hub" / "plans" / "plan_beta.plan.json"
    assert plan_file.exists()

    loaded = ws.get_plan("plan_beta")
    assert loaded["plan"]["title"] == "New Title"


def test_task_operations_in_workspace(workspace):
    """Test adding, editing, and deleting tasks within a plan."""
    tmp_path, ws = workspace
    ws.create_plan(plan_id="plan_tasks", title="Task Plan")

    # 1. Add task
    res_add = ws.edit_task(
        "plan_tasks",
        "task_1",
        title="Task One",
        description="First task",
        kind="code",
        work_status="planned",
        acceptance_criteria=["Criterion 1"],
    )
    assert res_add["success"] is True
    assert res_add["task"]["title"] == "Task One"

    # 2. Edit task
    res_edit = ws.edit_task(
        "plan_tasks",
        "task_1",
        work_status="in_progress",
        next_action="Reviewing code",
    )
    assert res_edit["success"] is True
    assert res_edit["task"]["work_status"] == "in_progress"
    assert res_edit["task"]["next_action"] == "Reviewing code"

    # 3. Delete task
    with pytest.raises(RepoPlanConflictError, match="active or unintegrated"):
        ws.delete_task("plan_tasks", "task_1")
    ws.edit_task("plan_tasks", "task_1", work_status="planned")
    res_del = ws.delete_task("plan_tasks", "task_1")
    assert res_del["success"] is True

    plan_now = ws.get_plan("plan_tasks")
    assert "task_1" not in plan_now["plan"]["tasks"]


def test_kanban_board_view(workspace):
    """Test scoped Kanban board projection with columns, counts, and indicators."""
    tmp_path, ws = workspace

    ws.create_plan("plan_board", title="Kanban Board Plan")
    ws.edit_task(
        "plan_board",
        "task_planned",
        title="Planned Task",
        work_status="planned",
    )
    ws.edit_task(
        "plan_board",
        "task_progress",
        title="Active Task",
        work_status="in_progress",
        next_action="Working",
    )
    ws.edit_task(
        "plan_board",
        "task_blocked",
        title="Blocked Task",
        work_status="blocked",
        blocker="Awaiting spec",
    )

    board = ws.get_board_view(plan_id="plan_board")
    assert board["success"] is True
    assert board["total_items"] == 3
    assert len(board["columns"]["planned"]) == 1
    assert len(board["columns"]["in_progress"]) == 1
    assert len(board["columns"]["blocked"]) == 1

    # Check card details
    blocked_card = board["columns"]["blocked"][0]
    assert blocked_card["blocker"] == "Awaiting spec"
    assert blocked_card["saved_to_file"] is True


def test_legacy_board_adoption(workspace):
    """Test adopting SQLite board items into a file-backed plan."""
    tmp_path, ws = workspace
    ws.create_plan("plan_adopted", title="Adopted Plan")

    legacy_items = [
        {"item_id": "item_123", "title": "Legacy Item 1", "status": "planned"},
        {"item_id": "item_456", "title": "Legacy Item 2", "status": "in_progress"},
    ]

    res = ws.adopt_legacy_board_items("plan_adopted", legacy_items)
    assert res["success"] is True
    assert res["adopted_count"] == 2

    plan = ws.get_plan("plan_adopted")
    tasks = plan["plan"]["tasks"]
    assert "task_item_123" in tasks
    assert "task_item_456" in tasks
    assert tasks["task_item_456"]["work_status"] == "in_progress"
