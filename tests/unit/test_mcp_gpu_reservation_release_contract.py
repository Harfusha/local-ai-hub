from __future__ import annotations

from typing import get_args

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import validate_operation_output


def test_successful_gpu_release_response_satisfies_mcp_output_contract(monkeypatch):
    seen = {}
    def post(path, payload, **kwargs):
        seen.update(path=path, payload=payload)
        return {"success": True, "mutation_applied": True, "generation": "generation-1"}
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    result = mcp_server.local_ai_coord(
        action="gpu_reservation_release",
        generation="generation-1",
        consent=True,
        audit_reason="test approved release",
    )

    assert result["success"] is True, result
    assert seen["path"] == "/api/gpu-reservation"
    assert seen["payload"]["action"] == "release"
    assert validate_operation_output("local_ai_coord", "gpu_reservation_release", result) is None


def test_authorized_current_release_response_satisfies_mcp_output_contract(monkeypatch):
    seen = {}
    def post(path, payload, **kwargs):
        seen.update(path=path, payload=payload)
        return {"success": True, "mutation_applied": True}
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    result = mcp_server.local_ai_coord(
        action="gpu_reservation_release_authorized",
        consent=True,
        audit_reason="operator authorized release without owner inspection",
    )

    assert result["success"] is True, result
    assert result["mutation_applied"] is True
    assert seen["path"] == "/api/gpu-reservation"
    assert seen["payload"]["action"] == "release_authorized"
    assert validate_operation_output(
        "local_ai_coord", "gpu_reservation_release_authorized", result,
    ) is None


def test_gpu_reservation_actions_are_advertised_in_high_profile_coord_schema():
    actions = {
        "gpu_reservation_status",
        "gpu_reservation_release",
        "gpu_reservation_release_authorized",
    }

    assert actions.issubset(set(mcp_server.FEATURES.supported_coord_actions()))
    assert actions.issubset(set(get_args(mcp_server.CoordAction)))

    description = mcp_server._desc_coord()
    assert all(action in description for action in actions)
    assert "owner-liveness preflight" in description
