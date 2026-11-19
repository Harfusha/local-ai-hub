from __future__ import annotations

from typing import get_args

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import validate_operation_output


def test_successful_gpu_release_response_satisfies_mcp_output_contract(monkeypatch):
    seen = {}
    def post(path, payload, **kwargs):
        # Tool accounting may emit an independent telemetry POST after the
        # reservation response. Inspect the operation, not the last POST.
        if path == "/api/gpu-reservation":
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
        if path == "/api/gpu-reservation":
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


def test_orphaned_laya_capacity_release_is_advertised_and_generation_fenced(monkeypatch):
    seen = {}

    def post(path, payload, **kwargs):
        seen.update(path=path, payload=payload)
        return {"success": True, "mutation_applied": True, "lease_id": "lease-1", "generation": "generation-1"}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    result = mcp_server.local_ai_coord(
        action="gpu_capacity_lease_release",
        lease_id="lease-1",
        owner="laya-runtime:12345:deadbeef",
        generation="generation-1",
        consent=True,
        audit_reason="operator approved exact orphaned lease",
    )

    assert result["success"] is True, result
    assert seen["path"] == "/api/gpu-reservation"
    assert seen["payload"] == {
        "action": "release_laya_capacity_lease",
        "lease_id": "lease-1",
        "owner": "laya-runtime:12345:deadbeef",
        "generation": "generation-1",
        "consent": True,
        "audit_reason": "operator approved exact orphaned lease",
    }
    assert validate_operation_output("local_ai_coord", "gpu_capacity_lease_release", result) is None
    assert "gpu_capacity_lease_release" in get_args(mcp_server.CoordAction)
    assert "gpu_capacity_lease_release" in mcp_server._desc_coord()


def test_orphaned_scheduler_capacity_release_uses_exact_fenced_payload(monkeypatch):
    seen = {}

    def post(path, payload, **kwargs):
        seen.update(path=path, payload=payload)
        return {"success": True, "mutation_applied": True, "lease_id": "lease-2", "generation": "generation-2"}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    result = mcp_server.local_ai_coord(
        action="gpu_scheduler_capacity_lease_release",
        lease_id="lease-2",
        owner="scheduler-job:7",
        generation="generation-2",
        consent=True,
        audit_reason="operator approved exact stale scheduler lease",
    )

    assert result["success"] is True, result
    assert seen["path"] == "/api/gpu-reservation"
    assert seen["payload"] == {
        "action": "release_scheduler_capacity_lease",
        "lease_id": "lease-2",
        "owner": "scheduler-job:7",
        "generation": "generation-2",
        "consent": True,
        "audit_reason": "operator approved exact stale scheduler lease",
    }
    assert validate_operation_output("local_ai_coord", "gpu_scheduler_capacity_lease_release", result) is None
    assert "gpu_scheduler_capacity_lease_release" in get_args(mcp_server.CoordAction)
    assert "gpu_scheduler_capacity_lease_release" in mcp_server._desc_coord()


def test_scheduler_capacity_release_rejects_without_explicit_consent(monkeypatch):
    posted = []

    def post(path, payload, **kwargs):
        posted.append((path, payload))
        return {"success": False, "operation_not_started": True}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    result = mcp_server.local_ai_coord(
        action="gpu_scheduler_capacity_lease_release",
        lease_id="lease-2",
        owner="scheduler-job:7",
        generation="generation-2",
        consent=False,
        audit_reason="operator did not approve release",
    )

    assert result["success"] is False
    releases = [payload for path, payload in posted if path == "/api/gpu-reservation"]
    assert len(releases) == 1
    assert releases[0]["consent"] is False
