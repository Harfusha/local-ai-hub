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
