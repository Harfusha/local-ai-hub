from __future__ import annotations

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import validate_operation_output


@pytest.mark.parametrize(
    "artifacts",
    [
        [],
        [
            {
                "artifact_id": "artifact-1",
                "kind": "text",
                "size_bytes": 12,
                "created_at": 1.0,
                "mime_type": "",
            }
        ],
    ],
)
def test_artifact_list_projection_preserves_contract_fields(monkeypatch, artifacts) -> None:
    response = {
        "success": True,
        "artifacts": artifacts,
    }
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda _path, _payload: response)

    actual = mcp_server.local_ai_artifact(action="list")
    error = validate_operation_output("local_ai_artifact", "list", actual)
    assert error is None, f"projected payload failed contract: {actual!r}; error={error!r}"


def test_artifact_list_does_not_normalize_items_alias(monkeypatch) -> None:
    response = {"success": True, "items": []}
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda _path, _payload: response)

    actual = mcp_server.local_ai_artifact(action="list")

    assert "artifacts" not in actual
    assert actual["success"] is False
    assert actual["failure_kind"] == "output_contract_violation"
    error = validate_operation_output("local_ai_artifact", "list", actual)
    assert error is None, "rejected noncanonical response must retain the canonical failure envelope"


def test_oversized_artifact_page_error_keeps_failure_contract(monkeypatch) -> None:
    response = {
        "success": True,
        "artifact_id": "artifact-1",
        "kind": "text",
        "text": "x" * 200,
        "offset": 0,
        "next_offset": 200,
        "total_chars": 200,
        "sections": [],
    }
    monkeypatch.setattr(mcp_server, "MAX_TEXT", 128)
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda _path, _payload: response)

    actual = mcp_server.local_ai_artifact(action="get", artifact_id="artifact-1")
    error = validate_operation_output("local_ai_artifact", "get", actual)
    assert error is None, f"oversized failure payload failed contract: {actual!r}; error={error!r}"
