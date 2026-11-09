import asyncio

import pytest

from local_ai_hub import mcp_server


@pytest.mark.parametrize("profile", ["minimal", "compact", "standard"])
def test_compact_api_spec_retains_endpoints_and_coverage(tmp_path, monkeypatch, profile):
    endpoints = [
        {"method": "GET", "path": f"/api/item/{i}", "handler": f"item_{i}", "file": "routes.py", "line": i + 1}
        for i in range(80)
    ]
    paths = {item["path"]: {"get": {"operationId": item["handler"], "responses": {"200": {"description": "Success"}}}} for item in endpoints}
    payload = {"success": True, "openapi": "3.0.0", "total_endpoints": len(endpoints),
               "paths": paths, "endpoints": endpoints}
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *_args, **_kwargs: payload)
    _, result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_repo", {"action": "api_spec", "root": str(tmp_path),
                          "response_profile": profile, "max_response_tokens": 1500},
    ))
    assert result["success"] is True, result
    assert result.get("total_endpoints") == len(endpoints), result
    assert result.get("endpoints"), result
    assert result.get("paths_omitted") is True, result
    assert len(result["endpoints"]) == len(endpoints) or result.get("response_budget", {}).get("truncated") is True, result


def test_empty_api_spec_preserves_explicit_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *_args, **_kwargs: {
        "success": True, "openapi": "3.0.0", "total_endpoints": 0, "paths": {}, "endpoints": [],
    })
    _, result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_repo", {"action": "api_spec", "root": str(tmp_path), "response_profile": "compact"},
    ))
    assert result["success"] is True, result
    assert result.get("total_endpoints") == 0, result


def test_small_api_spec_preserves_complete_paths(tmp_path, monkeypatch):
    item = {"method": "GET", "path": "/api/status", "handler": "status", "file": "routes.py", "line": 1}
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *_args, **_kwargs: {
        "success": True, "openapi": "3.0.0", "total_endpoints": 1,
        "paths": {"/api/status": {"get": {"operationId": "status"}}}, "endpoints": [item],
    })
    _, result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_repo", {"action": "api_spec", "root": str(tmp_path), "response_profile": "compact"},
    ))
    assert result["success"] is True
    assert result["total_endpoints"] == 1
    assert result["endpoints"] == [item]
    assert result["paths"] == {"/api/status": {"get": {"operationId": "status"}}}
    assert result.get("paths_omitted") is not True


@pytest.mark.parametrize("budget", [128, 256, 512])
def test_api_spec_tiny_budget_never_reports_empty_success(tmp_path, monkeypatch, budget):
    endpoints = [{"method": "GET", "path": f"/api/item/{i}", "handler": "handler", "file": "routes.py", "line": i + 1} for i in range(80)]
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *_args, **_kwargs: {
        "success": True, "total_endpoints": 80,
        "paths": {item["path"]: {"get": {"operationId": "handler"}} for item in endpoints},
        "endpoints": endpoints,
    })
    _, result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "api_spec", "root": str(tmp_path), "response_profile": "compact", "max_response_tokens": budget,
    }))
    assert result.get("success") is False or (result.get("total_endpoints") == 80 and result.get("endpoints") and result.get("paths_omitted") is True), result


def test_api_spec_long_endpoint_never_becomes_empty_success(tmp_path, monkeypatch):
    path = "/api/" + "x" * 4000
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *_args, **_kwargs: {
        "success": True, "total_endpoints": 1, "paths": {path: {"get": {}}},
        "endpoints": [{"method": "GET", "path": path, "file": "routes.py", "line": 1}],
    })
    _, result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "api_spec", "root": str(tmp_path), "response_profile": "compact", "max_response_tokens": 512,
    }))
    assert result.get("success") is False or (result.get("total_endpoints") == 1 and result.get("endpoints")), result


def test_api_spec_reports_endpoint_list_clipping(tmp_path, monkeypatch):
    endpoints = [{"method": "GET", "path": f"/r/{i}"} for i in range(60)]
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *_args, **_kwargs: {
        "success": True, "total_endpoints": 60, "paths": {}, "endpoints": endpoints,
    })
    _, result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "api_spec", "root": str(tmp_path), "response_profile": "compact",
    }))
    assert result["total_endpoints"] == 60
    assert len(result["endpoints"]) == 60 or result.get("truncated") is True or result.get("response_budget", {}).get("truncated") is True, result
