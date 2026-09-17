from __future__ import annotations

from local_ai_hub.response_budget import delta_response


def test_delta_response_returns_only_changed_fields_and_opaque_result_id() -> None:
    previous = {"success": True, "summary": "same", "items": ["old"], "removed": "gone"}
    current = {"success": True, "summary": "same", "items": ["new"], "added": "now"}

    result = delta_response(previous, current, result_id="abc123")

    assert result["success"] is True
    assert result["result_id"] == "abc123"
    assert result["delta"]["changed"] == {"items": ["new"]}
    assert result["delta"]["added"] == {"added": "now"}
    assert result["delta"]["removed"] == ["removed"]
