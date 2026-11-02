"""Unit tests for RepoPlanWorkspace and Kanban board view."""

import json
import pytest

from local_ai_hub.repo_plan import (
    RepoPlanConflictError,
    RepoPlanNotFoundError,
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


def test_adoption_rejects_colliding_normalized_ids_before_creating_plan(workspace):
    root, ws = workspace
    items = [{"item_id": "a/b", "title": "First"}, {"item_id": "a?b", "title": "Second"}]
    with pytest.raises(RepoPlanConflictError, match="collision"):
        ws.adopt_legacy_board_items("plan_adopted", items)
    assert not (root / ".local-ai-hub" / "plans" / "plan_adopted.plan.json").exists()


@pytest.mark.parametrize("item", [
    {"item_id": "blank", "title": "  ", "status": "planned"},
    {"item_id": "unknown", "title": "Legacy", "status": "unrecognized"},
    {"item_id": "invalid", "title": "Legacy", "status": None},
])
def test_adoption_rejects_incomplete_or_unknown_items_without_partial_plan(workspace, item):
    root, ws = workspace
    items = [{"item_id": "valid", "title": "Valid", "status": "planned"}, item]
    with pytest.raises(RepoPlanValidationError):
        ws.adopt_legacy_board_items("plan_adopted", items)
    assert not (root / ".local-ai-hub" / "plans" / "plan_adopted.plan.json").exists()


def test_adoption_does_not_silently_skip_unrelated_existing_task(workspace):
    _root, ws = workspace
    plan = ws.create_plan("plan_adopted", "Existing")
    ws.edit_task("plan_adopted", "task_a_b", title="Unrelated", expected_revision=plan["file_revision"])
    before = ws.get_plan("plan_adopted")
    with pytest.raises(RepoPlanConflictError, match="collision"):
        ws.adopt_legacy_board_items("plan_adopted", [{"item_id": "a/b", "title": "Legacy"}])
    assert ws.get_plan("plan_adopted")["file_revision"] == before["file_revision"]


def test_adopting_same_legacy_item_twice_is_a_noop(workspace):
    _root, ws = workspace
    items = [{"item_id": "a/b", "title": "Legacy"}]
    first = ws.adopt_legacy_board_items("plan_adopted", items)
    second = ws.adopt_legacy_board_items("plan_adopted", items)
    assert first["adopted_count"] == 1
    assert second["adopted_count"] == 0
    assert second["file_revision"] == first["file_revision"]


def test_adoption_preserves_legacy_metadata(workspace):
    _root, ws = workspace
    item = {"item_id": "item-1", "title": "Legacy", "status": "planned", "priority": "high",
            "labels": ["český", "urgent"], "assignee": "Adam", "milestone": "M1",
            "linked_task_id": "task_original", "details": {"description": "detail", "nested": [1, False]},
            "created_at": 1.25, "updated_at": 2.5}
    ws.adopt_legacy_board_items("plan_adopted", [item])
    description = ws.get_plan("plan_adopted")["plan"]["tasks"]["task_item-1"]["description"]
    assert json.loads(description.split("\nLegacy board item JSON:\n", 1)[1]) == item
    assert ws.adopt_legacy_board_items("plan_adopted", [item])["adopted_count"] == 0


def test_adoption_refuses_oversize_legacy_metadata_without_creating_plan(workspace):
    root, ws = workspace
    item = {"item_id": "item-1", "title": "Legacy", "details": {"description": "x" * 40000}}
    with pytest.raises(RepoPlanValidationError):
        ws.adopt_legacy_board_items("plan_adopted", [item])
    assert not (root / ".local-ai-hub" / "plans" / "plan_adopted.plan.json").exists()


def test_adoption_updates_legacy_marker_and_rejects_changed_source(workspace):
    _root, ws = workspace
    created = ws.create_plan("plan_adopted", "Existing")
    old = ws.edit_task("plan_adopted", "task_item-1", title="Legacy", description="Adopted from board item item-1", expected_revision=created["file_revision"])
    item = {"item_id": "item-1", "title": "Legacy", "priority": "high"}
    result = ws.adopt_legacy_board_items("plan_adopted", [item])
    assert result["adopted_count"] == 0 and result["no_op"] is False
    assert result["file_revision"] != old["file_revision"]
    with pytest.raises(RepoPlanConflictError, match="collision"):
        ws.adopt_legacy_board_items("plan_adopted", [{**item, "priority": "low"}])
    assert ws.get_plan("plan_adopted")["file_revision"] == result["file_revision"]


@pytest.mark.parametrize("selected_plan", ["", "plan_bad"])
def test_board_reports_unreadable_plan_instead_of_silent_empty_result(workspace, selected_plan):
    _root, ws = workspace
    ws.create_plan("plan_good", "Existing work")
    ws.edit_task("plan_good", "task_existing", title="Do not duplicate")
    (ws.plans_dir / "plan_bad.plan.json").write_text("{invalid", encoding="utf-8")

    with pytest.raises(RepoPlanValidationError, match="plan_bad"):
        ws.get_board_view(plan_id=selected_plan)


def test_board_can_show_selected_healthy_plan_when_another_plan_is_invalid(workspace):
    _root, ws = workspace
    ws.create_plan("plan_good", "Existing work")
    ws.edit_task("plan_good", "task_existing", title="Do not duplicate")
    (ws.plans_dir / "plan_bad.plan.json").write_text("{invalid", encoding="utf-8")

    board = ws.get_board_view(plan_id="plan_good")
    assert board["success"] is True
    assert board["columns"]["planned"][0]["task_id"] == "task_existing"


def test_board_reports_missing_selected_plan(workspace):
    _root, ws = workspace
    with pytest.raises(RepoPlanNotFoundError):
        ws.get_board_view(plan_id="plan_absent")


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
