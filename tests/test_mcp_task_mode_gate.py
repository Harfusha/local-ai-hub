from local_ai_hub import mcp_server
from local_ai_hub.operational_mode import set_operational_mode


def test_gaming_defers_mcp_inference_with_bounded_retry(tmp_path, monkeypatch):
    set_operational_mode(tmp_path, "gaming")
    monkeypatch.setattr(mcp_server, "CFG", {"server": {"state_dir": str(tmp_path)}})
    calls = []
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: calls.append(args))

    result = mcp_server.local_ai_task(action="delegate", task="summarize")

    assert result["success"] is False
    assert result["terminal"] is False
    assert result["retryable"] is True
    assert 0 < result["retry_after_seconds"] <= 10
    assert calls == []


def test_gaming_allows_cheap_artifact_read(tmp_path, monkeypatch):
    set_operational_mode(tmp_path, "gaming")
    monkeypatch.setattr(mcp_server, "CFG", {"server": {"state_dir": str(tmp_path)}})
    calls = []
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: calls.append(args) or {"success": True, "items": []})

    result = mcp_server.local_ai_artifact(action="list")

    assert result["success"] is True
    assert calls and calls[0][0] == "/api/artifact/list"


def test_maintenance_blocks_agent_action_but_preserves_job_status(tmp_path, monkeypatch):
    set_operational_mode(tmp_path, "maintenance")
    monkeypatch.setattr(mcp_server, "CFG", {"server": {"state_dir": str(tmp_path)}})
    calls = []

    def post(path, payload, **kwargs):
        calls.append((path, payload))
        return {"success": True, "state": "completed", "job_id": payload["job_id"]}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    blocked = mcp_server.local_ai_task(action="reason", task="do work")
    status = mcp_server.local_ai_task(action="status", job_id="existing-job")

    assert blocked["success"] is False
    assert blocked["terminal"] is False
    assert blocked["retryable"] is True
    assert status["success"] is True
    assert len(calls) == 1
    assert calls[0][0] == "/api/async-jobs"
    assert calls[0][1]["action"] == "status"
    assert calls[0][1]["job_id"] == "existing-job"
