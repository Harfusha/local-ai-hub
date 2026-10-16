from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator, Mapping, Sequence

_request_id: ContextVar[str] = ContextVar("local_ai_request_id", default="")
_trace_id: ContextVar[str] = ContextVar("local_ai_trace_id", default="")
_agent: ContextVar[str] = ContextVar("local_ai_agent", default="")
_tenant: ContextVar[str] = ContextVar("local_ai_tenant", default="")
_observer: ContextVar[Any | None] = ContextVar("local_ai_debug_observer", default=None)
_efficiency_metadata: ContextVar[dict[str, Any] | None] = ContextVar("local_ai_token_efficiency", default=None)


def _sanitize_ident(value: Any, limit: int = 256) -> str:
    if value is None:
        return ""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("metadata limit must be a non-negative integer")
    text = value if isinstance(value, str) else str(value)
    return "".join(char for char in text if char >= " " and char != "\x7f").strip()[:limit]


def set_context(
    *,
    request_id: Any = "",
    trace_id: Any = "",
    agent: Any = "",
    tenant: Any = "",
) -> tuple[Token, Token, Token, Token]:
    request = _sanitize_ident(request_id)
    trace = _sanitize_ident(trace_id or request)
    agent_id = _sanitize_ident(agent)
    tenant_id = _sanitize_ident(tenant)
    return (_request_id.set(request), _trace_id.set(trace), _agent.set(agent_id), _tenant.set(tenant_id))


def reset_context(tokens: tuple[Token, Token, Token, Token] | Sequence[Token] | Token | None) -> None:
    if tokens is None:
        return
    variables = (_request_id, _trace_id, _agent, _tenant)
    if isinstance(tokens, Token):
        for variable in variables:
            try:
                variable.reset(tokens)
                return
            except (ValueError, RuntimeError):
                continue
        return
    for variable, token in zip(variables, tokens):
        if isinstance(token, Token):
            try:
                variable.reset(token)
            except (ValueError, RuntimeError):
                pass


@contextmanager
def scoped_context(
    *, request_id: str | None = "", trace_id: str | None = "", agent: str | None = "", tenant: str | None = ""
) -> Iterator[dict[str, Any]]:
    tokens = set_context(request_id=request_id, trace_id=trace_id, agent=agent, tenant=tenant)
    try:
        yield current()
    finally:
        reset_context(tokens)


def set_observer(value: Any | None) -> Token:
    return _observer.set(value)


def reset_observer(token: Token) -> None:
    if not isinstance(token, Token):
        return
    try:
        _observer.reset(token)
    except (ValueError, RuntimeError):
        pass


@contextmanager
def scoped_observer(value: Any | None) -> Iterator[Any | None]:
    token = set_observer(value)
    try:
        yield value
    finally:
        reset_observer(token)


def observer() -> Any | None:
    return _observer.get()


def set_metadata(metadata: Mapping[str, Any] | None = None, **fields: Any) -> Token:
    """Set payload-free token metadata for the current request context."""
    from .token_accounting import token_efficiency_metadata

    value = dict(metadata) if isinstance(metadata, Mapping) else {}
    value.update(fields)
    return _efficiency_metadata.set(token_efficiency_metadata(value))


def reset_metadata(token: Token) -> None:
    if not isinstance(token, Token):
        return
    try:
        _efficiency_metadata.reset(token)
    except (ValueError, RuntimeError):
        pass


@contextmanager
def scoped_metadata(metadata: Mapping[str, Any] | None = None, **fields: Any) -> Iterator[dict[str, Any]]:
    token = set_metadata(metadata, **fields)
    try:
        yield efficiency_metadata()
    finally:
        reset_metadata(token)


def efficiency_metadata() -> dict[str, Any]:
    metadata = _efficiency_metadata.get()
    return dict(metadata) if metadata is not None else {}


def has_context() -> bool:
    return bool(_request_id.get() or _trace_id.get())


def is_trace_active() -> bool:
    return bool(_trace_id.get())


def current_request_id() -> str:
    return _request_id.get()


def current_trace_id() -> str:
    return _trace_id.get()


def current_agent() -> str:
    return _agent.get()


def current_tenant() -> str:
    return _tenant.get()


def current() -> dict[str, Any]:
    value = {"request_id": _request_id.get(), "trace_id": _trace_id.get(), "agent": _agent.get(), "tenant": _tenant.get()}
    metadata = efficiency_metadata()
    if metadata:
        value["token_efficiency"] = metadata
    return value


def clear_context() -> None:
    """Clear trace, observer, and token-efficiency metadata in this context."""
    _request_id.set("")
    _trace_id.set("")
    _agent.set("")
    _tenant.set("")
    _observer.set(None)
    _efficiency_metadata.set(None)
