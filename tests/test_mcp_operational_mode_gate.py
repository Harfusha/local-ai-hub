from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub import mcp_server


def test_heavy_mcp_action_is_blocked_before_http_dispatch(monkeypatch) -> None:
    calls: list[str] = []

    def load_operational_mode(*, state_dir=None):
        calls.append(f"load:{state_dir}")
        return SimpleNamespace(mode="gaming", revision=7, degraded=False)

    def operational_mode_gate_error(snapshot, action, *, requires_heavy_work=True):
        calls.append(f"gate:{snapshot.mode}:{action}:{requires_heavy_work}")
        return {
            "success": False,
            "status_code": 423,
            "error_code": "operational_mode_blocked",
            "retry_after_seconds": 90,
            "terminal": True,
            "retryable": False,
        }

    def unexpected_post(*_args, **_kwargs):
        raise AssertionError("blocked MCP action reached HTTP dispatch")

    monkeypatch.setattr(mcp_server, "load_operational_mode", load_operational_mode, raising=False)
    monkeypatch.setattr(mcp_server, "operational_mode_gate_error", operational_mode_gate_error, raising=False)
    monkeypatch.setattr(mcp_server.CLIENT, "post", unexpected_post)

    result = mcp_server.local_ai_task(action="reason", task="bounded test")

    assert result["error_code"] == "operational_mode_blocked"
    assert result["retryable"] is True
    assert result["terminal"] is False
    assert result["retry_after_seconds"] == 30
    state_dir = (mcp_server.CFG.get("server", {}) or {}).get("state_dir")
    assert calls == [f"load:{state_dir}", "gate:gaming:reason:True"]


def test_artifact_read_bypasses_operational_mode_gate(monkeypatch) -> None:
    calls: list[str] = []

    def unexpected_load(**_kwargs):
        calls.append("load")
        raise AssertionError("cheap artifact read loaded operational mode")

    monkeypatch.setattr(mcp_server, "load_operational_mode", unexpected_load, raising=False)
    monkeypatch.setattr(mcp_server.FEATURES, "artifacts", True)
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda path, _payload: {"success": True, "path": path})
    monkeypatch.setattr(mcp_server, "_compact", lambda result, _tool: result)

    result = mcp_server.local_ai_artifact(action="list")

    assert result == {"success": True, "path": "/api/artifact/list"}
    assert calls == []


def test_missing_operational_mode_api_fails_closed_with_bounded_retry(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_mcp_operational_mode_api", lambda: (None, None))

    result = mcp_server._mcp_operational_mode_block(
        "local_ai_task", {"action": "reason"}
    )

    assert result is not None
    assert result["status_code"] == 503
    assert result["error_code"] == "operational_mode_unavailable"
    assert result["retryable"] is True
    assert result["terminal"] is False
    assert result["retry_after_seconds"] == 5


def test_coord_verification_receipt_is_classified_as_mutating() -> None:
    assert mcp_server._mcp_requires_heavy_work(
        "local_ai_coord", {"action": "verify_receipt"}
    ) is True
