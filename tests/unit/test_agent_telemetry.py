import tempfile
from pathlib import Path
import pytest

from local_ai_hub.agent_telemetry import AgentTelemetryRecorder
from local_ai_hub.mcp_instrumentation import _project_minimal_agent_response


def test_agent_telemetry_recorder():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "agents.jsonl"
        recorder = AgentTelemetryRecorder(log_path=log_file)

        # Record events across multiple agents
        recorder.record(agent="antigravity", tool="run_command", action="exec", profile="minimal", outcome="allow", tokens_est=50)
        recorder.record(agent="codex", tool="edit_file", action="edit", profile="full", outcome="allow", tokens_est=120)
        recorder.record(agent="antigravity", tool="read_file", action="read", profile="compact", outcome="deny", tokens_saved_est=400)

        # Query all
        all_events = recorder.query(limit=10)
        assert len(all_events) == 3

        # Query by agent
        ag_events = recorder.query(agent="antigravity", limit=10)
        assert len(ag_events) == 2

        # Summary
        summary = recorder.summary()
        assert summary["total_events"] == 3
        assert summary["agents"]["antigravity"] == 2
        assert summary["agents"]["codex"] == 1
        assert summary["profiles"]["minimal"] == 1
        assert summary["profiles"]["full"] == 1
        assert summary["outcomes"]["allow"] == 2
        assert summary["outcomes"]["deny"] == 1
        assert summary["total_tokens_saved_est"] == 400


def test_agent_telemetry_modes():
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Mode OFF: zero records, zero disk writes
        off_file = Path(tmpdir) / "off_agents.jsonl"
        rec_off = AgentTelemetryRecorder(log_path=off_file, mode="off")
        res_off = rec_off.record(agent="codex", tool="edit")
        assert res_off["recorded"] is False
        assert rec_off.summary()["total_events"] == 0
        assert not off_file.exists()

        # 2. Mode MINIMAL: in-memory counts active, zero disk write
        min_file = Path(tmpdir) / "min_agents.jsonl"
        rec_min = AgentTelemetryRecorder(log_path=min_file, mode="minimal")
        rec_min.record(agent="antigravity", tool="run_command", outcome="allow", tokens_est=42)
        rec_min.record(agent="antigravity", tool="read_file", outcome="deny", tokens_saved_est=200)

        assert rec_min.summary()["total_events"] == 2
        assert rec_min.summary()["agents"]["antigravity"] == 2
        assert rec_min.summary()["total_tokens_est"] == 42
        assert rec_min.summary()["total_tokens_saved_est"] == 200
        # No file on disk! Zero disk I/O in minimal mode
        assert not min_file.exists()

        # 3. Mode FULL: written to disk with full details
        full_file = Path(tmpdir) / "full_agents.jsonl"
        rec_full = AgentTelemetryRecorder(log_path=full_file, mode="full")
        rec_full.record(agent="opencode", tool="search", details={"query": "find_x"})
        assert full_file.exists()
        events = rec_full.query()
        assert len(events) == 1
        assert events[0]["details"]["query"] == "find_x"


def test_project_minimal_agent_response_task():
    # Verbose task response with massive state_data
    verbose_task_res = {
        "success": True,
        "task": {
            "task_id": "task_123",
            "status": "active",
            "created_at": 12345678,
            "owner": "gemini",
            "context": {"root": "C:\\repo", "repo_id": "abc"},
            "checkpoint": {
                "phase": "coding",
                "next_action": "test",
                "affected_paths": ["a.py"],
                "state_data": {
                    "memory_context": {"items": [{"id": "m1", "content": "big content" * 100}]},
                    "debug_logs": ["line1", "line2"],
                },
            },
        },
        "response_budget": {"requested": 8192, "returned": 1800},
        "request_id": "req_xyz",
    }

    minimal = _project_minimal_agent_response(verbose_task_res, tool="local_ai_coord", action="task_checkpoint")
    assert minimal["success"] is True
    assert minimal["task"]["task_id"] == "task_123"
    assert minimal["task"]["status"] == "active"
    assert minimal["task"]["phase"] == "coding"
    assert minimal["task"]["next_action"] == "test"
    # Ensure bloat is gone
    assert "response_budget" not in minimal
    assert "request_id" not in minimal
    assert "context" not in minimal["task"]
    assert "state_data" not in minimal["task"]


def test_project_minimal_agent_response_search():
    verbose_search = {
        "success": True,
        "matches": [
            {"path": "src/a.py", "line": 10, "score": 0.99, "snippet": "def foo(): pass", "context_lines": [1, 2, 3]},
            {"path": "src/b.py", "line": 20, "score": 0.85, "snippet": "def bar(): pass", "context_lines": [4, 5, 6]},
        ],
        "total_matches": 2,
        "ai_summary": "Found 2 matches in repo",
        "response_budget": {"requested": 8192},
    }

    minimal = _project_minimal_agent_response(verbose_search, tool="local_ai_repo", action="search")
    assert minimal["success"] is True
    assert minimal["count"] == 2
    assert len(minimal["matches"]) == 2
    assert minimal["matches"][0] == {"path": "src/a.py", "line": 10}
    assert "ai_summary" not in minimal
    assert "response_budget" not in minimal
