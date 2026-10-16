from contextvars import ContextVar

from local_ai_hub.trace_context import (
    current,
    efficiency_metadata,
    reset_context,
    reset_metadata,
    reset_observer,
    scoped_context,
    scoped_metadata,
    scoped_observer,
    set_context,
    set_metadata,
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
