from local_ai_hub import mcp_server


def test_cache_status_uses_detail_and_keeps_runtime_stats(monkeypatch):
    paths = []

    def get(path):
        paths.append(path)
        return {"hub_online": True, "runtime_stats": {"repo_cache": {"entries": 7}}}

    monkeypatch.setattr(mcp_server.CLIENT, "get", get)
    monkeypatch.setattr(mcp_server, "_compact", lambda value, *args, **kwargs: value)
    result = mcp_server.local_ai_status.__wrapped__(detail="cache")
    assert paths == ["/api/live/status?light=1&scope=process"]
    assert result["repo_cache"] == {"entries": 7}
