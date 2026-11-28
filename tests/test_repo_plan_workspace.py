"""Unit tests for RepoPlanWorkspace and Kanban board view."""

import pytest

from local_ai_hub.repo_plan.schema_validation import (
    RepoPlanConflictError,
    RepoPlanNotFoundError,
    RepoPlanValidationError,
)

from local_ai_hub.repo_plan.workspace import (
    RepoPlanWorkspace,
)


@pytest.fixture
def workspace(tmp_path):
    ws = RepoPlanWorkspace(tmp_path)
    ws.init_workspace()
    return tmp_path, ws


def test_init_workspace(tmp_path):
    """Test initialization creates workspace files and canonical project identity."""
    ws = RepoPlanWorkspace(tmp_path)
    res = ws.init_workspace()
    assert res["success"] is True
    assert (tmp_path / ".local-ai-hub" / "README.md").exists()
    assert (tmp_path / ".local-ai-hub" / ".gitignore").exists()
    assert (tmp_path / ".local-ai-hub" / "project.json").is_file()
    assert (tmp_path / ".local-ai-hub" / "plans").is_dir()


def test_concurrent_workspace_initialization_publishes_one_project_identity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import json
    import subprocess

    from local_ai_hub.project_identity import project_scope_id

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "--allow-empty", "-m", "initial"],
        check=True, capture_output=True,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: RepoPlanWorkspace(root).init_workspace(), range(2)))

    manifest = json.loads((root / ".local-ai-hub" / "project.json").read_text(encoding="utf-8"))
    assert all(result["success"] for result in results)
    assert project_scope_id(root) == manifest["project_id"]


def test_independent_processes_initialize_one_project_identity(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "--allow-empty", "-m", "initial"],
        check=True, capture_output=True,
    )
    source = str(Path(__file__).resolve().parents[1] / "src")
    script = (
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[2]); "
        "from local_ai_hub.repo_plan.workspace import RepoPlanWorkspace; "
        "from local_ai_hub.project_identity import project_scope_id; "
        "print('ready', flush=True); sys.stdin.readline(); "
        "RepoPlanWorkspace(sys.argv[1]).init_workspace(); print(project_scope_id(sys.argv[1]))"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(root), source],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(2)
    ]
    try:
        assert [process.stdout.readline().strip() for process in processes] == ["ready", "ready"]
        for process in processes:
            process.stdin.write("go\n")
            process.stdin.flush()
        results = [process.communicate(timeout=30) for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()

    manifest = json.loads((root / ".local-ai-hub" / "project.json").read_text(encoding="utf-8"))
    assert all(process.returncode == 0 for process in processes), [stderr for _stdout, stderr in results]
    assert {stdout.strip().splitlines()[-1] for stdout, _stderr in results} == {manifest["project_id"]}


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


def test_list_plans_keeps_other_rows_when_a_plan_disappears_after_read(workspace, monkeypatch):
    root, ws = workspace
    ws.create_plan("plan_alpha", "Alpha")
    ws.create_plan("plan_beta", "Beta")
    read_plan_file = ws.storage.read_plan_file

    def read_and_remove(rel_path):
        plan, revision = read_plan_file(rel_path)
        if plan["id"] == "plan_alpha":
            (root / rel_path).unlink()
        return plan, revision

    monkeypatch.setattr(ws.storage, "read_plan_file", read_and_remove)

    assert [plan["id"] for plan in ws.list_plans(limit=1)] == ["plan_beta"]


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


def test_kanban_board_view_bounds_long_descriptions(workspace):
    _root, ws = workspace
    ws.create_plan("plan_long_description", title="Long Description Plan")
    description = "context " * 600
    ws.edit_task(
        "plan_long_description",
        "task_long",
        title="Long Task",
        description=description,
        work_status="in_progress",
    )

    card = ws.get_board_view(plan_id="plan_long_description", query="task_long")["columns"]["in_progress"][0]

    assert len(card["description"]) == 2048
    assert card["description_truncated"] is True
    assert card["plan_rel_path"] == ".local-ai-hub/plans/plan_long_description.plan.json"
    assert card["plan_file_revision"] == ws.get_plan("plan_long_description")["file_revision"]
