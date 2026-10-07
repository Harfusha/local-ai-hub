from __future__ import annotations

from local_ai_hub import mcp_server
from local_ai_hub.operational_mode import set_operational_mode


def test_mcp_command_run_classifies_test_execution_as_heavy(monkeypatch):
    gate_calls = []

    def gate(action, *, requires_heavy_work=True):
        gate_calls.append((action, requires_heavy_work))
        if requires_heavy_work:
            return {
                "success": False,
                "error_code": "operational_mode_blocked",
                "action": action,
            }
        return None

    monkeypatch.setattr(mcp_server, "_operational_mode_rejection", gate)
    monkeypatch.setattr(mcp_server.FEATURES, "commands", False)

    result = mcp_server.local_ai_command(
        action="run",
        command="python -m pytest -q",
        cwd=".",
    )

    assert gate_calls == [("run", True)]
    assert result["error_code"] == "operational_mode_blocked"


def test_mcp_command_allows_lightweight_classification_in_gaming_but_blocks_run(
    monkeypatch, tmp_path,
):
    set_operational_mode(tmp_path, "gaming")
    monkeypatch.setattr(
        mcp_server, "configured_state_dir", lambda *_args, **_kwargs: tmp_path,
    )
    monkeypatch.setattr(mcp_server.FEATURES, "commands", False)

    cheap = mcp_server.local_ai_command(
        action="classify", command="git status --short", cwd=".",
    )
    heavy = mcp_server.local_ai_command(
        action="run", command="python -m pytest -q", cwd=".",
    )
    set_operational_mode(tmp_path, "maintenance")
    maintenance = mcp_server.local_ai_command(
        action="classify", command="git status --short", cwd=".",
    )

    assert cheap.get("unsupported") is True
    assert cheap.get("error_code") != "operational_mode_blocked"
    assert heavy["error_code"] == "operational_mode_blocked"
    assert maintenance["error_code"] == "operational_mode_blocked"
