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


def test_swarm_dag_preserves_work_on_failure(tmp_path: Path):
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
    assert res["rolled_back"] is False
    assert res["rollback_status"] == "not_performed"
    assert "s2" in res["failed_steps"]
    # Failure must leave callback writes available for owner inspection.
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "corrupted content\n"


def test_swarm_dag_preflights_entire_graph_before_callbacks():
    called = []
    result = execute_swarm_dag([
        {"id": "first", "fn": lambda: called.append("first")},
        {"id": "later", "fn": lambda: called.append("later"), "depends_on": ["missing"]},
    ])
    assert result["success"] is False
    assert called == []
    assert result["step_results"]["first"]["status"] == "not_started"


def test_swarm_dag_rejects_duplicate_ids_and_cycles_before_callbacks():
    called = []
    duplicate = execute_swarm_dag([
        {"id": "same", "fn": lambda: called.append(1)},
        {"id": "same", "fn": lambda: called.append(2)},
    ])
    cycle = execute_swarm_dag([
        {"id": "a", "fn": lambda: called.append("a"), "depends_on": ["b"]},
        {"id": "b", "fn": lambda: called.append("b"), "depends_on": ["a"]},
    ])
    assert duplicate["success"] is False
    assert cycle["success"] is False
    assert called == []


def test_swarm_dag_requires_broker_before_any_command_graph_step():
    called = []
    result = execute_swarm_dag([
        {"id": "callback", "fn": lambda: called.append("ran")},
        {"id": "command", "command": ["python", "-V"], "depends_on": ["callback"]},
    ])
    assert result["success"] is False
    assert called == []
    assert "command broker is required" in result["error"]


def test_swarm_dag_rejects_noop_and_shell_string_steps():
    noop = execute_swarm_dag([{"id": "empty"}])
    shell_string = execute_swarm_dag([{"id": "shell", "command": "echo unsafe"}])
    assert noop["success"] is False
    assert shell_string["success"] is False


def test_swarm_dag_does_not_treat_non_boolean_success_as_success():
    result = execute_swarm_dag([
        {"id": "bad-result", "fn": lambda: {"success": "false"}},
    ])
    assert result["success"] is False


def test_swarm_dag_broker_receives_structured_bounded_command(tmp_path: Path):
    class Broker:
        def __init__(self):
            self.call = None

        def run(self, command, **kwargs):
            self.call = (command, kwargs)
            return {"success": True, "exit_code": 0}

    broker = Broker()
    fence = object()
    cancel_event = object()
    result = execute_swarm_dag(
        [{"id": "cmd", "command": ["python", "-V"]}],
        worktree_path=tmp_path,
        command_broker=broker,
        command_timeout=17,
        task_id="task-1",
        paths=["src/example.py"],
        work_attempt_fence=fence,
        request_cancel_event=cancel_event,
    )
    invocation, kwargs = broker.call
    assert result["success"] is True
    assert invocation.argv == ["python", "-V"]
    assert invocation.shell is False
    assert kwargs["timeout"] == 17
    assert kwargs["task_id"] == "task-1"
    assert kwargs["paths"] == ["src/example.py"]
    assert kwargs["_work_attempt_fence"] is fence
    assert kwargs["request_cancel_event"] is cancel_event


def test_swarm_dag_returns_aborted_steps_explicitly():
    called = []
    result = execute_swarm_dag([
        {"id": "fail", "fn": lambda: {"success": False}},
        {"id": "later", "fn": lambda: called.append("later"), "depends_on": ["fail"]},
    ], max_workers=1)
    assert result["success"] is False
    assert called == []
    assert result["step_results"]["later"]["status"] == "skipped"
    assert result["skipped_steps"] == ["later"]
