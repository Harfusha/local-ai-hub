from __future__ import annotations

from local_ai_hub import mcp_server
from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
from local_ai_hub.operation_contracts import validate_operation_output


def test_successful_gpu_release_response_satisfies_mcp_output_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_server, "load_config", lambda: {})
    monkeypatch.setattr(mcp_server, "configured_state_dir", lambda _config: tmp_path)
    monkeypatch.setattr(ExternalGpuReservationStore, "release_with_consent", lambda *_args, **_kwargs: True)

    result = mcp_server.local_ai_coord(
        action="gpu_reservation_release",
        generation="generation-1",
        consent=True,
        audit_reason="test approved release",
    )

    assert result["success"] is True
    assert validate_operation_output("local_ai_coord", "gpu_reservation_release", result) is None


def test_authorized_current_release_response_satisfies_mcp_output_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_server, "load_config", lambda: {})
    monkeypatch.setattr(mcp_server, "configured_state_dir", lambda _config: tmp_path)
    monkeypatch.setattr(
        ExternalGpuReservationStore,
        "release_current_with_consent",
        lambda *_args, **_kwargs: True,
    )

    result = mcp_server.local_ai_coord(
        action="gpu_reservation_release_authorized",
        consent=True,
        audit_reason="operator authorized release without owner inspection",
    )

    assert result["success"] is True
    assert result["mutation_applied"] is True
    assert validate_operation_output(
        "local_ai_coord", "gpu_reservation_release_authorized", result,
    ) is None
