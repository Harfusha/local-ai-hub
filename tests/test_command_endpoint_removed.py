from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from local_ai_hub import http_route_registry, mcp_server
from local_ai_hub.client import HubClient


def test_command_execution_is_not_a_public_mcp_tool() -> None:
    source = Path(mcp_server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "local_ai_command" not in mcp_server._ALL_REGISTERED_TOOLS
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "local_ai_command"
        for node in tree.body
    )


def test_command_http_routes_are_not_registered() -> None:
    paths = (
        "/api/command",
        "/api/command/preflight",
        "/api/command/speculative-lint",
        "/api/command/daemon",
        "/api/command/lint_fix",
        "/api/command/http_probe",
        "/api/command/mock_server",
        "/api/command/diff_hunk_stage",
        "/api/command/flaky_detect",
        "/api/command/webhook_replay",
    )

    assert all(not http_route_registry.select_http_routes("POST", path) for path in paths)


def test_command_only_client_helpers_are_removed() -> None:
    assert not hasattr(HubClient, "mock_server")
    assert not hasattr(HubClient, "diff_hunk_stage")
    assert not hasattr(HubClient, "flaky_detect")
    assert not hasattr(HubClient, "webhook_replay")


@pytest.mark.parametrize("path", [
    "/api/command", "/api/command/preflight", "/api/command/speculative-lint",
    "/api/command/daemon", "/api/command/lint_fix", "/api/command/http_probe",
    "/api/command/mock_server", "/api/command/diff_hunk_stage",
    "/api/command/flaky_detect", "/api/command/webhook_replay",
    "/api/speculative-lint", "/api/daemon", "/api/lint_fix", "/api/http_probe",
    "/api/mock_server", "/api/diff_hunk_stage", "/api/flaky_detect", "/api/webhook_replay",
])
def test_retired_command_http_paths_reject_before_auth_body_or_execution(monkeypatch, path):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(services=SimpleNamespace()))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler._require_authorized = lambda: pytest.fail("retired route attempted authorization")
    handler._read_json = lambda: pytest.fail("retired route read request body")
    handler._begin_trace = lambda *args, **kwargs: pytest.fail("retired route started execution")
    responses = []
    handler._send = lambda status, payload: responses.append(status)

    handler.do_POST()

    assert responses == [404]


def test_status_returns_compact_readiness_only(monkeypatch) -> None:
    class FakeClient:
        def get(self, path: str) -> dict:
            assert path == "/api/live/status?light=1"
            return {
                "success": True,
                "hub_online": True,
                "ollama_online": True,
                "degraded": False,
                "scheduler": {"active_model": "qwen2.5-coder:7b", "queued": 5, "inflight": 2},
                "runtime_stats": {"generation_cache": {"hits": 999}},
                "observability": {"cache_hits": 999},
                "vram_balancer": {"pressure_level": "nominal", "context_budget_factor": 1.0},
            }

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    result = inspect.unwrap(mcp_server.local_ai_status)()

    assert result["success"] is True
    assert result["ollama_online"] is True
    assert result["active_model"] == "qwen2.5-coder:7b"
    assert result["vram_pressure"] == "nominal"
    assert "queued" not in result
    assert "inflight" not in result
    assert "cache_hits" not in result
    assert "generation_cache" not in result


def test_status_rejects_removed_detail_modes() -> None:
    result = inspect.unwrap(mcp_server.local_ai_status)(detail="cache")

    assert result["success"] is False
    assert "only brief" in result["error"]


def test_agent_prompts_do_not_advertise_removed_command_tool() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("AGENTS.md", "docs/INSTALL_PROMPT.md", "docs/UPDATE_PROMPT.md"):
        prompt = (root / relative).read_text(encoding="utf-8")
        assert "local_ai_command" not in prompt
        assert "/api/command" not in prompt
