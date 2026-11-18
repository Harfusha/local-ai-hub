from __future__ import annotations

import asyncio
import json

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import validate_operation_output
from local_ai_hub.operational_mode import OperationalModeSnapshot


@pytest.mark.parametrize("degraded", [False, True])
@pytest.mark.parametrize("selector", [{"detail": "brief"}])
def test_readiness_keeps_required_identity_through_live_mcp_projection(monkeypatch, degraded, selector):
    payload = {
        "success": not degraded,
        "degraded": degraded,
        "hub_online": not degraded,
        "version": "4.0.0",
        "ollama_online": True,
        "runtime_stats": {"repo_cache": {"entries": 3}},
    }

    def get(path, **kwargs):
        if path == "/api/capabilities":
            return {
                "success": True,
                "tools": [
                    {"name": f"tool-{index}", "description": "capability detail " * 500}
                    for index in range(32)
                ],
            }
        assert path.startswith(("/api/status", "/api/live/status"))
        return dict(payload)

    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _: OperationalModeSnapshot("active", 0, None))
    monkeypatch.setattr(mcp_server.CLIENT, "get", get)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda event: None)
    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    contents, structured = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_status",
        {**selector, "response_profile": "compact", "max_response_tokens": 3200},
    ))
    actual = json.loads(contents[0].text)
    assert actual["hub_online"] is (not degraded)
    assert "runtime_stats" not in actual
    assert "active_model" in actual
    assert actual["version"] == "4.0.0"
    assert actual["success"] is (not degraded)
    assert actual["degraded"] is degraded
    assert validate_operation_output("local_ai_status", "brief", actual) is None
    assert structured == actual


def test_scheduler_status_extra_field_is_bounded_and_explains_visible_blockers():
    result = mcp_server._compact_scheduler_status({
        "background_allowed": False,
        "gpu_admission_state": "available",
        "foreground_inflight": 1,
        "foreground_queued": 2,
        "inflight_jobs": [{"prompt": "private prompt", "task_id": "private task"}],
        "pending_jobs": [{"path": "private/path.py"}],
    })

    assert result == {
        "available": True,
        "background_allowed": False,
        "foreground_inflight": 1,
        "foreground_queued": 2,
        "gpu_admission_state": "available",
        "visible_background_blockers": ["foreground_inflight", "foreground_queued"],
    }


def test_scheduler_status_without_visible_blocker_is_marked_incomplete():
    result = mcp_server._compact_scheduler_status({"background_allowed": False})

    assert result["background_allowed"] is False
    assert result["visible_background_blockers"] == []
    assert result["background_block_reason_incomplete"] is True
    assert mcp_server._compact_scheduler_status({}) == {
        "available": False,
        "error": "scheduler_status_unavailable",
    }


def test_status_exposes_scheduler_summary_only_when_requested(monkeypatch):
    payload = {
        "success": True,
        "hub_online": True,
        "version": "6.1.0",
        "ollama_online": True,
        "capabilities": {},
        "scheduler": {
            "background_allowed": False,
            "gpu_admission_state": "available",
            "foreground_queued": 1,
            "pending_jobs": [{"task_id": "private", "prompt": "private"}],
        },
    }

    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _: OperationalModeSnapshot("active", 0, None))
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda *_args, **_kwargs: dict(payload))
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    contents, structured = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_status",
        {"detail": "brief", "extra_fields": ["scheduler"], "response_profile": "compact", "max_response_tokens": 3200},
    ))
    actual = json.loads(contents[0].text)

    assert actual["scheduler"]["visible_background_blockers"] == ["foreground_queued"]
    assert "pending_jobs" not in actual["scheduler"]
    assert "private" not in json.dumps(actual["scheduler"])
    assert validate_operation_output("local_ai_status", "brief", actual) is None
    assert structured == actual
