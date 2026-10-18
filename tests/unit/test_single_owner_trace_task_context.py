from __future__ import annotations

import inspect

import pytest

from local_ai_hub import trace_context
from local_ai_hub.task_context import build_context_request


def test_trace_context_tuple_and_projection_have_only_real_trace_metadata() -> None:
    tokens = trace_context.set_context(request_id="request-1", trace_id="trace-2", agent="agent-3")
    try:
        assert len(tokens) == 3
        assert trace_context.current() == {
            "request_id": "request-1", "trace_id": "trace-2", "agent": "agent-3"
        }
    finally:
        trace_context.reset_context(tokens)


def test_trace_context_retired_tenant_interfaces_are_removed() -> None:
    assert "tenant" not in inspect.signature(trace_context.set_context).parameters
    assert "tenant" not in inspect.signature(trace_context.scoped_context).parameters
    assert not hasattr(trace_context, "current_tenant")
    with pytest.raises(TypeError, match="tenant"):
        trace_context.set_context(tenant=None)


@pytest.mark.parametrize("value", [None, False, ""])
def test_trace_metadata_rejects_retired_tenant_fields_by_presence(value: object) -> None:
    with pytest.raises(ValueError, match="retired"):
        trace_context.set_metadata({"tenant": value})


def test_task_context_builder_has_no_tenant_parameter() -> None:
    assert "tenant" not in inspect.signature(build_context_request).parameters
    with pytest.raises(TypeError, match="tenant"):
        build_context_request({}, tenant="legacy")


@pytest.mark.parametrize("value", [None, False, ""])
def test_task_context_builder_rejects_retired_generic_identity(value: object) -> None:
    assert "identity" not in inspect.signature(build_context_request).parameters
    with pytest.raises(ValueError, match="identity"):
        build_context_request({"identity": value})


@pytest.mark.parametrize("value", [None, False, ""])
def test_task_context_payload_rejects_retired_fields_by_presence(value: object) -> None:
    with pytest.raises(ValueError, match="retired"):
        build_context_request({"tenant_scope": value})
