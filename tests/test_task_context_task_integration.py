from local_ai_hub import mcp_server
import pytest


@pytest.fixture(autouse=True)
def isolated_task_context_transport(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: OperationalModeSnapshot("active", 1, None))
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)


def test_local_ai_task_loads_unified_context_before_model_call(monkeypatch):
    calls = []

    def post(path, payload, **kwargs):
        calls.append((path, payload))
        if path == "/api/agent-state/context":
            return {
                "success": True,
                "complete": True,
                "task_context": {
                    "success": True, "complete": True,
                    "context_id": "taskctx-1",
                    "etag": "etag-1",
                    "evidence_ids": ["E1"],
                    "text": "Task goal and indexed evidence",
                },
                "text": "Task goal and indexed evidence",
            }
        return {"success": True, "text": "ok"}

    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    result = mcp_server.local_ai_task(
        action="reason",
        task="Assess the change",
        context="Caller notes",
        task_id="task-1",
        root="C:\\repo",
        phase="review",
        focus=["context"],
    )

    assert result["success"] is True
    assert result["task_context_id"] == "taskctx-1"
    assert result["task_context_evidence_ids"] == ["E1"]
    assert calls[0][0] == "/api/agent-state/context"
    assert calls[0][1]["task_id"] == "task-1"
    model_call = next(payload for path, payload in calls if path == "/api/reason")
    assert "Caller notes" in model_call["context"]
    assert "Task goal and indexed evidence" in model_call["context"]
    assert "Task context receipt: context_id=taskctx-1" in model_call["context"]
    assert "evidence_ids=E1" in model_call["context"]


def test_local_ai_task_uses_agent_only_context_without_repository_root(monkeypatch):
    calls = []

    def post(path, payload, **kwargs):
        calls.append((path, payload))
        if path == "/api/agent-state/context":
            assert payload["task_id"] == "task-agent-only"
            return {
                "success": True,
                "complete": True,
                "task_context": {
                    "success": True, "complete": True,
                    "context_id": "taskctx-agent-only",
                    "etag": "etag-agent-only",
                    "evidence_ids": [],
                    "text": "Durable Agent OS task state",
                },
                "text": "Durable Agent OS task state",
            }
        return {"success": True, "text": "ok"}

    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    result = mcp_server.local_ai_task(
        action="reason",
        task="Summarize task state",
        task_id="task-agent-only",
    )

    assert result["success"] is True
    model_call = next(payload for path, payload in calls if path == "/api/reason")
    assert "Durable Agent OS task state" in model_call["context"]


def test_local_ai_task_keeps_unrelated_semantic_paths_as_advisory_warning(monkeypatch):
    def post(path, payload, **kwargs):
        if path == "/api/reason":
            return {"success": True, "text": "Fix src/Calculator.java"}
        return {
            "success": True,
            "complete": True,
            "task_context": {"success": True, "complete": True, "context_id": "taskctx-1", "etag": "etag-1", "text": "facts"},
            "text": "facts",
        }

    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    result = mcp_server.local_ai_task(
        action="reason",
        task="Diagnose src/auth.py",
        task_id="task-2",
        root="C:\\repo",
        changed_paths=["src/auth.py"],
    )

    assert result["success"] is True
    assert result["advisory_only"] is True
    assert result["bypass_reason"] == "unrelated_output"
    assert "quality_warning" in result
