from contextvars import ContextVar

from local_ai_hub.trace_context import (
    clear_context,
    current,
    efficiency_metadata,
    observer,
    reset_context,
    reset_metadata,
    reset_observer,
    scoped_context,
    scoped_metadata,
    scoped_observer,
    set_context,
    set_metadata,
    set_observer,
)


def test_scoped_context_restores_outer_values_and_ignores_foreign_token() -> None:
    tokens = set_context(request_id="outer")
    try:
        with scoped_context(request_id="inner", tenant="tenant-a"):
            assert current()["request_id"] == "inner"
            assert current()["tenant"] == "tenant-a"
        assert current()["request_id"] == "outer"

        foreign = ContextVar("foreign").set("value")
        reset_context(foreign)
        reset_context(None)
        assert current()["request_id"] == "outer"
    finally:
        reset_context(tokens)


def test_scoped_observer_restores_prior_value() -> None:
    with scoped_observer("outer"):
        with scoped_observer(None) as observer:
            assert observer is None
        with scoped_observer("inner") as observer:
            assert observer == "inner"


def test_scoped_metadata_restores_prior_value_and_none_reset_is_safe() -> None:
    token = set_metadata(parent_task="outer")
    try:
        with scoped_metadata(parent_task="inner") as metadata:
            assert metadata["parent_task"] == "inner"
        assert efficiency_metadata()["parent_task"] == "outer"
        reset_metadata(None)  # type: ignore[arg-type]
    finally:
        reset_metadata(token)

    assert efficiency_metadata() == {}


def test_context_identifiers_are_sanitized_and_clear_context_resets_state() -> None:
    tokens = set_context(
        request_id="req-1\x00poison\r\nline2",
        trace_id=12345,  # type: ignore[arg-type]
        agent="agent-alpha\t",
        tenant=None,  # type: ignore[arg-type]
    )
    observer_token = set_observer({"debug": True})
    metadata_token = set_metadata(parent_task="task-1")
    try:
        state = current()
        assert "\x00" not in state["request_id"]
        assert "\r" not in state["request_id"]
        assert "\n" not in state["request_id"]
        assert state["request_id"].startswith("req-1")
        assert state["trace_id"] == "12345"
        assert state["agent"] == "agent-alpha"
        assert state["tenant"] == ""
        assert observer() == {"debug": True}

        clear_context()

        assert current() == {"request_id": "", "trace_id": "", "agent": "", "tenant": ""}
        assert observer() is None
        assert efficiency_metadata() == {}
    finally:
        reset_metadata(metadata_token)
        reset_observer(observer_token)
        reset_context(tokens)
