from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Mapping

_request_id: ContextVar[str] = ContextVar("local_ai_request_id", default="")
_trace_id: ContextVar[str] = ContextVar("local_ai_trace_id", default="")
_agent: ContextVar[str] = ContextVar("local_ai_agent", default="")
_tenant: ContextVar[str] = ContextVar("local_ai_tenant", default="")
_observer: ContextVar[Any | None] = ContextVar("local_ai_debug_observer", default=None)
_efficiency_metadata: ContextVar[dict[str, Any]] = ContextVar("local_ai_token_efficiency", default={})


def set_context(*, request_id: str = "", trace_id: str = "", agent: str = "", tenant: str = "") -> tuple[Token, Token, Token, Token]:
    return (_request_id.set(request_id), _trace_id.set(trace_id or request_id), _agent.set(agent), _tenant.set(tenant))


def reset_context(tokens: tuple[Token, Token, Token, Token]) -> None:
    for var, token in zip((_request_id, _trace_id, _agent, _tenant), tokens):
        var.reset(token)


def set_observer(value: Any | None) -> Token:
    return _observer.set(value)


def reset_observer(token: Token) -> None:
    _observer.reset(token)


def observer() -> Any | None:
    return _observer.get()


def set_metadata(metadata: Mapping[str, Any] | None = None, **fields: Any) -> Token:
    """Set payload-free token metadata for the current request context."""
    from .token_accounting import token_efficiency_metadata

    value = dict(metadata or {})
    value.update(fields)
    return _efficiency_metadata.set(token_efficiency_metadata(value))


def reset_metadata(token: Token) -> None:
    _efficiency_metadata.reset(token)


def efficiency_metadata() -> dict[str, Any]:
    return dict(_efficiency_metadata.get())


# Descriptive aliases keep integrations free to choose either terminology.
set_efficiency_metadata = set_metadata
reset_efficiency_metadata = reset_metadata


def current() -> dict[str, Any]:
    value = {"request_id": _request_id.get(), "trace_id": _trace_id.get(), "agent": _agent.get(), "tenant": _tenant.get()}
    metadata = efficiency_metadata()
    if metadata:
        value["token_efficiency"] = metadata
    return value
