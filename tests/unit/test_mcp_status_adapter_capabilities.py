"""MCP status must not advertise capabilities hidden by its own schema."""

from local_ai_hub.mcp_server import _effective_mcp_capabilities
from local_ai_hub import mcp_server
from local_ai_hub.features import FeatureSet


def test_backend_capabilities_are_intersected_with_adapter_configuration():
    backend = {
        "search_summaries": {"available": True, "state": "enabled_by_operator"},
        "semantic_analysis": {"available": True, "state": "enabled_by_operator"},
    }
    adapter = {
        "search_summaries": {"available": False, "state": "disabled_by_operator"},
        "semantic_analysis": {"available": True, "state": "enabled_by_operator"},
    }
    result = _effective_mcp_capabilities(backend, adapter)
    assert result["search_summaries"]["available"] is False
    assert result["search_summaries"]["reason"] == "disabled_in_mcp_adapter"
    assert result["semantic_analysis"]["available"] is True
    assert backend["search_summaries"]["available"] is True


def test_backend_unavailability_remains_authoritative():
    backend = {"search_summaries": {"available": False, "reason": "disabled_on_server"}}
    adapter = {"search_summaries": {"available": True}}
    assert _effective_mcp_capabilities(backend, adapter) == backend


def test_status_uses_adapter_capabilities_when_server_config_differs(monkeypatch):
    adapter = FeatureSet({"hardware": {"profile": "high"}, "features": {"search_summaries": False}})
    monkeypatch.setattr(mcp_server, "FEATURES", adapter)
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda *args, **kwargs: {
        "hub_online": True,
        "capabilities": {"search_summaries": {"available": True, "state": "enabled_by_operator"}},
    })
    result = mcp_server.local_ai_status()
    assert result["capabilities"]["search_summaries"]["available"] is False
    assert result["capabilities"]["search_summaries"]["reason"] == "disabled_in_mcp_adapter"


def test_generated_summary_guidance_defers_to_connected_adapter_schema():
    features = FeatureSet({"hardware": {"profile": "high"}, "features": {"search_summaries": True}})
    line = next(line for line in features.specialized_trigger_lines() if "summarize_results" in line)
    assert "connected MCP schema" in line
