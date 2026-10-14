import subprocess
import time
from pathlib import Path
import pytest

from local_ai_hub.swarm import SwarmCoordinator, execute_swarm_dag


def _init_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True, capture_output=True)
    (repo / "tracked.txt").write_text("initial version\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True, capture_output=True)
    return repo


def test_swarm_dag_executes_parallel_steps(tmp_path: Path):
    coordinator = SwarmCoordinator(tmp_path / "swarm.sqlite")
    
    execution_order = []
    
    def step_a():
        time.sleep(0.05)
        execution_order.append("A")
        return {"success": True, "output": "A_done"}

    def step_b():
        time.sleep(0.05)
        execution_order.append("B")
        return {"success": True, "output": "B_done"}

    def step_c():
        execution_order.append("C")
        return {"success": True, "output": "C_done"}

    steps = [
        {"id": "step_a", "fn": step_a, "depends_on": []},
        {"id": "step_b", "fn": step_b, "depends_on": []},
        {"id": "step_c", "fn": step_c, "depends_on": ["step_a", "step_b"]},
    ]

    res = coordinator.execute_dag(steps)
    assert res["success"] is True
    assert set(res["completed_steps"]) == {"step_a", "step_b", "step_c"}
    # step_c must run after step_a and step_b
    assert execution_order[-1] == "C"


def test_swarm_dag_rollback_on_failure(tmp_path: Path):
    repo = _init_git_repo(tmp_path)
    coordinator = SwarmCoordinator(tmp_path / "swarm.sqlite")

    def modifying_step():
        (repo / "tracked.txt").write_text("corrupted content\n", encoding="utf-8")
        return {"success": True}

    def failing_step():
        return {"success": False, "error": "intentional failure"}

    steps = [
        {"id": "s1", "fn": modifying_step, "depends_on": []},
        {"id": "s2", "fn": failing_step, "depends_on": ["s1"]},
    ]

    res = coordinator.execute_dag(steps, worktree_path=repo)
    assert res["success"] is False
    assert res["rolled_back"] is True
    assert "s2" in res["failed_steps"]
    # Check that tracked.txt was restored to initial version
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "initial version\n"
