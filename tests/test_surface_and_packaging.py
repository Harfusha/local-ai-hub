from __future__ import annotations

import ast
from pathlib import Path

from local_ai_hub import __version__
from local_ai_hub.config import load_config
from local_ai_hub.http_server import _is_client_disconnect

ROOT = Path(__file__).resolve().parents[1]


def test_compact_mcp_surface_is_exactly_eight_tools():
    source = (ROOT / "src" / "local_ai_hub" / "mcp_server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    tools = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute) and deco.func.attr == "tool":
                tools.append(node.name)
    assert len(tools) == 8
    assert set(tools) == {"local_ai_status", "local_ai_task", "local_ai_repo", "local_ai_rag", "local_ai_command", "local_ai_coord", "local_ai_artifact", "local_ai_work"}
    assert not (ROOT / "mcp" / "local_ai_mcp_full.py").exists()


def test_packaged_defaults_match_source_defaults():
    assert (ROOT / "defaults.toml").read_bytes() == (ROOT / "src" / "local_ai_hub" / "defaults.toml").read_bytes()


def test_shipping_agent_policy_advertises_compact_workflow():
    policy = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "local_ai_work" in policy
    assert "eight existing tools" in policy
    assert "seven existing tools" not in policy
    assert "qwen2.5-coder:1.5b" in policy


def test_version_and_disconnect_regressions(tmp_path: Path):
    assert __version__ == "3.0.0"
    assert _is_client_disconnect(BrokenPipeError()) is True
    assert _is_client_disconnect(ConnectionResetError()) is True
    assert _is_client_disconnect(ConnectionAbortedError()) is True
    p = tmp_path / "config.toml"
    p.write_text(f'[server]\nstate_dir="{(tmp_path / "state").as_posix()}"\n[hardware]\nprofile="cpu"\n', encoding="utf-8")
    cfg = load_config(str(p))
    assert Path(cfg["server"]["state_dir"]).resolve() == (tmp_path / "state").resolve()


def test_remote_bind_fails_closed_without_token():
    from local_ai_hub.http_server import validate_network_security
    import pytest
    validate_network_security({"server": {"bind": "127.0.0.1"}, "security": {}})
    with pytest.raises(RuntimeError):
        validate_network_security({"server": {"bind": "0.0.0.0"}, "security": {"allow_remote": False, "api_token": ""}})
    with pytest.raises(RuntimeError):
        validate_network_security({"server": {"bind": "0.0.0.0"}, "security": {"allow_remote": True, "api_token": "short"}})
    validate_network_security({"server": {"bind": "0.0.0.0"}, "security": {"allow_remote": True, "api_token": "0123456789abcdef"}})


def test_telemetry_summary_cache_is_reachable(tmp_path: Path):
    from local_ai_hub.telemetry import TelemetryStore
    store = TelemetryStore(tmp_path / "telemetry-state", enabled=True, flush_interval_seconds=0.01)
    try:
        first = store.summary(1)
        second = store.summary(1)
        assert first["enabled"] is True
        assert second == first
        assert 1 in store._summary_cache
    finally:
        store.close()


def test_telemetry_summary_exposes_request_and_signed_token_accounting(tmp_path: Path):
    from local_ai_hub.telemetry import TelemetryStore

    store = TelemetryStore(
        tmp_path / "telemetry-state",
        enabled=True,
        cloud_token_cost_usd_per_million=5.0,
        flush_interval_seconds=0.01,
    )
    try:
        store.record(event_type="inference", avoided_cloud_tokens=2_000_000, success=True, duration_ms=1)
        store.record_tool_accounting({
            "tool": "local_ai_repo",
            "gross_cloud_tokens_avoided_est": 2_000_000,
            "agent_protocol_tokens_est": 250_000,
            "agent_tool_request_tokens_est": 50_000,
            "agent_tool_response_tokens_est": 200_000,
            "net_cloud_token_delta_est": 1_750_000,
            "cloud_token_overhead_est": 0,
            "net_after_schema_token_delta_est": 1_700_000,
            "schema_adjusted_overhead_est": 0,
        })
        store.record_http(action="/api/delegate", status_code=200, success=True, duration_ms=2)
        store.flush(1.0)
        summary = store.summary(1)
        assert summary["http"]["requests"] == 1
        assert summary["context_tokens_avoided_est"] == 2_000_000
        assert summary["net_cloud_token_delta_est"] == 1_750_000
        assert summary["estimated_savings_usd"] == 8.75
        assert summary["cloud_token_cost_usd_per_million"] == 5.0
    finally:
        store.close()

def test_repo_cache_stale_root_and_none_result_are_structured():
    from local_ai_hub.services import LocalAIServices

    class _State:
        def __init__(self, fail: bool = False):
            self.fail = fail
        def fingerprint(self, root: str):
            if self.fail:
                raise ValueError(f"root directory does not exist: {root}")
            return {"fingerprint": "abc", "kind": "git"}

    class _Flight:
        def __init__(self, value):
            self.value = value
        def get_or_compute(self, key, compute):
            return self.value, False, False

    svc = object.__new__(LocalAIServices)
    svc.preprocessor = None
    svc.repo_state = _State(fail=True)
    svc.repo_flight = _Flight(None)
    stale = svc._repo_cached("context", "/deleted/repo", {}, lambda: None)
    assert stale["success"] is False
    assert stale["stale_root"] is True
    assert stale["error_type"] == "ValueError"

    svc.repo_state = _State(fail=False)
    svc.repo_flight = _Flight(None)
    empty = svc._repo_cached("context", "/repo", {}, lambda: None)
    assert empty["success"] is False
    assert empty["workspace_cache"]["operation"] == "context"


def test_hybrid_context_missing_root_is_explicitly_degraded(tmp_path: Path):
    from local_ai_hub.services import LocalAIServices
    svc = object.__new__(LocalAIServices)
    out = svc._hybrid_context(str(tmp_path / "gone"), "query", "tenant", None, 500)
    assert out["success"] is False
    assert out["stale_root"] is True
    assert out["degraded"] is True
    assert out["error_type"] == "ValueError"
