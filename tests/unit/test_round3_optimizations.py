import pytest
from unittest.mock import MagicMock
from pathlib import Path
from local_ai_hub.repo_state import RepoStateTracker
from local_ai_hub.services import LocalAIServices

def make_services(state_dir: Path):
    config = {
        "server": {"state_dir": str(state_dir)},
        "cache": {},
        "models": {"fast_code": "test-fast", "heavy_code": "test-heavy"},
    }
    return LocalAIServices(
        config=config,
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
    )

def test_repo_state_ignores_venv_and_tool_envs():
    tracker = RepoStateTracker({})
    assert ".venv" in tracker.non_git_ignore_dirs
    assert "tool-envs" in tracker.non_git_ignore_dirs
    assert "site-packages" in tracker.non_git_ignore_dirs

def test_plan_create_auto_prefix(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".local-ai.toml").write_text("[project]\nentry_points = []\n", encoding="utf-8")
    
    services = make_services(tmp_path / "state")
    
    # 1. Un-prefixed plan_id
    res = services.plan_create(root=str(repo), plan_id="my-custom-plan", title="Test Plan")
    assert res["success"] is True
    assert res["plan_id"].startswith("plan_")
    assert "my-custom-plan" in res["plan_id"]

    # 2. Empty plan_id
    res2 = services.plan_create(root=str(repo), plan_id="", title="Auto ID Plan")
    assert res2["success"] is True
    assert res2["plan_id"].startswith("plan_")

def test_plan_task_edit_status_alias(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".local-ai.toml").write_text("[project]\nentry_points = []\n", encoding="utf-8")
    
    services = make_services(tmp_path / "state")
    p = services.plan_create(
        root=str(repo),
        plan_id="plan_sample",
        title="Sample",
        tasks={"task_1": {"title": "Task 1", "work_status": "planned"}}
    )
    rev = p["file_revision"]
    
    # Edit task with 'status' instead of 'work_status'
    edit_res = services.plan_task_edit(
        root=str(repo),
        plan_id="plan_sample",
        task_id="task_1",
        task_data={"status": "in_progress"},
        expected_revision=rev
    )
    assert edit_res["success"] is True
    assert edit_res["task"]["work_status"] == "in_progress"

    # Edit task with un-prefixed task_id
    rev2 = edit_res["file_revision"]
    edit_res2 = services.plan_task_edit(
        root=str(repo),
        plan_id="plan_sample",
        task_id="1", # should map to task_1
        task_data={"work_status": "completed"},
        expected_revision=rev2
    )
    assert edit_res2["success"] is True
    assert edit_res2["task"]["work_status"] == "completed"
