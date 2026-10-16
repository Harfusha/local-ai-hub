"""Durable submit identity is accessible through the canonical MCP schema."""

import pytest

from local_ai_hub.operation_contracts import (
    operation_tool_input_schema,
    validate_operation_arguments,
)


def test_submit_request_identity_is_declared_and_accepted():
    schema = operation_tool_input_schema("local_ai_task")
    assert schema["properties"]["request_id"]["type"] == "string"
    assert schema["additionalProperties"] is False
    assert validate_operation_arguments(
        "local_ai_task", "submit", {"task": "Summarize pinned context", "request_id": "submit-1"},
    ) is None


@pytest.mark.parametrize("invalid", [None, True, 1, [], {}])
def test_submit_identity_rejects_nonstring_values(invalid):
    assert validate_operation_arguments(
        "local_ai_task", "submit", {"task": "Summarize pinned context", "request_id": invalid},
    ) is not None


def test_submit_identity_cannot_be_ignored_by_another_action():
    assert validate_operation_arguments(
        "local_ai_task", "reason", {"task": "Reason over pinned context", "request_id": "submit-1"},
    ) is not None


def test_submit_keeps_unknown_arguments_rejected():
    assert validate_operation_arguments(
        "local_ai_task", "submit", {"task": "Summarize pinned context", "legacy_request_id": "submit-1"},
    ) is not None
