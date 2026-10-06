from __future__ import annotations

from local_ai_hub import mcp_server


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
