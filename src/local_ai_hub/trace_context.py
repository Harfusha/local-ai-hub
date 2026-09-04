from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_request_id: ContextVar[str] = ContextVar("local_ai_request_id", default="")
_trace_id: ContextVar[str] = ContextVar("local_ai_trace_id", default="")
_agent: ContextVar[str] = ContextVar("local_ai_agent", default="")
_tenant: ContextVar[str] = ContextVar("local_ai_tenant", default="")
_observer: ContextVar[Any | None] = ContextVar("local_ai_debug_observer", default=None)


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


def current() -> dict[str, Any]:
    return {"request_id": _request_id.get(), "trace_id": _trace_id.get(), "agent": _agent.get(), "tenant": _tenant.get()}
