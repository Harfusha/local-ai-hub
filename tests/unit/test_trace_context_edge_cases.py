from __future__ import annotations

import pytest

from local_ai_hub.trace_context import (
    clear_context,
    current,
    efficiency_metadata,
    metadata_scope,
    observer,
    observer_scope,
    reset_context,
    reset_metadata,
    reset_observer,
    set_context,
    trace_scope,
)


def test_set_context_sanitization_and_defensive_types() -> None:
    clear_context()
    # Non-string types, null-bytes, newlines
    tokens = set_context(
        request_id="req-1\x00poison\r\nline2",
        trace_id=12345,  # type: ignore[arg-type]
        agent="agent-alpha\t",
        tenant=None,  # type: ignore[arg-type]
    )
    try:
        ctx = current()
        assert "\x00" not in ctx["request_id"]
        assert "\r" not in ctx["request_id"]
        assert "\n" not in ctx["request_id"]
        assert ctx["request_id"].startswith("req-1")
        assert ctx["trace_id"] == "12345"
        assert ctx["agent"] == "agent-alpha"
        assert ctx["tenant"] == ""
    finally:
        reset_context(tokens)


def test_reset_context_defensive_against_malformed_tokens() -> None:
    # Malformed tokens must not raise TypeError or ValueError
    reset_context(None)
    reset_context([])
    reset_context(("invalid", "tokens", 1, 2))
    reset_observer(None)
    reset_observer("not-a-token")
    reset_metadata(None)
    reset_metadata(42)


def test_trace_scope_context_manager() -> None:
    clear_context()
    assert current()["request_id"] == ""
    assert current()["tenant"] == ""

    with trace_scope(request_id="scoped-req", tenant="tenant-xyz") as ctx:
        assert ctx["request_id"] == "scoped-req"
        assert ctx["tenant"] == "tenant-xyz"
        assert current()["request_id"] == "scoped-req"

    assert current()["request_id"] == ""
    assert current()["tenant"] == ""

    # Exception safety
    with pytest.raises(RuntimeError):
        with trace_scope(request_id="scoped-error", tenant="tenant-err"):
            assert current()["request_id"] == "scoped-error"
            raise RuntimeError("scope error")

    assert current()["request_id"] == ""
    assert current()["tenant"] == ""


def test_observer_and_metadata_scopes() -> None:
    clear_context()
    dummy_obs = {"id": "dummy-observer"}

    with observer_scope(dummy_obs):
        assert observer() is dummy_obs
    assert observer() is None

    with metadata_scope({"fanout_count": 3}):
        assert efficiency_metadata().get("fanout_count") == 3
    assert efficiency_metadata() == {}


def test_clear_context() -> None:
    set_context(request_id="temp-req", agent="temp-agent")
    clear_context()
    ctx = current()
    assert ctx["request_id"] == ""
    assert ctx["trace_id"] == ""
    assert ctx["agent"] == ""
    assert ctx["tenant"] == ""
