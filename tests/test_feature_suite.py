from __future__ import annotations

import ast
import json
import queue
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import __version__
from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.agent_blackboard import BlackboardStore
from local_ai_hub.benchmark import HardwareBenchmarkRunner
from local_ai_hub.commands import CommandBroker
from local_ai_hub.process_utils import hidden_run_kwargs
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.swarm import SwarmCoordinator, SwarmState

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_and_tool_contract():
    assert __version__ == "5.0.0"
    source = (ROOT / "src" / "local_ai_hub" / "mcp_server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    tools = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool" for d in node.decorator_list)
    ]
    assert len(tools) == 7
    assert set(tools) == {
        "local_ai_status", "local_ai_task", "local_ai_repo",
        "local_ai_rag", "local_ai_coord", "local_ai_artifact",
        "local_ai_work",
    }
    release = json.loads((ROOT / "RELEASE.json").read_text(encoding="utf-8"))
    assert release["version"] == "5.0.0"
    assert release["status"] == "production-ready"


def test_call_graph_semantic_diff_integration(tmp_path: Path):
    mod_path = tmp_path / "math_ops.py"
    caller_path = tmp_path / "calc.py"

    mod_path.write_text("def multiply(a: int, b: int) -> int:\n    return a * b\n", encoding="utf-8")
    caller_path.write_text("from math_ops import multiply\n\nres = multiply(2, 3)\n", encoding="utf-8")

    diff = """--- a/math_ops.py
+++ b/math_ops.py
@@ -1,2 +1,2 @@
-def multiply(a: int, b: int) -> int:
+def multiply(a: int, b: int, factor: int) -> int:
-    return a * b
+    return a * b * factor
"""
    engine = DeterministicEngine()
    result = engine.call_graph_diff(tmp_path, diff=diff)
    assert result["success"] is True
    assert len(result["breaking_callers"]) >= 1
    caller_match = [c for c in result["breaking_callers"] if "calc.py" in c["file"]]
    assert len(caller_match) == 1
    assert caller_match[0]["line"] == 3


def test_swarm_orchestrator_lifecycle(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    leases = ScopeLeaseStore(tmp_path)
    agent_state = AgentStateStore(db_path, enabled=True)
    blackboard = BlackboardStore(db_path, state_store=agent_state)
    verifications = VerificationStore(agent_state)
    swarm = SwarmCoordinator(db_path, leases=leases, blackboard=blackboard, verifications=verifications)

    dispatch_res = swarm.dispatch(
        goal="Implement robust logger",
        target_paths=["src/logger.py"],
        root=str(tmp_path),
        author="lead_agent",
    )
    assert dispatch_res["success"] is True
    swarm_id = dispatch_res["swarm_id"]
    assert dispatch_res["state"] == SwarmState.CODING.value

    step1 = swarm.step(swarm_id, role="Coder", action="submit_patch", payload={"patch": "logger code"})
    assert step1["success"] is True
    assert step1["state"] == SwarmState.TESTING.value

    step2 = swarm.step(swarm_id, role="Tester", action="report_test_results", payload={"passed": True, "output": "10 passed"})
    assert step2["success"] is True
    assert step2["state"] == SwarmState.REVIEWING.value

    step3 = swarm.step(swarm_id, role="Reviewer", action="approve", payload={"review": "LGTM"})
    assert step3["success"] is True
    assert step3["state"] == SwarmState.COMPLETED.value
    assert "receipt_id" in step3

    status = swarm.get_status(swarm_id)
    assert status["success"] is True
    assert status["state"] == SwarmState.COMPLETED.value


def test_hardware_benchmark_runner_suite(tmp_path: Path):
    from unittest.mock import MagicMock
    history_file = tmp_path / "benchmarks.json"
    mock_runtime = MagicMock()

    def fake_stream(model, prompt, options=None):
        import time
        time.sleep(0.02)
        yield "token1 "
        yield "token2 "

    mock_runtime.generate_stream.side_effect = fake_stream

    mock_balancer = MagicMock()
    mock_balancer.sample_vram.return_value = {
        "vram_used_mb": 2048,
        "vram_total_mb": 8192,
        "utilization_pct": 25.0,
    }

    runner = HardwareBenchmarkRunner(
        benchmarks_path=history_file,
        runtime=mock_runtime,
        vram_balancer=mock_balancer,
    )

    res = runner.run(model="fast-test-model", prompt="def test():", num_tokens=2)
    assert res["success"] is True
    assert res["ttft_ms"] > 0
    assert res["tokens_per_second"] > 0
    assert 0 <= res["hardware_score"] <= 100
    assert history_file.exists()

    summary = runner.get_latest_summary()
    assert summary["available"] is True
    assert summary["hardware_score"] == res["hardware_score"]


def test_command_streaming_and_sse_events(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3", enabled=True)
    sub_q = state_store.subscribe(maxsize=100)

    events_received: list[AgentEvent] = []

    def log_cb(stream: str, chunk: str) -> None:
        ev = AgentEvent.create(
            stream_id="cmd:test-stream",
            kind="command.log",
            payload={"stream": stream, "chunk": chunk},
            actor="test-runner",
        )
        state_store.append(ev)

    cmd_broker = CommandBroker({}, artifacts=None, repo_state=None)
    task_id = "streaming-test-task"
    task = SimpleNamespace(
        task_id=task_id,
        checkpoint=SimpleNamespace(
            state_data={"worktree": {"worktree_path": str(tmp_path), "success": True}}
        ),
    )

    class TaskStore:
        def get(self, requested_task_id: str) -> object | None:
            return task if requested_task_id == task_id else None

    cmd_broker.set_task_store(TaskStore())
    res = cmd_broker.run(
        f'"{sys.executable}" -c "print(\'live stream line 1\'); print(\'live stream line 2\')"',
        cwd=str(tmp_path),
        task_id=task_id,
        force=True,
        log_callback=log_cb,
    )
    assert res["success"] is True

    while not sub_q.empty():
        events_received.append(sub_q.get_nowait())

    cmd_logs = [e for e in events_received if e.kind == "command.log"]
    chunks = [e.payload.get("chunk", "") for e in cmd_logs]
    combined = "".join(chunks)
    assert "live stream line 1" in combined
    assert "live stream line 2" in combined
