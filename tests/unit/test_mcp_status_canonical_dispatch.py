import pytest

from local_ai_hub import mcp_server


def test_readiness_uses_light_status_and_omits_internal_runtime_stats(monkeypatch):
    paths = []

    def get(path):
        paths.append(path)
        return {"hub_online": True, "version": "test", "ollama_online": True, "runtime_stats": {"repo_cache": {"entries": 7}}}

    monkeypatch.setattr(mcp_server.CLIENT, "get", get)
    monkeypatch.setattr(mcp_server, "_compact", lambda value, *args, **kwargs: value)
    result = mcp_server.local_ai_status.__wrapped__(detail="brief")
    assert paths == ["/api/live/status?light=1"]
    assert result["success"] is True
    assert result["version"] == "test"
    assert "runtime_stats" not in result
    assert "repo_cache" not in result


def test_readiness_preserves_valid_hardware_profile(monkeypatch):
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda _path: {
        "hub_online": True,
        "version": "test",
        "ollama_online": True,
        "hardware_profile": "high",
    })
    monkeypatch.setattr(mcp_server, "_compact", lambda value, *args, **kwargs: value)

    result = mcp_server.local_ai_status.__wrapped__(detail="brief")

    assert result["hardware_profile"] == "high"


def test_minimal_status_profile_preserves_declared_readiness_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_server, "CFG", {"server": {"state_dir": str(tmp_path)}})
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda *_args, **_kwargs: {
        "hub_online": True,
        "version": "7.0.0",
        "ollama_online": True,
        "hardware_profile": "integrated",
        "scheduler": {"active_model": None, "gpu_admission_state": "available"},
        "capabilities": {
            "search_summaries": {"available": False, "state": "profile_blocked", "minimum_profile": "balanced",
                                  "reason": "requires_balanced_profile"},
        },
    })

    result = mcp_server.local_ai_status(detail="brief", response_profile="minimal")

    assert result["success"] is True
    assert result["version"] == "7.0.0"
    assert result["ollama_online"] is True
    assert result["active_model"] is None
    assert result["degraded"] is False
    assert result["hardware_profile"] == "integrated"
    assert "capabilities" in result
    assert mcp_server.validate_operation_output("local_ai_status", "brief", result) is None


@pytest.mark.parametrize("delay", [0.25, 10])
def test_rate_limit_preserves_server_retry_after(monkeypatch, delay):
    routes = []

    def get(path):
        routes.append(path)
        return {"success": False, "status_code": 429, "retryable": True, "terminal": False,
                "retry_after_seconds": delay, "error": "rate limit exceeded; slow down"}

    monkeypatch.setattr(mcp_server.CLIENT, "get", get)
    result = mcp_server.local_ai_status.__wrapped__(detail="brief")

    assert routes == ["/api/live/status?light=1"]
    assert result["success"] is False
    assert result["status_code"] == 429
    assert result["retryable"] is True
    assert result["retry_after_seconds"] == delay


@pytest.mark.parametrize("delay", [-1, True, "10", float("inf"), float("nan"), None])
def test_readiness_omits_invalid_retry_after(monkeypatch, delay):
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda _path: {
        "success": False, "status_code": 429, "retryable": True,
        "retry_after_seconds": delay,
    })
    result = mcp_server.local_ai_status.__wrapped__(detail="brief")
    assert "retry_after_seconds" not in result


def test_compact_status_preserves_retry_delay(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_server, "CFG", {"server": {"state_dir": str(tmp_path)}})
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda *args, **kwargs: None)
    routes = []

    def get(path, **kwargs):
        routes.append(path)
        return {"success": False, "status_code": 429, "retryable": True, "terminal": False,
                "retry_after_seconds": 10, "error": "rate limit exceeded; slow down"}

    monkeypatch.setattr(mcp_server.CLIENT, "get", get)
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: pytest.fail("unexpected network request"))
    result = mcp_server.local_ai_status(detail="brief", max_response_tokens=1150, response_profile="compact")

    assert routes == ["/api/live/status?light=1"]
    assert result["status_code"] == 429
    assert result["retryable"] is True
    assert result["retry_after_seconds"] == 10
